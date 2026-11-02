# Coverage analysis artifacts

Everything in this directory is **derived** from a coverage run and **committed**
on purpose: a reviewer should be able to re-check any triage decision here without
Questa and without access to the simulation tree. Until a tree has committed them
they are simply absent, and the tools that read them skip the checks that need
them rather than inventing fixture data.

Nothing under `coverage_report/` belongs here and nothing here belongs there.
`coverage_report/` is generated, published and gitignored; it also gets wiped by
`run_tests.py --cov-report`, which is why the analysis is copied *out* of it and
committed here. The direction never reverses: see
[The two copies of the analysis](#the-two-copies-of-the-analysis).

## What is here

| File | What it is | Produced by |
| --- | --- | --- |
| `coverage_review.csv` | **The review sheet.** One row per `cov.tcl` waiver and per open hole, with the triage verdict. | `bin/coverage_review.py` |
| `coverage_review.md` | How to read the sheet, the triage rules, the waiver policy, the current verdicts, and the baseline percentages the analysis started from. | hand-written |
| `raw/waiver_audit.csv` | One row per `coverage exclude` in `sim/tools/vsim/cov.tcl`, with the measured effect of lifting it. | `bin/coverage_waiver_audit.py` |
| `raw/holes.csv` | Every bin still missed with those exclusions in force, one row per missed bin. | `bin/coverage_holes.py` |
| `raw/phase_c_acceptance.csv` | The Phase C acceptance measurement: the 16 reset-transition waivers and the `cve2_controller.sv:514` branch, per seed and per merged database, as the two directed tests' own databases report them. | `vcover report -showexcluded`, commands and reading guide in `coverage_review.md`; its `cov.tcl Line` column is not a measurement: it is re-derived from `raw/waiver_audit.csv`, so re-check it after any `cov.tcl` edit |

Two derived things are deliberately *not* committed here. The run's
`coverage_report/summary.json` is a generated artifact, and the numbers that
matter to the review are quoted out of it, verbatim and with their date, in the
"Current state" section of `coverage_review.md`. The per-design-unit hole rollup
is a count of `raw/holes.csv`, which the published analysis page recomputes
instead of reading a second copy of the same fact: `bin/coverage_holes.py` writes
it to `coverage_report/analysis/raw/holes_by_du.csv`, beside the report it
describes.

Keep the committed dumps small (they are a few tens of KB). The Questa sources
they came from stay in `sim/`: `merged.ucdb` (319 KB), `cvg_detail.xml` (18.7 MB)
and `coverage_report/merged.ucis.xml` (6.4 MB) must **not** be committed here.

## The two copies of the analysis

This directory holds the copy a reviewer reads and the tools read back: the
sheet, the dumps, and the arguments beside them. `coverage_report/analysis/`
holds the copy a *browser* fetches: `publish_coverage_analysis()` in
`bin/run_tests.py` copies these same files into the published tree beside the
page that reads them (`templates/analysis_dashboard/`), because that is where
anybody looking for anything coverage-related looks.

The mirror is one-way. It is rewritten with every report and nothing reads it
back, so an edit to `coverage_report/analysis/coverage_review.csv` is lost on the
next run: edit the file here and republish. And the page renders only what these
files say -- every verdict in it came from `bin/coverage_review.py`'s triage
rules and its `HOLE_TRIAGE` table, and a dump this run did not publish shows up
as a table that says so rather than as a zero.

## Setting the environment up

The analysis scripts that only read a CSV need nothing but Python. The two that
ask Questa questions need the simulator on `PATH`. Which install that is belongs
to the site, not to this repository, so define the function the tasks call in
your own shell and point it at your own license server:

```bash
# Site-specific: point QUESTAROOT at your Questa One install and your license server.
set_questa_one_2025 () { export QUESTAROOT=<questasim-install>; export QSIM_VCO_MODE=64; export PATH=$QUESTAROOT/bin/:$PATH; export LD_PRELOAD=/usr/lib64/libstdc++.so.6; export MODEL_TECH=$QUESTAROOT/bin; export SALT_LICENSE_SERVER=<port>@<host>; }
set_questa_one_2025
export CV_SW_TOOLCHAIN=/opt/riscv
export SIMULATOR=vsim USE_ISS=NO
```

The host `python3` is too old for `bin/`, so use the repository's own Python:

```bash
venv_cv32e20-dv/bin/python bin/coverage_review.py --summary
```

`coverage_waiver_audit.py --parse-only` and `coverage_holes.py --report <file>`
deliberately need no licence: the first only parses `cov.tcl`, the second only
re-reads a saved report.

## The three artifacts the analysis reads

| Artifact | Where | Notes |
| --- | --- | --- |
| `merged.ucdb` | `sim/uvmt/vsim_results/default/merged/merged.ucdb` | The merged coverage database a `--cov-report` batch leaves behind. Both Questa scripts read it **report-only** (`vsim -viewcov`, `vcover report`): they never write it, and both record its md5 before and after so a claim can be tied to a specific database. |
| `dut_detail.xml` | `sim/uvmt/vsim_results/default/merged/dut_detail.xml` | Questa's DUT-scoped code-coverage XML export, the input of `bin/questa_xml_to_cobertura.py`. Not used by the two analysis scripts (Questa's own text holes report is a more faithful source of "is this bin missed" than the XML), but it is what the published Cobertura data comes from. |
| `merged.ucis.xml` | `coverage_report/merged.ucis.xml` | The UCIS interchange document of the same run, published for external consumers; see `docs/regression.md`. |

## Regenerating everything

```bash
# 0. after ANY edit to cov.tcl, comments included, before quoting anything:
#    do the line numbers these dumps publish still name their own waiver?
#    Writes nothing, needs no simulator, prints every stale cite and exits 1.
venv_cv32e20-dv/bin/python bin/coverage_review.py --check-cites

# 1. holes, with cov.tcl exactly as it is now
venv_cv32e20-dv/bin/python bin/coverage_holes.py --apply-cov-tcl --summary \
    --work-dir log_agent/covholes --timeout 3600

# 2. audit every waiver against the same database
venv_cv32e20-dv/bin/python bin/coverage_waiver_audit.py --timeout 3600 \
    --work-dir log_agent/waudit

# 3. merge the two dumps into the sheet
venv_cv32e20-dv/bin/python bin/coverage_review.py --summary
```

Steps 1 and 2 each open one report-only `vsim -viewcov` session, so the whole
thing costs a couple of minutes and cannot disturb a running regression. Step 1
has to run before step 2: the audit uses `raw/holes.csv` to tell a waiver that
excludes nothing from one aimed at the wrong line. Step 0 is the one to run when
`cov.tcl` changed but no new measurement was taken: every cite below is a line
number of that file, so inserting a comment moves them all, and a stale one still
looks plausible in a spreadsheet.

Both Questa scripts write their scratch (Tcl driver and raw `coverage report` text) into `--work-dir`, which the commands above point at `log_agent/`: never into `coverage_report/`, and never into `docs/coverage/raw/` except for the CSVs listed in the table above.

The covergroup HTML report the dashboard's **Functional Coverage** button opens (`coverage_report/questasim_func/`) comes from the same merged database and is not regenerated here: `make MERGE=YES cov_func CFG=default` reproduces it inside `sim/`, and `bin/run_tests.py` publishes it beside the code report as `vcover report -html -details -precision 2 -cvg`, deliberately **no** `-instance`, because the environment's covergroups live outside the DUT instance, while the code report keeps `-instance=<DUT>.` for the opposite reason. `docs/regression.md` states the invariant where both commands live.

## If the numbers look wrong

* **A waiver you just edited is reported as a no-op.** A merged `.ucdb` carries
  the exclusions that were in force when the tests were saved, not the ones in
  the file now. Both scripts therefore apply the current `cov.tcl` first (and
  the audit measures each waiver by lifting it). If you bypass that, you are
  measuring the old file.
* **A proposed assertion exclusion does nothing when pasted.** Pairing `-du` with `-assertpath` matches nothing, without an error. That is the exact failure mode this directory exists to catch, and the sheet met it in its own proposals. The working form is `coverage exclude -assertpath <path> -comment {…}` with no `-du`; `bin/tests/test_coverage_review.py` pins it so the generator cannot drift back.
* **A tool reports zero holes.** Suspicious by construction. `coverage_holes.py`
  cross-checks its rows against Questa's own `coverage report -summary` miss
  counts and refuses a rollup it cannot reproduce; if the vsim session wrote no
  report at all it exits non-zero rather than printing "0 holes".
* **The percentages moved.** Compare the freshly published
  `coverage_report/summary.json` against the baseline table in the "Current
  state" section of `coverage_review.md`, and read the warning at the top of
  `sim/tools/vsim/cov.tcl`: a number quoted in a waiver comment is history from
  whichever database produced it.

## Related documents

* `docs/regression.md` -- running the regression and publishing the reports.
* `mk/uvmt/README.md` -- the `cov`, `cov_txt`, `cov_func`, `cov_holes` and
  `cov_holes_details` make targets that produce the same views inside `sim/`.
* `sim/tools/vsim/cov.tcl` -- the waivers themselves, with their arguments.
* `docs/coverage/coverage_review.md` -- the sheet's column definitions and the
  triage and waiver rules it is built to enforce.
