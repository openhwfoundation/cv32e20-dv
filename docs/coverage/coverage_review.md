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
| `Status` | `open` (a hole nobody has decided on), `triaged` (a verdict is recorded; for a reset-injection waiver this means the test is planned and the waiver stays until the merged database proves otherwise), `waived` (in force, measured, and not expected to change), `fixed`, `tested`, `rejected` (a reviewer's call). |
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
  because the RTL is: it is aimed at lines the RTL does not have, or it hides
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
4. **A date**, in the `cov.tcl` note next to the statement, as a `NOTE
   (<yyyy-mm-dd>)` block. RTL line numbers drift; the date
   is what tells a reviewer whether the argument predates the last re-pin.

And one prohibition: **never waive a target that has hits.** An exclusion over
covered code deletes achieved coverage from the metric and silently makes the
number harder to reach. That is what `HIDING-COVERED-CODE` reports and it is
always `D-fix-waiver`; the audit has retired five exclusions this way, each
the same day a merged batch database first measured its target covered.
One had reported the design's FSM default arm as excluded-but-never-hit
for two years before that same-day check caught it: a stale waiver is
invisible to every reader who only ever sees the metric.

## Current state

Both Questa dumps in `raw/` were measured on 2026-11-05 against
`sim/uvmt/vsim_results/default/merged/merged.ucdb`, md5
`e8ac28486576b87be52c8196e05d460f`, and `merged_parked/merged.ucdb`, md5
`973109826b5ac23ddac93bf59fa3ffa7` (md5s of the regenerated dumps: holes
`bef11a783c2a2b1a9aee9d5b0eb1b0b8`, holes_parked
`0d78f88cb82597a14b108e5847bf9786`, waiver_audit
`5b629e9b618792557b1fa504452fae52`, sheet `319000c980d8ca60dae7c65fde7871f2`).
Those databases are one fresh batch: the 2026-11-05
`--all-custom --include-corev-dv --cov-report` regression -- 44 tests, 42 PASS
(the two FAILs are the documented parked pair), 35 default inputs and 42
including parked -- which also published the metrics below and ran
`irq_single_cycle_test`, the dedicated `cve2_controller.sv:514` stimulus
(below). The default holes dump, the waiver audit and the sheet are
byte-identical to the previous publication, which is exactly what
pinning md5s is for; `holes_parked.csv` alone moved, because its input list
grew by `irq_single_cycle_test`'s database. The sheet has
173 rows: **63 waivers and 110 holes**, every one of them classified (0 `open`).

Hole `ID`s follow the holes report's order, so two rows leaving the dump
move them: the `cve2_controller.sv:514` branch (closed, below) and
`cve2_compressed_decoder.sv:260` branch item `3'b101` (measured covered in
the regenerated stream -- see the family table). The CSR/counter family is
`H001`–`H107` and the three assertion holes are `H108`–`H110`. Waiver `ID`s
follow `cov.tcl` order and hold: `W038` is `cve2_tracer`, and the 14
surviving reset-transition waivers are `W006` and `W022`–`W034`. Their
`cov.tcl` cites move whenever the file's text moves -- even a comment edit
shifts every cite below it, and the cites here are re-derived from the file
itself, which is the only way to keep them true. (`ID`s are stable across
a re-export; line numbers are not, which is what `--check-cites` is
for.)

**Why this default number is what it is, and how to read a change in it.**
An earlier default-scope number (97.28%, 4 holes) had been merged by a blind
`find … -name "*.ucdb"`, and that merge quietly absorbs the parked tests'
PASSing `.ucdb`s left under `vsim_results/` by earlier runs -- stimulus
counted in the default number that no fresh CI batch reproduces. The default
scope is now always merged from the batch's own explicit input list; read it
against the including-parked view, never against a `find`-merged one: with
the parked tests merged, code coverage is **100.0%** -- every code metric at
100% except the three never-attempted assertions -- and the 98.49 % ↔
100.0 % gap *is* the parked gap a `find`-merged default number would hide.

The percentages that database was published with, recorded here because this
sheet is the document that has to say whether a later number moved and why. They
are `coverage_report/summary.json` copied verbatim from the 2026-11-05
batch's report, and the generated file itself is not committed:

| Metric | Active | Hits | Coverage |
| --- | --- | --- | --- |
| statement (line) | 1808 | 1776 | 98.23% |
| branch | 1302 | 1227 | 94.24% |
| condition | 95 | 95 | 100.0% |
| FSM state | 26 | 26 | 100.0% |
| FSM transition | 41 | 41 | 100.0% |
| assertion | 74 | 71 | 95.95% |
| cover directive | 0 | 0 | n/a |

That is the **98.49%** DUT-scoped code coverage
(`/uvmt_cv32e20_tb/dut_wrap/cv32e20_top_i/u_cve2_top/u_cve2_core`) beside
**70.19%** functional coverage: 32247 bins covered of 45942 across the full
hierarchy, environment covergroups included, which splits into
`uvma_isacov_pkg` 22133/33172 (66.72%), `uvma_obi_memory_pkg` 75/75 (100.0%) and
`uvme_cv32e20_pkg` 10039/12695 (79.08%). The same document's
`including_parked` block reads **100.0%** code (line 100.0%, branch 100.0%,
condition and both FSM metrics 100.0%; the only code metric below 100% is
`assertion` at 95.95%, the three `C-waive` rows below) and **70.96%** functional
(32599/45942). The regression counts beside them are **35 of 35** in the
default scope and **42 of 44** including parked (the two FAILs are
`debug_test_known_miscompares` and `debug_test_trigger`, the documented parked
pair) because this document's metrics and verdicts finally come from the one
`--cov-report` batch that published both. A `cover directive` of 0 of 0 is
`n/a` rather than 100% or 0% for the same reason the dashboards render it that
way: there was no denominator to divide by.

Of the 63 waivers, 62 measure `VALID` (each removes at least the miss it was
written for) and one measures `NOT-INSTRUMENTED`:

| ID | Row | Verdict |
| --- | --- | --- |
| W038 | `coverage exclude -du cve2_tracer` | `cve2_tracer` is outside the instrumented DUT scope, so the statement excludes nothing at all. Kept: if the scope ever widens, the tracer's CSR-name and mnemonic lookup tables are exactly the noise this exclusion is there to keep out. Recorded as `C-waive` / `sim-only` / `triaged`, not as a bug. |

There are **no `NO-OP`, `MIS-AIMED` or `HIDING-COVERED-CODE` rows**, and that
is a fresh measurement, not an inherited claim: the audit last found two
`HIDING-COVERED-CODE` rows -- `ctrl_fsm_cs DECODE->RESET` and
`md_state_q MD_COMP->MD_IDLE` -- and because the merged batch database now
contains `mid_run_reset_test`, both exclusions were retired on that verdict,
which is what the policy's "never waive a target that has hits" prohibition
demands. The `RESOLVED` note in each of the two FSM blocks records it, and
[`raw/phase_c_acceptance.csv`](raw/phase_c_acceptance.csv) carries the two
retired rows as `unwaived` with their `cov.tcl` cites re-derived. Re-run the
audit before quoting any older number. Re-running is not optional after editing
`cov.tcl` either, comments included: all three dumps take their `cov.tcl` line
numbers from the file's own text, so a note inserted anywhere moves every cite
below it, and a stale cite still looks plausible.
`bin/coverage_review.py --check-cites` reads each published cite back out of
`cov.tcl` and reports every cite that does not name its own waiver and exits
1; `TestPublishedCites` in `bin/tests/test_coverage_review.py` keeps that
command honest.

The 110 holes come in three families, and the sheet classifies every row:

| Family | Rows | Verdict |
| --- | --- | --- |
| `H001`–`H107` CSR/counter arms (`cve2_counter` 48, `cve2_cs_registers` 59) | 107 | `B-new-test` / `stimulus-gap`, classified from measured evidence, not guesswork: `raw/holes_parked.csv` shows every one of these bins covered when the parked tests are merged (its only three rows are the assertions below). The merge measures *that* the parked set covers them and, from the two `ucdb.request` input lists, *which set* it can be: the parked database is the default one plus exactly the seven parked tests that pass today -- `csr_instr_asm`, `riscv_arithmetic_basic_test_0`, `riscv_arithmetic_basic_test_1`, `riscv_csr`, `perf_counters_instructions`, `debug_test_boot_set` and `debug_test_reset` -- so the covering stimulus is one of those seven (they are in the merge because the merge split keys on PASSing `.ucdb`s, not on list membership). Which of the seven covers which bin is not measurable from a merge and is not claimed here. One of them is a listing artifact: `csr_instr_asm` is in `ASM_TESTS` *and* in `PARKED` (`bin/run_tests.py`), so its coverage lands in the parked database in every batch whatever selects it -- part of this default-to-parked delta is list membership, not parked-by-intent stimulus. Closed by promoting the stimulus (lane 2 below), never by a waiver: waiving bins the toggle already covers would delete achieved coverage from the metric. |
| ~~`H001` `cve2_compressed_decoder.sv:260` branch item `3'b101`~~ | 0 | **Not in the current dump** -- the arm measures covered (`corev_rand_illegal_instr_test` 8 hits, `corev_rand_debug` and `corev_rand_debug_single_step` 1 each): the file is unchanged between the `ce0fd917` and `d7f2156` pins and the bin appears and disappears with the `--gen-seed random` stream. Coverage by seed luck is not coverage: the row is *not* closed as far as the plan is concerned, and lane 2 item 1 (extend the directed illegal-compressed sequence in `illegal_instr_test` with `3'b101`) is what would close it deterministically. Not waivable either way: the arm is reachable RTL. |
| `H108`–`H110` | 3 | Three standing holes; their arguments are unchanged and `raw/holes_parked.csv` proves they are no one's stimulus gap -- they miss in both merges. The fourth, `H002` `cve2_controller.sv:514`, is **closed** (below) and appears in neither hole dump. The table below carries the three. |

The three standing holes, arguments unchanged, with their
measured status refreshed: they miss in both the default and the
including-parked merge of the current database as well
(`raw/holes.csv`, `raw/holes_parked.csv`).

| ID | Row | Verdict |
| --- | --- | --- |
| H108 | `CVE2NoDoubleSpecialReqPCSet` (controller) | `C-waive` / `dead-code`. Never attempted (`pass=0 fail=0`). The antecedent needs `seen_exception_pc_set`, which is `(seen_exception_pc_set \| exception_pc_set) & ~exception_req_done` (`:867`); every state that performs an exception PC set also returns `ctrl_fsm_ns` to `DECODE` in that same cycle, so `exception_req_done` (`:809`) clears it on the very edge it would be set. A guarded-by-construction safety assertion, not DUT behaviour to cover. |
| H109 | `IllegalInsnStallMustBeMemStall` (id_stage) | `C-waive` / `dead-code`. Never attempted. The antecedent `illegal_insn_o & stall_id` needs one instruction that both decodes illegal and asks for a stall, while `stall_id = stall_mem \| stall_multdiv \| stall_jump \| stall_branch \| stall_alu` (`cve2_id_stage.sv:898-899`) is qualified by the decode of a memory/divide/jump/branch/ALU instruction and `illegal_insn_o` by `illegal_csr_insn_i \| illegal_insn_dec` (`:408`). Never entered across the 32-test batch, which includes the illegal-instruction and misalign programs. |
| H110 | `IbexStallIfValidInstrNotExecuting` (id_stage) | `C-waive` / `dead-code`. Constant-false antecedent, provable with no stimulus: this build has no writeback stage, so `instr_executing` *is* `instr_executing_spec` (`:924`) `= instr_valid_i & ~instr_fetch_err_i & controller_run` (`:923`), and the antecedent `instr_valid_i & ~instr_fetch_err_i & ~instr_executing & controller_run` is `X & ~X`. |

H108-H110 are `C-waive`, i.e. they should end up in `cov.tcl`, and they are
deliberately **not** waived by this analysis. Waiving three assertions on an
argument nobody has reviewed is exactly how a waiver rot like the one above
starts; `Proposed cov.tcl Exclusion` holds the paste-ready line, the bare `-assertpath` form for the reason in the columns table, and the row stays `triaged` until a reviewer signs the `Justification` off.

### H002 closed: the interrupt-withdrawal injector

The `All False Count` of `if (handle_irq)` in `IRQ_TAKEN`
(`cve2_controller.sv:514`) is closed by stimulus, and nothing else -- it is
reachable RTL (the design describes the case itself in its
`irq_withdrawn_in_taken` assertion model, `:826-836`), so a waiver would have
had no reachability argument to stand on and, once the bin has hits, would be
`HIDING-COVERED-CODE`. `cov.tcl` gained no exclusion; it gained a dated
`RESOLVED` note recording the measurement.

The problem was the stimulus path, not the design or the test: the vendored
`uvma_interrupt_drv_c` lets go of the line only after sampling `irq_ack`, which
is this testbench's own `ctrl_fsm_cs == 4'h7` probe
(`tb/uvmt/uvmt_cv32e20_dut_wrap.sv:107`) and is high during the very cycle
`:514` is read -- so the earliest withdrawal that agent builds lands one cycle
after the window closes, and 3008 pulse pairs found exactly one commit. The
withdrawal is injected where the cycle reference already lives: the probe
`commit_to_irq` fires on the commit edge itself (`ctrl_fsm_cs` in
{`FIRST_FETCH`, `DECODE`} and `ctrl_fsm_ns == IRQ_TAKEN`, which inherits every
commit gate of `:431-436` and `:496-498`), and a registered one-cycle blank
pulls the whole `irq` bus low into the DUT for exactly the `IRQ_TAKEN` cycle,
N times. Blanking an asynchronous, level-sensitive input for one cycle is what
a real source withdrawing looks like, so the core sees legal stimulus. The
injector is a dedicated bound file rather than TB-internal
code: `tb/uvmt/uvmt_cv32e20_irq_single_cycle_injector.sv`, `bind`-ed into
`uvmt_cv32e20_dut_wrap` itself -- footprint: the injector section at that
file's end plus the `irq_dut` net it drives -- and it is inert without
`+irq_single_cycle_shots=N`. `+irq_single_cycle` starts
`env/uvme/vseq/uvme_cv32e20_irq_single_cycle_vseq.sv`, which extends the
pulse-sweep vseq and offers the NMI a few times more than the shot count, so
the last offer is genuinely taken and the program ends. The dedicated test is
`tests/programs/custom/irq_single_cycle_test` (`+irq_single_cycle
+irq_single_cycle_shots=3`), deliberately on no `regress/*.yaml` list --
sanity keeps the pulse-sweep `irq_withdraw_test` -- and coverage batches pick
it up through directory discovery. The run is self-checking --
`uvmt_cv32e20_tb.sv`'s `end_of_test` fails an armed injector that never
fired -- so a PASS *is* the measurement. Measured 2026-11-05 (seed 1, PASS in
150.9 s run alone): **6 hits of 8 evaluations** in the test's own `.ucdb`,
and **6 hits of 1479 evaluations**, **2 of 2 branches** of line 514, in both
merged databases of a fresh `--cov-report` batch. The pulse sweep itself
still measures 2 evaluations, 0 on the arm, on these same databases:
`irq_withdraw_test` passing was never this row's measurement, which is why
the dedicated test exists. Likewise
`cve2_compressed_decoder.sv:260` branch item `3'b101` measures covered
in these databases -- the
reserved encoding is drawn by the random stream, not by any directed
stimulus, which is why this sheet treats seed variance as an open
action rather than a closed hole. The 110 remaining holes are therefore 107
CSR/counter arms plus the 3 assertions.

The 14 remaining reset-transition waivers (`W006`, `W022`-`W034`) are a
different animal and are **not** dead code: `rst_ni` is a real asynchronous
input, so every `-> RESET` / `-> MD_IDLE` edge Questa's FSM extractor models is
reachable, merely untested -- every other test resets once, at t=0, before the
FSMs have left RESET. They classify `B-new-test` / `reset-injection`, and the
audit is what keeps that classification honest: all 14 measure `VALID` with
`Delta Misses = 1`, i.e. each hides a genuine miss; the two that stopped
hiding one were retired on exactly that verdict. Deleting a waiver before the
stimulus exists would take FSM-transition coverage from 100 % to 83 % and call
it progress, so the survivors stay and per-state stimulus is what retires them.

The per-edge acceptance measurement is
[`raw/phase_c_acceptance.csv`](raw/phase_c_acceptance.csv): across 12 seeds of
`mid_run_reset_test` three of the 16 edges landed (12/12, 8/12, 1/12), where
a single-seed run covers one or two at best -- so no waiver may be retired on
single-seed evidence. A waiver that outlives its miss is exactly what `E-hit`
means -- the audit measured `ctrl_fsm_cs DECODE->RESET` and
`md_state_q MD_COMP->MD_IDLE` that way once a merged batch database contained
the test, and both exclusions went -- and "never waive a target that has hits"
is the only retirement rule. The same audit run is what would catch a
waiver deleted too early.

### Reproducing the acceptance measurement

Report-only, against the per-test databases a `make test` run leaves behind; nothing below writes a `.ucdb`:

```bash
vcover report -details -annotate -precision 2 -code f -showexcluded \
    -output log_agent/acc/fsm.txt \
    sim/uvmt/vsim_results/default/mid_run_reset_test/0/mid_run_reset_test.ucdb
vcover report -details -annotate -precision 2 -code b -showexcluded \
    -instance=/uvmt_cv32e20_tb/dut_wrap/cv32e20_top_i/u_cve2_top/u_cve2_core. \
    -output log_agent/acc/br.txt \
    sim/uvmt/vsim_results/default/irq_single_cycle_test/0/irq_single_cycle_test.ucdb
```

`-showexcluded` is not optional: the exclusions a run saves are baked into its `.ucdb`, and `coverage exclude -clear -all` is rejected (`vish-4003`), so the only way to read a waived bin's own hit count is to print the report with the exclusions shown. `E-hit` is excluded-but-covered, `E` is excluded and still a miss, and a branch that never went the other way prints `***0***  All False Count`. In that report the `:514` arm prints `6     All False Count` and the block closes `Branch totals: 2 hits of 2 branches = 100.00%`.

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

1. The distance from 98.49% to 100% is made entirely of `cov.tcl` exclusions
   plus the 110 open holes, and no part of it is unargued: 107 of the holes
   vanish when the parked tests' stimulus is merged (code 100.0%), 3 are
   guarded-by-construction safety assertions with a paste-ready waiver line
   awaiting review, and 1 (the reserved compressed encoding, plus the reset
   transitions behind the 14 surviving waivers) needs one directed piece of
   stimulus each.
2. Every open item is already classified on the sheet (0 `open` rows), and
   107 of the 110 holes share one measured fact: `raw/holes_parked.csv` proves
   the repository's own parked stimulus covers them.
3. Nothing on the list requires new RTL knowledge. The arguments, the audit
   verdicts and the exclusions are written down; what is missing is stimulus
   work and three reviewed paste actions.

### Triage of every open item

| Item | Class | Lane |
| --- | --- | --- |
| `cve2_compressed_decoder.sv:260` branch `3'b101` | A (steer the existing illegal-compressed sequence; seed luck is not coverage -- the bin measures covered in the current dump and that is not a fix) | 2 |
| `H001`–`H107` CSR/counter arms (107) | B (the stimulus exists parked: promote `csr_instr_asm`; `riscv_csr` and `perf_counters_instructions` need only the promotion -- lane 2) | 2 |
| `H108`–`H110` `CVE2NoDoubleSpecialReqPCSet`, `IllegalInsnStallMustBeMemStall`, `IbexStallIfValidInstrNotExecuting` | C (guarded by construction; the sheet's `Proposed cov.tcl Exclusion` holds the bare `-assertpath` line -- never `-du` + `-assertpath`, which matches nothing) | 1 |
| ~~`H002` `cve2_controller.sv:514` All False (the IRQ-withdraw window)~~ | **CLOSED**, and held closed by the dedicated bound injector (`tb/uvmt/uvmt_cv32e20_irq_single_cycle_injector.sv`, run as `irq_single_cycle_test` with `+irq_single_cycle_shots`) -- see "H002 closed" above; the test is deliberately on no `regress/*.yaml` list, and no waiver was involved | done |
| 14 reset-transition waivers (`W006`, `W022`–`W034`) | B (reset injection: `mid_run_reset_test` retired 2 by measurement; a single asynchronous pulse cannot reach the rest, per `raw/phase_c_acceptance.csv` -- per-state variant stimulus retires more, or they stay as documented permanent gaps) | 2 |

### The plan, in three lanes

**Lane 1 -- waiver hygiene (mechanical, no simulator).** Review the three
assertion exclusions against the four policy checks, paste them if approved,
and re-measure: assertion coverage goes 95.95% => 100%, and
`coverage_waiver_audit.py` proves each new row `VALID`. Keep
`coverage_review.py --check-cites` (already in `python-ci.yml`) and
`TestPublishedCites` green.

**Lane 2 -- stimulus, in ascending cost.**

1. `cve2_compressed_decoder.sv:260` `3'b101`: extend the directed
   illegal-compressed sequence in `illegal_instr_test` with the reserved
   encoding, so the arm stops depending on which stream `--gen-seed random`
   draws. (Measuring covered on one random draw is seed variance, not the
   fix.)
2. `H001`–`H107`: promote `csr_instr_asm` (it passes today; promoting it means
   leaving `PARKED`, which is the list the merge split keys on, not leaving the
   default test set -- it is in `ASM_TESTS` too and already runs), then
   re-measure with a `--cov-report` batch and watch `raw/holes.csv` shrink
   toward the three standing items. The two tests this lane once listed as
   needing repair, `riscv_csr` and `perf_counters_instructions`, need none:
   both print PASS under `--tb uvmt`
   ([regression](../regression.md)), so what is left is the `PARKED`
   promotion -- and the re-measure is what makes this document's own
   including-parked numbers move.
3. ~~`H002`~~ **done, re-measured**: the one-cycle IRQ
   withdrawal is driven at the DUT pins by a bound testbench file --
   `tb/uvmt/uvmt_cv32e20_irq_single_cycle_injector.sv`, beside where the
   cycle reference (`irq_ack` as `ctrl_fsm_cs == 4'h7`) already lives --
   armed by `+irq_single_cycle_shots` and run as `irq_single_cycle_test`;
   acceptance (`H002` gone from `raw/holes.csv` *and* `raw/holes_parked.csv`)
   is measured: 6 hits of 1479 evaluations (6 of 8 in the test's own
   database), 2 of 2 branches of `cve2_controller.sv:514`.
4. Reset transitions: give `mid_run_reset_test` per-state siblings (debug,
   interrupt, `wfi`, exception variants) to retire more of the 14, or record
   the remainder as permanent documented gaps.

**Lane 3 -- cadence and guardrails.** Every RTL re-pin ends with a
`--cov-report` batch and the two audits -- the cadence that catches a
`HIDING-COVERED-CODE` pair the day it becomes measurable; `--check-cites` in
CI; a weekly waiver audit on the self-hosted runner in between; and the dual
`Default`/`Including Parked` merges kept published so the parked delta stays
visible instead of leaking back into the default number, the failure the
split-merge design exists to prevent.

### Explicit non-goals

* **Functional coverage** (70.19% default, 70.96% including parked): a separate
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
