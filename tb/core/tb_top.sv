// Top level testbench for the CV32E20
//
// Copyright 2025 Eclipse Foundation
// SPDX-License-Identifier: Apache-2.0 WITH SHL-0.51
//
// Copyright 2017 Embecosm Limited <www.embecosm.com>
// Copyright 2018 Robert Balas <balasr@student.ethz.ch>
// Copyright and related rights are licensed under the Solderpad Hardware
// License, Version 0.51 (the "License"); you may not use this file except in
// compliance with the License.  You may obtain a copy of the License at
// http://solderpad.org/licenses/SHL-0.51. Unless required by applicable law
// or agreed to in writing, software, hardware and materials distributed under
// this License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
// CONDITIONS OF ANY KIND, either express or implied. See the License for the
// specific language governing permissions and limitations under the License.

// Contributor: Robert Balas <balasr@student.ethz.ch>
//              Jeremy Bennett <jeremy.bennett@embecosm.com>

module tb_top;

    const int CLK_PHASE_HI        = 5;
    const int CLK_PHASE_LO        = 5;
    const int CLK2NRESET_DELAY    = 1;
    const int RESET_ASSERT_CYCLES = 4;

    // top-level localparams to be passed down to all submodules
    localparam int          INSTR_RDATA_WIDTH   = 32;
    localparam int          RAM_ADDR_WIDTH      = 22;
    localparam int          DBG_ADDR_WIDTH      = 18;
    // The boot-address of the CVE2 must be 256-byte aligned and must match start of text block in bsp/link.ld
    // Raised from 'h2000 to satisfy .align 14 in I-jal test (ACT4)
    localparam logic [31:0] BOOT_ADDR           = 'h4000;
    // Debugger memory remap parameters.  The debugger sections are linked at
    // high addresses (.debugger @0x1A11_0800, .debugger_exception/.stack
    // @0x1A14_0000) that lie far outside the RAM array.  mm_ram remaps run-time
    // accesses in the window [DM_HALTADDRESS, DM_HALTADDRESS + 2**DBG_ADDR_WIDTH)
    // to the top of RAM; the program loader below must apply the identical
    // remap so the loaded image matches what the core fetches/accesses.
    // NOTE: DM_HALTADDRESS and DBG_ADDR_WIDTH must match mm_ram.
    // TODO: clean up memory model in testbench to eliminate the need to remap debug memory region.
    localparam logic [31:0] DM_HALTADDRESS      = 32'h1A11_0800;  // must match .debugger in bsp/link.ld
    localparam logic [31:0] DM_EXCEPTIONADDRESS = 32'h1A14_0000;  // must match .debugger_exception in bsp/link.ld


    // clock and reset for tb
    logic                   core_clk;
    logic                   core_rst_n;

    // CPU control signals
    logic                   fetch_enable;

    // cycle counter
    int unsigned            cycle_cnt_q;

    // exit status flags
    logic                   tests_passed;
    logic                   tests_failed;
    logic                   exit_valid;
    logic [31:0]            exit_value;

    // strings for $display() and plusarg processing
    string id = "tb_top";
    string wave_file;

    // dumps waves
    initial begin
        if ($value$plusargs("wave_file=%s", wave_file)) begin
            $display("[%s] @ t=%0t: dumping waves to %s", id, $time, wave_file);
            $dumpfile(wave_file);
            $dumpvars(0, tb_top);
        end
    end

    // seed management
    initial begin
        int current_seed;
        current_seed = $get_initial_random_seed();
        $display("[%s] @ t=%0t: Simulation running with seed: %0d", id, $time, current_seed);
    end

    // Remap a byte address exactly as mm_ram does (see instr_addr_remap and
    // setup_transaction in mm_ram.sv).  Debug-window addresses are relocated to
    // the top of RAM; all others are truncated to the RAM array width.
    // TODO: clean up memory model in testbench to eliminate the need to remap debug memory region.
    function automatic int unsigned remap_load_addr(input logic [31:0] a);
        if ((a >= DM_HALTADDRESS) && (a < (DM_HALTADDRESS + (1 << DBG_ADDR_WIDTH))))
            remap_load_addr = (a - DM_HALTADDRESS) + (1 << RAM_ADDR_WIDTH) - (1 << DBG_ADDR_WIDTH);
        else
            remap_load_addr = a & ((1 << RAM_ADDR_WIDTH) - 1);
    endfunction

    // Load the provided firmware (Verilog-hex from objcopy -O verilog).  A plain
    // $readmemh cannot be used because it writes the file's absolute addresses
    // directly into the array and aborts on the out-of-bounds debugger sections.
    // Instead we parse the hex ourselves and apply the debug-region remap.
    initial begin: load_prog
        automatic string test_program;
        int          fd;
        string       tok;
        logic [31:0] cur_addr;
        logic [31:0] byte_val;
        int          n_bytes;

        if($value$plusargs("test_program=%s", test_program)) begin
            if($test$plusargs("verbose"))
                $display("[%s] @ t=%0t: loading test-program %0s", id, $time, test_program);

            fd = $fopen(test_program, "r");
            if (fd == 0) begin
                $display("[%s] @ t=%0t: ERROR: cannot open test-program %0s", id, $time, test_program);
                $fatal(2);
            end

            cur_addr = '0;
            n_bytes  = 0;
            // Read whitespace-separated tokens: "@<hex>" sets the byte address,
            // every other token is one hex byte written at the (remapped) address.
            while ($fscanf(fd, "%s", tok) == 1) begin
                if (tok.getc(0) == "@") begin
                    void'($sscanf(tok, "@%h", cur_addr));
                end else begin
                    void'($sscanf(tok, "%h", byte_val));
                    cv32e20_tb_wrapper_inst.mm_ram_inst.dp_ram_inst.mem[remap_load_addr(cur_addr)] = byte_val[7:0];
                    cur_addr = cur_addr + 1;
                    n_bytes  = n_bytes + 1;
                end
            end
            $fclose(fd);

            if($test$plusargs("verbose"))
                $display("[%s] @ t=%0t: loaded %0d bytes (debug region remapped to top of RAM)",
                         id, $time, n_bytes);
        end else begin
            $display("[%s] @ t=%0t: No test_program specified... terminating.", id, $time);
            end_of_sim();
        end
    end

    initial begin: clock_gen
        core_clk = 1'b1;
        // FIXME: using a forever loop here hangs Verilator
        repeat(10_000_000) begin
            #CLK_PHASE_HI core_clk = 1'b0;
            #CLK_PHASE_LO core_clk = 1'b1;
        end
    end: clock_gen


    // timing format, reset generation and parameter check
    initial begin
        $timeformat(-9, 0, "ns", 9);
        core_rst_n   = 1'b1; // deassert reset at t=0
        fetch_enable = 1'b0; // deassert fetch-enable (for now)

        @(negedge core_clk) core_rst_n = 1'b0; // assert reset
        // hold in reset for a few cycles
        repeat (RESET_ASSERT_CYCLES) @(posedge core_clk);
        // start running
        #CLK2NRESET_DELAY core_rst_n = 1'b1;
        core_rst_n = 1'b1;
        if($test$plusargs("verbose")) begin
            $display("[%s] @ t=%0t: reset deasserted", id, $time);
        end

        // wait a few cycles
        repeat (RESET_ASSERT_CYCLES) @(posedge core_clk);
        // assert fetch-enable
        #CLK2NRESET_DELAY fetch_enable = 1'b1;
        if($test$plusargs("verbose")) begin
            $display("[%s] @ t=%0t: fetch-enable asserted", id, $time);
        end

        if ( !( (INSTR_RDATA_WIDTH == 128) || (INSTR_RDATA_WIDTH == 32) ) ) begin
         $fatal(2, "[%s] @ t=%0t: invalid INSTR_RDATA_WIDTH, choose 32 or 128", id, $time);
        end
    end

    // abort after n cycles, if we want to
    always_ff @(posedge core_clk, negedge core_rst_n) begin
        automatic int maxcycles;
        if($value$plusargs("maxcycles=%d", maxcycles)) begin
            if (~core_rst_n) begin
                cycle_cnt_q <= 0;
            end else begin
                cycle_cnt_q     <= cycle_cnt_q + 1;
                if (cycle_cnt_q >= maxcycles) begin
                    $fatal(2, "[%s] @ t=%0t: Simulation aborted due to maximum cycle limit", id, $time);
                end
            end
        end
    end

    // Check for virtual peripheral status flags that the test-program may (or
    // may not) use to indicate the end of a test.
    always_ff @(posedge core_clk) begin: vp_check
        if (tests_passed) begin
            $display("[%s] @ t=%0t: ALL TESTS PASSED", id, $time);
            end_of_sim();
        end
        if (tests_failed) begin
            $display("[%s] @ t=%0t: TEST(S) FAILED!", id, $time);
            end_of_sim();
        end
        if (exit_valid) begin
            if (exit_value == 0)
                $display("[%s] @ %0t: EXIT SUCCESS", id, $time);
            else
                $display("[%s] @ %0t: EXIT FAILURE: %d", id, $time, exit_value);
            end_of_sim();
        end
    end

    // End Of Simulation control:
    //   - If the test-program invokes the virtual peripheral status flags
    //     (see 'vp_check' block, above) then end_of_sim() is called and it
    //     will trigger the 'final' block.
    //   - If the test-program invokes the C stdlib macro EXIT_SUCCESS or
    //     EXIT_FAILURE, then the simulation process is terminated and
    //     end_of_sim() is never called.  In this case the 'final' block
    //     is used to display the end of simulation messages, if any.
    task end_of_sim();
        $finish;
    endtask

    final begin
        if (wave_file != "") begin
            $display("[%s] @ t=%0t: waves written to %s", id, $time, wave_file);
        end
        $display("\n[%s] @ t=%0t: Verilator simulation ending...", id, $time);
    end

    // wrapper for cv32e20, the memory and virtual peripherals.
    cv32e20_tb_wrapper
        #(
          // Parameters used by TB
          .INSTR_RDATA_WIDTH   (INSTR_RDATA_WIDTH),
          .RAM_ADDR_WIDTH      (RAM_ADDR_WIDTH),
          // Parameters used by DUT
          .BOOT_ADDR           (BOOT_ADDR),
          .DM_HALTADDRESS      (DM_HALTADDRESS),
          .DM_EXCEPTIONADDRESS (DM_EXCEPTIONADDRESS),
          .MHPMCounterNum      (10),
          .MHPMCounterWidth    (40),
          .RV32E               (1'b0),
          .RV32M               (2/*RV32MFast*/)
         )
    cv32e20_tb_wrapper_inst
        (
         .clk_i          ( core_clk     ),
         .rst_ni         ( core_rst_n   ),
         .fetch_enable_i ( fetch_enable ),
         .tests_passed_o ( tests_passed ),
         .tests_failed_o ( tests_failed ),
         .exit_valid_o   ( exit_valid   ),
         .exit_value_o   ( exit_value   )
        );

endmodule // tb_top
