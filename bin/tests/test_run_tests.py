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
        self.assertIn("coverage_review.py", out)
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


if __name__ == "__main__":
    unittest.main()
