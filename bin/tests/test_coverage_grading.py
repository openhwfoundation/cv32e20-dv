# Copyright (c) 2026 Eclipse Foundation
# SPDX-License-Identifier: Apache-2.0 WITH SHL-2.1
"""Per-test coverage grading: row shapes, the unique-contribution delta,
the pertest index page and its summary.json block.

The delta is the arithmetic a review trusts -- "deleting this test from the
merge costs exactly this much" -- so its edge cases are pinned here:
metrics with no active objects contribute no number (not a zero), a
negative difference clamps to zero instead of printing an accusation, the
aggregate percent is taken over the *merged* active count (not the mean of
per-metric percents), and None rollups degrade to N/A rather than raising:
one failing vcover export must cost a cell, never the whole page.
"""

import sys
import unittest
from pathlib import Path

BIN = Path(__file__).resolve().parents[1]
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

import coverage_grading  # noqa: E402


def code_metrics(code=None, **metric):
    """A parse_questa_code_rollup()-shaped dict."""
    out = {"code": code}
    for name in ("statement", "branch", "condition", "fsm_state",
                 "fsm_transition"):
        value = metric.get(name)
        out[name] = dict(value) if value else {}
    return out


class TestFormatPercent(unittest.TestCase):
    def test_cells(self):
        self.assertEqual(coverage_grading.format_percent(None), "N/A")
        self.assertEqual(coverage_grading.format_percent(98.493), "98.49 %")
        self.assertEqual(coverage_grading.format_percent(0), "0.00 %")


class TestTestRow(unittest.TestCase):
    def test_none_rollups_degrade_to_na(self):
        row = coverage_grading.test_row("t", None, None, None)
        self.assertEqual(row["test"], "t")
        self.assertIsNone(row["code"])
        self.assertIsNone(row["functional"])
        self.assertEqual(row["functional_bins"], [0, 0])
        self.assertEqual(row["unique"], None)
        for metric, _label in coverage_grading._METRICS:
            self.assertEqual(row["metrics"][metric], {})

    def test_values_are_copied_not_aliased(self):
        metrics = code_metrics(code=90.0, statement={"active": 10,
                                                     "percent": 80.0})
        functional = {"percent": 50.0, "bins_covered": 5, "bins_total": 10}
        row = coverage_grading.test_row("t", "x.ucdb", metrics, functional)
        self.assertEqual(row["code"], 90.0)
        self.assertEqual(row["metrics"]["statement"], {"active": 10,
                                                       "percent": 80.0})
        self.assertEqual(row["functional_bins"], [5, 10])
        row["metrics"]["statement"]["active"] = 999
        self.assertEqual(metrics["statement"]["active"], 10)


class TestDelta(unittest.TestCase):
    def test_no_merged_code_is_no_delta(self):
        self.assertIsNone(coverage_grading.delta(None, None, None, None))
        self.assertIsNone(coverage_grading.delta({}, {}, None, None))

    def test_per_metric_and_aggregate(self):
        merged = code_metrics(
            statement={"active": 100, "hits": 60},
            branch={"active": 100, "hits": 40})
        residual = code_metrics(
            statement={"active": 100, "hits": 55},
            branch={"active": 100, "hits": 40})
        unique = coverage_grading.delta(merged, residual, None, None)
        self.assertEqual(unique["metrics"]["statement"],
                         {"active": 100, "unique_hits": 5, "percent": 5.0})
        self.assertEqual(unique["metrics"]["branch"]["unique_hits"], 0)
        # Aggregate over the merged active total: 5 unique of 200 active.
        self.assertEqual(unique["code_percent"], 2.5)

    def test_inactive_metrics_absent_negative_clamped(self):
        merged = code_metrics(statement={"active": 10, "hits": 4},
                              branch={"active": 0, "hits": 0})
        residual = code_metrics(statement={"active": 10, "hits": 9})
        unique = coverage_grading.delta(merged, residual, None, None)
        self.assertNotIn("branch", unique["metrics"])
        self.assertEqual(unique["metrics"]["statement"]["unique_hits"], 0)
        self.assertEqual(unique["code_percent"], 0.0)

    def test_functional_bins(self):
        merged_f = {"percent": 70.0, "bins_covered": 70, "bins_total": 100}
        residual_f = {"percent": 69.0, "bins_covered": 69, "bins_total": 100}
        unique = coverage_grading.delta(code_metrics(), code_metrics(),
                                        merged_f, residual_f)
        self.assertEqual(unique["functional_bins"],
                         {"total": 100, "unique_hits": 1, "percent": 1.0})
        unique = coverage_grading.delta(code_metrics(), code_metrics(),
                                        merged_f, None)
        self.assertEqual(unique["functional_bins"]["unique_hits"], 70)

    def test_missing_residual_counts_everything_unique(self):
        merged = code_metrics(statement={"active": 10, "hits": 4})
        unique = coverage_grading.delta(merged, None, None, None)
        self.assertEqual(unique["metrics"]["statement"]["unique_hits"], 4)


class TestRenderPertestIndex(unittest.TestCase):
    def _rows(self):
        rows = [
            coverage_grading.test_row("beta", "b.ucdb",
                                      code_metrics(code=50.0), None),
            coverage_grading.test_row("alpha", "a.ucdb",
                                      code_metrics(code=80.0), None),
            coverage_grading.test_row("na", None, None, None),
        ]
        rows[0]["unique"] = coverage_grading.delta(
            code_metrics(statement={"active": 10, "hits": 3}),
            code_metrics(statement={"active": 10, "hits": 1}), None, None)
        return rows

    def test_sorted_best_first_and_na_last(self):
        page = coverage_grading.render_pertest_index(self._rows())
        self.assertLess(page.index("alpha"), page.index("beta"))
        self.assertLess(page.index("beta"), page.index(">na<"))
        self.assertIn("80.00 %", page)
        self.assertIn("N/A", page)

    def test_unique_column_and_footnote_switch(self):
        page = coverage_grading.render_pertest_index(self._rows(),
                                                     unique_computed=True)
        self.assertIn("20.00 %", page)  # beta: 2 unique of 10 active
        self.assertIn("delcov", page)
        page = coverage_grading.render_pertest_index(self._rows(),
                                                     unique_computed=False)
        self.assertNotIn("delcov", page)
        self.assertIn(str(coverage_grading.DELTA_MAX_TESTS), page)

    def test_html_links_and_escaping(self):
        rows = [coverage_grading.test_row("a&b", "x.ucdb",
                                          code_metrics(code=1.0), None)]
        page = coverage_grading.render_pertest_index(
            rows, html_reports={"a&b": ("a&b_code", None)})
        self.assertIn('href="a&amp;b_code/index.html"', page)
        self.assertIn("a&amp;b", page)
        # Only the code report was generated; no func link appears.
        self.assertNotIn("func</a>", page)

    def test_empty_batch_still_a_table(self):
        page = coverage_grading.render_pertest_index([])
        self.assertIn("No per-test databases in this batch.", page)

    def test_merged_line(self):
        merged = coverage_grading.test_row("(merged)", "m.ucdb",
                                           code_metrics(code=98.5),
                                           {"percent": 69.0})
        page = coverage_grading.render_pertest_index(self._rows(),
                                                     merged=merged)
        self.assertIn("98.50 %", page)
        self.assertIn("69.00 %", page)


class TestPertestSummaryJson(unittest.TestCase):
    def test_block_shape(self):
        row = coverage_grading.test_row("t", "t.ucdb",
                                        code_metrics(code=90.0),
                                        {"percent": 60.0})
        row["unique"] = {"code_percent": 1.5}
        block = coverage_grading.pertest_summary_json([row], True, False)
        self.assertEqual(block["test_count"], 1)
        self.assertTrue(block["unique_computed"])
        self.assertFalse(block["html_reports"])
        self.assertEqual(block["tests"]["t"],
                         {"code": 90.0, "functional": 60.0,
                          "unique_code": 1.5, "ucdb": "t.ucdb"})

    def test_empty_batch_not_generated(self):
        block = coverage_grading.pertest_summary_json([], False)
        self.assertFalse(block["generated"])
        self.assertEqual(block["test_count"], 0)


if __name__ == "__main__":
    unittest.main()
