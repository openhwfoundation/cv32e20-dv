// Spike tandem support package for the CV32E20 "core" testbench.
//
// Copyright 2026 Eclipse Foundation
// SPDX-License-Identifier: Apache-2.0 WITH SHL-0.51
//
// This package provides the DPI-C imports and data types needed to run the
// Spike ISS in lock-step ("tandem") with the CV32E20 RTL.  The DPI functions
// are implemented in riscv_dpi.cc of the tandem-patched riscv-isa-sim that is
// vendored inside core-v-verif (see vendor_lib/openhwgroup_core-v-verif/
// vendor/riscv/riscv-isa-sim) and built into tools/spike/lib/libriscv.so by
// the 'spike_lib' target of mk/Common.mk.
//
// This is deliberately UVM-free so it can be used by the Verilator-based
// non-UVM core testbench.  It performs the same role as rvfi_spike.sv +
// uvma_rvfi_tdefs.sv in the UVM environment.
//
// IMPORTANT: st_rvfi below must match the C struct st_rvfi in riscv/Types.h
// of the vendored riscv-isa-sim *exactly*: 34 scalar uint64_t fields followed
// by six uint64_t[4096] arrays, no padding.  Every field is therefore 64 bits
// here, including 'mode' (the UVM-side uvma_rvfi_tdefs.sv declares mode as a
// 2-bit enum, which silently misaligns the SV view of the struct - do not
// copy that).
//
// The C side receives the packed struct as a flat array of 64-bit words in
// *reverse* order (an SV packed struct places the first-declared field in the
// most-significant bits) and un-reverses it in sv2rvfi()/rvfi2sv().  The CSR
// arrays end up index-reversed as well; Spike detects this via the
// "csr_addr[0x300] == 0x300" orientation probe (see INDEX_CSR in Proc.cc),
// so the SV side can simply read/write csr_*[csr_address] naturally as long
// as it sets csr_addr[12'h300] = 'h300 in every DUT-side struct it sends.

package spike_tandem_pkg;

  localparam int unsigned MAX_XLEN     = 64;
  localparam int unsigned CSR_MAX_SIZE = 4096;

  typedef struct packed {
    bit [MAX_XLEN-1:0] nret_id;
    bit [MAX_XLEN-1:0] cycle_cnt;
    bit [MAX_XLEN-1:0] order;
    bit [MAX_XLEN-1:0] insn;
    bit [MAX_XLEN-1:0] trap;
    bit [MAX_XLEN-1:0] halt;
    bit [MAX_XLEN-1:0] intr;
    bit [MAX_XLEN-1:0] mode;
    bit [MAX_XLEN-1:0] ixl;
    bit [MAX_XLEN-1:0] dbg;
    bit [MAX_XLEN-1:0] dbg_mode;
    bit [MAX_XLEN-1:0] nmip;

    bit [MAX_XLEN-1:0] insn_interrupt;
    bit [MAX_XLEN-1:0] insn_interrupt_id;
    bit [MAX_XLEN-1:0] insn_bus_fault;
    bit [MAX_XLEN-1:0] insn_nmi_store_fault;
    bit [MAX_XLEN-1:0] insn_nmi_load_fault;

    bit [MAX_XLEN-1:0] pc_rdata;
    bit [MAX_XLEN-1:0] pc_wdata;

    bit [MAX_XLEN-1:0] rs1_addr;
    bit [MAX_XLEN-1:0] rs1_rdata;

    bit [MAX_XLEN-1:0] rs2_addr;
    bit [MAX_XLEN-1:0] rs2_rdata;

    bit [MAX_XLEN-1:0] rs3_addr;
    bit [MAX_XLEN-1:0] rs3_rdata;

    bit [MAX_XLEN-1:0] rd1_addr;
    bit [MAX_XLEN-1:0] rd1_wdata;

    bit [MAX_XLEN-1:0] rd2_addr;
    bit [MAX_XLEN-1:0] rd2_wdata;

    bit [MAX_XLEN-1:0] mem_addr;
    bit [MAX_XLEN-1:0] mem_rdata;
    bit [MAX_XLEN-1:0] mem_rmask;
    bit [MAX_XLEN-1:0] mem_wdata;
    bit [MAX_XLEN-1:0] mem_wmask;

    bit [CSR_MAX_SIZE-1:0] [MAX_XLEN-1:0] csr_valid;
    bit [CSR_MAX_SIZE-1:0] [MAX_XLEN-1:0] csr_addr;
    bit [CSR_MAX_SIZE-1:0] [MAX_XLEN-1:0] csr_rdata;
    bit [CSR_MAX_SIZE-1:0] [MAX_XLEN-1:0] csr_rmask;
    bit [CSR_MAX_SIZE-1:0] [MAX_XLEN-1:0] csr_wdata;
    bit [CSR_MAX_SIZE-1:0] [MAX_XLEN-1:0] csr_wmask;
  } st_rvfi;

  localparam int unsigned ST_NUM_WORDS = $bits(st_rvfi) / MAX_XLEN;

  typedef bit [ST_NUM_WORDS-1:0] [MAX_XLEN-1:0] vector_rvfi;

  typedef union packed {
    st_rvfi     rvfi;
    vector_rvfi array;
  } union_rvfi;

  // Lifecycle (riscv_dpi.cc)
  import "DPI-C" function void spike_create(string filename);
  import "DPI-C" function void spike_delete();

  // Parameter plumbing (riscv_dpi.cc / Params.cc)
  import "DPI-C" function void spike_set_default_params(string profile);
  import "DPI-C" function void spike_set_param_uint64_t(string base, string name,
                                                        longint unsigned value);
  import "DPI-C" function void spike_set_param_str(string base, string name,
                                                   string value);
  import "DPI-C" function void spike_set_param_bool(string base, string name,
                                                    bit value);
  import "DPI-C" function longint unsigned spike_get_param_uint64_t(string base,
                                                                    string name);

  // Lock-step execution: steps Spike by one retired instruction.  'core' is
  // the DUT-side view (used for volatile CSR injection and, later, interrupt
  // injection); 'reference_model' returns Spike's view of the same step.
  import "DPI-C" function void spike_step_svLogic(inout vector_rvfi core,
                                                  inout vector_rvfi reference_model);

endpackage : spike_tandem_pkg
