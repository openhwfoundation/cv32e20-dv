#!/usr/bin/env python3
# Copyright (c) 2026 Eclipse Foundation
# SPDX-License-Identifier: Apache-2.0 WITH SHL-2.1
"""Build the one coverage review sheet out of the two raw dumps.

Inputs (both produced by this directory, both published under
docs/coverage/raw/ so a reviewer can re-check a verdict without Questa):

  * ``waiver_audit.csv`` -- bin/coverage_waiver_audit.py: every ``coverage
    exclude`` in sim/tools/vsim/cov.tcl, with what lifting it in a live
    .ucdb actually changed.
  * ``holes.csv`` -- bin/coverage_holes.py: every bin still missed *with those
    exclusions in force*, i.e. what a developer sees as open.
  * ``holes_parked.csv`` -- the same export run against the including-parked
    merged database. Optional (a tree without that database builds the old
    sheet), but when it exists it is what tells a hole the parked tests cover
    -- a stimulus gap of the default set -- from a hole nothing in the
    repository covers.

Output: docs/coverage/coverage_review.csv -- one row per waiver and per hole,
the measured facts from the dumps first, then the triage the plan of record
asks for: is this coverable as things stand (A), does it need a new test (B),
should it be waived (C), or is the waiver itself broken (D).

Everything in the sheet is derived: rerun this after either dump and the file
is the same shape, so the triage rules below are the reviewable thing, not a
spreadsheet someone typed once. Reviewer, Review Date and Notes come out empty
for a human to fill in, and no cell ever contains a newline, so the file opens
as one clean table in Excel and in Google Sheets.

Usage
-----
    bin/coverage_review.py                      # write the sheet
    bin/coverage_review.py --summary            # and print the tally
    bin/coverage_review.py --out /tmp/sheet.csv

Triage rules
------------
A waiver's classification comes from *why* it exists, read off the measured
row, in this order:

  * a comment about mid-run reset injection => B-new-test / reset-injection.
    These are not dead code and are not accepted as permanently untestable:
    ``rst_ni`` is a real asynchronous input, so the transition is reachable
    and the answer is a reset-injection test (mid_run_reset_test). The waiver
    stays until the merged database covers the transition, because deleting it
    first would just lower the reported number.
  * an inactive-config gate (``BusErrSupported`` / ``UmodeEnabled`` / ``RVB``
    / ``XInterface``) => C-waive / config-disabled. The RTL is not in the
    design being verified.
  * a comment saying the code only exists for the simulation (RVFI plumbing,
    the tracer, the simutil stubs) => C-waive / sim-only.
  * a waiver that measures NOT-INSTRUMENTED => C-waive / sim-only. It excludes
    nothing because its design unit is outside the instrumented scope; it is
    documentation, and the audit is what proves that.
  * everything else => C-waive / dead-code, which is what the -comment argues.

A hole is keyed by design unit, metric and target, because the verdict is a
statement about that specific RTL construct and nothing else: an unlisted hole
comes out ``open`` with no classification, which is the tool admitting it has
not been thought about rather than guessing. The one measured exception is the
including-parked evidence: a hole the parked merge covers is stimulus the
repository already has but the default scope does not run -- ``B-new-test`` /
``stimulus-gap``, to be closed by promoting or repairing that stimulus, not by
a waiver. A hole that survives both dumps stays open however the tool's rules
feel about it.
"""

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

REPO = Path(__file__).resolve().parents[1]
DEFAULT_WAIVERS = REPO / "docs" / "coverage" / "raw" / "waiver_audit.csv"
DEFAULT_HOLES = REPO / "docs" / "coverage" / "raw" / "holes.csv"
DEFAULT_PARKED_HOLES = REPO / "docs" / "coverage" / "raw" / "holes_parked.csv"
DEFAULT_COV_TCL = REPO / "sim" / "tools" / "vsim" / "cov.tcl"
DEFAULT_OUT = REPO / "docs" / "coverage" / "coverage_review.csv"

# The tests this plan of record adds. A row that names one of these is waiting
# on stimulus; tests/programs/custom/<name>/ is where it lives.
MID_RUN_RESET_TEST = "mid_run_reset_test"
IRQ_SINGLE_CYCLE_TEST = "irq_single_cycle_test"

# The status strings bin/coverage_waiver_audit.py writes.
NOT_INSTRUMENTED = "NOT-INSTRUMENTED"

# A waiver whose own comment says the target is reachable and merely untested
# by reset timing is a stimulus gap, not dead code.
RESET_INJECTION_MARKERS = ("mid-run reset injection",)

# ... and one that says the code exists for the simulator does not belong to
# the DUT's coverage at all.
SIM_ONLY_MARKERS = ("RVFI", "simutil_get_scramble", "Simulation-only",
                    "sim-only", "disassembler")

# cov.tcl's `if {!$VAR}` gates: a waiver under one of these is a statement
# about the configuration, not about the RTL.
CONFIG_GATES = ("BusErrSupported", "UmodeEnabled", "RVB", "XInterface")

COLUMNS = ["ID", "Type", "Design Unit", "Metric", "Target", "cov.tcl Line",
           "Hits", "Misses", "Coverage %", "Config Gate", "Waiver Status",
           "Classification", "Rationale Category", "Justification",
           "Proposed Test", "Proposed cov.tcl Exclusion", "Status", "Reviewer",
           "Review Date", "Notes"]

# Metric => the code-metric letter Questa wants in a re-aimed exclusion.
METRIC_CODE_FLAG = {"stmt": "s", "branch": "b", "condition": "c",
                    "fsm": "f", "assertion": "a"}

# Holes that have been triaged, keyed by (design unit, metric, name). The name
# is the line for a code hole and the assertion's own name for an assertion
# hole, i.e. the two things that survive a re-export. Each entry is the verdict
# plus the argument it rests on; docs/coverage/coverage_review.md holds the
# longer version of the same reasoning.
HOLE_TRIAGE = {
    ("cve2_controller", "branch", "514"): {
        "classification": "B-new-test",
        "category": "stimulus-gap",
        "test": IRQ_SINGLE_CYCLE_TEST,
        "justification": (
            "handle_irq is committed by the DECODE->IRQ_TAKEN transition "
            "(cve2_controller.sv:496-498) and sampled again the next cycle in "
            "IRQ_TAKEN (:514); an interrupt source that drops inside that one-cycle "
            "window takes the false arm -- the irq_withdrawn_in_taken case the RTL's "
            "own assertion block (:835-836) exists to describe. Reachable in the "
            "RTL, so it is stimulus, not dead code: waive nothing, direct an "
            "interrupt withdrawal at the window instead. MEASURED CLOSED: "
            "irq_single_cycle_test runs the bound injector "
            "(tb/uvmt/uvmt_cv32e20_irq_single_cycle_injector.sv, "
            "blanking the core's irq bus for exactly one cycle after a commit "
            "edge, +irq_single_cycle +irq_single_cycle_shots=3) and hits the "
            "arm; uvmt_cv32e20_tb.sv's end_of_test fails an armed injector "
            "that never fired, so a PASS is the measurement. The merged-bin "
            "numbers, and why the vendored agent's own clear lands one cycle "
            "after the window closes (its irq_ack is the testbench probe "
            "tb/uvmt/uvmt_cv32e20_dut_wrap.sv:107, not a DUT output), are in "
            "docs/coverage/coverage_review.md and "
            "docs/coverage/raw/phase_c_acceptance.csv."),
    },
    ("cve2_controller", "assertion", "CVE2NoDoubleSpecialReqPCSet"): {
        "classification": "C-waive",
        "category": "dead-code",
        "justification": (
            "Never attempted (pass=0 fail=0): the antecedent needs "
            "seen_exception_pc_set, which is `(seen_exception_pc_set | "
            "exception_pc_set) & ~exception_req_done` (cve2_controller.sv:867), and "
            "every state that performs an exception PC set returns ctrl_fsm_ns to "
            "DECODE in that same cycle (IRQ_TAKEN, DBG_TAKEN_IF and DBG_TAKEN_ID each "
            "end with it), "
            "so exception_req_done (:809) clears it on the very edge it would be set. "
            "A guarded-by-construction safety assertion, not DUT behaviour to cover."),
    },
    ("cve2_id_stage", "assertion", "IllegalInsnStallMustBeMemStall"): {
        "classification": "C-waive",
        "category": "dead-code",
        "justification": (
            "Never attempted (pass=0 fail=0): the antecedent illegal_insn_o & stall_id "
            "needs one instruction that both decodes illegal and asks for a stall, "
            "while stall_id = stall_mem | stall_multdiv | stall_jump | stall_branch | "
            "stall_alu (cve2_id_stage.sv:898-899) is itself qualified by the decode of "
            "a memory/divide/jump/branch/ALU instruction and illegal_insn_o by "
            "illegal_csr_insn_i | illegal_insn_dec (:408). Never once entered across "
            "the 32-test batch, which includes the illegal-instruction and misalign "
            "programs."),
    },
    ("cve2_id_stage", "assertion", "IbexStallIfValidInstrNotExecuting"): {
        "classification": "C-waive",
        "category": "dead-code",
        "justification": (
            "Constant-false antecedent, provable without stimulus: this build has no "
            "writeback stage, so instr_executing is instr_executing_spec "
            "(cve2_id_stage.sv:924) = instr_valid_i & ~instr_fetch_err_i & "
            "controller_run (:923). Substituting that into "
            "`instr_valid_i & ~instr_fetch_err_i & ~instr_executing & controller_run` "
            "is X & ~X, so the property can never be attempted, let alone pass."),
    },
    ("cve2_compressed_decoder", "branch", "260"): {
        "classification": "A-existing-state",
        "category": "stimulus-gap",
        "justification": (
            "Branch item 3'b101 -- the reserved quadrant-2 compressed encoding "
            "sharing the illegal-instruction arm with 3'b001/3'b011/3'b111 "
            "(cve2_compressed_decoder.sv:258-262); the siblings all measure hit "
            "and only this one has never been fetched. The file is unchanged "
            "between the ce0fd917 and d7f2156 pins (empty git diff), and an "
            "earlier database covered the item: this is the accepted "
            "--gen-seed random variance, not RTL -- the current stream "
            "simply never drew that encoding. Coverage by seed luck is not "
            "coverage: extend the directed illegal-compressed sequence "
            "(illegal_instr_test) with the reserved 3'b101 encoding and it "
            "closes deterministically. Not waivable -- the arm is reachable "
            "RTL that a waiver would exclude."),
    },
    }


def read_raw_csv(path, allow_empty=False):
    """Read one of the raw dumps: UTF-8 BOM, CRLF, optional ``# source:`` line.

    allow_empty says a header with no data rows is a result rather than a
    broken export. Only the including-parked hole dump asks for it, because
    there "nothing left open" is itself the finding (load_parked_holes). A file
    with no header row at all is refused either way: an export that wrote
    nothing and a design with no holes left do not state the same thing, and
    reading the first as the second would reclassify every row the dump
    qualified -- silently."""
    path = Path(path)
    if not path.is_file():
        raise SystemExit("error: no %s -- regenerate it first (docs/coverage/README.md)"
                         % path)
    with open(path, newline="", encoding="utf-8-sig") as handle:
        lines = [line for line in handle if not line.startswith("#")]
    if not any(line.strip() for line in lines):
        raise SystemExit("error: %s has no header row -- an export that wrote "
                         "nothing is not a measurement (regenerate it: "
                         "docs/coverage/README.md)" % path)
    rows = list(csv.DictReader(lines))
    if not rows and not allow_empty:
        raise SystemExit("error: %s has no data rows" % path)
    return rows


def _one_line(text):
    """Flatten a -comment for a spreadsheet cell: no newlines, no double spaces."""
    return " ".join((text or "").split())


def _coverage_percent(hits, misses):
    if hits + misses <= 0:
        return ""
    return "%.2f" % (100.0 * hits / (hits + misses))


def _int(text, default=0):
    try:
        return int(text)
    except (TypeError, ValueError):
        return default


def gate_name(config_gate):
    """`UmodeEnabled=0` => `UmodeEnabled`; `none` => `none`."""
    return (config_gate or "").split("=")[0].strip() or "none"


# What the including-parked evidence says a default-scope hole needs: not new
# RTL knowledge, just the stimulus the repository already owns but keeps parked
# (docs/regression.md). Naming the whole set rather than one test is the
# honest reading of the diff -- the parked merge says the family covers it,
# which member does is a question for whoever picks up the lane.
PARKED_STIMULUS_TEST = ("parked set (docs/regression.md): promote or repair "
                        "the parked test that covers it")
# Deliberately undated: this cell is regenerated from the dump on every run, so
# a date written here would silently re-assert the day *this* generation
# happened, not the day the parked database was measured. The date belongs in
# the prose that dates the dump (docs/coverage/coverage_review.md, "Current
# state"), where it cannot outlive its own measurement.
PARKED_STIMULUS_JUSTIFICATION = (
    "MEASURED: the including-parked merge covers this bin (raw/holes_parked.csv) "
    "while the default merge misses it, so the stimulus exists in the repository "
    "-- it is only parked or failing, not missing. Not dead code, not config: "
    "close it by promoting or repairing that stimulus, never by a waiver (a "
    "waiver here would exclude reachable, already-covered-behind-the-toggle "
    "RTL).")


def load_parked_holes(path):
    """Keys still open in the including-parked database, or None when unmeasured.

    Optional on purpose: a checkout without the second merged database builds
    the pre-toggle sheet unchanged. When the dump exists it splits the open
    holes in two: a key still listed is missed by every test in the
    repository, while a key the parked merge dropped from the list is a hole
    only of the default scope -- stimulus the repository has and does not run.

    A header and no rows is the goal state of the whole exercise -- the parked
    merge closed everything the default merge missed -- so it is read as the
    empty set it measures, and said out loud because it reclassifies every hole
    in the sheet. A dump with no header is a truncated export and aborts:
    agreeing with an empty file is the one thing this rule must never do."""
    path = Path(path)
    if not path.is_file():
        return None
    rows = read_raw_csv(path, allow_empty=True)
    if not rows:
        print(f"note: {path} lists no holes: every default-scope hole classes "
              "as a parked-stimulus gap")
    return {hole_key(row) for row in rows}


def triage_waiver(row):
    """(classification, category, proposed test, status) for one audited waiver."""
    comment = row.get("Waiver Comment") or ""
    gate = gate_name(row.get("Config Gate"))
    if any(marker in comment for marker in RESET_INJECTION_MARKERS):
        # Reachable RTL waiting for reset-injection stimulus. The waiver stays
        # in force until the merged database covers the transition.
        return ("B-new-test", "reset-injection", MID_RUN_RESET_TEST, "triaged")
    if gate in CONFIG_GATES:
        return ("C-waive", "config-disabled", "", "waived")
    if row.get("Waiver Status") == NOT_INSTRUMENTED:
        # Nothing to re-aim: the design unit is outside the instrumented scope,
        # so the statement excludes nothing and can only document intent.
        return ("C-waive", "sim-only", "", "triaged")
    if any(marker in comment for marker in SIM_ONLY_MARKERS):
        return ("C-waive", "sim-only", "", "waived")
    return ("C-waive", "dead-code", "", "waived")


def hole_key(row):
    """A hole's identity across dumps: (design unit, metric, name), the name
    being the source line for code and the assertion's own name for
    assertions -- the two things that survive a re-export."""
    name = (row.get("Line") or "").strip()
    if (row.get("Metric") or "") == "assertion":
        name = (row.get("Target") or "").strip().rstrip("/").rsplit("/", 1)[-1]
    return (row.get("Design Unit"), row.get("Metric"), name)


def triage_hole(row, parked_keys=None):
    """The recorded verdict for one open hole, or an untriaged placeholder.

    HOLE_TRIAGE wins when a human argument exists for the key. Otherwise the
    including-parked evidence (when measured) decides: a hole the parked
    merge covered is a stimulus gap of the default scope, classed without a
    waiver. A hole survived by both dumps stays open -- nothing here has
    thought about it, and guessing is what the sheet exists to prevent."""
    key = hole_key(row)
    verdict = HOLE_TRIAGE.get(key)
    if verdict is None:
        if parked_keys is not None and key not in parked_keys:
            return {"classification": "B-new-test",
                    "category": "stimulus-gap",
                    "test": PARKED_STIMULUS_TEST,
                    "justification": PARKED_STIMULUS_JUSTIFICATION,
                    "status": "triaged"}
        return {"classification": "", "category": "", "test": "",
                "justification": "", "status": "open"}
    out = dict(verdict)
    out.setdefault("test", "")
    out["status"] = "triaged"
    return out


def waiver_exclusion(row, exclusion):
    """Rebuild the literal `coverage exclude` line, comment and all.

    The point is that a reviewer can paste it back into cov.tcl after a re-aim,
    so it is regenerated from the parsed statement rather than retyped from the
    sheet.
    """
    if exclusion is None:
        return ""
    line = "coverage exclude %s" % exclusion.args
    comment = _one_line(row.get("Waiver Comment") or exclusion.comment)
    if comment:
        line += " -comment {%s}" % (comment.replace("{", "").replace("}", ""))
    return line


def hole_exclusion(row):
    """The exclusion that *would* waive this hole, if that is the verdict.

    Deliberately not applied by this tool: a hole only gets waived once the
    sheet says so. An assertion is excluded by path because it is a named
    verification object rather than a line of code; everything else by line and
    metric letter, which is the shape every waiver in cov.tcl already uses.

    The assertion form carries no -du on purpose, and neither may one be added:
    measured against the live merged.ucdb in vsim -c -viewcov, "coverage exclude
    -du <unit> -assertpath <path>" silently matches nothing (the assertion miss
    count does not move), while the bare "coverage exclude -assertpath <path>"
    removes exactly its own bin, one path at a time, until no assertion miss is
    left. The full path is already unambiguous, so all -du does there is break
    the match -- and Questa reports no error either way, the same failure mode
    cov.tcl's header warns about.
    """
    du = row.get("Design Unit") or ""
    metric = row.get("Metric") or ""
    target = row.get("Target") or ""
    reason = "reviewed in docs/coverage/coverage_review.csv"
    if metric == "assertion":
        return ("coverage exclude -assertpath %s -comment {%s}"
                % (target, reason))
    line = (row.get("Line") or "").strip()
    flag = METRIC_CODE_FLAG.get(metric)
    if not line or not flag:
        return ""
    return ("coverage exclude -du %s -linerange %s -code %s -comment {%s}"
            % (du, line, flag, reason))


def load_exclusions_by_line(cov_tcl):
    """{line number: Exclusion} so each sheet row can quote its own Tcl source."""
    path = Path(cov_tcl)
    if not path.is_file():
        return {}
    from coverage_waiver_audit import parse_cov_tcl
    exclusions, _variables, _gates = parse_cov_tcl(path)
    return {excl.lineno: excl for excl in exclusions}


# Each published dump and the column where it quotes a line of cov.tcl. Those
# numbers come out of cov.tcl's own text, so editing the file -- a comment
# included -- moves every cite below it, and a stale cite is invisible in a
# spreadsheet: the number is still in range and the row still reads fine,
# which is what makes a stale cite so expensive: the whole set is
# checked below, never by hand. A bare integer parses as well as a
# `cov.tcl:NNN`, because the three dumps have never agreed on the prefix.
# Files are named relative to docs/coverage/, where all three are published.
PUBLISHED_CITES = (("raw/waiver_audit.csv", "Source Line"),
                   ("coverage_review.csv", "cov.tcl Line"),
                   ("raw/phase_c_acceptance.csv", "cov.tcl Line"))


def check_published_cites(cov_tcl, docs_dir, dumps=None):
    """(problems, checked): does every published cov.tcl line name its own waiver?

    Reads cov.tcl back and asks each cite's line three questions: that it is a
    `coverage exclude` statement at all, that it contains every word of the
    row's Target, and that it names the row's design unit.

    It lives here, and not beside the parser in coverage_waiver_audit.py,
    because the sheet is this tool's own output and it copies the audit's cite
    column straight into it -- and because it has to stay Questa-free, which is
    the one thing the audit tool is not.

    The statement test is deliberately a `startswith` on the cited line rather
    than parse_cov_tcl's set of linenos: that parser reports commented-out
    exclusions too, so citing it would let a cite that drifted onto a
    commented-out waiver pass. Drifting onto one is itself a finding here.
    """
    path = Path(cov_tcl)
    if not path.is_file():
        raise SystemExit("error: no %s -- the dumps under %s cite lines of it"
                         % (path, docs_dir))
    lines = path.read_text(encoding="utf-8").splitlines()
    problems, checked = [], 0
    for name, column in (dumps if dumps is not None else PUBLISHED_CITES):
        dump = Path(docs_dir) / name
        if not dump.is_file():
            continue
        for row in read_raw_csv(dump):
            cell = (row.get(column) or "").strip()
            digits = cell.rsplit(":", 1)[-1]
            if not digits.isdigit():
                continue
            checked += 1
            where = "%s %s -> %s" % (name, row.get("ID") or row.get("Test"), cell)
            lineno = int(digits)
            statement = (lines[lineno - 1].strip()
                         if 1 <= lineno <= len(lines) else "")
            if statement.startswith("#coverage exclude") or statement.startswith(
                    "# coverage exclude"):
                problems.append("%s points at a commented-out exclusion" % where)
                continue
            if not statement.startswith("coverage exclude"):
                problems.append("%s is not a coverage exclude statement" % where)
                continue
            target = (row.get("Target") or "").replace("{", " ").replace("}", " ")
            for word in target.split():
                if word not in statement:
                    problems.append("%s does not name %r" % (where, word))
            design_unit = (row.get("Design Unit") or "").strip()
            if design_unit and design_unit not in statement:
                problems.append("%s does not name %s" % (where, design_unit))
    return problems, checked


def build_rows(waivers, holes, exclusions_by_line=None, parked_keys=None):
    """The whole sheet: every waiver, then every hole, in the dumps' own order."""
    exclusions_by_line = exclusions_by_line or {}
    rows = []
    for row in waivers:
        classification, category, test, status = triage_waiver(row)
        hits = max(_int(row.get("Delta Hits")), 0)
        misses = max(_int(row.get("Delta Misses")), 0)
        line = (row.get("Source Line") or "").strip()
        exclusion = exclusions_by_line.get(_int(line.rsplit(":", 1)[-1]))
        rows.append({
            "ID": row.get("ID", ""),
            "Type": "WAIVER",
            "Design Unit": row.get("Design Unit", ""),
            "Metric": row.get("Metric", ""),
            "Target": row.get("Target", ""),
            "cov.tcl Line": line,
            # What lifting the exclusion brings back *is* the target's live
            # count: the exclusion removes exactly those bins from the metric.
            "Hits": hits,
            "Misses": misses,
            "Coverage %": _coverage_percent(hits, misses),
            "Config Gate": row.get("Config Gate") or "none",
            "Waiver Status": row.get("Waiver Status", ""),
            "Classification": classification,
            "Rationale Category": category,
            "Justification": _one_line(row.get("Waiver Comment")),
            "Proposed Test": test,
            "Proposed cov.tcl Exclusion": waiver_exclusion(row, exclusion),
            "Status": status,
            "Reviewer": "", "Review Date": "", "Notes": "",
        })
    for number, row in enumerate(holes, start=1):
        verdict = triage_hole(row, parked_keys)
        target = row.get("Target") or ""
        if row.get("Metric") == "stmt":
            # A statement's identity is its source line; the sheet says so
            # explicitly rather than leaving the column blank.
            target = "line %s" % row.get("Line", "")
        hits = _int(row.get("Hits"))
        misses = _int(row.get("Misses"), 1)
        rows.append({
            "ID": "H%03d" % number,
            "Type": "HOLE",
            "Design Unit": row.get("Design Unit", ""),
            "Metric": row.get("Metric", ""),
            "Target": target,
            "cov.tcl Line": "",
            "Hits": hits,
            "Misses": misses,
            "Coverage %": _coverage_percent(hits, misses),
            "Config Gate": "none",
            # An open hole has no waiver, so no audit verdict either.
            "Waiver Status": "",
            "Classification": verdict["classification"],
            "Rationale Category": verdict["category"],
            "Justification": verdict["justification"],
            "Proposed Test": verdict["test"],
            "Proposed cov.tcl Exclusion": hole_exclusion(row),
            "Status": verdict["status"],
            "Reviewer": "", "Review Date": "", "Notes": "",
        })
    return rows


def write_sheet(path, rows):
    """Write the sheet: UTF-8 with BOM, CRLF, RFC-4180 quoting, no blank lines."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS,
                                quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return len(rows)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Merge the waiver audit and the hole list into the review sheet.")
    parser.add_argument("--waivers", default=str(DEFAULT_WAIVERS),
                        help="waiver_audit.csv from bin/coverage_waiver_audit.py")
    parser.add_argument("--holes", default=str(DEFAULT_HOLES),
                        help="holes.csv from bin/coverage_holes.py")
    parser.add_argument("--parked-holes", default=str(DEFAULT_PARKED_HOLES),
                        help="holes_parked.csv, the same export against the "
                             "including-parked database; absent file keeps the "
                             "parked-evidence rule off (default-scope triage "
                             "only)")
    parser.add_argument("--cov-tcl", default=str(DEFAULT_COV_TCL),
                        help="cov.tcl, read only to quote each waiver's own line")
    parser.add_argument("--out", default=str(DEFAULT_OUT),
                        help="sheet to write (default: docs/coverage/coverage_review.csv)")
    parser.add_argument("--summary", action="store_true",
                        help="print the tally by type, classification and status")
    parser.add_argument("--check-cites", action="store_true",
                        help="write nothing: check that every cov.tcl line number the "
                             "dumps beside --out publish still names its own "
                             "exclusion (run this after editing cov.tcl, comments "
                             "included, and before quoting a sheet)")
    args = parser.parse_args(argv)

    if args.check_cites:
        problems, checked = check_published_cites(args.cov_tcl, Path(args.out).parent)
        for problem in problems:
            print("stale cite: %s" % problem)
        if not checked:
            print("FAIL: no dump with a cov.tcl cite found beside %s"
                  % Path(args.out).parent)
            return 1
        print("%s: %d published cov.tcl cites checked, %d problem(s)"
              % ("FAIL" if problems else "OK", checked, len(problems)))
        return 1 if problems else 0

    waivers = read_raw_csv(args.waivers)
    holes = read_raw_csv(args.holes)
    parked_keys = load_parked_holes(args.parked_holes)
    if parked_keys is None:
        print("note: no %s -- parked-evidence rule off, holes that the "
              "including-parked merge covers stay open" % args.parked_holes)
    rows = build_rows(waivers, holes, load_exclusions_by_line(args.cov_tcl),
                      parked_keys)
    total = write_sheet(args.out, rows)
    print("Wrote %s: %d rows (%d WAIVER from %s, %d HOLE from %s)"
          % (args.out, total, len(waivers), args.waivers, len(holes), args.holes))

    if args.summary:
        for column in ("Type", "Classification", "Rationale Category",
                       "Waiver Status", "Status"):
            tally = {}
            for row in rows:
                key = row[column] or "(blank)"
                tally[key] = tally.get(key, 0) + 1
            print("\n%s:" % column)
            for key in sorted(tally):
                print("  %-22s %d" % (key, tally[key]))
        untriaged = [row["ID"] for row in rows if not row["Classification"]]
        if untriaged:
            print("\nUnclassified rows (no rule matched): %s" % ", ".join(untriaged))
    return 0


if __name__ == "__main__":
    sys.exit(main())
