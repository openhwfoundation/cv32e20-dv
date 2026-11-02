#!/usr/bin/env python3
# Copyright (c) 2026 Eclipse Foundation
# SPDX-License-Identifier: Apache-2.0 WITH SHL-2.1
"""Audit every ``coverage exclude`` in sim/tools/vsim/cov.tcl against a live .ucdb.

Why this exists
---------------
``coverage exclude`` accepts a target that matches nothing and says so in no
way at all: the command succeeds, the run succeeds, and the dead code the
author meant to waive stays in the report as an open miss while -- far worse --
a -linerange that drifted onto live code silently deletes *covered* coverage
from the metric. cov.tcl's own header records several of these
("several exclusions here were silently pointing two lines off their intended
target"). RTL line numbers drift every time the vendored core is updated, so
this needs to be a measurement, not a note to be careful about.

The measurement
---------------
The session first applies *every* exclusion the current cov.tcl contains, and
only then lifts them one at a time. Both halves matter:

A merged .ucdb carries the exclusions of the cov.tcl that was in force when the
tests were compiled -- and nothing else. Re-aim a waiver in the file and the
database still does not know about it, so lifting it would clear an exclusion it
never had and report the re-aimed waiver as a no-op. Applying the file first
measures the file a user actually runs (re-applying what the .ucdb already
carries is idempotent). Then, for each waiver, ``coverage exclude ... -clear``
lifts one and the report says what came *back*.

    bins came back    -> the waiver was excluding something: it aims at a real
                         bin.
    nothing came back -> the waiver excludes nothing. Either the RTL moved or
                         the target was never excludable (wrong -du, wrong
                         state-variable name).
    hits came back    -> the waiver was hiding *covered* code. The metric was
                         being computed without bins that the suite actually
                         reaches, which understates real coverage.

Each waiver is measured in a fresh ordering position against the same baseline,
then re-applied, so one waiver's verdict cannot depend on the previous one.

Usage
-----
    bin/coverage_waiver_audit.py                     # audit, write the CSV
    bin/coverage_waiver_audit.py --parse-only        # no Questa: parse cov.tcl only
    bin/coverage_waiver_audit.py --ucdb path/to/merged.ucdb --out sheet.csv

``--parse-only`` needs no simulator and no licence; it is what the CI unit tests
exercise. The measurement pass needs vsim (a licence) and Questa's ``-viewcov``,
and refuses to run without sim/tools/vsim/cov.tcl.
"""

import argparse
import csv
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_COV_TCL = REPO / "sim" / "tools" / "vsim" / "cov.tcl"
DEFAULT_UCDB = (REPO / "sim" / "uvmt" / "vsim_results" / "default"
                / "merged" / "merged.ucdb")
DEFAULT_OUT = REPO / "docs" / "coverage" / "raw" / "waiver_audit.csv"

# One `coverage exclude` per line in cov.tcl; -comment arguments are the only
# place a brace can appear, and no target list spans lines.
EXCLUDE_RE = re.compile(r"^\s*(#?\s*)coverage\s+exclude\b(.*)$")
SET_RE = re.compile(r"^\s*set\s+([A-Za-z_][A-Za-z0-9_]*)\s+(.*?)\s*$")
GATE_RE = re.compile(r"^\s*if\s*\{\s*!\$([A-Za-z_][A-Za-z0-9_]*)\s*\}\s*\{?\s*$")

METRIC_FLAGS = ("-ftrans", "-fstate", "-fsamestate", "-finitial", "-fcontains",
                "-feccondrow", "-fecexprrow", "-udpcondrow", "-udpexprrow",
                "-linerange", "-togglenode", "-cvgpath", "-dirpath", "-assertpath")

# Classification of one waiver, from the measured deltas.
VALID = "VALID"
MIS_AIMED = "MIS-AIMED"
NO_OP = "NO-OP"
HIDING_COVERED_CODE = "HIDING-COVERED-CODE"
NOT_INSTRUMENTED = "NOT-INSTRUMENTED"
DISABLED = "DISABLED"
GATED_OFF = "GATED-OFF"

# The hole metrics (as bin/coverage_holes.py names them) that each exclusion
# metric is supposed to cover, for the MIS-AIMED cross-check.
HOLE_METRICS = {
    "statement": ("stmt",),
    "branch": ("branch",),
    "condition": ("condition",),
    "fec": ("condition",),
    "fsm": ("fsm",),
    "fsm-state": ("fsm",),
    "fsm-trans": ("fsm",),
    "toggle": ("toggle",),
    "assertion": ("assertion",),
    "all-on-line": ("stmt", "branch", "condition", "fsm"),
    "du": ("stmt", "branch", "condition", "fsm", "assertion"),
}


class Exclusion:
    """One `coverage exclude` statement, with the context needed to re-run it.

    ``args`` is the argument string exactly as written (less the leading
    ``coverage exclude``), so the audit can hand it back to vsim verbatim --
    the whole point is to measure the line in the file, not a paraphrase of it.
    """

    def __init__(self, lineno, du, metric, targets, comment, gate, enabled,
                 args, comment_var=""):
        self.lineno = lineno
        self.du = du
        self.metric = metric
        self.targets = targets
        self.comment = comment
        self.comment_var = comment_var
        self.gate = gate
        self.enabled = enabled
        self.args = args

    def label(self):
        if self.metric in ("fsm-trans", "fsm-state", "fec", "toggle", "cvg",
                           "assertion"):
            return self.targets
        return self.targets or "(whole design unit)"


def _split_args(text):
    """Split a Tcl argument string on whitespace, honouring {braced} and "quoted".

    Braces nest (a -comment can contain them); backslash escapes are kept
    verbatim because cov.tcl uses none and re-emitting them unchanged is what
    the audit needs.
    """
    out, token, i, depth, quote = [], "", 0, 0, None
    while i < len(text):
        ch = text[i]
        if quote:
            token += ch
            if ch == quote:
                quote = None
        elif ch == "{":
            depth += 1
            token += ch
        elif ch == "}":
            depth -= 1
            token += ch
        elif ch in "\"'":
            quote = ch
            token += ch
        elif ch.isspace() and depth == 0:
            if token:
                out.append(token)
                token = ""
        else:
            token += ch
        i += 1
    if token:
        out.append(token)
    return out


def _brace_value(value):
    """Unwrap a Tcl `{...}`/`"..."` word; return the text either way."""
    value = value.strip()
    if len(value) >= 2 and value[0] == "{" and value[-1] == "}":
        return value[1:-1].strip()
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1]
    return value


def _metric_of(tokens):
    """Map an exclusion's flags onto the coverage metric it targets."""
    flags = {t for t in tokens if t.startswith("-")}
    if "-code" in flags:
        idx = tokens.index("-code")
        code = tokens[idx + 1] if idx + 1 < len(tokens) else ""
        if "b" in code:
            return "branch"
        if "c" in code:
            return "condition"
        if "s" in code:
            return "statement"
        if "f" in code:
            return "fsm"
        if "t" in code:
            return "toggle"
    if flags & {"-ftrans"}:
        return "fsm-trans"
    if flags & {"-fstate", "-fsamestate", "-finitial", "-fcontains"}:
        return "fsm-state"
    if flags & {"-feccondrow", "-fecexprrow", "-udpcondrow", "-udpexprrow"}:
        return "fec"
    if "-togglenode" in flags:
        return "toggle"
    if "-cvgpath" in flags:
        return "cvg"
    if flags & {"-assertpath", "-dirpath"}:
        return "assertion"
    if "-linerange" in flags:
        # Unscoped -linerange asks Questa for every coverage type on the line.
        return "all-on-line"
    return "du"


def _targets_of(tokens, metric):
    """The interesting part of the argument list for a human reviewing a sheet.

    Line ranges and FSM transitions are the identity of a waiver, so those are
    what gets a column; the -comment is a separate field.
    """
    if metric in ("fsm-trans", "fsm-state"):
        idx = tokens.index("-ftrans") if "-ftrans" in tokens else None
        if idx is None:
            for flag in ("-fstate", "-fsamestate", "-finitial", "-fcontains"):
                if flag in tokens:
                    idx = tokens.index(flag)
                    break
        if idx is not None:
            rest = tokens[idx + 1:]
            stop = next((n for n, t in enumerate(rest) if t.startswith("-")),
                        len(rest))
            return " ".join(rest[:stop]).replace("{", "").replace("}", "")
    if metric == "fec":
        for flag in ("-feccondrow", "-fecexprrow", "-udpcondrow", "-udpexprrow"):
            if flag in tokens:
                idx = tokens.index(flag)
                rest = tokens[idx + 1:]
                stop = next((n for n, t in enumerate(rest) if t.startswith("-")),
                            len(rest))
                return ("%s %s" % (flag.lstrip("-"), " ".join(rest[:stop]))).strip()
    if "-linerange" in tokens:
        idx = tokens.index("-linerange")
        rest = tokens[idx + 1:]
        stop = next((n for n, t in enumerate(rest) if t.startswith("-")),
                    len(rest))
        return " ".join(rest[:stop])
    if "-cvgpath" in tokens or "-assertpath" in tokens or "-dirpath" in tokens:
        for flag in ("-cvgpath", "-assertpath", "-dirpath"):
            if flag in tokens:
                idx = tokens.index(flag)
                return tokens[idx + 1] if idx + 1 < len(tokens) else ""
    return ""


def parse_cov_tcl(path):
    """Return (exclusions, variables, gates) for a cov.tcl.

    Every ``coverage exclude`` line becomes an Exclusion, including the four
    commented-out "To review" ones (``enabled=False``: they exclude nothing today
    and a reviewer needs to see that they still exclude nothing). ``gate`` is the
    enclosing ``if {!$VAR}`` variable, whose value decides whether the statement
    ever runs.
    """
    text = Path(path).read_text()
    exclusions = []
    variables = {}
    gates = []
    gate_stack = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("##"):
            continue
        gate = GATE_RE.match(line)
        if gate:
            gate_stack.append(gate.group(1))
            gates.append({"variable": gate.group(1), "lineno": lineno,
                          "opened": True})
            continue
        if re.match(r"^\s*\}\s*$", line) and gate_stack:
            gate_stack.pop()
            continue
        setter = SET_RE.match(line)
        if setter:
            variables[setter.group(1)] = _brace_value(setter.group(2))
            continue
        found = EXCLUDE_RE.match(line)
        if not found:
            continue
        enabled = not found.group(1).strip().startswith("#")
        body = found.group(2)
        comment = ""
        comment_var = ""
        # Peel -comment (always last in this file) before splitting targets.
        comment_match = re.search(r"-comment\s+(\$?[A-Za-z_][A-Za-z0-9_]*|\{.*\}\S*)\s*$",
                                  body)
        if comment_match:
            raw = comment_match.group(1)
            body = body[:comment_match.start()].rstrip()
            if raw.startswith("$"):
                comment_var = raw[1:]
                comment = variables.get(comment_var, raw)
            else:
                comment = _brace_value(raw)
        tokens = _split_args(body)
        du = ""
        if "-du" in tokens:
            idx = tokens.index("-du")
            du = tokens[idx + 1] if idx + 1 < len(tokens) else ""
        metric = _metric_of(tokens)
        exclusions.append(Exclusion(
            lineno=lineno, du=du, metric=metric,
            targets=_targets_of(tokens, metric), comment=comment,
            comment_var=comment_var,
            gate=gate_stack[-1] if gate_stack else "",
            enabled=enabled, args=body.strip()))
    for name in list(variables):
        variables[name] = variables[name].strip()
    return exclusions, variables, gates


def gate_is_active(gate, variables):
    """cov.tcl gates are `if {!$VAR}`: the block runs when the variable is 0."""
    if not gate:
        return True
    value = variables.get(gate)
    if value is None:
        return True
    return value.strip() in ("0", "false", "off", "")


def _report_counts(report_text):
    """Pull bins/hits/misses out of one `coverage report` text report.

    Questa prints one row per coverage type; a design-unit report looks like

        Branches    92   75   17   81.52%
        Statements 182  173    9   95.05%

    A waiver of one metric must not be judged on another metric's row, so
    everything is kept and the caller picks.
    """
    rows = {}
    total = None
    for line in report_text.splitlines():
        match = re.match(r"^\s*([A-Za-z][A-Za-z /]*?)\s+"
                         r"(\d+)\s+(\d+)\s+(\d+)\s+[\d.]+%\s*$", line)
        if match:
            name = match.group(1).strip().lower().replace(" ", "_")
            rows[name] = (int(match.group(2)), int(match.group(3)),
                          int(match.group(4)))
            continue
        overall = re.match(r"^\s*Total Coverage By Design Unit[^:]*:\s*([\d.]+)%",
                           line)
        if overall:
            total = float(overall.group(1))
    return rows, total


# Questa's report row name for each metric this tool can measure.
REPORT_ROWS = {
    "statement": ("statements",),
    "branch": ("branches",),
    "condition": ("conditions",),
    "fec": ("conditions",),
    "fsm": ("fsm_states", "fsm_transitions"),
    "fsm-state": ("fsm_states",),
    "fsm-trans": ("fsm_transitions",),
    "assertion": ("assertions",),
    "toggle": ("toggles",),
    "all-on-line": ("statements", "branches", "conditions"),
    "du": ("statements", "branches", "conditions", "fsm_states",
           "fsm_transitions", "assertions"),
}


def _metric_delta(before, after, metric):
    """Summed (bins, hits, misses) delta across the report rows a metric covers."""
    keys = REPORT_ROWS.get(metric)
    if keys is None:
        keys = tuple(set(before) | set(after))
    delta = [0, 0, 0]
    touched = False
    for key in keys:
        if key not in before and key not in after:
            continue
        touched = True
        b = before.get(key, (0, 0, 0))
        a = after.get(key, (0, 0, 0))
        for i in range(3):
            delta[i] += a[i] - b[i]
    return tuple(delta) if touched else (0, 0, 0)


def classify(exclusion, delta, variables, holes=(), instrumented=True):
    """Verdict for one waiver, from what lifting it brought back.

    ``delta`` is (bins, hits, misses) counted with the waiver lifted minus the
    same counts with it applied, i.e. what the waiver actually removes:

    ``(0, 0, 0)``   it excludes nothing at all. If the design unit still has an
                    open hole of this metric, then the dead code the -comment
                    describes is sitting in the report unwaived and the waiver
                    is aimed at the wrong line (MIS-AIMED); otherwise it is a
                    plain NO-OP -- or the whole design unit is outside the
                    instrumented scope, which is a different fact entirely.
    ``hits > 0``    lifting it brought back *covered* code and not one miss: the
                    waiver was deleting achieved coverage from the metric.
    ``misses > 0``  the waiver removes the misses it was written for. A waiver
                    that also loses a covered sibling bin (Questa excludes a
                    line's branch bins as one unit, with no per-arm granularity)
                    is still a valid waiver -- the Delta Hits column is where a
                    reviewer sees what that coarseness costs.

    An FEC-row waiver reports no bin of its own and turns one of the condition's
    counted items from missed into covered when it is lifted, which is why
    nothing here may test the three counters in isolation.
    """
    if not exclusion.enabled:
        return DISABLED
    if not gate_is_active(exclusion.gate, variables):
        return GATED_OFF
    bins, hits, misses = delta
    if bins == 0 and hits == 0 and misses == 0:
        if holes:
            return MIS_AIMED
        return NOT_INSTRUMENTED if not instrumented else NO_OP
    if hits > 0 and misses == 0:
        return HIDING_COVERED_CODE
    return VALID


def load_open_holes(path):
    """{design unit: {hole metric}} from bin/coverage_holes.py's holes.csv.

    Lets a waiver that merely does nothing be told apart from one aimed at the
    wrong line: the first has nothing left to hide in its own design unit, the
    second still leaves its own dead code in the report.
    """
    path = Path(path)
    if not path.is_file():
        return {}
    out = {}
    with open(path, newline="", encoding="utf-8-sig") as handle:
        rows = csv.DictReader(line for line in handle if not line.startswith("#"))
        for row in rows:
            du = (row.get("Design Unit") or "").strip()
            metric = (row.get("Metric") or "").strip()
            if du and metric:
                out.setdefault(du, set()).add(metric)
    return out


def open_holes_for(exclusion, holes_by_du):
    """The open holes in this waiver's design unit that it should have covered."""
    metrics = HOLE_METRICS.get(exclusion.metric)
    if not metrics or not exclusion.du:
        return ()
    return tuple(sorted(set(holes_by_du.get(exclusion.du, set()))
                        & set(metrics)))


def _tcl_quote(text):
    return "{" + text.replace("{", "").replace("}", "").replace("]", "") + "}"


# Every command of the driver runs through covtry: a `coverage exclude` whose
# target does not parse at all (an unknown option, an unknown FSM variable) is a
# Tcl *error*, and an uncaught error in a -do script aborts the session -- which
# cost a whole audit run's reports once. A waiver that merely matches nothing is
# not an error, and stays exactly as silent as it always was.
TCL_PROLOGUE = """proc covtry {label code} {
    if {[catch {uplevel 1 $code} err]} {
        puts "CMDFAIL $label : $err"
    }
}
"""


def apply_all_lines(exclusions, variables):
    """covtry-wrapped `coverage exclude` for every statement that is in force.

    Shared with bin/coverage_holes.py: the holes list has to be extracted under
    the *current* cov.tcl for the same reason the audit does -- see the module
    docstring.
    """
    return ["covtry apply-e%03d {coverage exclude %s -comment %s}"
            % (index + 1, excl.args, _tcl_quote("audit-apply"))
            for index, excl in enumerate(exclusions)
            if excl.enabled and gate_is_active(excl.gate, variables)]


def build_driver_tcl(exclusions, work_dir, variables, timeout):
    """Write the one-at-a-time Tcl driver and return (script path, report map).

    Per waiver: report, lift the waiver, report, re-apply it. Re-applying keeps
    the ordering of the measurement irrelevant to every later verdict, which is
    what makes a single vsim session safe for 60+ experiments.
    """
    script = Path(work_dir) / "waiver_audit.tcl"
    lines = [TCL_PROLOGUE]
    lines += apply_all_lines(exclusions, variables)
    report_map = []
    for index, excl in enumerate(exclusions):
        tag = "e%03d" % (index + 1)
        before = Path(work_dir) / ("%s_before.txt" % tag)
        after = Path(work_dir) / ("%s_after.txt" % tag)
        report_map.append((tag, before, after))
        active = excl.enabled and gate_is_active(excl.gate, variables)
        scope = "-du=%s " % excl.du if excl.du else ""
        report = "coverage report %s-code bcsf -output {%s}"
        lines.append("covtry %s-before {%s}" % (tag, report % (scope, before)))
        if active:
            lines.append("covtry %s-lift {coverage exclude %s -clear}"
                         % (tag, excl.args))
            lines.append("covtry %s-after {%s}" % (tag, report % (scope, after)))
            lines.append("covtry %s-reapply {coverage exclude %s -comment %s}"
                         % (tag, excl.args, _tcl_quote("audit-reapply")))
        else:
            # Nothing to lift: measure the same state twice so the delta is
            # exactly zero and the verdict comes from classify() unchanged.
            lines.append("covtry %s-after {%s}" % (tag, report % (scope, after)))
    script.write_text("\n".join(lines) + "\nexit -f\n")
    return script, report_map


def run_audit(exclusions, ucdb, variables, timeout=1800, work_dir=None,
              keep_work=False, holes_by_du=None):
    """Measure every waiver; returns {index: (classification, delta)}."""
    ucdb = Path(ucdb).resolve()
    if not ucdb.is_file():
        raise SystemExit("error: no merged coverage database at %s -- run a "
                         "coverage regression first (see docs/coverage/README.md)"
                         % ucdb)
    vsim = shutil.which("vsim")
    if vsim is None:
        raise SystemExit("error: vsim not on PATH -- set up Questa first "
                         "(docs/coverage/README.md); --parse-only needs neither")
    owned = work_dir is None
    # Absolute, because the vsim session below runs with this directory as its
    # cwd: a relative report path would be resolved against it twice and every
    # report would then read back as missing (which classify() reports as a
    # NO-OP, i.e. exactly the wrong answer).
    work_dir = (Path(tempfile.mkdtemp(prefix="waiver_audit.")) if owned
                else Path(work_dir)).resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    script, report_map = build_driver_tcl(exclusions, work_dir, variables,
                                          timeout)
    command = [vsim, "-c", "-viewcov", str(ucdb), "-do", str(script)]
    print("Measuring %d waivers in %s ..." % (len(exclusions), ucdb))
    try:
        proc = subprocess.run(command, cwd=str(work_dir), capture_output=True,
                              text=True, timeout=timeout)
        output = (proc.stdout or "") + (proc.stderr or "")
        # Questa reports an unknown FSM variable or an unmatched line range as a
        # note, not an error; anything else here is worth showing the operator,
        # and covtry's own markers say which command of the driver was refused.
        for noise in sorted(set(re.findall(r"CMDFAIL [^\n]*", output)))[:20]:
            print("  vsim: %s" % noise)
        for noise in sorted(set(re.findall(r"\*\* (?:Error|Warning):[^\n]*",
                                            output)))[:20]:
            print("  vsim: %s" % noise)
        holes_by_du = holes_by_du or {}
        results = {}
        for index, (_tag, before, after) in enumerate(report_map):
            if not before.is_file() or not after.is_file():
                results[index] = (NO_OP, (0, 0, 0))
                continue
            b_rows, _ = _report_counts(before.read_text())
            a_rows, _ = _report_counts(after.read_text())
            excl = exclusions[index]
            delta = _metric_delta(b_rows, a_rows, excl.metric)
            results[index] = (classify(excl, delta, variables,
                                       open_holes_for(excl, holes_by_du),
                                       instrumented=bool(b_rows)),
                              delta)
        return results
    finally:
        if owned and not keep_work:
            shutil.rmtree(work_dir, ignore_errors=True)


COLUMNS = ["ID", "Source Line", "Design Unit", "Metric", "Target",
           "Config Gate", "Waiver Status", "Delta Bins", "Delta Hits",
           "Delta Misses", "Waiver Comment"]


def write_audit_csv(path, exclusions, results, variables):
    rows = []
    for index, excl in enumerate(exclusions):
        if results is None:
            status, delta = (DISABLED if not excl.enabled
                             else (GATED_OFF
                                   if not gate_is_active(excl.gate, variables)
                                   else "unmeasured")), (0, 0, 0)
        else:
            status, delta = results[index]
        rows.append({
            "ID": "W%03d" % (index + 1),
            "Source Line": "cov.tcl:%d" % excl.lineno,
            "Design Unit": excl.du,
            "Metric": excl.metric,
            "Target": excl.targets,
            "Config Gate": ("%s=%s" % (excl.gate, variables.get(excl.gate, "?"))
                            if excl.gate else "none"),
            "Waiver Status": status,
            "Delta Bins": delta[0],
            "Delta Hits": delta[1],
            "Delta Misses": delta[2],
            "Waiver Comment": excl.comment,
        })
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, quoting=csv.QUOTE_MINIMAL,
                                lineterminator="\r\n")
        writer.writeheader()
        writer.writerows(rows)
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Audit cov.tcl's coverage exclusions against a live .ucdb.")
    parser.add_argument("--cov-tcl", default=str(DEFAULT_COV_TCL),
                        help="the exclusions file (default: sim/tools/vsim/cov.tcl)")
    parser.add_argument("--ucdb", default=str(DEFAULT_UCDB),
                        help="merged coverage database to audit against")
    parser.add_argument("--out", default=str(DEFAULT_OUT),
                        help="CSV to write (default: docs/coverage/raw/waiver_audit.csv)")
    parser.add_argument("--holes",
                        default=str(REPO / "docs" / "coverage" / "raw" / "holes.csv"),
                        help="holes CSV from bin/coverage_holes.py, used to tell a "
                             "waiver that excludes nothing from one aimed at the "
                             "wrong line (missing file: no cross-check)")
    parser.add_argument("--work-dir", default=None,
                        help="keep the driver script and Questa reports here")
    parser.add_argument("--timeout", type=int, default=1800,
                        help="seconds for the whole vsim session")
    parser.add_argument("--parse-only", action="store_true",
                        help="parse cov.tcl and write the CSV with no Questa run")
    parser.add_argument("--keep-work", action="store_true",
                        help="leave the temporary work directory in place")
    args = parser.parse_args(argv)

    cov_tcl = Path(args.cov_tcl)
    if not cov_tcl.is_file():
        # The same guard run_tests.py warns about: no cov.tcl means the
        # simulation ran with no exclusions and every number below is moot.
        raise SystemExit("error: %s not found -- exclusions are applied from "
                         "that file, so there is nothing to audit" % cov_tcl)

    exclusions, variables, _gates = parse_cov_tcl(cov_tcl)
    active = [e for e in exclusions if e.enabled
              and gate_is_active(e.gate, variables)]
    print("Parsed %d exclusions from %s (%d currently active, %d commented out)"
          % (len(exclusions), cov_tcl, len(active),
             sum(1 for e in exclusions if not e.enabled)))

    results = None
    if not args.parse_only:
        holes_by_du = load_open_holes(args.holes)
        if holes_by_du:
            print("Cross-checking against %d design units with open holes (%s)"
                  % (len(holes_by_du), args.holes))
        results = run_audit(exclusions, args.ucdb, variables,
                            timeout=args.timeout, work_dir=args.work_dir,
                            keep_work=args.keep_work,
                            holes_by_du=holes_by_du)
    rows = write_audit_csv(args.out, exclusions, results, variables)
    print("Wrote %s" % args.out)
    if results is not None:
        tally = {}
        for status, _delta in results.values():
            tally[status] = tally.get(status, 0) + 1
        for status in sorted(tally):
            print("  %-22s %d" % (status, tally[status]))
        suspects = [(rows[i]["ID"], rows[i]["Source Line"], rows[i]["Design Unit"],
                     rows[i]["Metric"], rows[i]["Target"], results[i][0])
                    for i in range(len(exclusions))
                    if results[i][0] in (NO_OP, MIS_AIMED, HIDING_COVERED_CODE,
                                         NOT_INSTRUMENTED)]
        if suspects:
            print("\nWaivers that need re-aiming:")
            for row in suspects:
                print("  %-5s %-16s %-22s %-12s %-28s %s" % row)
        else:
            print("\nAll active waivers measurably exclude their intended target.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
