#!/usr/bin/env python3
# Copyright (c) 2026 Eclipse Foundation
# SPDX-License-Identifier: Apache-2.0 WITH SHL-2.1
"""coverage_grading.py: A dedicated per-test coverage grading reporting tool
for the CV32E30-DV.

Note: This is WIP. It is currently compatible only with Siemens EDA's Questa 
Sim as simulator.


This module address the question on how much each test contributes to the
coverage results for the CVE2. It is used by `run_tests.py --cov-report` 
after the merge coverage step, where each test's Questa coverage database 
.ucdb file gets the same two Questa XML exports, and the same two parsers, 
as the merged database: DUT-scoped for Code coverage, and whole-hierarchy 
covergroups for functional coverage. It outputs a report HTML table in 
../coverage_report/pertest/index.html.

The Unique column is the grading insight. For each test the batch produced,
the merged database is copied and that test's contribution deleted with
``vcover delcov -test <name>``; what the copy loses is what only this test
covered. It costs one database copy plus two more vcover exports per test,
so it runs by default only for batches of at most DELTA_MAX_TESTS tests
(sanity-sized), always off with --no-cov-delta.

This module holds no subprocess calls and no paths. `run_tests.py` exports 
the XML with the same invocations it already uses for the merged database,
parses it with the existing parse_questa_code_rollup()/parse_questa_
functional_rollup(), and hands the parsed dicts down here. Keeping the
arithmetic and the HTML here keeps them unit-testable without Questa.
"""

import html

# The five code metrics, in table order: (parse_questa_code_rollup key,
# column label).
_METRICS = (
    ("statement", "Stmt"),
    ("branch", "Branch"),
    ("condition", "Cond"),
    ("fsm_state", "FSM state"),
    ("fsm_transition", "FSM trans"),
)

# Batches at or below this many tests compute the unique-contribution delta
# by default -- each one costs a merged-database copy, a delcov replay and
# two more vcover exports, which is minutes at sanity size and an hour at
# full-batch size.
DELTA_MAX_TESTS = 20


def format_percent(value):
    """A percentage (float or None) as a table cell."""
    return "N/A" if value is None else f"{value:.2f} %"


def test_row(name, ucdb, code_metrics, functional):
    """One grading row from one test's parsed rollups (either may be None)."""
    return {
        "test": name,
        "ucdb": str(ucdb) if ucdb is not None else None,
        "code": (code_metrics or {}).get("code"),
        "metrics": {metric: dict((code_metrics or {}).get(metric) or {})
                    for metric, _label in _METRICS},
        "functional": (functional or {}).get("percent"),
        "functional_bins": [
            (functional or {}).get("bins_covered") or 0,
            (functional or {}).get("bins_total") or 0,
        ],
        "unique": None,
    }


def delta(merged_code, residual_code, merged_functional,
          residual_functional):
    """What only one test contributes, as a test_row() ``unique`` dict.

    merged_* are the merged database's parsed rollups; residual_* the same
    parse after ``vcover delcov -test <name>`` removed that test's rows.
    Every percentage is relative to the *merged* active count, so a unique
    code % reads directly against the merged code %. Metrics with no active
    objects (None percent) contribute no number, and a negative difference
    (impossible, but databases are allowed to surprise) clamps to zero.
    """
    if not merged_code:
        return None
    per = {}
    active_total = 0
    unique_total = 0
    for metric, _label in _METRICS:
        merged = merged_code.get(metric) or {}
        active = merged.get("active") or 0
        if not active:
            continue
        residual = (residual_code or {}).get(metric) or {}
        unique_hits = max((merged.get("hits") or 0)
                          - (residual.get("hits") or 0), 0)
        per[metric] = {
            "active": active,
            "unique_hits": unique_hits,
            "percent": round(100.0 * unique_hits / active, 2),
        }
        active_total += active
        unique_total += unique_hits
    functional = None
    if merged_functional and merged_functional.get("bins_total"):
        total = merged_functional["bins_total"]
        unique_bins = max((merged_functional.get("bins_covered") or 0)
                          - ((residual_functional or {}).get(
                              "bins_covered") or 0), 0)
        functional = {"total": total,
                      "unique_hits": unique_bins,
                      "percent": round(100.0 * unique_bins / total, 2)}
    return {
        "code_percent": (round(100.0 * unique_total / active_total, 2)
                         if active_total else None),
        "metrics": per,
        "functional_bins": functional,
    }


def render_pertest_index(rows, html_reports=None, merged=None,
                         unique_computed=False):
    """The HTML for coverage_report/pertest/index.html: one row per test,
    best-covered first, plus the merged totals as the summary line.

    html_reports maps test name -> (code_dir, func_dir), relative links to
    the per-test vcover HTML trees when --cov-report-html-tests generated
    them (either may be None). merged is the merged database's own
    test_row()-shaped dict, for the header line. unique_computed only
    selects the footnote wording -- rows carry their own unique dicts, so an
    honest page never needs this to say more than which note is true.
    """
    html_reports = html_reports or {}
    order = sorted(rows,
                   key=lambda r: (-(r["code"] if r["code"] is not None
                                     else -1.0), r["test"]))

    head = "".join(f"<th>{label}</th>" for _m, label in
                   (("code", "Code"),) + _METRICS +
                   (("functional", "Functional"),
                    ("unique", "Unique"),
                    ("ucdb", "UCDB")))

    def num_cell(value):
        return f'<td class="num">{format_percent(value)}</td>'

    body = []
    for row in order:
        unique = row.get("unique") or {}
        cells = [f"<td>{html.escape(row['test'])}</td>",
                 num_cell(row.get("code"))]
        for metric, _label in _METRICS:
            cells.append(num_cell(
                (row["metrics"].get(metric) or {}).get("percent")))
        cells.append(num_cell(row.get("functional")))
        cells.append(num_cell(unique.get("code_percent") if unique
                              else None))
        code_dir, func_dir = html_reports.get(row["test"], (None, None))
        links = []
        if code_dir:
            links.append('<a href="{}/index.html">code</a>'
                         .format(html.escape(code_dir)))
        if func_dir:
            links.append('<a href="{}/index.html">func</a>'
                         .format(html.escape(func_dir)))
        links.append('<span class="dim ucdb">{}</span>'
                     .format(html.escape(row.get("ucdb") or "")))
        cells.append("<td>" + " ".join(links) + "</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")

    merged_line = ""
    if merged:
        merged_line = ("<p>Merged database: code {}, functional {} -- the "
                       "rows describe each test alone, and Unique is what "
                       "only that test contributes on top of the "
                       "rest.</p>").format(format_percent(merged.get("code")),
                                           format_percent(
                                               merged.get("functional")))
    note = ("Unique is what deleting this test from the merged database "
            "(<code>vcover delcov -test</code>) takes away with it."
            if unique_computed else
            "Unique was not computed for this batch (batches over "
            f"{DELTA_MAX_TESTS} tests, or --no-cov-delta).")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Per-test coverage grading</title>
<style>
body {{ font-family: sans-serif; margin: 1.5em; color: #222; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #bbb; padding: 4px 8px; font-size: 14px;
          text-align: left; vertical-align: top; }}
th {{ background: #eee; }}
td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
tr:hover {{ background: #f6f9ff; }}
p, .note {{ color: #444; max-width: 70em; }}
.dim {{ color: #777; font-size: 12px; }}
.ucdb {{ display: block; word-break: break-all; }}
a {{ color: #06c; }}
</style>
</head>
<body>
<h1>Per-test coverage grading</h1>
{merged_line}
<table>
<thead><tr>{head}</tr></thead>
<tbody>
{chr(10).join(body) if body else '<tr><td colspan="9">No per-test databases in this batch.</td></tr>'}
</tbody>
</table>
<p class="note">{note}</p>
<p class="note">Code is the DUT-scoped mean of the five TRL5 metrics,
Functional the covergroup-bin percentage of the whole hierarchy,
environment included -- the same two scopes as the top-level dashboard, so
a row and the merged line are directly comparable.</p>
</body>
</html>
"""


def pertest_summary_json(rows, unique_computed, html_reports=False):
    """The summary.json ``pertest`` block: enough for the dashboard to link
    the grading page and say what is behind it, no more."""
    return {
        "generated": bool(rows),
        "test_count": len(rows),
        "unique_computed": bool(unique_computed),
        "html_reports": bool(html_reports),
        "tests": {
            row["test"]: {
                "code": row.get("code"),
                "functional": row.get("functional"),
                "unique_code": (row.get("unique") or {}).get("code_percent"),
                "ucdb": row.get("ucdb"),
            } for row in rows
        },
    }
