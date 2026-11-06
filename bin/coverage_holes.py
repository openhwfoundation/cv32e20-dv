#!/usr/bin/env python3
# Copyright (c) 2026 Eclipse Foundation
# SPDX-License-Identifier: Apache-2.0 WITH SHL-2.1
"""Extract every unwaived code-coverage hole from a merged .ucdb as CSV.

Source
------
Questa's own holes report, i.e. the same view ``make cov_holes_details`` shows a
reviewer::

    vcover report -details -annotate -below 100 -precision 2 \\
        -code bcsf -instance=<cov_instance>. <merged.ucdb>

Parsing this rather than the ``-xml -details`` export is deliberate, because a
*bin* is not the same thing as an arm in the XML. In

    <if hasElse="1" active="2" hits="2">
      <ielem ln="68" st="1" true="25539418" false="5119403"/>
      <ielem ln="68" st="2" true="5119403"  false="0"/>
    </if>

the second ``false="0"`` is the count falling out of the ``else``, not an
unexercised bin; the group says 2 active, 2 hit. Counting those zeros as holes
inflates the list by an order of magnitude, so this tool only ever reports a
miss that Questa's own report marks ``***0***``, and its rollup is checked
against ``vcover report -summary``, the numbers
coverage_report/summary.json publishes, which is what makes the two agree by
construction rather than by hope.

The three units this has to get right, because Questa's metrics do not all count
the same thing:

* **statement, branch**: one row per item the report marks missed, including
  the ``All False Count`` row, which is the ``else`` arm of an ``if`` and is a
  bin like any other.
* **condition**: Questa counts *input terms*, so one row per input term whose
  ``Covered`` column is ``N``. The ``Row N: ***0***`` FEC targets underneath a
  term are how you exclude it (``-feccondrow``), so they are collected into the
  row's Target rather than emitted as separate holes; counting them instead
  gave 26 rows for 21 real holes.
* **assertion**: pass count 0 means the suite never exercised it.

What counts as a hole
---------------------
The report is generated *with* sim/tools/vsim/cov.tcl's exclusions in force (they
are saved into every test's .ucdb), so what this lists is exactly the set a
developer sees as still open: waived code is not here. That is the input to the
triage into "coverable", "new test" or "waive" in
docs/coverage/coverage_review.md.

Usage
-----
    bin/coverage_holes.py --summary
    bin/coverage_holes.py --apply-cov-tcl          # current cov.tcl, not the saved one
    bin/coverage_holes.py --ucdb path/to/merged.ucdb --out holes.csv
    bin/coverage_holes.py --report log_agent/covprobe/holes_txt   # re-parse a dump

--apply-cov-tcl is how the list is regenerated right after cov.tcl changes: the
exclusions a .ucdb carries are the ones that were in force when the tests were
saved, so a plain `vcover report` keeps showing the *previous* file's view of
the design. It runs vsim -viewcov, applies cov.tcl's exclusions, and asks the
same questions there, which needs a licence, where --report and the plain
`vcover` path need none.
"""

import argparse
import csv
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import OrderedDict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_UCDB = (REPO / "sim" / "uvmt" / "vsim_results" / "default"
                / "merged" / "merged.ucdb")


def repo_relative(path):
    """`path` as seen from the repository root, for anything this tool emits.

    The provenance header of a dump gets committed and quoted in the review
    sheet, so an absolute path in it records the home directory of whoever ran
    the tool and nothing about where the data came from.
    """
    try:
        return os.path.relpath(path, REPO)
    except ValueError:  # a path on another drive
        return str(path)


DEFAULT_OUT = REPO / "docs" / "coverage" / "raw" / "holes.csv"
# The per-design-unit rollup is a count of the rows of --out, not a second
# measurement, and the published analysis page counts the same thing out of
# holes.csv itself (templates/analysis_dashboard/index.html), so it goes beside
# the report it belongs to rather than being committed next to its own input.
# coverage_report/ is generated and gitignored; docs/coverage/ is what a reviewer
# without Questa reads, and holes.csv is all they need to reproduce this.
DEFAULT_BY_DU = REPO / "coverage_report" / "analysis" / "raw" / "holes_by_du.csv"

# The DUT scope, i.e. TESTBENCHES['uvmt']['cov_instance'] in bin/run_tests.py and
# COV_INSTANCE in mk/uvmt/uvmt.mk. Code coverage is only instrumented here, so
# asking Questa for anything else reports an empty design.
DEFAULT_INSTANCE = "/uvmt_cv32e20_tb/dut_wrap/cv32e20_top_i/u_cve2_top/u_cve2_core"

MISS = "***0***"

# Which metric a missed item belongs to, from the banner of the block it is in.
BANNER_METRICS = {
    "Statement Coverage": "stmt",
    "Branch Coverage": "branch",
    "Condition Coverage": "condition",
    "FSM Coverage": "fsm",
    "Toggle Coverage": "toggle",
    "Expression Coverage": "expression",
    "Assertion Coverage": "assertion",
    "Cover Group Coverage": "cvg",
}

DESIGN_UNIT_RE = re.compile(r"^=== Design Unit:\s*(?:work\.)?(\S+)")
INSTANCE_RE = re.compile(r"^=== Instance:\s*(\S+)")
FILE_RE = re.compile(r"^\s*File\s+(\S+)")
BANNER_RE = re.compile(r"^([A-Za-z ]+Coverage):\s*$")
# A per-metric rollup row: "Branches 92 75 17 81.52%". The optional columns in
# the middle are the Excluded and Weight columns that -showexcluded adds.
ROLLUP_RE = re.compile(r"^\s*([A-Za-z][A-Za-z /]*?)\s+"
                       r"(\d+)\s+(\d+)\s+(\d+)(?:\s+\d+)*\s+[\d.]+%\s*$")
# An annotated source line the report marks missed: "257  1  ***0***  <source>".
# The item column is optional because the "All False Count" and "Count coming
# in to IF" rows have neither a line number nor an item.
MISSED_ITEM_RE = re.compile(r"^\s*(\d+)?\s*(\d+)?\s+" + re.escape(MISS) +
                            r"\s*(.*?)\s*$")
# An IF/CASE block header: "514  433  Count coming in to IF". The line
# number is only printed here, and the block's "All False Count" row --
# the else arm, a bin like any other, carries none, so it inherits it.
INCOMING_RE = re.compile(r"^\s*(\d+)\s+[\d,]+\s+Count coming in to\s")
# An FEC condition block header: "Line 312 Item 1 (priv_mode_i == PRIV_LVL_M)".
FEC_HEADER_RE = re.compile(r"^\s*Line\s+(\d+)\s+Item\s+(\d+)\s+(.*?)\s*$")
# One FEC row: "Row 1: ***0***  (priv_mode_i == PRIV_LVL_M)_0  -".
FEC_ROW_RE = re.compile(r"^\s*Row\s+(\d+):\s+(?:" + re.escape(MISS) +
                        r"|[\d,]+)\s+(\S+)\s*(.*?)\s*$")
# An input-term line of the "Input Term Covered Reason Hint" table.
INPUT_TERM_RE = re.compile(r"^\s{2,}(\S.*?)\s{2,}([YN])\s*(.*?)\s*$")
# An assertion's hierarchical name: a path, and never the File(line) line below
# it (which carries parentheses), nor the banner rules made of dashes.
ASSERT_NAME_RE = re.compile(r"^(/[^\s()|-]+)\s*$")
ASSERT_COUNTS_RE = re.compile(r"^\s*(\d+)\s+(\d+)\s*$")

COLUMNS = ["Design Unit", "Instance", "File", "Line", "Metric", "Target",
           "Hits", "Misses", "Source"]


class Hole:
    """One missed bin, in the unit its metric counts."""

    def __init__(self, du, instance, fpath, line, metric, target, source=""):
        self.du = du
        self.instance = instance
        self.file = fpath
        self.line = line
        self.metric = metric
        self.target = target
        self.source = source

    def row(self):
        return OrderedDict((
            ("Design Unit", self.du),
            ("Instance", self.instance),
            ("File", self.file),
            ("Line", self.line),
            ("Metric", self.metric),
            ("Target", self.target),
            ("Hits", 0),
            ("Misses", 1),
            ("Source", self.source),
        ))


def _source_name(path):
    """Keep the basename and its parent: the paths are the compile host's."""
    if not path:
        return ""
    parts = Path(path).parts
    return "/".join(parts[-2:]) if len(parts) >= 2 else path


def parse_holes_report(text):
    """Return (holes, rollups) parsed out of Questa's text reports.

    ``rollups`` maps a report row name ("branches", "conditions", …) to
    (active, hits, misses) summed over the design-unit rollups the report prints.
    The report is a state machine of banners: a design unit, then a metric, then
    annotated source blocks, so the metric and the file both come from the last
    banner seen, and a block is only flushed when its own table is known to be
    over.
    """
    holes = []
    rollups = {}
    state = {"du": "", "instance": "", "file": "", "metric": None,
             "assert": None, "in_assertion_table": False,
             # The FEC condition block being read: its header, its uncovered
             # input terms, and the zero-hit Row numbers under it.
             "fec": None, "branch_line": ""}

    def add(line, kind, target, source="", fpath=None):
        holes.append(Hole(state["du"], state["instance"],
                          _source_name(state["file"]) if fpath is None else fpath,
                          line, kind, target, source))

    def flush_fec():
        """Emit this condition block's holes: one per uncovered input term.

        The terms table decides *whether* the block has a hole and in what unit
        (Questa's condition metric counts input terms, not FEC rows), while the
        zero-hit Rows below it name the -feccondrow targets that would waive it.
        """
        fec = state["fec"]
        state["fec"] = None
        if not fec or not fec["uncovered"]:
            return
        line = fec["line"]
        for term in fec["uncovered"]:
            rows = [number for number, target in fec["rows"]
                    if term in target]
            add(line, "condition",
                "feccondrow %s %s (%s)" % (line, " ".join(rows), term),
                fec["expression"])

    for raw in text.splitlines():
        line = raw.rstrip("\n")
        found = DESIGN_UNIT_RE.match(line)
        if found:
            flush_fec()
            state["du"], state["assert"] = found.group(1), None
            continue
        found = INSTANCE_RE.match(line)
        if found:
            state["instance"] = found.group(1)
            continue
        found = FILE_RE.match(line)
        if found:
            state["file"] = found.group(1)
            continue
        banner = BANNER_RE.match(line)
        if banner:
            flush_fec()
            state["metric"] = BANNER_METRICS.get(banner.group(1))
            state["in_assertion_table"] = (state["metric"] == "assertion")
            state["assert"] = None
            continue
        rollup = ROLLUP_RE.match(line)
        if rollup and state["metric"] is not None:
            name = rollup.group(1).strip().lower().replace(" ", "_")
            values = tuple(int(rollup.group(i)) for i in (2, 3, 4))
            seen = rollups.get(name)
            rollups[name] = tuple(a + b for a, b in zip(seen, values)) if seen \
                else values
            continue

        if state["in_assertion_table"]:
            name = ASSERT_NAME_RE.match(line.strip())
            if name:
                state["assert"] = name.group(1).rstrip("/")
                continue
            counts = ASSERT_COUNTS_RE.match(line)
            if counts and state["assert"]:
                failed, passed = int(counts.group(1)), int(counts.group(2))
                if passed == 0:
                    # The assertion table is a name/count list with no File line,
                    # so the last File banner is another unit's: leave the file
                    # empty rather than repeat it, and keep the full path (which
                    # does name the instance) as the hole's target.
                    add("", "assertion", state["assert"],
                        "pass=0 fail=%d" % failed, fpath="")
                state["assert"] = None
                continue

        if state["metric"] == "condition":
            if re.match(r"^-{5,}Focused Condition View-{5,}$", line):
                continue
            header = FEC_HEADER_RE.match(line)
            if header and "Item" in line:
                flush_fec()
                state["fec"] = {"line": header.group(1),
                                "expression": header.group(3),
                                "uncovered": [], "rows": [], "in_terms": True}
                continue
            fec = state["fec"]
            if fec is None:
                continue
            if re.match(r"^\s*Rows?:", line):
                fec["in_terms"] = False
                continue
            if fec["in_terms"]:
                found = INPUT_TERM_RE.match(line)
                if found and found.group(2) == "N":
                    fec["uncovered"].append(found.group(1).strip())
                continue
            found = FEC_ROW_RE.match(line)
            if found and MISS in line:
                fec["rows"].append((found.group(1), found.group(2)))
            continue

        incoming = INCOMING_RE.match(line)
        if incoming:
            state["branch_line"] = incoming.group(1)
            continue

        found = MISSED_ITEM_RE.match(line)
        if found and state["metric"] in ("stmt", "branch", "fsm", "toggle",
                                         "expression"):
            number, item, source = found.group(1), found.group(2), found.group(3)
            if source.startswith("Count coming in to"):
                # Not a bin: the report prints the entries into a decision for
                # context, and a 0 there just means the decision was never made.
                continue
            if not number and not item:
                if not source.startswith("All False Count"):
                    continue
            if source.startswith("All False Count"):
                # The else arm of the enclosing if, whose line the report only
                # prints on the block's incoming-count row. It is a branch
                # miss Questa counts as one of its own, and it is the specific
                # irq_withdrawn_in_taken miss the review sheet exists to track.
                add(number or state["branch_line"], state["metric"],
                    "All False Count (else arm)", source)
            elif state["metric"] == "stmt":
                # A statement's identity is the source line itself.
                add(number or "", state["metric"], "", source)
            else:
                add(number or "", state["metric"], "item %s" % (item or "-"),
                    source)
            continue
    flush_fec()
    return holes, rollups


# The four report invocations, paired with the rollup that cross-checks them.
# Shared shape with the audit driver: same questions, one session each.
def report_variants(instance):
    return (
        ("_code", ["-details", "-annotate", "-below", "100",
                   "-code", "bcsf"], "-instance=%s." % instance),
        ("_code_summary", ["-summary", "-code", "bcsf"], None),
        ("_assert", ["-details", "-annotate", "-below", "100", "-assert"],
         "-instance=%s." % instance),
        ("_assert_summary", ["-summary", "-assert"], None))


def generate_report_with_cov_tcl(ucdb, instance, cov_tcl, timeout, work_dir):
    """The same four reports, with the *current* cov.tcl applied in a vsim session.

    `vcover report` can only show the exclusions saved into the .ucdb. A vsim
    -viewcov session takes new `coverage exclude` commands and reports their
    effect, verified by measurement like everything else about this flow.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from coverage_waiver_audit import (apply_all_lines, gate_is_active,
                                       parse_cov_tcl)

    vsim = shutil.which("vsim")
    if vsim is None:
        raise SystemExit("error: vsim not on PATH -- --apply-cov-tcl needs Questa "
                         "(docs/coverage/README.md); the saved --report path needs none")
    exclusions, variables, _gates = parse_cov_tcl(cov_tcl)
    # Absolute, because the vsim session below runs with this directory as its
    # cwd: a --work-dir given relative to the repository is otherwise resolved
    # against it a second time, Questa then refuses to open the report
    # ("Failed to open functional coverage report file
    # \"log_agent/covholes/holes_code.txt\" in write mode") and a run that
    # measured nothing reads exactly like a design with no holes left.
    work_dir = Path(work_dir).resolve()
    script = work_dir / "holes_driver.tcl"
    lines = ['proc covtry {label code} {',
             '    if {[catch {uplevel 1 $code} err]} {',
             '        puts "CMDFAIL $label : $err"',
             '    }',
             '}']
    lines += apply_all_lines(exclusions, variables)
    for suffix, options, scope in report_variants(instance):
        out = work_dir / ("holes%s.txt" % suffix)
        command = "coverage report " + " ".join(options)
        if scope:
            command += " " + scope
        # Filed, all four. A vsim -viewcov session sends a -summary table to its
        # own transcript instead of to the subprocess's stdout, so the only copy
        # the caller can read is the one -output writes (measured: `coverage
        # report -summary -code bcsf -output f.txt` returns the same
        # 1432/1409/23 branch and 185/164/21 condition rollups
        # coverage_report/summary.json publishes).
        lines.append('covtry rep%s {%s -output "%s"}'
                     % (suffix, command, out))
    script.write_text("\n".join(lines) + "\nexit -f\n")
    proc = subprocess.run([vsim, "-c", "-viewcov", str(ucdb),
                           "-do", str(script)], cwd=str(work_dir),
                          capture_output=True, text=True, timeout=timeout)
    output = (proc.stdout or "") + (proc.stderr or "")
    for noise in sorted(set(re.findall(r"CMDFAIL [^\n]*", output)))[:20]:
        print("  vsim: %s" % noise)
    details, totals = [], {}
    for suffix, _options, _scope in report_variants(instance):
        path = work_dir / ("holes%s.txt" % suffix)
        if suffix.endswith("_summary"):
            if path.is_file():
                totals.update(parse_summary_report(path.read_text()))
            else:
                print("warning: no %s rollup from the vsim session, so the holes "
                      "cannot be cross-checked against Questa's own miss counts"
                      % suffix)
            continue
        if path.is_file():
            details.append(path.read_text())
        else:
            # Loud on purpose: a missing detail report means the session wrote
            # nothing, and the one answer that must never come out of this tool
            # quietly is "0 holes".
            raise SystemExit("error: the vsim session wrote no %s report (%s) -- "
                             "see the driver at %s" % (suffix, path, script))
    return "\n".join(details), totals


# Emitted metric => the report row that counts it, for the cross-check.
METRIC_ROLLUP = {"stmt": "statements", "branch": "branches",
                 "condition": "conditions", "fsm": "fsm_transitions",
                 "assertion": "assertions", "toggle": "toggles"}


def parse_summary_report(text):
    """Global per-metric rollups from `vcover report -summary`.

    These, not the per-design-unit rows, are the numbers
    coverage_report/summary.json publishes, so they are the ones the emitted
    hole count has to match.
    """
    totals = {}
    for line in text.splitlines():
        match = ROLLUP_RE.match(line)
        if match:
            name = match.group(1).strip().lower().replace(" ", "_")
            totals[name] = (int(match.group(2)), int(match.group(3)),
                            int(match.group(4)))
    return totals


def cross_check(holes, rollups):
    """Compare the emitted rows with Questa's own per-metric miss counts."""
    counted = {}
    for hole in holes:
        key = METRIC_ROLLUP.get(hole.metric)
        if key:
            counted[key] = counted.get(key, 0) + 1
    problems = []
    for key in sorted(set(counted) | set(rollups)):
        if key not in METRIC_ROLLUP.values():
            continue
        misses = counted.get(key, 0)
        row = rollups.get(key)
        if row is None:
            if misses:
                problems.append("%s: %d holes but the summary has no %s row"
                                % (key, misses, key))
        elif row[2] != misses:
            problems.append("%s: %d holes vs summary %d misses (%d active, %d hits)"
                            % (key, misses, row[2], row[0], row[1]))
    return problems


def generate_report(ucdb, instance, timeout, work_dir=None):
    """Run vcover over the ucdb; return (details text, global rollups).

    Four invocations of one tool. ``vcover report`` needs no licence, unlike
    ``vsim``. -code bcsf is statement/branch/condition/FSM and assertions only
    come back when asked for with -assert; each is paired with its own -summary
    so the emitted holes are checked against the same totals summary.json
    publishes.
    """
    vcover = shutil.which("vcover")
    if vcover is None:
        raise SystemExit("error: vcover not on PATH -- set up Questa first "
                         "(docs/coverage/README.md)")
    owned = work_dir is None
    work_dir = (Path(tempfile.mkdtemp(prefix="covholes.")) if owned
                else Path(work_dir))
    work_dir.mkdir(parents=True, exist_ok=True)
    details, totals = [], {}
    try:
        for suffix, options, scope in report_variants(instance):
            summary = suffix.endswith("_summary")
            command = [vcover, "report", "-precision", "2"]
            if scope:
                # -instance scopes the *detail* report to the DUT. The rollup
                # must not carry it: with -instance, vcover prints only the
                # "Total coverage" line for -summary, and code coverage is
                # instrumented inside the DUT alone anyway (VOPT_COV's
                # +cover=bcsf+<instance>), so the unscoped totals are the same
                # numbers coverage_report/summary.json publishes.
                command.append(scope)
            command += options
            out = None
            if not summary:
                out = work_dir / ("holes%s.txt" % suffix)
                command += ["-output", str(out)]
            command.append(str(ucdb))
            proc = subprocess.run(command, capture_output=True, text=True,
                                  timeout=timeout)
            last = (proc.stderr or "").strip().splitlines()
            if proc.returncode != 0 or (summary and not proc.stdout.strip()) \
                    or (out is not None and not out.is_file()):
                print("warning: `vcover report %s` failed (exit %d): %s"
                      % (" ".join(options), proc.returncode,
                         last[-1] if last else "no output"))
                continue
            text = proc.stdout if summary else out.read_text()
            if summary:
                totals.update(parse_summary_report(text))
            else:
                details.append(text)
        return "\n".join(details), totals
    finally:
        if owned:
            shutil.rmtree(work_dir, ignore_errors=True)


def write_holes_csv(path, holes, source_note):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        handle.write("# source: %s\n" % source_note)
        writer = csv.DictWriter(handle, fieldnames=COLUMNS,
                                quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
        writer.writeheader()
        for hole in holes:
            writer.writerow(hole.row())
    return len(holes)


def write_by_du_csv(path, holes):
    per_du = OrderedDict()
    for hole in holes:
        key = (hole.du, hole.metric)
        per_du[key] = per_du.get(key, 0) + 1
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle, quoting=csv.QUOTE_MINIMAL,
                            lineterminator="\r\n")
        writer.writerow(["Design Unit", "Metric", "Missed Bins"])
        for (du, metric), count in per_du.items():
            writer.writerow([du, metric, count])
    return len(per_du)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Extract unwaived code-coverage holes from a merged .ucdb.")
    parser.add_argument("--ucdb", default=str(DEFAULT_UCDB),
                        help="merged coverage database")
    parser.add_argument("--instance", default=DEFAULT_INSTANCE,
                        help="DUT scope (default: the uvmt COV_INSTANCE)")
    parser.add_argument("--cov-tcl", default=str(REPO / "sim" / "tools" / "vsim" / "cov.tcl"),
                        help="recorded in the output header as the waiver source")
    parser.add_argument("--report", default=None,
                        help="re-parse this saved vcover details report instead of running vcover")
    parser.add_argument("--apply-cov-tcl", action="store_true",
                        help="apply --cov-tcl in a vsim -viewcov session first, so the "
                             "holes reflect the exclusions file as it is now rather than "
                             "as it was when the .ucdb was saved (needs a licence)")
    parser.add_argument("--summary-report", default=None,
                        help="saved `vcover report -summary` text for the cross-check")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="holes CSV to write")
    parser.add_argument("--by-du", default=str(DEFAULT_BY_DU),
                        help="per-design-unit rollup CSV to write")
    parser.add_argument("--work-dir", default=None,
                        help="where to keep the generated Tcl driver and reports")
    parser.add_argument("--summary", action="store_true",
                        help="print the per-metric totals to stdout")
    parser.add_argument("--timeout", type=int, default=900,
                        help="seconds for the vcover invocations")
    args = parser.parse_args(argv)

    totals = {}
    if args.report:
        text = Path(args.report).read_text()
        source_note = "saved vcover report %s" % repo_relative(args.report)
        if args.summary_report:
            totals = parse_summary_report(Path(args.summary_report).read_text())
    else:
        ucdb = Path(args.ucdb)
        if not ucdb.is_file():
            raise SystemExit("error: no merged coverage database at %s -- run a "
                             "coverage regression first (docs/coverage/README.md)"
                             % ucdb)
        if args.apply_cov_tcl:
            work_dir = Path(args.work_dir) if args.work_dir else None
            if work_dir is None:
                work_dir = Path(tempfile.mkdtemp(prefix="covholes."))
            work_dir.mkdir(parents=True, exist_ok=True)
            text, totals = generate_report_with_cov_tcl(
                ucdb, args.instance, args.cov_tcl, args.timeout, work_dir)
            source_note = ("%s with %s applied in vsim -viewcov (report-only "
                           "session; the .ucdb is not modified)"
                           % (repo_relative(ucdb), repo_relative(args.cov_tcl)))
        else:
            text, totals = generate_report(ucdb, args.instance, args.timeout)
            source_note = ("vcover report -details -annotate -below 100 -code bcsf "
                           "-assert -instance=%s. %s; %s exclusions as saved in the .ucdb"
                           % (args.instance, repo_relative(ucdb),
                              Path(args.cov_tcl).name))

    holes, _per_du_rollups = parse_holes_report(text)
    if totals:
        for problem in cross_check(holes, totals):
            print("error: %s -- this list is not the whole hole set" % problem)
    else:
        print("warning: no global rollup to cross-check the %d holes against"
              % len(holes))
    print("Found %d unwaived holes (%s)" % (len(holes), source_note))
    total = write_holes_csv(args.out, holes, source_note)
    groups = write_by_du_csv(args.by_du, holes)
    print("Wrote %s (%d rows) and %s (%d design-unit/metric rows)"
          % (repo_relative(args.out), total, repo_relative(args.by_du), groups))

    if args.summary:
        by_metric = {}
        for hole in holes:
            by_metric[hole.metric] = by_metric.get(hole.metric, 0) + 1
        print("\nUnwaived holes by metric:")
        for metric in sorted(by_metric):
            key = METRIC_ROLLUP.get(metric, metric)
            row = totals.get(key)
            note = " (summary: %d misses of %d active)" % (row[2], row[0]) if row else ""
            print("  %-10s %3d%s" % (metric, by_metric[metric], note))
        print("\nBy design unit:")
        per_du = {}
        for hole in holes:
            per_du[hole.du] = per_du.get(hole.du, 0) + 1
        for du in sorted(per_du, key=lambda k: (-per_du[k], k)):
            print("  %-26s %3d" % (du, per_du[du]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
