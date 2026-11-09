// SPDX-License-Identifier: Apache-2.0 WITH SHL-2.1
// Copyright 2020,2022 OpenHW Group
// Copyright 2020 Datum Technology Corporation
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


`ifndef __UVME_CV32E20_INTERRUPT_NOISE_SV__
`define __UVME_CV32E20_INTERRUPT_NOISE_SV__

/**
 * Virtual sequence responsible for running a free-running stream of
 * random interrupt events to the DUT. These events are asynchronous with the main test program.
 */
class uvme_cv32e20_interrupt_noise_c extends uvme_cv32e20_base_vseq_c;

   // Free-running interrupt noise generation (all three threads below) is only allowed up to
   // NOISE_CUTOFF_TIME_NS in simulated time; a busy noise stream can otherwise perpetually starve the
   // core of the chance to drain pending interrupts and return to executing the test program,
   // potentially causing a livelock on corev_rand_interrupt_nested.
   //
   // Past this point:
   //  - gen_assert/gen_deassert (fire-and-forget UVMA_INTERRUPT_SEQ_ITEM_ACTION_DEASSERT/ASSERT)
   //    simply stop. UVMA_INTERRUPT_SEQ_ITEM_ACTION_ASSERT (driven by the gen_deassert thread --
   //    the two are cosmetically mislabeled, see uvma_interrupt_drv.sv) drives a line high and
   //    releases its tracking semaphore immediately with no self-clear
   //    (uvma_interrupt_drv_c::assert_irq()); the line only clears via a later DEASSERT lucky
   //    enough to target the same bit, or the driver's ack-clear thread seeing
   //    an ack -- on this testbench that ack is the probe
   //    `ctrl_fsm_cs == 4'h7` (tb/uvmt/uvmt_cv32e20_dut_wrap.sv:107), because
   //    CVE2 has no interrupt acknowledge of its own. Left running past the
   //    cutoff, one of these can leave a line stuck pending indefinitely, which -- combined with
   //    a WFI-only interrupt-vector handler that does no masking -- produces a self-sustaining
   //    wfi -> mret -> re-take same still-pending line -> wfi livelock with no forward progress
   //    (observed on corev_rand_interrupt_exception), or -- with no WFI involved at all -- an
   //    endless mret -> re-take -> mret loop on whatever cause that stuck bit maps to,
   //    observed as a 100ms watchdog timeout on corev_rand_interrupt (mcause 0x80000016,
   //    fast irq 6, stuck asserted with zero WFI retirements in the whole run). body() now
   //    forces a final DEASSERT of every non-reserved line once both fire-and-forget threads
   //    stop, so no bit can be left stuck past the cutoff -- see the comment at that call site.
   //  - gen_assert_until_ack keeps running, but gated one action per real WFI retirement (see
   //    wfi_monitor()/wait_for_noise_slot() below) instead of being cut off entirely -- a total
   //    cutoff strands any test whose generated program relies on an interrupt to wake a WFI
   //    forever asleep (observed as a 100ms watchdog timeout on corev_rand_interrupt_debug).
   //    This action self-clears via the agent's irq_ack handshake
   //    (uvma_interrupt_drv_c::assert_irq_until_ack()) -- and on this testbench the
   //    ack it waits for is the `ctrl_fsm_cs == 4'h7` probe named above, so it fires
   //    only *if* the core ever takes that specific cause. If the generated test
   //    program's own CSR content permanently masks a cause off in
   //    mie, the ack never goes high for it, and assert_irq_until_ack() blocks forever holding that
   //    index's semaphore -- every later request that includes that bit is silently dropped (see
   //    "already in flight" in uvma_interrupt_drv_c::assert_irq_until_ack()). That's harmless as
   //    long as some other, live bit is also in the same request, but once enough bits go stuck
   //    this way, a request drawn entirely from stuck bits is a total no-op: no new edge is ever
   //    driven, and since this is gated one-per-WFI with no other noise source running, the core
   //    can be left asleep in WFI forever (observed as a 100ms watchdog timeout on
   //    corev_rand_interrupt_wfi_mem_stress -- traced live via a temporary $display in
   //    assert_irq_until_ack(): two bits went permanently un-acked within the first 70us of a
   //    100ms run, and ~55ms later a request happened to draw only those two). ack_monitor()
   //    below tracks per-bit ack latency and gen_assert_until_ack excludes any bit that's been
   //    outstanding too long from future draws, so a stuck bit can no longer poison the pool.
   localparam longint unsigned NOISE_CUTOFF_TIME_NS = 10_000_000;

   // How long a requested bit is allowed to sit un-acked before gen_assert_until_ack treats it
   // as permanently stuck (e.g. masked off in mie for the rest of the test) and stops selecting
   // it. Normal acks in practice land within a few hundred to a couple thousand ns; this is
   // generous enough to never mistake a merely-slow ack for a stuck one.
   localparam longint unsigned ACK_STUCK_TIMEOUT_NS = 50_000;

   // WFI instruction encoding (opcode 1110011, funct12 0x105, rs1=rd=x0), used by
   // wfi_monitor() to detect a WFI retirement over RVFI. This is done to sense the
   // WFI retirement rather than just the irq_ack handshake.
   localparam bit [31:0] WFI_INSTR_ENCODING = 32'h10500073;

   // One key is put() by wfi_monitor() each time the core retires a WFI instruction, and
   // get() by a noise-generation loop past the cutoff before it's allowed to issue its next
   // action. A semaphore (rather than a plain SV event) is required here: an event trigger
   // that occurs while no thread is yet parked on it is lost, which would permanently
   // deadlock the core in WFI the first time the three generator threads' independent
   // rand_delay()s all happened to still be in flight when the WFI retired.
   semaphore wfi_sem;

   // Per-bit ack tracking for gen_assert_until_ack, maintained by ack_monitor(). A bit is
   // "outstanding" from the moment gen_assert_until_ack requests it until either a matching
   // irq_ack/irq_id is observed (cleared) or ACK_STUCK_TIMEOUT_NS elapses (treated as stuck).
   bit               outstanding_until_ack[32];
   time              outstanding_until_ack_since[32];

   rand int unsigned short_delay_wgt;
   rand int unsigned med_delay_wgt;
   rand int unsigned long_delay_wgt;
   rand int unsigned initial_delay_assert_until_ack;
   rand int unsigned initial_delay_assert;
   rand int unsigned initial_delay_deassert;

   rand bit [31:0]   reserved_irq_mask;

   `uvm_object_utils_begin(uvme_cv32e20_interrupt_noise_c)
   `uvm_object_utils_end

   // Bit 0 == irq_uvma[0] == NMI (uvmt_cv32e20_dut_wrap.sv irq_nm_i). Not
   // excluded from noise generation by default -- soft, so any caller's
   // explicit override (e.g. uvmt_cv32e20_general_purpose_test_c::irq_noise(),
   // which already pins reserved_irq_mask == 32'h0) still wins outright.
   // This just guarantees the permissive default is a property of the class
   // itself, not an accident of the one caller that happens to set it today.
   constraint reserved_irq_mask_default_c {
     soft reserved_irq_mask[0] == 1'b0;
   }

   constraint default_delay_c {
     soft short_delay_wgt == 2;
     soft med_delay_wgt == 5;
     soft long_delay_wgt == 3;
   }

   constraint valid_delay_c {
     short_delay_wgt != 0 || med_delay_wgt != 0 || long_delay_wgt != 0;
   }

   constraint valid_initial_delay_assert_until_ack_c {
     initial_delay_assert_until_ack dist { 0 :/ 1,
                                           [10:500] :/ 4,
                                           [500:1000] :/ 3};
   }

   constraint valid_initial_delay_assert_c {
     initial_delay_assert dist { 0 :/ 2,
                                 [10:500] :/ 4,
                                 [500:1000] :/ 3};
   }

   constraint valid_initial_delay_deassert_c {
     initial_delay_deassert dist { 0 :/ 2,
                                   [10:500] :/ 4,
                                   [500:1000] :/ 3};
   }

   /**
    * Default constructor.
    */
   extern function new(string name="uvme_cv32e20_interrupt_noise");

   /**
    * Starts the clock, waits, then resets the DUT.
    */
   extern virtual task body();
   extern virtual task rand_delay();

   /**
    * Watches the RVFI instruction retirement interface and puts a token into wfi_sem each
    * time a WFI instruction retires.
    */
   extern virtual task wfi_monitor();

   /**
    * Called at the top of each gen_assert_until_ack loop iteration (the only noise thread
    * still running past the cutoff -- see NOISE_CUTOFF_TIME_NS above). Returns immediately
    * before NOISE_CUTOFF_TIME_NS; after it, blocks until the core retires a WFI.
    */
   extern virtual task wait_for_noise_slot();

   /**
    * Watches irq_ack/irq_id and clears outstanding_until_ack[] on each ack, so
    * get_stuck_until_ack_mask() can tell a bit that's genuinely still in flight from one that's
    * merely been requested before and never touched since.
    */
   extern virtual task ack_monitor();

   /**
    * Returns the set of bits currently in outstanding_until_ack[] that have been waiting longer
    * than ACK_STUCK_TIMEOUT_NS -- i.e. bits gen_assert_until_ack should stop selecting because
    * the DUT is never going to ack them again.
    */
   extern virtual function bit [31:0] get_stuck_until_ack_mask();
endclass : uvme_cv32e20_interrupt_noise_c

function uvme_cv32e20_interrupt_noise_c::new(string name="uvme_cv32e20_interrupt_noise");

   super.new(name);

   wfi_sem = new(0);

endfunction : new

task uvme_cv32e20_interrupt_noise_c::rand_delay();
  randcase
    // SVTB.29.1.3.1 - Banned random number system functions and methods calls
    // Waive because the calls to the sys fns are controlled by constrained vars.
    //@DVT_LINTER_WAIVER_START "MT20211214_1" disable SVTB.29.1.3.1
    short_delay_wgt: repeat($urandom_range(   100,    1)) @(cntxt.interrupt_cntxt.vif.drv_cb);
    med_delay_wgt:   repeat($urandom_range(   500,  100)) @(cntxt.interrupt_cntxt.vif.drv_cb);
    long_delay_wgt:  repeat($urandom_range(10_000,5_000)) @(cntxt.interrupt_cntxt.vif.drv_cb);
    //@DVT_LINTER_WAIVER_END "MT20211214_1"
  endcase
endtask : rand_delay

task uvme_cv32e20_interrupt_noise_c::wfi_monitor();
  bit               last_order_valid = 0;
  longint unsigned  last_order;

  forever begin
    @(cntxt.rvfi_cntxt.instr_vif[0].mon_cb);
    // rvfi_valid/rvfi_insn hold their last-sampled value rather than pulsing back to an
    // invalid state, so once the core stops retiring (e.g. genuinely parked in WFI) this
    // condition would otherwise stay spuriously true on every subsequent clock -- checking
    // rvfi_order actually advancing is what distinguishes a real new retirement.
    if (cntxt.rvfi_cntxt.instr_vif[0].mon_cb.rvfi_valid &&
        (!last_order_valid || cntxt.rvfi_cntxt.instr_vif[0].mon_cb.rvfi_order != last_order)) begin
      last_order       = cntxt.rvfi_cntxt.instr_vif[0].mon_cb.rvfi_order;
      last_order_valid = 1;
      if (cntxt.rvfi_cntxt.instr_vif[0].mon_cb.rvfi_insn == WFI_INSTR_ENCODING) begin
        wfi_sem.put(1);
      end
    end
  end
endtask : wfi_monitor

task uvme_cv32e20_interrupt_noise_c::wait_for_noise_slot();
  if ($time >= NOISE_CUTOFF_TIME_NS) begin
    wfi_sem.get(1);
  end
endtask : wait_for_noise_slot

task uvme_cv32e20_interrupt_noise_c::ack_monitor();
  forever begin
    @(cntxt.interrupt_cntxt.vif.mon_cb);
    if (cntxt.interrupt_cntxt.vif.mon_cb.irq_ack) begin
      outstanding_until_ack[cntxt.interrupt_cntxt.vif.mon_cb.irq_id] = 0;
    end
  end
endtask : ack_monitor

function bit [31:0] uvme_cv32e20_interrupt_noise_c::get_stuck_until_ack_mask();
  bit [31:0] stuck_mask = '0;

  foreach (outstanding_until_ack[i]) begin
    if (outstanding_until_ack[i] &&
        (($time - outstanding_until_ack_since[i]) > ACK_STUCK_TIMEOUT_NS)) begin
      stuck_mask[i] = 1;
    end
  end

  return stuck_mask;
endfunction : get_stuck_until_ack_mask

task uvme_cv32e20_interrupt_noise_c::body();

  fork
    begin : wfi_monitor_thread
      wfi_monitor();
    end

    begin : ack_monitor_thread
      ack_monitor();
    end

    begin : gen_assert_until_ack

      repeat (initial_delay_assert_until_ack) @(cntxt.interrupt_cntxt.vif.drv_cb);

      while (1) begin
        uvma_interrupt_seq_item_c irq_req;
        bit [31:0]                stuck_mask;

        wait_for_noise_slot();

        stuck_mask = get_stuck_until_ack_mask();

        `uvm_create_on(irq_req, p_sequencer.interrupt_sequencer);
        start_item(irq_req);
        irq_req.default_repeat_count_c.constraint_mode(0);
        assert(irq_req.randomize() with {
          action        == UVMA_INTERRUPT_SEQ_ITEM_ACTION_ASSERT_UNTIL_ACK;
          repeat_count dist { 1 :/ 9, [2:3] :/ 1 };

          (irq_mask & local::reserved_irq_mask) == 0;
          (irq_mask & local::stuck_mask) == 0;
        });
        finish_item(irq_req);

        foreach (irq_req.irq_mask[i]) begin
          if (irq_req.irq_mask[i] && !outstanding_until_ack[i]) begin
            outstanding_until_ack[i]       = 1;
            outstanding_until_ack_since[i] = $time;
          end
        end

        rand_delay();

      end
    end

    begin : gen_assert_and_deassert_with_cleanup

      fork
        begin : gen_assert

          repeat (initial_delay_assert) @(cntxt.interrupt_cntxt.vif.drv_cb);

          while ($time < NOISE_CUTOFF_TIME_NS) begin
            uvma_interrupt_seq_item_c irq_req;

            `uvm_do_on_with(irq_req, p_sequencer.interrupt_sequencer, {
              action        == UVMA_INTERRUPT_SEQ_ITEM_ACTION_DEASSERT;
              (irq_mask & local::reserved_irq_mask) == 0;
            })

            rand_delay();

          end
        end

        begin : gen_deassert

          repeat (initial_delay_deassert) @(cntxt.interrupt_cntxt.vif.drv_cb);

          while ($time < NOISE_CUTOFF_TIME_NS) begin
            uvma_interrupt_seq_item_c irq_req;

            `uvm_do_on_with(irq_req, p_sequencer.interrupt_sequencer, {
              action        == UVMA_INTERRUPT_SEQ_ITEM_ACTION_ASSERT;
              (irq_mask & local::reserved_irq_mask) == 0;
            })

            rand_delay();

          end
        end
      join

      // gen_deassert's plain ASSERT actions have no self-clear (see class-level comment
      // above): assert_irq() releases its per-bit semaphore immediately after driving the
      // edge, so a bit it set can only ever clear via a later DEASSERT lucky enough to hit
      // the same bit, or an ack for that exact id -- which on this testbench is
      // the `ctrl_fsm_cs == 4'h7` probe at tb/uvmt/uvmt_cv32e20_dut_wrap.sv:107
      // keyed on exc_cause_o, not a CVE2 output. Once both threads above stop at
      // the cutoff, nothing is left running that will ever issue that lucky DEASSERT, and if
      // the ack for that id never comes (e.g. the interrupt the core actually takes
      // reports a different cause), the bit
      // stays pending forever -- observed as a 100ms watchdog timeout on
      // corev_rand_interrupt, with the core endlessly re-taking the same still-pending fast
      // interrupt and never returning to the test program.
      //
      // Wait comfortably longer than the max per-bit skew (always [1:32] cycles -- see
      // uvma_interrupt_seq_item_c::default_skew_c) so any still-in-flight skewed edge from
      // either thread's last issued item has landed, then force every non-reserved line back
      // to deasserted. deassert_irq() (uvma_interrupt_drv.sv) is a safe no-op on any bit
      // currently owned by an in-flight assert_irq_until_ack(), so this can't disturb that
      // mechanism's own bookkeeping.
      repeat (64) @(cntxt.interrupt_cntxt.vif.drv_cb);

      begin
        uvma_interrupt_seq_item_c cleanup_req;

        `uvm_create_on(cleanup_req, p_sequencer.interrupt_sequencer);
        start_item(cleanup_req);
        // uvma_interrupt_seq_item_c::irq_mask_c caps $countones(irq_mask) at 31
        // (it's tuned for general-purpose noise generation), but this cleanup
        // needs the full complement of reserved_irq_mask, which is all 32 bits
        // whenever reserved_irq_mask happens to randomize to 0. With irq_mask_c
        // left enabled that case is unsatisfiable, randomize() fails, this
        // cleanup silently never sends, and a line left asserted by
        // gen_deassert's non-self-clearing ASSERT (see comment above) can be
        // left stuck pending past the cutoff with nothing left running that will
        // ever clear it (the exact failure mode described above). Disable it
        // here since the inline constraint below fully determines irq_mask
        // anyway.
        cleanup_req.irq_mask_c.constraint_mode(0);
        assert(cleanup_req.randomize() with {
          action   == UVMA_INTERRUPT_SEQ_ITEM_ACTION_DEASSERT;
          irq_mask == ~local::reserved_irq_mask;
        });
        finish_item(cleanup_req);
      end
    end
  join
endtask : body

`endif // __UVME_CV32E20_INTERRUPT_NOISE_SV__
