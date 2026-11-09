# A miniature of sim/tools/vsim/cov.tcl, one statement per metric the audit
# understands. Shapes taken from the real file: the comment variable that several
# exclusions share, the config gate that swallows a whole block, the
# commented-out "To review" exclusions that exclude nothing, and the
# assertion-by-path form that must NOT carry a -du.
set comment "One shared justification for the exclusions below"

coverage exclude -du cve2_controller -linerange 258 266 268 -code s -comment {Statement excluded: BusErrSupported=0 path}
coverage exclude -du cve2_controller -linerange 514 -code b -comment {Branch excluded: interrupt withdrawn in IRQ_TAKEN}
coverage exclude -du cve2_controller -linerange 312 -code c -comment $comment

# The reset-injection family, the 16 rows mid_run_reset_test exists to retire.
coverage exclude -du cve2_id_stage -ftrans {ctrl_fsm_cs DECODE->RESET} -comment {FSM transition excluded: accepted untested-stimulus gap (mid-run reset injection)}
coverage exclude -du cve2_if_stage -fstate {fetch_fsm_cs WAIT} -comment $comment
coverage exclude -du cve2_controller -feccondrow 501 row4 -comment {FEC row excluded: one-hot by construction}

# An assertion is a named verification object: path, and no -du (which Questa
# silently ignores the match of).
coverage exclude -assertpath /tb/dut/ctrl_i/CVE2NoDoubleSpecialReqPCSet -comment {Assertion never attempted}

# Commented out, i.e. documentation only: enabled=0.
# coverage exclude -du cve2_pmp -linerange 100 -code s -comment {To review}

if {!$BusErrSupported} {
    coverage exclude -du cve2_controller -linerange 258 -code c -comment {Condition excluded: BusErrSupported=0}
}
