#!/usr/bin/env python3
# Copyright (c) 2026 Eclipse Foundation
# SPDX-License-Identifier: Apache-2.0 WITH SHL-2.1
"""Publish a regression's results as a machine-readable document plus a dashboard.

Why this file exists
--------------------
``bin/run_tests.py`` has always *printed* its verdict table and written a
plain-text ``sim/uvmt/test_results.log``, which answers "did the last run go
green?" for whoever was watching the terminal. It leaves nothing behind for a
browser: the published ``coverage_report/`` dashboard reports *coverage* and a
single pass-rate number, so "which test failed, on which seed, and how long did
it take?" still meant digging through per-test simulation logs by hand -- the
question a regression dashboard exists to answer.

This module owns that answer. It turns the harness's result rows into one JSON
document (``regression_results.json``) and publishes
``templates/regression_dashboard/{index.html,style.css}`` next to it, the same
template-copy pattern ``generate_coverage_reports()`` uses for the coverage
dashboard. It is imported by ``bin/run_tests.py`` at the end of ``main()`` and is
also usable stand-alone to re-publish the dashboard from a document that is
already on disk::

    bin/regression_report.py --results sim/uvmt/regression_results.json \
                             --out coverage_report/regression

Output lands in ``coverage_report/regression/`` -- a *sub*directory of the
published report tree, so it cannot collide with the coverage dashboard's own
``style.css`` and it rides along with the Pages deployment
(.github/workflows/coverage.yml) without that job having to learn about it.

Deliberate constraints
----------------------
* **Standard library only.** ``bin/run_tests.py`` must keep working with a bare
  ``python3``, so anything it imports has to as well.
* **Never invent a number.** A test that was only parsed from an existing log
  (``--parse-only``) has no measured duration, so ``duration_s`` is ``null``
  rather than 0; a host without git gets ``git: null`` rather than a placeholder
  SHA. The dashboard renders every ``null`` as "N/A" for exactly this reason,
  which is also the lesson of the coverage dashboard's old scraped "100%"
  functional coverage (see bin/run_tests.py's coverage-report notes).
* **No new dependency for the dashboard either.** The published page is static
  HTML + CSS + ``fetch()``, like the coverage dashboard: no build step, no CDN,
  and it still renders when the JSON is missing entirely.

Document schema (schema_version 1)
----------------------------------
``{schema_version, generated, tb, cfg, testlist, git, host, simulator,
summary, tests}`` -- ``summary`` holds ``total/passed/failed/error/pass_rate``,
the per-set ``parked``/``parked_passed`` counts and the wall-clock window, and
``tests`` one object per result row with
``name, verdict, detail, gen_seed, run_seed, duration_s, description, log,
log_exists, published_log, parked``. Adding or renaming a field means bumping
``SCHEMA_VERSION``.
"""

import argparse
import json
import platform
import shutil
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DASHBOARD_TEMPLATES = REPO_ROOT / "templates" / "regression_dashboard"

# Schema 2 added the per-row ``parked`` flag and the ``parked``/
# ``parked_passed`` counts in ``summary``; schema 1 documents (which the
# dashboard still has to render) simply lack both.
SCHEMA_VERSION = 2

# Bumped only when a document written by an older version cannot be read.
DOCUMENT_NAME = "regression_results.json"

# The verdicts bin/run_tests.py's classify() can return; anything else is
# counted as an error by build_document() rather than silently dropped.
VERDICTS = ("PASS", "FAIL", "ERROR")


def now():
    """UTC timestamp in the one format this document uses (ISO 8601, seconds).

    Public because bin/run_tests.py stamps the start of a batch with it, so a
    published wall time and the harness's own clock cannot disagree."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def test_entry(name, verdict, detail="", gen_seed=None, run_seed=None,
               duration_s=None, log=None, log_exists=False, description=None,
               parked=False):
    """One ``tests[]`` element.

    Kept as a function rather than a dict literal at the call site so the set of
    fields a consumer may rely on is declared in exactly one place. Every
    argument that a given run genuinely cannot know about stays ``None``:
    ``gen_seed`` because hand-written test-programs have no generation step,
    ``duration_s`` because nothing was timed when the verdict came from an
    existing log."""
    return {
        "name": name,
        "verdict": verdict,
        "detail": detail or "",
        "gen_seed": gen_seed,
        "run_seed": run_seed,
        "duration_s": duration_s,
        "description": description,
        # Repository-relative so the document is portable, and only advisory:
        # the simulation logs themselves are gitignored, so publish_logs() has to
        # copy them into the report for the path to be a link -- log_exists says
        # whether there was one at all, published_log whether it got published.
        "log": log,
        "log_exists": bool(log_exists),
        "published_log": None,
        # A parked test (run_tests.py's PARKED list) ran for the
        # including-parked view only: the dashboard badges its row and keeps
        # it out of the default verdict, exactly like the coverage toggle.
        "parked": bool(parked),
        }


def summarize(entries):
    """The ``summary`` object for a list of test entries.

    ``pass_rate`` is ``None`` for an empty run: 0 tests is not a 0% pass rate,
    and printing 0% for a run that selected nothing would be the same class of
    lie the coverage dashboard used to publish."""
    counts = dict((verdict, 0) for verdict in VERDICTS)
    for entry in entries:
        counts[entry["verdict"] if entry["verdict"] in counts else "ERROR"] += 1
    total = len(entries)
    # Per-set counts: total/passed cover every row (parked rows included, so
    # the document's own numbers stay a plain count of its rows), while
    # parked/parked_passed let the dashboard render the default set (the rows
    # without the flag) and say how many parked rows it left out.
    parked_total = sum(1 for entry in entries if entry.get("parked"))
    parked_passed = sum(1 for entry in entries
                        if entry.get("parked") and entry["verdict"] == "PASS")
    return {
        "total": total,
        "passed": counts["PASS"],
        "failed": counts["FAIL"],
        "error": counts["ERROR"],
        "pass_rate": round(100.0 * counts["PASS"] / total, 2) if total else None,
        "parked": parked_total,
        "parked_passed": parked_passed,
    }


def build_document(entries, tb, cfg, testlist=None, started=None, finished=None,
                   meta=None):
    """Assemble the whole ``regression_results.json`` document.

    entries: ``test_entry()`` results, in the order the harness ran them.
    tb/cfg/testlist: what was run, as the user named it.
    started/finished: ``now()``-format strings, or None when unknown; the wall
    clock between them is the only duration the document reports for the run as
    a whole, because the sum of the per-test durations means something else
    entirely once ``--jobs`` is above 1.
    meta: pre-collected ``collect_meta()`` result, or None to collect it now
    (the parameter exists so the tests can pass a fixed one)."""
    document = {
        "schema_version": SCHEMA_VERSION,
        "generated": now(),
        "tb": tb,
        "cfg": cfg,
        "testlist": testlist,
        "summary": summarize(entries),
        "tests": list(entries),
    }
    document.update(meta if meta is not None else collect_meta())
    document["summary"]["start"] = started
    document["summary"]["end"] = finished
    document["summary"]["duration_s"] = _elapsed(started, finished)
    return document


def _elapsed(started, finished):
    """Whole seconds-plus-tenths between two ``now()`` timestamps, or None."""
    try:
        first = datetime.fromisoformat(started)
        last = datetime.fromisoformat(finished)
    except (TypeError, ValueError):
        return None
    return round((last - first).total_seconds(), 1)


def _run_quiet(cmd, timeout=20):
    """stdout of a short-lived tool, or None if it is unavailable or unhappy.

    Everything the document says about its environment is best-effort: a
    released tarball has no .git, and a hosted CI runner has no Questa."""
    try:
        completed = subprocess.run(cmd, cwd=str(REPO_ROOT), timeout=timeout,
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                   text=True)
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return (completed.stdout or "").strip()


def git_meta():
    """``{sha, branch, dirty}``, or None outside a git checkout."""
    sha = _run_quiet(["git", "rev-parse", "--short", "HEAD"])
    if sha is None:
        return None
    branch = _run_quiet(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    # Only "did the tree differ from the commit" matters here, so an empty
    # porcelain listing is the whole answer.
    status = _run_quiet(["git", "status", "--porcelain"])
    return {"sha": sha, "branch": branch,
            "dirty": bool(status) if status is not None else None}


def host_meta():
    return {
        "name": socket.gethostname(),
        "os": f"{platform.system()} {platform.release()}",
        "python": platform.python_version(),
    }


def simulator_meta(tb):
    """``{name, version}`` for the simulator this testbench used, or None.

    Probed rather than parsed out of a log: the version of the simulator that
    produced a green regression belongs on the results page, and ``vsim`` is only
    asked when the run actually claimed to be a Questa (uvmt) one."""
    if tb != "uvmt" or shutil.which("vsim") is None:
        return None
    version = _run_quiet(["vsim", "-version"])
    if not version:
        return None
    return {"name": "vsim", "version": version.splitlines()[0]}


def collect_meta(tb="uvmt", cfg="default", testlist=None):
    """Environment block: who ran this, where, and with what."""
    return {
        "git": git_meta(),
        "host": host_meta(),
        "simulator": simulator_meta(tb),
    }


def write_document(document, path):
    """Write the document as JSON (the same 4-space style as summary.json)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=4) + "\n")
    print(f"Regression results saved to {path}")
    return path


def publish_logs(entries, dest_dir, max_bytes=8 * 1024 * 1024):
    """Copy each test's simulation log into ``<dest_dir>/logs/``.

    A verdict without the log it came from is only half an answer, and the logs
    themselves are gitignored, so publishing them is the only way the dashboard's
    Log column can be a link instead of a path. Each entry that made it gets a
    ``published_log`` name; the ones that did not (no log on this host, or a
    runaway log above ``max_bytes``) keep ``published_log: null`` and the page
    falls back to showing the path as text. Mutates and returns ``entries``."""
    logs_dir = Path(dest_dir) / "logs"
    for entry in entries:
        entry["published_log"] = None
        relative = entry.get("log")
        if not relative:
            continue
        source = REPO_ROOT / relative
        if not source.is_file():
            continue
        size = source.stat().st_size
        if size > max_bytes:
            print(f"warning: {relative} is {size} bytes; not publishing it with "
                  f"the dashboard")
            continue
        logs_dir.mkdir(parents=True, exist_ok=True)
        # One file per row, named after the test: several rows can share a test
        # name (--parse-only reports one per seed), so the seed disambiguates.
        suffix = entry.get("run_seed") or "0"
        shutil.copy(source, logs_dir / f"{entry['name']}-{suffix}.log")
        entry["published_log"] = f"logs/{entry['name']}-{suffix}.log"
    return entries


def publish(document, dest_dir, copy_logs=True):
    """Write the document and copy the dashboard into ``dest_dir``.

    Warns and keeps going when the templates are missing, exactly like the
    coverage dashboard's copy step: a partial report is still worth publishing,
    and the JSON is the part another tool can use."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    if copy_logs:
        publish_logs(document.get("tests", []), dest_dir)
    write_document(document, dest_dir / DOCUMENT_NAME)

    if (DASHBOARD_TEMPLATES / "index.html").is_file():
        for name in ("index.html", "style.css"):
            shutil.copy(DASHBOARD_TEMPLATES / name, dest_dir / name)
        print(f"Regression dashboard copied to {dest_dir}/")
    else:
        print(f"warning: regression dashboard templates not found at "
              f"{DASHBOARD_TEMPLATES}/")

    # The shared stylesheet, one directory down. run_tests.py publishes the very
    # same file at coverage_report/common.css; copying rather than reaching up
    # with ../ keeps each published directory self-contained (and the Pages
    # artifact path-independent).
    common_css = REPO_ROOT / "templates" / "common" / "style.css"
    if common_css.is_file():
        shutil.copy(common_css, dest_dir / "common.css")
    else:
        print(f"warning: shared stylesheet not found at {common_css}")
    return dest_dir

def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Re-publish the regression-results dashboard from a "
                    "regression_results.json that is already on disk (runs no "
                    "simulation). bin/run_tests.py calls publish() directly "
                    "after a batch.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("-r", "--results", default=str(REPO_ROOT / "sim" / "uvmt" / DOCUMENT_NAME),
                        help="regression_results.json to re-publish")
    parser.add_argument("-o", "--out", default=str(REPO_ROOT / "coverage_report" / "regression"),
                        help="directory to publish into")
    args = parser.parse_args(argv)

    try:
        document = json.loads(Path(args.results).read_text())
    except (OSError, ValueError) as exc:
        sys.exit(f"error: could not read {args.results}: {exc}")
    if not isinstance(document, dict) or "tests" not in document:
        sys.exit(f"error: {args.results} is not a regression results document")

    publish(document, args.out)
    summary = document.get("summary", {})
    print(f"{summary.get('passed', '?')}/{summary.get('total', '?')} test(s) "
          f"published to {args.out}")
    # Re-publishing reads no simulation, so like --report-only it never gates.
    return 0


if __name__ == "__main__":
    sys.exit(main())
