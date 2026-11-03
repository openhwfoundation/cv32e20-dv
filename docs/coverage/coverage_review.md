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

Every cell comes from the raw dumps in [`raw/`](raw/) and the rules below;
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

One hole rule is measured rather than argued, and it exists because the
published default scope must not hide stimulus the repository already owns:
when `raw/holes_parked.csv` has been regenerated, a hole it does not list --
one the including-parked merge covers -- classifies `B-new-test` /
`stimulus-gap` on that evidence. The stimulus exists; it is only parked or
failing. A hole both merges miss stays `open` unless a human has filed the
argument for it.

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
design's FSM default arm as excluded-but-never-hit. Two more followed on
2026-11-03, retired by the audit the same day a merged batch database first
covered the transitions they excused.

## Current state

Both Questa dumps in `raw/` were re-measured on 2026-11-03 against
`sim/uvmt/vsim_results/default/merged/merged.ucdb`, md5
`3ddf367f8732d92b60c74f364e045e00`: the 43-test `--cov-report` batch of
2026-11-03 (34 default tests and the 9 PARKED tests, `--include-corev-dv
--all-custom`, upstream CVE2 pin `d7f2156`, Questa One 2025.3_2) merged through
the batch-scoped lists of `bin/run_tests.py`. The optional third dump,
`raw/holes_parked.csv` (md5 `5374a0b3a43467afa4e2ef3a2195195d`), is the same
export run against `merged_parked/merged.ucdb`, md5
`44eb3424dd559a373f16173eb0e7c6df`. The sheet has 175 rows: **63 waivers and
112 holes**, every one of them classified (0 `open`).

Two waivers and many rows moved since 2026-11-01, so the sheet's `ID`s
renumbered: the `cve2_controller.sv:514` branch is `H002` now (was `H001`), the
three assertion holes are `H110`–`H112` (were `H002`–`H004`), the
`cve2_tracer` waiver is `W038` (was `W040`), and the 14 surviving
reset-transition waivers are `W006` and `W022`–`W034`.

**Why the numbers moved, and why that is not a regression.** The 97.28% /
4-hole baseline this section carried on 2026-11-01 had been merged by the old
blind `find … -name "*.ucdb"`, and that merge was quietly absorbing the
parked tests' PASSing `.ucdb`s left under `vsim_results/` by earlier runs --
stimulus counted in the default number that no fresh CI batch reproduces. This
is the first default-scope measurement of the suite merged from its own scope;
read it against the including-parked view, not against the contaminated one:
with the parked tests merged, code coverage is **99.97%** -- matching the old
100%-class local figures -- and the 98.46 % ↔ 99.97 % gap *is* the parked gap
that used to hide inside the default number.

The percentages that database was published with, recorded here because this
sheet is the document that has to say whether a later number moved and why. They
are `coverage_report/summary.json` of the 2026-11-03 batch copied verbatim, and
the generated file itself is not committed:

| Metric | Active | Hits | Coverage |
| --- | --- | --- | --- |
| statement (line) | 1808 | 1776 | 98.23% |
| branch | 1302 | 1225 | 94.09% |
| condition | 95 | 95 | 100.0% |
| FSM state | 26 | 26 | 100.0% |
| FSM transition | 39 | 39 | 100.0% |
| assertion | 74 | 71 | 95.95% |
| cover directive | 0 | 0 | n/a |

That is the **98.46%** DUT-scoped code coverage
(`/uvmt_cv32e20_tb/dut_wrap/cv32e20_top_i/u_cve2_top/u_cve2_core`) beside
**67.74%** functional coverage: 31119 bins covered of 45942 across the full
hierarchy, environment covergroups included, which splits into
`uvma_isacov_pkg` 21441/33172 (64.64%), `uvma_obi_memory_pkg` 75/75 (100.0%) and
`uvme_cv32e20_pkg` 9603/12695 (75.64%). The same document's
`including_parked` block reads **99.97%** code (line 100.0%, branch 99.85%,
condition and both FSM metrics 100.0%) and **68.38%** functional
(31416/45942), over 37 passed of 43 test rows: every FAIL/ERROR row is a parked
test (`riscv_csr`, `perf_counters_instructions` and the four `debug_test_*`s;
`sim/uvmt/regression_results.json` names them), and the default set is 34/34.
A `cover directive` of 0 of 0 is `n/a` rather than 100% or 0% for the same
reason the dashboards render it that way: there was no denominator to divide by.

Of the 63 waivers, 62 measure `VALID` (each removes at least the miss it was
written for) and one measures `NOT-INSTRUMENTED`:

| ID | Row | Verdict |
| --- | --- | --- |
| W038 | `coverage exclude -du cve2_tracer` | `cve2_tracer` is outside the instrumented DUT scope, so the statement excludes nothing at all. Kept: if the scope ever widens, the tracer's CSR-name and mnemonic lookup tables are exactly the noise this exclusion is there to keep out. Recorded as `C-waive` / `sim-only` / `triaged`, not as a bug. |

There are **no `NO-OP`, `MIS-AIMED` or `HIDING-COVERED-CODE` rows**, and that
is a fresh measurement, not an inherited claim: the 2026-11-03 audit found
exactly two `HIDING-COVERED-CODE` rows -- `ctrl_fsm_cs DECODE->RESET` and
`md_state_q MD_COMP->MD_IDLE` -- and because a real merged batch database now
contains `mid_run_reset_test`, both exclusions were deleted the same day, which
is what the policy's "never waive a target that has hits" prohibition demands.
The dated re-pin note in each of the two FSM blocks records it, and
[`raw/phase_c_acceptance.csv`](raw/phase_c_acceptance.csv) carries the two
retired rows as `unwaived` with their `cov.tcl` cites re-derived. Re-run the
audit before quoting any older number. Re-running is not optional after editing
`cov.tcl` either, comments included: all three dumps take their `cov.tcl` line
numbers from the file's own text, so a note inserted anywhere moves every cite
below it, and a stale cite still looks plausible.
`bin/coverage_review.py --check-cites` reads each published cite back out of
`cov.tcl` and reports every cite that no longer names its own waiver and exits
1; `TestPublishedCites` in `bin/tests/test_coverage_review.py` keeps that
command honest.

The 112 holes come in three families, and the sheet classifies every row:

| Family | Rows | Verdict |
| --- | --- | --- |
| `cve2_cs_registers` and `cve2_counter` CSR/counter arms (`H003`–`H109`) | 107 | `B-new-test` / `stimulus-gap`, classified from measured evidence, not guesswork: `raw/holes_parked.csv` shows every one of these bins covered when the parked tests are merged. The merge measures *that* the parked set covers them and, from the two `ucdb.list` files, *which set* it can be: the parked database is the default one plus exactly `csr_instr_asm`, `riscv_arithmetic_basic_test_0` and `riscv_arithmetic_basic_test_1`, so the covering stimulus is one of those three (while `riscv_csr` and `perf_counters_instructions` fail). Which of the three covers which bin is not measurable from a merge and is not claimed here. One of the three is a listing artefact: `csr_instr_asm` is in `ASM_TESTS` and in `PARKED` (`bin/run_tests.py`), and the merge split keys on `PARKED`, so its coverage lands in the parked database in every batch whatever selects it -- part of this default-to-parked delta is list membership, not parked-by-intent stimulus. Closed by promoting or repairing the stimulus (lane 2 below), never by a waiver: waiving bins the toggle already covers would delete achieved coverage from the metric. |
| `H001` `cve2_compressed_decoder.sv:260` branch item `3'b101` | 1 | `A-existing-state` / `stimulus-gap`. The reserved quadrant-2 compressed encoding sharing the illegal-instruction arm with `3'b001`/`3'b011`/`3'b111` (`:258-262`); all three siblings measure hit and only this arm has never been fetched. The file is unchanged between the `ce0fd917` and `d7f2156` pins (empty `git diff`), and the previous database covered the item: the 2026-11-03 `--gen-seed random` stream simply never drew the encoding. Coverage by seed luck is not coverage -- extend the directed illegal-compressed sequence with `3'b101` and it closes deterministically. Not waivable: the arm is reachable RTL. |
| `H002` and `H110`–`H112` | 4 | The same four open items the 2026-11-01 sheet carried; their arguments stand unchanged and `raw/holes_parked.csv` proves they are no one's stimulus gap -- they miss in both merges. The table below carries them (renumbered). |

The four standing holes, verbatim from the 2026-11-01 review with their
measured status refreshed: they miss in both the default and the
including-parked merge of the 2026-11-03 database as well
(`raw/holes.csv`, `raw/holes_parked.csv`).

| ID | Row | Verdict |
| --- | --- | --- |
| H002 | `cve2_controller.sv:514` branch, `All False Count` (the `else` arm of `if (handle_irq)` inside `IRQ_TAKEN`) | `B-new-test` / `stimulus-gap` → `irq_withdraw_test`. `handle_irq` is committed by the `DECODE -> IRQ_TAKEN` transition (`cve2_controller.sv:496-498`) and sampled again the next cycle; an interrupt that drops in that one-cycle window is the `irq_withdrawn_in_taken` case the RTL's own assertion block (`:835-836`) exists to describe. Reachable in the RTL, so it gets directed stimulus, not a waiver. That stimulus now exists: `env/uvme/vseq/uvme_cv32e20_irq_withdraw_vseq.sv`, kicked by `+irq_withdraw` from the general-purpose test, with `tests/programs/custom/irq_withdraw_test/` registered on `regress/cv32e20_ci_check.yaml`. It has now been compiled and run: `SIMULATION PASSED`, 2026-11-01, Questa One 2025.3_2, `USE_ISS=NO`, seed 1, 10 m 34 s wall. **And the bin is still a miss**: line 514 was evaluated twice in that run and was true both times ([`raw/phase_c_acceptance.csv`](raw/phase_c_acceptance.csv)). The reason is structural, not bad luck. 3008 assert/deassert pulses produced exactly **one** `DECODE -> IRQ_TAKEN` commit, and the vendored `uvma_interrupt_drv_c` cannot put a falling edge on the cycle this window is open: `wait_and_assert_irq_edge()` holds every rising edge for two cycles, and `irq_ack_clear()` only drops the line once it has *sampled* `irq_ack`, and `irq_ack` is no DUT signal: CVE2's interrupts are level-sensitive with no acknowledge (the controller's entire interrupt interface is the `irq_pending_i`/`irqs_i`/`irq_nm_i` inputs at `cve2_controller.sv:66-72`), and `uvma_interrupt_if.irq_ack` is fabricated by the testbench as `ctrl_fsm_cs == 4'h7` (`tb/uvmt/uvmt_cv32e20_dut_wrap.sv:107`). `4'h7` is `IRQ_TAKEN`, the eighth member of the module-local `ctrl_fsm_e` at `cve2_controller.sv:106-109`, and that state lasts exactly one cycle. So the driver samples the ack during the very cycle `:514` is evaluated and drives the line low on the *next* edge: the earliest withdrawal that agent can build lands one cycle after `IRQ_TAKEN` samples `handle_irq`. The 2026-08-12 claim that the window had been seen once on `corev_rand_interrupt_exception` cannot be reproduced from the current database either: the merged `.ucdb` of the 32-test `--all-custom` batch, which holds 39 per-test databases, counts 433 evaluations of line 514 and **0** false-arm hits; with the two runs of the new test that is 435 evaluations, still 0 hits. The row stays open and `triaged`, and more pulses will not close it: what would is a one-cycle-wide withdrawal driven below the agent (a `tb/uvmt/` stimulus path, which is where `ctrl_fsm_cs` is already being probed; `vendor_lib/openhwgroup_core-v-verif` is a git-ignored clone of upstream core-v-verif, not a fork this repository patches), or a decision to document it as a gap. It is not waivable under the policy below, because the argument that holds is about the verification environment, not about the RTL. This remains the design's only open code miss outside the three assertions below. |
| H110 | `CVE2NoDoubleSpecialReqPCSet` (controller) | `C-waive` / `dead-code`. Never attempted (`pass=0 fail=0`). The antecedent needs `seen_exception_pc_set`, which is `(seen_exception_pc_set \| exception_pc_set) & ~exception_req_done` (`:867`); every state that performs an exception PC set also returns `ctrl_fsm_ns` to `DECODE` in that same cycle, so `exception_req_done` (`:809`) clears it on the very edge it would be set. A guarded-by-construction safety assertion, not DUT behaviour to cover. |
| H111 | `IllegalInsnStallMustBeMemStall` (id_stage) | `C-waive` / `dead-code`. Never attempted. The antecedent `illegal_insn_o & stall_id` needs one instruction that both decodes illegal and asks for a stall, while `stall_id = stall_mem \| stall_multdiv \| stall_jump \| stall_branch \| stall_alu` (`cve2_id_stage.sv:898-899`) is qualified by the decode of a memory/divide/jump/branch/ALU instruction and `illegal_insn_o` by `illegal_csr_insn_i \| illegal_insn_dec` (`:408`). Never entered across the 32-test batch, which includes the illegal-instruction and misalign programs. |
| H112 | `IbexStallIfValidInstrNotExecuting` (id_stage) | `C-waive` / `dead-code`. Constant-false antecedent, provable with no stimulus: this build has no writeback stage, so `instr_executing` *is* `instr_executing_spec` (`:924`) `= instr_valid_i & ~instr_fetch_err_i & controller_run` (`:923`), and the antecedent `instr_valid_i & ~instr_fetch_err_i & ~instr_executing & controller_run` is `X & ~X`. |

H110-H112 are `C-waive`, i.e. they should end up in `cov.tcl`, and they are
deliberately **not** waived by this analysis. Waiving three assertions on an
argument nobody has reviewed is exactly how a waiver rot like the one above
starts; `Proposed cov.tcl Exclusion` holds the paste-ready line, the bare `-assertpath` form for the reason in the columns table, and the row stays `triaged` until a reviewer signs the `Justification` off.

The 14 remaining reset-transition waivers (`W006`, `W022`-`W034`) are a
different animal and are **not** dead code: `rst_ni` is a real asynchronous
input, so every `-> RESET` / `-> MD_IDLE` edge Questa's FSM extractor models is
reachable, merely untested -- every other test resets once, at t=0, before the
FSMs have left RESET. They classify `B-new-test` / `reset-injection`, and the
audit is what keeps that classification honest: all 14 now measure `VALID` with
`Delta Misses = 1`, i.e. each hides a genuine miss, after the 2026-11-03 merged
batch retired the two that stopped hiding one. Deleting a waiver before the
stimulus exists would take FSM-transition coverage from 100 % to 83 % and call
it progress, so the survivors stay and per-state stimulus is what retires them.

The per-edge acceptance measurement is
[`raw/phase_c_acceptance.csv`](raw/phase_c_acceptance.csv): across 12 seeds of
`mid_run_reset_test` three of the then-16 edges landed (12/12, 8/12, 1/12),
which in 2026-11-01's single-seed regression covered one or two at best -- so
no waiver was retired on that evidence. On 2026-11-03 a real merged batch
database contained the test, the audit measured `ctrl_fsm_cs DECODE->RESET` and
`md_state_q MD_COMP->MD_IDLE` as `HIDING-COVERED-CODE`, and both exclusions
were deleted: a waiver that outlives its miss is exactly what `E-hit` means,
and "never waive a target that has hits" is the only retirement rule. The same
audit run is what would catch a waiver deleted too early.

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

## Reaching 100% code coverage

**What 100% means here.** DUT-scoped code coverage -- the `bcsf` metrics Questa
collects at
`-instance=/uvmt_cv32e20_tb/dut_wrap/cv32e20_top_i/u_cve2_top/u_cve2_core.` --
at 100% **after policy-compliant waivers**, evaluated on the **default** test
set (the `Default` view of the published report; the including-parked toggle is
a diagnostic aid, never the baseline). A number that reaches 100% by waiving
covered code, or by excluding bins nobody reviewed, is not this goal: the
waiver policy above is what separates the two.

### Three facts that bound the problem

1. The distance from 98.46% to 100% is made entirely of `cov.tcl` exclusions
   plus the 112 open holes, and no part of it is unargued: 107 of the holes
   vanish when the parked tests' stimulus is merged (code 99.97%), 3 are
   guarded-by-construction safety assertions with a paste-ready waiver line
   awaiting review, and 2 need one directed piece of stimulus each.
2. Every open item is already classified on the sheet (0 `open` rows), and
   107 of the 112 holes share one measured fact: `raw/holes_parked.csv` proves
   the repository's own parked stimulus covers them.
3. Nothing on the list requires new RTL knowledge. The arguments, the audit
   verdicts and the exclusions are written down; what is missing is stimulus
   work and three reviewed paste actions.

### Triage of every open item

| Item | Class | Lane |
| --- | --- | --- |
| `H001` `cve2_compressed_decoder.sv:260` branch `3'b101` | A (steer the existing illegal-compressed sequence; seed luck is not coverage) | 2 |
| `H002` `cve2_controller.sv:514` All False (the IRQ-withdraw window) | B (one-cycle `irq` withdrawal below the vendored agent, timed against the `ctrl_fsm_cs == 4'h7` probe at `tb/uvmt/uvmt_cv32e20_dut_wrap.sv:107`) | 2 |
| `H003`–`H109` CSR/counter arms (107) | B (the stimulus exists parked: promote `csr_instr_asm`, repair `riscv_csr` / `perf_counters_instructions`) | 2 |
| `H110`–`H112` `CVE2NoDoubleSpecialReqPCSet`, `IllegalInsnStallMustBeMemStall`, `IbexStallIfValidInstrNotExecuting` | C (guarded by construction; the sheet's `Proposed cov.tcl Exclusion` holds the bare `-assertpath` line -- never `-du` + `-assertpath`, which matches nothing) | 1 |
| 14 reset-transition waivers (`W006`, `W022`–`W034`) | B (reset injection: `mid_run_reset_test` retired 2 by measurement; a single asynchronous pulse cannot reach the rest, per `raw/phase_c_acceptance.csv` -- per-state variant stimulus retires more, or they stay as documented permanent gaps) | 2 |

### The plan, in three lanes

**Lane 1 -- waiver hygiene (mechanical, no simulator).** Review the three
assertion exclusions against the four policy checks, paste them if approved,
and re-measure: assertion coverage goes 95.95% -> 100%, and
`coverage_waiver_audit.py` proves each new row `VALID`. Keep
`coverage_review.py --check-cites` (already in `python-ci.yml`) and
`TestPublishedCites` green.

**Lane 2 -- stimulus, in ascending cost.**

1. `H001`: extend the directed illegal-compressed sequence in
   `illegal_instr_test` with the reserved `3'b101` encoding.
2. `H003`–`H109`: promote `csr_instr_asm` (it passes today; promoting it means
   leaving `PARKED`, which is the list the merge split keys on, not leaving the
   default test set -- it is in `ASM_TESTS` too and already runs), then repair
   the failing `riscv_csr` and `perf_counters_instructions`; re-measure with a
   `--cov-report` batch and watch `raw/holes.csv` shrink toward the four
   standing items.
3. `H002`: drive a one-cycle IRQ withdrawal below the vendored agent --
   `tb/uvmt/` is where the needed cycle reference (`irq_ack` as
   `ctrl_fsm_cs == 4'h7`) already lives; acceptance is `H002` gone from
   `raw/holes.csv`.
4. Reset transitions: give `mid_run_reset_test` per-state siblings (debug,
   interrupt, `wfi`, exception variants) to retire more of the 14, or record
   the remainder as permanent documented gaps.

**Lane 3 -- cadence and guardrails.** Every RTL re-pin ends with a
`--cov-report` batch and the two audits (the re-pin plan is what caught the
`HIDING-COVERED-CODE` pair the same day it became measurable); `--check-cites`
in CI; a weekly waiver audit on the self-hosted runner in between; and the dual
`Default`/`Including Parked` merges kept published so the parked delta stays
visible instead of leaking back into the default number, as it did before
2026-11-03.

### Explicit non-goals

* **Functional coverage** (67.74% default, 68.38% including parked): a separate
  covergroup programme with its own review loop; no item in this section moves
  it and it gates nothing here.
* **Toggle and expression coverage**: not instrumented (`COV_TYPES=bcsf`), and
  switching it on is a re-baselining exercise for every waiver in `cov.tcl`,
  not a cite update.
* **Parked tests in the baseline**: they define the `Including Parked` view
  only; the default set is the one that reaches 100% first.

## Reading the same numbers without this sheet

`cov_txt`, `cov_holes_details` and `cov_func` in `mk/uvmt/README.md` and `mk/uvmt/vsim.mk` produce Questa's own views of the same database: the first two of the code metrics, `cov_func` of the covergroups, deliberately unscoped. `docs/regression.md` explains how the merged database and the published `coverage_report/` are produced. The published tree carries the two HTML reports side by side, `questasim/` (code, DUT-scoped) and `questasim_func/` (covergroups, full hierarchy), opened by the dashboard's **Code Coverage** and **Functional Coverage** buttons. This sheet exists
because none of those views can show a waiver and an open hole in one table next
to the argument for each.
