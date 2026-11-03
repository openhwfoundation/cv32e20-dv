# Copyright (c) 2026 Eclipse Foundation
# SPDX-License-Identifier: Apache-2.0 WITH SHL-2.1
"""Tests for bin/regression_report.py.

Nothing here needs a simulator, a git checkout with a particular state, or the
published templates -- the point is that the document and its counting rules hold
up on their own, since a wrong number on the dashboard is much harder to notice
than a wrong number in a terminal."""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

BIN = Path(__file__).resolve().parents[1]
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

import regression_report  # noqa: E402


def entry(name, verdict, **kwargs):
    return regression_report.test_entry(name, verdict, **kwargs)


class TestSummarize(unittest.TestCase):

    def test_empty_run_has_no_pass_rate(self):
        """0 tests is not a 0% pass rate -- see summarize()'s docstring."""
        summary = regression_report.summarize([])
        self.assertEqual(summary["total"], 0)
        self.assertIsNone(summary["pass_rate"])

    def test_counts_and_rate(self):
        entries = ([entry(f"t{i}", "PASS") for i in range(7)]
                   + [entry("bad", "FAIL"), entry("boom", "ERROR"),
                      entry("also", "PASS")])
        summary = regression_report.summarize(entries)
        self.assertEqual(summary["total"], 10)
        self.assertEqual(summary["passed"], 8)
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(summary["error"], 1)
        self.assertEqual(summary["pass_rate"], 80.0)

    def test_unknown_verdict_counts_as_error(self):
        """classify() only ever returns PASS/FAIL/ERROR today, but an unknown
        verdict must be reported, never dropped from the total."""
        summary = regression_report.summarize([entry("t", "WEIRD")])
        self.assertEqual(summary["total"], 1)
        self.assertEqual(summary["error"], 1)

    def test_parked_rows_count_in_the_rows_and_separately(self):
        """total/passed stay a plain count of every row (the document is
        honest about what it holds); parked/parked_passed are what lets the
        dashboard render the default set without re-reading the rows."""
        entries = [entry("a", "PASS"),
                   entry("p1", "PASS", parked=True),
                   entry("p2", "FAIL", parked=True)]
        summary = regression_report.summarize(entries)
        self.assertEqual(summary["total"], 3)
        self.assertEqual(summary["passed"], 2)
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(summary["parked"], 2)
        self.assertEqual(summary["parked_passed"], 1)

    def test_parked_defaults_to_false(self):
        self.assertFalse(entry("t", "PASS")["parked"])
        self.assertTrue(entry("t", "PASS", parked=True)["parked"])


class TestBuildDocument(unittest.TestCase):

    def test_document_shape(self):
        doc = regression_report.build_document(
            [entry("hello-world", "PASS", run_seed="1", duration_s=4.2)],
            "uvmt", "default", testlist="regress/cv32e20_sanity.yaml",
            started="2026-01-01T00:00:00+00:00",
            finished="2026-01-01T00:01:00+00:00", meta={})
        self.assertEqual(doc["schema_version"], regression_report.SCHEMA_VERSION)
        self.assertEqual(doc["tb"], "uvmt")
        self.assertEqual(doc["cfg"], "default")
        self.assertEqual(doc["testlist"], "regress/cv32e20_sanity.yaml")
        self.assertEqual(doc["summary"]["duration_s"], 60.0)
        self.assertEqual(doc["tests"][0]["name"], "hello-world")
        self.assertEqual(doc["tests"][0]["duration_s"], 4.2)

    def test_missing_times_stay_missing(self):
        doc = regression_report.build_document([entry("t", "PASS")], "core", "default")
        self.assertIsNone(doc["summary"]["duration_s"])
        self.assertIsNone(doc["summary"]["start"])

    def test_unparsable_times_do_not_raise(self):
        doc = regression_report.build_document([entry("t", "PASS")], "core", "default",
                                               started="yesterday", finished="today")
        self.assertIsNone(doc["summary"]["duration_s"])

    def test_generated_is_iso8601(self):
        doc = regression_report.build_document([], "core", "default")
        # Round-trips through fromisoformat(), which is what _elapsed() needs.
        self.assertIsNotNone(doc["generated"])
        from datetime import datetime
        datetime.fromisoformat(doc["generated"])


class TestPublish(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.doc = regression_report.build_document(
            [entry("hello-world", "PASS", run_seed="1")], "uvmt", "default",
            meta={"git": None, "host": {"name": "h", "os": "Linux", "python": "3"},
                  "simulator": None})

    def test_writes_document_and_templates(self):
        dest = self.tmp / "regression"
        regression_report.publish(self.doc, dest)
        self.assertTrue((dest / "regression_results.json").is_file())
        for name in ("index.html", "style.css"):
            self.assertTrue((dest / name).is_file(), f"{name} not published")
        # What was written must be readable as the document it claims to be.
        written = json.loads((dest / "regression_results.json").read_text())
        self.assertEqual(written["tests"][0]["name"], "hello-world")

    def test_missing_templates_warn_but_keep_the_document(self):
        """A partial report still has to be published (same policy as the
        coverage dashboard's copy step)."""
        original = regression_report.DASHBOARD_TEMPLATES
        regression_report.DASHBOARD_TEMPLATES = self.tmp / "nowhere"
        self.addCleanup(setattr, regression_report, "DASHBOARD_TEMPLATES", original)
        dest = self.tmp / "partial"
        regression_report.publish(self.doc, dest)
        self.assertTrue((dest / "regression_results.json").is_file())
        self.assertFalse((dest / "index.html").exists())

    def test_write_document_creates_parent_directories(self):
        path = self.tmp / "deep" / "nested" / "regression_results.json"
        regression_report.write_document(self.doc, path)
        self.assertTrue(path.is_file())


class TestPublishLogs(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.original = regression_report.REPO_ROOT
        regression_report.REPO_ROOT = self.tmp
        self.addCleanup(setattr, regression_report, "REPO_ROOT", self.original)

    def test_copies_existing_logs_and_records_them(self):
        log = self.tmp / "sim" / "uvmt" / "vsim_results" / "default" / "t" / "0"
        log.mkdir(parents=True)
        (log / "vsim-t.log").write_text("SIMULATION PASSED\n")
        entries = [entry("t", "PASS", run_seed="1",
                         log="sim/uvmt/vsim_results/default/t/0/vsim-t.log",
                         log_exists=True)]
        regression_report.publish_logs(entries, self.tmp / "out")
        self.assertEqual(entries[0]["published_log"], "logs/t-1.log")
        copied = self.tmp / "out" / "logs" / "t-1.log"
        self.assertTrue(copied.is_file())
        self.assertIn("PASSED", copied.read_text())

    def test_missing_log_is_not_published(self):
        entries = [entry("t", "ERROR", run_seed="1", log="sim/uvmt/nope.log",
                         log_exists=False)]
        regression_report.publish_logs(entries, self.tmp / "out")
        self.assertIsNone(entries[0]["published_log"])
        self.assertFalse((self.tmp / "out" / "logs").exists())

    def test_oversized_log_is_skipped_with_a_warning(self):
        """A runaway simulation log must not be copied into a published site."""
        log = self.tmp / "big.log"
        log.write_text("x" * 2048)
        entries = [entry("t", "FAIL", run_seed="1", log="big.log", log_exists=True)]
        regression_report.publish_logs(entries, self.tmp / "out", max_bytes=1024)
        self.assertIsNone(entries[0]["published_log"])


class TestMeta(unittest.TestCase):

    def test_collect_meta_never_raises_without_tools(self):
        """No git, no Questa: every probe degrades to None, not an exception."""
        original = regression_report._run_quiet
        regression_report._run_quiet = lambda cmd, timeout=20: None
        self.addCleanup(setattr, regression_report, "_run_quiet", original)
        meta = regression_report.collect_meta("uvmt", "default")
        self.assertIsNone(meta["git"])
        self.assertIsNone(meta["simulator"])
        self.assertIn("python", meta["host"])

    def test_simulator_only_probed_for_uvmt(self):
        self.assertIsNone(regression_report.simulator_meta("core"))

    def test_main_republishes_an_existing_document(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        source = tmp / "regression_results.json"
        source.write_text(json.dumps({"schema_version": 1, "tests": [],
                                      "summary": {"total": 0}}))
        out = tmp / "published"
        self.assertEqual(
            regression_report.main(["--results", str(source), "--out", str(out)]), 0)
        self.assertTrue((out / "index.html").is_file())
        self.assertTrue((out / "regression_results.json").is_file())


if __name__ == "__main__":
    unittest.main()
