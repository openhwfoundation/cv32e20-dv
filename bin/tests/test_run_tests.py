# Copyright (c) 2026 Eclipse Foundation
# SPDX-License-Identifier: Apache-2.0 WITH SHL-2.1
"""Tests for the parts of bin/run_tests.py that decide what runs and what passed.

The simulator-facing half of the script is verified by running it (see
docs/regression.md); what is verified here is the bookkeeping around it, because
every one of these functions can silently turn a failing regression into a
passing one -- a banner that stops matching, a testlist key that is ignored, a
seed that is reported wrong."""

import contextlib
import io
import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

BIN = Path(__file__).resolve().parents[1]
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

import regression_report  # noqa: E402
import run_tests  # noqa: E402


class TestClassify(unittest.TestCase):
    """The verdict contract: the testbench prints, this parses.

    These banner strings are the whole interface to tb/uvmt/uvmt_cv32e20_tb.sv
    and tb/core/tb_top.sv, so a rename on either side has to fail something."""

    def test_uvmt_banners(self):
        cfg = run_tests.TESTBENCHES["uvmt"]
        self.assertEqual(run_tests.classify("** SIMULATION PASSED **", cfg), "PASS")
        # "... with WARNINGS" is still a pass, and is what the uvmt TB prints for
        # every test currently in regress/*.yaml.
        self.assertEqual(run_tests.classify("SIMULATION PASSED with WARNINGS", cfg),
                         "PASS")
        self.assertEqual(run_tests.classify("SIMULATION FAILED", cfg), "FAIL")
        self.assertEqual(run_tests.classify("compile error", cfg), "ERROR")

    def test_core_banners(self):
        cfg = run_tests.TESTBENCHES["core"]
        self.assertEqual(run_tests.classify("ALL TESTS PASSED", cfg), "PASS")
        self.assertEqual(run_tests.classify("TEST(S) FAILED!", cfg), "FAIL")
        self.assertEqual(run_tests.classify("nothing yet", cfg), "ERROR")

    def test_a_uvmt_pass_is_not_a_core_pass(self):
        """The two testbenches print different banners; one pattern matching both
        would report a core run that never printed anything as passed."""
        self.assertEqual(run_tests.classify("SIMULATION PASSED",
                                            run_tests.TESTBENCHES["core"]), "ERROR")


class TestSeeds(unittest.TestCase):

    def test_seed_arg_accepts_random_and_the_bounds(self):
        self.assertEqual(run_tests.seed_arg("random"), "random")
        self.assertEqual(run_tests.seed_arg("1"), 1)
        self.assertEqual(run_tests.seed_arg(str(run_tests.MAX_SEED)),
                         run_tests.MAX_SEED)

    def test_seed_arg_rejects_zero_and_junk(self):
        # 0 in particular: Verilator reads +verilator+seed+0 as "pick your own",
        # so a result directory named 0 would not identify the seed used.
        for bad in ("0", "-1", str(run_tests.MAX_SEED + 1), "abc", ""):
            with self.assertRaises(Exception, msg=f"{bad!r} was accepted"):
                run_tests.seed_arg(bad)

    def test_resolve_seed(self):
        self.assertEqual(run_tests.resolve_seed(7), 7)
        for _ in range(20):
            self.assertLessEqual(run_tests.resolve_seed("random"),
                                 run_tests.MAX_SEED)
            self.assertGreaterEqual(run_tests.resolve_seed("random"), 1)

    def test_extract_seed_both_formats(self):
        self.assertEqual(run_tests.extract_seed("vsim -sv_seed 354410829 -c"),
                         "354410829")
        self.assertEqual(run_tests.extract_seed("Simulation running with seed: 12"),
                         "12")
        self.assertIsNone(run_tests.extract_seed("no seed here"))


class TestCorevDvDetection(unittest.TestCase):
    """corev-dv membership comes from the tree, not from a fourth hard-coded list."""

    def test_generated_test_is_detected(self):
        self.assertTrue(run_tests.is_corev_dv("corev_rand_instr_test"))

    def test_directed_test_is_not_generated(self):
        self.assertFalse(run_tests.is_corev_dv("hello-world"))

    def test_every_curated_name_is_detected(self):
        """The curated list has to keep meaning "needs gen_corev-dv": a name
        added to COREV_DV_TESTS without a corev-dv.yaml still gets its
        generation step (is_corev_dv() consults both), and one whose
        corev-dv.yaml was renamed is still not skipped by accident."""
        for name in run_tests.COREV_DV_TESTS:
            self.assertTrue(run_tests.is_corev_dv(name), name)

    def test_tree_alone_is_enough(self):
        """A generation test that is in the tree but not in the curated list is
        still generated -- which is what lets a testlist name one without
        editing Python. Proved against a fake tree, because today the tree and
        COREV_DV_TESTS happen to hold the same 15 names."""
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "corev-dv" / "corev_rand_brand_new").mkdir(parents=True)
        (tmp / "corev-dv" / "corev_rand_brand_new" / "corev-dv.yaml").write_text("")
        original = run_tests.TESTS_PROGRAM_ROOT
        run_tests.TESTS_PROGRAM_ROOT = tmp
        self.addCleanup(setattr, run_tests, "TESTS_PROGRAM_ROOT", original)

        self.assertNotIn("corev_rand_brand_new", run_tests.COREV_DV_TESTS)
        self.assertTrue(run_tests.is_corev_dv("corev_rand_brand_new"))
        # A directory alone is not a generated test; corev-dv.yaml is the marker.
        (tmp / "corev-dv" / "plain_dir").mkdir()
        self.assertFalse(run_tests.is_corev_dv("plain_dir"))


class TestLoadTestlist(unittest.TestCase):
    """--testlist parsing, and above all its rejections."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def load(self, text):
        path = self.tmp / "list.yaml"
        path.write_text(text)
        return run_tests.load_testlist(path)

    def test_missing_file_is_an_error(self):
        with self.assertRaises(SystemExit):
            run_tests.load_testlist(self.tmp / "nope.yaml")

    def test_minimal_form(self):
        meta, entries = self.load("name: t\n"
                                  "tests:\n"
                                  "  - name: hello-world\n")
        self.assertEqual(meta["name"], "t")
        self.assertEqual([entry["name"] for entry in entries], ["hello-world"])

    def test_order_is_the_file_order(self):
        _, entries = self.load("name: t\n"
                               "tests:\n"
                               "  - name: misalign\n"
                               "  - name: hello-world\n")
        self.assertEqual([entry["name"] for entry in entries],
                         ["misalign", "hello-world"])

    def test_unknown_top_level_key_is_an_error(self):
        with self.assertRaises(SystemExit) as ctx:
            self.load("name: t\n"
                      "tests:\n"
                      "  - name: hello-world\n"
                      "color: blue\n")
        self.assertIn("color", str(ctx.exception))

    def test_unknown_test_key_is_an_error(self):
        """The old cv_regress 'num:' key in particular: accepting and ignoring it
        would report one run where the author asked for two."""
        with self.assertRaises(SystemExit) as ctx:
            self.load("name: t\n"
                      "tests:\n"
                      "  - name: hello-world\n"
                      "    num: 2\n")
        self.assertIn("num", str(ctx.exception))

    def test_name_and_tests_are_required(self):
        for text in ("description: d\ntests:\n  - name: hello-world\n",
                     "name: t\ndescription: d\n",
                     "name: t\ntests: []\n"):
            with self.assertRaises(SystemExit, msg=text):
                self.load(text)

    def test_entry_without_a_name_is_an_error(self):
        with self.assertRaises(SystemExit):
            self.load("name: t\ntests:\n  - description: nameless\n")

    def test_duplicate_test_is_an_error(self):
        with self.assertRaises(SystemExit) as ctx:
            self.load("name: t\n"
                      "tests:\n"
                      "  - name: hello-world\n"
                      "  - name: hello-world\n")
        self.assertIn("twice", str(ctx.exception))

    def test_unknown_test_name_is_an_error(self):
        """A name with no test-program directory must fail at load time, not
        two hours into a regression as an ERROR row."""
        with self.assertRaises(SystemExit) as ctx:
            self.load("name: t\ntests:\n  - name: no_such_test_program\n")
        self.assertIn("no_such_test_program", str(ctx.exception))

    def test_entries_carry_description_and_make_args(self):
        _, entries = self.load("name: t\n"
                               "tests:\n"
                               "  - name: hello-world\n"
                               "    description: boot\n"
                               "    make_args: [FOO=1]\n")
        self.assertEqual(entries[0]["description"], "boot")
        self.assertEqual(entries[0]["make_args"], ["FOO=1"])
        _, entries = self.load("name: t\ntests:\n  - name: hello-world\n")
        self.assertIsNone(entries[0]["description"])
        self.assertEqual(entries[0]["make_args"], [])

    def test_meta_path_is_repo_relative_when_it_can_be(self):
        """The published dashboard names the testlist that produced a run; a
        build-machine absolute path in it would be noise. A testlist outside the
        checkout has no relative form, and keeps its absolute path rather than a
        '../..' walk nobody can resolve."""
        repo_list = (Path(__file__).resolve().parents[2] / "regress"
                     / "cv32e20_sanity.yaml")
        if not repo_list.is_file():
            self.skipTest("cv32e20_sanity.yaml not next to this checkout")
        meta, _ = run_tests.load_testlist(repo_list)
        self.assertEqual(meta["path"], "regress/cv32e20_sanity.yaml")

        meta, _ = self.load("name: t\ntests:\n  - name: hello-world\n")
        self.assertTrue(Path(meta["path"]).is_absolute())
        self.assertTrue(meta["path"].endswith("list.yaml"))


class TestRegressionDocument(unittest.TestCase):

    def test_rows_become_entries(self):
        rows = [("hello-world", "PASS", "", None, "1", 42.7),
                ("misalign", "FAIL", "mismatch", None, "3", 12.0),
                ("corev_rand_instr_test", "ERROR", "no verdict banner",
                 "99", "7", None)]
        doc = run_tests.regression_document(
            "uvmt", "default", rows, testlist="regress/x.yaml",
            descriptions={"hello-world": "Boot and signal pass"})
        self.assertEqual(doc["summary"]["total"], 3)
        self.assertEqual(doc["summary"]["passed"], 1)
        self.assertEqual(doc["summary"]["failed"], 1)
        self.assertEqual(doc["summary"]["error"], 1)

        by_name = dict((test["name"], test) for test in doc["tests"])
        self.assertEqual(by_name["hello-world"]["description"],
                         "Boot and signal pass")
        self.assertEqual(by_name["corev_rand_instr_test"]["gen_seed"], "99")
        self.assertIsNone(by_name["corev_rand_instr_test"]["duration_s"])
        self.assertEqual(by_name["misalign"]["detail"], "mismatch")

    def test_log_paths_are_repo_relative_and_existence_is_recorded(self):
        doc = run_tests.regression_document(
            "uvmt", "default", [("hello-world", "PASS", "", None, "1", 1.0)])
        test = doc["tests"][0]
        self.assertFalse(Path(test["log"]).is_absolute())
        self.assertTrue(test["log"].startswith(
            "sim/uvmt/vsim_results/default/hello-world/0/"))
        self.assertIn(test["log_exists"], (True, False))

    def test_parked_rows_are_flagged(self):
        """The published regression document holds every row the batch ran,
        with the parked ones flagged, so the dashboard can badge them and
        still render the default verdict from the unflagged rows."""
        parked_name = run_tests.PARKED[0]
        doc = run_tests.regression_document(
            "uvmt", "default",
            [("hello-world", "PASS", "", None, "1", 1.0),
             (parked_name, "FAIL", "vacuous", None, "2", 2.0)])
        by_name = dict((test["name"], test) for test in doc["tests"])
        self.assertFalse(by_name["hello-world"]["parked"])
        self.assertTrue(by_name[parked_name]["parked"])
        self.assertEqual(doc["summary"]["total"], 2)
        self.assertEqual(doc["summary"]["parked"], 1)
        self.assertEqual(doc["summary"]["parked_passed"], 0)

    def test_core_log_paths_name_the_seed_that_ran(self):
        doc = run_tests.regression_document(
            "core", "default", [("fibonacci", "PASS", "", None, "12345", 1.0)])
        self.assertIn("/fibonacci/12345/", doc["tests"][0]["log"])

    def test_the_wall_window_is_reported_only_when_it_was_measured(self):
        """A batch that ran tests knows how long it took; a batch that only read
        old logs back does not, and must not be published with a 0 s window."""
        doc = run_tests.regression_document(
            "uvmt", "default", [("hello-world", "PASS", "", None, "1", 42.7)],
            started="2026-10-30T21:38:00+00:00",
            finished="2026-10-30T21:39:30+00:00")
        self.assertEqual(doc["summary"]["start"], "2026-10-30T21:38:00+00:00")
        self.assertEqual(doc["summary"]["duration_s"], 90.0)
        doc = run_tests.regression_document(
            "uvmt", "default", [("hello-world", "PASS", "", None, "1", None)])
        self.assertIsNone(doc["summary"]["start"])
        self.assertIsNone(doc["summary"]["end"])
        self.assertIsNone(doc["summary"]["duration_s"])


class TestMainPublishesResults(unittest.TestCase):
    """A batch that publishes nothing is just a print statement.

    Every path that could reach the checkout or a simulator is redirected at a
    throwaway tree: the testbench's sim directory (so there are no logs to read)
    and REPO/TESTS_PROGRAM_ROOT (so the published report and the test-program
    existence checks use the temporary tree). --parse-only is what makes this
    need no simulator at all: the selected test reports ERROR "no log file",
    which is exactly the row a machine with nothing built produces -- and a
    failing batch is still expected to publish, because that is the batch
    somebody needs the dashboard for."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.sim_dir = self.tmp / "sim" / "uvmt"
        self.sim_dir.mkdir(parents=True)
        # uvmt everywhere: --cov/--cov-report and corev-dv are uvmt-only, and
        # its results are not keyed by seed, so --parse-only yields one row.
        for name, value in (("REPO", self.tmp),
                            ("TESTS_PROGRAM_ROOT", self.tmp / "tests" / "programs")):
            original = getattr(run_tests, name)
            setattr(run_tests, name, value)
            self.addCleanup(setattr, run_tests, name, original)
        original = run_tests.TESTBENCHES["uvmt"]["sim_dir"]
        run_tests.TESTBENCHES["uvmt"]["sim_dir"] = self.sim_dir
        self.addCleanup(run_tests.TESTBENCHES["uvmt"].__setitem__,
                        "sim_dir", original)
        # publish_logs() resolves the log paths of a document against its own
        # idea of the repository, so without this a log that happens to still be
        # on disk in the real checkout would be published into this test's
        # temporary output.
        original = regression_report.REPO_ROOT
        regression_report.REPO_ROOT = self.tmp
        self.addCleanup(setattr, regression_report, "REPO_ROOT", original)

    def run_main(self, argv):
        """main() ends in sys.exit(); return that code, discarding its output."""
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as exited:
                run_tests.main(argv)
        return exited.exception.code

    def published(self):
        root = self.tmp / "coverage_report" / "regression"
        document = json.loads((root / regression_report.DOCUMENT_NAME).read_text())
        return root, document

    def test_a_batch_publishes_the_document_and_the_dashboard(self):
        code = self.run_main(["--tb", "uvmt", "--parse-only",
                              "--allow-failures", "hello-world"])
        self.assertEqual(code, 0)
        root, document = self.published()
        self.assertEqual(document["testlist"], None)
        self.assertEqual(document["summary"]["total"], 1)
        self.assertEqual(document["summary"]["error"], 1)
        self.assertEqual(document["tests"][0]["name"], "hello-world")
        self.assertEqual(document["tests"][0]["verdict"], "ERROR")
        # Nothing was timed, so the dashboard must show N/A rather than 0s.
        self.assertIsNone(document["tests"][0]["duration_s"])
        self.assertIsNone(document["tests"][0]["published_log"])
        # ... nor for the run as a whole: the seconds between two timestamps of a
        # batch that launched no simulation are not its wall time.
        self.assertIsNone(document["summary"]["start"])
        self.assertIsNone(document["summary"]["end"])
        self.assertIsNone(document["summary"]["duration_s"])
        # The page that fetch()es the JSON goes out next to it.
        self.assertTrue((root / "index.html").is_file())
        # ... and a copy of the document sits beside the logs it describes.
        self.assertTrue((self.sim_dir / regression_report.DOCUMENT_NAME).is_file())

    def test_a_failing_batch_still_publishes_and_still_gates(self):
        """Without --allow-failures the same run exits non-zero -- publishing is
        reporting and must not soften the exit code in either direction."""
        code = self.run_main(["--tb", "uvmt", "--parse-only", "hello-world"])
        self.assertEqual(code, 1)
        _root, document = self.published()
        self.assertEqual(document["summary"]["error"], 1)

    def test_a_measured_batch_publishes_its_wall_window(self):
        """The other half of the null rule: a batch that ran tests keeps its
        window, or a regression could quietly lose its Wall Time card and every
        test would still be green. run_test() is patched out because what is
        under test here is the publishing, not the simulation; the 4-tuple is
        the verdict/detail/gen_seed/run_seed shape run_one() unpacks."""
        calls = []

        def fake_run_test(*args, **kwargs):
            calls.append(args[1] if len(args) > 1 else kwargs.get("test"))
            return ("PASS", "", None, "1")

        original = run_tests.run_test
        run_tests.run_test = fake_run_test
        self.addCleanup(setattr, run_tests, "run_test", original)

        code = self.run_main(["--tb", "uvmt", "hello-world"])
        self.assertEqual(code, 0)
        self.assertEqual(calls, ["hello-world"])
        _root, document = self.published()
        test = document["tests"][0]
        self.assertEqual(test["verdict"], "PASS")
        self.assertIsNotNone(test["duration_s"])
        self.assertIsNotNone(document["summary"]["start"])
        self.assertIsNotNone(document["summary"]["end"])
        # now() is second-resolution, so a patched-out test really can measure
        # zero seconds; what is asserted is that the window is *there*.
        self.assertGreaterEqual(document["summary"]["duration_s"], 0)

    def test_the_testlist_reaches_the_document(self):
        """The dashboard names the list a run came from; that is the difference
        between "a regression" and "cv32e20_sanity on this commit"."""
        (run_tests.TESTS_PROGRAM_ROOT / "custom" / "hello-world").mkdir(parents=True)
        listing = self.tmp / "list.yaml"
        listing.write_text("name: tmp_list\ndescription: throwaway\ntb: uvmt\n"
                           "tests:\n  - name: hello-world\n"
                           "    description: boot\n")
        code = self.run_main(["--testlist", str(listing), "--parse-only",
                              "--allow-failures"])
        self.assertEqual(code, 0)
        _root, document = self.published()
        # The file supplies tb, so nothing on the command line had to say so.
        self.assertEqual(document["tb"], "uvmt")
        # Named relative to the checkout, as load_testlist() records it.
        self.assertEqual(document["testlist"], "list.yaml")
        self.assertEqual(document["tests"][0]["description"], "boot")


class TestPublishCoverageAnalysis(unittest.TestCase):
    """The one-way mirror of the committed analysis into the published tree.

    The sheet and its raw dumps are committed under docs/coverage/ because they
    are input to a review, and mirrored into coverage_report/analysis/ because
    that is where the published page goes looking for them. What is pinned here
    is both halves of that deal: the layout the page fetch()es, and the fact that
    an analysis nobody has generated yet is a warning naming the tool that would
    regenerate it rather than a report worth losing. REPO is redirected at a
    throwaway tree holding a fake templates/ directory, so none of this touches
    the checkout, and none of it needs Questa or a database.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.source = self.tmp / "docs" / "coverage"
        self.dest = self.tmp / "coverage_report"
        # The page and the shared stylesheet come out of templates/, so a tree
        # without them is one of the cases asserted below, not a fixture bug.
        for name in ("templates/analysis_dashboard/index.html",
                     "templates/analysis_dashboard/style.css",
                     "templates/common/style.css"):
            template = self.tmp / name
            template.parent.mkdir(parents=True, exist_ok=True)
            template.write_text(f"/* {name} */\n")
        original = run_tests.REPO
        run_tests.REPO = self.tmp
        self.addCleanup(setattr, run_tests, "REPO", original)

    def given(self, names):
        """One fake dump per name, all with the same content, under source_root."""
        for name in names:
            source = self.source / name
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text("ID,a,b\r\nH001,1,2\r\n")

    def publish(self):
        """Mirror the fake tree, returning (destination, what it printed)."""
        with contextlib.redirect_stdout(io.StringIO()) as out:
            analysis = run_tests.publish_coverage_analysis(self.dest, self.source)
        return analysis, out.getvalue()

    def test_the_mirror_lays_out_what_the_page_fetches(self):
        self.given(run_tests.COVERAGE_ANALYSIS_FILES)
        analysis, _out = self.publish()
        self.assertEqual(analysis, self.dest / "analysis")
        for name in run_tests.COVERAGE_ANALYSIS_FILES:
            # Byte-for-byte: the raw dumps are UTF-8 BOM + CRLF and the page that
            # reads them strips both itself, so a mirror that re-writes them
            # would be a second, subtly different copy of a committed file.
            self.assertEqual((analysis / name).read_bytes(),
                             (self.source / name).read_bytes())
        # The page that reads them, and the two stylesheets it links, sit beside
        # the CSVs so every path it uses is relative to analysis/.
        for name in ("index.html", "style.css", "common.css"):
            self.assertTrue((analysis / name).is_file(), name)

    def test_one_missing_dump_publishes_the_rest_and_says_which(self):
        missing = "raw/holes.csv"
        self.given([n for n in run_tests.COVERAGE_ANALYSIS_FILES if n != missing])
        analysis, out = self.publish()
        self.assertIn(missing, out)
        # Each dump names the tool that measured it: holes.csv is a
        # coverage_holes.py export, and only the sheet is coverage_review.py's
        # own output.
        self.assertIn("coverage_holes.py", out)
        self.assertFalse((analysis / missing).exists())
        for name in run_tests.COVERAGE_ANALYSIS_FILES:
            if name != missing:
                self.assertTrue((analysis / name).is_file(), name)

    def test_a_set_with_no_raw_dumps_leaves_no_empty_raw_directory(self):
        """The raw/ subtree is created per file, not up front: a report of an
        analysis that was never audited must not look like it was."""
        self.given(["coverage_review.csv"])
        analysis, _out = self.publish()
        self.assertTrue((analysis / "coverage_review.csv").is_file())
        self.assertFalse((analysis / "raw").exists())

    def test_missing_page_templates_keep_the_data(self):
        """A downloadable sheet is still worth publishing without the viewer."""
        self.given(run_tests.COVERAGE_ANALYSIS_FILES)
        shutil.rmtree(self.tmp / "templates" / "analysis_dashboard")
        analysis, out = self.publish()
        self.assertIn("analysis page templates not found", out)
        for name in run_tests.COVERAGE_ANALYSIS_FILES:
            self.assertTrue((analysis / name).is_file(), name)
        self.assertFalse((analysis / "index.html").exists())
        self.assertFalse((analysis / "common.css").exists())


class TestBatchUcdbLists(unittest.TestCase):
    """The split that feeds the two batch-scoped merges.

    Only PASSing tests with a .ucdb that exists on disk are merge inputs, and
    a parked test never lands in the default list: those two rules are what
    keep a parked failure out of the default view and a leftover directory out
    of both."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.sim_dir = self.tmp / "sim" / "uvmt"
        self.sim_dir.mkdir(parents=True)
        original = run_tests.TESTBENCHES["uvmt"]["sim_dir"]
        run_tests.TESTBENCHES["uvmt"]["sim_dir"] = self.sim_dir
        self.addCleanup(run_tests.TESTBENCHES["uvmt"].__setitem__,
                        "sim_dir", original)

    def touch_ucdb(self, test):
        ucdb = run_tests.test_ucdb_path("uvmt", test, 0, "default")
        ucdb.parent.mkdir(parents=True, exist_ok=True)
        ucdb.write_text("fake ucdb")
        return ucdb

    def test_split_and_exclusions(self):
        parked_a, parked_b = run_tests.PARKED[0], run_tests.PARKED[1]
        hello = self.touch_ucdb("hello-world")
        misalign = self.touch_ucdb("misalign")
        pa = self.touch_ucdb(parked_a)
        self.touch_ucdb(parked_b)  # parked but FAILED below
        gone = str(run_tests.test_ucdb_path("uvmt", "no_such_run", 0, "default"))
        results = [
            ("hello-world", "PASS", "", None, "1", 1.0),
            ("misalign", "PASS", "", None, "2", 1.0),
            (parked_a, "PASS", "", None, "3", 1.0),
            (parked_b, "FAIL", "vacuous", None, "4", 1.0),
            ("time_out_test", "ERROR", "timeout", None, "5", 1.0),
            ("no_such_run", "PASS", "", None, "6", 1.0),  # .ucdb missing
        ]
        default_paths, parked_paths = run_tests.batch_ucdb_lists(
            results, "uvmt", "default")
        self.assertEqual(default_paths, sorted([str(hello), str(misalign)]))
        self.assertEqual(parked_paths, [str(pa)])
        self.assertNotIn(gone, default_paths + parked_paths)

    def test_write_ucdb_list(self):
        path = self.tmp / "deep" / "ucdb.request"
        run_tests.write_ucdb_list(path, ["/abs/a.ucdb", "/abs/b.ucdb"])
        self.assertEqual(path.read_text(), "/abs/a.ucdb\n/abs/b.ucdb\n")
        run_tests.write_ucdb_list(path, [])
        self.assertEqual(path.read_text(), "")


class TestCovReportBatch(unittest.TestCase):
    """What a --cov-report batch wires up, without Questa.

    run_test() is patched to PASS and drop a .ucdb on disk (a real one would
    need the simulator); merge_batch_coverage() is patched to record its
    arguments and copy the request to ucdb.list the way mk/uvmt/vsim.mk does,
    but leaves no merged.ucdb -- so generate_coverage_reports() stays on its
    fail-soft "no database" path and no vcover is ever invoked. What is under
    test is exactly that wiring: the clean-slate wipe, the parked auto-
    selection of --all-custom, the two request lists, and what summary.json
    is allowed to claim without databases behind it.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.sim_dir = self.tmp / "sim" / "uvmt"
        self.cfg_results = self.sim_dir / "vsim_results" / "default"
        self.cfg_results.mkdir(parents=True)
        for name, value in (("REPO", self.tmp),
                            ("TESTS_PROGRAM_ROOT", self.tmp / "tests" / "programs")):
            original = getattr(run_tests, name)
            setattr(run_tests, name, value)
            self.addCleanup(setattr, run_tests, name, original)
        original = run_tests.TESTBENCHES["uvmt"]["sim_dir"]
        run_tests.TESTBENCHES["uvmt"]["sim_dir"] = self.sim_dir
        self.addCleanup(run_tests.TESTBENCHES["uvmt"].__setitem__,
                        "sim_dir", original)
        original = regression_report.REPO_ROOT
        regression_report.REPO_ROOT = self.tmp
        self.addCleanup(setattr, regression_report, "REPO_ROOT", original)

        self.ran = []

        def fake_run_test(tb, test, *args, **kwargs):
            self.ran.append(test)
            ucdb = run_tests.test_ucdb_path(tb, test, 0, "default")
            ucdb.parent.mkdir(parents=True, exist_ok=True)
            ucdb.write_text("fake ucdb")
            return ("PASS", "", None, "1")

        original = run_tests.run_test
        run_tests.run_test = fake_run_test
        self.addCleanup(setattr, run_tests, "run_test", original)

        self.merges = []

        def fake_merge(tb, cfg, timeout, ucdb_list=None, merge_dir="merged"):
            self.merges.append((merge_dir, Path(ucdb_list).read_text().splitlines()))
            merge_dir_path = self.cfg_results / merge_dir
            merge_dir_path.mkdir(parents=True, exist_ok=True)
            (merge_dir_path / "ucdb.list").write_text(
                Path(ucdb_list).read_text())
            return True

        original = run_tests.merge_batch_coverage
        run_tests.merge_batch_coverage = fake_merge
        self.addCleanup(setattr, run_tests, "merge_batch_coverage", original)

    def run_main(self, argv):
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as exited:
                run_tests.main(argv)
        return exited.exception.code

    def summary(self):
        path = self.tmp / "coverage_report" / "summary.json"
        return json.loads(path.read_text())

    def test_clean_slate_wipe(self):
        stale_ucdb = self.cfg_results / "old_run" / "0" / "old_run.ucdb"
        stale_ucdb.parent.mkdir(parents=True)
        stale_ucdb.write_text("stale")
        stale_merged = self.cfg_results / "merged"
        stale_merged.mkdir()
        (stale_merged / "merged.ucdb").write_text("stale")
        stale_parked = self.cfg_results / "merged_parked"
        stale_parked.mkdir()
        (stale_parked / "stale.txt").write_text("stale")
        stale_report = self.tmp / "coverage_report"
        stale_report.mkdir()
        (stale_report / "index.html").write_text("stale")

        code = self.run_main(["--tb", "uvmt", "--cov-report", "hello-world"])
        self.assertEqual(code, 0)
        # Every merge input of the previous batch is gone, and nothing from
        # the published trees survived -- while this batch's own .ucdb, the
        # one written after the wipe, is still there.
        self.assertFalse(stale_ucdb.exists())
        self.assertFalse((stale_merged / "merged.ucdb").exists())
        self.assertFalse((stale_parked / "stale.txt").exists())
        self.assertFalse((stale_report / "index.html").exists())
        self.assertTrue((self.cfg_results / "hello-world" / "0"
                         / "hello-world.ucdb").is_file())
        self.assertTrue((stale_report / "summary.json").is_file())

    def test_parked_selection_and_two_merge_scopes(self):
        parked = run_tests.PARKED[0]
        (run_tests.TESTS_PROGRAM_ROOT / "custom" / "hello-world").mkdir(
            parents=True)
        self.ran.clear()
        code = self.run_main(["--tb", "uvmt", "--all-custom", "--cov-report"])
        self.assertEqual(code, 0)
        # --all-custom found the one test program in the tree, and --cov-report
        # pulled every parked test in on top of it -- once each.
        self.assertEqual(sorted(self.ran),
                         sorted(run_tests.PARKED + ["hello-world"]))
        self.assertEqual(self.ran.count(parked), 1)

        scopes = dict(self.merges)
        self.assertEqual(sorted(scopes), ["merged", "merged_parked"])
        default_names = sorted(Path(p).stem for p in scopes["merged"])
        parked_names = sorted(Path(p).stem for p in scopes["merged_parked"])
        # The parked scope is a strict superset: exactly the default names
        # plus every parked one.
        self.assertEqual(default_names, ["hello-world"])
        self.assertEqual(parked_names, sorted(run_tests.PARKED + ["hello-world"]))

        summary = self.summary()
        # test_sets names what each database holds, read back from the
        # ucdb.list files; the "parked" set is only the delta. With no
        # merged.ucdb on disk (the fake merged never writes one) there are no
        # metrics, and -- crucially -- no including_parked block for a
        # database that does not exist.
        self.assertEqual(summary["test_sets"]["default"], ["hello-world"])
        self.assertEqual(summary["test_sets"]["parked"],
                         sorted(run_tests.PARKED))
        self.assertNotIn("including_parked", summary)
        # Report metadata is always written (a tree without git says so).
        self.assertIn("generated", summary)
        self.assertIn("versions", summary)
        self.assertEqual(summary["versions"]["cve2"]["actual_hash"],
                         "not cloned")


class TestIncludingParkedSummary(unittest.TestCase):
    """The including_parked block mirrors the top-level metric keys, so the
    dashboard toggles between two dicts of one shape. Fixture numbers, two
    mini metric sets, no Questa."""

    CODE = {"code": 95.0,
            "statement": {"hits": 95, "active": 100, "percent": 95.0},
            "branch": {"hits": 9, "active": 10, "percent": 90.0},
            "condition": {"hits": 4, "active": 5, "percent": 80.0},
            "fsm_state": {"hits": 1, "active": 1, "percent": 100.0},
            "fsm_transition": {"hits": 2, "active": 2, "percent": 100.0}}
    FUNCTIONAL = {"percent": 70.0, "bins_covered": 70, "bins_total": 100,
                  "packages": {"/uvme_cv32e20_pkg": {"bins_covered": 70,
                                                     "bins_total": 100,
                                                     "percent": 70.0}}}

    def test_metric_block(self):
        block = run_tests.build_including_parked_summary(
            self.CODE, self.FUNCTIONAL, 8, 10)
        self.assertEqual(block["code_coverage"], 95.0)
        self.assertEqual(block["functional_coverage"], 70.0)
        self.assertEqual(block["bins_covered"], 70)
        self.assertEqual(block["bins_total"], 100)
        self.assertEqual(block["functional_packages"],
                         self.FUNCTIONAL["packages"])
        self.assertEqual(block["pass_rate"], 80.0)
        self.assertEqual(block["total_tests"], 10)
        self.assertEqual(block["passed"], 8)
        self.assertEqual(block["failed"], 2)
        # The five TRL5 keys, under the same names as the top level.
        self.assertEqual(block["line_coverage"], 95.0)
        self.assertEqual(block["condition_coverage"], 80.0)
        self.assertEqual(block["branch_coverage"], 90.0)
        self.assertEqual(block["fsm_state_coverage"], 100.0)
        self.assertEqual(block["fsm_transition_coverage"], 100.0)
        # code_metrics drops the "code" average, like the top level does.
        self.assertNotIn("code", block["code_metrics"])
        self.assertIn("statement", block["code_metrics"])

    def test_missing_metrics_stay_na(self):
        block = run_tests.build_including_parked_summary(None, None, 0, 0)
        self.assertEqual(block["code_coverage"], "N/A")
        self.assertEqual(block["functional_coverage"], "N/A")
        self.assertEqual(block["bins_total"], 0)
        self.assertEqual(block["code_metrics"], {})
        self.assertEqual(block["pass_rate"], 0)
        self.assertNotIn("line_coverage", block)


class TestCollectVersions(unittest.TestCase):
    """The Build Versions data: parsed pins, checked-out state, and the pin
    comparison the dashboard warns on. Git is stubbed -- what is under test is
    which values win where and how a missing checkout reads, not git itself."""

    REPOS_MK = """CV_CORE_REPO   ?= https://example.invalid/cve2
CV_CORE_BRANCH ?= main
CV_CORE_HASH   ?= d7f2156
#CV_CORE_REPO   ?= https://example.invalid/old-fork
#CV_CORE_BRANCH ?= some_branch
#CV_CORE_HASH   ?= dead123
CV_VERIF_REPO   ?= https://example.invalid/core-v-verif
CV_VERIF_BRANCH ?= cv32e20-dv/dev
CV_VERIF_HASH   ?= c525ca3
"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.tmp / "sim").mkdir()
        (self.tmp / "sim" / "ExternalRepos.mk").write_text(self.REPOS_MK)
        (self.tmp / "core-v-cores" / "cv32e20").mkdir(parents=True)
        # vendor_lib/openhwgroup_core-v-verif deliberately NOT created.

    def test_parse_external_repos_skips_comments(self):
        pins = run_tests.parse_external_repos(self.tmp / "sim"
                                              / "ExternalRepos.mk")
        self.assertEqual(pins["CV_CORE_REPO"], "https://example.invalid/cve2")
        self.assertEqual(pins["CV_CORE_HASH"], "d7f2156")
        self.assertEqual(pins["CV_VERIF_BRANCH"], "cv32e20-dv/dev")
        self.assertNotIn("dead123", pins.values())
        self.assertNotIn("CV_CORE_BRANCH", {k for k, v in pins.items()
                                            if v == "some_branch"})

    def test_collect_versions(self):
        full_head = "d7f21568028a1114be663599bd42145dccf28928"
        state = {"clean": ""}

        def fake_git(cwd, *args):
            cwd = str(cwd)
            if cwd.endswith("cv32e20") and not cwd.endswith("core-v-cores"):
                if args[:2] == ("rev-parse", "HEAD"):
                    return full_head
                if args[0] == "status":
                    return state["clean"]
            if cwd == str(self.tmp):
                if args[:2] == ("rev-parse", "--abbrev-ref"):
                    return "feat_coverage"
                if args[:2] == ("rev-parse", "HEAD"):
                    return "1234567890abcdef1234567890abcdef12345678"
                if args[:2] == ("remote", "get-url"):
                    return "https://example.invalid/cv32e20-dv.git"
                if args[0] == "status":
                    return "?? dirty"
            return None

        original = run_tests._git_output
        run_tests._git_output = fake_git
        self.addCleanup(setattr, run_tests, "_git_output", original)

        versions = run_tests.collect_versions(repo=self.tmp)
        cve2 = versions["cve2"]
        self.assertEqual(cve2["repo"], "https://example.invalid/cve2")
        self.assertEqual(cve2["branch"], "main")
        self.assertEqual(cve2["pinned_hash"], "d7f2156")
        self.assertEqual(cve2["actual_hash"], full_head)
        self.assertTrue(cve2["matches_pin"])
        self.assertTrue(cve2["clean"])

        state["clean"] = " M rtl/cve2_id_stage.sv"
        self.assertFalse(run_tests.collect_versions(repo=self.tmp)["cve2"]["clean"])

        # This repository has no pin: repo/branch come from its own git.
        dv = versions["cv32e20-dv"]
        self.assertEqual(dv["repo"], "https://example.invalid/cv32e20-dv.git")
        self.assertEqual(dv["branch"], "feat_coverage")
        self.assertIsNone(dv["pinned_hash"])
        self.assertIsNone(dv["matches_pin"])
        self.assertFalse(dv["clean"])

        # Never cloned: says so, with the pin it wanted still visible.
        verif = versions["core-v-verif"]
        self.assertEqual(verif["actual_hash"], "not cloned")
        self.assertEqual(verif["pinned_hash"], "c525ca3")
        self.assertIsNone(verif["matches_pin"])

    def test_collect_versions_survives_no_pins_file(self):
        empty = self.tmp.parent / "empty-checkout"
        empty.mkdir()
        self.addCleanup(shutil.rmtree, empty, True)
        original = run_tests._git_output
        run_tests._git_output = lambda cwd, *args: None
        self.addCleanup(setattr, run_tests, "_git_output", original)
        versions = run_tests.collect_versions(repo=empty)
        self.assertEqual(set(versions),
                         {"cv32e20-dv", "cve2", "core-v-verif"})
        self.assertTrue(all(v["actual_hash"] == "not cloned"
                            for v in versions.values()))


class TestMergeBatchCoverageCommand(unittest.TestCase):
    """The batch merge is one make call, and only this test pins its shape.

    cov_merge, not cov: cov is one of Common.mk's TEST_YAML_PARSE_TARGETS and
    aborts without a TEST variable -- and a batch merge has no single test to
    name. A --cov-report batch whose merge died that way still exits 0 under
    --allow-failures, so the shape here is what stands between a rename and a
    silently unmerged batch."""

    def test_merge_command_shape(self):
        captured = {}

        def fake_run(cmd, cwd, env, timeout, capture=True):
            captured.update(cmd=cmd, cwd=cwd)
            return 0, "", ""

        original = run_tests._run
        run_tests._run = fake_run
        self.addCleanup(setattr, run_tests, "_run", original)
        ok = run_tests.merge_batch_coverage(
            "uvmt", "default", 60,
            ucdb_list=Path("sim/uvmt/vsim_results/default/merged"
                           "/ucdb.request"),
            merge_dir="merged_parked")
        self.assertTrue(ok)
        cmd = captured["cmd"]
        self.assertIn("cov_merge", cmd)
        self.assertNotIn("cov", cmd)
        self.assertIn("MERGE=YES", cmd)
        # CFG says which results tree the mk merge searches when it has no
        # explicit input list (COV_MERGE_FIND walks $(SIM_CFG_RESULTS), and that
        # defaults to default): without it --cfg NAME --merge-existing merges
        # default's .ucdb files into NAME's merged directory.
        self.assertIn("CFG=default", cmd)
        self.assertFalse([a for a in cmd if a.startswith("TEST=")])
        self.assertTrue(any(a.startswith("VSIM_COV_MERGE_DIR=")
                            and a.endswith("merged_parked") for a in cmd))
        self.assertTrue(any(a.startswith("COV_MERGE_LIST=") for a in cmd))
        # The uvmt make args still ride along (SIMULATOR=vsim ...).
        self.assertIn("SIMULATOR=vsim", cmd)


class TestReportOnlyRecovery(unittest.TestCase):
    """--report-only runs and merges nothing, so the pass/fail counts it
    republishes are recovered: from the regression document -- the authority
    on verdicts, whose rows carry the parked flag, so both dashboard views
    recover -- with the published summary.json only as a fallback. No merged
    .ucdb is created unless a test deliberately leaves one behind, and a
    fixture that does and still drives main() stubs the export step
    (stub_vcover): --report-only runs and merges nothing, so no metric is ever
    recomputed and no real vcover process is ever spawned."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.sim_dir = self.tmp / "sim" / "uvmt"
        self.cfg_results = self.sim_dir / "vsim_results" / "default"
        self.cfg_results.mkdir(parents=True)
        for name, value in (("REPO", self.tmp),
                            ("TESTS_PROGRAM_ROOT", self.tmp / "tests" / "programs")):
            original = getattr(run_tests, name)
            setattr(run_tests, name, value)
            self.addCleanup(setattr, run_tests, name, original)
        original = run_tests.TESTBENCHES["uvmt"]["sim_dir"]
        run_tests.TESTBENCHES["uvmt"]["sim_dir"] = self.sim_dir
        self.addCleanup(run_tests.TESTBENCHES["uvmt"].__setitem__,
                        "sim_dir", original)
        original = regression_report.REPO_ROOT
        regression_report.REPO_ROOT = self.tmp
        self.addCleanup(setattr, regression_report, "REPO_ROOT", original)

    def run_main(self, argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with self.assertRaises(SystemExit) as exited:
                run_tests.main(argv)
        return exited.exception.code, buf.getvalue()

    def stub_vcover(self):
        """Stand in for the metric steps of a fixture that does leave a merged
        database on disk. --report-only neither runs nor merges, so a vcover
        export is the only command that path may reach: anything else is a
        regression in its own right, not something this stub should swallow."""
        def fake_run(cmd, cwd, env, timeout, capture=True):
            if cmd[0] != "vcover":
                raise AssertionError(f"--report-only invoked {cmd[0]}")
            return 0, "", ""

        original = run_tests._run
        run_tests._run = fake_run
        self.addCleanup(setattr, run_tests, "_run", original)

    def summary(self):
        path = self.tmp / "coverage_report" / "summary.json"
        return json.loads(path.read_text())

    @staticmethod
    def document(tb="uvmt", cfg="default"):
        return {"tb": tb, "cfg": cfg, "tests": [
            {"name": "a", "verdict": "PASS"},
            {"name": "b", "verdict": "PASS"},
            {"name": "c", "verdict": "FAIL"},
            {"name": run_tests.PARKED[0], "verdict": "PASS", "parked": True},
            {"name": run_tests.PARKED[1], "verdict": "ERROR", "parked": True},
        ]}

    def test_recovered_from_regression_document(self):
        (self.sim_dir / regression_report.DOCUMENT_NAME).write_text(
            json.dumps(self.document()))
        code, out = self.run_main(["--tb", "uvmt", "--report-only"])
        self.assertEqual(code, 0)
        self.assertIn("2/3 passed, 3/5 including parked "
                      "from regression_results.json.", out)
        summary = self.summary()
        # Top-level keys are the default scope: the parked rows never move them.
        self.assertEqual(summary["passed"], 2)
        self.assertEqual(summary["total_tests"], 3)

    def test_falls_back_to_published_summary(self):
        report_dir = self.tmp / "coverage_report"
        report_dir.mkdir()
        (report_dir / "summary.json").write_text(json.dumps({
            "passed": 4, "total_tests": 5,
            "including_parked": {"passed": 6, "total_tests": 7}}))
        _code, out = self.run_main(["--tb", "uvmt", "--report-only"])
        self.assertIn("4/5 passed, 6/7 including parked from summary.json.",
                      out)

    def test_document_for_another_tb_or_cfg_is_not_recovered(self):
        # A document from a different testbench or configuration says nothing
        # about this one; without a fallback the counts stay 0/0 rather than
        # borrowing a stranger's verdicts.
        (self.sim_dir / regression_report.DOCUMENT_NAME).write_text(
            json.dumps(self.document(tb="core")))
        _code, out = self.run_main(["--tb", "uvmt", "--report-only"])
        self.assertIn("0/0 passed.", out)

    # The provenance warning, matched on its scope label. A test that only
    # looked for a word the sentence contains can be satisfied by other output
    # of the same run -- "including-parked" appears in the no-database note --
    # so what these tests assert is which scope spoke, and how many did.
    PROVENANCE = re.compile(
        r"warning: the recovered verdicts and the (\S+) merged database "
        r"list different tests")

    @classmethod
    def warned_scopes(cls, out):
        return cls.PROVENANCE.findall(out)

    def test_a_document_that_is_not_the_merged_batch_is_called_out(self):
        """The document is rewritten by every uvmt batch while the merged
        databases survive until the next --report-only, so a --report-only after
        an unrelated batch would publish one batch's counts beside another's
        metrics. The merge input lists are the only record of what a database
        holds, so a disagreement is warned about by name -- and the report still
        goes out, because both halves are true of their own batch."""
        (self.sim_dir / regression_report.DOCUMENT_NAME).write_text(
            json.dumps(self.document()))
        merged = self.cfg_results / "merged"
        merged.mkdir()
        # The document passes a, b and parked[0]; this database holds a, b and
        # one test the document never heard of, and not parked[0]. No parked
        # database exists in this fixture, so exactly one scope may speak.
        (merged / "ucdb.list").write_text(
            "/x/a/a.ucdb\n/x/b/b.ucdb\n/x/gone/gone.ucdb\n")
        code, out = self.run_main(["--tb", "uvmt", "--report-only"])
        self.assertEqual(code, 0)
        self.assertEqual(self.warned_scopes(out), ["default"])
        self.assertIn("gone", out)
        # Warned, not withheld: the counts still publish.
        self.assertEqual(self.summary()["passed"], 2)

    def test_the_parked_scope_is_the_one_named_when_it_disagrees(self):
        """Each scope is measured against its own input list, so the warning has
        to name the scope that disagreed and stay quiet about the one that did
        not: whoever reads it decides which database to re-merge."""
        document = self.document()
        (self.sim_dir / regression_report.DOCUMENT_NAME).write_text(
            json.dumps(document))
        merged = self.cfg_results / "merged"
        parked = self.cfg_results / "merged_parked"
        merged.mkdir()
        parked.mkdir()
        passed_main = [r["name"] for r in document["tests"]
                       if r["verdict"] == "PASS" and not r.get("parked")]
        same = "".join(f"/x/{n}/{n}.ucdb\n" for n in passed_main)
        (merged / "ucdb.list").write_text(same)
        # The identical list beside the parked database says it holds no parked
        # PASS at all, while the document passes parked[0]: default agrees,
        # including-parked does not.
        (parked / "ucdb.list").write_text(same)
        _code, out = self.run_main(["--tb", "uvmt", "--report-only"])
        self.assertEqual(self.warned_scopes(out), ["including-parked"])
        self.assertIn(run_tests.PARKED[0], out)

    def test_a_database_without_its_input_list_says_its_origin_is_unknown(self):
        """An absent list is not agreement. A merged.ucdb with no ucdb.list
        beside it was produced by something that recorded nothing, which is
        precisely when the report should not imply the pair was checked."""
        (self.sim_dir / regression_report.DOCUMENT_NAME).write_text(
            json.dumps(self.document()))
        merged = self.cfg_results / "merged"
        merged.mkdir()
        (merged / "merged.ucdb").write_bytes(b"not a database")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            run_tests.warn_recovered_vs_databases(
                self.document()["tests"], merged,
                self.cfg_results / "merged_parked")
        out = buf.getvalue()
        self.assertIn("cannot check the default merged database", out)
        self.assertEqual(self.warned_scopes(out), [])

    def test_the_summary_fallback_is_measured_the_same_way(self):
        """The fallback pairs a published summary's counts with the databases on
        disk now, and summary.json records the names those databases were built
        from -- so the same disagreement has to surface on that path too."""
        report_dir = self.tmp / "coverage_report"
        report_dir.mkdir()
        (report_dir / "summary.json").write_text(json.dumps({
            "passed": 4, "total_tests": 5,
            "test_sets": {"default": ["a", "b"], "parked": []}}))
        merged = self.cfg_results / "merged"
        merged.mkdir()
        (merged / "ucdb.list").write_text("/x/c/c.ucdb\n/x/d/d.ucdb\n")
        _code, out = self.run_main(["--tb", "uvmt", "--report-only"])
        self.assertEqual(self.warned_scopes(out), ["default"])

    def test_the_parked_union_is_what_the_parked_list_has_to_match(self):
        """test_sets keeps the parked side as only the parked names, while the
        parked database is the default list plus those. The fallback has to
        compare the union: pass the parked names alone and a database that
        agrees with the report disagrees with the check."""
        report_dir = self.tmp / "coverage_report"
        report_dir.mkdir()
        (report_dir / "summary.json").write_text(json.dumps({
            "passed": 4, "total_tests": 5,
            "test_sets": {"default": ["a", "b"],
                          "parked": [run_tests.PARKED[0]]}}))
        parked = self.cfg_results / "merged_parked"
        parked.mkdir()
        # The union a, b, parked[0] plus one name the report never recorded:
        # the default scope has no database here, so parked alone may speak.
        (parked / "ucdb.list").write_text(
            f"/x/a/a.ucdb\n/x/b/b.ucdb\n"
            f"/x/{run_tests.PARKED[0]}/{run_tests.PARKED[0]}.ucdb\n"
            "/x/extra/extra.ucdb\n")
        _code, out = self.run_main(["--tb", "uvmt", "--report-only"])
        self.assertEqual(self.warned_scopes(out), ["including-parked"])
        self.assertIn("extra", out)
        # The count is what discriminates: three names is the union, one is the
        # parked set alone -- and the two lists differ either way.
        self.assertIn("counts 3 as PASS", out)

    def test_a_summary_recording_no_names_discloses_the_missing_check(self):
        """A summary without test_sets cannot be compared, yet its counts are
        still published beside this database: that is a pairing which went
        unchecked, and it is said -- instead of the "counts 0 as PASS"
        comparison an empty name set would otherwise produce."""
        merged = self.cfg_results / "merged"
        merged.mkdir()
        (merged / "merged.ucdb").write_bytes(b"not a database")
        # A list that does name tests, which is the state the branch exists
        # for: without it the empty recovered set is compared, and the run
        # announces "counts 0 as PASS" about a pairing it never checked. The
        # recovered summary supplies counts and no test_sets at all.
        (merged / "ucdb.list").write_text("/x/a/a.ucdb\n/x/b/b.ucdb\n")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            run_tests.warn_summary_vs_databases({"passed": 4, "total_tests": 5},
                                                merged,
                                                self.cfg_results / "merged_parked")
        out = buf.getvalue()
        self.assertIn("cannot check the default merged database against the "
                      "published summary", out)
        self.assertIn("recorded no test names", out)
        self.assertNotIn("counts 0 as PASS", out)
        self.assertEqual(self.warned_scopes(out), [])

    def test_a_parked_only_summary_is_still_a_pairing(self):
        """A summary whose counts are all in the parked block is still counts
        recovered beside these databases. Gating the check on the default
        numbers being non-zero published 0/0 passed, 6/7 including parked with
        nothing said about where the 6/7 came from."""
        report_dir = self.tmp / "coverage_report"
        report_dir.mkdir()
        (report_dir / "summary.json").write_text(json.dumps({
            "passed": 0, "total_tests": 0,
            "including_parked": {"passed": 6, "total_tests": 7}}))
        merged = self.cfg_results / "merged"
        merged.mkdir()
        (merged / "merged.ucdb").write_bytes(b"not a database")
        # A database on disk takes the metric steps off their no-database
        # fail-soft path; the provenance disclosure under test is about where
        # the counts came from, not about a simulator being present.
        self.stub_vcover()
        _code, out = self.run_main(["--tb", "uvmt", "--report-only"])
        self.assertIn("0/0 passed, 6/7 including parked from summary.json.",
                      out)
        self.assertIn("cannot check the default merged database against the "
                      "published summary", out)

    def test_an_unrecorded_publish_still_ships_the_test_sets_keys(self):
        """coverage.yml's validation step requires test_sets, so "nothing
        recorded" has to publish empty sets rather than no key -- and
        warn_summary_vs_databases reads exactly that value back as unrecorded,
        not as agreement with the databases beside it."""
        # A document from another testbench is not recovered, so this falls
        # through to a summary.json that was never written: nothing recorded.
        (self.sim_dir / regression_report.DOCUMENT_NAME).write_text(
            json.dumps(self.document(tb="core")))
        code, out = self.run_main(["--tb", "uvmt", "--report-only"])
        self.assertEqual(code, 0)
        self.assertEqual(self.summary()["test_sets"],
                         {"default": [], "parked": []})
        self.assertIn("0/0 passed.", out)

    def test_a_matching_document_and_database_say_nothing(self):
        """No warning on the healthy path -- a warning that always fires is a
        warning nobody reads. Both scopes are present and both agree, which is
        also the fixture that keeps the parked scope's positive path covered."""
        document = self.document()
        (self.sim_dir / regression_report.DOCUMENT_NAME).write_text(
            json.dumps(document))
        merged = self.cfg_results / "merged"
        parked = self.cfg_results / "merged_parked"
        merged.mkdir()
        parked.mkdir()
        passed_main = [r["name"] for r in document["tests"]
                       if r["verdict"] == "PASS" and not r.get("parked")]
        (merged / "ucdb.list").write_text(
            "".join(f"/x/{n}/{n}.ucdb\n" for n in passed_main))
        passed_all = [r["name"] for r in document["tests"]
                      if r["verdict"] == "PASS"]
        (parked / "ucdb.list").write_text(
            "".join(f"/x/{n}/{n}.ucdb\n" for n in passed_all))
        _code, out = self.run_main(["--tb", "uvmt", "--report-only"])
        self.assertEqual(self.warned_scopes(out), [])


if __name__ == "__main__":
    unittest.main()
