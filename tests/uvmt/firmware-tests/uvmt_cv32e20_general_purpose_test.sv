//
// Copyright 2022 OpenHW Group
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
//

// SPDX-License-Identifier: Apache-2.0 WITH SHL-2.1


`ifndef __UVMT_CV32E20_GENERAL_PURPOSE_TEST_SV__
`define __UVMT_CV32E20_GENERAL_PURPOSE_TEST_SV__


/**
 *  CV32E20 "general purpose firmware" test.
 *  This class relies on a pre-existing "firmware" file written in C and/or RISC-V assembly code.
 *  The "firmware" can be either manually written or machine generated.
 */
class uvmt_cv32e20_general_purpose_test_c extends uvmt_cv32e20_base_test_c;

   constraint test_type_cons {
     test_cfg.tpt == GENERAL_PURPOSE;
   }

   `uvm_component_utils_begin(uvmt_cv32e20_general_purpose_test_c)
   `uvm_object_utils_end

   /**
    */
   extern function new(string name="uvmt_cv32e20_general_purpose_test", uvm_component parent=null);


   /*
   *  Override types with the UVM Factory
   */
   extern virtual function void build_phase(uvm_phase phase);

   /**
    *  Enable program execution, wait for completion.
    */
   extern virtual task run_phase(uvm_phase phase);

   /**
   * Start random debug sequencer
   */
    extern virtual task random_debug();

    extern virtual task reset_debug();

    extern virtual task bootset_debug();
   /**
    *  Start the interrupt sequencer to apply random interrupts during test
    */
   extern virtual task irq_noise();

   /**
    *  Deterministically assert NMI (irq_mask[0]) once, after a bounded
    *  random delay. See uvme_cv32e20_nmi_assert_vseq.sv.
    */
   extern virtual task nmi_assert();

   /**
    *  Drop reset once in the middle of the running program, after a bounded
    *  random delay. See uvme_cv32e20_mid_run_reset_vseq.sv.
    */
   extern virtual task mid_run_reset();

   /**
    *  Pulse and withdraw the NMI line repeatedly. See
    *  uvme_cv32e20_irq_withdraw_vseq.sv.
    */
   extern virtual task irq_withdraw();

   /**
    *  Randomly assert/deassert fetch_enable_i
    */
   extern virtual task random_fetch_toggle();

endclass : uvmt_cv32e20_general_purpose_test_c


function uvmt_cv32e20_general_purpose_test_c::new(string name="uvmt_cv32e20_general_purpose_test", uvm_component parent=null);

   super.new(name, parent);
   `uvm_info("TEST", "This is the GENERAL PURPOSE FIRMWARE UVM_TEST", UVM_NONE)

endfunction : new

task uvmt_cv32e20_general_purpose_test_c::run_phase(uvm_phase phase);

   // start_clk() and watchdog_timer() are called in the base_test
   super.run_phase(phase);

   // The RVFI Agent needs to be writting to it AP, otherwise the reference
   // model and ISA functional coverage model have nothing to proces.
   env.rvfi_agent.instr_monitor.cfg.ap_write_en = 1;
   `uvm_info("TEST", "Writing to RVFI Agent's instruction monitor Analysis Port enabled", UVM_NONE)

   if ($test$plusargs("gen_random_debug")) begin
    fork
      random_debug();
    join_none
   end

   if ($test$plusargs("gen_irq_noise")) begin
    fork
      irq_noise();
    join_none
   end

   if ($test$plusargs("nmi_assert")) begin
    fork
      nmi_assert();
    join_none
   end

   if ($test$plusargs("mid_run_reset")) begin
    fork
      mid_run_reset();
    join_none
   end

   if ($test$plusargs("irq_withdraw")) begin
    fork
      irq_withdraw();
    join_none
   end

   if ($test$plusargs("random_fetch_toggle")) begin
     fork
       random_fetch_toggle();
     join_none
   end

   if ($test$plusargs("reset_debug")) begin
    fork
      reset_debug();
    join_none
   end
   if ($test$plusargs("debug_boot_set")) begin
    fork
      bootset_debug();
    join_none
   end

   phase.raise_objection(this);
   `uvm_info("TEST", "run_phase has raised objection...", UVM_HIGH)
   // The firmware is expected to write exit status and pass/fail indication to the Virtual Peripheral
   wait (
          (vp_status_vif.exit_valid    == 1'b1) ||
          (vp_status_vif.tests_failed  == 1'b1) ||
          (vp_status_vif.tests_passed  == 1'b1)
        );
   repeat (100) @(posedge env_cntxt.clknrst_cntxt.vif.clk);
   //TODO: exit_value will not be valid - need to add a latch in the vp_status_vif
   begin
       string mystr = "Finished run_phase:\n";
       mystr = {mystr,$sformatf("              exit_value  is %0h\n", vp_status_vif.exit_value)};
       mystr = {mystr,$sformatf("              exit_valid  is %0h\n", vp_status_vif.exit_valid)};
       mystr = {mystr,$sformatf("              test_failed is %0h\n", vp_status_vif.tests_failed)};
       mystr = {mystr,$sformatf("              test_passed is %0h\n", vp_status_vif.tests_passed)};
       `uvm_info("TEST", $sformatf("%s", mystr), UVM_DEBUG)
   end
   phase.drop_objection(this);
   `uvm_info("TEST", "run_phase has dropped objection...", UVM_HIGH)

endtask : run_phase

task uvmt_cv32e20_general_purpose_test_c::reset_debug();
    uvme_cv32e20_random_debug_reset_c debug_vseq;
    debug_vseq = uvme_cv32e20_random_debug_reset_c::type_id::create("random_debug_reset_vseqr", vsequencer);
    `uvm_info("TEST", "Applying debug_req_i at reset", UVM_NONE);
    @(negedge env_cntxt.clknrst_cntxt.vif.reset_n);

    if (!debug_vseq.randomize()) begin
        `uvm_fatal("TEST", "Cannot randomize the debug sequence!")
    end
    debug_vseq.start(vsequencer);

endtask

function void uvmt_cv32e20_general_purpose_test_c::build_phase(uvm_phase phase);
       super.build_phase(phase);

       `uvm_info("TEST", "Overriding Reference Model with Spike", UVM_NONE)
       set_type_override_by_type(uvmc_rvfi_reference_model#()::get_type(),uvmc_rvfi_spike#()::get_type());

endfunction : build_phase

task uvmt_cv32e20_general_purpose_test_c::bootset_debug();
    uvme_cv32e20_random_debug_bootset_c debug_vseq;
    debug_vseq = uvme_cv32e20_random_debug_bootset_c::type_id::create("random_debug_bootset_vseqr", vsequencer);
    `uvm_info("TEST", "Applying single cycle debug_req after reset", UVM_NONE);
    @(negedge env_cntxt.clknrst_cntxt.vif.reset_n);

    // Delay debug_req_i by up to 35 cycles.Should hit BOOT_SET
    if (!test_randvars.randomize() with { random_int inside {[1:35]}; }) begin
        `uvm_fatal("TEST", "Cannot randomize test_randvars for debug_req_delay!")
    end
    repeat(test_randvars.random_int) @(posedge env_cntxt.clknrst_cntxt.vif.clk);

    if (!debug_vseq.randomize()) begin
        `uvm_fatal("TEST", "Cannot randomize the debug sequence!")
    end
    debug_vseq.start(vsequencer);

endtask

task uvmt_cv32e20_general_purpose_test_c::random_debug();
    `uvm_info("TEST", "Starting random debug in thread UVM test", UVM_NONE)

    while (1) begin
        uvme_cv32e20_random_debug_c debug_vseq;
        repeat (100) @(env_cntxt.debug_cntxt.vif.mon_cb);
        debug_vseq = uvme_cv32e20_random_debug_c::type_id::create("random_debug_vseqr", vsequencer);
        if (!debug_vseq.randomize()) begin
           `uvm_fatal("TEST", "Cannot randomize the debug sequence!")
        end
        debug_vseq.start(vsequencer);
        break;
    end
endtask : random_debug

task uvmt_cv32e20_general_purpose_test_c::irq_noise();
  `uvm_info("TEST", "Starting IRQ Noise thread in UVM test", UVM_NONE);
  while (1) begin
    uvme_cv32e20_interrupt_noise_c interrupt_noise_vseq;

    interrupt_noise_vseq = uvme_cv32e20_interrupt_noise_c::type_id::create("interrupt_noise_vseqr", vsequencer);
    assert(interrupt_noise_vseq.randomize() with {
      reserved_irq_mask == 32'h0;
    });
    interrupt_noise_vseq.start(vsequencer);
    break;
  end
endtask : irq_noise

task uvmt_cv32e20_general_purpose_test_c::nmi_assert();
  uvme_cv32e20_nmi_assert_c nmi_assert_vseq;

  `uvm_info("TEST", "Starting NMI Assert thread in UVM test", UVM_NONE);

  nmi_assert_vseq = uvme_cv32e20_nmi_assert_c::type_id::create("nmi_assert_vseqr", vsequencer);
  assert(nmi_assert_vseq.randomize());
  nmi_assert_vseq.start(vsequencer);
endtask : nmi_assert

task uvmt_cv32e20_general_purpose_test_c::mid_run_reset();
  uvme_cv32e20_mid_run_reset_c mid_run_reset_vseq;

  `uvm_info("TEST", "Starting Mid-Run Reset thread in UVM test", UVM_NONE);

  mid_run_reset_vseq = uvme_cv32e20_mid_run_reset_c::type_id::create("mid_run_reset_vseqr", vsequencer);
  assert(mid_run_reset_vseq.randomize());
  mid_run_reset_vseq.start(vsequencer);
endtask : mid_run_reset

task uvmt_cv32e20_general_purpose_test_c::irq_withdraw();
  uvme_cv32e20_irq_withdraw_c irq_withdraw_vseq;

  `uvm_info("TEST", "Starting IRQ Withdraw thread in UVM test", UVM_NONE);

  irq_withdraw_vseq = uvme_cv32e20_irq_withdraw_c::type_id::create("irq_withdraw_vseqr", vsequencer);
  assert(irq_withdraw_vseq.randomize());
  irq_withdraw_vseq.start(vsequencer);
endtask : irq_withdraw

task uvmt_cv32e20_general_purpose_test_c::random_fetch_toggle();
  `uvm_info("TEST", "Starting random_fetch_toggle thread in UVM test", UVM_NONE);
  while (1) begin
    int unsigned fetch_assert_cycles;
    int unsigned fetch_deassert_cycles;

    // SVTB.29.1.3.1 - Banned random number system functions and methods calls
    // Waive for performance reasons.
    //@DVT_LINTER_WAIVER_START "MT20211214_4" disable SVTB.29.1.3.1

    // Randomly assert for a random number of cycles
    randcase
      9: fetch_assert_cycles = $urandom_range(100_000, 100);
      1: fetch_assert_cycles = $urandom_range(100, 1);
      1: fetch_assert_cycles = $urandom_range(3, 1);
    endcase
    repeat (fetch_assert_cycles) @(core_cntrl_vif.drv_cb);

    // Randomly dessert for a random number of cycles
    randcase
      3: fetch_deassert_cycles = $urandom_range(100, 1);
      1: fetch_deassert_cycles = $urandom_range(3, 1);
    endcase
    //@DVT_LINTER_WAIVER_END "MT20211214_4"

    repeat (fetch_deassert_cycles) @(core_cntrl_vif.drv_cb);
  end

endtask : random_fetch_toggle

`endif // __UVMT_CV32E20_GENERAL_PURPOSE_TEST_SV__
