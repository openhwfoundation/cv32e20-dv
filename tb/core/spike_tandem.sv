// Spike tandem checker for the CV32E20 "core" testbench.
//
// Copyright 2026 Eclipse Foundation
// SPDX-License-Identifier: Apache-2.0 WITH SHL-0.51
//
// Runs the Spike ISS in lock-step with the CV32E20: every time the core
// retires an instruction (RVFI handshake), Spike is stepped by one
// instruction and the architectural state changes reported by both models
// are compared.  Any divergence terminates the simulation with a report.
//
// Requirements:
//   - +elf_file=<path> plusarg pointing at the ELF of the loaded test-program
//     (the same program the testbench loads into mm_ram via +test_program).
//   - libriscv.so/libfesvr.so from the tandem-patched riscv-isa-sim on the
//     simulator's library path (built by 'make spike_lib', linked in by
//     SPIKE_TANDEM=1 in sim/core/Makefile).
//
// Known limitations:
//   - Loads from testbench virtual peripherals (e.g. the mm_ram timer) return
//     testbench-specific values that Spike cannot predict.
//   - Reads of free-running counter CSRs (cycle/mcycle/mip) are handled by
//     injecting the RTL value into Spike (csr_counters_injection).

module spike_tandem
  import spike_tandem_pkg::*;
  #(parameter logic [31:0] BOOT_ADDR = 32'h0000_4000,
    parameter logic [31:0] HART_ID   = 32'h0000_0000)
   (
    input logic        clk_i,
    input logic        rst_ni,

    // RVFI retirement interface from cve2_top
    input logic        rvfi_valid,
    input logic [63:0] rvfi_order,
    input logic [31:0] rvfi_insn,
    input logic        rvfi_trap,
    input logic        rvfi_halt,
    input logic        rvfi_intr,
    input logic [ 1:0] rvfi_mode,
    input logic [ 1:0] rvfi_ixl,
    input logic [ 4:0] rvfi_rs1_addr,
    input logic [ 4:0] rvfi_rs2_addr,
    input logic [31:0] rvfi_rs1_rdata,
    input logic [31:0] rvfi_rs2_rdata,
    input logic [ 4:0] rvfi_rd_addr,
    input logic [31:0] rvfi_rd_wdata,
    input logic [31:0] rvfi_pc_rdata,
    input logic [31:0] rvfi_pc_wdata,
    input logic [31:0] rvfi_mem_addr,
    input logic [ 3:0] rvfi_mem_rmask,
    input logic [ 3:0] rvfi_mem_wmask,
    input logic [31:0] rvfi_mem_rdata,
    input logic [31:0] rvfi_mem_wdata,

    // Whitebox probe from cv32e20_tb_wrapper.sv: cve2_core.sv's internal
    // rvfi_stage_intr[RVFI_STAGES-1], giving the interrupt/trap-entry tag and
    // mcause cause code that the top-level 1-bit rvfi_intr port truncates
    // away. {cause[5:0], 3'b101} = async interrupt entry, {cause[5:0],
    // 3'b011} = sync exception entry, 9'b0 otherwise.
    input logic [ 8:0] rvfi_intr_cause,

    // Raw external IRQ lines (cv32e20_tb_wrapper.sv's irq_from_mm_ram) --
    // used to independently verify mip instead of trusting the RTL's own
    // readback. See tandem_step().
    input logic [31:0] rvfi_ext_irq,

    // Whitebox probe of cve2_core.sv's internal rvfi_stage_dbg -- a one-shot
    // debug-entry cause tag used to inject debug-mode entry into Spike. See
    // tandem_step() and reference/spike-tandem.md.
    input logic [ 3:0] rvfi_dbg_cause,

    // Whitebox probe of the RTL's own debug_mode, for an independent
    // cross-check in compare_retirement() at every retirement (not just entry).
    input logic        rvfi_dbg_mode,

    // Whitebox probe from cv32e20_tb_wrapper.sv: actual bytes at
    // rvfi_mem_addr in the testbench RAM's backing store (dp_ram_inst.mem[]),
    // used to verify a store's write actually landed in memory -- see
    // compare_retirement() below.
    input logic [31:0] rvfi_mem_actual_wdata
   );

    // ID CSR values of the CV32E20.  Must match cve2_pkg.sv:
    //   CSR_MVENDORID_VALUE = {MVENDORID_BANK (25'hC), MVENDORID_OFFSET (7'h2)}
    //   CSR_MARCHID_VALUE   = 32'd35
    //   CSR_MIMPID_VALUE    = 32'b0
    localparam longint unsigned CVE2_MVENDORID = 64'h0000_0602;
    localparam longint unsigned CVE2_MARCHID   = 64'd35;
    localparam longint unsigned CVE2_MIMPID    = 64'h0;

    // Spike memory map: one sparse region from 0x0 covering the 4 MiB
    // testbench RAM, the CLINT-style timer (0x0200_xxxx), the print
    // peripheral (0x1000_0000), the timer/debug/random-stall peripherals
    // (0x15xx_xxxx/0x16xx_xxxx), the debugger sections (0x1A1x_xxxx) and the
    // test-status peripheral (0x2000_00xx).  mem_t allocates pages lazily, so
    // the large size costs only what the program actually touches.
    localparam longint unsigned SPIKE_DRAM_BASE = 64'h0;
    localparam longint unsigned SPIKE_DRAM_SIZE = 64'h2100_0000;

    string  id = "spike_tandem";
    string  elf_file;
    bit     trace_enable;
    longint unsigned step_count = 0;
    // Self-test: +tandem_inject_error=<n> corrupts the RTL-side rd write
    // value at retirement <n>, which must produce a TANDEM MISMATCH.
    longint unsigned inject_step = 0;
    logic [31:0]     inject_mask = '0;

    function automatic void spike_tandem_init();
        string base;
        base = $sformatf("/top/core/%0d/", HART_ID);

        if (!$value$plusargs("elf_file=%s", elf_file)) begin
            $display("[%s] ERROR: tandem verification requires +elf_file=<test-program>.elf", id);
            $fatal(2);
        end
        trace_enable = $test$plusargs("tandem_trace");
        if ($value$plusargs("tandem_inject_error=%d", inject_step)) begin
            $display("[%s] self-test: will corrupt rd_wdata at retirement %0d", id, inject_step);
        end

        void'(spike_set_default_params("cve2"));

        // ISA / privilege configuration (must match the RTL build): M-mode
        // only -- UmodeEnabled=0 in cve2_cs_registers.sv means no U bit.
        void'(spike_set_param_str("/top/", "isa", "rv32imc_zicsr_zifencei"));
        void'(spike_set_param_str(base,    "isa", "rv32imc_zicsr_zifencei"));
        void'(spike_set_param_str("/top/", "priv", "M"));
        void'(spike_set_param_str(base,    "priv", "M"));

        // Memory map (see localparams above).  The CVE2 has no boot ROM:
        // execution starts directly at {boot_addr[31:2], 2'b00}.
        void'(spike_set_param_bool    ("/top/", "bootrom",   1'b0));
        void'(spike_set_param_uint64_t("/top/", "dram_base", SPIKE_DRAM_BASE));
        void'(spike_set_param_uint64_t("/top/", "dram_size", SPIKE_DRAM_SIZE));
        void'(spike_set_param_uint64_t(base,    "boot_addr", {32'b0, BOOT_ADDR[31:2], 2'b00}));

        // CVE2 handles misaligned data accesses in hardware (no exception).
        void'(spike_set_param_bool("/top/", "misaligned", 1'b1));
        void'(spike_set_param_bool(base,    "misaligned", 1'b1));

        void'(spike_set_param_uint64_t("/top/", "num_procs", 64'h1));

        // ID CSRs.
        void'(spike_set_param_uint64_t(base, "mhartid_override_mask",    64'hFFFF_FFFF));
        void'(spike_set_param_uint64_t(base, "mhartid_override_value",   {32'b0, HART_ID}));
        void'(spike_set_param_uint64_t(base, "mvendorid_override_mask",  64'hFFFF_FFFF));
        void'(spike_set_param_uint64_t(base, "mvendorid_override_value", CVE2_MVENDORID));
        void'(spike_set_param_uint64_t(base, "marchid_override_mask",    64'hFFFF_FFFF));
        void'(spike_set_param_uint64_t(base, "marchid_override_value",   CVE2_MARCHID));
        void'(spike_set_param_uint64_t(base, "mimpid_override_mask",     64'hFFFF_FFFF));
        void'(spike_set_param_uint64_t(base, "mimpid_override_value",    CVE2_MIMPID));

        // mtvec: CVE2 resets it to {boot_addr[31:8], 6'b0, 2'b01} (vectored)
        // and writes update only [31:8] (low byte forced to 8'h01).  The
        // Spike ext-CSR write rule is new = (val & write_mask) | (curr &
        // ~write_mask), so a write mask of 0xFFFFFF00 preserves the reset
        // low byte.
        void'(spike_set_param_uint64_t(base, "mtvec_override_mask",  64'hFFFF_FFFF));
        void'(spike_set_param_uint64_t(base, "mtvec_override_value", {32'b0, BOOT_ADDR[31:8], 8'h01}));
        void'(spike_set_param_uint64_t(base, "mtvec_write_mask",     64'hFFFF_FF00));

        // mstatus reset value: MPP=M (0x1800), everything else 0.
        void'(spike_set_param_uint64_t(base, "mstatus_override_mask",  64'hFFFF_FFFF));
        void'(spike_set_param_uint64_t(base, "mstatus_override_value", 64'h0000_1800));
        // UmodeEnabled=0 hardwires MPRV/TW to 0 and clamps MPP to M, so
        // MIE/MPIE are the only bits software can actually change here --
        // mask Spike's writes down to match.
        void'(spike_set_param_uint64_t(base, "mstatus_write_mask",   64'h0000_0088));

        // Single trigger, tdata1 reset value per CVE2 (type=2 mcontrol,
        // dmode=1, maskmax=0x4, action/match bits per cve2_cs_registers).
        // Values copied from the proven cve2 profile in core-v-verif's
        // rvfi_spike.sv.
        void'(spike_set_param_uint64_t(base, "tdata1_override_mask",  64'hFFFF_FFFF));
        void'(spike_set_param_uint64_t(base, "tdata1_override_value", 64'h2800_1048));
        void'(spike_set_param_bool    (base, "tdata1_we",             1'b0));
        void'(spike_set_param_bool    (base, "tdata1_we_enable",      1'b1));
        void'(spike_set_param_bool    (base, "tinfo_presence",        1'b0));
        void'(spike_set_param_uint64_t(base, "trigger_count",         64'h1));

        // CVE2 interrupt lines do not follow the CLINT layout exactly.
        void'(spike_set_param_bool(base, "non_standard_interrupts", 1'b1));

        // Inject RTL values of free-running counters (cycle/mcycle/mip) into
        // Spike when the program reads them via CSR instructions.
        void'(spike_set_param_bool(base, "csr_counters_injection", 1'b1));

        void'(spike_set_param_bool(base, "interrupts_injection", 1'b1));
        // Without this, Proc::step() takes the trap (redirects pc to the
        // handler) but returns immediately without fetching the handler's
        // first instruction, leaving that instruction's rvfi info stale by
        // one DPI call relative to the RTL's single retirement.
        void'(spike_set_param_bool(base, "unified_traps",        1'b1));
        // Debug-mode entry injection: rvfi_dbg_cause (see tandem_step())
        // feeds reference->dbg, which Proc.cc already knows how to consume.
        void'(spike_set_param_bool(base, "debug_injection",      1'b1));

        // Run until the DUT stops retiring; never let Spike terminate first.
        void'(spike_set_param_bool("/top/", "max_steps_enabled", 1'b0));

        $display("[%s] starting Spike in tandem mode", id);
        $display("[%s]   elf_file  = %s",     id, elf_file);
        $display("[%s]   isa       = rv32imc_zicsr_zifencei (priv M)", id);
        $display("[%s]   boot_addr = 0x%08h", id, {BOOT_ADDR[31:2], 2'b00});
        spike_create(elf_file);
    endfunction : spike_tandem_init

    initial begin
        spike_tandem_init();
    end

    // Number of bytes a store touches, given its size-only RVFI mask
    // (4'b0001/4'b0011/4'b1111 -- always contiguous from bit 0).
    function automatic logic [31:0] store_size_bytes(logic [3:0] wmask);
        return (wmask == 4'b1111) ? 32'd4 : (wmask == 4'b0011) ? 32'd2 : 32'd1;
    endfunction

    // Compare one retirement against one Spike step.  Returns the number of
    // mismatching fields; prints one line per mismatch.
    function automatic int unsigned compare_retirement(const ref st_rvfi s_ref);
        int unsigned errors = 0;

        if (s_ref.pc_rdata[31:0] !== rvfi_pc_rdata) begin
            $display("[%s] MISMATCH pc:       rtl=0x%08h spike=0x%08h", id, rvfi_pc_rdata, s_ref.pc_rdata[31:0]);
            errors++;
        end

        // For compressed instructions Spike reports the 16-bit encoding;
        // the CVE2 RVFI zero-extends it the same way, so compare the
        // meaningful halfword only.
        if (rvfi_insn[1:0] != 2'b11) begin
            if (s_ref.insn[15:0] !== rvfi_insn[15:0]) begin
                $display("[%s] MISMATCH insn(c):  rtl=0x%04h spike=0x%04h", id, rvfi_insn[15:0], s_ref.insn[15:0]);
                errors++;
            end
        end else if (s_ref.insn[31:0] !== rvfi_insn) begin
            $display("[%s] MISMATCH insn:     rtl=0x%08h spike=0x%08h", id, rvfi_insn, s_ref.insn[31:0]);
            errors++;
        end

        if (s_ref.trap[0] !== rvfi_trap) begin
            $display("[%s] MISMATCH trap:     rtl=%0d spike=%0d (spike trap field 0x%0h)", id, rvfi_trap, s_ref.trap[0], s_ref.trap);
            errors++;
        end

        if (s_ref.mode[1:0] !== rvfi_mode) begin
            $display("[%s] MISMATCH mode:     rtl=%0d spike=%0d", id, rvfi_mode, s_ref.mode[1:0]);
            errors++;
        end

        // Cross-check debug-mode occupancy at every retirement (not just
        // entry) -- s_ref.dbg_mode is Proc.cc's own output, not forwarded.
        if (s_ref.dbg_mode[0] !== rvfi_dbg_mode) begin
            $display("[%s] MISMATCH dbg_mode: rtl=%0d spike=%0d", id, rvfi_dbg_mode, s_ref.dbg_mode[0]);
            errors++;
        end

        if (s_ref.rd1_addr[4:0] !== rvfi_rd_addr) begin
            $display("[%s] MISMATCH rd_addr:  rtl=x%0d spike=x%0d", id, rvfi_rd_addr, s_ref.rd1_addr[4:0]);
            errors++;
        end else if ((rvfi_rd_addr != 0) && (s_ref.rd1_wdata[31:0] !== (rvfi_rd_wdata ^ inject_mask))) begin
            $display("[%s] MISMATCH rd_wdata: rtl=0x%08h spike=0x%08h (rd=x%0d)", id, rvfi_rd_wdata ^ inject_mask, s_ref.rd1_wdata[31:0], rvfi_rd_addr);
            errors++;
        end

        // Store verification, part 1 of 2 (see Proc.cc for the independent
        // computation this compares against): the RTL's self-reported
        // rvfi_mem_addr/wmask/wdata vs. Spike's independently-computed
        // expected values -- verifies the core's address-generation/
        // operand-fetch datapath. s_ref.mem_wmask != 0 is the
        // store-happened gate; Proc.cc only sets it for a non-trapping
        // store.
        if (s_ref.mem_wmask[3:0] != 4'b0) begin
            if (s_ref.mem_addr[31:0] !== rvfi_mem_addr) begin
                $display("[%s] MISMATCH mem_addr:  rtl=0x%08h spike=0x%08h", id, rvfi_mem_addr, s_ref.mem_addr[31:0]);
                errors++;
            end
            if (s_ref.mem_wmask[3:0] !== rvfi_mem_wmask) begin
                $display("[%s] MISMATCH mem_wmask: rtl=0x%01h spike=0x%01h", id, rvfi_mem_wmask, s_ref.mem_wmask[3:0]);
                errors++;
            end
            if (s_ref.mem_wdata[31:0] !== rvfi_mem_wdata) begin
                $display("[%s] MISMATCH mem_wdata: rtl=0x%08h spike=0x%08h", id, rvfi_mem_wdata, s_ref.mem_wdata[31:0]);
                errors++;
            end

            // Part 2 of 2: compare the RAM's actual byte contents at the
            // store address (rvfi_mem_actual_wdata, a hierarchical
            // readback wired in cv32e20_tb_wrapper.sv) against Spike's
            // expected write bytes -- same ground truth as part 1,
            // deliberately NOT rvfi_mem_wdata, so a bug that corrupts both
            // the RTL's self-report and the real bus identically still
            // can't hide. This is the only one of the two checks that
            // exercises the real OBI/LSU byte-rotation path -- part 1's
            // RVFI signals are captured pre-LSU and bypass it entirely.
            // Gated to the real testbench RAM range; peripherals have no
            // backing dp_ram_inst.mem[] entries.
            if ((s_ref.mem_addr[31:0] + store_size_bytes(s_ref.mem_wmask[3:0])) <= 32'h0040_0000) begin
                for (int b = 0; b < 4; b++) begin
                    if (s_ref.mem_wmask[b] &&
                        (rvfi_mem_actual_wdata[b*8 +: 8] !== s_ref.mem_wdata[b*8 +: 8])) begin
                        $display("[%s] MISMATCH mem_landed byte%0d @0x%08h: ram=0x%02h spike=0x%02h",
                                 id, b, rvfi_mem_addr + b,
                                 rvfi_mem_actual_wdata[b*8 +: 8], s_ref.mem_wdata[b*8 +: 8]);
                        errors++;
                    end
                end
            end
        end

        return errors;
    endfunction : compare_retirement

    function automatic void tandem_step();
        union_rvfi   u_core;
        union_rvfi   u_ref;
        st_rvfi      s_core;
        st_rvfi      s_ref;
        int unsigned errors;

        s_core = '0;
        s_core.nret_id   = 64'h0;
        s_core.order     = rvfi_order;
        s_core.insn      = {32'b0, rvfi_insn};
        s_core.trap      = {63'b0, rvfi_trap};
        s_core.halt      = {63'b0, rvfi_halt};
        s_core.mode      = {62'b0, rvfi_mode};
        s_core.ixl       = {62'b0, rvfi_ixl};
        s_core.pc_rdata  = {32'b0, rvfi_pc_rdata};
        s_core.pc_wdata  = {32'b0, rvfi_pc_wdata};
        s_core.rs1_addr  = {59'b0, rvfi_rs1_addr};
        s_core.rs1_rdata = {32'b0, rvfi_rs1_rdata};
        s_core.rs2_addr  = {59'b0, rvfi_rs2_addr};
        s_core.rs2_rdata = {32'b0, rvfi_rs2_rdata};
        s_core.rd1_addr  = {59'b0, rvfi_rd_addr};
        s_core.rd1_wdata = {32'b0, rvfi_rd_wdata};
        s_core.mem_addr  = {32'b0, rvfi_mem_addr};
        s_core.mem_rdata = {32'b0, rvfi_mem_rdata};
        s_core.mem_rmask = {60'b0, rvfi_mem_rmask};
        s_core.mem_wdata = {32'b0, rvfi_mem_wdata};
        s_core.mem_wmask = {60'b0, rvfi_mem_wmask};

        // Asynchronous-interrupt injection: Proc.cc::step() looks at
        // reference->intr (this struct) and, when its low 3 bits read
        // 3'b101, reads reference->csr_rdata[CSR_MCAUSE] to convert mcause
        // into a backdoor mip write so Spike takes the same interrupt the
        // RTL just did. rvfi_intr_cause carries cve2_core's internal
        // {mcause[5:0], tag} for this retirement (see cv32e20_tb_wrapper.sv);
        // tag==3'b101 is an interrupt entry, 3'b011 a synchronous exception
        // entry (left at s_core.intr=0 -- Spike detects those on its own by
        // executing the same instruction stream).
        if (rvfi_intr_cause[2:0] == 3'b101) begin
            s_core.intr             = 64'h5;
            s_core.csr_rdata[12'h342] = {32'b0, 1'b1, 25'b0, rvfi_intr_cause[8:3]};
        end

        // Independent mip verification: mip is a pure combinational
        // reflection of the external IRQ lines (MSIP=bit3, MTIP=bit7,
        // MEIP=bit11, fast=bits[31:16], CVE2's CSR_M*IX_BIT layout).
        // Trusting the RTL's own readback would make this tautological, so
        // smuggle the raw pre-DUT IRQ lines into csr_rdata[CSR_MIP] the same
        // way rvfi_intr_cause smuggles mcause above; Proc.cc uses this
        // instead of forwarding mip from the reference.
        s_core.csr_rdata[12'h344] = {32'b0, (rvfi_ext_irq & 32'hFFFF_0888)};

        // Debug-mode entry injection: Proc.cc::step() reads reference->dbg
        // and, when nonzero, calls enter_debug_mode() with this cause.
        // rvfi_dbg_cause is a one-shot tag, zero except on the entry
        // retirement -- only the async haltreq cause needs forwarding;
        // ebreak/step entries are already self-contained in Spike.
        s_core.dbg = {60'b0, rvfi_dbg_cause};

        // Orientation probe: Proc.cc detects the packed-struct word reversal
        // by checking csr_addr[0x300] (see INDEX_CSR).
        s_core.csr_addr[12'h300] = 64'h300;

        u_core.rvfi = s_core;
        u_ref       = '0;
        spike_step_svLogic(u_core.array, u_ref.array);
        s_ref       = u_ref.rvfi;

        step_count++;
        inject_mask = (inject_step != 0 && step_count == inject_step) ? 32'h8000_0000 : '0;

        if (trace_enable) begin
            $display("[%s] step %0d: pc=0x%08h insn=0x%08h rd=x%0d rd_wdata=0x%08h trap=%0d",
                     id, step_count, rvfi_pc_rdata, rvfi_insn, rvfi_rd_addr, rvfi_rd_wdata, rvfi_trap);
        end

        errors = compare_retirement(s_ref);
        if (errors != 0) begin
            $display("[%s] @ t=%0t: TANDEM MISMATCH at retirement %0d (%0d field(s) differ)", id, $time, step_count, errors);
            $display("[%s]   rtl:   pc=0x%08h insn=0x%08h rd=x%0d rd_wdata=0x%08h trap=%0d mode=%0d",
                     id, rvfi_pc_rdata, rvfi_insn, rvfi_rd_addr, rvfi_rd_wdata ^ inject_mask, rvfi_trap, rvfi_mode);
            $display("[%s]   spike: pc=0x%08h insn=0x%08h rd=x%0d rd_wdata=0x%08h trap=%0d mode=%0d",
                     id, s_ref.pc_rdata[31:0], s_ref.insn[31:0], s_ref.rd1_addr[4:0], s_ref.rd1_wdata[31:0], s_ref.trap[0], s_ref.mode[1:0]);
            $fatal(2, "[%s] tandem verification FAILED", id);
        end
    endfunction : tandem_step

    always @(posedge clk_i) begin
        if (rst_ni && rvfi_valid) begin
            tandem_step();
        end
    end

    final begin
        $display("[%s] %0d instructions verified in tandem with Spike", id, step_count);
        spike_delete();
    end

endmodule : spike_tandem
