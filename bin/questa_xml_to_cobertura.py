#!/usr/bin/env python3
# Copyright (c) 2026 Eclipse Foundation
# SPDX-License-Identifier: Apache-2.0 WITH SHL-2.1
"""Convert a Questa per-line coverage export into Cobertura 0.4 XML.

Input is the XML that `vcover report -xml -details -code scb -instance=<inst>.`
writes for a merged .ucdb (see bin/run_tests.py's generate_coverage_reports()).
Questa's own document looks like

    <coverage_report>
      <code_coverage_report byInstance="1">
        <instanceData path="/…/alu_i" du="cve2_alu">
          <sourceTable files="1"><fileMap fn="0" path="/abs/…/cve2_alu.sv"/></sourceTable>
          <branches active="55" hits="49" percent="89.09"/>
          <if hasElse="1" active="2" hits="2" percent="100.00">
            <ielem fn="0" ln="138" st="1" true="4382" false="3078"/>
            <ielem fn="0" ln="140" st="1" true="3078" false="0"/>
          </if>
          <case active="2" hits="1" percent="50.00">
            <celem fn="0" ln="87" st="1" hits="0"/>
          </case>
          <fec_conditions active="2" hits="2" percent="100.00"/>
          <condition fn="0" ln="138" st="1" active="2" hits="2" percent="100.00"/>
          <statements active="66" hits="64" percent="96.96"/>
          <stmt fn="0" ln="56" st="1" hits="5319"/>
        </instanceData>
      </code_coverage_report>
    </coverage_report>

so every Cobertura number this file emits is a real number from the simulation:
one <line> per instrumented source line of the design (<stmt fn ln hits>, with
<fileMap fn path> resolving fn to a file), and one condition per <ielem> /
<celem> (Questa's branch metric) or <condition> (its condition metric).

Mapping to Cobertura
--------------------
* <sources><source> is the repository root, and every <class filename> is
  relative to it when the source lives under the root, so the report is
  portable to machines where the checkout lives elsewhere (the fn paths in the
  XML are the compile host's absolute paths).
* <package> is the source directory as a dotted name, <class> the file's
  relative path -- unique, unlike a bare basename, which two directories of
  same-named files would collide on.
* Items of one source line are aggregated per line: max of the hit counts
  within one instance, summed across instances, so a line executed by any
  instance counts as covered. lines-valid therefore counts source lines, not
  Questa statement items -- the two differ whenever several statements share a
  line, which is why the consistency cross-check below compares items.
* A <line> is any line Questa instruments: one carrying a statement, or one
  carrying only branch/condition items -- an RTL `case` label or an `if`
  condition line usually has no statement of its own. Its 'hits' then come
  from the branch items themselves (a case item that was never selected was
  never entered, so 0 is the honest count). line-rate is consequently the share
  of *all* instrumented lines that were reached and reads lower than Questa's
  statement percentage, while branch-rate reproduces vcover's branch number
  exactly, because it counts the same <ielem>/<celem> items the rollup's
  <branches active hits> does. Questa's condition metric is reported on the
  same lines as extra <condition type="condition"> children.
* <methods/> stays empty: Questa attributes coverage to source lines, not to
  subroutines, so there is no method granularity to report (an empty
  <methods/> is what the Cobertura DTD's <!ELEMENT class (methods, lines)>
  requires, and without it the file is not DTD-valid at all).

Optionally pass --rollup (the DUT-scoped `vcover report -xml` export of the same
.ucdb) to cross-check the detail against the rollup and shout when the two
disagree -- a mismatch means Questa did not export every item, and reporting
only the exported subset as if it were the whole design would publish a
flattering 1.0000 line rate -- the failure this cross-check exists to shout
about.
"""

import argparse
import os
import sys
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Reported in the Cobertura 'version' attribute; this converter's own version.
VERSION = "4.0.3"

# One aggregated source line.
_LINE_FIELDS = ("hits", "branch_total", "branch_covered", "cond_total", "cond_covered")


def _int(value, default=0):
    """Integer attribute; Questa writes 'na' where a count does not apply."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _new_line():
    return dict((field, 0) for field in _LINE_FIELDS)


def _relative(path, repo_root):
    """Path relative to the repository root, or the absolute path unchanged
    when it lives outside it (vendor checkouts, a simulator's own sources)."""
    try:
        rel = os.path.relpath(path, str(repo_root))
    except ValueError:
        # Different drive on Windows; nothing sensible to make relative.
        return path
    if rel.startswith(".." + os.sep) or rel == "..":
        return path
    return rel.replace(os.sep, "/")


def _reach_count(elem):
    """Times a branch item was executed. <ielem> reports true/false counts and
    no 'hits'; <celem> reports 'hits'."""
    return max(_int(elem.get("true")), _int(elem.get("hits")))


def _branch_taken(elem):
    """Whether a branch item was exercised."""
    return _reach_count(elem) > 0


def parse_detail(detail_path, repo_root=REPO_ROOT):
    """Read the per-line detail of a Questa XML export.

    Returns (files, totals). files maps a source path to
    {line_number: {hits, branch_total, branch_covered, cond_total,
    cond_covered}}; the keys are relative to repo_root where possible. totals
    counts the Questa *items* seen (statement/branch/condition items, of which
    a line can carry several) for the rollup cross-check."""
    root = ET.parse(str(detail_path)).getroot()
    files = {}
    totals = {"stmt_items": 0, "stmt_items_covered": 0,
              "branch_items": 0, "branch_items_covered": 0,
              "cond_items": 0, "cond_items_covered": 0,
              "instances": 0, "instances_without_source": 0}

    for inst in root.iter("instanceData"):
        # fn => source path, per instance: Questa numbers the files of each
        # design unit separately.
        file_map = {}
        source_table = inst.find("sourceTable")
        if source_table is not None:
            for fmap in source_table.iter("fileMap"):
                fn, path = fmap.get("fn"), fmap.get("path")
                if fn is not None and path:
                    file_map[fn] = _relative(path, repo_root)
        if not file_map:
            totals["instances_without_source"] += 1
            continue
        totals["instances"] += 1

        # This instance's items, aggregated per (source path, line).
        inst_lines = defaultdict(_new_line)
        for stmt in inst.iter("stmt"):
            path = file_map.get(stmt.get("fn"))
            if path is None or stmt.get("ln") is None:
                continue
            hits = _int(stmt.get("hits"))
            line = inst_lines[(path, _int(stmt.get("ln")))]
            line["hits"] = max(line["hits"], hits)
            totals["stmt_items"] += 1
            totals["stmt_items_covered"] += 1 if hits > 0 else 0

        # <ielem> is one branch of an if/case-if, <celem> one case item. Both
        # are one item of Questa's branch metric.
        for tag in ("ielem", "celem"):
            for elem in inst.iter(tag):
                path = file_map.get(elem.get("fn"))
                if path is None or elem.get("ln") is None:
                    continue
                line = inst_lines[(path, _int(elem.get("ln")))]
                taken = _branch_taken(elem)
                line["branch_total"] += 1
                line["branch_covered"] += 1 if taken else 0
                line["hits"] = max(line["hits"], _reach_count(elem))
                totals["branch_items"] += 1
                totals["branch_items_covered"] += 1 if taken else 0

        # <condition> rolls up the rows of one expression's truth table, so it
        # contributes active/hits rather than a single item.
        for elem in inst.iter("condition"):
            path = file_map.get(elem.get("fn"))
            if path is None or elem.get("ln") is None:
                continue
            active, hits = _int(elem.get("active")), _int(elem.get("hits"))
            line = inst_lines[(path, _int(elem.get("ln")))]
            line["cond_total"] += active
            line["cond_covered"] += min(hits, active)
            totals["cond_items"] += active
            totals["cond_items_covered"] += min(hits, active)

        # Merge this instance into the file map: a line covered in any one
        # instance is covered, and its hit count is the total across instances.
        for (path, line_no), items in inst_lines.items():
            if line_no <= 0:
                continue
            lines = files.setdefault(path, {})
            existing = lines.setdefault(line_no, _new_line())
            for field in _LINE_FIELDS:
                existing[field] += items[field]

    return files, totals


def check_consistency(detail_path, rollup_path, scope=None):
    """Compare the detail export's item counts against the rollup export's.

    Both come from the same .ucdb, so the detail must contain exactly 'active'
    items and 'hits' covered items of every metric the rollup counts for the
    same scope. Returns True when they agree (or there is nothing to compare),
    False on a mismatch -- the caller keeps going either way, because a partial
    report still beats none, but says so loudly.
    """
    try:
        root = ET.parse(str(rollup_path)).getroot()
    except (OSError, ET.ParseError) as exc:
        print(f"warning: cannot cross-check Cobertura against rollup "
              f"{rollup_path}: {exc}")
        return True

    scope = scope.rstrip(".") if scope else None
    rollup = {"statements": [0, 0], "branches": [0, 0], "fec_conditions": [0, 0]}
    for inst in root.iter("instanceData"):
        path = inst.get("path", "")
        if scope and not (path == scope or path.startswith(scope + "/")):
            continue
        for metric in rollup:
            node = inst.find(metric)
            if node is not None:
                rollup[metric][0] += _int(node.get("active"))
                rollup[metric][1] += _int(node.get("hits"))

    _, detail = parse_detail(detail_path)
    checks = (("statements", detail["stmt_items"], detail["stmt_items_covered"]),
              ("branches", detail["branch_items"], detail["branch_items_covered"]),
              ("fec_conditions", detail["cond_items"], detail["cond_items_covered"]))
    ok = True
    for metric, items, covered in checks:
        active, hits = rollup[metric]
        if not active:
            continue
        if items != active or covered != hits:
            ok = False
            print(f"warning: the Cobertura detail disagrees with the rollup for "
                  f"{metric}: detail has {items} items ({covered} covered), "
                  f"rollup reports {active} active ({hits} covered). The "
                  f"Cobertura file only reflects what Questa exported.")
    if ok:
        print(f"  Cobertura detail matches the rollup ({detail['stmt_items']} "
              f"statements, {detail['branch_items']} branches, "
              f"{detail['cond_items']} conditions)")
    return ok


def _rate(covered, total):
    return (covered / total) if total else 0.0


def _pct(covered, total):
    return f"{_rate(covered, total) * 100:.2f}% ({covered}/{total})"


def _totals(lines):
    """(lines-valid, lines-covered, branches-valid, branches-covered)."""
    return (len(lines),
            sum(1 for line in lines.values() if line["hits"] > 0),
            sum(line["branch_total"] for line in lines.values()),
            sum(line["branch_covered"] for line in lines.values()))


def generate_cobertura_xml(detail_path, output_path, rollup_path=None,
                           scope=None, repo_root=REPO_ROOT):
    """Write Cobertura XML for the Questa detail export at detail_path.

    rollup_path, when given, is the DUT-scoped `vcover report -xml` export used
    for the consistency cross-check (see check_consistency); scope is the
    -instance the detail was exported with, and only scopes that check. Returns
    True when a file was written.
    """
    detail_path = Path(detail_path)
    if not detail_path.is_file():
        print(f"error: Questa detail XML not found: {detail_path}", file=sys.stderr)
        return False

    if rollup_path:
        check_consistency(detail_path, rollup_path, scope)

    files, _detail_totals = parse_detail(detail_path, repo_root)
    if not files:
        print(f"warning: {detail_path} carries no per-file statement data; "
              f"the Cobertura report will be empty", file=sys.stderr)

    # Group by directory into Cobertura packages, files by name inside them.
    packages = defaultdict(list)
    for rel_path, lines in files.items():
        directory = os.path.dirname(rel_path)
        package = directory.replace("/", ".") if directory else "rtl"
        packages[package].append((rel_path, lines))

    grand = [0, 0, 0, 0]
    for lines in files.values():
        for i, value in enumerate(_totals(lines)):
            grand[i] += value

    coverage = ET.Element("coverage", {
        "line-rate": f"{_rate(grand[1], grand[0]):.4f}",
        "branch-rate": f"{_rate(grand[3], grand[2]):.4f}",
        "lines-covered": str(grand[1]),
        "lines-valid": str(grand[0]),
        "branches-covered": str(grand[3]),
        "branches-valid": str(grand[2]),
        "complexity": "0",
        "version": VERSION,
        # Cobertura's timestamp is seconds since the epoch (the reference
        # implementation writes seconds; a millisecond value reads as year 45k).
        "timestamp": str(int(time.time())),
    })
    ET.SubElement(ET.SubElement(coverage, "sources"), "source").text = str(repo_root)

    packages_elem = ET.SubElement(coverage, "packages")
    for package_name in sorted(packages):
        members = packages[package_name]
        pkg_totals = [0, 0, 0, 0]
        for _rel, lines in members:
            for i, value in enumerate(_totals(lines)):
                pkg_totals[i] += value

        package = ET.SubElement(packages_elem, "package", {
            "name": package_name,
            "line-rate": f"{_rate(pkg_totals[1], pkg_totals[0]):.4f}",
            "branch-rate": f"{_rate(pkg_totals[3], pkg_totals[2]):.4f}",
            "complexity": "0",
        })
        classes = ET.SubElement(package, "classes")
        for rel_path, lines in sorted(members, key=lambda m: m[0]):
            valid, covered, branch_total, branch_covered = _totals(lines)
            clazz = ET.SubElement(classes, "class", {
                "name": rel_path,
                "filename": rel_path,
                "line-rate": f"{_rate(covered, valid):.4f}",
                "branch-rate": f"{_rate(branch_covered, branch_total):.4f}",
                "complexity": "0",
            })
            # The DTD orders the children of <class> as (methods, lines); no
            # statement in an .sv source belongs to a method Questa tracks.
            ET.SubElement(clazz, "methods")
            lines_elem = ET.SubElement(clazz, "lines")
            for line_no in sorted(lines):
                line = lines[line_no]
                has_branch = line["branch_total"] > 0
                attributes = {
                    "number": str(line_no),
                    "hits": str(line["hits"]),
                    "branch": "true" if has_branch else "false",
                }
                if has_branch:
                    attributes["condition-coverage"] = _pct(
                        line["branch_covered"], line["branch_total"])
                line_elem = ET.SubElement(lines_elem, "line", attributes)

                cond_children = []
                if has_branch:
                    cond_children.append(("branch", line["branch_total"],
                                          line["branch_covered"]))
                if line["cond_total"]:
                    cond_children.append(("condition", line["cond_total"],
                                          line["cond_covered"]))
                if cond_children:
                    conditions_elem = ET.SubElement(line_elem, "conditions")
                    for cond_type, total, covered_by_type in cond_children:
                        ET.SubElement(conditions_elem, "condition", {
                            "type": cond_type,
                            "number": str(total),
                            "coverage": f"{_rate(covered_by_type, total) * 100:.2f}%",
                        })

    tree = ET.ElementTree(coverage)
    if hasattr(ET, "indent"):
        ET.indent(tree)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as handle:
        handle.write(b'<?xml version="1.0" encoding="UTF-8"?>\n'
                     b'<!DOCTYPE coverage SYSTEM '
                     b'"http://cobertura.sourceforge.net/xml/coverage-04.dtd">\n')
        tree.write(handle, encoding="utf-8", xml_declaration=False)

    print(f"Cobertura: {grand[1]}/{grand[0]} lines "
          f"({_rate(grand[1], grand[0]) * 100:.2f}%), "
          f"{grand[3]}/{grand[2]} branches "
          f"({_rate(grand[3], grand[2]) * 100:.2f}%) across {len(files)} files "
          f"-> {output_path}")
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Convert a Questa per-line coverage XML export to Cobertura XML.")
    parser.add_argument("-i", "--input", default="dut_detail.xml",
                        help="Questa `-xml -details -code scb` export "
                             "(default: dut_detail.xml)")
    parser.add_argument("-r", "--rollup",
                        help="Questa `-xml` rollup of the same .ucdb, for a "
                             "consistency cross-check")
    parser.add_argument("--instance",
                        help="Instance the detail was scoped to with -instance= "
                             "(only used to scope --rollup)")
    parser.add_argument("-o", "--output", default="cobertura.xml",
                        help="Output Cobertura XML file (default: cobertura.xml)")
    parser.add_argument("--repo-root", default=str(REPO_ROOT),
                        help="Repository root the file names are made relative "
                             "to (default: this script's repository)")
    args = parser.parse_args(argv)

    ok = generate_cobertura_xml(args.input, args.output, rollup_path=args.rollup,
                                scope=args.instance, repo_root=Path(args.repo_root))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
