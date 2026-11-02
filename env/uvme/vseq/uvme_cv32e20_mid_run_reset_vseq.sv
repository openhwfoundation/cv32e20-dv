// SPDX-License-Identifier: Apache-2.0 WITH SHL-2.1
// Copyright (c) 2026 Eclipse Foundation
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


`ifndef __UVME_CV32E20_MID_RUN_RESET_VSEQ_SV__
`define __UVME_CV32E20_MID_RUN_RESET_VSEQ_SV__

/**
 * Virtual sequence that drops reset *while the DUT is running*, once, after a
 * bounded random delay.
 *
 * This exists for the 16 reset-transition rows of
 * docs/coverage/coverage_review.csv. Questa's FSM extractor models the async
 * reset of every FSM as an implicit transition into its reset value, and the
 * only way to exercise, say, ctrl_fsm_cs IRQ_TAKEN->RESET or
 * md_state_q MD_COMP->MD_IDLE is to pull rst_ni while the design sits in that
 * state. Nothing in the suite did that: uvme_cv32e20_reset_vseq_c is started
 * exactly once, in reset_phase, before the core has left RESET, so all 16 of
 * those bins were misses and sim/tools/vsim/cov.tcl waived them as an accepted
 * untested-stimulus gap.
 *
 * No new agent is needed. The vendored clock/reset driver applies
 * UVMA_CLKNRST_SEQ_ITEM_ACTION_ASSERT_RESET from its run-loop regardless of
 * phase (uvma_clknrst_drv.sv), so one sequence item on the existing
 * clknrst_sequencer is a real asynchronous reset pulse at an arbitrary point of
 * the program's execution -- exactly what the waivers describe.
 *
 * What this deliberately does not do is keep the test running afterwards. The
 * pulse is asynchronous and the whole point is to land it in the middle of a
 * state, so the RVFI trace, the ISA coverage model and the reference-model
 * comparison all lose their place at that moment -- which is why the UVMT
 * testbench is run with USE_ISS=NO (it is in run_tests.py's TESTBENCHES table
 * for every uvmt test, so no per-test opt-out is needed).
 *
 * Like every other piece of asynchronous stimulus here this sequence is kicked
 * off with fork/join_none from uvmt_cv32e20_general_purpose_test_c, so the
 * delay below is the only thing aiming the pulse. It is bounded deliberately
 * short of the paired program's own length: a pulse that lands mid-loop is the
 * expected case, not a failure, because the core restarts from BOOT_SET, runs
 * the program a second time and reports pass at the end of *that* pass (see
 * tests/programs/custom/mid_run_reset_test/). A pulse that lands after the
 * pass has been reported disturbs nothing. What would hang the test is a
 * program waiting for something when the pulse arrives -- hence the absence of
 * wfi in the program, and hence ctrl_fsm_cs WAIT_SLEEP->RESET and SLEEP->RESET
 * staying under their waivers.
 *
 * MEASURED 2026-11-01 (seeds 1-12): it runs, and the paired test passes on all
 * twelve seeds. What one asynchronous pulse retires is three rows of the
 * sixteen, not sixteen -- ctrl_fsm_cs DECODE->RESET on 12 of 12 seeds,
 * md_state_q MD_COMP->MD_IDLE on 8 of 12, gen_mult_fast/mult_state_q ALBH->ALBL
 * on 1 of 12. The other thirteen need stimulus this program does not contain (a
 * wfi, debug_req_i, an interrupt, an exception, a misaligned access) or a pulse
 * aimed at a one-cycle state, which a randomized delay cannot do. Per-row
 * numbers and the reason for each are in
 * docs/coverage/raw/phase_c_acceptance.csv; none of them is retired on this
 * evidence, because a waiver is retired against the merged database of a real
 * batch, which is what bin/coverage_waiver_audit.py re-measures.
 */
class uvme_cv32e20_mid_run_reset_c extends uvme_cv32e20_base_vseq_c;

   // How long to wait, in clock cycles, before pulling reset. Randomized so a
   // regression over several seeds lands the pulse in different pipeline and
   // FSM states; the lower bound keeps the pulse clear of the initial reset's
   // own de-assertion.
   rand int unsigned initial_delay;

   // How long to hold reset, in picoseconds -- the same unit and meaning as
   // uvme_cv32e20_reset_vseq_c::rst_deassert_period. The default agent value
   // (100 ns) is far longer than any pipeline state is worth holding, and the
   // initial reset uses 7.4 ns; a few cycles in the middle of that range is
   // what puts the design back into RESET without changing what the pulse is
   // there to cover.
   rand int unsigned rst_deassert_period;

   constraint valid_initial_delay_c {
     initial_delay dist { [10:200]      :/ 3,
                          [200:2000]    :/ 4,
                          [2000:20000]  :/ 3 };
   }

   constraint valid_rst_deassert_period_c {
     rst_deassert_period inside {[2_000:20_000]};
   }

   `uvm_object_utils_begin(uvme_cv32e20_mid_run_reset_c)
      `uvm_field_int(initial_delay       , UVM_DEFAULT + UVM_DEC)
      `uvm_field_int(rst_deassert_period , UVM_DEFAULT + UVM_DEC)
   `uvm_object_utils_end

   /**
    * Default constructor.
    */
   extern function new(string name="uvme_cv32e20_mid_run_reset");

   /**
    * Waits initial_delay clock cycles, then pulses reset once.
    */
   extern virtual task body();

endclass : uvme_cv32e20_mid_run_reset_c


function uvme_cv32e20_mid_run_reset_c::new(string name="uvme_cv32e20_mid_run_reset");

   super.new(name);

endfunction : new


task uvme_cv32e20_mid_run_reset_c::body();

   uvma_clknrst_seq_item_c reset_req;

   repeat (initial_delay) @(posedge cntxt.clknrst_cntxt.vif.clk);

   `uvm_info("MIDRUNRST",
             $sformatf("Asserting reset for %0t after %0d cycles",
                       (rst_deassert_period * 1ps), initial_delay),
             UVM_NONE)

   `uvm_do_on_with(reset_req, p_sequencer.clknrst_sequencer, {
     action              == UVMA_CLKNRST_SEQ_ITEM_ACTION_ASSERT_RESET;
     initial_value       == UVMA_CLKNRST_SEQ_ITEM_INITIAL_VALUE_1;
     rst_deassert_period == local::rst_deassert_period;
   })

   `uvm_info("MIDRUNRST", "Reset re-asserted and released", UVM_NONE)

endtask : body

`endif // __UVME_CV32E20_MID_RUN_RESET_VSEQ_SV__
