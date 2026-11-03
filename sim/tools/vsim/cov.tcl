
# Coverage exclusions ("waivers") applied to the CVE2 design by the vsim
# invocation in mk/uvmt/vsim.mk (COV=1).  Each one is a single `coverage
# exclude` statement carrying a -comment that says why the thing it hides
# cannot be covered; the report targets that read the result (cov, cov_txt,
# cov_holes*) are in mk/uvmt/vsim.mk, and mk/uvmt/README.md plus the
# "Coverage" section of mk/README.md explain how to run them.
#
# Read this before quoting a measurement in a new waiver: every hit count and
# "N bins -> M bins" number below was taken against a merged .ucdb that has
# since been rebuilt from different sources, so it is history, not something a
# reviewer can re-check.  Re-derive it from the live
# sim/uvmt/vsim_results/<cfg>/merged/merged.ucdb (`make cov_holes MERGE=YES`)
# and quote that, or quote the command that produced it.  RTL line numbers drift
# the same way -- several exclusions here were silently pointing two lines off
# their intended target for exactly that reason, which is what the in-place
# NOTEs record.
#
# Re-derive line targets with:
#
#     bin/coverage_waiver_audit.py            # does every exclusion still bite?
#     bin/coverage_holes.py --apply-cov-tcl   # what is left open once they do?
#
# Both ask the live sim/uvmt/vsim_results/<cfg>/merged/merged.ucdb in a
# report-only vsim session and are documented in docs/coverage/README.md. The
# audit measures each statement by lifting it, because `coverage exclude`
# accepts a target that matches nothing without saying so. The last full re-aim
# (2026-11-01) moved twenty statements in six design units -- cve2_controller
# by twenty lines on its own -- and changed the count from 61 statements to the
# 64 it stood at then: two RVFI_CONNECT condition rows that a -linerange cannot
# reach, the U-mode CSR-read arms, minus an ls_fsm_e default-case waiver that
# measurement showed was hiding covered code rather than waiving a miss.
#
# Re-pin 2026-11-03 (CVE2 moved to upstream main @ d7f2156): rtl/
# cve2_id_stage.sv is the only file the new pin changes (+11/-2 lines, a
# register-file write-address mux plus the coprocessor result-address fix),
# so every other unit's line targets carried over unchanged (verified
# line-by-line against ce0fd917). The three cve2_id_stage statements below
# were re-aimed (+1/+9 shifts), one new CV-X-IF statement was added for the new
# mux's unreachable coprocessor arm, and two reset-transition statements were
# retired -- the batch covers what they excused. 63 statements; audit re-run.
#
# The dated NOTE blocks below quote RTL line numbers as they stood the day each
# one was written, and they keep those numbers on purpose: they are the audit
# trail of a drift fix, not a pointer into today's source. What has to agree
# with today's source is a waiver's own targets, and the audit above is what
# enforces that.

# Control variable for CV-X-IF exclusions, enabled only for the CV32E20X config
set XInterface 0
set CV_XIF_DISABLED_COMMENT {Only used when CV-X-IF is enabled (CV32E20X)}

# Bitmanip operations extension. Disabled for the CVE2.
set RVB 0
set RVB_DISABLED_COMMENT {RVB (Bitmanip) is disabled on the CVE2}

# U-mode support. cve2_cs_registers.sv:113 hardcodes
# `localparam int unsigned UmodeEnabled = 0` -- a bare localparam, not a
# module parameter, not wired to anything in cve2_core.sv/cve2_top.sv (this
# is nonetheless the CVE2 "umode" branch). If UmodeEnabled is ever wired up,
# every exclusion gated on this variable needs revisiting.
set UmodeEnabled 0
set UMODE_DISABLED_COMMENT {UmodeEnabled=0 is hardcoded in cve2_cs_registers.sv -- umode_control is permanently 0, so any check that could distinguish PRIV_LVL_U from PRIV_LVL_M is structurally unreachable.}


# cve2_load_store_unit
# ====================
#
#   Narrowed 2026-08-10 from a bare, undocumented, pre-existing bundle
#   (`-linerange 124 140 154 372-381 428-443`) that predates this session.
#   That bundle wrongly excluded genuinely reachable, exercised RTL: the
#   WAIT_GNT_MIS->WAIT_RVALID_MIS transition and the WAIT_RVALID_MIS case
#   item's own entry point (372-381) -- proven live via 530 hits on that
#   state's nested statements, which sit just outside the old range --
#   plus misaligned-write byte-enable generation (124, 140, 154) and part
#   of the FSM register's reset block (within 428-443). Only the `default:`
#   case of ls_fsm_e is genuinely dead (logic [2:0], 3 bits/8 encodings,
#   only 5 named/assigned anywhere in the FSM -- of the remaining 3
#   encodings no decode can ever be produced).
#
#   REMOVED 2026-11-01: the ls_fsm_e `default:` waiver (last target 447-448, the
#   `default: begin ls_fsm_ns = IDLE; end` of the next-state case) is gone. The
#   audit measures it as HIDING-COVERED-CODE -- lifting it returns two bins and
#   two hits and not one miss -- because Questa already credits the FSM's default
#   arm as exercised, so the waiver was deleting achieved coverage from the
#   metric instead of waiving a miss. The absence of a waiver on 447-448 is now
#   the measured state, which is the only reason it is worth a note here.

#   3 more genuinely dead lines found while narrowing the bundle above
#   (verified 2026-08-10):
#   - line 124 (2'b00: data_be = 4'b0000;, word-write "second part" case):
#     the address increment for a misaligned access's second half is always
#     exactly +4 (cve2_id_stage.sv:451, IMM_B_INCR_ADDR: imm_b = 32'h4;),
#     which never changes address bits [1:0] -- and word-access splitting
#     only triggers when the first part's data_offset != 2'b00 (line 329),
#     so the second part's data_offset (same bits, unchanged by +4) can
#     never be 2'b00. Matches the RTL's own comment ("this is not used").
#   - lines 140, 154 (default: data_be = 4'b1111;, half-word/byte cases):
#     both are `default:` inside `unique case (data_offset)`, a plain 2-bit
#     signal, with all 4 possible encodings (00/01/10/11) already
#     explicitly enumerated -- an exhaustive case, so its default can never
#     be entered.
#     NOTE (2026-08-12): these three -linerange targets were previously
#     122/138/152 -- stale by exactly 2 lines (same drift-by-2 pattern found
#     several more times this session, e.g. cve2_cs_registers' UmodeEnabled
#     block and the earlier cve2_cs_registers PMP-CSR-read exclusion).
#     Found via a design-wide branch-coverage holes sweep: clearing the
#     stale exclusions and inspecting the live report showed lines 138/152
#     (real, legitimate `2'b10:` case items, NOT defaults) had been
#     silently hidden from the coverage metric with real hits (14448 and
#     25749 respectively) never counted, while the genuinely dead defaults
#     at 140/154 remained open, uncounted misses the whole time. Fixed by
#     re-pointing at the current correct line numbers, verified via a
#     -viewcov dry run before applying to this file.
coverage exclude -du cve2_load_store_unit -linerange 124 -comment {Word-write second-part byte-enable: unreachable because the +4 address increment (cve2_id_stage.sv IMM_B_INCR_ADDR) never changes address bits [1:0], and splitting only triggers when the first part's data_offset is nonzero -- so the second part's data_offset can never be 2'b00. Matches the RTL's own comment.}
coverage exclude -du cve2_load_store_unit -linerange 140 -comment {default case of unique case (data_offset), a plain 2-bit signal with all 4 encodings (00/01/10/11) already explicitly enumerated, so the default can never be entered.}
coverage exclude -du cve2_load_store_unit -linerange 154 -comment {default case of unique case (data_offset), a plain 2-bit signal with all 4 encodings (00/01/10/11) already explicitly enumerated, so the default can never be entered.}

#   Lines 148 and 318 -- `lsu_type_i`/`data_type_q`'s `2'b11` value (both
#   drive `unique case`s where 2'b10/2'b11 are grouped as "byte"). Traced
#   the whole decoder assignment set for `data_type_o` (which feeds
#   `lsu_type_i` directly): it's initialized to `2'b00` at the top of
#   cve2_decoder.sv's single decode `always_comb` (line 227) and only ever
#   overridden inside the OPCODE_STORE (310-312: sb->2'b10, sh->2'b01,
#   sw->2'b00) and OPCODE_LOAD (327-330: lb(u)->2'b10, lh(u)->2'b01,
#   lw->2'b00) case blocks -- `2'b11` is never assigned anywhere. Line 148
#   (`2'b11: begin // Writing a byte`, grouped with the genuinely-hit
#   `2'b10` at line 147) and line 318 (`2'b10,2'b11: data_rdata_ext =
#   rdata_b_ext;`, `data_type_q` being the registered form of the same
#   never-2'b11 signal) are both structurally unreachable. Found 2026-08-12
#   auditing branch-coverage holes; verified via -viewcov dry run alongside
#   the fix above.
coverage exclude -du cve2_load_store_unit -linerange 148 -code b -comment {lsu_type_i can never be 2'b11: data_type_o (decoder) is initialized to 2'b00 and only ever overridden to 2'b00/01/10 in the STORE/LOAD case blocks.}
coverage exclude -du cve2_load_store_unit -linerange 318 -code b -comment {data_type_q (registered lsu_type_i) can never be 2'b11, same root cause as line 148.}

#   ls_fsm_cs FSM transition: WAIT_GNT_MIS -> IDLE. Same pattern/rationale
#   as ctrl_fsm_cs and md_state_q above: NOT dead code -- WAIT_GNT_MIS's
#   only functional next-state target is WAIT_RVALID_MIS (line 381); the
#   only way to reach IDLE from WAIT_GNT_MIS is the async reset
#   (`ls_fsm_cs <= IDLE;`, line 456, inside `if (!rst_ni)`), which is a
#   real, reachable scenario, just untested by the current suite (same
#   mid-run-reset gap as the other two FSMs). Excluded per the same
#   explicit user decision (2026-08-10).
coverage exclude -du cve2_load_store_unit -ftrans ls_fsm_cs {WAIT_GNT_MIS->IDLE} -comment {rst_ni can legitimately drop while in WAIT_GNT_MIS -- not dead code, an accepted untested-stimulus gap (mid-run reset injection).}

#   Lines 377, 392, 419: `(data_gnt_i||pmp_err_q)`/`(data_rvalid_i||pmp_err_q)`.
#   pmp_err_q is a register fed by the module input data_pmp_err_i (lines
#   355/394/435: pmp_err_d = data_pmp_err_i), which traces up through
#   cve2_core.sv:591 to pmp_req_err[PMP_D]. With PMPEnable hardcoded false
#   (cve2_top.sv:128), elaboration always takes the g_no_pmp branch
#   (cve2_core.sv:854-869), which ties pmp_req_err[PMP_D] = 1'b0 as a
#   constant net, not a runtime-gated 0. So pmp_err_d can only ever be
#   assigned 1'b0 or hold its already-0 previous value, and pmp_err_q
#   (reset to '0) can never become 1 -- the pmp_err_q_1 FEC row in each of
#   these three conditions is structurally unreachable, same PMPEnable=0
#   dead-code family as the existing cve2_cs_registers PMP-CSR-read
#   exclusion above. Confirmed empirically: 0 hits across all 32
#   regression tests while the sibling data_gnt_i/data_rvalid_i rows hit
#   normally.
coverage exclude -du cve2_load_store_unit -feccondrow 377 4 -comment {pmp_err_q can never be 1: PMPEnable is hardcoded false (cve2_top.sv:128), so pmp_req_err[PMP_D] is tied to a constant 1'b0 at elaboration (cve2_core.sv g_no_pmp branch), and data_pmp_err_i (driving pmp_err_d) inherits that constant.}
coverage exclude -du cve2_load_store_unit -feccondrow 392 4 -comment {pmp_err_q can never be 1: PMPEnable is hardcoded false (cve2_top.sv:128), so pmp_req_err[PMP_D] is tied to a constant 1'b0 at elaboration (cve2_core.sv g_no_pmp branch), and data_pmp_err_i (driving pmp_err_d) inherits that constant.}
coverage exclude -du cve2_load_store_unit -feccondrow 419 4 -comment {pmp_err_q can never be 1: PMPEnable is hardcoded false (cve2_top.sv:128), so pmp_req_err[PMP_D] is tied to a constant 1'b0 at elaboration (cve2_core.sv g_no_pmp branch), and data_pmp_err_i (driving pmp_err_d) inherits that constant.}


# cve2_compressed_decoder
# =======================
#
#   Unreachable default cases. The label
#   line itself (CASE Branch bin) and the dead statement inside it (Statement
#   bin) are separate coverage bins -- both need excluding.
coverage exclude -du cve2_compressed_decoder -linerange 75-76 177-178 183-184 197-198 265-266
#   A commented-out "To review" exclusion over lines 121 221 233 246 used to sit
#   here. Deleted 2026-11-01: cve2_compressed_decoder has no open hole in the
#   merged database, so every one of those lines is covered, and a waiver over
#   covered code only ever understates the metric (the audit's
#   HIDING-COVERED-CODE).

# cve2_if_stage
# =============
#
# Exclude dummy DPI functions needed by the former RISC-V compliance checking simulation model
# See rtl/cve2_if_stage.sv for more info
coverage exclude -du cve2_if_stage -linerange 181-194 -comment {Dummy sim-only simutil_get_scramble_key and simutil_get_scramble_nonce functions}
#   Two more commented-out "To review" exclusions used to sit in this section
#   (line 156 here, line 608 below the cve2_id_stage block). Both deleted
#   2026-11-01 for the same reason as the compressed-decoder one above:
#   cve2_if_stage has no open hole in the merged database.


# cve2_id_stage
# =============
#   NOTE (2026-11-03): re-aimed 883-884 -> 892-893 for the d7f2156 re-pin --
#   rtl/cve2_id_stage.sv grew a register-file write-address mux at its line
#   500, shifting everything below by 9. Target unchanged: the `default:`
#   arm of the id_fsm_q next-state case (`default: begin id_fsm_d =
#   FIRST_CYCLE;`), verified verbatim at 892-893 of the pinned file.
coverage exclude -du cve2_id_stage -linerange 892-893 -comment {Default case for the id_fsm_q signal}

# cve2_controller
# ===============
#
#   instr_err_i and data_err_i are hardwired to 1'b0 in the design being
#   verified (confirmed by the user, 2026-08-10) -- so instr_fetch_err_i,
#   load_err_i, and store_err_i (which trace back through cve2_if_stage.sv/
#   cve2_load_store_unit.sv to those two ports) are permanently 0, making
#   the whole instr_fetch_err_prio/store_err_prio/load_err_prio access-fault
#   exception path structurally dead:
#   - lines 257/265/267: the true branch of each `if`/`else if` (only the
#     false/fall-through side, checking the next priority, is reachable)
#   - lines 258/266/268: the *_prio = 1'b1; statements those true branches
#     guard
#   - lines 625/670/674: the corresponding CASE branch items in the
#     exception-cause selection (unique case (1'b1) ...), and lines
#     626-627/671-672/675-676: the exc_cause_o/csr_mtval_o statements
#     inside them
#   - line 612 (`exc_req_q || store_err_q || load_err_q`): NOT excluded
#     wholesale -- exc_req_q remains genuinely reachable (illegal
#     instruction/ecall/ebreak/instr_fetch_err all still flow through it).
#     Only the store_err_q/load_err_q input *terms* are dead -- condition-
#     only exclusion (-code c), same precision as the UmodeEnabled block.
#
set BusErrSupported 0
set BUS_ERR_DISABLED_COMMENT {instr_err_i/data_err_i are hardwired to 1'b0 in the design being verified -- the access-fault exception path they feed is structurally unreachable.}
if {!$BusErrSupported} {
    coverage exclude -du cve2_controller -linerange 257 258 265 266 267 268 -comment $BUS_ERR_DISABLED_COMMENT
    coverage exclude -du cve2_controller -linerange 625 626-627 -comment $BUS_ERR_DISABLED_COMMENT
    coverage exclude -du cve2_controller -linerange 670 671-672 -comment $BUS_ERR_DISABLED_COMMENT
    coverage exclude -du cve2_controller -linerange 674 675-676 -comment $BUS_ERR_DISABLED_COMMENT
    coverage exclude -du cve2_controller -feccondrow 612 4 -comment $BUS_ERR_DISABLED_COMMENT
    coverage exclude -du cve2_controller -feccondrow 612 6 -comment $BUS_ERR_DISABLED_COMMENT
}

#   cve2_controller.sv:678 -- `default: ;` in the exception-cause priority
#   `unique case (1'b1) instr_fetch_err_prio: ... illegal_insn_prio: ...
#   ecall_insn_prio: ... ebrk_insn_prio: ... store_err_prio: ...
#   load_err_prio: ... default: ; endcase` (line 624). Unreachable, not
#   config-dependent: the RTL's own comment at line 623 states "Exception/
#   fault prioritisation logic will have set exactly 1 X_prio signal", and
#   this one-hot guarantee is independently enforced by the
#   CVE2ExceptionPrioOnehot assertion elsewhere in this file -- entering
#   this case at all (gated by `exc_req_q || store_err_q || load_err_q` at
#   line 612) already guarantees exactly one of the six named arms matches.
#   Found 2026-08-12 auditing branch-coverage holes.
#
coverage exclude -du cve2_controller -linerange 678 -code b -comment {default arm of a one-hot exception-priority case (unique case (1'b1)), unreachable: RTL comment + the CVE2ExceptionPrioOnehot assertion both guarantee exactly one of the six named priority signals is set whenever this case is entered.}

#   cve2_controller.sv:521 `(irq_nm_i && ~nmi_mode_q)` -- one FEC row of this
#   2-term condition, "nmi_mode_q sensitized to 1" (nmi_mode_q_1, the row
#   requiring irq_nm_i to be checked again while nmi_mode_q is already 1,
#   i.e. NMI re-asserted/held while already servicing a prior NMI), is
#   structurally unreachable, not an untested-stimulus gap: this line is
#   only ever evaluated during the single-cycle IRQ_TAKEN FSM state
#   (line 510), which is only entered via handle_irq (line 496-498), and
#   handle_irq is unconditionally 0 whenever nmi_mode_q==1 (line 321-322:
#   `assign handle_irq = ~debug_mode_q & ~nmi_mode_q & ...`, with the RTL's
#   own comment: "while in NMI mode (nested NMIs are not supported, NMI has
#   highest priority and cannot be interrupted by regular interrupts)").
#   So the FSM can never even reach the state that checks this condition
#   while nmi_mode_q is already 1. Confirmed two ways: the RTL trace above,
#   and empirically -- a dedicated stimulus attempt that held irq_nm_i
#   asserted for several cycles squarely inside an active NMI handler
#   (verified via log timestamps) still left this row at 0 hits. The other
#   rows of this same condition, and the nmi_mode_q branch on mret (line
#   686), are genuinely reachable and already covered by nmi_test -- only
#   this one row is excluded.
coverage exclude -du cve2_controller -feccondrow 521 4 -comment {Nested NMI (irq_nm_i sensitized while nmi_mode_q==1) is structurally unreachable: entry into the only FSM state that evaluates this condition (IRQ_TAKEN) requires handle_irq, which is unconditionally 0 whenever nmi_mode_q==1 (cve2_controller.sv:321-322, explicit RTL comment: nested NMIs not supported).}

#   cve2_controller.sv:514 `if (handle_irq) begin` (inside IRQ_TAKEN) --
#   its false arm ("All False Count") is a real branch-coverage miss, left
#   DELIBERATELY UNEXCLUDED (user decision, 2026-08-12): this is
#   `irq_withdrawn_in_taken` (see the `` `ifdef INC_ASSERT `` block further
#   down in cve2_controller.sv) -- an interrupt can be
#   committed (DECODE->IRQ_TAKEN, handle_irq=1 at commit) and then
#   withdrawn one cycle later, right as IRQ_TAKEN would perform the PC
#   redirect. This is genuinely reachable and has been empirically
#   confirmed once via a cycle-accurate signal dump on
#   corev_rand_interrupt_exception -- not dead code, just a rare,
#   interrupt-noise-timing-dependent window that doesn't reproduce on
#   every regression seed.
#   Superseded 2026-11-01: classified B-new-test rather than accepted, and the
#   directed test written for it (irq_withdraw_test, which pulses the NMI line
#   -- not irq_pending_i -- and withdraws it) now builds, runs and PASSES.
#   MEASURED 2026-11-01 (seed 1, Questa One 2025.3_2, USE_ISS=NO): the bin is
#   still a miss, and the reason is the agent, not the timing lottery. 3008
#   assert/deassert pulses produced exactly one DECODE->IRQ_TAKEN commit, and
#   line 514 was evaluated twice, true both times. In
#   uvma_interrupt_drv_c, wait_and_assert_irq_edge() holds every rising edge
#   for two cycles and irq_ack_clear() only drops the line after it samples
#   irq_ack -- which is no DUT signal at all: CVE2's interrupts are
#   level-sensitive and the controller's entire interrupt interface is the
#   irq_pending_i/irqs_i/irq_nm_i inputs (cve2_controller.sv:66-72). What the
#   agent waits for is the testbench's own
#   tb/uvmt/uvmt_cv32e20_dut_wrap.sv:107 `ctrl_fsm_cs == 4'h7` -- 4'h7 is
#   IRQ_TAKEN, the eighth member of the module-local ctrl_fsm_e at
#   cve2_controller.sv:106-109 -- so the ack is high during the IRQ_TAKEN cycle
#   itself: the driver samples it at that cycle's end and drives low on the
#   next edge, when the FSM has already left IRQ_TAKEN. One cycle too late, and
#   no hold/gap setting is earlier.
#   The 2026-08-12 note above that this had been confirmed once cannot be
#   reproduced from any database that still exists: the merged .ucdb
#   (md5 7d8c430e78b4648bb75c8a0b4b6c7670) has 433 evaluations, 0 on this arm.
#   Still left unexcluded, and still not waivable under the policy of
#   docs/coverage/coverage_review.md -- what is unreachable here is the
#   stimulus path, not the RTL. Closing it means a cycle-accurate irq stimulus
#   below uvma_interrupt_drv_c: drive irq_nm low for one cycle from tb/uvmt/,
#   which is where ctrl_fsm_cs is already probed -- vendor_lib/ holds a
#   git-ignored clone of upstream core-v-verif, so the driver itself is not
#   ours to patch. Row H001 of docs/coverage/coverage_review.csv and the last
#   row of docs/coverage/raw/phase_c_acceptance.csv carry the measurement.

#   cve2_controller.sv:416 (SLEEP state's wfi wake condition)
#   `(irq_nm_i || irq_pending_i || debug_req_i || debug_mode_q ||
#   debug_single_step_i)` -- the `debug_single_step_i_1` FEC row (this term
#   sensitized to 1, all others 0) is structurally unreachable, same
#   "dead, not untested" category as the NMI row above. Reaching this line
#   at all requires a `wfi` to have already completed the FLUSH -> WAIT_SLEEP
#   -> SLEEP transition. But whenever `debug_single_step_i` (dcsr.step) is
#   1, `do_single_step_d` (line 296) goes high the moment `wfi` first
#   becomes `instr_valid_i` (in DECODE, before the special_req-triggered
#   move to FLUSH), so `enter_debug_mode_prio_q` (line 307's registered
#   form) is already 1 by the time FLUSH actually processes the `wfi` --
#   and line 713's `if (enter_debug_mode_prio_q && ...) ctrl_fsm_ns =
#   DBG_TAKEN_IF;` runs *after* (overrides) the `wfi_insn` branch's
#   `ctrl_fsm_ns = WAIT_SLEEP` (line 695) in the same always_comb block,
#   same cycle. So a single-stepped `wfi` is redirected straight back to
#   debug mode and never actually reaches WAIT_SLEEP/SLEEP -- matching
#   `tests/programs/custom/debug_test/single_step.S`'s own comment ("we are
#   single stepping, WFI should complete as NOP"). Confirmed two ways: the
#   RTL trace above, and empirically -- `debug_test` already exercises
#   exactly this scenario (single-step directly over a `wfi`, `single_step.S`
#   line 63) and still leaves this row at 0 hits even though line 416 itself
#   is reached (via ordinary, non-single-stepped `wfi` wake-ups elsewhere in
#   the same test). The other 4 terms of this condition are genuinely
#   reachable and already covered -- only this one row is excluded.
coverage exclude -du cve2_controller -feccondrow 416 10 -comment {debug_single_step_i sensitized (all other wake terms 0) while in SLEEP is structurally unreachable: a single-stepped wfi always re-enters debug mode via enter_debug_mode_prio_q (cve2_controller.sv:713) before it can complete the FLUSH->WAIT_SLEEP->SLEEP transition, so debug_single_step_i can never be the sole wake reason once SLEEP is actually reached.}

#   ctrl_fsm_cs FSM transitions: <STATE> -> RESET, of the 9 non-RESET states
#   8 remain excluded (DECODE->RESET was retired on measurement 2026-11-03,
#   see the MEASURED note below).
#   NOT dead code -- rst_ni is a real async input (see the `if (!rst_ni)`
#   branch of update_regs, line 753) that can legitimately drop while the
#   controller is in any state; these edges are genuinely reachable, just
#   untested by the current suite (every test only resets once, at t=0,
#   before the FSM has left RESET -- none exercise a mid-run reset).
#   Excluded per explicit user decision (2026-08-10) to accept this as an
#   untested stimulus gap rather than build new reset-injection test
#   infrastructure right now.
#   MEASURED 2026-11-01: mid_run_reset_test exists now, passes (12 seeds), and
#   one asynchronous pulse retires exactly one row of this set -- DECODE->RESET,
#   hit on 12 of 12 seeds. Nothing else here is reachable with it:
#   BOOT_SET/FIRST_FETCH are the one-cycle states immediately after the reset
#   this sequence itself releases (its randomized delay is bounded below at 10
#   cycles), WAIT_SLEEP/SLEEP need a wfi the paired program deliberately does
#   not contain, DBG_TAKEN_IF/DBG_TAKEN_ID/IRQ_TAKEN need debug and interrupt
#   stimulus it does not drive, and FLUSH needs an exception. So the other eight
#   stay; per-target numbers are in
#   docs/coverage/raw/phase_c_acceptance.csv. The one that is covered stays
#   excluded too, until a merged batch database contains the test -- retiring
#   it against the current merge would only lower the reported number.
#   MEASURED 2026-11-03: that moment arrived -- the 43-test --cov-report batch
#   (upstream d7f2156 RTL) merged mid_run_reset_test into the default database,
#   and bin/coverage_waiver_audit.py measured DECODE->RESET as
#   HIDING-COVERED-CODE. Per the policy (never waive a target that has hits)
#   that exclusion is deleted below; the other eight edges the 2026-11-01
#   measurement cleared as unreachable with one pulse stay.
set CTRL_FSM_RESET_TRANS_COMMENT {rst_ni can legitimately drop from any controller state -- not dead code, an accepted untested-stimulus gap (mid-run reset injection).}
coverage exclude -du cve2_controller -ftrans ctrl_fsm_cs {BOOT_SET->RESET} -comment $CTRL_FSM_RESET_TRANS_COMMENT
coverage exclude -du cve2_controller -ftrans ctrl_fsm_cs {FIRST_FETCH->RESET} -comment $CTRL_FSM_RESET_TRANS_COMMENT
coverage exclude -du cve2_controller -ftrans ctrl_fsm_cs {WAIT_SLEEP->RESET} -comment $CTRL_FSM_RESET_TRANS_COMMENT
coverage exclude -du cve2_controller -ftrans ctrl_fsm_cs {SLEEP->RESET} -comment $CTRL_FSM_RESET_TRANS_COMMENT
coverage exclude -du cve2_controller -ftrans ctrl_fsm_cs {DBG_TAKEN_IF->RESET} -comment $CTRL_FSM_RESET_TRANS_COMMENT
coverage exclude -du cve2_controller -ftrans ctrl_fsm_cs {IRQ_TAKEN->RESET} -comment $CTRL_FSM_RESET_TRANS_COMMENT
coverage exclude -du cve2_controller -ftrans ctrl_fsm_cs {FLUSH->RESET} -comment $CTRL_FSM_RESET_TRANS_COMMENT
coverage exclude -du cve2_controller -ftrans ctrl_fsm_cs {DBG_TAKEN_ID->RESET} -comment $CTRL_FSM_RESET_TRANS_COMMENT

# cve2_multdiv_fast
# =================
#
#   md_state_q (divider FSM) transitions: <STATE> -> MD_IDLE, of the 5
#   non-MD_IDLE states 4 remain excluded (MD_COMP->MD_IDLE was retired on
#   measurement 2026-11-03, see below). Same pattern/rationale as
#   ctrl_fsm_cs above: NOT
#   dead code -- `md_state_q <= MD_IDLE;` sits inside the `if (!rst_ni)`
#   branch (line 99), so rst_ni dropping mid-divide is a real, reachable
#   scenario, just untested by the current suite. Excluded per the same
#   explicit user decision (2026-08-10).
#
#   RESOLVED 2026-08-12 (was previously left unexcluded as "ambiguous",
#   2026-08-10): mult_state_q (the multiply FSM in the same file/instance)
#   has its own single miss, ALBH->ALBL, which is the exact same
#   async-reset-artifact pattern as md_state_q above -- it just wasn't
#   obviously so before, since this FSM resets into a real, named
#   functional state (ALBL) rather than a dedicated RESET/MD_IDLE-style
#   value. Confirmed via RTL trace: ALBH's own case-arm body (line 313)
#   unconditionally sets mult_state_d = AHBL -- there is no functional
#   path where ALBH transitions directly to ALBL. The only way to produce
#   this edge is rst_ni dropping while in ALBH (`mult_state_q <= ALBL;`,
#   line 362, inside the async `if (!rst_ni)` branch), which Questa's FSM
#   extractor models as an implicit edge from every state to the reset
#   value. Same accepted-gap category and same explicit user decision as
#   every other reset-transition exclusion in this file.
#
#   MEASURED 2026-11-01 (mid_run_reset_test, 12 seeds): MD_COMP->MD_IDLE is
#   genuinely hit, on 8 of 12 seeds -- MD_COMP is the divider's only long
#   state, and the other four are one cycle each out of a ~35-cycle divide,
#   which is why none of them was ever caught. ALBH->ALBL below was caught on
#   one seed out of twelve. Neither is retired: one seed of this test covers
#   one or two of the 16, and the merged database these waivers are measured
#   against does not contain the test yet.
#   MEASURED 2026-11-03 (same test merged into the 43-test default batch,
#   upstream d7f2156 RTL): the audit now measures MD_COMP->MD_IDLE as
#   HIDING-COVERED-CODE, so that exclusion is deleted below. ALBH->ALBL stays
#   VALID -- this batch's seed did not land the pulse in its one-cycle window
#   (1 of 12 seeds in the 12-seed measurement), so its edge is still a real
#   miss the waiver is paying for.
set MD_FSM_RESET_TRANS_COMMENT {rst_ni can legitimately drop mid-divide -- not dead code, an accepted untested-stimulus gap (mid-run reset injection).}
coverage exclude -du cve2_multdiv_fast -ftrans md_state_q {MD_ABS_A->MD_IDLE} -comment $MD_FSM_RESET_TRANS_COMMENT
coverage exclude -du cve2_multdiv_fast -ftrans md_state_q {MD_ABS_B->MD_IDLE} -comment $MD_FSM_RESET_TRANS_COMMENT
coverage exclude -du cve2_multdiv_fast -ftrans md_state_q {MD_LAST->MD_IDLE} -comment $MD_FSM_RESET_TRANS_COMMENT
coverage exclude -du cve2_multdiv_fast -ftrans md_state_q {MD_CHANGE_SIGN->MD_IDLE} -comment $MD_FSM_RESET_TRANS_COMMENT
coverage exclude -du cve2_multdiv_fast -ftrans gen_mult_fast/mult_state_q {ALBH->ALBL} -comment {rst_ni can legitimately drop mid-multiply -- not dead code, an accepted untested-stimulus gap (mid-run reset injection), same as the md_state_q transitions above. Note the FSM variable needs the gen_mult_fast/ generate-block qualifier here (unlike md_state_q, which isn't inside a generate block) -- confirmed via a -viewcov dry run after the bare "mult_state_q" form silently matched nothing.}


#   A commented-out "To review" exclusion over cve2_if_stage lines 430 448 used
#   to sit here; deleted 2026-11-01 with the other two, same reason.
#
# cve2_decoder
# ============
#
#   Unreachable default cases: instr[14:12]/instr_alu[14:12] funct3 dispatch
#   is exhaustive over 3 bits (both dispatches below re-checked arm-by-arm
#   against cve2_decoder.sv on 2026-10-31). Line 448 was previously mistakenly
#   excluded under -du cve2_if_stage, which is a 297-line file -- that
#   exclusion was a silent no-op.
#
#   line 439 (illegal_insn = 1'b1;, inside the 5'b0_0001/unshfl case item's
#   `if (instr[26]==1'b0) ... else` at line 436) is unreachable: this whole
#   case(instr[31:27]) block is only entered from the `else` of the outer
#   `if (instr[26]) begin // fsri ... end else begin` at line 404-406, which
#   already constrains instr[26]==1'b0 for everything inside it -- so the
#   inner `else` at 436 (instr[26]==1'b1) can never be taken. Previously
#   excluded (correctly identified, wrong DU) under -du cve2_if_stage.
#
#   line 930 is `default: ;`, the default arm of `unique case
#   (instr_alu[14:12])` (cve2_decoder.sv:811) inside the OPCODE_OP_IMM arm of
#   the ALU-control `unique case (opcode_alu)`. Unreachable for the same
#   exhaustive-3-bits reason as line 448 above, one level deeper and on the
#   ALU-side copy of the instruction (instr_alu = instr_rdata_alu_i,
#   cve2_decoder.sv:130): the arms enumerate every encoding of the 3-bit
#   selector -- 3'b000/010/011/100/110/111 at 812-817, 3'b001 at 819, 3'b101
#   at 886 -- so no value can fall through to the default. Only an X/Z selector
#   could, and instr_alu is the timing replica of instr (lines 126-130), whose
#   funct3 the RTL constrains itself: the CVE2RegImmAluOpKnown assertion (line
#   1190, `(opcode == OPCODE_OP_IMM) |-> !$isunknown(instr[14:12])`).
#
coverage exclude -du cve2_decoder -linerange 439 448
coverage exclude -du cve2_decoder -linerange 930 -comment {default arm of unique case (instr_alu[14:12]) in the OPCODE_OP_IMM decode (cve2_decoder.sv:811): unreachable, its arms enumerate all eight encodings of the 3-bit selector (3'b000/010/011/100/110/111 at 812-817, 3'b001 at 819, 3'b101 at 886), so this is an exhaustive case -- same shape as the line-448 exclusion above.}

#   Branch-level exclusion for the same finding above, added 2026-08-12
#   while auditing branch-coverage holes: the statement exclusion at 439
#   never covered the `if` decision itself, which Questa associates with
#   line 438 (the `end else begin` of the inner `if (instr[26]==1'b0)`,
#   itself already inside the outer instr[26]==1'b0-only scope). Verified
#   via -viewcov dry run that this removes only the dead miss bin (264
#   bins/254 hits/10 misses -> 263/254/9), no side effect on the sibling
#   (legitimate, hit) true-arm bin -- same "explicit else on its own line
#   excludes surgically" shape as cve2_alu.sv:284 found in the same
#   session.
coverage exclude -du cve2_decoder -linerange 438 -code b -comment {Unreachable: this if (instr[26]==1'b0) is nested inside an outer scope that already constrains instr[26]==1'b0 for everything inside it (cve2_decoder.sv:404-406), so this inner else (instr[26]==1'b1) can never be taken. Same root cause as the line-439 statement exclusion above.}

# cve2_tracer
# ===========
#
#   Excluded entirely. This is a simulation-only instruction/CSR disassembler
#   for the trace log, not DUT behavior: almost all of its statement misses
#   are individual entries in a large CSR-address-to-name / instruction-
#   mnemonic-to-string lookup table (implemented-but-untested CSRs, CSR names
#   for S-mode/H-mode/legacy addresses only reachable via illegal CSR
#   accesses, RV32B mnemonics only reachable via illegal RV32B encodings).
#   None of it is dead code -- every entry is reachable given the right raw
#   instruction bits -- but it's an inherently large, sparse decode space
#   that isn't a meaningful coverage-quality signal for the DUT itself.
coverage exclude -du cve2_tracer -comment {Simulation-only disassembler for the trace log, not DUT behavior}

# cve2_cs_registers
# =================
#
#   The UmodeEnabled=0 exclusions for this file (mstatus_d.mprv = 1'b0 at
#   line 699, plus the mstatus_d.mpp/dcsr_d.prv vs PRIV_LVL_U conditions at
#   553/581/698) live in the UmodeEnabled-gated block near the bottom of
#   this file, alongside the matching cve2_controller exclusions -- same
#   root cause, single toggle point.
#
#   PMPCFG0-3/PMPADDR0-15 CSR read case items (361-384): a prior exclusion
#   here (-linerange 372-395) was WRONG on two counts, found 2026-08-12 while
#   investigating branch-coverage holes. (1) Its dead-code premise doesn't
#   hold: the read logic is NOT gated by a guard before the case -- the
#   `unique case (csr_addr_i)` runs unconditionally (csr_addr = csr_addr_i
#   directly, no legalization), and the `if (!PMPEnable) ... illegal_csr =
#   1'b1;` override sits AFTER `endcase` (lines 491-499), not wrapping it.
#   So any real CSR instruction targeting a PMP address DOES select these
#   case items and execute the read -- illegal_csr is only forced true
#   afterward, meaning the access still traps, but the RTL line itself is
#   reachable. Same category as the already-untouched illegal_csr override
#   line, which this file's comment always correctly called "genuinely
#   reachable... untested", not dead. (2) Its line range was also stale --
#   372-395 doesn't even cover the real PMPCFG0-3/PMPADDR0-2 case items
#   (361-371), and instead wrongly swallowed CSR_DCSR/CSR_DPC/CSR_DSCRATCH0's
#   `begin` blocks (386-395+), silently hiding real, well-tested code from
#   the coverage metric instead of counting it as covered. Closed with real
#   stimulus instead of a corrected exclusion: illegal_instr_test.S gained
#   one hand-built `csrrw x0,<pmp-csr>,x0` per PMPCFG0-3/PMPADDR0-15 (20
#   entries).

#   Lines 1471-1590 (the whole `ifdef RVFI ... endif` block: `ifdef RVFI` is
#   itself line 1471, and the CSR list is the `RVFI_CONNECT` macro use at
#   1575-1588) are RVFI
#   (RISC-V Formal Interface) monitoring plumbing: structs/wires that
#   reformat already-existing DUT state (mstatus_q.mie, mip.irq_software,
#   etc.) for the RVFI monitor/co-simulation interface, plus the
#   RVFI_CONNECT-macro-generated per-CSR read/write-mask tracking
#   (mstatus/mie/mip/misa/mtvec/mepc/mcause/mtval/mstatush/dcsr/dpc/
#   dscratch0/dscratch1/mscratch). `RVFI` is only ever defined via
#   `+define+CV32E20_RVFI+RVFI` in sim/uvmt/Makefile -- a verification-
#   testbench-only compile flag, never present for synthesis. Same
#   category as the cve2_tracer exclusion above: simulation/monitoring-
#   only, not DUT behavior. Originally investigated as a genuine "thin
#   CSR software-write coverage" gap (the repeated `RVFI_CONNECT`
#   write-mask condition never going true for MIP/MISA/MTVEC/MEPC/MCAUSE/
#   MTVAL/MSTATUSH/DSCRATCH1) before the ifdef boundary was noticed --
#
coverage exclude -du cve2_cs_registers -linerange 1471-1590 -comment {RVFI (RISC-V Formal Interface) monitoring plumbing -- only compiled for the verification testbench (+define+RVFI in sim/uvmt/Makefile), never for synthesis. Not DUT behavior.}

#   ... but a -linerange excludes lines, and an FEC condition row is not a line.
#   Two rows of the RVFI_CONNECT write-mask conditions survived the block waiver
#   above and were the design's last two open condition misses: the
#   `csr_op_en_i` input term of the CSR_MCAUSE (line 1581) and CSR_DSCRATCH0
#   (line 1586) expansions, which can never be exercised because a CSR write
#   with op_en set to those addresses never arrives from the ID stage while the
#   RVFI copy is what the monitor samples. Same block, same reason, so the same
#   -comment variable; needs the row-level exclusion.
set RVFI_DISABLED_COMMENT {RVFI (RISC-V Formal Interface) monitoring plumbing -- only compiled for the verification testbench (+define+RVFI in sim/uvmt/Makefile), never for synthesis. Not DUT behavior.}
coverage exclude -du cve2_cs_registers -feccondrow 1581 5 -comment $RVFI_DISABLED_COMMENT
coverage exclude -du cve2_cs_registers -feccondrow 1586 5 -comment $RVFI_DISABLED_COMMENT

#   cve2_core.sv:1152/1154/1156 -- `instr_valid_id | ~captured_valid`, used to
#   select live vs. captured mip/nmi/debug_req values for the RVFI ext-stage
#   tracking pipeline. In each, FEC Row 2 (instr_valid_id sensitized true
#   while captured_valid==1) is structurally unreachable: instr_valid_id is
#   if_stage_i.instr_valid_id_q (cve2_core.sv:328), and captured_valid can
#   only be *set* while instr_valid_id==0 (line 1119: `~instr_valid_id & ...`).
#   captured_valid is *cleared* on exactly the edge that
#   if_stage_i.instr_valid_id_d is 1 (line 1133) -- the same signal that
#   drives instr_valid_id_q to 1 on that edge (cve2_if_stage.sv:244-245). So
#   the only transition of instr_valid_id 0->1 always coincides with
#   captured_valid being cleared to 0 on that same edge: instr_valid_id==1
#   and captured_valid==1 can never hold simultaneously. Confirmed empirically
#   too -- Row 1 of the same condition hits repeatedly across the regression
#   (including heavy interrupt/debug/nmi tests) while Row 2 never hits once.
#
coverage exclude -du cve2_core -feccondrow 1152 2 -comment {instr_valid_id==1 while captured_valid==1 is structurally unreachable: both are driven from if_stage_i.instr_valid_id_d/_q, and the only 0->1 transition of instr_valid_id coincides with captured_valid being cleared on the same edge.}
coverage exclude -du cve2_core -feccondrow 1154 2 -comment {instr_valid_id==1 while captured_valid==1 is structurally unreachable: both are driven from if_stage_i.instr_valid_id_d/_q, and the only 0->1 transition of instr_valid_id coincides with captured_valid being cleared on the same edge.}
coverage exclude -du cve2_core -feccondrow 1156 2 -comment {instr_valid_id==1 while captured_valid==1 is structurally unreachable: both are driven from if_stage_i.instr_valid_id_d/_q, and the only 0->1 transition of instr_valid_id coincides with captured_valid being cleared on the same edge.}

#   Exclude coverage for ID stage when CV-X-IF is disabled
#
#   NOTE (2026-11-03): re-aimed for the d7f2156 re-pin -- 494 -> 495 (+1) and
#   829-832 -> 838-841 (+9), both verified verbatim against the pinned file
#   (the rf_wdata_id_mux coprocessor arm; the alu_multicycle_dec case arm).
#   The pin also added the rf_waddr_id_mux block (new 500-507), whose
#   RF_WD_COPROC line 503 is the same shape as the rf_wdata_id_mux one it
#   sits under: rf_wdata_sel can only take RF_WD_COPROC through the
#   coprocessor paths that do not exist when XInterface is 0, so that case
#   item is never selected and the `default:` arm carries the mux alone.
if {!$XInterface} {
    coverage exclude -du cve2_id_stage -linerange 495 -comment $CV_XIF_DISABLED_COMMENT
    coverage exclude -du cve2_id_stage -linerange 503 -comment $CV_XIF_DISABLED_COMMENT
    coverage exclude -du cve2_id_stage -linerange 838-841 -comment $CV_XIF_DISABLED_COMMENT

    #   cve2_controller.sv:473,492,498 -- `ctrl_fsm_ns = xif_scoreboard_busy_i
    #   ? DECODE : <FLUSH|DBG_TAKEN_IF|IRQ_TAKEN>;`. xif_scoreboard_busy_i is
    #   fed from cve2_id_stage.sv's scoreboard_busy, which the no_gen_xif
    #   generate branch (entered whenever XInterface is disabled,
    #   cve2_id_stage.sv:389, the `else begin: no_gen_xif` at 377) hardwires to
    #   `1'b0` -- so the DECODE arm of
    #   each ternary can never be taken. Found 2026-08-12 auditing
    #   branch-coverage holes.
    coverage exclude -du cve2_controller -linerange 473 492 498 -code b -comment $CV_XIF_DISABLED_COMMENT
}

# Exclude coverage for RVB (Bitmanip) extension
if {!$RVB} {
    coverage exclude -du cve2_alu -linerange 88-90 285 288-289 308-315 319 376-378 1342 1345 1355 1359 1363 1366 1369-1378 1381-1382 1385 1388 1391-1392 -comment $RVB_DISABLED_COMMENT

    #   Branch-level RVB-disabled dead code found 2026-08-12 while auditing
    #   cve2_alu's branch-coverage holes (the -linerange block above only
    #   ever targeted statement coverage for a different, smaller set of
    #   lines -- these are a genuinely separate, much larger set of ALU
    #   case-item/if-branch decision points never previously excluded at
    #   -code b). All confirmed via the decoder: every RV32B-only ALU
    #   opcode (ALU_MIN/MINU/MAX/MAXU, ALU_SH1ADD/SH2ADD/SH3ADD,
    #   ALU_XNOR/ORN/ANDN, ALU_SLO/SRO, ALU_CLZ/CTZ, ALU_PACK/PACKH) is only
    #   ever assigned to alu_operator_o inside an `if (RV32B != RV32BNone)`
    #   (or narrower RV32BOTEarlGrey/RV32BFull) guard in cve2_decoder.sv
    #   (lines 820, 1008-1024 for the OP-immediate/-register paths) -- with
    #   RV32B hardcoded to RV32BNone, alu_operator_i can never actually take
    #   any of these values, so every case item selecting on them is
    #   structurally unreachable, not just untested. Likewise bfp_op
    #   (line 267) and shift_sbmode (line 294) are each an explicit
    #   `(RV32B != RV32BNone) ? ... : 1'b0` ternary -- permanently 0 here --
    #   so their own `if` branches (284, 318) are dead, and
    #   bwlogic_op_b_negate (permanently 0 once XNOR/ORN/ANDN/CMIX are all
    #   dead, lines 375-378) makes line 383's ternary true-arm dead too.
    #
    #   Verified via a -viewcov dry run before applying: several of these
    #   share a case-statement line with an already-covered, live opcode
    #   (e.g. line 1325 lists `ALU_XOR, ALU_XNOR,` together -- XOR is hit,
    #   XNOR is dead). Questa's -code b exclusion removes a line's branch
    #   bins as one unit (no per-arm granularity for grouped case items,
    #   same limitation found this session excluding cve2_cs_registers'
    #   UmodeEnabled branches) -- so excluding these lines also drops the
    #   sibling live opcode's own separately-tracked hit bin. Confirmed this
    #   is a clean consolidation, not a real loss of signal: XOR/OR/AND
    #   (lines 1325-1327) and the shift_sbmode/bwlogic_op_b_negate implicit
    #   false-arms (318, 383) were all unambiguously covered already. Lines
    #   284's `if/else` has an explicit `end else begin` on its own line
    #   (286), so unlike the others it excluded surgically -- only the dead
    #   true arm was removed, line 286's hit stayed a separately-tracked bin.
    #   Full before/after: 91 bins/60 hits/31 misses -> 55/55/0 (100%).
    #
    coverage exclude -du cve2_alu -linerange 72 73 76 77 78 126 127 165 167 -code b -comment $RVB_DISABLED_COMMENT
    coverage exclude -du cve2_alu -linerange 284 318 375 383 -code b -comment $RVB_DISABLED_COMMENT
    coverage exclude -du cve2_alu -linerange 1325 1326 1327 1332 1333 1339 1354 1358 1362 -code b -comment $RVB_DISABLED_COMMENT

    #   line 171: (use_rs3_q & ~instr_first_cycle_i) ? instr_rs3 : instr_rs1.
    #   use_rs3_q is tied combinationally to use_rs3_d via gen_no_rs3_flop
    #   when RV32B==RV32BNone (line 164), and every `use_rs3_d = 1'b1;`
    #   assignment (CMIX/CMOV/FSL/FSR decode) sits inside an
    #   `if (RV32B != RV32BNone)` guard that can never be entered here --
    #   so use_rs3_q is permanently 0 and both input terms of this
    #   condition are structurally masked. Found while verifying where
    #   condition-coverage holes cluster; same RVB-disabled dead-code
    #   family as the cve2_alu exclusion above.
    coverage exclude -du cve2_decoder -linerange 171 -comment $RVB_DISABLED_COMMENT
}

# Exclude coverage for U-mode support (UmodeEnabled hardcoded to 0)
if {!$UmodeEnabled} {
    #   cve2_cs_registers.sv:
    #   - line 699 (mstatus_d.mprv = 1'b0;, inside MRET's
    #     `if (mstatus_q.mpp != PRIV_LVL_M)` at 698): unreachable statement,
    #     since mpp can never be non-M with U-mode disabled. Unscoped (no
    #     genuinely-live coverage type shares this line).
    #   - line 698's own condition (mstatus_q.mpp != PRIV_LVL_M): the `if`
    #     itself is genuinely reachable/hit every MRET (mpp==M side), only
    #     its true branch (mpp!=M) is dead -- excluded -code c since 2026-08-11.
    #   - lines 553, 581 (mstatus_d.mpp/dcsr_d.prv vs PRIV_LVL_U checks,
    #     `... && (umode_control ~& (... == PRIV_LVL_U))`): umode_control is
    #     permanently 0 and the PRIV_LVL_U comparisons can never be true --
    #     condition-only, same reasoning as line 698.
    #     NOTE (2026-08-11): these three -linerange targets were previously
    #     687/687/(542 570) -- stale by exactly 2 lines, silently missing
    #     their intended targets (Questa doesn't error on a -linerange that
    #     matches no excludable item at that line). Found via a design-wide
    #     cov_holes -code c sweep: this file's 5 condition misses were
    #     literally the ones this block was already meant to exclude. Cause
    #     of the 2-line drift not investigated (likely upstream RTL edits
    #     after this block was written); fix was to re-point at current
    #     line numbers, verified against the live RTL file before applying.
    #   - BRANCH-level exclusions added 2026-08-12 for the same UmodeEnabled=0
    #     root cause, previously left uncounted on purpose ("the line's real
    #     statement/branch coverage stays counted") but explicitly requested
    #     closed this session:
    #       * line 698 (`if (mstatus_q.mpp != PRIV_LVL_M)`): true branch dead,
    #         mpp forced back to M by every software write (line 548's write-
    #         side legalization, `& umode_control`) and by MRET's own
    #         legalization here.
    #       * line 718 (`mstatus_d.mpp = umode_control ? PRIV_LVL_U :
    #         PRIV_LVL_M;`): the PRIV_LVL_U arm is dead, umode_control
    #         permanently 0.
    #       * line 738 (`assign priv_mode_lsu_o = mstatus_q.mprv ? ... :
    #         priv_lvl_q;`): the mstatus_q.mprv arm is dead -- mprv can never
    #         become 1, since every software write to it is masked
    #         (`csr_wdata_int[...] & umode_control`, lines 548-549) and the
    #         only RTL path that could set it (line 699,
    #         `mstatus_d.mprv = 1'b0;`) is itself inside the already-dead
    #         line-698 `if`.
    #     Questa's -code b exclusion for a simple if/ternary removes the
    #     whole branch (both arms) as one unit -- no per-arm granularity like
    #     -feccondrow gives for conditions -- so the already-covered false/
    #     M-mode arm's bin is removed too, not just the dead true arm. Net
    #     effect confirmed via a -viewcov dry run before applying: cs_registers_i
    #     branches 257/260 (3 misses) -> 254/254 (100%, clean, no side effects
    #     on any other line).
    #   NOTE (2026-08-12): this -linerange target was previously 687 -- off
    #   by exactly 1 line (the statement itself is at 686; 687 is just the
    #   closing `end`), silently missing its target this whole time. Found
    #   via a design-wide statement-coverage sweep: this was the ONLY
    #   statement-level miss left in the entire design. Fixed by re-pointing
    #   at the correct line, verified against the live RTL file.
    coverage exclude -du cve2_cs_registers -linerange 302-303 324-325 -comment $UMODE_DISABLED_COMMENT
    coverage exclude -du cve2_cs_registers -linerange 699 -comment $UMODE_DISABLED_COMMENT
    coverage exclude -du cve2_cs_registers -linerange 698 -code c -comment $UMODE_DISABLED_COMMENT
    coverage exclude -du cve2_cs_registers -linerange 553 581 -code c -comment $UMODE_DISABLED_COMMENT
    coverage exclude -du cve2_cs_registers -linerange 698 -code b -comment $UMODE_DISABLED_COMMENT
    coverage exclude -du cve2_cs_registers -linerange 718 -code b -comment $UMODE_DISABLED_COMMENT
    coverage exclude -du cve2_cs_registers -linerange 738 -code b -comment $UMODE_DISABLED_COMMENT

    #   cve2_controller.sv: priv_mode_i (fed from cs_registers' permanently-M
    #   priv_lvl_q) is permanently PRIV_LVL_M, so `priv_mode_i == PRIV_LVL_M`
    #   (lines 312, 634) can never evaluate false and
    #   `priv_mode_i == PRIV_LVL_U` (line 313) can never evaluate true --
    #   condition-only, same reasoning as above.
    coverage exclude -du cve2_controller -linerange 312 313 634 -code c -comment $UMODE_DISABLED_COMMENT

    #   Branch-level exclusions for the same finding, added 2026-08-12 while
    #   auditing branch-coverage holes (same "-code c scope gap" pattern
    #   found this session on cs_registers_i/decoder_i): lines 312-314 are
    #   the nested `ebreak_into_debug = priv_mode_i==PRIV_LVL_M ? ... :
    #   priv_mode_i==PRIV_LVL_U ? ... : 1'b0;` ternary -- since the outer
    #   `priv_mode_i==PRIV_LVL_M` term is always true, the entire inner
    #   ternary (313's own condition and 314's default) is never evaluated.
    #   Line 635 is `EXC_CAUSE_ECALL_UMODE`, the same permanently-dead U-mode
    #   arm as line 313. Verified via -viewcov dry run alongside the
    #   XInterface/one-hot-default exclusions below: controller_i branches
    #   86/77/9 -> 74/73/1 (only the genuine, real irq_withdrawn_in_taken
    #   miss at line 514 remains -- see the cve2_controller.sv:514 note above).
    coverage exclude -du cve2_controller -linerange 312-314 -code b -comment $UMODE_DISABLED_COMMENT
    coverage exclude -du cve2_controller -linerange 635 -code b -comment $UMODE_DISABLED_COMMENT
}

coverage save -onexit -testname ${TEST} ${TEST}.ucdb
