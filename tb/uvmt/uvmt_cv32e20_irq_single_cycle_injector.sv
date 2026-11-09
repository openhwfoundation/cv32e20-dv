// SPDX-License-Identifier: Apache-2.0 WITH SHL-2.1
//
// Copyright 2026 Eclipse Foundation
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
///////////////////////////////////////////////////////////////////////////////


`ifndef __UVMT_CV32E20_IRQ_SINGLE_CYCLE_INJECTOR_SV__
`define __UVMT_CV32E20_IRQ_SINGLE_CYCLE_INJECTOR_SV__

/**
 * Directed interrupt withdrawal at the core's interrupt pins: blanks the
 * interrupt bus into the DUT for exactly the one IRQ_TAKEN cycle after the
 * controller commits to an interrupt, a bounded number of times.
 *
 * cve2_controller.sv enters IRQ_TAKEN because handle_irq was true in the
 * *committing* cycle (cve2_controller.sv:431-436 in FIRST_FETCH,
 * :496-498 in DECODE), and then re-evaluates handle_irq in the IRQ_TAKEN
 * cycle itself (:514) before it redirects the PC.  The false arm of that
 * if -- "the source withdrew in the commit cycle, so decline the redirect"
 * -- is legal hardware behaviour, modelled by the RTL itself as
 * irq_withdrawn_in_taken (cve2_controller.sv:826-836), and it is what this
 * module injects.
 *
 * It cannot be reached through uvma_interrupt_drv_c.  That driver drops a
 * line only after it samples irq_ack, and irq_ack is no DUT signal at all:
 * it is the testbench's own probe `ctrl_fsm_cs == 4'h7' in
 * tb/uvmt/uvmt_cv32e20_dut_wrap.sv -- high during the IRQ_TAKEN cycle in
 * which :514 is sampled -- so the driver's falling edge lands one cycle
 * later than the window, always, whatever the sequence asks for: a sweep of
 * 3008 pulses committed once and hit the arm never, because the clear is
 * structurally one cycle late, not mistuned (cov.tcl carries the analysis).
 *
 * The commit edge is the one signal that names the window, so the blank is
 * registered off it: ctrl_fsm_cs inside {FIRST_FETCH, DECODE} &&
 * ctrl_fsm_ns == IRQ_TAKEN is the transition the RTL has just made, and a
 * flop clocked by it therefore goes high for the IRQ_TAKEN cycle and for no
 * other.  Probing ctrl_fsm_ns rather than handle_irq inherits every commit
 * precondition of the RTL (!stall, !special_req, !instr_valid_i, no debug
 * request, xif scoreboard idle) for free.  Holding the inputs low for that
 * one cycle is exactly what an asynchronous interrupt source de-asserting
 * one cycle after the core sampled it looks like at the pins, so this is
 * legal stimulus and not a protocol violation: the core declines the
 * redirect, returns to DECODE, and re-attempts with the next cycle the
 * source is still good for.
 *
 * The module has no knowledge of where it is bound; the bind statement
 * lives at the end of tb/uvmt/uvmt_cv32e20_dut_wrap.sv, and irq_dut -- the
 * net irq_out drives -- is what the core's .irq_*_i ports are wired to.
 * Nothing is routed back out of the instance: uvmt_cv32e20_tb.sv's
 * end_of_test guard reads en and fired_q by hierarchical reference, so the
 * bind carries the stimulus path alone and dut_wrap keeps no second copy of
 * the blanking rule (its checkers' view is irq_dut itself).
 *
 * Inert unless +irq_single_cycle_shots=<N> is on the vsim command line:
 * with the plusarg absent, en is 0 and irq_out == irq_in for every other
 * test in the regression.  uvmt_cv32e20_tb.sv's end_of_test fails a run
 * whose injector was armed but never fired, so the test that arms this
 * cannot pass without having stimulated the bin
 * (tests/programs/custom/irq_single_cycle_test, run with
 * +irq_single_cycle +irq_single_cycle_shots=N).
 *
 * FIXME: need a sol'n that does not require probing the core RTL.
 */
module uvmt_cv32e20_irq_single_cycle_injector #(
   // Sanity bound on +irq_single_cycle_shots: a run that asks to withdraw
   // more commits than a handful is nearly always a typo, and one that big
   // would deafen the core for the whole test.
   parameter int unsigned SHOTS_MAX = 16
) (
   input  logic        clk,
   input  logic        reset_n,
   // The controller's own FSM state/next-state, wired through the bind.
   input  logic [3:0]  ctrl_fsm_cs,
   input  logic [3:0]  ctrl_fsm_ns,
   // The interrupt bus as the interrupt agent drives it ...
   input  logic [31:0] irq_in,
   // ... and as the core must see it: blanked for the withdrawn cycles.
   output logic [31:0] irq_out
   );

   // Encodings of cve2_controller's module-local ctrl_fsm_e
   // (cve2_controller.sv:106-109): RESET, BOOT_SET, WAIT_SLEEP, SLEEP,
   // FIRST_FETCH, DECODE, FLUSH, IRQ_TAKEN, DBG_TAKEN_IF, DBG_TAKEN_ID.
   localparam logic [3:0] FSM_FIRST_FETCH = 4'h4;
   localparam logic [3:0] FSM_DECODE      = 4'h5;
   localparam logic [3:0] FSM_IRQ_TAKEN   = 4'h7;

   // The bind wires nothing back out of these: uvmt_cv32e20_tb.sv's
   // end_of_test guard reads en and fired_q by hierarchical reference into
   // the bound instance -- the established probe path in this harness.
   // Treat the names below as this module's observability interface.
   int unsigned shots;      // +irq_single_cycle_shots, written once below
   logic        en;         // 1 once a non-zero shot count was parsed
   logic        withdraw_q; // 1 => the core sees no interrupt this cycle
   logic [31:0] fired_q;    // shots fired so far

   // The core commits to an interrupt at this clock edge.
   wire commit_to_irq =
       ((ctrl_fsm_cs == FSM_FIRST_FETCH) || (ctrl_fsm_cs == FSM_DECODE)) &&
       (ctrl_fsm_ns == FSM_IRQ_TAKEN);

   assign irq_out  = irq_in & ~{32{withdraw_q}};

   // Written only by the initial block below; withdraw_q and fired_q only
   // by the always block further down.
   initial begin
      shots = 0;
      en    = 1'b0;
      if ($value$plusargs("irq_single_cycle_shots=%d", shots)) begin
         if (shots > SHOTS_MAX) begin
            $display("IRQ_SINGLE_CYCLE: +irq_single_cycle_shots=%0d exceeds SHOTS_MAX=%0d, clamping.", shots, SHOTS_MAX);
            shots = SHOTS_MAX;
         end
         en = (shots != 0);
         if (en) begin
            $display("IRQ_SINGLE_CYCLE: armed, blanking the core's interrupt inputs for %0d IRQ_TAKEN cycle(s) (cve2_controller.sv:514 false arm).", shots);
         end
      end
   end

   always @(posedge clk or negedge reset_n) begin
      if (!reset_n) begin
         withdraw_q <= 1'b0;
         fired_q    <= '0;
      end
      else begin
         withdraw_q <= 1'b0;
         if (en && commit_to_irq && (fired_q < shots)) begin
            withdraw_q <= 1'b1;
            fired_q    <= fired_q + 1;
            $display("IRQ_SINGLE_CYCLE: shot %0d of %0d, interrupt inputs withdrawn for the IRQ_TAKEN cycle starting at %0t.", fired_q + 1, shots, $time);
         end
      end
   end

   final begin
      if (en) begin
         $display("IRQ_SINGLE_CYCLE: %0d of %0d withdrawal shot(s) fired.", fired_q, shots);
      end
   end

endmodule : uvmt_cv32e20_irq_single_cycle_injector

`endif // __UVMT_CV32E20_IRQ_SINGLE_CYCLE_INJECTOR_SV__
