# Copyright (c) 2026 Eclipse Foundation
# SPDX-License-Identifier: Apache-2.0 WITH SHL-2.1
"""Every regress/*.yaml must load, name real tests, and agree with its own rules.

This is the test that keeps the testlists honest: they are the answer to "what
does a regression of this repository run?", and the previous answer (a cv_regress
YAML that nothing could execute, with a duplicated key in one entry) is exactly
what a test here would have caught."""

import sys
import unittest
from pathlib import Path

BIN = Path(__file__).resolve().parents[1]
REPO = BIN.parent
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

try:
    import run_tests  # noqa: E402
    HAVE_PYYAML = True
except ImportError:                                  # pragma: no cover
    HAVE_PYYAML = False

TESTLISTS = sorted((REPO / "regress").glob("*.yaml"))


@unittest.skipUnless(HAVE_PYYAML, "PyYAML not installed (bin/requirements.txt)")
class TestTestlists(unittest.TestCase):

    def test_there_are_testlists(self):
        self.assertTrue(TESTLISTS, "no regress/*.yaml found")

    def test_each_testlist_loads_and_names_real_tests(self):
        """load_testlist() already enforces the schema, the required keys, the
        no-duplicates rule and that every name is a test-program directory;
        reaching the end of the loop for every file *is* the assertion."""
        for path in TESTLISTS:
            meta, entries = run_tests.load_testlist(path)
            self.assertTrue(meta["name"], f"{path.name} has no name")
            self.assertTrue(entries, f"{path.name} selects nothing")

    def test_each_testlist_declares_a_supported_testbench(self):
        for path in TESTLISTS:
            meta, _ = run_tests.load_testlist(path)
            tb = meta.get("tb", "core")
            self.assertIn(tb, run_tests.TESTBENCHES,
                          f"{path.name}: unknown tb {tb!r}")

    def test_generation_tests_only_run_where_they_can(self):
        """corev-dv generation is a uvmt-only feature (gen_corev-dv is a uvmt
        make target), so a generated test in a core testlist would fail with a
        confusing make error."""
        for path in TESTLISTS:
            meta, entries = run_tests.load_testlist(path)
            if meta.get("tb", "core") == "core":
                continue
            for entry in entries:
                if run_tests.is_corev_dv(entry["name"]):
                    self.assertEqual(meta.get("tb"), "uvmt",
                                     f"{path.name}: {entry['name']} needs uvmt")

    def test_sanity_is_fast_by_construction(self):
        """The blocking list's whole claim is that it needs no program
        generation; if that changes, it stops being the sanity list."""
        path = REPO / "regress" / "cv32e20_sanity.yaml"
        if not path.is_file():
            self.skipTest("no cv32e20_sanity.yaml")
        _, entries = run_tests.load_testlist(path)
        generated = [entry["name"] for entry in entries
                     if run_tests.is_corev_dv(entry["name"])]
        self.assertEqual(generated, [], "sanity must not run corev-dv tests")

    def test_the_full_regression_contains_the_sanity_set(self):
        """Running the full regression should not need the sanity list too."""
        sanity = REPO / "regress" / "cv32e20_sanity.yaml"
        full = REPO / "regress" / "cv32e20_ci_check.yaml"
        if not (sanity.is_file() and full.is_file()):
            self.skipTest("sanity or ci_check testlist missing")
        _, sanity_entries = run_tests.load_testlist(sanity)
        _, full_entries = run_tests.load_testlist(full)
        missing = ({entry["name"] for entry in sanity_entries}
                   - {entry["name"] for entry in full_entries})
        self.assertEqual(missing, set(), f"ci_check is missing {sorted(missing)}")

    def test_no_testlist_selects_a_known_broken_test(self):
        """DISCOVERY_EXCLUDES is the repo's list of test-programs that are known
        not to pass; --all-custom skips them, so a testlist must not smuggle one
        back in."""
        for path in TESTLISTS:
            _, entries = run_tests.load_testlist(path)
            for entry in entries:
                self.assertNotIn(entry["name"], run_tests.DISCOVERY_EXCLUDES,
                                 f"{path.name} selects excluded "
                                 f"{entry['name']}")


if __name__ == "__main__":
    unittest.main()
