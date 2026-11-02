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


`ifndef __UVME_CV32E20_IRQ_WITHDRAW_VSEQ_SV__
`define __UVME_CV32E20_IRQ_WITHDRAW_VSEQ_SV__

/**
 * Virtual sequence that repeatedly *withdraws* an interrupt shortly after
 * asserting it, to hit the controller's one-cycle interrupt-commit window.
 *
 * This exists for one bin: the false arm of `if (handle_irq)` inside the
 * controller's IRQ_TAKEN state, cve2_controller.sv:514, row H001 of
 * docs/coverage/coverage_review.csv. The window it has to land in is described
 * by the RTL's own assertion block:
 *
 *   DECODE commits the request (cve2_controller.sv:496-498, handle_irq=1, ->
 *   IRQ_TAKEN), and IRQ_TAKEN then re-samples handle_irq the next cycle before
 *   it performs the PC redirect (:514). If the source dropped in between, the
 *   core correctly declines the redirect -- that is irq_withdrawn_in_taken
 *   (:835-836) -- and the false arm is taken.
 *
 * SWEEPS A WINDOW, DOES NOT AIM AT ONE CYCLE. That is a real limitation of
 * driving this through uvma_interrupt_drv_c rather than on the interface
 * directly, and it is exactly why this is a randomized pulse train:
 *
 *   * A line is held up for a *minimum of two* clock cycles no matter what the
 *     sequence asks for (uvma_interrupt_drv_c::wait_and_assert_irq_edge), so a
 *     withdrawal cannot be placed on an arbitrary cycle after the assert edge:
 *     the narrowest pulse this can build is two cycles wide.
 *   * Every action runs in its own forked thread behind a per-irq semaphore
 *     (uvma_interrupt_drv_c::assert_irq, ::deassert_irq). A DEASSERT that
 *     arrives while the matching ASSERT still holds that semaphore is dropped
 *     and the line stays up until the driver's own irq_ack_clear() takes it
 *     down on the ack -- which is no DUT signal but the testbench's own probe
 *     `ctrl_fsm_cs == 4'h7` (tb/uvmt/uvmt_cv32e20_dut_wrap.sv:107), high for
 *     exactly the one IRQ_TAKEN cycle -- so part of this train is consumed as
 *     ordinary, taken interrupts rather than as withdrawals.
 *   * What the sequence does control is the *distribution* of trailing edges.
 *     hold_cycles randomizes the width of each pulse and gap_cycles the space
 *     between pulses, so each pulse puts its withdraw edge on a different cycle
 *     relative to whatever DECODE was doing. IRQ_TAKEN lasts exactly one cycle,
 *     so no single width is reliably right, and a single hit would have been
 *     enough, because a covered bin stays covered for the whole merged database.
 *
 * MEASURED 2026-11-01 (seed 1, Questa One 2025.3_2, USE_ISS=NO): the sweep does
 * not land, and the reason is not the distribution. The run passes (SIMULATION
 * PASSED, 10 m 34 s), all 3008 pulses go by, and the controller's
 * DECODE -> IRQ_TAKEN commit happens exactly *once* in the run: cve2_controller.sv:514
 * is evaluated twice, true both times, so the acceptance bin is still a miss
 * (docs/coverage/raw/phase_c_acceptance.csv). The two-cycle minimum above is not
 * a narrowing of the window, it is wider than the window: a withdrawal needs a
 * falling edge one cycle after the commit, and the driver's own irq_ack_clear()
 * drops the line when it samples irq_ack -- and the testbench asserts that as
 * `ctrl_fsm_cs == 4'h7` (tb/uvmt/uvmt_cv32e20_dut_wrap.sv:107), that is during
 * the IRQ_TAKEN cycle in which :514 is sampled -- so the clear lands on the
 * next edge, when the FSM has already left IRQ_TAKEN: one cycle late at the
 * earliest. No hold_cycles/gap_cycles setting can beat that, so please do not
 * tune this sequence toward the window; closing the bin means driving the irq
 * line low for exactly one cycle from below uvma_interrupt_drv_c -- from
 * tb/uvmt/, which is where ctrl_fsm_cs is already probed, since vendor_lib/ is
 * a git-ignored clone of upstream core-v-verif and is not ours to patch -- or
 * documenting the miss on purpose. The sequence
 * stays wired up as the harness either way, so the measurement is reproducible
 * while that decision is open.
 *
 * skew is zeroed after randomization. The sequence item's own valid_skew_wgt
 * (uvma_interrupt_seq_item.sv) hard-pins no_skew_wgt == 0 and skew_wgt == 1, so
 * default_skew_c gives every action a 1..32 cycle skew and no inline `with`
 * constraint can ask for 0 -- a dist weight of 0 makes 0 unsolvable and the
 * randomization would fail. Assigning the field after randomize() is what the
 * driver reads, and it takes up to 32 cycles of slop off both edges of every
 * pulse; what remains uncontrolled is the driver's own two-cycle hold, which is
 * precisely what sweeping hold_cycles is for.
 *
 * The interrupt chosen is the NMI line (irq_uvma[0], see
 * uvmt_cv32e20_dut_wrap.sv), for two reasons. handle_irq is
 * `~debug_mode_q & ~nmi_mode_q & (irq_nm_i | (irq_pending_i & csr_mstatus_mie_i))`
 * (:321-322), so the NMI reaches handle_irq without the program first having
 * to enable mstatus.MIE and a mie bit -- one moving part less in the paired
 * test-program. And the BSP does install a returning handler for it
 * (bsp/vectors.S -> m_nmi_irq_handler), so the pulses that are *not* withdrawn
 * are taken and retired rather than derailing the program. That is a real cost
 * of this choice and it is documented in the test-program's own header.
 *
 * UVMA_INTERRUPT_SEQ_ITEM_ACTION_ASSERT_UNTIL_ACK is deliberately not used: it
 * holds the line until that fabricated ack goes up, which is the opposite of
 * withdrawing it.
 */
class uvme_cv32e20_irq_withdraw_c extends uvme_cv32e20_base_vseq_c;

   // Cycles to wait before the first pulse, so the program is properly running.
   rand int unsigned initial_delay;

   // Number of assert/deassert pulses. Each one is one attempt at the window.
   rand int unsigned pulse_count;

   // Cycles between the assert edge and the withdraw edge: the sweep variable.
   // The floor of 2 is the driver's own minimum hold; below it the two edges
   // this sequence asks for are not distinguishable at the DUT.
   rand int unsigned hold_cycles;

   // Cycles between pulses. Small, so a run fits in a normal timeout.
   rand int unsigned gap_cycles;

   constraint valid_initial_delay_c {
     initial_delay inside {[50:500]};
   }

   constraint valid_pulse_count_c {
     pulse_count inside {[2000:6000]};
   }

   // Weighted to the narrow end: the interesting withdrawal is the one that
   // lands the cycle after DECODE committed, and each cycle wider than that is
   // progressively less likely to still be inside IRQ_TAKEN. The tail to 10 is
   // there for a commit delayed behind a stall.
   constraint valid_hold_cycles_c {
     hold_cycles dist { 2 := 30,
                        3 := 25,
                        4 := 15,
                      [5:10] :/ 30 };
   }

   constraint valid_gap_cycles_c {
     gap_cycles inside {[1:20]};
   }

   `uvm_object_utils_begin(uvme_cv32e20_irq_withdraw_c)
      `uvm_field_int(initial_delay , UVM_DEFAULT + UVM_DEC)
      `uvm_field_int(pulse_count   , UVM_DEFAULT + UVM_DEC)
      `uvm_field_int(hold_cycles   , UVM_DEFAULT + UVM_DEC)
      `uvm_field_int(gap_cycles    , UVM_DEFAULT + UVM_DEC)
   `uvm_object_utils_end

   /**
    * Default constructor.
    */
   extern function new(string name="uvme_cv32e20_irq_withdraw");

   /**
    * Pulse and withdraw the NMI line pulse_count times, sweeping pulse width.
    */
   extern virtual task body();

endclass : uvme_cv32e20_irq_withdraw_c


function uvme_cv32e20_irq_withdraw_c::new(string name="uvme_cv32e20_irq_withdraw");

   super.new(name);

endfunction : new


task uvme_cv32e20_irq_withdraw_c::body();

   uvma_interrupt_seq_item_c irq_req;

   // Bit 0 of irq_mask is irq_uvma[0], which is the DUT's irq_nm_i.
   repeat (initial_delay) @(cntxt.interrupt_cntxt.vif.drv_cb);

   `uvm_info("IRQWITHDRAW",
             $sformatf("Withdrawing NMI (irq_mask[0]) %0d times, hold 2..10 cycles",
                       pulse_count),
             UVM_NONE)

   for (int unsigned pulse = 0; pulse < pulse_count; pulse++) begin

      `uvm_create_on(irq_req, p_sequencer.interrupt_sequencer);
      start_item(irq_req);
      assert(irq_req.randomize() with {
        action   == UVMA_INTERRUPT_SEQ_ITEM_ACTION_ASSERT;
        // Bit 0 of irq_mask is irq_uvma[0], the DUT's irq_nm_i.
        irq_mask == 32'h1;
      });
      // See the class header: the item's own constraints make skew 0
      // unsolvable, so it is assigned rather than constrained.
      foreach (irq_req.skew[i]) irq_req.skew[i] = 0;
      finish_item(irq_req);

      repeat (hold_cycles) @(cntxt.interrupt_cntxt.vif.drv_cb);

      `uvm_create_on(irq_req, p_sequencer.interrupt_sequencer);
      start_item(irq_req);
      assert(irq_req.randomize() with {
        action   == UVMA_INTERRUPT_SEQ_ITEM_ACTION_DEASSERT;
        irq_mask == 32'h1;
      });
      foreach (irq_req.skew[i]) irq_req.skew[i] = 0;
      finish_item(irq_req);

      // The withdrawal above is the interesting edge. Whether it lands inside
      // IRQ_TAKEN is a lottery against the pipeline in front of it; hold_cycles
      // is the ticket and this loop is the number of draws.
      repeat (gap_cycles) @(cntxt.interrupt_cntxt.vif.drv_cb);

   end

   `uvm_info("IRQWITHDRAW", "Interrupt-withdrawal pulses complete", UVM_NONE)

endtask : body

`endif // __UVME_CV32E20_IRQ_WITHDRAW_VSEQ_SV__
