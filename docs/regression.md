<!--
Copyright (c) 2026 Eclipse Foundation
SPDX-License-Identifier: Apache-2.0 WITH SHL-2.1
-->
# Regression Testing

How this repository runs a set of tests, decides whether it passed, and tells
somebody else afterwards. Three things, each with one owner:

| Question | Owner |
| --- | --- |
| *Which* tests make up a regression? | a testlist in [`regress/`](../regress) |
| Did they pass? | `bin/run_tests.py`, reading the testbench's verdict banner |
| What happened? | `bin/regression_report.py` -> `regression_results.json` + a dashboard |

## Quick start

```bash
# The blocking sanity list (fast, self-checking, no program generation):
bin/run_tests.py --testlist regress/cv32e20_sanity.yaml

# Everything this repository knows how to run (hours; needs a Questa licence pool):
bin/run_tests.py --testlist regress/cv32e20_ci_check.yaml --jobs 4

# Re-summarize the logs of a run that already happened, publishing the dashboard again:
bin/run_tests.py --tb uvmt --parse-only
bin/regression_report.py --results sim/uvmt/regression_results.json \
                         --out coverage_report/regression
```

The first of those is a batch like any other, and it is the source of a
foot-gun: it *replaces* `sim/<tb>/regression_results.json`, so the durations and
the wall window of the run it parsed come back `null` (see
[Last batch wins](#results-document-and-dashboard)). Verdicts are unaffected --
they come from the same logs either way.

Both testlists say `tb: uvmt`, so they need Questa on `PATH`
(`set_questa_one_2025` here; see [AGENTS.md](../AGENTS.md)) and the CORE-V
toolchain at `CV_SW_TOOLCHAIN`. A `--tb core` list needs Verilator instead, and
no licence at all.

`python3` must be 3.7 or newer -- the harness uses
`datetime.fromisoformat()` and `subprocess.run(text=...)`. On a host whose
`python3` is 3.6 (this development machine is one) use the project venv:
`venv_cv32e20-dv/bin/python bin/run_tests.py ...`.

## The verdict contract

A test's verdict is read out of its simulation log, never from `make`'s exit
code, because a `make` that fails to compile and a test that runs and fails are
different problems and CI has to tell them apart:

| Testbench | Log | PASS banner | FAIL banner |
| --- | --- | --- | --- |
| `core` | `sim/core/simulation_results/<test>/<seed>/<test>.log` | `ALL TESTS PASSED` | `TEST(S) FAILED!` |
| `uvmt` | `sim/uvmt/vsim_results/<cfg>/<test>/0/vsim-<test>.log` | `SIMULATION PASSED` | `SIMULATION FAILED` |

Anything else -- no banner, compile error, timeout -- is `ERROR`. The banners are
printed by [tb/core/tb_top.sv](../tb/core/tb_top.sv) and
[tb/uvmt/uvmt_cv32e20_tb.sv](../tb/uvmt/uvmt_cv32e20_tb.sv); `bin/tests/test_run_tests.py`
asserts on them so a rename on either side fails a test instead of silently
reporting a green regression.

`bin/run_tests.py` exits 0 only when every selected test printed its PASS
banner, which is what makes it usable as a CI gate. Two documented exceptions:

* `--allow-failures` prints the same table and exits 0 anyway -- for a job whose
  next step is publishing reports, where a red test must not hide the report.
  Setup failures (`make comp_corev-dv`, `make comp`, no tests selected) still exit
  non-zero.
* `--report-only` launches no simulation, so it has nothing to gate on and
  always exits 0.

## Testlists (`regress/*.yaml`)

A testlist is the reviewable answer to "which tests make up a regression of this
repository". They replaced the test lists that used to be duplicated inside
`bin/ci_check` and the workflows -- see [Legacy tools](#legacy-tools) for why
those two no longer run.

```yaml
name: cv32e20_sanity           # required; shown on the published dashboard
description: >                 # required; free text
  Fast blocking sanity on the Questa UVMT testbench.
tb: uvmt                       # optional; core|uvmt (default core)
cfg: default                   # optional; the --cfg equivalent
timeout: 3600                  # optional per-test seconds
jobs: 4                        # optional --jobs equivalent
seed: 1                        # optional --seed equivalent (int or random)
make_args: []                  # optional list appended to every make call
tests:                         # ordered; each entry:
  - name: hello-world          # required: dir under tests/programs/{custom,corev-dv}
    description: Boot and signal pass through the virtual peripheral   # optional
    make_args: []              # optional extra make args for this test
```

The rules that make a list trustworthy are enforced by `load_testlist()`:

* **An unknown key is a hard error**, at both the file level and the entry
  level. A typo that quietly changed what a regression ran is the failure mode
  this whole feature exists to remove; a warning nobody reads is the same bug
  with better manners. The old `cv_regress` `num:` key is rejected for the same
  reason -- to run a list twice, run it twice with a different `--seed`, which
  stays reproducible and keeps both runs visible in the results document.
* **A name must be a real test-program directory**, checked at load time rather
  than two hours into a regression as an `ERROR` row.
* **No duplicates.**
* Whether a test needs the `gen_corev-dv` generation step is read from the tree
  (`tests/programs/corev-dv/<name>/corev-dv.yaml`), so a list may name any
  generated test without a fourth Python list to keep in sync. A generated test
  costs two simulations: `make gen_corev-dv` runs the generator and `make test`
  runs the program it produced, and `make comp_corev-dv` has to compile the
  generator once first; `bin/run_tests.py` does all three itself whenever the
  selection contains a generated test.
* The file only supplies *defaults*: `--tb`, `--cfg`, `--timeout`, `--jobs` and
  `--seed` on the command line still win over it.
* `--testlist` cannot be combined with test names, `--all-custom`,
  `--corev-dv-only`, `--include-parked`, `--include-corev-dv` or `--certify`:
  the file is the selection.

PyYAML is the one third-party module this needs (`pip install PyYAML`, also in
[bin/requirements.txt](../bin/requirements.txt)); it is imported lazily inside
`load_testlist()`, so `bin/run_tests.py hello-world` still runs on a bare
interpreter.

### The two lists that ship

| List | Tests | Use |
| --- | --- | --- |
| `regress/cv32e20_sanity.yaml` | 11 directed, self-checking, no generation | blocks a change; minutes |
| `regress/cv32e20_ci_check.yaml` | the 11 + slow directed tests + the 15 corev-dv templates | nightly/weekly; hours |

The sanity list was measured, not estimated: all 11 tests pass on Questa One
2025.3_2 with `--jobs 4` (11 passed, 0 failed, 0 error(s)) in **644 s** of batch
time against the `d7f2156` CVE2 pin, slowest test `illegal_instr_test` at
612.7 s and the rest between 23.6 s and 123.1 s, which is what publishes a 100%
pass rate on the dashboard. Those
figures *are* the published document's -- `coverage_report/regression/regression_results.json`
of that run holds the same 644 s and the same per-test times -- so re-measuring
the list updates the dashboard and this page from one source. One caveat travels
with `summary.duration_s`: it is the window from the first test starting to the
last one finishing, so it excludes the one-time `make comp` that `--jobs > 1`
does before the loop (and, in `self-hosted.yml`, the `make clean_all` that starts
from nothing). It is the price of the list, not of the CI job. The lists are
gate-able: `bin/tests/test_testlists.py` checks that every list loads, names
real tests, keeps the sanity set free of generation steps, contains no
`DISCOVERY_EXCLUDES` name, and is a subset of the full list.

## Results document and dashboard

Every batch that runs (or parses) tests writes one JSON document and publishes a
dashboard of it -- `--report-only` and `--certify` are the exceptions, and neither
is a regression in this sense: the first launches nothing and reports coverage
out of an existing database, the second short-circuits over `make certify`'s own
ELF-sweep summary:

```
coverage_report/regression/index.html            the page
coverage_report/regression/style.css
coverage_report/regression/common.css            stylesheet shared with the coverage page
coverage_report/regression/regression_results.json
coverage_report/regression/logs/<test>-<seed>.log  a copy of each run's log
sim/<tb>/regression_results.json                 the same document, beside the logs
```

The coverage report beside it publishes the same way, and the two pages share
`templates/common/style.css`, which is copied *into* each directory rather than
referenced across them so each stays self-contained:

```
coverage_report/index.html                the coverage page
coverage_report/style.css                 coverage page's own rules
coverage_report/common.css                the shared stylesheet, same file as above
coverage_report/questasim/                Questa HTML report, code, DUT-scoped
coverage_report/questasim_func/           Questa HTML report, covergroups, full hierarchy
coverage_report/questasim_parked/         the code report from merged_parked/ instead
coverage_report/questasim_func_parked/    the covergroup report from merged_parked/
coverage_report/coverage_review.csv       the waiver/open-hole review sheet (from docs/)
coverage_report/analysis/index.html       the analysis page (templates/analysis_dashboard/)
coverage_report/analysis/style.css        its own rules, plus common.css beside it
coverage_report/analysis/*.csv            the committed dumps that page fetches
```

The last three lines and the review-sheet line are the only places the published
tree holds a file that is *committed* rather than measured: all four are copies of
`docs/coverage/`, which stays the authority because the sheet and the dumps are
input to a review, not output of a run. The mirror is one-way --
`bin/run_tests.py` regenerates `coverage_report/analysis/` with every report and
nothing reads it back -- so an edit there is lost on the next run; edit
`docs/coverage/` and republish.

`questasim/` and `questasim_func/` are the same merged database seen through the
two deliberately different scopes -- `-instance=<DUT>.` for the code report and
`-cvg` with no `-instance` for the covergroup one -- which is why the dashboard
has a **Code Coverage** and a **Functional Coverage** button and why neither
flag may be copied from one invocation to the other (`bin/run_tests.py`'s
module docstring states the invariant where both commands are).

A `--cov-report` batch actually keeps **two** merged databases, each built from
an explicit list of that batch's PASSing `.ucdb` files (never from a `find`
over `vsim_results/<cfg>/`, which used to let leftover databases of earlier
runs leak into the published numbers): `vsim_results/<cfg>/merged/merged.ucdb`
is the **default scope**, and `vsim_results/<cfg>/merged_parked/merged.ucdb`
is the same plus the **PARKED** tests that the batch also runs (`--all-custom
--cov-report` adds them on its own). Each directory holds the `ucdb.list` its
merge consumed. The dashboard's top-level numbers and its `Default | Including
Parked` toggle show one database or the other -- a parked failure can only
ever move the parked view, which is also why CI can run the parked tests
behind `--allow-failures`. The vendor-neutral exports (`cobertura.xml`,
`merged.ucis.xml`) stay default-scope. `--merge-existing` predates all this
and keeps merging whatever is on disk into the default scope.

Neither copy is committed: `coverage_report/` and `sim/*/regression_results.json`
are both gitignored, and the CI artifacts (see [CI](#ci)) are how a document
leaves the machine it was measured on.

`schema_version` 2 (schema 1 documents still render; they simply have no
parked rows or counts):

| Key | Contents |
| --- | --- |
| `generated`, `tb`, `cfg`, `testlist` | what produced this, as the user named it |
| `git` | `{sha, branch, dirty}`, or `null` outside a git checkout |
| `host` | `{name, os, python}` |
| `simulator` | `{name, version}` -- `vsim -version`, probed only for a `uvmt` run when `vsim` is on `PATH` |
| `summary` | `total`, `passed`, `failed`, `error`, `pass_rate`, `parked`, `parked_passed`, `start`, `end`, `duration_s` |
| `tests[]` | `name`, `verdict`, `detail`, `gen_seed`, `run_seed`, `duration_s`, `description`, `log`, `log_exists`, `published_log`, `parked` |

Three rules the format exists to enforce:

* **Nothing is invented.** A row parsed out of an old log (`--parse-only`) has
  `duration_s: null`, because nothing was timed; an empty run has
  `pass_rate: null`, because zero tests is not a 0% pass rate; a tarball with no
  `.git` has `git: null`. A batch that timed nothing at all also publishes
  `summary.start`, `summary.end` and `summary.duration_s` as `null`: the seconds
  between two timestamps of a `--parse-only` run are not that regression's wall
  time, and "0.0 s" underneath a 100% pass rate is exactly the invented number
  this report exists to remove. The dashboard renders every one of those as `N/A`.
* **Last batch wins.** Both copies of the document describe the batch that wrote
  them, so re-summarizing an old run with `--parse-only` replaces a measured
  document with a parsed one: the verdicts come back identical and the times come
  back `null`, because a batch that launches no simulation timed nothing. To get
  the measured numbers back, re-run the batch; to publish a document that is
  still on disk, point `bin/regression_report.py --results` at that copy. A
  coverage batch's document holds every row that batch ran -- the parked ones
  flagged `"parked": true`, badged `PARKED` on the page, and excluded from the
  page's default verdict -- because one batch's results belong in one document,
  not in two that can disagree.
* **The dashboard is a copy of the verdict table, never a second verdict.**
  Nothing in `bin/regression_report.py` can turn a FAIL into a pass, and
  publishing a failing or partially-parsed batch is deliberately supported.

`--report-only` belongs to the coverage report rather than to this document, and
neither report re-derives the other: it re-exports the Questa XML of the `.ucdb`
that is already merged and regenerates every coverage artifact out of it, running
no test and merging nothing (`--parse-only` and `--merge-existing` are rejected
beside it). A coverage-collection flag left on such a command line -- `--cov`,
`--cov-report` -- is therefore read and then ignored, a silent no-op, and the
coverage numbers it publishes describe the merged database rather than a batch
while its pass counts are the previous batch's, recovered because nothing ran
to recompute them: first from this document, whose rows name every test that ran
with its verdict and its parked flag (which is what both dashboard views
need), and only when no document from the same testbench and config is there,
from the `summary.json` on disk. That recovery pairs two artifacts, and the
harness says out loud when the two do not describe the same tests: each merged
database keeps an input list (`ucdb.list`), and a recovered set naming
different tests than that list gets a warning naming both sides instead of
publishing the pair silently -- a plain, non-coverage batch rewrites this
document while the merged databases of an older coverage batch sit there
untouched. The published `summary.json` is measured the same way, since it
records the names its own databases were built from. Two same-batch causes
move the lists apart as well, and the warning names them: a PASSing test that
left no `.ucdb` on disk is never merged, and `--merge-existing` merges every
`.ucdb` in the results tree. Neither can a merged database with no `ucdb.list`
beside it be checked, nor one paired with a summary that recorded no test
names, and both are said too. The metrics always come from the databases. The UCIS XML is the one place the two kinds of report meet, and it
keeps the same division: its history holds a single `merged` node, because the
rollup `bin/questa_xml_to_ucis_xml.py` reads does not name the tests the `.ucdb`
merged (the format itself would take one node per test), so per-test history --
verdicts, runtimes -- is not emitted there at all.

`coverage_report/` is generated and gitignored; the coverage job publishes it as
a GitHub Pages artifact, so `regression/` -- being a subdirectory of it -- is
deployed by that job without the job knowing about it. The coverage dashboard
links to it ("Regression results"), and the regression dashboard links back.
Preview a report tree locally with:

```bash
python3 -m http.server -d coverage_report 8080
```

Logs are copied into the report because they are gitignored and a verdict
without the log it came from is only half an answer. A log over 8 MiB is left
out and the page shows its path as text instead -- a broken link is worse. That
ceiling is not hypothetical: the sanity list's biggest log
(`illegal_instr_test`: 8,376,301 bytes of the 8,388,608 allowed) fits under it
with 12 KiB to spare, so a change that makes that test talk more turns its link
back into text on purpose rather than bloating the Pages deployment.

## Which tests exist

`bin/run_tests.py` keeps several named sets; `--help` prints them all.

| Set | Selected by | Notes |
| --- | --- | --- |
| `C_TESTS` + `ASM_TESTS` | default | the curated, self-checking directed programs |
| `UVMT_TESTS` | automatically with `--tb uvmt` | need uvmt stimulus with no core-TB equivalent (`nmi_test`) |
| `PARKED` | `--include-parked` | see below |
| `COREV_DV_TESTS` | `--include-corev-dv` / `--corev-dv-only` | generated programs; uvmt only. The generator (`make comp_corev-dv`, incremental -- it does not re-clone riscv-dv the way `make corev-dv` does) is built once per batch, then each test is generated and run in two vsim steps |
| `DISCOVERY_EXCLUDES` | never | known-broken, and covered by no other list |
| `--all-custom` | every directory under `tests/programs/*` | what the coverage job runs, so a new test program is picked up without editing Python |

### Tests that are known not to pass

They are not hidden. `PARKED` and `DISCOVERY_EXCLUDES` are the repository's
list, and a test that starts failing belongs in one of them with a note, not in
a deleted line of a testlist. Equally, "in a testlist" is not a claim that
somebody watched it pass: the sanity set is (see the measurement above), while
the extra directed tests in `cv32e20_ci_check.yaml` are listed because the
harness supports running them. The 15 corev-dv templates were measured on
Questa One 2025.3_2 (`--corev-dv-only --jobs 4`, 2026-10-31): 14 PASS, and
`corev_rand_interrupt_wfi` FAILED on one generation seed -- its program read a
debug CSR outside debug mode and tripped the core's illegal-cycle lockup check;
the two seeds run after it passed. A generated test is therefore only as good as
its seed, which is why the harness reports the generation seed per test. The
per-test table is in
[tests/programs/custom/README.md](../tests/programs/custom/README.md).

| Test | Where | Why it is not in a list |
| --- | --- | --- |
| `riscv_arithmetic_basic_test_0`, `riscv_arithmetic_basic_test_1`, `csr_instr_asm`, `riscv_csr`, `perf_counters_instructions` | `PARKED` | builds and runs on the core testbench but is not meaningfully self-checking there; verifying it needs `--tb uvmt` (step-and-compare against the ISS). `csr_instr_asm` and `riscv_csr` are also in `cv32e20_ci_check.yaml`, where a PASS banner would be the evidence to take them out of `PARKED` |
| `debug_test_boot_set`, `debug_test_reset`, `debug_test_known_miscompares`, `debug_test_trigger` | `PARKED` | debug mode needs uvmt stimulus, so they FAIL outright on the core testbench |
| `isa_fcov_holes`, `riscv_ebreak_test_0` | `DISCOVERY_EXCLUDES` | known-broken and in no curated list, so even `--all-custom` skips them |
| `cvxif_basic` | nowhere -- not a test-program | a UVM task in `tests/uvmt/firmware-tests/uvmt_cv32e20_general_purpose_test.sv`, compiled only with `CVE2_CONFIG=CV32E20X`; run it with the `cv32e20-dv: compile uvmt env (Questa, CV32E20X)` and `cv32e20-dv: run cvxif_basic UVM test (Questa, CV32E20X, no ISS)` tasks in `.theia/tasks.json`, or `make comp`/`make test TEST=cvxif_basic SIMULATOR=vsim CVE2_CONFIG=CV32E20X USE_ISS=NO` |

`--tb uvmt` runs `cvxif_basic` only when the design was compiled for CV32E20X,
which is why it is not in a testlist: a list cannot change the compile of a
shared design between tests without recompiling it for every one of them.

### The one test that outlives the default timeout

A test that needs longer than the 1800 s default says so in the testlist -- the
file-level `timeout:` or a per-entry one -- rather than by raising `--timeout`
for a whole batch: that default is what turns a hung simulation into an `ERROR`
row inside half an hour, and a batch-wide override spends the slack on every
other test as well.

`all_csr_por` is the only test that has needed more so far, and what to do about
it is an open decision. It reads the Power-on-Reset value of all 4K CSR
addresses and reports each one, so it is I/O-bound rather than compute-bound: a
single run's `trace_core_*.log` measures 572 MB, which is also the case the 8 MiB
log-publishing ceiling above exists for -- the dashboard prints that path as text
instead of linking it. Under the load of a four-job `--cov-report` batch it
exceeded 5400 s and became that batch's only `ERROR` row (2026-10-31); run alone
under `--timeout 7200` it printed PASS in 1:04:09 of wall time, per the
simulator's own end-of-run line. Neither number is the one to write down: a
per-test `timeout:` has to be measured on the configuration and the load the list
actually runs at. It is commented out of
`C_TESTS` and named by no testlist, which does not keep it out of the coverage
regression -- `--all-custom` selects every directory under
`tests/programs/custom/`, so the coverage job pays for it regardless. Listing it
properly means measuring that number and deciding whether an hour-long CSR sweep
belongs in a list that gates anything at all; until then it is discovered and
reported rather than curated.

## CI

| Workflow | Runner | When | What |
| --- | --- | --- | --- |
| [python-ci.yml](../.github/workflows/python-ci.yml) | hosted | trunk pushes, pull requests | byte-compiles `bin/`, runs the unit tests, checks the published `cov.tcl` cites, loads both testlists, smoke-tests the harness with `--parse-only`, validates the converted reports against `schemas/` with `xmllint`, lints markdown (advisory) |
| [self-hosted.yml](../.github/workflows/self-hosted.yml) | self-hosted | manual | `regress/cv32e20_sanity.yaml` for real, gating on its verdicts, and uploads the results |
| [coverage.yml](../.github/workflows/coverage.yml) | self-hosted | manual | the whole `--all-custom` coverage regression, validates the report formats, publishes `coverage_report/` (including `regression/` and `analysis/`) to Pages and to a rolling release, and uploads a flat `release-files` artifact of the pages and the data they fetch |

python-ci.yml is the workflow that makes CI able to fail. It needs no simulator,
which is the point: `--parse-only` on an empty results tree reports `ERROR` for
every test and `--allow-failures` turns that into exit 0. It proves the harness
starts, loads its lists, selects, and publishes -- a necessary condition for the
Questa jobs, never a substitute for them.

The cite check beside it is the same kind of claim about the committed analysis:
`bin/coverage_review.py --check-cites` re-reads `sim/tools/vsim/cov.tcl` and
fails when a line number published by the sheet or a raw dump no longer names its
own `coverage exclude` statement. It writes nothing, so it is cheap enough to run
on every push, and it is the only review promise here that can be kept without a
simulator or a license.

## Legacy tools

`bin/cv_regress`, `bin/ci_check` and `bin/metrics-regress` are inherited from
the old multi-core `core-v-verif` layout and **cannot run in this repository**:
they `import cv_regression` from a `bin/lib/` that was never copied here, expect
a `<core>/`-nested checkout, and `ci_check` drives a `.metrics.json` that does
not exist. `bin/README.md` documents their (incompatible, `builds:`-style) YAML
format for the same historical reason. They are kept for the day the upstream
`bin/lib/` arrives, not as a template for anything new -- the format above is
the one this repository runs.

## Adding a test to a regression

1. Add the test program under `tests/programs/custom/<name>/` (or a corev-dv
   template under `tests/programs/corev-dv/<name>/`).
2. If it is self-checking and finishes in a minute or two, add it to
   `regress/cv32e20_sanity.yaml`; otherwise to `regress/cv32e20_ci_check.yaml`.
   Give it a `description:` -- it is the only human-readable text the dashboard
   shows for it.
3. If it does not pass, do not list it: put it in `PARKED` (or
   `DISCOVERY_EXCLUDES`) with a comment saying why, and add it to the table
   above.
4. `bin/run_tests.py --testlist regress/cv32e20_sanity.yaml --parse-only` says
   whether the list still loads; `python3 -m unittest discover -s bin/tests -t
   bin/tests -p 'test_*.py'` says whether the lists still agree with each other.
