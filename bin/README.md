Core-V-Verif Utilities
==================================

This directory contains various utilities for running tests and performing various verification-related 
activities in the core-v-verif repository.

Unless otherwise noted all utilities in this directory should be agnostic to $CWD.  Therefore a user
should be able to run the utilities via a PATH from any directory.  The utilities will be able to 
determine their own directory based on the implementation language hooks available.

For example from a bash-type shell:<br>
> % export PATH=./core-v-verif/bin:$PATH

Requirements
============
Much of the scriptware in CORE-V-VERIF is written in python and makes use of external packages that are not necessarily distributed with python itself.
An easy way to get the Python plug-ins installed on your machine is:
> % git clone https://github.com/openhwgroup/core-v-verif.git \<core-v-verif><br>
> % cd \<core-v-verif>/bin<br>
> % pip3 install -r requirements.txt<br>

Note that *cv32e20-dv* is a standalone repository, so the equivalent here is
`pip3 install -r bin/requirements.txt` from the repository root. The regression
harness below deliberately needs none of those packages to run (PyYAML is the
one exception, and only for `--testlist`); the rest of the tools in this
directory do.

Running tests in this repository
================================

## run_tests.py

The regression harness: it selects tests, invokes `make test TEST=<name> ...` in
the chosen testbench's sim directory, reads the verdict out of the simulation
log's pass/fail banner, prints a summary table and publishes a dashboard. It is
a plain Python 3 (>= 3.7) script with no build products of its own, and it is
the only supported way to run a set of tests here.

```
bin/run_tests.py --testlist regress/cv32e20_sanity.yaml   # the blocking list
bin/run_tests.py --tb uvmt hello-world                    # one test
bin/run_tests.py --tb uvmt --parse-only                   # just re-read the logs
bin/run_tests.py --help                                   # everything else
```

`--help` is long on purpose: it documents the two testbenches' verdict banners,
the seed model (`--seed` for the run, `--gen-seed` for corev-dv program
generation, both reported back per test), the coverage-report pipeline, the
`--jobs` concurrency model and its Questa-licence caveat, and the exit-code
rules that make the script usable as a CI gate. The prose around all of that -
which tests are curated, which are parked and why, and what CI runs - lives in
[docs/regression.md](../docs/regression.md).

## regression_report.py

Owns the results document (`regression_results.json`) that `run_tests.py`
publishes after every batch, and the static dashboard in
`templates/regression_dashboard/` rendered from it. Run it stand-alone to
re-publish the page from a document that is already on disk without simulating
anything:

```
bin/regression_report.py --results sim/uvmt/regression_results.json \
                        --out coverage_report/regression
```

## Coverage-report converters

`--cov-report` merges the per-test `.ucdb` files and publishes
[coverage_report/](../coverage_report/); these two converters turn Questa's own
XML export of the merged database into the formats other tools read:

| Converter | From | To |
| --- | --- | --- |
| `questa_xml_to_cobertura.py` | DUT-scoped `-details -code scb` export | `cobertura.xml` (DTD in `schemas/`) |
| `questa_xml_to_ucis_xml.py` | the per-line *and* per-covergroup detail exports | `merged.ucis.xml` (schema in `schemas/ucis.xsd`) |

The UCIS document is written in the interchange format PyUCIS reads, so the
coverage of a regression opens in the tools of that ecosystem rather than only in
this repository's dashboard. PyUCIS is deliberately not in `bin/requirements.txt`
(nothing here imports it), so the viewer is an explicit install:

```
pip3 install "pyucis>=0.2.0"          # the reader; 0.2.0 for the reason below
pyucis-viewer coverage_report/merged.ucis.xml     # the covergroup tree, per bin
```

One caveat when using it: `pyucis` <= 0.1.4 divides by a covergroup-weight total
it never guards, so its viewer stops with `ZeroDivisionError` on any UCIS
database that reports code coverage for an instance without covergroups -- that
is, on any real one. Upstream fixed it in 0.2.0; a viewer built against 0.2.0 or
newer opens the report normally. `xmllint --noout --schema schemas/ucis.xsd
coverage_report/merged.ucis.xml` says whether the artifact itself is valid
(`bin/tests/test_converters.py` runs the same check in CI, in the
`reports-schema` job that installs `libxml2-utils`).

What the converter leaves out is in its module docstring, and none of it is
silently. Most gaps are Questa's and each is handled a different way. A bin has
no value domain in the export (its domain is free text in `<bin_rhs>`) while the
schema wants a range, so the bin is written with the nominal `0..0` and its
identity is its name. A multi-term condition has no expression anywhere in the
export, so only a condition of one sub-expression is written and the rest are
dropped and counted. A covergroup has no source line, and the schema wants a file
and a line of every object, so it is located rather than dropped: line 1 of the
package file its own export names. Assertion and FSM coverage arrive as counts
with no individual name to point at, so those kinds are absent. A cross bin is
the opposite case - Questa *does* name the combination it counts
(`<auto[ZERO],auto[POSITIVE]>`) without naming the UCIS index of those bins, so
the index is looked up in the crossed coverpoint, and only a bin Questa gives no
one combination for is left out, counted rather than dropped. Measured on the
database this was written for, none of the 387 `*` bins left out was ever hit,
and of the 63 ignore bins left out the 37 that carry a count report occurrences
of an *ignored* combination, not hits. The history node is Questa's gap too, in
another way: the schema takes one node per test, while the rollup names none of
the tests the `.ucdb` merged, so the document describes the merge and
`sim/uvmt/regression_results.json` stays the authority on verdicts. The
docstring's list is the full account, and one gap belongs to the format rather
than to Questa: it carries no aggregate metric, so the percentages stay in
`summary.json`. The Questa HTML report is where every one of those counts can
still be read.

## Coverage analysis

Three scripts, one artifact: the review sheet in
[docs/coverage/coverage_review.csv](../docs/coverage/coverage_review.csv), one
row per waiver in `sim/tools/vsim/cov.tcl` and one row per coverage hole that
survives those waivers.

| Script | Needs Questa? | What it does |
| --- | --- | --- |
| `coverage_waiver_audit.py` | measuring does; `--parse-only` does not | Applies every `coverage exclude` in `cov.tcl` to the merged `.ucdb` in a report-only `vsim -viewcov` session and then lifts them one at a time, so a waiver that matches nothing (`NO-OP`), aims at a line the RTL no longer has (`MIS-AIMED`) or hides *covered* code (`HIDING-COVERED-CODE`) is measured rather than noticed. `cov.tcl`'s header explains why this is the only reliable check: Questa accepts an exclusion that matches nothing and says nothing. |
| `coverage_holes.py` | only to apply the current `cov.tcl`; `--report <file>` re-reads a saved dump | Lists every still-missed bin (statement, branch, condition, FSM, assertion) with its design unit, file, line and metric, and cross-checks its own row count against Questa's `coverage report -summary` before writing. |
| `coverage_review.py` | no | Merges the two dumps into the sheet, deriving each row's triage verdict from the measured row; `Reviewer`, `Review Date` and `Notes` come out empty for a human. UTF-8 BOM and CRLF, and no cell ever holds a newline, so it opens as a table in Excel and Google Sheets. `--check-cites` writes nothing and only asks whether the `cov.tcl` line numbers the dumps publish still name their own exclusion. Run it after editing `cov.tcl`, comments included. |

The raw dumps and the sheet live under `docs/coverage/` (they are KB-scale and
let a reviewer re-check a verdict without Questa); the Questa sources they came
from stay in `sim/`. `bin/run_tests.py` mirrors the committed sheet and dumps into
the published tree as `coverage_report/analysis/`, beside the page that fetches
them (`templates/analysis_dashboard/`); that mirror is one-way and nothing here
reads it back, which is also why `coverage_holes.py`'s `--by-du` rollup is written
there rather than committed: the page counts the same thing out of `raw/holes.csv`
itself. Setup, the regeneration recipe and the failure modes are in
[docs/coverage/README.md](../docs/coverage/README.md), and
`bin/tests/test_coverage_review.py` keeps the parser, the triage rules, the sheet
format and those published `cov.tcl` cites honest on a hosted runner (the cite
check needs the dumps in the tree, and skips where they are not published yet).

## Regression YAML format (the one run_tests.py reads)

Testlists live in `regress/`. `bin/cv_regress` **cannot** read this format and
`run_tests.py` cannot read the `builds:`-style format below - see
[Legacy tools](#legacy-tools).

```
name: <string>                    # required; shown on the published dashboard
description: <string>             # required
tb: core|uvmt                     # optional (default core)
cfg: <string>                     # optional; the --cfg equivalent
timeout: <seconds>                # optional
jobs: <number>                    # optional
seed: <int|random>                # optional
make_args: [<string>, ...]        # optional, appended to every make call
tests:                            # ordered
  - name: <string>                # required: a directory under tests/programs/{custom,corev-dv}
    description: <string>         # optional; shown on the dashboard
    make_args: [<string>, ...]    # optional extra make args for this test
```

Any key outside that list is an error rather than ignored, a name with no
test-program directory is an error, and the file only supplies defaults - an
option given on the command line still wins. There is no `num:`: run the list
again with a different `--seed`, which is reproducible and keeps both runs in
the results document. `regress/cv32e20_sanity.yaml` and
`regress/cv32e20_ci_check.yaml` are the two that ship.

Legacy tools
============

The utilities below came with the environment when this repository was extracted
from the multi-core *core-v-verif* tree. **None of them can run here:** they
`import cv_regression` from a `bin/lib/` that was not part of the extraction,
`ci_check` drives a `.metrics.json` that does not exist, and they expect a
`<core>/`-nested checkout rather than this layout. They are left in place
because the upstream tooling may one day be restored, not because anything here
uses them - use `run_tests.py` above.

Utility Documentation
=====================

Documentation for each of the utilities are included below.  Each utility should also support a help option
on the command line for describing options and arguments available.

## makeuvmt
This is a simple wrapper to redirect a make call to any core's UVMT Makefile.  This redirection script
simply requires that you either:
- specify CV_CORE in your environment -or-
- specify CV_CORE on the makeuvmt command line as an override

The script will then invoke make in the following directory:<br>
> \<core-v-verif>/$(CV_CORE)/sim/uvmt

This should enable simulations to be executed regardess of current shell directory.  All common make flags
and conventions should be passed to the underlying Makefile directory.

*Examples:*
> \# makeuvmt can be invoked from any directory<br>
> % makeuvmt test TEST=hello-world WAVES=1 SIMULATOR=vsim<br>
> \# Override the core to cv32e40x (regardless of CV_CORE environment setting)<br>
> % makeuvmt test TEST=hello-world WAVES=1 CV_CORE=cv32e40x<br>

## ci_check

**Legacy, cannot run - see [Legacy tools](#legacy-tools).**

Continuous integration checker script.  This script runs a quick sanity regression on the requested
simulator for the purposes of ensuring a pull-request can be safely made.  Note that *ci_check* should now
be able to be executed in any directory where previously it required the user to *cd* to ci/.  Please
refer to *ci_check*'s help utility for more details on options

If required, the step and compare ISS can be disabled for this regression by setting _--iss=0_

*Examples:*
> \# Run CI sanity regression on Xcelium<br>
% ci_check -s xrun<br>
> \# Run CI sanity regression on Xcelium with the ISS disabled<br>
% ci_check -s xrun --iss=0<br>
> \# Get help of all available options<br>
% ci_check --help

## cv_regress

**Legacy, cannot run - see [Legacy tools](#legacy-tools).**

Regression script generator utility.  *cv_regress* will read in one or more regressions defined in a specific
YAML format into an output format suitable for the specified regression platform or utility.  The currently supported
output platforms are:<br>
- Metrics JSON (--metrics)
- Shell Script (--sh)
- Vmanager VSIF (--vsif)

The format of the YAML testlist file is given below.  All YAML regression testslists should go in the following directory:
> core-v-verif/\<project>/regress<br>

where *\<project>* is a core (cv32e40p or cva6)

Note that the utility has the ability to combine multiple testlists to build larger regressions.  Therefore the --file
option may be specified multiple times.

Please refer to the help utility of *cv_regress* for more details on the utility.

*Examples:*
> \# Read in *cv32e40p_ci_check* testlist with Questa and emit an executable shell script<br>
% cv_regress --file=cv32e40p_ci_check.yaml --simulator=vsim --outfile=vsim_ci_check.sh

### Regression YAML Format

The following describes the YAML format for regression testlists.  **This is the
legacy `cv_regress` format, kept for the tool above; the format this repository
actually runs is [above](#regression-yaml-format-the-one-run_testspy-reads).**

>\<*Required*: the name of the testlist><br>
name: \<string\><br>
\<*Required*: human-readable description to specify the intent of the testlist><br>
description: \<string><br>
><br>
\# List of builds, this can include SystemVerilog compiles and riscv-dv compiles<br>
\# Multiple builds may be defined<br>
builds:<br>
&nbsp;&nbsp;build_name0:<br>
&nbsp;&nbsp;&nbsp;&nbsp;<*Required*: make command for the build><br>
&nbsp;&nbsp;&nbsp;&nbsp;cmd: make comp<br>
&nbsp;&nbsp;&nbsp;&nbsp;<*Required*: make directory for the build><br>
&nbsp;&nbsp;&nbsp;&nbsp;dir: cv32/sim/uvmt_cv32<br>
><br>
\# List of tests<br>
\# Multiple tests can be defined<br>
tests:<br>
&nbsp;&nbsp;test_name0:<br>
&nbsp;&nbsp;&nbsp;&nbsp;<*Required*: build dependencies, can be a list of single build_name><br>
&nbsp;&nbsp;&nbsp;&nbsp;build: \<string><br>
&nbsp;&nbsp;&nbsp;&nbsp;<*Required*: human-readable test description><br>
&nbsp;&nbsp;&nbsp;&nbsp;description: \<string><br>
&nbsp;&nbsp;&nbsp;&nbsp;<*Required*: make directory for the test><br>
&nbsp;&nbsp;&nbsp;&nbsp;dir: \<string><br>
&nbsp;&nbsp;&nbsp;&nbsp;<*Optional*: A make command to run before running the test(s).  This could be used for gen_* makes for corev-dv<br>
&nbsp;&nbsp;&nbsp;&nbsp;precmd: \<string><br>
&nbsp;&nbsp;&nbsp;&nbsp;<*Required*: make directory for the test><br>
&nbsp;&nbsp;&nbsp;&nbsp;cmd: \<string><br>
&nbsp;&nbsp;&nbsp;&nbsp;<*Optional*: The number of test iterations to run.  Note that all runs will receive a random seed><br>
&nbsp;&nbsp;&nbsp;&nbsp;num: \<number>


