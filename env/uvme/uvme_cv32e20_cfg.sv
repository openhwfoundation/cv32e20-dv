// SPDX-License-Identifier: Apache-2.0 WITH SHL-2.1
//
// Copyright (c) 2025 Eclipse Foundation
// Copyright 2020,2022 OpenHW Group
// Copyright 2020 Datum Technology Corporation
// Copyright 2020 Silicon Labs, Inc.
//
// Licensed under the Solderpad Hardware Licence, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     https://solderpad.org/licenses/
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.


`ifndef __UVME_CV32E20_CFG_SV__
`define __UVME_CV32E20_CFG_SV__


/**
 * Object encapsulating all parameters for creating, connecting and running
 * CV32E20 environment (uvme_cv32e20_env_c) components.
 */
class uvme_cv32e20_cfg_c extends uvma_core_cntrl_cfg_c;

    rand int unsigned                sys_clk_period;
   // Random knobs
   rand bit                   zero_stall_sim; // Pinned to 1 by +rand_stall_obi_disable; expressed by zero_stall_sim_cons below
   bit                        max_data_zero_instr_stall; // state variable set by plusarg +max_data_zero_instr_stall
   bit                        max_both_stall; // state variable set by plusarg +max_both_stall

   rand longint unsigned fetch_initial_delay;

   // Agent cfg handles
   rand uvma_isacov_cfg_c     isacov_cfg;
   rand uvma_clknrst_cfg_c    clknrst_cfg;
   rand uvma_interrupt_cfg_c  interrupt_cfg;
   rand uvma_debug_cfg_c      debug_cfg;
   rand uvma_obi_memory_cfg_c obi_memory_instr_cfg;
   rand uvma_obi_memory_cfg_c obi_memory_data_cfg;

   rand uvma_rvfi_cfg_c#(ILEN,XLEN)       rvfi_cfg;

   longint unsigned vp_virtual_printer_symbol = 32'h1000_0000;
   longint unsigned vp_virtual_printer_legacy = 32'h1000_0000;
   longint unsigned vp_rand_num = 32'h1500_1000;
   longint unsigned vp_cycle_counter = 32'h1500_1004;
   longint unsigned vp_sig_writer = 32'h2000_0008;
   longint unsigned vp_status_flags_symbol = 32'h2000_0000;
   longint unsigned vp_status_flags_legacy = 32'h2000_0000;
   longint unsigned vp_interrupt_timer = 32'h1500_0000;
   longint unsigned vp_debug_control = 32'h1500_0008;

   // Objects
   // TODO Add scoreboard configuration handles
   //      Ex: rand uvml_sb_cfg_c  sb_egress_cfg;
   //          rand uvml_sb_cfg_c  sb_ingress_cfg;


   `uvm_object_utils_begin(uvme_cv32e20_cfg_c)
      `uvm_field_int (                         cov_model_enabled         , UVM_DEFAULT          )
      `uvm_field_int (                         trn_log_enabled           , UVM_DEFAULT          )
      `uvm_field_int (                         fetch_initial_delay       , UVM_DEFAULT          )
      `uvm_field_int (                         sys_clk_period            , UVM_DEFAULT + UVM_DEC)
      //`uvm_field_int (                         debug_clk_period            , UVM_DEFAULT + UVM_DEC)

      `uvm_field_object(isacov_cfg          , UVM_DEFAULT)
      `uvm_field_object(clknrst_cfg         , UVM_DEFAULT)
      `uvm_field_object(interrupt_cfg       , UVM_DEFAULT)
      `uvm_field_object(debug_cfg           , UVM_DEFAULT)
      `uvm_field_object(obi_memory_instr_cfg, UVM_DEFAULT)
      `uvm_field_object(obi_memory_data_cfg , UVM_DEFAULT)
      `uvm_field_object(rvfi_cfg            , UVM_DEFAULT)

      // TODO Add scoreboard cfg field macros
      //      Ex: `uvm_field_object(sb_egress_cfg , UVM_DEFAULT)
      //          `uvm_field_object(sb_ingress_cfg, UVM_DEFAULT)
   `uvm_object_utils_end


   constraint defaults_cons {
      soft enabled                == 0;
      soft is_active              == UVM_PASSIVE;
      soft scoreboard_enabled     == 1;
      soft cov_model_enabled      == 1;
      soft trn_log_enabled        == 1;
      soft sys_clk_period         == uvme_cv32e20_sys_default_clk_period; // see uvme_cv32e20_constants.sv
      //soft debug_clk_period       == uvme_cv32e20_debug_default_clk_period;
   }

constraint cve2_riscv_cons {
      xlen == uvma_core_cntrl_pkg::MXL_32;
      ilen == 32;

      mhartid                == 0;
      marchid                == 'd35;
      mvendorid              == 'h602;

      ext_i_supported        == 1;
      ext_a_supported        == 0;
      ext_m_supported        == 1;
      ext_c_supported        == 1;
      ext_p_supported        == 0;
      ext_v_supported        == 0;
      ext_f_supported        == 0;
      ext_d_supported        == 0;

      ext_zba_supported      == 0;
      ext_zbb_supported      == 0;
      ext_zbc_supported      == 0;

      ext_zbe_supported      == 0;
      ext_zbf_supported      == 0;
      ext_zbm_supported      == 0;
      ext_zbp_supported      == 0;
      ext_zbr_supported      == 0;
      ext_zbs_supported      == 1;
      ext_zbt_supported      == 0;
      ext_zifencei_supported == 1;
      ext_zicsr_supported    == 1;
      ext_zcb_supported      == 0;

      ext_cv32a60x_supported == 0;
      mode_s_supported       == 0;
      mode_u_supported       == 1;
      mode_h_supported       == 0;

      pmp_supported          == 0;
      debug_supported        == 1;

      unaligned_access_supported     == 1;
      unaligned_access_amo_supported == 0;

      bitmanip_version        == BITMANIP_VERSION_1P00;
      priv_spec_version       == PRIV_VERSION_MASTER;
      endianness              == ENDIAN_LITTLE;

      pmp_regions             == 8;
      boot_addr_valid         == 1;
      boot_addr               == 'h80000000;
      mtvec_addr_valid        == 1;
      dm_halt_addr_valid      == 1;
      dm_exception_addr_valid == 1;
      nmi_addr_valid          == 1;

      dram_valid              == 1;
      dram_base               == 'h10000000;
      dram_size               == 'hFFFF0000;

      fetch_initial_delay     == 30;
   }

   constraint zero_stall_sim_dist_cons {
      zero_stall_sim dist { 0 :/ 2,  1 :/ 1};
   }

   constraint zero_stall_sim_cons {
      if (zero_stall_sim) {
         obi_memory_instr_cfg.drv_slv_gnt_mode    == UVMA_OBI_MEMORY_DRV_SLV_GNT_MODE_CONSTANT;
         obi_memory_instr_cfg.drv_slv_rvalid_mode == UVMA_OBI_MEMORY_DRV_SLV_RVALID_MODE_CONSTANT;
         obi_memory_data_cfg.drv_slv_gnt_mode     == UVMA_OBI_MEMORY_DRV_SLV_GNT_MODE_CONSTANT;
         obi_memory_data_cfg.drv_slv_rvalid_mode  == UVMA_OBI_MEMORY_DRV_SLV_RVALID_MODE_CONSTANT;
      }
   }

   constraint max_data_zero_instr_stall_sim_cons {
      if (max_data_zero_instr_stall) {
         obi_memory_instr_cfg.drv_slv_gnt_mode    == UVMA_OBI_MEMORY_DRV_SLV_GNT_MODE_CONSTANT;
         obi_memory_instr_cfg.drv_slv_rvalid_mode == UVMA_OBI_MEMORY_DRV_SLV_RVALID_MODE_CONSTANT;

         obi_memory_data_cfg.drv_slv_gnt_mode    == UVMA_OBI_MEMORY_DRV_SLV_GNT_MODE_RANDOM_LATENCY;
         obi_memory_data_cfg.drv_slv_gnt_random_latency_min == 0;
         obi_memory_data_cfg.drv_slv_gnt_random_latency_max == 8;

         obi_memory_data_cfg.drv_slv_rvalid_mode == UVMA_OBI_MEMORY_DRV_SLV_RVALID_MODE_RANDOM_LATENCY;
         obi_memory_data_cfg.drv_slv_rvalid_random_latency_min == 0;
         obi_memory_data_cfg.drv_slv_rvalid_random_latency_max == 8;
      }
   }

   constraint max_both_stall_sim_cons {
      if (max_both_stall) {
         obi_memory_instr_cfg.drv_slv_gnt_mode    == UVMA_OBI_MEMORY_DRV_SLV_GNT_MODE_RANDOM_LATENCY;
         obi_memory_instr_cfg.drv_slv_gnt_random_latency_min == 0;
         obi_memory_instr_cfg.drv_slv_gnt_random_latency_max == 8;

         obi_memory_instr_cfg.drv_slv_rvalid_mode == UVMA_OBI_MEMORY_DRV_SLV_RVALID_MODE_RANDOM_LATENCY;
         obi_memory_instr_cfg.drv_slv_rvalid_random_latency_min == 0;
         obi_memory_instr_cfg.drv_slv_rvalid_random_latency_max == 8;

         obi_memory_data_cfg.drv_slv_gnt_mode    == UVMA_OBI_MEMORY_DRV_SLV_GNT_MODE_RANDOM_LATENCY;
         obi_memory_data_cfg.drv_slv_gnt_random_latency_min == 0;
         obi_memory_data_cfg.drv_slv_gnt_random_latency_max == 8;

         obi_memory_data_cfg.drv_slv_rvalid_mode == UVMA_OBI_MEMORY_DRV_SLV_RVALID_MODE_RANDOM_LATENCY;
         obi_memory_data_cfg.drv_slv_rvalid_random_latency_min == 0;
         obi_memory_data_cfg.drv_slv_rvalid_random_latency_max == 8;
      }
   }

   constraint agent_cfg_cons {
      if (enabled) {
         clknrst_cfg.enabled           == 1;
         interrupt_cfg.enabled         == 1;
         debug_cfg.enabled             == 1;
         obi_memory_instr_cfg.enabled  == 1;
         obi_memory_data_cfg.enabled   == 1;
         rvfi_cfg.enabled              == 1;
         rvfi_cfg.unified_csr_vif      == 1;
      }

      obi_memory_instr_cfg.version       == UVMA_OBI_MEMORY_VERSION_1P1;
      obi_memory_instr_cfg.drv_mode      == UVMA_OBI_MEMORY_MODE_SLV;
      obi_memory_instr_cfg.write_enabled == 0;
      obi_memory_instr_cfg.addr_width    == 32;
      obi_memory_instr_cfg.data_width    == 32;
      obi_memory_instr_cfg.id_width      == 0;
      obi_memory_instr_cfg.achk_width    == 0;
      obi_memory_instr_cfg.rchk_width    == 0;
      obi_memory_instr_cfg.auser_width   == 0;
      obi_memory_instr_cfg.ruser_width   == 0;
      obi_memory_instr_cfg.wuser_width   == 0;
      soft obi_memory_instr_cfg.drv_slv_gnt_random_latency_max    <= 2;
      soft obi_memory_instr_cfg.drv_slv_gnt_fixed_latency         <= 2;
      soft obi_memory_instr_cfg.drv_slv_rvalid_random_latency_max <= 3;
      soft obi_memory_instr_cfg.drv_slv_rvalid_fixed_latency      <= 3;

      obi_memory_data_cfg.version        == UVMA_OBI_MEMORY_VERSION_1P1;
      obi_memory_data_cfg.drv_mode       == UVMA_OBI_MEMORY_MODE_SLV;
      obi_memory_data_cfg.addr_width     == 32;
      obi_memory_data_cfg.data_width     == 32;
      obi_memory_data_cfg.id_width       == 0;
      obi_memory_data_cfg.achk_width     == 0;
      obi_memory_data_cfg.rchk_width     == 0;
      obi_memory_data_cfg.auser_width    == 0;
      obi_memory_data_cfg.ruser_width    == 0;
      obi_memory_data_cfg.wuser_width    == 0;
      soft obi_memory_data_cfg.drv_slv_gnt_random_latency_max    <= 2;
      soft obi_memory_data_cfg.drv_slv_gnt_fixed_latency         <= 2;
      soft obi_memory_data_cfg.drv_slv_rvalid_random_latency_max <= 3;
      soft obi_memory_data_cfg.drv_slv_rvalid_fixed_latency      <= 3;

      isacov_cfg.enabled                    == 1;
      isacov_cfg.seq_instr_group_x2_enabled == 1;
      isacov_cfg.seq_instr_group_x3_enabled == 1;
      isacov_cfg.seq_instr_group_x4_enabled == 0;
      isacov_cfg.seq_instr_x2_enabled       == 1;
      isacov_cfg.reg_crosses_enabled        == 0;
      isacov_cfg.reg_hazards_enabled        == 1;

      rvfi_cfg.nret                      == 1;
      unified_traps                      == 1;

      if (is_active == UVM_ACTIVE) {
         isacov_cfg.is_active            == UVM_PASSIVE;
         clknrst_cfg.is_active           == UVM_ACTIVE;
         interrupt_cfg.is_active         == UVM_ACTIVE;
         debug_cfg.is_active             == UVM_ACTIVE;
         obi_memory_instr_cfg.is_active  == UVM_ACTIVE;
         obi_memory_data_cfg.is_active   == UVM_ACTIVE;
      }

      if (trn_log_enabled) {
         clknrst_cfg.trn_log_enabled           == 1;
         interrupt_cfg.trn_log_enabled         == 1;
         debug_cfg.trn_log_enabled             == 1;
         isacov_cfg.trn_log_enabled            == 1;
         obi_memory_instr_cfg.trn_log_enabled  == 1;
         obi_memory_data_cfg.trn_log_enabled   == 1;
         rvfi_cfg.trn_log_enabled              == 1;
      }
      else{
         isacov_cfg.trn_log_enabled            == 0;
      }

      if (cov_model_enabled) {
         isacov_cfg.cov_model_enabled            == 1;
         obi_memory_instr_cfg.cov_model_enabled  == 1;
         obi_memory_data_cfg.cov_model_enabled   == 1;
      }

   }

   /**
    * Creates sub-configuration objects.
    */
   extern function new(string name="uvme_cv32e20_cfg");

   extern function void pre_randomize();

   extern virtual function void sample_parameters(uvma_core_cntrl_cntxt_c cntxt);

   /**
    * Set unsupported_csr_mask based on extensions/modes supported
    */
   extern virtual function void set_unsupported_csr_mask();
endclass : uvme_cv32e20_cfg_c


function uvme_cv32e20_cfg_c::new(string name="uvme_cv32e20_cfg");

   super.new(name);

   core_name             = "cve2";
   isacov_cfg           = uvma_isacov_cfg_c::type_id::create("isacov_cfg");
   clknrst_cfg           = uvma_clknrst_cfg_c   ::type_id::create("clknrst_cfg"         );
   interrupt_cfg         = uvma_interrupt_cfg_c ::type_id::create("interrupt_cfg"       );
   debug_cfg             = uvma_debug_cfg_c     ::type_id::create("debug_cfg"           );
   obi_memory_instr_cfg  = uvma_obi_memory_cfg_c::type_id::create("obi_memory_instr_cfg");
   obi_memory_data_cfg   = uvma_obi_memory_cfg_c::type_id::create("obi_memory_data_cfg" );

   rvfi_cfg              = uvma_rvfi_cfg_c#(ILEN,XLEN)::type_id::create("rvfi_cfg");

   isacov_cfg.core_cfg = this;
   rvfi_cfg.core_cfg = this;

endfunction : new

function void uvme_cv32e20_cfg_c::pre_randomize();

   `uvm_info("CFG", "Executing pre_randomize() of env cfg.", UVM_DEBUG)

   if ($test$plusargs("rand_stall_obi_disable")) begin
      zero_stall_sim = 1;
      zero_stall_sim.rand_mode(0);

      // Zero-stall is expressed by the zero_stall_sim_cons constraint alone.
      // The legacy uvmt_cv32e20_step_compare module, whose is_stall_sim bit an
      // earlier revision deposited a 0 into with uvm_hdl_deposit(), is neither
      // instantiated nor compiled into this testbench (tb/uvmt/
      // uvmt_cv32e20.flist lists only the step_compare_if interface), so the
      // deposit could only ever fail.
   end
   else if ($test$plusargs("max_data_zero_instr_stall")) begin
      // No stalls on the I bus, max on D bus
      max_data_zero_instr_stall = 1;
   end
   else if ($test$plusargs("max_both_stall")) begin
      // Randomized stalls (0-8 cycles) on both the I bus and D bus simultaneously
      max_both_stall = 1;
   end

endfunction : pre_randomize


function void uvme_cv32e20_cfg_c::sample_parameters(uvma_core_cntrl_cntxt_c cntxt);
//
//   uvma_cv32e20_core_cntrl_cntxt_c cv32e20_cntxt;
//
//   if (!$cast(cv32e20_cntxt, cntxt)) begin
//      `uvm_fatal("SAMPLECNTXT", "Could not cast cntxt to uvma_cva6_core_cntrl_cntxt_c");
//   end
//
endfunction : sample_parameters

function void uvme_cv32e20_cfg_c::set_unsupported_csr_mask();

   super.set_unsupported_csr_mask();

   // Remove unsupported CSRs for Embedded configuration
   unsupported_csr_mask[uvma_core_cntrl_pkg::MCOUNTINHIBIT] = 1;
   unsupported_csr_mask[uvma_core_cntrl_pkg::MTVAL] = 1;
   unsupported_csr_mask[uvma_core_cntrl_pkg::MTVAL2] = 1;
   unsupported_csr_mask[uvma_core_cntrl_pkg::MTINST] = 1;
   unsupported_csr_mask[uvma_core_cntrl_pkg::MSTATUSH] = 1;

endfunction : set_unsupported_csr_mask



`endif // __UVME_CV32E20_CFG_SV__

