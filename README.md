<!--
Copyright 2022 OpenHW Group
SPDX-License-Identifier: Apache-2.0 WITH SHL-2.1
-->
# Verification Environment for the CV32E20 CORE-V processor core.
This directory hosts the CV32E20-specific SystemVerilog sources plus C and assembly test-program sources for the CV32E20 verification environment.
Non-CV32E20-specific verification components (e.g. OBI Agent) used in this verification environment are in `vendor_lib/openhwgroup_core-v-verif`.

## Directories:
- **bin**:        the Python/shell scriptware: `run_tests.py` (the regression harness), `regression_report.py` (its results document and dashboard) and the coverage-report converters. See [bin/README.md](bin/README.md).
- **bsp**:        the "board support package" for test-programs compiled/assembled/linked for the CV32E20.  This BSP is used by both the `core` testbench and the `uvmt_cv32` UVM verification environment.
- **docs**:       repository documentation, e.g. [docs/regression.md](docs/regression.md) (testlists, verdicts, the results dashboard, CI).
- **env**:        the UVM environment class and its associated infrastrucutre.
- **mk**:         Makefiles and related scriptware. You may find it useful to review the [Common Makefile README](https://github.com/openhwgroup/core-v-verif/blob/master/mk/README.md).
- **regress**:    the regression testlists (`*.yaml`) that `bin/run_tests.py --testlist` runs.
- **schemas**:    the vendored report schemas (`coverage-04.dtd`, `ucis.xsd`) that `bin/`'s converters' output is validated against.
- **sim**:        directory where you run the simulations.
- **tb**:         the Testbench module that instanitates the core.
- **templates**:  the static HTML/CSS of the published reports: `coverage_dashboard/`, `regression_dashboard/` and `analysis_dashboard/` (the waiver and open-hole triage page, which reads the CSVs committed under `docs/coverage/`), plus `common/`, the stylesheet all three of them link. All are copied into `coverage_report/` (into `coverage_report/regression/` and `coverage_report/analysis/` for those two) when a report is generated.
- **tests**:      this is where all the testcases are.
- **vendor_lib**: Third party vendor libraries and extensions to same.

There are README files in each directory with additional information.

## Running a regression

Tests are run through `bin/run_tests.py`, which reads a curated testlist out of
`regress/`, runs each test's `make test`, reads the verdict out of the testbench's
pass/fail banner, and publishes a dashboard of the results:

```bash
bin/run_tests.py --testlist regress/cv32e20_sanity.yaml
```

The format of a testlist, what counts as a pass, which tests are known not to
pass and why, and what each CI job runs, are all in
[docs/regression.md](docs/regression.md).

## Getting Started
Check out the Quick Start Guide in the [CORE-V-VERIF Verification Strategy](https://docs.openhwgroup.org/projects/core-v-verif/en/latest/quick_start.html).
