Tool-specific Makefiles for the CORE-V-VERIF UVM Verification Environment
==================================
This directory contains a set of simulator-specific Makefiles.
The Makefile selected is controlled by the `CV_SIMULATOR` shell environment variable.
For more information see Makefiles in [../README](../README.md#makefiles).

## Coverage "holes" reports (`vsim.mk`)

`cov_holes` and `cov_holes_details` report only what's *not* fully covered,
omitting any instance/coverage-type that's already at or above
`COV_HOLES_THRESHOLD` (default 100):

- `cov_func` -- the covergroup (functional) coverage as an HTML report. Unlike
  every other target here it takes **no** `COV_INSTANCE`: the environment's
  covergroups live in packages outside the DUT instance, so a scoped `fc`
  reports the RTL's own cover directives instead of the bins anyone cares
  about, near 100% while the real covergroups sit at zero.
- `cov_holes` -- compact: just the remaining coverage percentages, no source.
- `cov_holes_details` -- same filtering, plus full source-line detail for
  whatever's still incomplete.

Both accept the same `TEST=`/`MERGE=YES`/`COV_INSTANCE=` options as `cov`,
and write to `<COV_DIR>/cov_report/cov_holes[_details]`. The other report
targets (`cov`, `cov_txt`) are in `vsim.mk` beside them; the pipeline that
merges the per-test databases and publishes the result is
[`bin/run_tests.py --cov-report`](../../docs/regression.md).
