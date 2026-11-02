#!/usr/bin/env python3
# Copyright (c) 2026 Eclipse Foundation
# SPDX-License-Identifier: Apache-2.0 WITH SHL-2.1
"""Convert Questa coverage XML into a UCIS XML coverage database.

Why this file exists
--------------------
`vcover report -xml` writes Questa's own proprietary <coverage_report> schema,
which only Questa understands and which reports code coverage as a percentage per
instance. This converter turns three Questa exports of the same .ucdb into a
document a UCIS consumer can open:

  * full-hierarchy rollup (vcover report -xml)
        -> provenance only: the tool name/version and the vcover command line.
  * DUT-scoped detail (vcover report -xml -details -code scb -instance=<dut>.)
        -> one <instanceCoverages> per design instance: its statements
           (blockCoverage), condition expressions (conditionCoverage) and branch
           arms (branchCoverage), each at the source line Questa gives it.
  * DUT-independent covergroup detail (vcover report -xml -details -cvg)
        -> one <instanceCoverages> per covergroup package: one <cgInstance> per
           instantiated covergroup, with its coverpoints, its crosses and every
           named bin together with its hit count.

Conformance
-----------
The normative schema of this document is schemas/ucis.xsd, the UCIS XML schema
that PyUCIS (https://github.com/fvutils/pyucis, Apache-2.0) validates against and
reads with; it is vendored in this repository byte-for-byte (sha256
ks-uWiD_-YnB4Qa6Kfpj4OeVhOYxcfdwyMQzZnK0c0Q, from pyucis 0.1.4's
ucis/xml/schema/ucis.xsd) so that `xmllint` in .github/workflows/coverage.yml and
in bin/tests/test_converters.py can enforce it offline. Keep it at that digest
rather than "update" it to the copy an installed pyucis ships: 0.2.0's own copy
differs from this one in a single attribute, CGINSTANCE/coverpoint's minOccurs
(1 here, 0 there), so the check this repository runs enforces the stricter of the
two -- and what this writes validates against both. PyUCIS is why the format is
worth emitting at all: it is what makes the published artifact openable by
`pyucis-viewer`, which neither Questa's XML nor an aggregate-percentage rendition
of the same numbers can do.

That schema is stricter than "use the UCIS names", and two of its rules shape the
output here, so read them before changing the emitter:

  * Every coverage object names a source line -- <id file= line= inlineCount=>,
    all three required and >= 1 -- so an object Questa gives no usable file and
    line for cannot be written at all: it is skipped and counted, never relocated
    onto a line that does not hold it. (Questa's per-line statement index, <st>, is
    what UCIS calls inlineCount: it tells two statements of one line apart.)
  * Covergroups are per bin: a coverpoint must carry at least one `coverpointBin`
    with a count, so Questa's type-level summaries (a percentage plus three bin
    counts, and no bin names) cannot be emitted -- only the per-instance bins can,
    and objects whose bins are all absent are dropped rather than written empty.

Honest gaps, recorded rather than papered over:
  * The .ucdb records the tests it merged, but the plain -xml rollup does not name
    them, so the history holds one node for the merged database and its
    `testStatus` says what a merge implies, not a measured verdict;
    sim/uvmt/regression_results.json stays the authority on pass/fail. Its
    `logicalName` is the stem of the --ucdb name, or the plain word "merged" when
    no --ucdb was given: the schema makes the attribute mandatory, so that much is
    a label rather than a measurement.
  * Questa names no source line for a covergroup, so a covergroup's <id> refers to
    line 1 of the package file its own file map reports.
  * The schema has no aggregate metric of any kind, so the rollup's percentages are
    not repeated here; coverage_report/summary.json and the Questa HTML report
    carry those.
  * `coverpointBin` requires a value range, while Questa names the bin and its
    count and puts the value domain in free text (<bin_rhs>), so the range is
    written as the nominal 0..0 and a bin's identity is its name.
  * A UCIS condition expression must carry the source text of the whole condition
    in `exprString`, while Questa's export names only the individual
    sub-expressions in `<row body=>`; a condition of exactly one sub-expression is
    therefore emitted and every multi-term one is skipped.
  * `CROSS_BIN` identifies a cross bin by the index, within each crossed coverpoint,
    of the bin it combines. Questa writes that combination in the cross bin's own
    name (`<auto[ZERO],auto[POSITIVE]>`), so the name is translated into the
    `coverpointBin/@key` of this same document. A cross bin Questa names some other
    way is counted as skipped instead; measured on the database this runs against,
    those are 387 `*` bins for "anything else", not one of them hit, and 63
    cross-level ignore bins (`IGN_HAZ`, `IGN_OFF`, `IGN_PREV_GROUP`), 37 of them
    carrying a count -- and such a count is an occurrence of an *ignored*
    combination rather than a hit, and an ignore bin names a whole set of
    combinations, so no one index vector describes it either. The skip tally counts
    bins, not hits, and the Questa HTML report is where those counts stay readable.
  * Questa reports assertion and FSM coverage only as counts, never naming the
    individual assertions, states or transitions, so those kinds are absent.
"""

import argparse
import os
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

SCHEMA_LOCATION = "schemas/ucis.xsd"
UCIS_VERSION = "1.0"
# <historyNodes> requires all four of these; they describe the tool that produced
# the .ucdb, not this converter (writtenBy does that).
TOOL_CATEGORY = "simulator"
VENDOR_ID = "Siemens EDA"
VENDOR_TOOL = "Questa Sim"
# A merged database has no single test status and the schema demands one, which a
# consumer reads as one passing run; sim/uvmt/regression_results.json stays the
# verdict anybody should rely on. See the "Honest gaps" note above.
MERGED_TEST_STATUS = "true"

# Questa's <bins> holds <bin>, <ignore_bins> and <illegal_bins>; UCIS keeps the
# three kinds in one element distinguished by a type.
BIN_KIND_BY_TAG = {"bin": "bins", "ignore_bins": "ignore", "illegal_bins": "illegal"}

# The option values this converter copies, per call site: every name below is an
# attribute the schema declares for that kind of <options>, and Questa writes more
# than any one of them allows. `comment` is free text and `merge_instances` is an
# option of the merge rather than of the covergroup instance, so both are dropped
# everywhere.
CGINST_OPTIONS = ("weight", "goal", "at_least", "detect_overlap", "auto_bin_max",
                  "cross_num_print_missing", "per_instance")
COVERPOINT_OPTIONS = ("weight", "goal", "at_least", "detect_overlap", "auto_bin_max")
CROSS_OPTIONS = ("weight", "goal", "at_least", "cross_num_print_missing")


def _int(value):
    """Integer attribute, or None where it does not apply: Questa writes 'na' for
    metrics nothing was hit, so every caller spells out its own fallback."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _positive(value):
    """Integer attribute that UCIS could use, i.e. an actual positive integer:
    Questa leaves `ln` off an object it has no source line for, and UCIS requires
    line >= 1 of every one of them."""
    number = _int(value)
    return number if number and number > 0 else None


def _text(element, child_tag):
    """Text of a child element -- or of `element` itself when child_tag is None --
    or None."""
    if element is None:
        return None
    child = element if child_tag is None else element.find(child_tag)
    if child is None:
        return None
    value = (child.text or "").strip()
    return value if value else None


def _file_name(path, repo_root):
    """The file's path as UCIS should name it: relative to the repository when it
    lives under it (a consumer resolves it against this checkout), absolute -- as
    Questa wrote it -- when it does not."""
    path = str(path)
    try:
        relative = os.path.relpath(path, str(repo_root))
    except ValueError:
        return path
    if relative.startswith(".." + os.sep) or relative == "..":
        return path
    return relative.replace(os.sep, "/")


def _last(name):
    """Last component of a scope-qualified name Questa writes as /a/b/c."""
    return (name or "").rstrip("/").rsplit("/", 1)[-1]


def _scope_of(name):
    """Everything but the last component of a Questa name: the scope it lives in."""
    name = (name or "").rstrip("/")
    return name.rsplit("/", 1)[0] if "/" in name else name


class _Files(object):
    """UCIS refers to a source file by the numeric id of a <sourceFiles> entry and
    every coverage object must name one, so each file is registered once here and
    keeps the id it was first given."""

    def __init__(self, repo_root):
        self.repo_root = repo_root
        self.ids = {}      # file name -> id
        self.order = []    # file names, in registration order

    def register(self, path):
        """Id of `path`, registering it if it is new. None for the empty paths
        Questa writes for files it elided from an export."""
        if not path:
            return None
        key = _file_name(path, self.repo_root)
        if key not in self.ids:
            self.ids[key] = len(self.order) + 1
            self.order.append(key)
        return self.ids[key]

    def file_map(self, scope_element):
        """{Questa file number: UCIS file id} of one <sourceTable>."""
        table = scope_element.find("sourceTable")
        if table is None:
            return {}
        return dict((element.get("fn"), self.register(element.get("path")))
                    for element in table.iter("fileMap")
                    if element.get("fn") is not None)

    def first_of(self, file_map):
        """Id of the first file a scope's own table names -- the package that
        declares the covergroups, in the exports this converts. None when the scope
        names no file at all, which is not the same as not knowing which one to
        name: guessing another scope's file would locate the coverage in the wrong
        source."""
        for number in sorted(file_map, key=_number):
            if file_map[number]:
                return file_map[number]
        return None

    def emit(self, parent):
        # <sourceFiles> comes before everything that refers to it in the schema's
        # sequence, so it is written first, in registration order.
        for key in self.order:
            ET.SubElement(parent, "sourceFiles", {"fileName": key,
                                                  "id": str(self.ids[key])})


def _number(value):
    """Sort key that puts Questa's numeric file numbers in order ('10' after '9')."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return sys.maxsize


def _parse_root(path, what="export"):
    """Root of a Questa export, or None after saying why it could not be read. One
    export being unreadable is an ordinary outcome here (bin/run_tests.py warns and
    carries on when a `vcover report` step fails), so it must not reach the caller
    as a traceback."""
    try:
        return ET.parse(str(path)).getroot()
    except (OSError, ET.ParseError) as exc:
        print(f"error: could not read the {what} {path}: {exc}", file=sys.stderr)
        return None


def _optional_root(path, what):
    """Root of an optional export: None when it is absent, unreadable or malformed,
    each of which means only that this kind of coverage is not in the document -- a
    caller that asked for it says which part fell out."""
    if not path or not Path(path).is_file():
        return None
    return _parse_root(path, what)


def _schema_hint(output_path, repo_root):
    """Where the vendored schema is, spelled from `output_path`'s directory, which
    is the only place anything resolves the hint against."""
    try:
        hint = os.path.relpath(str(Path(repo_root) / SCHEMA_LOCATION),
                               str(Path(output_path).parent))
    except ValueError:
        return SCHEMA_LOCATION
    return hint.replace(os.sep, "/")


def _statement_id(parent, tag, file_id, line=1, inline_count=1):
    """Adds <file line inlineCount=> to `parent`, or returns None writing nothing
    when the export gave no file or no positive line: UCIS requires all three and
    a line clamped or guessed to satisfy it would locate the coverage somewhere it
    is not."""
    line = _positive(line)
    if file_id is None or line is None:
        return None
    return ET.SubElement(parent, tag, {"file": str(file_id), "line": str(line),
                                       "inlineCount": str(max(1, _int(inline_count) or 1))})


def _contents(parent, count):
    """<contents coverageCount="n"/>: how UCIS records one hit count."""
    ET.SubElement(parent, "contents",
                  {"coverageCount": str(max(0, count or 0))})


def _counted_bin(parent, tag, count):
    """<tag><contents coverageCount="n"/></tag>: how UCIS records one hit count."""
    element = ET.SubElement(parent, tag)
    _contents(element, count)
    return element


def _options(parent, source, allowed):
    """<options/> carrying the option values of a Questa <option>/<type_option>,
    limited to the attributes the schema declares for this kind of options and to
    the values it can hold: every one of them is an xsd:nonNegativeInteger, while
    Questa writes 'None' for an option it does not use."""
    attributes = {}
    for name in allowed:
        number = _int(_text(source, name))
        if number is not None and number >= 0:
            attributes[name] = str(number)
    ET.SubElement(parent, "options", attributes)


def _emit_code_coverage(scope, file_map, key, parent, skipped):
    """Writes the <instanceCoverages> of one design instance from its -code scb
    detail, and returns whether anything was written.

    An instance Questa gives no usable source location for is skipped entirely: the
    schema makes a file and a line mandatory on the instance and on every object
    below it, and a made-up one would attribute the coverage to a file or a line
    that does not contain it."""
    statements = [element for element in scope.findall("stmt")
                  if _int(element.get("hits")) is not None]
    if not statements:
        return False
    # The instance's own <id> has to name something, and the schema will not accept
    # one without both a file and a line, so the anchor is the first statement that
    # has both -- after which writing its id cannot fail.
    anchor = next((statement for statement in statements
                   if file_map.get(statement.get("fn"))
                   and _positive(statement.get("ln"))), None)
    if anchor is None:
        skipped["instances with no source location"] += 1
        return False

    instance = ET.SubElement(parent, "instanceCoverages",
                             {"name": scope.get("path", ""), "key": str(key),
                              "moduleName": scope.get("du") or _last(scope.get("path"))})
    _statement_id(instance, "id", file_map.get(anchor.get("fn")), anchor.get("ln"),
                  anchor.get("st"))

    # Emitted in the order the schema declares: id, blockCoverage,
    # conditionCoverage, branchCoverage.
    block = None
    for statement in statements:
        # Built detached and attached only once it is known to carry the <id> the
        # schema demands, so an object Questa located nowhere is skipped rather than
        # written somewhere it is not.
        element = ET.Element("statement")
        if _statement_id(element, "id", file_map.get(statement.get("fn")),
                         statement.get("ln"), statement.get("st")) is None:
            skipped["statements with no source location"] += 1
            continue
        if block is None:
            block = ET.SubElement(instance, "blockCoverage")
        block.append(element)
        _counted_bin(element, "bin", _int(statement.get("hits")))

    conditions = None
    for condition in scope.findall("condition"):
        # UCIS wants the source text of the whole expression in `exprString`, but
        # Questa writes only the individual sub-expressions in `<row body=>`, so a
        # condition is emitted truthfully only when it consists of exactly one of
        # them; the rest are skipped rather than given an invented expression.
        bodies = [body for body in (row.get("body") for row in condition.iter("row"))
                  if body]
        if len(bodies) != 1:
            skipped["conditions not made of one sub-expression"] += 1
            continue
        number = str(len(conditions) + 1) if conditions is not None else "1"
        expression = ET.Element("expr",
                               {"name": "line %s" % condition.get("ln"),
                                "key": number, "exprString": bodies[0],
                                "index": number, "width": "1"})
        if _statement_id(expression, "id", file_map.get(condition.get("fn")),
                         condition.get("ln"), condition.get("st")) is None:
            skipped["conditions with no source location"] += 1
            continue
        if conditions is None:
            conditions = ET.SubElement(instance, "conditionCoverage")
        conditions.append(expression)
        ET.SubElement(expression, "subExpr").text = bodies[0]
        _counted_bin(expression, "bin", _int(condition.get("hits")))

    branches = None
    for tag in ("if", "case"):
        for node in scope.findall(tag):
            for arm in node:
                # <ielem> is one line with a taken and a not-taken count, <celem>
                # one case arm; UCIS calls each of those a branch of the statement.
                counts = ([arm.get("true"), arm.get("false")] if arm.tag == "ielem"
                          else [arm.get("hits")])
                counts = [count for count in (_int(value) for value in counts)
                          if count is not None]
                if not counts:
                    skipped["branch arms without a count"] += 1
                    continue
                statement = ET.Element("statement", {"statementType": tag})
                if _statement_id(statement, "id", file_map.get(arm.get("fn")),
                                 arm.get("ln"), arm.get("st")) is None:
                    skipped["branch arms with no source location"] += 1
                    continue
                for count in counts:
                    # Same file and line as the statement above, whose id was
                    # accepted, so this one cannot be refused either.
                    branch = ET.Element("branch")
                    _statement_id(branch, "id", file_map.get(arm.get("fn")),
                                  arm.get("ln"), arm.get("st"))
                    _counted_bin(branch, "branchBin", count)
                    statement.append(branch)
                if branches is None:
                    branches = ET.SubElement(instance, "branchCoverage")
                branches.append(statement)

    return True


def _emit_coverpoint(cover_group, coverpoint, key, skipped):
    """Writes one <coverpoint> of a <cgInstance> and returns (its name, {bin name:
    key}), or (None, None) when it has no bin to carry -- which the schema forbids
    and which means Questa reported no coverage detail for it."""
    name = _text(coverpoint, "bin/name")
    if not name:
        return None, None
    element = ET.SubElement(cover_group, "coverpoint",
                            {"name": name, "key": str(key)})
    _options(element, coverpoint.find("option"), COVERPOINT_OPTIONS)
    written_bins = {}
    for index, bin_element in enumerate(coverpoint.findall("bins/*"), start=1):
        kind = BIN_KIND_BY_TAG.get(bin_element.tag)
        if kind is None:
            skipped["bins of a kind UCIS has no type for"] += 1
            continue
        count = _int(_text(bin_element, "metric"))
        if count is None:
            skipped["bins Questa gave no count for"] += 1
            continue
        bin_name = _text(bin_element, "name") or "bin_%d" % index
        # The range is nominal: Questa writes the bin's value domain as free text
        # (<bin_rhs>), which the schema has no slot for, so a bin's identity here
        # is its name and its data is the count.
        bin_out = ET.SubElement(element, "coverpointBin",
                                {"type": kind, "name": bin_name, "key": str(index)})
        value_range = ET.SubElement(bin_out, "range", {"from": "0", "to": "0"})
        _contents(value_range, count)
        # A bin name repeated inside one coverpoint is illegal SystemVerilog and
        # unseen here; were it to appear, a cross naming it would mean the first
        # of those bins, which is the key worth keeping.
        written_bins.setdefault(bin_name, index)
    if not written_bins:
        cover_group.remove(element)
        skipped["coverpoints without bins"] += 1
        return None, None
    return name, written_bins


def _cross_bin_indices(bin_name, expressions, written, skipped):
    """The index vector a UCIS cross bin is identified by: within each crossed
    coverpoint, the key of the bin Questa names in the cross bin's own name, which
    is a tuple of them ("<auto[ZERO],auto[POSITIVE]>"). Returns None -- after
    counting why -- when Questa named no such combination (a name that is not one
    tuple of bin names per crossed coverpoint) or named one this document does not
    carry (a `*` wildcard bin); an index taken from the bin's ordinal instead would
    be read back as a real combination.

    A name splitting into the wrong number of parts never reaches the lookup: it
    is counted under its own reason, so a name Questa wrote some other way is never
    mixed up with one it wrote over a bin this document does not carry."""
    combination = ([part.strip() for part in bin_name[1:-1].split(",")]
                   if bin_name.startswith("<") and bin_name.endswith(">") else [])
    if len(combination) != len(expressions):
        skipped["cross bins whose combination Questa does not name"] += 1
        return None
    indices = []
    for expression, part in zip(expressions, combination):
        key = written[expression].get(part)
        if key is None:
            skipped["cross bins over a bin Questa does not carry"] += 1
            return None
        indices.append(key)
    return indices


def _emit_cross(cover_group, cross, key, written, skipped):
    """Writes one <cross> of a <cgInstance>. A cross whose expression names a
    coverpoint this document does not carry is skipped: UCIS resolves a cross by
    the coverpoints of the same covergroup, so an unresolved reference is not
    merely less detail -- PyUCIS's own reader stops on it."""
    name = _text(cross, "bin/name")
    expressions = [text for text in (_text(element, None)
                                     for element in cross.iter("cross_coverpoint"))
                   if text]
    if not name or not expressions:
        return
    if any(expression not in written for expression in expressions):
        skipped["crosses naming an unwritten coverpoint"] += 1
        return
    element = ET.SubElement(cover_group, "cross", {"name": _last(name), "key": str(key)})
    _options(element, cross.find("type_option"), CROSS_OPTIONS)
    for expression in expressions:
        ET.SubElement(element, "crossExpr").text = expression
    for index, bin_element in enumerate(cross.findall("bins/*"), start=1):
        count = _int(_text(bin_element, "metric"))
        if count is None:
            skipped["bins Questa gave no count for"] += 1
            continue
        kind = BIN_KIND_BY_TAG.get(bin_element.tag)
        if kind in ("ignore", "illegal"):
            # Questa writes a cross's own ignore bin as a whole set of combinations
            # ("<a,b>;<a,c>;..."), so no one index vector describes it and its count
            # is not a hit; CROSS_BIN/@type is a free string no reader looks at, so
            # writing the bin under it would only hide that.
            skipped["cross bins Questa marked ignored or illegal"] += 1
            continue
        if kind != "bins":
            skipped["cross bins of a kind UCIS has no type for"] += 1
            continue
        bin_name = _text(bin_element, "name") or "bin_%d" % index
        indices = _cross_bin_indices(bin_name, expressions, written, skipped)
        if indices is None:
            continue
        # <index> before <contents>, as CROSS_BIN declares them.
        bin_out = ET.SubElement(element, "crossBin",
                                {"name": bin_name, "key": str(index)})
        for position in indices:
            ET.SubElement(bin_out, "index").text = str(position)
        _contents(bin_out, count)


def _emit_covergroup_instance(scope, cover_instance, file_id, type_name, parent, key,
                              skipped):
    """Writes one <cgInstance> -- a covergroup Questa instantiated, with its bins --
    and returns it, or None when no coverpoint of it had a bin."""
    full_name = _text(cover_instance, "bin/name") or ""
    instance_name = _text(cover_instance, "option/name") or _last(full_name)
    if not instance_name:
        skipped["covergroup instances without a name"] += 1
        return None
    # Questa names the covergroup type in the instance's own path; the type block
    # that precedes it says the same thing, so either identifies the type.
    type_name = type_name or _last(_scope_of(full_name)) or "covergroup"

    cover_group = ET.Element("cgInstance", {"name": instance_name, "key": str(key)})
    _options(cover_group, cover_instance.find("option"), CGINST_OPTIONS)
    cg_id = ET.SubElement(cover_group, "cgId", {"cgName": type_name,
                                                "moduleName": scope.get("path") or ""})
    # Both source ids are mandatory and Questa names no line for a covergroup, so
    # they point at the package file (line 1) that the scope's own table reports.
    for tag in ("cginstSourceId", "cgSourceId"):
        _statement_id(cg_id, tag, file_id)

    # A key only has to be unique among the coverpoints and crosses of this one
    # covergroup, so they share one counter; the schema wants the coverpoints
    # before the crosses, which is also the order the keys run in.
    written = {}
    for coverpoint in cover_instance.findall("coverpoint"):
        name, written_bins = _emit_coverpoint(cover_group, coverpoint, len(written) + 1,
                                              skipped)
        if name:
            written[name] = written_bins
    if not written:
        return None
    for offset, cross in enumerate(cover_instance.findall("cross"),
                                   start=len(written) + 1):
        _emit_cross(cover_group, cross, offset, written, skipped)
    parent.append(cover_group)
    return cover_group


def generate_ucis_xml(rollup_path, output_path, detail_path=None,
                      cvg_detail_path=None, ucdb_name=None, repo_root=REPO_ROOT):
    """Write a UCIS XML coverage database.

    rollup_path is the full-hierarchy `vcover report -xml` export and supplies the
    tool provenance; detail_path (per-line, DUT-scoped) and cvg_detail_path
    (per-covergroup instance) supply the coverage. A missing optional input only
    means that part of the database is empty, so a partial export still yields a
    valid document. Returns True when the file was written."""
    rollup_path = Path(rollup_path)
    if not rollup_path.is_file():
        print(f"error: Questa rollup XML not found: {rollup_path}", file=sys.stderr)
        return False
    rollup_root = _parse_root(rollup_path, "rollup export")
    if rollup_root is None:
        return False
    output_path = Path(output_path)

    written_time = time.strftime("%Y-%m-%dT%H:%M:%S")
    ucis = ET.Element("UCIS", {
        "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
        "xsi:noNamespaceSchemaLocation": _schema_hint(output_path, repo_root),
        "ucisVersion": UCIS_VERSION,
        "writtenBy": "bin/questa_xml_to_ucis_xml.py",
        "writtenTime": written_time,
    })
    # One history node for the merged database: the .ucdb records the tests it
    # merged, but the plain -xml rollup does not expose their names.
    history = ET.Element("historyNodes", {
        "historyNodeId": "1",
        "logicalName": Path(ucdb_name or "merged").stem,
        "physicalName": ucdb_name or "",
        "kind": "merged",
        "testStatus": MERGED_TEST_STATUS,
        "date": written_time,
        "toolCategory": TOOL_CATEGORY,
        "ucisVersion": UCIS_VERSION,
        "vendorId": VENDOR_ID,
        "vendorTool": VENDOR_TOOL,
        "vendorToolVersion": rollup_root.get("questa_version", "unknown"),
        "cmd": rollup_root.get("command", ""),
    })

    files = _Files(repo_root)
    # A detached accumulator, extended into the document at the end: the coverage
    # is discovered per export, while the schema wants all files first and all
    # instances last.
    instances = ET.Element("instances")
    skipped = Counter()
    code_count = functional_count = bin_count = cross_bin_count = 0

    detail_root = _optional_root(detail_path, "per-line code")
    if detail_root is None:
        print("warning: no usable per-line detail export; the UCIS document carries "
              "no code coverage", file=sys.stderr)
    else:
        for scope in detail_root.iter("instanceData"):
            if not scope.get("path"):
                continue
            file_map = files.file_map(scope)
            if _emit_code_coverage(scope, file_map, len(instances) + 1, instances,
                                   skipped):
                code_count += 1

    cvg_root = _optional_root(cvg_detail_path, "covergroup")
    if cvg_root is None:
        print("warning: no usable covergroup detail export; the UCIS document "
              "carries no covergroup coverage", file=sys.stderr)
    else:
        for scope in cvg_root.iter("instanceData"):
            path = scope.get("path")
            if not path:
                continue
            file_map = files.file_map(scope)
            file_id = files.first_of(file_map)
            if file_id is None:
                skipped["covergroup scopes with no source file"] += 1
                continue
            instance = ET.SubElement(instances, "instanceCoverages",
                                     {"name": path, "key": str(len(instances) + 1),
                                      "moduleName": _last(path)})
            _statement_id(instance, "id", file_id)
            coverages = ET.SubElement(instance, "covergroupCoverage")
            type_name = None
            for child in scope:
                # Questa writes each covergroup type of the package as a flat run
                # of siblings: the <bin> naming the type, its options and
                # summaries, then one <coverinstance> per instantiated copy.
                if child.tag == "bin":
                    type_name = _last(_text(child, "name"))
                elif child.tag == "coverinstance":
                    cover_group = _emit_covergroup_instance(
                        scope, child, file_id, type_name, coverages,
                        len(coverages) + 1, skipped)
                    if cover_group is not None:
                        functional_count += 1
                        bin_count += len(cover_group.findall(".//coverpointBin"))
                        cross_bin_count += len(cover_group.findall(".//crossBin"))
            if not coverages.findall("cgInstance"):
                # Nothing to show for this scope: no covergroup in it has a bin.
                instances.remove(instance)

    files.emit(ucis)
    if not len(instances):
        # The schema requires at least one instance, so a document with no coverage
        # is not a UCIS document; say so instead of publishing an invalid file.
        print("error: neither detail export yielded any coverage; refusing to write "
              "an empty UCIS document", file=sys.stderr)
        return False
    ucis.append(history)
    ucis.extend(list(instances))

    tree = ET.ElementTree(ucis)
    # Deliberately no ET.indent(): this document is a database of tens of
    # thousands of bins, and pretty-printing it costs about half its size again.
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(output_path, encoding="utf-8", xml_declaration=True)

    print(f"UCIS: {len(files.order)} source files, {code_count} instances with code "
          f"coverage, {functional_count} covergroup instances with {bin_count} "
          f"covergroup bins and {cross_bin_count} cross bins -> {output_path}")
    for reason, count in sorted(skipped.items()):
        print(f"UCIS: skipped {count} {reason} (why: see this script's docstring)")
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Convert Questa coverage XML to a UCIS XML coverage database "
                    f"(the format validated against {SCHEMA_LOCATION}).")
    parser.add_argument("-i", "--input", default="merged.questasim.xml",
                        help="full-hierarchy `vcover report -xml` export, used for "
                             "the tool provenance (default: merged.questasim.xml)")
    parser.add_argument("-d", "--detail",
                        help="DUT-scoped `-xml -details -code scb` export, for code "
                             "coverage")
    parser.add_argument("-c", "--cvg-detail",
                        help="`-xml -details -cvg` export, for covergroups and bins")
    parser.add_argument("--ucdb", help="name of the source .ucdb, recorded in the "
                                       "history node for traceability")
    parser.add_argument("-o", "--output", default="merged.ucis.xml",
                        help="Output UCIS XML file (default: merged.ucis.xml)")
    parser.add_argument("--repo-root", default=str(REPO_ROOT),
                        help="repository root file paths are made relative to "
                             "(default: this script's repository)")
    args = parser.parse_args(argv)

    ok = generate_ucis_xml(args.input, args.output, detail_path=args.detail,
                           cvg_detail_path=args.cvg_detail, ucdb_name=args.ucdb,
                           repo_root=Path(args.repo_root))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
