// Wrapper for a CV32E20 "core" testbench,
// containing CV32E20, Memory and virtual peripherals.
//
// Copyright 2025 Eclipse Foundation
// SPDX-License-Identifier: Apache-2.0 WITH SHL-0.51
//
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

module cv32e20_tb_wrapper
    #(parameter // Parameters used by TB
                INSTR_RDATA_WIDTH = 32,
                RAM_ADDR_WIDTH    = 20,
                // Parameters used by DUT
                BOOT_ADDR         = 'h80,
                DM_HALTADDRESS    = 32'h1A11_0800,
                // Debug-exception entry address driven to the core's
                // dm_exception_addr_i.  Must match _debugger_exception_start in
                // bsp/link.ld (0x1A14_0000).  Previously this connected to an
                // *undeclared* identifier (DM_EXCEPTIONADDRESS), which Verilator
                // implicitly tied to 0 -- sending in-debug exceptions to PC 0.
                DM_EXCEPTIONADDRESS = 32'h1A14_0000,
                HART_ID           = 32'h0000_0000,
                MHPMCounterNum    = 10,
                MHPMCounterWidth  = 40,
                RV32E             = 1'b0,
                RV32M             = 2 // RV32MFast
    ) (
     input logic         clk_i,
     input logic         rst_ni,
     input logic         fetch_enable_i,

     output logic        tests_passed_o,
     output logic        tests_failed_o,
     output logic [31:0] exit_value_o,
     output logic        exit_valid_o);

    // signals connecting core to memory
    logic                         instr_req;
    logic                         instr_gnt;
    logic                         instr_rvalid;
    logic [31:0]                  instr_addr;
    logic [INSTR_RDATA_WIDTH-1:0] instr_rdata;

    logic                         data_req;
    logic                         data_gnt;
    logic                         data_rvalid;
    logic [31:0]                  data_addr;
    logic                         data_we;
    logic [3:0]                   data_be;
    logic [31:0]                  data_rdata;
    logic [31:0]                  data_wdata;

    // signals to debug unit
    logic                         debug_req;

`ifdef SPIKE_TANDEM
    // RVFI retirement interface from cve2_top (compile with +define+RVFI)
    logic        rvfi_valid;
    logic [63:0] rvfi_order;
    logic [31:0] rvfi_insn;
    logic        rvfi_trap;
    logic        rvfi_halt;
    logic        rvfi_intr;
    logic [ 1:0] rvfi_mode;
    logic [ 1:0] rvfi_ixl;
    logic [ 4:0] rvfi_rs1_addr;
    logic [ 4:0] rvfi_rs2_addr;
    logic [ 4:0] rvfi_rs3_addr;
    logic [31:0] rvfi_rs1_rdata;
    logic [31:0] rvfi_rs2_rdata;
    logic [31:0] rvfi_rs3_rdata;
    logic [ 4:0] rvfi_rd_addr;
    logic [31:0] rvfi_rd_wdata;
    logic [31:0] rvfi_pc_rdata;
    logic [31:0] rvfi_pc_wdata;
    logic [31:0] rvfi_mem_addr;
    logic [ 3:0] rvfi_mem_rmask;
    logic [ 3:0] rvfi_mem_wmask;
    logic [31:0] rvfi_mem_rdata;
    logic [31:0] rvfi_mem_wdata;
    logic [31:0] rvfi_ext_mip;
    logic        rvfi_ext_nmi;
    logic        rvfi_ext_debug_req;
    logic [63:0] rvfi_ext_mcycle;

    // Whitebox probes required for RVFI (aka cross-module references or XMRs).
    // Refer to reference/spike-tandem.md for details.

    // 'rvfi_intr' only exposed LSB and Spike tandem needs the full value.
    wire [8:0] rvfi_intr_cause = cv32e20_top_inst.u_cve2_core.rvfi_stage_intr[0];
    wire [3:0] rvfi_dbg_cause = cv32e20_top_inst.u_cve2_core.rvfi_stage_dbg[0];
    wire rvfi_dbg_mode = cv32e20_top_inst.u_cve2_core.rvfi_stage_dbg_mode[0];

    // Whitebox probe: actual bytes at rvfi_mem_addr in the testbench RAM's
    // backing store, read directly (same dp_ram_inst.mem[] hierarchical-
    // reference technique mm_ram.sv's ACT4 signature-dump logic already
    // uses). Feeds spike_tandem's post-write-landed check, independent of
    // the RTL's own RVFI self-report. Always driven; spike_tandem.sv gates
    // whether it's meaningful (store vs. not, in-range RAM vs. peripheral).
    wire [31:0] rvfi_mem_actual_wdata;
    assign rvfi_mem_actual_wdata[ 7: 0] = mm_ram_inst.dp_ram_inst.mem[rvfi_mem_addr + 0];
    assign rvfi_mem_actual_wdata[15: 8] = mm_ram_inst.dp_ram_inst.mem[rvfi_mem_addr + 1];
    assign rvfi_mem_actual_wdata[23:16] = mm_ram_inst.dp_ram_inst.mem[rvfi_mem_addr + 2];
    assign rvfi_mem_actual_wdata[31:24] = mm_ram_inst.dp_ram_inst.mem[rvfi_mem_addr + 3];
`endif

    // irq signals (driven from mm_ram virtual interrupt peripheral)
    logic [31:0]                  irq_from_mm_ram;
    logic [0:4]                   irq_id_in;
    logic                         irq_ack;
    logic                         irq_sec;

    // interrupts (only timer for now)
    assign irq_sec     = '0;

    // instantiate the core
    cve2_top #(
               .MHPMCounterNum   (10),
               .MHPMCounterWidth (40),
               .RV32E            (1'b0),
               .RV32M            () // RV32MFast
             )
    cv32e20_top_inst
        (
         .clk_i                  ( clk_i                 ),
         .rst_ni                 ( rst_ni                ),

         .test_en_i              ( '0                    ), // enable all clock gates for testing
         .ram_cfg_i              ( '0                    ), // prim_ram_1p_pkg::ram_1p_cfg_t RAM_1P_CFG_DEFAULT),

         .hart_id_i              ( HART_ID               ),
         .boot_addr_i            ( BOOT_ADDR             ),

         .instr_req_o            ( instr_req             ),
         .instr_gnt_i            ( instr_gnt             ),
         .instr_rvalid_i         ( instr_rvalid          ),
         .instr_addr_o           ( instr_addr            ),
         .instr_rdata_i          ( instr_rdata           ),
         .instr_err_i            ( 1'b0                  ),

         .data_req_o             ( data_req              ),
         .data_gnt_i             ( data_gnt              ),
         .data_rvalid_i          ( data_rvalid           ),
         .data_we_o              ( data_we               ),
         .data_be_o              ( data_be               ),
         .data_addr_o            ( data_addr             ),
         .data_wdata_o           ( data_wdata            ),
         .data_rdata_i           ( data_rdata            ),
         .data_err_i             ( 1'b0                  ),

         // Interrupts from mm_ram virtual interrupt peripheral
         // mip bit layout: MSI=3, MTI=7, MEI=11, fast/local=16..31
         .irq_software_i         ( irq_from_mm_ram[3]    ),
         .irq_timer_i            ( irq_from_mm_ram[7]    ),
         .irq_external_i         ( irq_from_mm_ram[11]   ),
         .irq_fast_i             ( irq_from_mm_ram[31:16]),
         .irq_nm_i               ( 1'b0                  ),       // non-maskeable interrupt

         .debug_req_i            ( debug_req             ),
         .dm_halt_addr_i         ( DM_HALTADDRESS        ),
         .dm_exception_addr_i    ( DM_EXCEPTIONADDRESS   ),
         .crash_dump_o           (                       ),

`ifdef SPIKE_TANDEM
         .rvfi_valid             ( rvfi_valid            ),
         .rvfi_order             ( rvfi_order            ),
         .rvfi_insn              ( rvfi_insn             ),
         .rvfi_trap              ( rvfi_trap             ),
         .rvfi_halt              ( rvfi_halt             ),
         .rvfi_intr              ( rvfi_intr             ),
         .rvfi_mode              ( rvfi_mode             ),
         .rvfi_ixl               ( rvfi_ixl              ),
         .rvfi_rs1_addr          ( rvfi_rs1_addr         ),
         .rvfi_rs2_addr          ( rvfi_rs2_addr         ),
         .rvfi_rs3_addr          ( rvfi_rs3_addr         ),
         .rvfi_rs1_rdata         ( rvfi_rs1_rdata        ),
         .rvfi_rs2_rdata         ( rvfi_rs2_rdata        ),
         .rvfi_rs3_rdata         ( rvfi_rs3_rdata        ),
         .rvfi_rd_addr           ( rvfi_rd_addr          ),
         .rvfi_rd_wdata          ( rvfi_rd_wdata         ),
         .rvfi_pc_rdata          ( rvfi_pc_rdata         ),
         .rvfi_pc_wdata          ( rvfi_pc_wdata         ),
         .rvfi_mem_addr          ( rvfi_mem_addr         ),
         .rvfi_mem_rmask         ( rvfi_mem_rmask        ),
         .rvfi_mem_wmask         ( rvfi_mem_wmask        ),
         .rvfi_mem_rdata         ( rvfi_mem_rdata        ),
         .rvfi_mem_wdata         ( rvfi_mem_wdata        ),
         .rvfi_ext_mip           ( rvfi_ext_mip          ),
         .rvfi_ext_nmi           ( rvfi_ext_nmi          ),
         .rvfi_ext_debug_req     ( rvfi_ext_debug_req    ),
         .rvfi_ext_mcycle        ( rvfi_ext_mcycle       ),
`endif

         // CPU Control Signals
         .fetch_enable_i         ( fetch_enable_i        ),
         .core_sleep_o           (                       )
       );

    // this handles read to RAM and memory mapped pseudo peripherals
    mm_ram
        #(.RAM_ADDR_WIDTH (RAM_ADDR_WIDTH),
          .INSTR_RDATA_WIDTH (INSTR_RDATA_WIDTH)
         )
    mm_ram_inst
        (.clk_i          ( clk_i                                     ),
         .rst_ni         ( rst_ni                                    ),
         .dm_halt_addr_i ( DM_HALTADDRESS                            ),

         .instr_req_i    ( instr_req                                 ),
         .instr_addr_i   ( instr_addr                                ),
         .instr_rdata_o  ( instr_rdata                               ),
         .instr_rvalid_o ( instr_rvalid                              ),
         .instr_gnt_o    ( instr_gnt                                 ),

         .data_req_i     ( data_req                                  ),
         .data_addr_i    ( data_addr                                 ),
         .data_we_i      ( data_we                                   ),
         .data_be_i      ( data_be                                   ),
         .data_wdata_i   ( data_wdata                                ),
         .data_rdata_o   ( data_rdata                                ),
         .data_rvalid_o  ( data_rvalid                               ),
         .data_gnt_o     ( data_gnt                                  ),

         .irq_id_i       ( irq_id_in                                 ),
         .irq_ack_i      ( irq_ack                                   ),
         .irq_o          ( irq_from_mm_ram                           ),

         .debug_req_o    ( debug_req                                 ),

         .pc_core_id_i   ( /*cv32e20_core_i.pc_id*/'0                ),

         .tests_passed_o ( tests_passed_o                            ),
         .tests_failed_o ( tests_failed_o                            ),
         .exit_valid_o   ( exit_valid_o                              ),
         .exit_value_o   ( exit_value_o                              )
        );

`ifdef SPIKE_TANDEM
    // Lock-step comparison of every retired instruction against Spike.
    spike_tandem
        #(.BOOT_ADDR (BOOT_ADDR),
          .HART_ID   (HART_ID)
         )
    spike_tandem_inst
        (.clk_i          ( clk_i          ),
         .rst_ni         ( rst_ni         ),
         .rvfi_valid     ( rvfi_valid     ),
         .rvfi_order     ( rvfi_order     ),
         .rvfi_insn      ( rvfi_insn      ),
         .rvfi_trap      ( rvfi_trap      ),
         .rvfi_halt      ( rvfi_halt      ),
         .rvfi_intr      ( rvfi_intr      ),
         .rvfi_mode      ( rvfi_mode      ),
         .rvfi_ixl       ( rvfi_ixl       ),
         .rvfi_rs1_addr  ( rvfi_rs1_addr  ),
         .rvfi_rs2_addr  ( rvfi_rs2_addr  ),
         .rvfi_rs1_rdata ( rvfi_rs1_rdata ),
         .rvfi_rs2_rdata ( rvfi_rs2_rdata ),
         .rvfi_rd_addr   ( rvfi_rd_addr   ),
         .rvfi_rd_wdata  ( rvfi_rd_wdata  ),
         .rvfi_pc_rdata  ( rvfi_pc_rdata  ),
         .rvfi_pc_wdata  ( rvfi_pc_wdata  ),
         .rvfi_mem_addr  ( rvfi_mem_addr  ),
         .rvfi_mem_rmask ( rvfi_mem_rmask ),
         .rvfi_mem_wmask ( rvfi_mem_wmask ),
         .rvfi_mem_rdata ( rvfi_mem_rdata ),
         .rvfi_mem_wdata ( rvfi_mem_wdata ),
         .rvfi_intr_cause( rvfi_intr_cause),
         .rvfi_ext_irq   ( irq_from_mm_ram),
         .rvfi_dbg_cause ( rvfi_dbg_cause ),
         .rvfi_dbg_mode  ( rvfi_dbg_mode  ),
         .rvfi_mem_actual_wdata ( rvfi_mem_actual_wdata )
        );
`endif

endmodule : cv32e20_tb_wrapper
