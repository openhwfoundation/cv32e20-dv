# Coverage review sheet

`coverage_review.csv` is the review artifact for this repository's DUT code
coverage: **one row per waiver in `sim/tools/vsim/cov.tcl` and one row per
coverage hole that is still open after those waivers**, with a measured verdict
for the waiver and a triage verdict for the hole. It is a CSV with a UTF-8 BOM
and CRLF line endings on purpose, so it opens correctly in Excel and Google
Sheets without an import wizard, and no cell ever contains a newline, so one
record is always one row on screen.

Regenerate it, never hand-edit it:

```bash
venv_cv32e20-dv/bin/python bin/coverage_review.py --summary
```

Every cell comes from the two raw dumps in [`raw/`](raw/) and the rules below;
the four columns a human owns (`Reviewer`, `Review Date`, `Notes`) come out
empty. What to review and in what order is in
[`README.md`](README.md#regenerating-everything).

## Columns

| Column | Meaning |
| --- | --- |
| `ID` | `W###` for a waiver, in `cov.tcl` order; `H###` for a hole, in the holes report's order. Stable across regenerations as long as the file order is stable, which is what makes `Notes` in a reviewed copy still point at the right row. |
| `Type` | `WAIVER` or `HOLE`. |
| `Design Unit` | The design unit (RTL module) the row is about. |
| `Metric` | `stmt`, `branch`, `condition`, `fec`, `fsm-trans`, `all-on-line` or `du` for a waiver (the latter two are Questa's own units: `-linerange` waives every metric on a line, a bare `-du` the whole unit); `stmt`, `branch`, `condition`, `fsm` or `assertion` for a hole, counted in the unit Questa's metric uses (a condition row is an input *term*, not an FEC row). |
| `Target` | Line list, FSM transition, `feccondrow <line> <row>`, assertion path, or `line <N>` for a statement hole. What the row is about, in the form you would paste into `cov.tcl`. |
| `cov.tcl Line` | `cov.tcl:<n>`: the source line of that exact statement. Empty for holes, which have no waiver. |
| `Hits` / `Misses` | For a waiver: what **lifting** the exclusion brings back, i.e. the live bins it covers today. For a hole: always `0` and `1`, since it is a single missed bin. |
| `Coverage %` | `Hits / (Hits + Misses)` of the row's own bins. A hole is therefore always `0.00`, and a waiver whose number is not `0.00` is a waiver sitting on covered code; see the policy. |
| `Config Gate` | `none`, or the `cov.tcl` control variable (`BusErrSupported=0`, `UmodeEnabled=0`, `RVB=0`, `XInterface=0`) whose `if {!$VAR}` block the statement sits in. |
| `Waiver Status` | The audit's measured verdict: `VALID`, `NO-OP`, `MIS-AIMED`, `HIDING-COVERED-CODE`, `NOT-INSTRUMENTED`, `DISABLED` (a commented-out statement), `GATED-OFF` (its gate is inactive). Empty for holes. |
| `Classification` | The triage decision: `A-existing-state`, `B-new-test`, `C-waive`, `D-fix-waiver`. Rules below. |
| `Rationale Category` | `dead-code`, `config-disabled`, `sim-only`, `reset-injection`, `stimulus-gap`. *Why* the row is where it is. |
| `Justification` | For a waiver, its `-comment`, verbatim and on one line; this is the reachability argument the policy demands. For a hole, the argument for the verdict. |
| `Proposed Test` | The new test that would close the row, if the verdict is `B-new-test`. |
| `Proposed cov.tcl Exclusion` | The literal `coverage exclude` line, paste-ready: regenerated for a waiver from the statement `cov.tcl` actually contains (so a re-aim can be pasted back), and for a hole the exclusion that *would* waive it if the reviewer decides to. Assertion rows use one form worth knowing before pasting: `coverage exclude -assertpath <path> -comment {…}` with **no `-du`**: measured on the merged database, `-du` paired with `-assertpath` silently matches nothing (the same matches-nothing-without-an-error trap as the policy's item 3), while the bare `-assertpath` removes exactly its one bin. |
| `Status` | `open` (a hole nobody has decided on), `triaged` (a verdict is recorded; for a reset-injection waiver this means the test is planned and the waiver stays until the merged database proves otherwise), `waived` (in force, measured, and no longer expected to change), `fixed`, `tested`, `rejected` (a reviewer's call). |
| `Reviewer` / `Review Date` / `Notes` | Blank, for the reviewer. |

## Triage rules

The four classifications answer one question: what would it take to get this
row off the list?

* **`A-existing-state`**: coverable today. The RTL is reachable and the
  existing stimulus just does not happen to reach it in a way the metric
  counts. Fix by steering an existing test (or by accepting that the metric
  counts a bin the suite does reach in another form), not by adding a waiver.
* **`B-new-test`**: reachable, but nothing in the suite can reach it. Needs a
  directed test, named in `Proposed Test`. The row keeps its waiver (if it has
  one) until the merged database covers the target, because deleting a waiver
  before the stimulus exists only moves the number down.
* **`C-waive`**: not coverable in the configuration being verified. Dead code,
  a disabled feature, or code that only exists for the simulator. Belongs in
  `cov.tcl` with a `-comment` that argues it.
* **`D-fix-waiver`**: the row exists because the *waiver* is wrong, not
  because the RTL is: it was aimed at lines the RTL no longer has, or it hides
  code that is covered. The fix is a corrected exclusion, not new stimulus, and
  `Waiver Status` of `NO-OP`, `MIS-AIMED` or `HIDING-COVERED-CODE` means a row
  is `D-fix-waiver` no matter what its `-comment` claims.

`bin/coverage_review.py` applies these mechanically from the measured row (its
module docstring is the rule list); a human decides the cases it leaves blank.

## Waiver policy

A waiver is only acceptable if all four of these are true of it, and the sheet
makes each one checkable:

1. **A reachability argument traceable to RTL.** That is the `Justification`
   column: which signal, which elaboration parameter, which `unique case`, and
   why no legal sequence reaches the target. "It never hits" is not an argument;
   it is the measurement in item 3.
2. **A config or parameter reference.** If the target is dead because a feature
   is off, say which parameter and where it is pinned, and put the statement
   under the matching `if {!$VAR}` gate in `cov.tcl` so the `Config Gate` column
   can record it. The four gates today are `BusErrSupported`, `UmodeEnabled`,
   `RVB` and `XInterface`.
3. **A live measurement.** Run `bin/coverage_waiver_audit.py` and point at the
   row it writes. `coverage exclude` accepts a target that matches nothing and
   reports no error, so a waiver is only worth what its measurement is: the
   audit applies the whole file to the merged database and then lifts each
   statement in turn, and a waiver that brings nothing back is a no-op whatever
   its comment says. `Waiver Status` must be `VALID`.
4. **A date**, in the `cov.tcl` note next to the statement, like the `NOTE
   (2026-08-12)` blocks already in the file. RTL line numbers drift; the date
   is what tells a reviewer whether the argument predates the last re-pin.

And one prohibition: **never waive a target that has hits.** An exclusion over
covered code deletes achieved coverage from the metric and silently makes the
number harder to reach. That is what `HIDING-COVERED-CODE` reports and it is
always `D-fix-waiver`; three exclusions were removed this way on 2026-11-01,
one of them (the `ls_fsm_e` default case) after 26 months of reporting the
design's FSM default arm as excluded-but-never-hit.

## Current state

Both dumps in `raw/` were measured against
`sim/uvmt/vsim_results/default/merged/merged.ucdb`, md5
`7d8c430e78b4648bb75c8a0b4b6c7670`, on 2026-11-01: the 32-test `--all-custom`
batch of 2026-10-31 merged into one database. The sheet has 68 rows: **64 waivers and 4 holes**. It was last regenerated after `coverage_review.py`'s proposed assertion exclusions were corrected from `-du <unit> -assertpath …` (which excludes nothing) to the bare `-assertpath` form; the tallies did not move, only the paste-ready lines. It was regenerated once more the same day after the `MEASURED 2026-11-01` notes were added to `cov.tcl`: the statements below each note moved down by 17, 29 or 37 lines, and because `cov.tcl Line` and `Proposed cov.tcl Exclusion` are derived from that file, both dumps were re-measured (report-only, same database) rather than left to drift: still 68 rows, still 63 `VALID` and one `NOT-INSTRUMENTED`, and 44 rows moved in `cov.tcl Line` and in nothing else. A re-derive that quiet is exactly what the audit is for: a comment edit that had *accidentally* changed an exclusion would have surfaced as a changed verdict instead of as a silently stale sheet.

The percentages that database was published with, recorded here because this
sheet is the document that has to say whether a later number moved and why. They
are `coverage_report/summary.json` of the 2026-10-31 `--all-custom` batch copied
verbatim, and the generated file itself is not committed:

| Metric | Active | Hits | Coverage |
| --- | --- | --- | --- |
| statement (line) | 1912 | 1900 | 99.37% |
| branch | 1432 | 1409 | 98.39% |
| condition | 185 | 164 | 88.65% |
| FSM state | 26 | 26 | 100.0% |
| FSM transition | 37 | 37 | 100.0% |
| assertion | 74 | 71 | 95.95% |
| cover directive | 0 | 0 | n/a |

That is the **97.28%** DUT-scoped code coverage
(`/uvmt_cv32e20_tb/dut_wrap/cv32e20_top_i/u_cve2_top/u_cve2_core`) this document
quotes as the baseline, beside **69.09%** functional coverage: 31743 bins
covered of 45942 across the full hierarchy, environment covergroups included,
which splits into
`uvma_isacov_pkg` 21820/33172 (65.78%), `uvma_obi_memory_pkg` 75/75 (100.0%) and
`uvme_cv32e20_pkg` 9848/12695 (77.57%). The same document reports 34 passed of 41
test rows, 7 failed (82.93%): 41 is that batch's row count, not the 39 per-test
databases sitting in the merge above, and `sim/uvmt/regression_results.json` is
what says which tests those rows were. A `cover directive` of 0 of 0 is `n/a`
rather than 100% or 0% for the same reason the dashboards render it that way:
there was no denominator to divide by.

Of the 64 waivers, 63 measure `VALID` (each removes at least the miss it was
written for) and one measures `NOT-INSTRUMENTED`:

| ID | Row | Verdict |
| --- | --- | --- |
| W040 | `coverage exclude -du cve2_tracer` | `cve2_tracer` is outside the instrumented DUT scope, so the statement excludes nothing at all. Kept: if the scope ever widens, the tracer's CSR-name and mnemonic lookup tables are exactly the noise this exclusion is there to keep out. Recorded as `C-waive` / `sim-only` / `triaged`, not as a bug. |

There are **no `NO-OP`, `MIS-AIMED` or `HIDING-COVERED-CODE` rows**, which is the
result of the 2026-11-01 re-aim: 20 statements moved in six design units, four
commented-out "To review" exclusions were deleted (their design units have no
open hole, so they could only have hidden covered code), one was deleted for
measuring `HIDING-COVERED-CODE`, and two `cve2_cs_registers` RVFI condition
rows that a `-linerange` structurally cannot reach were added as
`-feccondrow`. Re-run the audit before quoting any older number. Re-running is not
optional after editing `cov.tcl` either, comments included: all three dumps take their
`cov.tcl` line numbers from the file's own text, so a note inserted anywhere moves every
cite below it, and a stale cite still looks plausible. `bin/coverage_review.py --check-cites` reads each published cite back out of `cov.tcl` and reports every cite that no longer names its own waiver and exits 1; `TestPublishedCites` in
`bin/tests/test_coverage_review.py` keeps that command honest.

The 4 open holes:

| ID | Row | Verdict |
| --- | --- | --- |
| H001 | `cve2_controller.sv:514` branch, `All False Count` (the `else` arm of `if (handle_irq)` inside `IRQ_TAKEN`) | `B-new-test` / `stimulus-gap` → `irq_withdraw_test`. `handle_irq` is committed by the `DECODE -> IRQ_TAKEN` transition (`cve2_controller.sv:496-498`) and sampled again the next cycle; an interrupt that drops in that one-cycle window is the `irq_withdrawn_in_taken` case the RTL's own assertion block (`:835-836`) exists to describe. Reachable in the RTL, so it gets directed stimulus, not a waiver. That stimulus now exists: `env/uvme/vseq/uvme_cv32e20_irq_withdraw_vseq.sv`, kicked by `+irq_withdraw` from the general-purpose test, with `tests/programs/custom/irq_withdraw_test/` registered on `regress/cv32e20_ci_check.yaml`. It has now been compiled and run: `SIMULATION PASSED`, 2026-11-01, Questa One 2025.3_2, `USE_ISS=NO`, seed 1, 10 m 34 s wall. **And the bin is still a miss**: line 514 was evaluated twice in that run and was true both times ([`raw/phase_c_acceptance.csv`](raw/phase_c_acceptance.csv)). The reason is structural, not bad luck. 3008 assert/deassert pulses produced exactly **one** `DECODE -> IRQ_TAKEN` commit, and the vendored `uvma_interrupt_drv_c` cannot put a falling edge on the cycle this window is open: `wait_and_assert_irq_edge()` holds every rising edge for two cycles, and `irq_ack_clear()` only drops the line once it has *sampled* `irq_ack`, and `irq_ack` is no DUT signal: CVE2's interrupts are level-sensitive with no acknowledge (the controller's entire interrupt interface is the `irq_pending_i`/`irqs_i`/`irq_nm_i` inputs at `cve2_controller.sv:66-72`), and `uvma_interrupt_if.irq_ack` is fabricated by the testbench as `ctrl_fsm_cs == 4'h7` (`tb/uvmt/uvmt_cv32e20_dut_wrap.sv:107`). `4'h7` is `IRQ_TAKEN`, the eighth member of the module-local `ctrl_fsm_e` at `cve2_controller.sv:106-109`, and that state lasts exactly one cycle. So the driver samples the ack during the very cycle `:514` is evaluated and drives the line low on the *next* edge: the earliest withdrawal that agent can build lands one cycle after `IRQ_TAKEN` samples `handle_irq`. The 2026-08-12 claim that the window had been seen once on `corev_rand_interrupt_exception` cannot be reproduced from the current database either: the merged `.ucdb` of the 32-test `--all-custom` batch, which holds 39 per-test databases, counts 433 evaluations of line 514 and **0** false-arm hits; with the two runs of the new test that is 435 evaluations, still 0 hits. The row stays open and `triaged`, and more pulses will not close it: what would is a one-cycle-wide withdrawal driven below the agent (a `tb/uvmt/` stimulus path, which is where `ctrl_fsm_cs` is already being probed; `vendor_lib/openhwgroup_core-v-verif` is a git-ignored clone of upstream core-v-verif, not a fork this repository patches), or a decision to document it as a gap. It is not waivable under the policy below, because the argument that holds is about the verification environment, not about the RTL. This remains the design's only open code miss outside the three assertions below. |
| H002 | `CVE2NoDoubleSpecialReqPCSet` (controller) | `C-waive` / `dead-code`. Never attempted (`pass=0 fail=0`). The antecedent needs `seen_exception_pc_set`, which is `(seen_exception_pc_set \| exception_pc_set) & ~exception_req_done` (`:867`); every state that performs an exception PC set also returns `ctrl_fsm_ns` to `DECODE` in that same cycle, so `exception_req_done` (`:809`) clears it on the very edge it would be set. A guarded-by-construction safety assertion, not DUT behaviour to cover. |
| H003 | `IllegalInsnStallMustBeMemStall` (id_stage) | `C-waive` / `dead-code`. Never attempted. The antecedent `illegal_insn_o & stall_id` needs one instruction that both decodes illegal and asks for a stall, while `stall_id = stall_mem \| stall_multdiv \| stall_jump \| stall_branch \| stall_alu` (`cve2_id_stage.sv:898-899`) is qualified by the decode of a memory/divide/jump/branch/ALU instruction and `illegal_insn_o` by `illegal_csr_insn_i \| illegal_insn_dec` (`:408`). Never entered across the 32-test batch, which includes the illegal-instruction and misalign programs. |
| H004 | `IbexStallIfValidInstrNotExecuting` (id_stage) | `C-waive` / `dead-code`. Constant-false antecedent, provable with no stimulus: this build has no writeback stage, so `instr_executing` *is* `instr_executing_spec` (`:924`) `= instr_valid_i & ~instr_fetch_err_i & controller_run` (`:923`), and the antecedent `instr_valid_i & ~instr_fetch_err_i & ~instr_executing & controller_run` is `X & ~X`. |

H002-H004 are `C-waive`, i.e. they should end up in `cov.tcl`, and they are
deliberately **not** waived by this analysis. Waiving three assertions on an
argument nobody has reviewed is exactly how a waiver rot like the one above
starts; `Proposed cov.tcl Exclusion` holds the paste-ready line, the bare `-assertpath` form for the reason in the columns table, and the row stays `triaged` until a reviewer signs the `Justification` off.

The 16 reset-transition waivers (`W006`, `W022`-`W030`, `W031`-`W036`) are a
different animal and are **not** dead code: `rst_ni` is a real asynchronous
input, so every `-> RESET` / `-> MD_IDLE` edge Questa's FSM extractor models is
reachable, merely untested because no test in the suite pulls reset after t=0.
They classify `B-new-test` / `reset-injection` → `mid_run_reset_test`, and the
audit is what proves that classification is honest: all 16 measure `VALID` with
`Delta Misses = 1`, i.e. they are hiding genuine misses. Deleting them before the stimulus exists would take FSM-transition coverage from 100 % to 83 % and call it progress, so they stay and the test is what retires them. `env/uvme/vseq/uvme_cv32e20_mid_run_reset_vseq.sv` and `tests/programs/custom/mid_run_reset_test/` (`+mid_run_reset`) have now been compiled and run, on seeds 1-12: **12 of 12 `SIMULATION PASSED`**, with the pulse genuinely mid-program (seed 1: `Asserting reset for 16.933 ns after 8756 cycles`). The acceptance criterion is measured in [`raw/phase_c_acceptance.csv`](raw/phase_c_acceptance.csv) and it comes out **3 of 16**:

| Edge | Seeds hitting it | Why the rest do not |
| --- | --- | --- |
| `ctrl_fsm_cs DECODE->RESET` | 12 / 12 | n/a |
| `md_state_q MD_COMP->MD_IDLE` | 8 / 12 | MD_COMP is the divider's only long state; the four other `md_state_q` edges are one cycle each out of a ~35-cycle divide. |
| `gen_mult_fast/mult_state_q ALBH->ALBL` | 1 / 12 | one cycle per multiply. |
| the other 13 | 0 / 12 | `BOOT_SET`/`FIRST_FETCH` are the one-cycle states right after the reset this sequence itself releases, whose randomized delay is bounded below at 10 cycles; `WAIT_SLEEP`/`SLEEP` need a `wfi` the program deliberately omits (a core asleep when the pulse lands can never be woken); `DBG_TAKEN_IF`/`DBG_TAKEN_ID`/`IRQ_TAKEN` need debug and interrupt stimulus this test does not drive; `FLUSH` needs an exception; `ls_fsm_cs WAIT_GNT_MIS->IDLE` needs a misaligned access in flight, and this program does no memory access at all. |

So **no waiver is retired on this evidence**. The three edges that did land read `E-hit`, excluded *and* covered: that is the state this sheet calls `HIDING-COVERED-CODE` once a waiver outlives its stimulus, and a regression run of one seed covers one or two of them at best. They become retirable when the merged database of a real batch contains the test, which is exactly what re-running `bin/coverage_waiver_audit.py` measures; the same run is what would catch a waiver deleted too early.

### Reproducing the acceptance measurement

Report-only, against the per-test databases a `make test` run leaves behind; nothing below writes a `.ucdb`:

```bash
vcover report -details -annotate -precision 2 -code f -showexcluded \
    -output log_agent/acc/fsm.txt \
    sim/uvmt/vsim_results/default/mid_run_reset_test/0/mid_run_reset_test.ucdb
vcover report -details -annotate -precision 2 -code b -showexcluded \
    -instance=/uvmt_cv32e20_tb/dut_wrap/cv32e20_top_i/u_cve2_top/u_cve2_core. \
    -output log_agent/acc/br.txt \
    sim/uvmt/vsim_results/default/irq_withdraw_test/0/irq_withdraw_test.ucdb
```

`-showexcluded` is not optional: the exclusions a run saves are baked into its `.ucdb`, and `coverage exclude -clear -all` is rejected (`vish-4003`), so the only way to read a waived bin's own hit count is to print the report with the exclusions shown. `E-hit` is excluded-but-covered, `E` is excluded and still a miss, and a branch that never went the other way prints `***0***  All False Count`.

## Reading the same numbers without this sheet

`cov_txt`, `cov_holes_details` and `cov_func` in `mk/uvmt/README.md` and `mk/uvmt/vsim.mk` produce Questa's own views of the same database: the first two of the code metrics, `cov_func` of the covergroups, deliberately unscoped. `docs/regression.md` explains how the merged database and the published `coverage_report/` are produced. The published tree carries the two HTML reports side by side, `questasim/` (code, DUT-scoped) and `questasim_func/` (covergroups, full hierarchy), opened by the dashboard's **Code Coverage** and **Functional Coverage** buttons. This sheet exists
because none of those views can show a waiver and an open hole in one table next
to the argument for each.
