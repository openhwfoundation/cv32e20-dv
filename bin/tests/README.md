# Tests for the Python utilities in `bin/`

Plain [`unittest`](https://docs.python.org/3/library/unittest.html) modules --
there is no third-party test framework in this repository, and `bin/` has to keep
running on a bare interpreter, so neither should its tests. Run them from the
repository root:

```
python3 -m unittest discover -s bin/tests -t bin/tests -p 'test_*.py' -v
```

`bin/` is not a package, so each module puts it on `sys.path` itself -- the same
trick `bin/run_tests.py` uses to find its neighbours.

This directory is deliberately not under `tests/`: in this repository `tests/`
holds test-*programs* and UVM testcases (see `AGENTS.md`), not Python tests.

| Module | What it covers |
| --- | --- |
| `test_regression_report.py` | the results document: counting, N/A rules, publishing |
| `test_run_tests.py` | testlist loading, verdict classification, seed handling |
| `test_testlists.py` | every `regress/*.yaml` is well formed and names real tests |
| `test_converters.py` | Questa XML => Cobertura / UCIS on a tiny fixture |
