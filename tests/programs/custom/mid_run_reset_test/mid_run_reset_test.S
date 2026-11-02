# Mid-run reset directed test (CV32E20).
#
# Copyright (c) 2026 Eclipse Foundation
# SPDX-License-Identifier: Apache-2.0 WITH SHL-2.1
#
# Purpose: be *running* -- in the middle of a divide, in the middle of a
# multiply, in the ordinary DECODE/FLUSH business of a program -- at the moment
# the testbench drops rst_ni, so the edges Questa's FSM extractor only models
# because rst_ni is asynchronous are reached: ctrl_fsm_cs -> RESET,
# md_state_q -> MD_IDLE, gen_mult_fast/mult_state_q ALBH->ALBL and ls_fsm_cs
# WAIT_GNT_MIS->IDLE. Rows W006 and W022-W036 of
# docs/coverage/coverage_review.csv; the waivers themselves are the "accepted
# untested-stimulus gap (mid-run reset injection)" block in
# sim/tools/vsim/cov.tcl.
#
# MEASURED 2026-11-01 (seeds 1-12, docs/coverage/raw/phase_c_acceptance.csv):
# 12 of 12 runs pass and 3 of those 16 edges are genuinely hit --
# DECODE->RESET on every seed, MD_COMP->MD_IDLE on 8, ALBH->ALBL on 1. The
# other 13 need stimulus this program does not contain (a wfi, an exception, a
# misaligned access, debug or interrupt activity) or a pulse aimed at a
# one-cycle state, which a randomized delay cannot do. No waiver is retired on
# this evidence, and this program stays a pulse-once test for the reason two
# paragraphs below.
#
# The pulse is the testbench's, not this program's: run with +mid_run_reset
# (see uvmt_cv32e20_general_purpose_test_c::mid_run_reset(), which starts
# uvme_cv32e20_mid_run_reset_c) to drop reset once, after a bounded random
# number of cycles.
#
# That is also why this program can be this simple. The pulse fires exactly
# once; if it lands while the loop below is still running, the core restarts
# from BOOT_SET and walks the same instructions a second time, uninterrupted,
# and reports the pass at the end of that second pass. If it lands after the
# pass has already been reported, nothing is disturbed. Either way the verdict
# this program prints is a real one -- which is the whole reason it does not
# check anything about the reset itself.
#
# Deliberately absent: a `wfi`. Sleeping is the only way to reach the
# controller's WAIT_SLEEP and SLEEP states, so ctrl_fsm_cs WAIT_SLEEP->RESET and
# SLEEP->RESET need the pulse timed around one -- but with a single pulse a
# program that sleeps after it can never be woken, and the test would hang
# instead of failing on every seed where the timing did not line up. Those two
# rows therefore stay covered by their waiver, and the sheet says so.
#
# Run this with USE_ISS=NO: the pulse desyncs the RVFI trace from any reference
# model, by design.
.include "user_define.h"
#include "cv32e20_dv.h"
.section .text.start
.globl _start
.section .text
.type _start, @function

_start:
    j _start_main

.globl _start_main
.section .text
_start_main:

    # x5: outer loop counter. x6/x7: divide operands, kept non-zero so the
    # divider is genuinely engaged (a zero divisor is a special case that
    # retires in cve2_multdiv_fast's first state).
    li   x5, 4000
    li   x6, 0x1234567d
    li   x7, 0x0000d3b1

reset_loop:
    # A divide and a multiply back to back: MD_ABS_A/MD_ABS_B/MD_COMP/MD_LAST/
    # MD_CHANGE_SIGN are the states the md_state_q waivers are about, and the
    # multiply's AL* states are gen_mult_fast/mult_state_q's.
    div  x8, x6, x7
    mul  x9, x6, x7
    remu x10, x6, x7
    mulh x11, x6, x7
    # Both increments stay inside the +/-2048 addi immediate: 0x1105 looked
    # harmless here and is what kept this program from assembling at all.
    addi x6, x6, 0x105
    addi x7, x7, 0x307
    bne  x7, x0, reset_loop_next
    li   x7, 0x0000d3b1
reset_loop_next:
    addi x5, x5, -1
    bne  x5, x0, reset_loop

    j test_pass

    # End-of-test exits: the canonical pass/fail protocol of bsp/cv32e20_dv.h
    # (write 123456789 / 1 to the test-status port, then halt), the same shape
    # tests/programs/custom/load_store_rs1_zero/ uses. A bare `j test_pass` does
    # not link -- no test_pass symbol exists anywhere in the BSP or in
    # tests/asm/user_define.h, which is why the test-program this one was modelled
    # on (tests/programs/custom/isa_fcov_holes/, in run_tests.py's
    # DISCOVERY_EXCLUDES) cannot be built either.
    test_pass:
    TEST_PASS
    test_fail:
    TEST_FAIL
