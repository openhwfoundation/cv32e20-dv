# Single-cycle interrupt-withdrawal directed test (CV32E20).
#
# Copyright (c) 2026 Eclipse Foundation
# SPDX-License-Identifier: Apache-2.0 WITH SHL-2.1
#
# Purpose: give the controller's IRQ_TAKEN state an interrupt that is withdrawn
# on the exact cycle it would have redirected the PC, so the false arm of
# `if (handle_irq)` (cve2_controller.sv:514) is taken. Row H002 of
# docs/coverage/coverage_review.csv; the window itself is `irq_withdrawn_in_taken`
# (cve2_controller.sv:826-836).
#
# The stimulus is the testbench's, not this program's: run with
# +irq_single_cycle +irq_single_cycle_shots=3 (see
# uvmt_cv32e20_general_purpose_test_c::irq_single_cycle(), which starts
# uvme_cv32e20_irq_single_cycle_vseq_c, and
# tb/uvmt/uvmt_cv32e20_irq_single_cycle_injector.sv, which does the
# withdrawal). The vseq offers the NMI a few times, held until the core acks
# each offer; the injector blanks the core's interrupt inputs for the
# IRQ_TAKEN cycle of the first shots commits, and uvmt_cv32e20_tb.sv's
# end_of_test fails the run if an armed injector never fired. A PASS here is
# therefore the measurement: the bin was stimulated. This program's only job
# is to keep the pipeline busy so that DECODE is committing instructions the
# whole time -- an interrupt with nowhere to be committed to is a window that
# never opens.
#
# Nothing here enables mstatus.MIE or any mie bit, and that is deliberate: the
# NMI reaches handle_irq without them (cve2_controller.sv:321-322), so the
# offers that are *not* withdrawn -- the last ones, since the vseq offers more
# than the injector withdraws -- are taken as an NMI and retired by the BSP's
# own handler (bsp/handlers.S's m_nmi_irq_handler, which saves the
# caller-saved registers and mrets). Enabling the maskable interrupts instead
# would add two CSRs to the list of things that have to go right for this test
# to mean anything.
#
# The loop count is a duration, not a pass criterion: sized to comfortably
# outlast the vseq's handful of offers (initial delay, gap and NMI handler all
# bounded), so the window is pursued for the whole run and the test still ends
# on its own.
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

    # x5: loop counter. One pass is ~8 cycles, so 20000 passes is on the order
    # of 160k cycles of live DECODE traffic -- more than ten times the upper
    # bound on the vseq's offer schedule (see uvme_cv32e20_irq_single_cycle_vseq_c).
    li   x5, 20000

single_cycle_loop:
    # Deliberately ordinary work -- an ALU op, a load, a store and a taken
    # branch -- so the instruction in ID keeps changing and DECODE keeps being
    # ready to commit. The accesses go through the stack pointer that crt0 set
    # up, which is the one address range this program knows it may touch.
    addi x1, x1, 1
    add  x2, x2, x1
    sw   x2, -8(sp)
    lw   x4, -8(sp)
    xor  x6, x4, x2
    bne  x6, x0, single_cycle_next
    addi x7, x7, 1
single_cycle_next:
    addi x5, x5, -1
    bne  x5, x0, single_cycle_loop

    j test_pass

    # End-of-test exits: the canonical pass/fail protocol of bsp/cv32e20_dv.h
    # (write 123456789 / 1 to the test-status port, then halt), the same shape
    # tests/programs/custom/load_store_rs1_zero/ uses.
    test_pass:
    TEST_PASS
    test_fail:
    TEST_FAIL
