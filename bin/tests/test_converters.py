# Copyright (c) 2026 Eclipse Foundation
# SPDX-License-Identifier: Apache-2.0 WITH SHL-2.1
"""Questa XML -> Cobertura / UCIS on a three-instance fixture.

Two reasons these tests exist:

1. ``bin/questa_xml_to_ucis_xml.py``'s own docstring says its output is validated
   with ``xmllint`` "in .github/workflows/coverage.yml" -- a job that needs a
   Questa licence and nobody had ever run the check. Everything here needs
   nothing but Python (and ``xmllint`` when it happens to be installed), so the
   schema promise is finally enforced by the hosted CI job.
2. The fixture has an uncovered statement on purpose. The bug these guard
   against was a converter that reported the exported subset as if it were the
   whole design and published a line rate of 1.0000.

The fixtures substitute __REPO__ with the repository root at run time because
Questa writes the compile host's absolute source paths, and the converters are
supposed to make them relative to *this* checkout."""

import base64
import contextlib
import hashlib
import io
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

BIN = Path(__file__).resolve().parents[1]
REPO = BIN.parent
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

import questa_xml_to_ucis_xml  # noqa: E402
from questa_xml_to_cobertura import generate_cobertura_xml, parse_detail  # noqa: E402
from questa_xml_to_ucis_xml import generate_ucis_xml  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SCHEMAS = REPO / "schemas"
HAS_XMLLINT = shutil.which("xmllint") is not None

# A code-coverage export of one design unit carrying two conditions: one built of
# two sub-expressions and one of a single sub-expression. Used by the test that
# pins which of the two a UCIS document may name. Note both conditions sit on the
# same line, which is what makes the inline count of the second one matter.
DOUBLE_TERM_CONDITION_EXPORT = """\
<coverage_report questa_version="2025.3">
 <code_coverage_report>
  <instanceData path="/tb/dut/alu_i" du="cve2_alu">
   <sourceTable files="1"><fileMap fn="0" path="%(tmp)s/x.sv"/></sourceTable>
   <stmt fn="0" ln="7" st="1" hits="1"/>
   <condition fn="0" ln="7" st="1" active="2" hits="0">
    <table rows="2" cols="0">
     <row j="1" body="(a == 0)"/><row j="2" body="(b == 0)"/>
    </table>
   </condition>
   <condition fn="0" ln="7" st="2" active="1" hits="1">
    <table rows="1" cols="0"><row j="1" body="(c == 0)"/></table>
   </condition>
  </instanceData>
 </code_coverage_report>
</coverage_report>
"""

# One instance whose every kind of coverage object also comes in a variant with no
# source line at all, which is what Questa writes when it cannot say where the item
# is. UCIS requires file+line of every object, so those variants have to be skipped
# rather than written at some line that never had any coverage.
UNLOCATED_EXPORT = """\
<coverage_report questa_version="2025.3">
 <code_coverage_report>
  <instanceData path="/tb/dut/alu_i" du="cve2_alu">
   <sourceTable files="1"><fileMap fn="0" path="%(tmp)s/x.sv"/></sourceTable>
   <stmt fn="0" ln="12" st="1" hits="1"/>
   <stmt fn="0" st="2" hits="1"/>
   <condition fn="0" st="1" active="1" hits="1">
    <table rows="1" cols="0"><row j="1" body="(a == 0)"/></table>
   </condition>
   <if><ielem fn="0" st="1" true="1" false="0"/></if>
  </instanceData>
 </code_coverage_report>
</coverage_report>
"""

# HISTORY_NODE's own run-metadata attributes (schemas/ucis.xsd): where a run was
# done, by whom, with what arguments, at what cost, standing for how many runs.
# `cmd` is the one the rollup does report, so it is the one exempted below. A merged
# .ucdb exports none of the rest for any of the runs it merged, and the converter's
# docstring says so rather than inventing one, so none of these may turn up anywhere
# in the document.
RUNTIME_ATTRIBUTES = frozenset(("simtime", "cpuTime", "timeunit", "seed", "runCwd",
                                "args", "userName", "cost", "sameTests"))

# Every source file the two detail exports name, so that a test can insist the
# paths the converters publish resolve against this checkout.
FIXTURE_SOURCES = (
    "core-v-cores/cv32e20/rtl/cve2_alu.sv",
    "env/uvme/cov/uvme_rv32isa_covg.sv",
    "env/uvme/cov/uvme_unsampled_covg.sv",
    "env/uvme/uvme_cv32e20_pkg.sv",
)


class FixtureCase(unittest.TestCase):
    """Copies the fixtures into a temporary tree, __REPO__ already resolved."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.fixtures = {}
        for name in ("questa_rollup.xml", "questa_detail.xml", "questa_cvg.xml"):
            text = (FIXTURES / name).read_text().replace("__REPO__", str(self.tmp))
            destination = self.tmp / name
            destination.write_text(text)
            self.fixtures[name] = destination
        # The detail exports name these source files; make the paths they use real
        # so the converters' repository-relative mapping has something to resolve.
        for name in FIXTURE_SOURCES:
            source = self.tmp / name
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text("// fixture\n")


class TestCobertura(FixtureCase):

    def generate(self, rollup=True):
        output = self.tmp / "cobertura.xml"
        ok = generate_cobertura_xml(
            self.fixtures["questa_detail.xml"], output,
            rollup_path=self.fixtures["questa_rollup.xml"] if rollup else None,
            scope="/uvmt_cv32e20_tb/dut_wrap/cv32e20_top_i/u_cve2_top/u_cve2_core",
            repo_root=self.tmp)
        self.assertTrue(ok)
        return output

    def test_uncovered_lines_survive(self):
        """The single most important property: 1 of the 3 statements is not
        covered, so the rate must be below 1.0 and the line must be listed."""
        root = ET.parse(str(self.generate(rollup=False))).getroot()
        self.assertLess(float(root.get("line-rate")), 1.0)
        lines = root.iter("line")
        hits = dict((int(line.get("number")), int(line.get("hits")))
                    for line in lines)
        self.assertIn(57, hits)
        self.assertEqual(hits[57], 0)
        self.assertGreater(hits[56], 0)
        self.assertEqual(int(root.get("lines-valid")), 4)
        self.assertEqual(int(root.get("lines-covered")), 2)

    def test_branches_are_not_hardcoded_zero(self):
        root = ET.parse(str(self.generate(rollup=False))).getroot()
        self.assertGreater(float(root.get("branch-rate")), 0.0)
        self.assertEqual(int(root.get("branches-valid")), 2)
        self.assertEqual(int(root.get("branches-covered")), 1)
        branching = [line for line in root.iter("line")
                     if line.get("branch") == "true"]
        self.assertTrue(branching)
        # A branch-carrying line must report its conditions, per the Cobertura DTD
        # usage this converter documents.
        self.assertIsNotNone(branching[0].find("conditions"))

    def test_file_names_are_relative_to_the_repository_root(self):
        """Questa wrote an absolute path under the compile host; a consumer
        resolving it against this checkout must land on the real file."""
        root = ET.parse(str(self.generate(rollup=False))).getroot()
        classes = list(root.iter("class"))
        self.assertEqual(len(classes), 1)
        filename = classes[0].get("filename")
        self.assertFalse(Path(filename).is_absolute())
        self.assertTrue((self.tmp / filename).is_file())

    def test_rollup_cross_check_accepts_a_consistent_export(self):
        """Detail-vs-rollup agreement is the guard against publishing only what
        Questa happened to export, so the check has to pass on these fixtures."""
        self.assertTrue(self.generate(rollup=True).is_file())

    def test_detail_item_counts_match_the_rollup(self):
        """The other direction: assert the fixture really is consistent, or the
        test above proves nothing."""
        _, totals = parse_detail(self.fixtures["questa_detail.xml"], self.tmp)
        self.assertEqual((totals["stmt_items"], totals["stmt_items_covered"]), (3, 2))
        self.assertEqual((totals["branch_items"], totals["branch_items_covered"]),
                         (2, 1))
        self.assertEqual((totals["cond_items"], totals["cond_items_covered"]),
                         (1, 1))

    @unittest.skipUnless(HAS_XMLLINT, "xmllint not installed")
    def test_cobertura_is_dtd_valid(self):
        output = self.generate()
        # The DOCTYPE points at Cobertura's historic URL; schemas/catalog.xml maps
        # it to the vendored copy so this works offline (--nonet).
        env = {"SGML_CATALOG_FILES": str(SCHEMAS), "PATH": "/usr/bin:/bin"}
        result = subprocess.run(
            ["xmllint", "--noout", "--nonet", "--catalogs", "--dtdvalid",
             str(SCHEMAS / "coverage-04.dtd"), str(output)],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.assertEqual(result.returncode, 0, result.stdout)


class TestUcis(FixtureCase):
    """The document a UCIS consumer -- PyUCIS, ``pyucis-viewer`` -- has to accept.

    The shape is not a style choice: it is what ``schemas/ucis.xsd`` (the schema
    those tools validate against, vendored here) declares, so these tests are what
    keeps the artifact openable. Several of them also pin what the converter may
    *not* say: Questa leaves gaps the schema has no room for, and filling one with
    an invented value is the failure mode these guard against."""

    def generate(self, detail=True, cvg_detail=True):
        output = self.tmp / "merged.ucis.xml"
        ok = generate_ucis_xml(
            self.fixtures["questa_rollup.xml"], output,
            detail_path=self.fixtures["questa_detail.xml"] if detail else None,
            cvg_detail_path=self.fixtures["questa_cvg.xml"] if cvg_detail else None,
            ucdb_name="merged.ucdb", repo_root=self.tmp)
        self.assertTrue(ok)
        return output

    def generate_capturing(self):
        """``generate()`` with the converter's own report returned too: what it
        chose to leave out is only visible there, and a gap it left silently is a
        gap nobody reading the run would ever learn about."""
        output = self.tmp / "captured.ucis.xml"
        report = io.StringIO()
        with contextlib.redirect_stdout(report):
            ok = generate_ucis_xml(
                self.fixtures["questa_rollup.xml"], output,
                detail_path=self.fixtures["questa_detail.xml"],
                cvg_detail_path=self.fixtures["questa_cvg.xml"],
                ucdb_name="merged.ucdb", repo_root=self.tmp)
        self.assertTrue(ok)
        return ET.parse(str(output)).getroot(), report.getvalue()

    def root(self, **kwargs):
        return ET.parse(str(self.generate(**kwargs))).getroot()

    def test_the_sections_are_the_ones_the_schema_declares_in_the_order_it_wants(
            self):
        """A reader that cannot validate the root element never gets as far as the
        coverage in it -- which is exactly how this artifact used to fail."""
        root = self.root()
        self.assertEqual(root.tag, "UCIS")
        for attribute in ("ucisVersion", "writtenBy", "writtenTime"):
            self.assertTrue(root.get(attribute), attribute)
        order = [element.tag for element in root]
        history_at = order.index("historyNodes")
        instance_at = order.index("instanceCoverages")
        self.assertTrue(all(tag == "sourceFiles" for tag in order[:history_at]))
        self.assertTrue(all(tag == "historyNodes"
                            for tag in order[history_at:instance_at]))
        self.assertTrue(all(tag == "instanceCoverages"
                            for tag in order[instance_at:]))
        for node in root.findall("historyNodes"):
            for attribute in ("historyNodeId", "logicalName", "testStatus", "date",
                              "toolCategory", "ucisVersion", "vendorId", "vendorTool",
                              "vendorToolVersion"):
                self.assertTrue(node.get(attribute), attribute)
            self.assertEqual(node.get("logicalName"), "merged")

    def test_the_history_node_is_an_honest_placeholder(self):
        """The schema makes a test status mandatory (HISTORY_NODE/@testStatus)
        while Questa's plain rollup names no test at all, so the one node says what
        a merge implies and the converter's docstring names
        ``sim/uvmt/regression_results.json`` as the authority instead. Nothing that
        would read as a measured per-test result -- a second status, a runtime, a
        seed, a user -- may appear anywhere in the document."""
        root = self.root()
        nodes = root.findall("historyNodes")
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0].get("kind"), "merged")
        self.assertEqual(nodes[0].get("logicalName"), "merged")
        # The one status is the merge's own: no coverage object below it may carry
        # a status a reader could take for a test's verdict.
        carriers = [element for element in root.iter()
                    if element.get("testStatus") is not None]
        self.assertEqual(carriers, nodes)
        timed = [element.tag for element in root.iter()
                 if set(element.keys()) & RUNTIME_ATTRIBUTES]
        self.assertEqual(timed, [])
        # `cmd` is the run attribute the rollup really does report, so it is the one
        # the guard above lets through: what Questa ran, recorded rather than made
        # up, and never a per-test command line.
        self.assertEqual(nodes[0].get("cmd"), "vcover report -xml")
        # A path is only ever the one the caller named: given --ucdb it is
        # recorded, and without it the document names no database at all rather
        # than a made-up one.
        self.assertEqual(nodes[0].get("physicalName"), "merged.ucdb")
        bare = self.tmp / "bare.ucis.xml"
        self.assertTrue(generate_ucis_xml(self.fixtures["questa_rollup.xml"], bare,
                                          detail_path=self.fixtures["questa_detail.xml"],
                                          repo_root=self.tmp))
        bare_node = ET.parse(str(bare)).getroot().find("historyNodes")
        self.assertEqual(bare_node.get("physicalName"), "")
        # And where the verdicts do live is written where a maintainer reads it.
        self.assertIn("regression_results.json", questa_xml_to_ucis_xml.__doc__)

    def test_no_aggregate_metric_is_invented(self):
        """The interchange format has no aggregate metric of any kind: its root
        element admits ``sourceFiles``, ``historyNodes`` and ``instanceCoverages``
        and nothing else, which is why PyUCIS's own ``get_toplevel_metric()`` has
        zero calls. So this document states hit counts and never a percentage --
        those are ``coverage_report/summary.json``'s and the Questa HTML report's
        to publish."""
        root = self.root()
        for element in root.iter():
            for name in element.keys():
                for needle in ("percent", "rate", "ratio"):
                    self.assertNotIn(needle, name.lower(),
                                     "%s=%r on <%s>" % (name, element.get(name),
                                                        element.tag))
        # What it does state is counts, and every one of them is a hit count.
        contents = root.findall(".//contents")
        self.assertTrue(contents)
        for element in contents:
            self.assertEqual(sorted(element.keys()), ["coverageCount"])
            self.assertGreaterEqual(int(element.get("coverageCount")), 0)

    def test_bins_and_their_counts_survive_in_both_directions(self):
        """The reason this converter reads the per-instance export instead of the
        type summaries: only the instances name the bins and their hit counts --
        and an uncovered bin has to stay uncovered."""
        root = self.root()
        counts = dict(((bin_element.get("name"), bin_element.get("type")),
                       int(bin_element.find("range/contents").get("coverageCount")))
                      for bin_element in root.iter("coverpointBin"))
        self.assertEqual(counts[("ADD", "bins")], 7)
        self.assertEqual(counts[("BRANCH", "bins")], 3)
        self.assertEqual(counts[("LS", "bins")], 0)
        self.assertEqual(counts[("CRITICAL", "bins")], 0)
        # Questa's <ignore_bins>/<illegal_bins> are bins of another kind, not bins
        # that were left out.
        self.assertEqual(counts[("RESERVED", "ignore")], 0)
        self.assertEqual(counts[("ILLEGAL_IRQ", "illegal")], 0)

    def test_covergroup_types_and_their_instances_are_distinguished(self):
        """UCIS names the instantiated covergroup on <cgInstance> and its type on
        <cgId>; a consumer builds the type coverage by merging the instances."""
        root = self.root()
        self.assertEqual(set(instance.get("name")
                             for instance in root.iter("cgInstance")),
                         {"rv32i_instr_cg", "rv32i_branch_cg", "env_irq_cg"})
        self.assertEqual(set(element.get("cgName") for element in root.iter("cgId")),
                         {"cg_instr", "cg_irq"})
        for element in root.iter("cgId"):
            self.assertTrue(element.get("moduleName"))
            for tag in ("cginstSourceId", "cgSourceId"):
                self.assertIsNotNone(element.find(tag), tag)

    def test_a_coverpoint_without_bins_is_not_written(self):
        """Questa exports coverpoints with no bins at all. The schema forbids a
        coverpoint without one and there is no count to report, so it is skipped."""
        root = self.root()
        written = set(point.get("name") for point in root.iter("coverpoint"))
        self.assertIn("cp_opcode", written)
        self.assertIn("cp_irq", written)
        self.assertNotIn("cp_rd", written)

    def test_a_cross_over_an_unwritten_coverpoint_is_dropped(self):
        """UCIS resolves a cross by the coverpoints beside it; a reference to a
        coverpoint the document does not carry stops PyUCIS's own reader."""
        root = self.root()
        self.assertEqual(set(cross.get("name") for cross in root.iter("cross")),
                         {"cx_op_rs1", "cx_instr_opcode", "cx_irq_source"})
        for cover_group in root.iter("cgInstance"):
            written = set(point.get("name")
                          for point in cover_group.findall("coverpoint"))
            for cross in cover_group.findall("cross"):
                expressions = [element.text for element in cross.findall("crossExpr")]
                self.assertTrue(expressions)
                for expression in expressions:
                    self.assertIn(expression, written)

    def test_a_scope_without_a_single_bin_is_absent(self):
        root = self.root()
        scopes = set(instance.get("name")
                     for instance in root.findall("instanceCoverages"))
        self.assertIn("/uvme_cv32e20_pkg", scopes)
        self.assertNotIn("/uvme_unsampled_pkg", scopes)

    def test_code_coverage_is_located_where_questa_said_it_is(self):
        """Every object UCIS writes names a file and a line, including the
        statements nobody hit."""
        root = self.root()
        statements = root.findall(".//blockCoverage/statement")
        self.assertEqual(len(statements), 3)
        self.assertEqual(
            dict((int(statement.find("id").get("line")),
                  int(statement.find("bin/contents").get("coverageCount")))
                 for statement in statements),
            {56: 5, 57: 0, 138: 9})
        # One <ielem> is a line with a taken and a not-taken arm, and UCIS keeps
        # both even though neither was hit.
        branch_statements = root.findall(".//branchCoverage/statement")
        self.assertEqual([statement.get("statementType")
                          for statement in branch_statements], ["if", "if"])
        self.assertEqual(len(root.findall(".//branchCoverage/statement/branch")), 4)
        for branch in root.findall(".//branchCoverage/statement/branch"):
            self.assertIsNotNone(branch.find("id"))
            self.assertIsNotNone(branch.find("branchBin/contents"))
        counts = sorted(int(branch.find("branchBin/contents").get("coverageCount"))
                        for branch in branch_statements[0].findall("branch"))
        self.assertEqual(counts, [3, 4])

    def test_a_condition_is_written_only_when_its_expression_is_known(self):
        """Questa names the whole condition nowhere; a one-sub-expression condition
        states it, and a longer one would have to be invented."""
        detail = self.tmp / "multi_term_detail.xml"
        detail.write_text(DOUBLE_TERM_CONDITION_EXPORT % {"tmp": self.tmp})
        output = self.tmp / "multi_term.ucis.xml"
        report = io.StringIO()
        with contextlib.redirect_stdout(report):
            self.assertTrue(generate_ucis_xml(self.fixtures["questa_rollup.xml"], output,
                                              detail_path=detail, repo_root=self.tmp))
        expressions = ET.parse(str(output)).getroot().findall(".//expr")
        self.assertEqual(len(expressions), 1)
        self.assertEqual(expressions[0].get("exprString"), "(c == 0)")
        self.assertEqual(expressions[0].find("subExpr").text, "(c == 0)")
        self.assertEqual(expressions[0].find("bin/contents").get("coverageCount"), "1")
        # And said so: the run that drops half the conditions has to show it.
        self.assertIn("skipped 1 conditions not made of one sub-expression",
                      report.getvalue())

    def test_an_object_without_a_source_line_is_dropped_not_relocated(self):
        """Questa leaves `ln` off an item it cannot place. The schema demands a
        positive line of every object, and satisfying it with line 1 -- or with the
        first statement of the instance -- would put coverage where none was taken."""
        detail = self.tmp / "unlocated_detail.xml"
        detail.write_text(UNLOCATED_EXPORT % {"tmp": self.tmp})
        output = self.tmp / "unlocated.ucis.xml"
        report = io.StringIO()
        with contextlib.redirect_stdout(report):
            self.assertTrue(generate_ucis_xml(self.fixtures["questa_rollup.xml"],
                                              output, detail_path=detail,
                                              repo_root=self.tmp))
        root = ET.parse(str(output)).getroot()
        # Nothing that has to be located may be in the document without a location,
        # and nothing may have been parked on a line the export never named.
        for element in root.iter():
            if element.tag in ("statement", "expr", "branch", "instanceCoverages"):
                self.assertIsNotNone(element.find("id"), element.tag)
                self.assertNotEqual(element.find("id").get("line"), "1",
                                    "coverage relocated to line 1")
        self.assertEqual([element.find("id").get("line")
                          for element in root.findall(".//blockCoverage/statement")],
                         ["12"])
        self.assertFalse(root.findall(".//conditionCoverage"))
        self.assertFalse(root.findall(".//branchCoverage"))
        for reason in ("statements with no source location",
                       "conditions with no source location",
                       "branch arms with no source location"):
            self.assertIn("skipped 1 " + reason, report.getvalue())

    def test_a_cross_bin_is_indexed_by_the_bins_its_name_names(self):
        """UCIS identifies a cross bin by the index, within each crossed coverpoint,
        of the bin it combines. Questa never writes that index, but it does name
        those bins (``<LS,R0>``), so the index may only come from the coverpoint the
        cross crosses and nowhere else.

        The fixture is built so that this can be told apart from an index taken from
        the cross bin's own ordinal: its first cross bin is ``<LS,R0>``, whose bins
        are the *second* of cp_opcode and the *first* of cp_rs1, and whose own
        ordinal is 1. An ordinal index, a reversed tuple, or an index of one
        everywhere all fail here."""
        root = self.root()
        checked = 0
        for cover_group in root.iter("cgInstance"):
            keys = dict((point.get("name"),
                         dict((bin_element.get("name"), bin_element.get("key"))
                              for bin_element in point.findall("coverpointBin")))
                        for point in cover_group.findall("coverpoint"))
            for cross in cover_group.findall("cross"):
                expressions = [element.text
                               for element in cross.findall("crossExpr")]
                for bin_element in cross.findall("crossBin"):
                    combination = bin_element.get("name").strip("<>").split(",")
                    self.assertEqual([child.text
                                      for child in bin_element.findall("index")],
                                     [keys[expression][part] for expression, part
                                      in zip(expressions, combination)])
                    # <index> elements before <contents>, as CROSS_BIN declares.
                    self.assertEqual([child.tag for child in bin_element],
                                     ["index"] * len(expressions) + ["contents"])
                    checked += 1
        for cross in root.iter("cross"):
            if cross.get("name") != "cx_op_rs1":
                continue
            vectors = dict((bin_element.get("name"),
                            [child.text for child in bin_element.findall("index")])
                           for bin_element in cross.findall("crossBin"))
            self.assertEqual(sorted(vectors), ["<ADD,R1>", "<LS,R0>"])
            self.assertEqual(vectors["<LS,R0>"], ["2", "1"])
            self.assertEqual(vectors["<ADD,R1>"], ["1", "2"])
            break
        else:
            self.fail("the fixture wrote no two-coverpoint cross")
        self.assertEqual(checked, 5)

    def test_a_cross_bin_naming_no_combination_is_not_given_an_index(self):
        """Three kinds of cross bin count something without naming one
        combination -- a bin of the testbench's own naming, the ``*`` bin for
        "anything else", and an ignore bin whose <bin_rhs> is a whole list of
        combinations and whose count is not even a hit -- and none of them may be
        parked on an index they were never taken at."""
        root, report = self.generate_capturing()
        counts = dict((element.get("name"),
                       element.find("contents").get("coverageCount"))
                      for element in root.iter("crossBin"))
        self.assertEqual(counts, {"<LS,R0>": "2", "<ADD,R1>": "5", "<ADD>": "2",
                                  "<LS>": "0", "<MEIC>": "5"})
        self.assertIn("skipped 1 cross bins whose combination Questa does not name",
                      report)
        self.assertIn("skipped 2 cross bins over a bin Questa does not carry", report)
        self.assertIn("skipped 1 cross bins Questa marked ignored or illegal", report)
        # What was written is in the report next to what was left out.
        self.assertIn("5 cross bins", report)

    def test_a_truncated_covergroup_export_narrows_the_document(self):
        """bin/run_tests.py only warns when a `vcover report` step fails, so an
        export can reach here half written; that must cost the reader one coverage
        kind, not the whole --cov-report step."""
        truncated = self.tmp / "truncated_cvg.xml"
        text = self.fixtures["questa_cvg.xml"].read_text()
        truncated.write_text(text[:len(text) // 2])
        output = self.tmp / "truncated.ucis.xml"
        self.assertTrue(generate_ucis_xml(self.fixtures["questa_rollup.xml"], output,
                                          detail_path=self.fixtures["questa_detail.xml"],
                                          cvg_detail_path=truncated, repo_root=self.tmp))
        root = ET.parse(str(output)).getroot()
        self.assertTrue(root.findall(".//blockCoverage"))
        self.assertFalse(root.findall(".//cgInstance"))

    def test_a_truncated_code_export_narrows_the_document(self):
        """The mirror of the covergroup case, and the reason both are pinned: the
        converter reads the two detail exports independently, so a half-written
        per-line export costs the document its code coverage and must leave the
        covergroups beside it standing (a `try:` around the whole load loop, or an
        `except: pass` around one file, fails one of the two)."""
        truncated = self.tmp / "truncated_code.xml"
        text = self.fixtures["questa_detail.xml"].read_text()
        truncated.write_text(text[:len(text) // 2])
        output = self.tmp / "truncated_code.ucis.xml"
        self.assertTrue(generate_ucis_xml(self.fixtures["questa_rollup.xml"], output,
                                          detail_path=truncated,
                                          cvg_detail_path=self.fixtures["questa_cvg.xml"],
                                          repo_root=self.tmp))
        root = ET.parse(str(output)).getroot()
        self.assertTrue(root.findall(".//cgInstance"))
        self.assertFalse(root.findall(".//blockCoverage"))

    def test_a_truncated_rollup_export_refuses_the_whole_document(self):
        """Without the rollup there is no provenance for the database, and an
        unreadable one is a hard error rather than a narrowed report."""
        truncated = self.tmp / "truncated_rollup.xml"
        text = self.fixtures["questa_rollup.xml"].read_text()
        truncated.write_text(text[:len(text) // 2])
        output = self.tmp / "truncated_rollup.ucis.xml"
        self.assertFalse(generate_ucis_xml(truncated, output,
                                           detail_path=self.fixtures["questa_detail.xml"],
                                           repo_root=self.tmp))
        self.assertFalse(output.is_file())

    def test_every_source_reference_names_a_declared_file(self):
        """UCIS resolves coverage objects through the file table, so a dangling id
        or a path outside the checkout is a broken artifact, not a loose end."""
        root = self.root()
        declared = dict((element.get("id"), element.get("fileName"))
                        for element in root.findall("sourceFiles"))
        self.assertEqual(set(declared),
                         set(str(number) for number in range(1, len(declared) + 1)))
        for element in root.iter():
            if element.get("file") is not None:
                self.assertIn(element.get("file"), declared)
        for name in declared.values():
            self.assertFalse(Path(name).is_absolute(), name)
            self.assertTrue((self.tmp / name).is_file(), name)

    def test_a_database_with_no_coverage_is_not_published(self):
        """The schema requires at least one instance, so writing one with nothing
        in it would publish a file its consumers reject."""
        output = self.tmp / "empty.ucis.xml"
        self.assertFalse(generate_ucis_xml(self.fixtures["questa_rollup.xml"], output,
                                           repo_root=self.tmp))
        self.assertFalse(output.is_file())

    def test_the_detail_exports_are_optional(self):
        """A report of one coverage kind is still a valid report: a missing export
        narrows the document instead of breaking it."""
        for kwargs in ({"cvg_detail": False}, {"detail": False}):
            root = self.root(**kwargs)
            self.assertEqual(root.tag, "UCIS")
            self.assertTrue(root.findall("instanceCoverages"))

    def test_the_vendored_schema_is_the_one_its_recorded_digest_names(self):
        """``schemas/ucis.xsd`` cannot carry a provenance comment of its own -- it is
        vendored byte-for-byte -- so the only record in the repository of which
        schema it is is the sha256 the converter's docstring quotes. Hash the file
        against that quoted number, or "byte-for-byte" is a promise nothing checks:
        an edit that "just relaxes one minOccurs" would leave every check below
        validating against a schema no consumer of this document uses."""
        recorded = re.search(r"byte-for-byte \(sha256\s+(\S+),",
                             questa_xml_to_ucis_xml.__doc__)
        self.assertIsNotNone(recorded,
                             "the docstring no longer records the schema's sha256")
        digest = base64.urlsafe_b64encode(hashlib.sha256(
            (SCHEMAS / "ucis.xsd").read_bytes()).digest()).decode().rstrip("=")
        self.assertEqual(digest, recorded.group(1))

    @unittest.skipUnless(HAS_XMLLINT, "xmllint not installed")
    def test_ucis_validates_against_the_ucis_schema(self):
        """The check bin/questa_xml_to_ucis_xml.py's docstring promises, against
        the schema its consumers validate with."""
        output = self.generate()
        result = subprocess.run(
            ["xmllint", "--noout", "--nonet", "--schema",
             str(SCHEMAS / "ucis.xsd"), str(output)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.assertEqual(result.returncode, 0, result.stdout)


if __name__ == "__main__":
    unittest.main()
