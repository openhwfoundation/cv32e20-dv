#!/usr/bin/env python3
"""Line-to-tests coverage matrix: which tests hit each RTL source object.

The merged coverage report says a bin is covered; this answers the review
question behind it: *by what*. bin/coverage_matrix.py consumes the
`vcover report -xml -details -instance=<dut>.` exports of the per-test
.ucdb files, the same DUT scope the published code metrics use, exported by
run_tests.py; this module never launches Questa. It renders a static,
self-contained HTML tree under coverage_report/matrix/:

    index.html      one row per RTL file, a per-category heat column and a
                    link into the annotated source page;
    <file>.html     the verbatim RTL source, every line whose objects any
                    test hit badged per category, each badge expanding
                    (CSS-only <details>) into the tests that hit it.

Categories follow Questa's code-coverage metrics, named after the elements
the -details export uses: S statement (<stmt>), B branch arm (<ielem> of
an <if>, <celem> of a <case>), C condition (<condition>, one FEC
requirement object), FS FSM state (<state>), FT FSM transition (<trans>),
FE assertion (<asrt>; this is what a `cover property` object contributes
too, and its covered criterion is Questa's own: pass count > 0). The
plural per-instance rollups (<statements>, <branches>, <fec_conditions>,
<states>, <transitions>, <assertion_successes>) carry the same numbers per
instance and are deliberately not parsed here.

Object => file resolution: a <stmt>/<ielem>/<celem>/<condition> carries an
fn="N" index into its instance's <sourceTable><fileMap>; <state>/<trans>
carry no file, so they resolve through a single-file sourceTable (an FSM
module compiles from its own file), and an <asrt> carries its own
``<source>path(line)</source>``. An object whose file or line cannot be
resolved is counted in the parse's "unattributed" totals, never on a
guessed line.

merged_map (the same parse of the merged database's export) supplies the
"full merge" reference: the per-file totals and the merge-level hit marker,
so a line covered by no individual row but present in the merge is visibly
labelled rather than silently green.
"""

import html
import re
from xml.etree import ElementTree as ET

# (category key, one-letter badge, long label) in column order.
CATEGORIES = (
    ("S", "S", "statement"),
    ("B", "B", "branch arm"),
    ("C", "C", "condition"),
    ("FS", "FS", "FSM state"),
    ("FT", "FT", "FSM transition"),
    ("FE", "FE", "assertion / cover"),
)
_CATEGORY_KEYS = tuple(key for key, _b, _l in CATEGORIES)

# The singular metric elements one -details export carries per instance.
# The file each lives in comes from the instance's sourceTable (fn= attribute)
# or, for <asrt>, from its own <source>path(line)</source> text.
_OBJECT_ELEMENTS = {
    "stmt": "S",
    "ielem": "B",
    "celem": "B",
    "condition": "C",
    "state": "FS",
    "trans": "FT",
    "asrt": "FE",
}

# "<source>/path/to/file.sv(272)</source>": the line an assertion carries.
_ASRT_SOURCE = re.compile(r"\((\d+)\)\s*$")


def _int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _covered(element):
    """Whether this metric object counts as covered. An if-arm (<ielem>) is
    an arm whose condition took either way; an assertion is Questa's own
    success criterion, pass count > 0; everything else carries hits=."""
    tag = element.tag
    if tag == "ielem":
        return _int(element.get("true")) + _int(element.get("false")) > 0
    if tag == "asrt":
        return _int(element.findtext("passcount")) > 0
    return _int(element.get("hits")) > 0


def _base_name(path):
    return path.replace("\\", "/").split("/")[-1]


def _instance_files(instance):
    """(fn => file name, sole file name or None) for one <instanceData>."""
    files = {}
    single = None
    table = instance.find("sourceTable")
    if table is not None:
        maps = table.findall("fileMap")
        for file_map in maps:
            path = file_map.get("path") or ""
            if path:
                files[file_map.get("fn")] = _base_name(path)
        if len(maps) == 1:
            path = maps[0].get("path") or ""
            single = _base_name(path) if path else None
    return files, single


def _locate(element, files, single):
    """(file name, line) an object attributes to; either may be None."""
    if element.tag == "asrt":
        source = (element.findtext("source") or "").strip()
        match = _ASRT_SOURCE.search(source)
        if not source or match is None:
            return None, None
        return (_base_name(source[:match.start()]),
                int(match.group(1)))
    fn = element.get("fn")
    path = files.get(fn) if fn is not None else single
    line = _int(element.get("ln"), None)
    return path, line


def parse_detail_xml(xml_path):
    """One `vcover report -xml -details` export => this database's objects.

    Returns {"objects": {(file, line): {category: count}},
             "unattributed": {category: count},
             "by_file": {file: {category: count}}}
    where count is the number of *covered* objects of that category at that
    line (a statement counts 1, a branch contributes one per covered arm,
    an assertion 1 when it passed). Objects with no resolvable file or
    source line land in "unattributed", never on a guessed line.
    """
    root = ET.parse(str(xml_path)).getroot()
    objects = {}
    unattributed = dict((category, 0) for category in _CATEGORY_KEYS)
    for instance in root.iter("instanceData"):
        files, single = _instance_files(instance)
        for element in instance.iter():
            category = _OBJECT_ELEMENTS.get(element.tag)
            if category is None or not _covered(element):
                continue
            name, line = _locate(element, files, single)
            if name is None or line is None:
                unattributed[category] += 1
                continue
            cell = objects.setdefault((name, line), {})
            cell[category] = cell.get(category, 0) + 1
    by_file = {}
    for (name, _line), cell in objects.items():
        totals = by_file.setdefault(name, dict((c, 0) for c in
                                               _CATEGORY_KEYS))
        for category, count in cell.items():
            totals[category] += count
    return {"objects": objects, "unattributed": unattributed,
            "by_file": by_file}


def merge_test_maps(test_maps):
    """{file: {line: {category: set(test names)}}} from
    {test_name: parse_detail_xml() result}."""
    matrix = {}
    for name, parsed in test_maps.items():
        for (file_name, line), cell in parsed["objects"].items():
            row = matrix.setdefault(file_name, {}).setdefault(
                line, dict((c, set()) for c in _CATEGORY_KEYS))
            for category in cell:
                row[category].add(name)
    return matrix


_CSS = """
body { font-family: sans-serif; margin: 1.2em; color: #222; }
table { border-collapse: collapse; }
th, td { border: 1px solid #bbb; padding: 3px 8px; font-size: 13px; }
th { background: #eee; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
.heat { display: inline-block; width: 8em; height: 1em; background: #eee;
        vertical-align: middle; }
.heat i { display: block; height: 100%; background: #3a6; }
a { color: #06c; text-decoration: none; }
.src { font-family: monospace; font-size: 12px; border-collapse: collapse;
       width: 100%; }
.src td { border: none; padding: 0 6px; white-space: pre; }
.src td.ln { color: #888; text-align: right; user-select: none;
             border-right: 1px solid #ddd; width: 1%; }
.badge { display: inline-block; padding: 0 4px; margin-right: 3px;
         border-radius: 3px; background: #d6e9c6; color: #145; cursor:
         pointer; font-size: 11px; }
.badge.partial { background: #fcf3cf; color: #754; }
details { display: inline; }
details summary { display: inline; list-style: none; cursor: pointer; }
details ul { display: inline-block; margin: 2px 0; padding: 4px 10px;
             border: 1px solid #bbb; background: #fff; position: absolute;
             z-index: 10; }
h1 code { font-size: 70%; }
.note { color: #444; max-width: 70em; }
"""


def _heat_cell(hits, total):
    if not total:
        return '<td class="num">&mdash;</td>'
    fraction = max(0.0, min(1.0, hits / total))
    return ('<td><span class="heat"><i style="width: {:.0f}%"></i></span> '
            '<span class="num">{} / {}</span></td>'.format(
                fraction * 100, hits, total))


def render_matrix(test_maps, merged_map, sources_dir, out_dir, title=None):
    """Write out_dir/index.html plus one page per RTL file. sources_dir is
    scanned for the RTL files the matrix names (the CVE2 core's rtl/
    directory); files not found there are reported and skipped, never
    invented. Returns {"files": n rendered, "objects": m (file, line)
    rows with a hit, "missing_sources": [...]} for the caller's log."""
    from pathlib import Path
    sources_dir = Path(str(sources_dir))
    out_dir = Path(str(out_dir))
    out_dir.mkdir(parents=True, exist_ok=True)
    matrix = merge_test_maps(test_maps)
    title = title or "Coverage matrix"

    merged_counts = (merged_map or {}).get("by_file", {})
    # Union of covered objects across tests: an object two tests hit counts
    # once (summing the per-test by_file totals would double-count it).
    union_hits = {}
    for parsed in test_maps.values():
        for (hit_file, line), cell in parsed["objects"].items():
            file_hits = union_hits.setdefault(hit_file, {})
            for category, count in cell.items():
                key = (line, category)
                if count > file_hits.get(key, 0):
                    file_hits[key] = count
    union_totals = {}
    for hit_file, entries in union_hits.items():
        totals = union_totals.setdefault(hit_file, {})
        for (_line, category), count in entries.items():
            totals[category] = totals.get(category, 0) + count

    written = []
    missing_sources = []
    index_rows = []
    for file_name in sorted(matrix):
        source_path = sources_dir / file_name
        if not source_path.is_file():
            missing_sources.append(file_name)
            continue
        try:
            source = source_path.read_text(errors="replace").splitlines()
        except OSError as exc:
            print(f"  warning: cannot read {source_path}: {exc}")
            missing_sources.append(file_name)
            continue
        totals = merged_counts.get(file_name) or union_totals.get(file_name) \
            or {}
        cells = [f'<td><a href="{html.escape(file_name)}.html">'
                 f'{html.escape(file_name)}</a></td>']
        for category, _badge, _label in CATEGORIES:
            total = totals.get(category, 0)
            if not total:
                cells.append('<td class="num">&mdash;</td>')
                continue
            hits = sum(count for (_line, cat), count
                       in union_hits.get(file_name, {}).items()
                       if cat == category)
            cells.append(_heat_cell(hits, total))
        index_rows.append("<tr>" + "".join(cells) + "</tr>")
        _write_source_page(out_dir / f"{file_name}.html", file_name, source,
                           matrix[file_name], merged_map, title)
        written.append(file_name)

    header = ('<tr><th>RTL file</th>' + "".join(
        f"<th>{label}</th>" for _k, _b, label in CATEGORIES) + "</tr>")
    note = ""
    if missing_sources:
        note = ('<p class="note">No source found under {} for: {} '
                '(reported, not rendered).</p>').format(
                    html.escape(str(sources_dir)),
                    html.escape(", ".join(missing_sources)))
    (out_dir / "index.html").write_text(f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>{html.escape(title)}
</title><style>{_CSS}</style></head><body>
<h1>{html.escape(title)}</h1>
<p class="note">Which tests hit each source object. Cells read hit by a
test / total covered objects of that category (totals from the merged
database when available, otherwise the union over tests); the per-file
pages carry the test names per line.</p>
<table>
<thead>{header}</thead>
<tbody>
{chr(10).join(index_rows)}
</tbody>
</table>
{note}
</body></html>
""")
    return {"files": len(written),
            "objects": sum(len(lines) for lines in matrix.values()),
            "missing_sources": missing_sources}


def _write_source_page(path, file_name, source, line_map, merged_map, title):
    """One annotated page: verbatim source, per-line category badges whose
    <details> reveal names the contributing tests (merged_map membership
    shown as the "(merge)" entry when no individual test lists it)."""
    merged_objects = (merged_map or {}).get("objects", {})
    rows = []
    for number, text in enumerate(source, start=1):
        cell = line_map.get(number)
        merged_cell = merged_objects.get((file_name, number)) or {}
        badges = []
        for category, badge, label in CATEGORIES:
            tests = sorted((cell or {}).get(category) or ())
            in_merge = bool(merged_cell.get(category))
            if not tests and not in_merge:
                continue
            names = tests + (["(full merge)"] if in_merge and not tests
                             else [])
            partial = "" if tests else " partial"
            badges.append(
                "<details class=\"b{cat}\"><summary><span class=\"badge"
                "{p}\" title=\"{label}\">{badge} +{n}</span></summary>"
                "<ul><li>{items}</li></ul></details>".format(
                    cat=category, p=partial,
                    label=html.escape(label), badge=badge,
                    n=max(len(tests) - 1, 0),
                    items="</li><li>".join(html.escape(t) for t in names)))
        rows.append(f'<tr><td class="ln">{number}</td><td>'
                    f'{html.escape(text)}{"".join(badges)}</td></tr>')
    path.write_text(f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>{html.escape(title)} &mdash; {html.escape(file_name)}</title>
<style>{_CSS}</style></head><body>
<p><a href="index.html">&larr; all files</a></p>
<h1><code>{html.escape(file_name)}</code></h1>
<table class="src">
<tbody>
{chr(10).join(rows)}
</tbody>
</table>
</body></html>
""")
