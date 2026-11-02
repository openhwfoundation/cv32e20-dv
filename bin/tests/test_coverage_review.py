# Copyright (c) 2026 Eclipse Foundation
# SPDX-License-Identifier: Apache-2.0 WITH SHL-2.1
"""The coverage review toolchain: cov.tcl parser, triage rules, sheet format.

Four things are pinned here, and all four have already been wrong once:

1. **The parser reads cov.tcl as it is actually written.** Gates, shared comment
   variables and the four commented-out "To review" exclusions are what the
   audit reports on, so a parser that quietly drops one of them produces a
   review sheet that is complete-looking and wrong.
2. **The triage rules are the reviewable artifact.** docs/coverage/README.md
   says the sheet is derived, never typed; that only holds if the rules that
   derive it have tests.
3. **An assertion exclusion must not carry a -du.** Measured against the live
   merged.ucdb, ``coverage exclude -du <unit> -assertpath <path>`` silently
   matches nothing while the bare ``-assertpath <path>`` works, and Questa
   reports no error either way -- the same silent no-op the audit exists to
   catch, in the tool that writes proposed waivers.
4. **A published cov.tcl cite has to outlive the next cov.tcl edit.** The three
   dumps under docs/coverage/ quote line numbers out of cov.tcl; TestPublishedCites
   reads the file back and checks each one still names its own waiver.

Nothing here needs a simulator: the cov.tcl parser, the hole-report parser and
the sheet writer are all pure functions over fixtures, which is what keeps
.github/workflows/python-ci.yml Questa-free.
"""

import csv
import sys
import tempfile
import unittest
from pathlib import Path

BIN = Path(__file__).resolve().parents[1]
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

import coverage_review  # noqa: E402
from coverage_holes import parse_holes_report  # noqa: E402
from coverage_waiver_audit import Exclusion, gate_is_active, parse_cov_tcl  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
REPO = BIN.parent
COV_TCL = REPO / "sim" / "tools" / "vsim" / "cov.tcl"
DOCS = REPO / "docs" / "coverage"


def published_rows(path):
    """A published dump's rows, without the `#` comment lines it is fronted (and
    sometimes punctuated) with."""
    lines = [line for line in path.read_text(encoding="utf-8-sig").splitlines()
             if line.strip() and not line.startswith("#")]
    return list(csv.DictReader(lines))


class TestParseCovTcl(unittest.TestCase):
    """bin/tests/fixtures/cov_tcl_mini.tcl, one statement per metric."""

    @classmethod
    def setUpClass(cls):
        cls.exclusions, cls.variables, cls.gates = parse_cov_tcl(
            FIXTURES / "cov_tcl_mini.tcl")
        cls.by_metric = {}
        for excl in cls.exclusions:
            cls.by_metric.setdefault(excl.metric, []).append(excl)

    def test_every_statement_is_found_including_the_commented_out_one(self):
        self.assertEqual(len(self.exclusions), 9)
        disabled = [e for e in self.exclusions if not e.enabled]
        self.assertEqual(len(disabled), 1)
        self.assertEqual(disabled[0].targets, "100")
        self.assertIn("To review", disabled[0].comment)

    def test_metrics_are_mapped_from_the_flags_not_from_the_comment(self):
        self.assertEqual(self.by_metric["statement"][0].targets, "258 266 268")
        self.assertEqual(self.by_metric["branch"][0].targets, "514")
        self.assertEqual(self.by_metric["condition"][0].targets, "312")
        self.assertEqual(self.by_metric["fsm-trans"][0].targets,
                         "ctrl_fsm_cs DECODE->RESET")
        self.assertEqual(self.by_metric["fsm-state"][0].targets,
                         "fetch_fsm_cs WAIT")
        self.assertEqual(self.by_metric["fec"][0].targets, "feccondrow 501 row4")
        self.assertEqual(len(self.by_metric["assertion"]), 1)

    def test_comment_variables_are_resolved(self):
        self.assertEqual(self.by_metric["condition"][0].comment,
                         "One shared justification for the exclusions below")
        self.assertEqual(self.by_metric["condition"][0].comment_var, "comment")
        self.assertEqual(self.by_metric["fsm-state"][0].comment_var, "comment")

    def test_gate_of_a_block_is_recorded_and_gates_are_per_their_value(self):
        gated = [e for e in self.exclusions if e.gate == "BusErrSupported"]
        self.assertEqual(len(gated), 1)
        self.assertEqual(len([e for e in self.exclusions if not e.gate]), 8)
        # cov.tcl gates are `if {!$VAR}`, so the block runs when the variable is 0.
        self.assertTrue(gate_is_active("BusErrSupported", {"BusErrSupported": "0"}))
        self.assertFalse(gate_is_active("BusErrSupported", {"BusErrSupported": "1"}))
        self.assertTrue(gate_is_active("", {}))

    def test_whole_design_unit_exclusion_names_itself_as_such(self):
        """A `-du x` with nothing else excludes the unit, and the sheet has to
        say so rather than leave the Target column blank."""
        self.assertEqual(self.by_metric["assertion"][0].label(),
                         "/tb/dut/ctrl_i/CVE2NoDoubleSpecialReqPCSet")
        bare = Exclusion(lineno=1, du="cve2_tracer", metric="du", targets="",
                         comment="", gate="", enabled=True, args="-du cve2_tracer")
        self.assertEqual(bare.label(), "(whole design unit)")


class TestHoleExclusion(unittest.TestCase):
    """The paste-ready exclusion the sheet proposes for an open hole."""

    def test_assertion_exclusion_is_a_bare_assertpath(self):
        row = {"Design Unit": "cve2_controller", "Metric": "assertion",
               "Target": "/tb/dut/ctrl_i/CVE2NoDoubleSpecialReqPCSet", "Line": ""}
        self.assertEqual(
            coverage_review.hole_exclusion(row),
            "coverage exclude -assertpath /tb/dut/ctrl_i/CVE2NoDoubleSpecialReqPCSet "
            "-comment {reviewed in docs/coverage/coverage_review.csv}")
        # A -du here is the silent-no-op form; guard against adding it back.
        self.assertNotIn("-du", coverage_review.hole_exclusion(row))

    def test_code_holes_use_line_and_metric_letter(self):
        for metric, flag in (("stmt", "s"), ("branch", "b"),
                             ("condition", "c"), ("fsm", "f")):
            row = {"Design Unit": "cve2_alu", "Metric": metric,
                   "Target": "", "Line": "42"}
            self.assertEqual(
                coverage_review.hole_exclusion(row),
                "coverage exclude -du cve2_alu -linerange 42 -code %s "
                "-comment {reviewed in docs/coverage/coverage_review.csv}" % flag)

    def test_a_hole_this_tool_cannot_name_proposes_nothing(self):
        """A half-built Tcl line is worse than none: a reviewer pastes it."""
        for row in ({"Design Unit": "x", "Metric": "toggle", "Line": "7",
                     "Target": ""},
                    {"Design Unit": "x", "Metric": "stmt", "Line": "",
                     "Target": ""}):
            self.assertEqual(coverage_review.hole_exclusion(row), "")


class TestWaiverExclusion(unittest.TestCase):
    def test_round_trips_the_parsed_statement(self):
        exclusions, _vars, _gates = parse_cov_tcl(FIXTURES / "cov_tcl_mini.tcl")
        excl = next(e for e in exclusions if e.metric == "branch")
        line = coverage_review.waiver_exclusion({"Waiver Comment": ""}, excl)
        self.assertTrue(line.startswith("coverage exclude "))
        self.assertIn("-linerange 514 -code b", line)
        self.assertIn("Branch excluded: interrupt withdrawn in IRQ_TAKEN", line)

    def test_a_row_without_its_source_line_falls_back_to_nothing(self):
        self.assertEqual(
            coverage_review.waiver_exclusion({"Waiver Comment": "Because"}, None),
            "")


class TestTriageRules(unittest.TestCase):
    """The rules docs/coverage/coverage_review.md documents, in code."""

    def waiver(self, **over):
        row = {"Waiver Comment": "Statement excluded: dead by construction",
               "Config Gate": "none", "Waiver Status": "VALID"}
        row.update(over)
        return row

    def test_reset_injection_is_a_stimulus_gap_not_dead_code(self):
        got = coverage_review.triage_waiver(self.waiver(
            **{"Waiver Comment": "accepted untested-stimulus gap "
                                 "(mid-run reset injection)"}))
        self.assertEqual(got, ("B-new-test", "reset-injection",
                               "mid_run_reset_test", "triaged"))

    def test_config_gate_wins_over_the_comment(self):
        got = coverage_review.triage_waiver(self.waiver(
            **{"Config Gate": "BusErrSupported=0"}))
        self.assertEqual(got, ("C-waive", "config-disabled", "", "waived"))

    def test_not_instrumented_is_documentation_not_a_bug(self):
        got = coverage_review.triage_waiver(self.waiver(
            **{"Waiver Status": coverage_review.NOT_INSTRUMENTED,
               "Waiver Comment": "Some unit outside the scope"}))
        self.assertEqual(got, ("C-waive", "sim-only", "", "triaged"))

    def test_sim_only_markers(self):
        got = coverage_review.triage_waiver(self.waiver(
            **{"Waiver Comment": "RVFI trace plumbing"}))
        self.assertEqual(got, ("C-waive", "sim-only", "", "waived"))

    def test_default_is_what_the_comment_argues_dead_code(self):
        got = coverage_review.triage_waiver(self.waiver())
        self.assertEqual(got, ("C-waive", "dead-code", "", "waived"))

    def test_every_gate_name_is_stripped_of_its_value(self):
        self.assertEqual(coverage_review.gate_name("UmodeEnabled=0"),
                         "UmodeEnabled")
        self.assertEqual(coverage_review.gate_name(""), "none")
        self.assertEqual(coverage_review.gate_name(None), "none")

    def test_triaged_hole_and_untriaged_hole(self):
        triaged = coverage_review.triage_hole(
            {"Design Unit": "cve2_controller", "Metric": "branch",
             "Line": "514", "Target": "All False Count (else arm)"})
        self.assertEqual(triaged["classification"], "B-new-test")
        self.assertEqual(triaged["test"], "irq_withdraw_test")
        self.assertEqual(triaged["status"], "triaged")
        # An assertion is keyed by its own name, not by a line number.
        by_name = coverage_review.triage_hole(
            {"Design Unit": "cve2_id_stage", "Metric": "assertion", "Line": "",
             "Target": "/tb/dut/id_i/IbexStallIfValidInstrNotExecuting"})
        self.assertEqual(by_name["classification"], "C-waive")
        # Anything else stays open: the tool admits it has not thought about it.
        unknown = coverage_review.triage_hole(
            {"Design Unit": "cve2_alu", "Metric": "stmt", "Line": "9",
             "Target": ""})
        self.assertEqual(unknown["status"], "open")
        self.assertEqual(unknown["classification"], "")


class TestSheet(unittest.TestCase):
    """build_rows/write_sheet: the format Excel and Google Sheets are given."""

    def build(self):
        waivers = [{
            "ID": "W001", "Design Unit": "cve2_controller", "Metric": "branch",
            "Target": "514", "Source Line": "cov.tcl:12", "Delta Hits": "3",
            "Delta Misses": "1", "Config Gate": "none", "Waiver Status": "VALID",
            "Waiver Comment": "Branch, with, commas",
        }]
        holes = [{"Design Unit": "cve2_controller", "Metric": "branch",
                  "Line": "514", "Target": "All False Count (else arm)",
                  "Hits": "0", "Misses": "1", "Instance": "/tb/dut",
                  "File": "rtl/cve2_controller.sv", "Source": "All False Count"}]
        return coverage_review.build_rows(waivers, holes)

    def test_rows_are_keyed_and_ordered(self):
        rows = self.build()
        self.assertEqual([r["ID"] for r in rows], ["W001", "H001"])
        self.assertEqual([r["Type"] for r in rows], ["WAIVER", "HOLE"])
        # A waiver's counts are what lifting it brings back, and a waiver that
        # hides covered code cannot make them negative.
        self.assertEqual(rows[0]["Hits"], 3)
        self.assertEqual(rows[0]["Coverage %"], "75.00")
        self.assertEqual(rows[1]["Target"], "All False Count (else arm)")
        self.assertEqual(rows[1]["Waiver Status"], "")

    def test_written_sheet_is_excel_safe(self):
        rows = self.build()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sheet.csv"
            self.assertEqual(coverage_review.write_sheet(path, rows), 2)
            raw = path.read_bytes()
            self.assertTrue(raw.startswith(b"\xef\xbb\xbf"), "no UTF-8 BOM")
            text = raw.decode("utf-8-sig")
            self.assertNotIn("\n\n", text, "blank line in the sheet")
            self.assertEqual(text.count("\n"), text.count("\r\n"),
                             "a bare LF line ending")
            parsed = list(csv.reader(text.splitlines()))
            self.assertEqual(len(parsed[0]), len(coverage_review.COLUMNS))
            for row in parsed[1:]:
                self.assertEqual(len(row), len(coverage_review.COLUMNS))
                # ID, Type, Design Unit and Metric are the filter columns.
                for name, value in zip(parsed[0], row):
                    if name in ("ID", "Type", "Design Unit", "Metric"):
                        self.assertTrue(value.strip(), "empty %s" % name)

    def test_main_writes_a_sheet_from_two_dumps(self):
        """The whole tool over fixture input, the way the make target runs it:
        two raw dumps in, one sheet out, in the dumps' own order."""
        waiver_columns = ["ID", "Design Unit", "Metric", "Target",
                          "Source Line", "Delta Hits", "Delta Misses",
                          "Config Gate", "Waiver Status", "Waiver Comment"]
        hole_columns = ["Design Unit", "Instance", "File", "Line", "Metric",
                        "Target", "Hits", "Misses", "Source"]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "coverage_review.csv"
            waivers = Path(tmp) / "waiver_audit.csv"
            holes = Path(tmp) / "holes.csv"
            with open(waivers, "w", newline="", encoding="utf-8-sig") as fh:
                writer = csv.DictWriter(fh, fieldnames=waiver_columns,
                                        lineterminator="\r\n")
                writer.writeheader()
                writer.writerow(dict(zip(waiver_columns, [
                    "W001", "cve2_tracer", "du", "", "cov.tcl:4", "0", "0",
                    "none", coverage_review.NOT_INSTRUMENTED,
                    "Simulation-only design unit"])))
            with open(holes, "w", newline="", encoding="utf-8-sig") as fh:
                fh.write("# source: fixture\r\n")
                writer = csv.DictWriter(fh, fieldnames=hole_columns,
                                        lineterminator="\r\n")
                writer.writeheader()
                writer.writerow({"Design Unit": "cve2_controller",
                                 "Instance": "/tb/dut/ctrl_i",
                                 "File": "rtl/cve2_controller.sv",
                                 "Line": "514", "Metric": "branch",
                                 "Target": "All False Count (else arm)",
                                 "Hits": "0", "Misses": "1",
                                 "Source": "All False Count"})
            rc = coverage_review.main([
                "--waivers", str(waivers), "--holes", str(holes),
                "--cov-tcl", str(FIXTURES / "cov_tcl_mini.tcl"),
                "--out", str(out)])
            self.assertEqual(rc, 0)
            rows = list(csv.DictReader(out.read_text(encoding="utf-8-sig")
                                       .splitlines()))
            self.assertEqual([r["ID"] for r in rows], ["W001", "H001"])
            self.assertEqual(rows[0]["Classification"], "C-waive")
            self.assertEqual(rows[0]["Rationale Category"], "sim-only")
            self.assertEqual(rows[0]["Status"], "triaged")
            # The one triaged hole this tool knows by heart.
            self.assertEqual(rows[1]["Classification"], "B-new-test")
            self.assertEqual(rows[1]["Proposed Test"], "irq_withdraw_test")


class TestPublishedCites(unittest.TestCase):
    """check_published_cites, and the dumps this repository publishes.

    Three artifacts quote line numbers of cov.tcl and all three take them from
    the file's own text -- which is edited for a living, and a comment inserted
    anywhere moves every cite below it. That silently invalidated the published
    dumps on 2026-11-01: 43 of 64 rows pointed one line off their own exclusion,
    and it stayed invisible because the numbers still looked plausible. The
    checker therefore ships as `bin/coverage_review.py --check-cites`, proved
    below on a fixture, and only then run against whatever the tree has
    published.
    """

    COV_TCL_TEXT = ("coverage exclude -du cve2_alu -linerange 42 -code b "
                    "-comment {one}\n"
                    "coverage exclude -du cve2_controller -ftrans ctrl_fsm_cs "
                    "{DECODE->RESET} -comment {two}\n"
                    "# a note between statements\n"
                    "#coverage exclude -du cve2_controller -linerange 42 -code b "
                    "-comment {deleted but still here}\n")

    def check(self, cited_line):
        """The fixture, checked: a three-line cov.tcl and one dump that quotes
        whichever line of it the test is interested in."""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "cov.tcl").write_text(self.COV_TCL_TEXT, encoding="utf-8")
            (root / "raw").mkdir()
            with open(root / "raw" / "waiver_audit.csv", "w", newline="",
                      encoding="utf-8-sig") as handle:
                writer = csv.writer(handle, lineterminator="\r\n")
                writer.writerow(["ID", "Design Unit", "Metric", "Target",
                                 "Source Line"])
                writer.writerow(["W001", "cve2_controller", "fsm-trans",
                                 "ctrl_fsm_cs DECODE->RESET",
                                 "cov.tcl:%d" % cited_line])
            return coverage_review.check_published_cites(
                root / "cov.tcl", root,
                (("raw/waiver_audit.csv", "Source Line"),))

    def test_a_cite_that_names_its_own_waiver_is_no_problem(self):
        problems, checked = self.check(2)
        self.assertEqual(checked, 1)
        self.assertEqual(problems, [])

    def test_a_waiver_moved_one_line_in_cov_tcl_is_caught(self):
        """The failure this exists for: cov.tcl gained a line above the
        statement, so the published number lands on the neighbour's waiver --
        still a valid `coverage exclude` line, which is exactly why nobody
        notices."""
        problems, checked = self.check(1)
        self.assertEqual(checked, 1)
        # Both words of the target and the design unit are missing from the line
        # the cite now lands on, and each is reported -- a checker that stopped
        # naming the design unit would still pass a one-problem assertion.
        self.assertEqual(len(problems), 3, problems)
        self.assertTrue(any("does not name 'DECODE->RESET'" in problem
                            for problem in problems), problems)
        self.assertTrue(any("does not name cve2_controller" in problem
                            for problem in problems), problems)
        self.assertTrue(all("W001" in problem for problem in problems), problems)

    def test_a_cite_on_a_plain_comment_is_caught(self):
        problems, checked = self.check(3)
        self.assertEqual(checked, 1)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("not a coverage exclude statement", problems[0])

    def test_a_cite_on_a_commented_out_exclusion_is_caught(self):
        """The other drift a re-aim leaves behind: cov.tcl commented the
        statement out, and the parser still reports it, so only a check that
        reads the line itself notices the waiver no longer exists."""
        problems, checked = self.check(4)
        self.assertEqual(checked, 1)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("commented-out exclusion", problems[0])

    def test_a_cite_past_the_end_of_cov_tcl_is_caught(self):
        problems, checked = self.check(99)
        self.assertEqual(checked, 1)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("not a coverage exclude statement", problems[0])

    def test_the_dumps_this_tree_publishes_resolve_their_own_cites(self):
        if not COV_TCL.is_file():
            self.skipTest("no cov.tcl in this tree")
        published = [(DOCS / name, column)
                     for name, column in coverage_review.PUBLISHED_CITES
                     if (DOCS / name).is_file()]
        if not published:
            self.skipTest("this tree has not published the dumps")
        # Counted from the dumps, not written down: retiring a waiver retires
        # its cites, and a literal floor would make that correct day look like
        # a broken check. What is pinned is that every citable row was looked at
        # and none of them points at the wrong statement.
        expected = sum(
            1 for path, column in published
            for row in published_rows(path)
            if (row.get(column) or "").strip().rsplit(":", 1)[-1].isdigit())
        self.assertGreater(expected, 0, "no dump has a readable cite column")
        problems, checked = coverage_review.check_published_cites(COV_TCL, DOCS)
        self.assertEqual(problems, [])
        self.assertEqual(checked, expected)

    def test_the_two_dumps_quote_the_same_line_for_the_same_waiver(self):
        """The sheet copies its cite out of the audit dump; when they disagree,
        one of them was regenerated after the cov.tcl edit and the other
        was not."""
        audit = DOCS / "raw" / "waiver_audit.csv"
        sheet = DOCS / "coverage_review.csv"
        if not (audit.is_file() and sheet.is_file()):
            self.skipTest("both dumps are needed to compare their cites")
        by_id = {(row.get("ID") or ""): (row.get("Source Line") or "").strip()
                 for row in published_rows(audit)}
        compared = 0
        for row in published_rows(sheet):
            cited = (row.get("cov.tcl Line") or "").strip()
            if cited and row.get("ID") in by_id:
                compared += 1
                self.assertEqual(by_id[row["ID"]], cited,
                                 "%s cites cov.tcl differently in the two dumps"
                                 % row["ID"])
        self.assertGreater(compared, 0, "no shared waiver row to compare")


class TestHolesReportParser(unittest.TestCase):
    """bin/tests/fixtures/questa_holes_report.txt: the text report Questa's
    `coverage report -details -annotate -below 100` writes, which is the hole
    source that sees both the annotated misses and the exclusions applied in a
    -viewcov session."""

    @classmethod
    def setUpClass(cls):
        cls.holes, cls.rollups = parse_holes_report(
            (FIXTURES / "questa_holes_report.txt").read_text())

    def test_statement_hole_carries_its_line_and_shortened_file(self):
        stmts = [h for h in self.holes if h.metric == "stmt"]
        self.assertEqual(len(stmts), 1)
        self.assertEqual(stmts[0].line, "258")
        self.assertEqual(stmts[0].du, "cve2_controller")
        self.assertEqual(stmts[0].file, "rtl/cve2_controller.sv")

    def test_all_false_count_inherits_the_if_line(self):
        """The else arm carries no line number of its own; dropping it is the
        difference between 22 and 23 branch holes."""
        branches = [h for h in self.holes if h.metric == "branch"]
        self.assertEqual(len(branches), 1)
        self.assertEqual(branches[0].line, "514")
        self.assertEqual(branches[0].target, "All False Count (else arm)")

    def test_condition_hole_is_per_uncovered_input_term(self):
        conds = [h for h in self.holes if h.metric == "condition"]
        self.assertEqual(len(conds), 1)
        self.assertIn("feccondrow 312", conds[0].target)
        self.assertIn("handle_irq", conds[0].target)

    def test_never_attempted_assertion_is_a_hole(self):
        asserts = [h for h in self.holes if h.metric == "assertion"]
        self.assertEqual(len(asserts), 1)
        self.assertTrue(asserts[0].target.endswith("CVE2NoDoubleSpecialReqPCSet"))
        self.assertEqual(asserts[0].file, "")

    def test_rollups_are_summed_per_metric_row_name(self):
        self.assertEqual(self.rollups["statements"], (10, 9, 1))
        self.assertEqual(self.rollups["branches"], (4, 3, 1))


if __name__ == "__main__":
    unittest.main()
