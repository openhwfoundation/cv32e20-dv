# Copyright (c) 2026 Eclipse Foundation
# SPDX-License-Identifier: Apache-2.0 WITH SHL-2.1
"""The line-to-tests matrix: -details XML parsing and HTML rendering.

What this pins (the parser was drafted against an imagined vocabulary and
then measured against the real export):

1. **The element names are the real ones.** Questa's -details export uses
   singular objects <stmt>, <ielem>, <celem>, <condition>, <state>, <trans>
   and <asrt>, and plural per-instance rollups that carry the same numbers
   and must NOT be parsed as objects. fixtures/questa_details.xml is that
   shape, element for element, including the fn="N" fileMap indirection.
2. **Covered has a per-element meaning.** An <ielem> arm is hit through
   either outcome (true + false > 0), an <asrt> through passcount > 0, and
   everything else through hits > 0. A parser that reads only hits= would
   silently drop every covered if-arm.
3. **Attribution is never guessed.** <state>/<trans> carry no fn: they
   resolve through a single-file sourceTable and land in "unattributed"
   when the instance spans several files.
4. **The pages render what the merge says.** Index totals come from the
   merged map when present (union otherwise), missing source files are
   reported, never invented, and lines only the merge holds get their
   labelled entry rather than a silent green.
"""

import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

BIN = Path(__file__).resolve().parents[1]
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

import coverage_matrix  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
DETAILS_XML = FIXTURES / "questa_details.xml"


class TestParseDetailXml(unittest.TestCase):
    """fixtures/questa_details.xml: one covered and one uncovered object
    per category, plus the two attribution edge cases."""

    @classmethod
    def setUpClass(cls):
        # Parse the fixture as XML first: an unparseable fixture is what
        # once made a converter fail three layers away from the cause.
        ET.parse(str(DETAILS_XML))
        cls.parsed = coverage_matrix.parse_detail_xml(DETAILS_XML)

    def test_objects_are_the_covered_ones_only(self):
        want = {
            ("cve2_controller.sv", 100): {"S": 1},
            ("cve2_controller.sv", 101): {"S": 1},
            ("cve2_controller.sv", 514): {"B": 1},
            ("cve2_controller.sv", 300): {"B": 1},
            ("cve2_controller.sv", 60): {"C": 1},
            ("cve2_controller.sv", 381): {"FS": 1},
            ("cve2_controller.sv", 387): {"FT": 1},
            ("cve2_controller.sv", 272): {"FE": 1},
            ("cve2_alu.sv", 45): {"S": 1},
            ("added_package.sv", 12): {"S": 1},
        }
        self.assertEqual(self.parsed["objects"], want)

    def test_uncovered_objects_absent_by_category(self):
        # Line 100 holds two statements, one hit: the cell counts the
        # covered one, not the line.
        self.assertEqual(self.parsed["objects"][("cve2_controller.sv", 100)],
                         {"S": 1})
        # The uncovered branch arm (ielem true=0 false=0), case arm
        # (celem hits=0), condition (hits=0), state, transition and the
        # passcount=0 assertion contribute nothing anywhere.
        for key in (("cve2_controller.sv", 61),
                    ("cve2_controller.sv", 382),
                    ("cve2_controller.sv", 388),
                    ("cve2_controller.sv", 873)):
            self.assertNotIn(key, self.parsed["objects"])

    def test_if_arm_covered_through_either_outcome(self):
        # ielem st=1: true=12 false=5 => covered; an implementation that
        # read only hits= (absent here) would report no B object at all.
        self.assertIn(("cve2_controller.sv", 514), self.parsed["objects"])

    def test_rollups_are_not_objects(self):
        # The fixture's plural rollups (statements active=4,
        # assertion_successes active=2, ...) carry deliberately
        # contradictory numbers: were they parsed as objects, the exact
        # objects dict above could not hold.
        self.assertEqual(self.parsed["by_file"]["cve2_controller.sv"],
                         {"S": 2, "B": 2, "C": 1, "FS": 1, "FT": 1,
                          "FE": 1})

    def test_state_without_file_resolves_or_is_unattributed(self):
        # The controller instance has one file, so its <state>/<trans>
        # attributed above; the alu instance spans two files, so its
        # fn-less state is unattributed, never guessed onto a line.
        self.assertEqual(self.parsed["unattributed"]["FS"], 1)
        self.assertEqual(self.parsed["unattributed"]["S"], 0)
        self.assertEqual(self.parsed["unattributed"]["FE"], 0)

    def test_by_file_totals(self):
        self.assertEqual(self.parsed["by_file"]["cve2_alu.sv"]["S"], 1)
        self.assertEqual(
            self.parsed["by_file"]["added_package.sv"],
            {"S": 1, "B": 0, "C": 0, "FS": 0, "FT": 0, "FE": 0})


class TestMergeTestMaps(unittest.TestCase):
    def test_two_tests_share_a_cell_and_stay_apart_otherwise(self):
        t1 = coverage_matrix.parse_detail_xml(DETAILS_XML)
        t2 = {"objects": {("cve2_alu.sv", 45): {"S": 1},
                          ("cve2_controller.sv", 999): {"S": 1}},
              "unattributed": {}, "by_file": {}}
        merged = coverage_matrix.merge_test_maps({"t1": t1, "t2": t2})
        shared = merged["cve2_alu.sv"][45]["S"]
        self.assertEqual(shared, {"t1", "t2"})
        self.assertEqual(merged["cve2_controller.sv"][514]["S"], set())
        self.assertEqual(merged["cve2_controller.sv"][514]["B"], {"t1"})
        self.assertEqual(merged["cve2_controller.sv"][999]["S"], {"t2"})


class TestRenderMatrix(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.sources = self.root / "rtl"
        self.sources.mkdir()
        (self.sources / "cve2_controller.sv").write_text(
            "module cve2_controller;\n"
            "  if (commit_to_irq) begin\n"
            "  end\n"
            "endmodule\n")
        # cve2_alu.sv deliberately absent: reported, never invented.
        self.out = self.root / "matrix"
        self.parsed = coverage_matrix.parse_detail_xml(DETAILS_XML)

    def tearDown(self):
        self.tmp.cleanup()

    def _render(self, merged_map=None):
        return coverage_matrix.render_matrix(
            {"hello_test": self.parsed}, merged_map, self.sources, self.out)

    def test_renders_index_and_page_and_reports_missing_sources(self):
        summary = self._render()
        self.assertEqual(summary["files"], 1)
        self.assertIn("cve2_alu.sv", summary["missing_sources"])
        self.assertIn("added_package.sv", summary["missing_sources"])
        index = (self.out / "index.html").read_text()
        self.assertIn("cve2_controller.sv.html", index)
        self.assertIn("cve2_alu.sv", index)  # named in the note

    def test_pages_badge_covered_lines_and_label_merge_only_ones(self):
        # Badges render on source lines that exist in the scanned file,
        # so this map uses the four lines of the fake source.
        small = {"objects": {("cve2_controller.sv", 2): {"S": 1, "B": 1},
                             ("cve2_controller.sv", 3): {"FE": 1}},
                 "unattributed": {}, "by_file": {}}
        coverage_matrix.render_matrix({"hello_test": small}, None,
                                      self.sources, self.out)
        page = (self.out / "cve2_controller.sv.html").read_text()
        self.assertIn("hello_test", page)
        self.assertIn("commit_to_irq", page)  # verbatim source line
        # A line no individual test covers but the merge holds shows as
        # the merge-only entry, not as green.
        merged = {"objects": {("cve2_controller.sv", 4): {"S": 3}},
                  "by_file": {}, "unattributed": {}}
        coverage_matrix.render_matrix({"hello_test": small}, merged,
                                      self.sources, self.out)
        page = (self.out / "cve2_controller.sv.html").read_text()
        self.assertIn("(full merge)", page)

    def test_index_totals_prefer_the_merged_map(self):
        union = self.parsed["by_file"]["cve2_controller.sv"]["S"]  # 2
        merged = {"objects": {}, "unattributed": {},
                  "by_file": {"cve2_controller.sv": {
                      "S": 10, "B": 0, "C": 0, "FS": 0, "FT": 0, "FE": 0}}}
        self._render(merged_map=merged)
        index = (self.out / "index.html").read_text()
        self.assertIn(f"{union} / 10", index)
        self._render()  # no merged map: union over tests
        index = (self.out / "index.html").read_text()
        self.assertIn(f"{union} / {union}", index)

    def test_html_escapes_test_names(self):
        parsed = {"objects": {("cve2_controller.sv", 1): {"S": 1}},
                  "unattributed": {}, "by_file": {}}
        coverage_matrix.render_matrix(
            {"a<b & c>": parsed}, None, self.sources, self.out)
        page = (self.out / "cve2_controller.sv.html").read_text()
        self.assertIn("a&lt;b &amp; c&gt;", page)
        self.assertNotIn("<b> c", page)


if __name__ == "__main__":
    unittest.main()
