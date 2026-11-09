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


`ifndef __UVME_CV32E20_IRQ_SINGLE_CYCLE_VSEQ_SV__
`define __UVME_CV32E20_IRQ_SINGLE_CYCLE_VSEQ_SV__

/**
 * Virtual sequence that offers the core an interrupt a small, bounded number of
 * times, so that the *testbench* can decline a few of them on the exact cycle
 * the controller commits to one.
 *
 * This exists for one branch bin: the false arm of `if (handle_irq)` inside the
 * controller's IRQ_TAKEN state, cve2_controller.sv:514. The window it has to
 * land in is described by the RTL's own assertion model:
 *
 *   DECODE (or FIRST_FETCH) commits the request because handle_irq was true
 *   (:496-498, :431-436), and IRQ_TAKEN re-samples handle_irq in the cycle
 *   after, before it redirects the PC (:514). A source that dropped in between
 *   is correctly declined -- `irq_withdrawn_in_taken` (:826-836) -- which is
 *   the false arm.
 *
 * THE WITHDRAWAL IS NOT THIS SEQUENCE'S JOB, AND CANNOT BE. uvma_interrupt_drv_c
 * drives through a clocking block and drops a line only after it has sampled
 * irq_ack; irq_ack is not a DUT signal at all (CVE2 interrupts are
 * level-sensitive), it is this testbench's own probe
 * `ctrl_fsm_cs == 4'h7` in tb/uvmt/uvmt_cv32e20_dut_wrap.sv -- high during the
 * IRQ_TAKEN cycle in which :514 is sampled. The driver's falling edge therefore
 * lands one cycle after the window closes, permanently; 3008 assert/deassert
 * pulses of the parent's pulse sweep produced one commit and no hit
 * (docs/coverage/raw/phase_c_acceptance.csv). Do not try to fix that by tuning
 * hold or gap widths: no width is earlier than one cycle.
 *
 * The hand-off is by plusarg, and both halves are needed:
 *
 *   +irq_single_cycle          starts this sequence (see
 *                              uvmt_cv32e20_general_purpose_test_c::irq_single_cycle).
 *   +irq_single_cycle_shots=N  arms the bound injector in
 *                              tb/uvmt/uvmt_cv32e20_irq_single_cycle_injector.sv,
 *                              which blanks the core's interrupt inputs for the
 *                              IRQ_TAKEN cycle of the next N commits. That is
 *                              where the withdrawal happens, because the commit
 *                              edge is the only cycle-accurate signal the
 *                              testbench has.
 *
 * What this sequence contributes is the commit: one NMI per attempt, offered
 * until the core acks it. The NMI line (irq_uvma[0] => irq_nm_i) is the one
 * that needs nothing from the program: handle_irq is
 * `~debug_mode_q & ~nmi_mode_q & (irq_nm_i | (irq_pending_i & csr_mstatus_mie_i))`
 * (:321-322), so no mstatus.MIE and no mie bit have to be set for the core to
 * commit to it. Attempts are kept a few more than the armed shots so that at
 * least one interrupt is *not* withdrawn and really is taken: an injector that
 * silently deafened the core forever would otherwise still look like a pass,
 * and the test-program only ends once the handler for the last, taken NMI has
 * retired.
 *
 * gap_cycles is wide enough that the BSP's NMI handler
 * (bsp/handlers.S's m_nmi_irq_handler, which writes to stdout and `mret`s) has
 * retired before the next offer: while it runs, nmi_mode_q is 1, handle_irq is
 * 0, and a commit -- and with it the ack this sequence waits for -- cannot
 * happen. That is why this class overrides the parent's [1:20] gap: the pulse
 * sweep could fire blindly between acks, this sequence needs a commit per
 * attempt.
 *
 * UVMA_INTERRUPT_SEQ_ITEM_ACTION_ASSERT_UNTIL_ACK is exactly the right action
 * here, and it is what uvme_cv32e20_nmi_assert_c uses for the same reason: it
 * holds the line until the ack, so one item is one commit. The skew knobs are
 * left at the item's own random defaults; nothing in this sequence aims at a
 * particular cycle any more, because the injector does.
 */
class uvme_cv32e20_irq_single_cycle_vseq_c extends uvme_cv32e20_irq_withdraw_c;

   // How many times to offer the NMI. Must stay above the shot count armed
   // with +irq_single_cycle_shots, so that a normal, taken interrupt closes
   // the run.
   rand int unsigned attempts;

   // +irq_single_cycle_shots, parsed in new(): the constraint below is stated
   // relative to it, and randomize() runs after create() in the test task, so
   // pre_body would already be too late.
   int unsigned shots;

   constraint valid_attempts_c {
     attempts inside {[shots+1:shots+3]};
   }

   // Same name overrides the parent's [1:20] pulse-sweep gap; see header.
   constraint valid_gap_cycles_c {
     gap_cycles inside {[200:500]};
   }

   `uvm_object_utils_begin(uvme_cv32e20_irq_single_cycle_vseq_c)
      `uvm_field_int(attempts , UVM_DEFAULT + UVM_DEC)
   `uvm_object_utils_end

   /**
    * Default constructor. Parses +irq_single_cycle_shots for the attempts
    * constraint.
    */
   extern function new(string name="uvme_cv32e20_irq_single_cycle_vseq");

   /**
    * Offer the NMI attempts times, each one held until the core acks it.
    */
   extern virtual task body();

endclass : uvme_cv32e20_irq_single_cycle_vseq_c


function uvme_cv32e20_irq_single_cycle_vseq_c::new(string name="uvme_cv32e20_irq_single_cycle_vseq");

   super.new(name);

   if (!$value$plusargs("irq_single_cycle_shots=%d", shots)) begin
      shots = 0;
   end

endfunction : new


task uvme_cv32e20_irq_single_cycle_vseq_c::body();

   uvma_interrupt_seq_item_c irq_req;

   repeat (initial_delay) @(cntxt.interrupt_cntxt.vif.drv_cb);

   `uvm_info("IRQSINGLECYCLE",
             $sformatf("Offering NMI (irq_mask[0]) %0d times; the TB injector (+irq_single_cycle_shots=%0d) withdraws the first ones at the commit edge",
                       attempts, shots),
             UVM_NONE)

   for (int unsigned attempt = 0; attempt < attempts; attempt++) begin

      `uvm_create_on(irq_req, p_sequencer.interrupt_sequencer);
      start_item(irq_req);
      assert(irq_req.randomize() with {
        // Held until the fabricated ack, i.e. until the core commits: one item,
        // one DECODE => IRQ_TAKEN transition for the injector to blank.
        action       == UVMA_INTERRUPT_SEQ_ITEM_ACTION_ASSERT_UNTIL_ACK;
        repeat_count == 1;
        // Bit 0 of irq_mask is irq_uvma[0], the DUT's irq_nm_i.
        irq_mask     == 32'h1;
      });
      finish_item(irq_req);

      `uvm_info("IRQSINGLECYCLE",
                $sformatf("Offer %0d of %0d acked", attempt + 1, attempts),
                UVM_NONE)

      repeat (gap_cycles) @(cntxt.interrupt_cntxt.vif.drv_cb);

   end

   `uvm_info("IRQSINGLECYCLE", "Interrupt offers complete", UVM_NONE)

endtask : body

`endif // __UVME_CV32E20_IRQ_SINGLE_CYCLE_VSEQ_SV__
