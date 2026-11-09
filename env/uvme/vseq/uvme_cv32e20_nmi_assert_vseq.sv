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


`ifndef __UVME_CV32E20_NMI_ASSERT_VSEQ_SV__
`define __UVME_CV32E20_NMI_ASSERT_VSEQ_SV__

/**
 * Virtual sequence that deterministically asserts the NMI line
 * (irq_uvma[0] -> irq_nm_i, see uvmt_cv32e20_dut_wrap.sv) exactly once,
 * after a bounded random delay, and waits for the DUT to ack it.
 *
 * Deliberately kept separate from uvme_cv32e20_interrupt_noise_c: that
 * class's job is broad, sustained random noise across all 32 lines, with
 * a lot of hardening (livelock avoidance, stuck-bit tracking, a WFI-paced
 * cutoff) built up specifically for that job. A single deterministic NMI
 * assertion doesn't need any of that -- reusing the noise vseq for this
 * would mean depending on (and risking disturbing) machinery this doesn't
 * need. This just sends one UVMA_INTERRUPT_SEQ_ITEM_ACTION_ASSERT_UNTIL_ACK
 * request with irq_mask == 32'h1 straight to the interrupt sequencer,
 * exactly the same primitive the noise vseq itself calls down to.
 */
class uvme_cv32e20_nmi_assert_c extends uvme_cv32e20_base_vseq_c;

   // Bounded random delay (in interrupt-driver clock cycles) before the NMI
   // is asserted, so it doesn't always land at the exact same point in a
   // test's execution.
   rand int unsigned initial_delay;

   constraint valid_initial_delay_c {
     initial_delay dist { [0:100]     :/ 3,
                           [100:1000] :/ 4,
                           [1000:5000]:/ 3};
   }

   `uvm_object_utils(uvme_cv32e20_nmi_assert_c)

   /**
    * Default constructor.
    */
   extern function new(string name="uvme_cv32e20_nmi_assert");

   /**
    * Waits initial_delay cycles, then asserts NMI (irq_mask bit 0) until
    * the DUT acks it.
    */
   extern virtual task body();

endclass : uvme_cv32e20_nmi_assert_c


function uvme_cv32e20_nmi_assert_c::new(string name="uvme_cv32e20_nmi_assert");

   super.new(name);

endfunction : new


task uvme_cv32e20_nmi_assert_c::body();

   uvma_interrupt_seq_item_c irq_req;

   repeat (initial_delay) @(cntxt.interrupt_cntxt.vif.drv_cb);

   `uvm_info("NMIASSERT", "Asserting NMI (irq_mask[0])", UVM_NONE)

   `uvm_create_on(irq_req, p_sequencer.interrupt_sequencer);
   start_item(irq_req);
   assert(irq_req.randomize() with {
     action       == UVMA_INTERRUPT_SEQ_ITEM_ACTION_ASSERT_UNTIL_ACK;
     repeat_count == 1;
     irq_mask     == 32'h1;
   });
   finish_item(irq_req);

   `uvm_info("NMIASSERT", "NMI asserted and acked", UVM_NONE)

endtask : body

`endif // __UVME_CV32E20_NMI_ASSERT_VSEQ_SV__
