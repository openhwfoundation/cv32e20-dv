#!/usr/bin/env python3
import sys
import os
import time
import argparse
import xml.etree.ElementTree as ET
from xml.dom import minidom
from collections import defaultdict


def parse_questa_xml(input_path):
    """
    Parses Questa XML coverage report and aggregates line hits per source file.
    """
    tree = ET.parse(input_path)
    root = tree.getroot()

    # file_path -> line_number -> hit_count
    file_lines = defaultdict(lambda: defaultdict(int))

    for instance in root.findall(".//instanceData"):
        # Map local fn index to file path for this instance
        file_map = {}
        for fmap in instance.findall(".//fileMap"):
            fn = fmap.get("fn")
            path = fmap.get("path")
            if fn and path:
                file_map[fn] = path

        # Aggregate hits per line within this instance
        # (Takes max hit count among multiple statements on the same line)
        inst_line_hits = defaultdict(list)
        for stmt in instance.findall("stmt"):
            fn = stmt.get("fn")
            ln = stmt.get("ln")
            hits = stmt.get("hits")
            if fn in file_map and ln is not None and hits is not None:
                file_path = file_map[fn]
                inst_line_hits[(file_path, int(ln))].append(int(hits))

        # Sum line execution hits across all instances in the report
        for (file_path, line_no), hits_list in inst_line_hits.items():
            file_lines[file_path][line_no] += max(hits_list)

    return file_lines


def generate_cobertura_xml(file_lines):
    """
    Generates a formatted Cobertura XML tree from aggregated file coverage data.
    """
    all_paths = list(file_lines.keys())
    if not all_paths:
        common_prefix = ""
    elif len(all_paths) == 1:
        common_prefix = os.path.dirname(all_paths[0])
    else:
        common_prefix = os.path.commonpath(all_paths)

    # Group files into packages based on directory structure relative to common prefix
    packages = defaultdict(list)
    for file_path, lines in file_lines.items():
        rel_path = os.path.relpath(file_path, common_prefix) if common_prefix else file_path
        pkg_dir = os.path.dirname(rel_path)
        pkg_name = pkg_dir.replace(os.sep, ".").replace("/", ".") if pkg_dir else "default"
        packages[pkg_name].append((file_path, rel_path, lines))

    # Calculate global metrics
    total_valid = sum(len(lines) for lines in file_lines.values())
    total_covered = sum(
        sum(1 for hits in lines.values() if hits > 0)
        for lines in file_lines.values()
    )
    overall_line_rate = (total_covered / total_valid) if total_valid > 0 else 0.0

    # Build XML structure
    coverage_elem = ET.Element("coverage", {
        "line-rate": f"{overall_line_rate:.4f}",
        "branch-rate": "0.0",
        "lines-covered": str(total_covered),
        "lines-valid": str(total_valid),
        "branches-covered": "0",
        "branches-valid": "0",
        "complexity": "0",
        "version": "2.0.3",
        "timestamp": str(int(time.time()))
    })

    # <sources>
    sources_elem = ET.SubElement(coverage_elem, "sources")
    source_elem = ET.SubElement(sources_elem, "source")
    source_elem.text = common_prefix or "."

    # <packages>
    packages_elem = ET.SubElement(coverage_elem, "packages")

    for pkg_name, files in sorted(packages.items()):
        pkg_valid = sum(len(lines) for _, _, lines in files)
        pkg_covered = sum(
            sum(1 for h in lines.values() if h > 0)
            for _, _, lines in files
        )
        pkg_line_rate = (pkg_covered / pkg_valid) if pkg_valid > 0 else 0.0

        pkg_elem = ET.SubElement(packages_elem, "package", {
            "name": pkg_name,
            "line-rate": f"{pkg_line_rate:.4f}",
            "branch-rate": "0.0",
            "complexity": "0"
        })

        classes_elem = ET.SubElement(pkg_elem, "classes")

        for file_path, rel_path, lines in sorted(files, key=lambda x: x[1]):
            cls_valid = len(lines)
            cls_covered = sum(1 for h in lines.values() if h > 0)
            cls_line_rate = (cls_covered / cls_valid) if cls_valid > 0 else 0.0
            class_name = os.path.splitext(os.path.basename(file_path))[0]

            class_elem = ET.SubElement(classes_elem, "class", {
                "name": class_name,
                "filename": rel_path.replace("\\", "/"),
                "line-rate": f"{cls_line_rate:.4f}",
                "branch-rate": "0.0",
                "complexity": "0"
            })

            ET.SubElement(class_elem, "methods")
            lines_elem = ET.SubElement(class_elem, "lines")

            for line_no in sorted(lines.keys()):
                hits = lines[line_no]
                ET.SubElement(lines_elem, "line", {
                    "number": str(line_no),
                    "hits": str(hits),
                    "branch": "false"
                })

    # Render minidom document with Cobertura DTD declaration
    raw_xml = ET.tostring(coverage_elem, encoding="utf-8")
    parsed_dom = minidom.parseString(raw_xml)
    
    dom_impl = minidom.getDOMImplementation()
    dtd = dom_impl.createDocumentType(
        "coverage", None, "http://cobertura.sourceforge.net/xml/coverage-04.dtd"
    )
    doc = dom_impl.createDocument(None, "coverage", dtd)
    doc.replaceChild(parsed_dom.documentElement, doc.documentElement)

    return doc.toprettyxml(indent="  ")


def main():
    parser = argparse.ArgumentParser(description="Convert Questa XML report to Cobertura XML.")
    parser.add_argument("-i", "--input", default="report.xml", help="Input Questa XML file (default: report.xml)")
    parser.add_argument("-o", "--output", default="cobertura.xml", help="Output Cobertura XML file (default: cobertura.xml)")
    args = parser.parse_args()

    if not os.path.isfile(args.input):
        print(f"Error: Input file '{args.input}' not found.", file=sys.stderr)
        sys.exit(1)

    file_lines = parse_questa_xml(args.input)
    cobertura_xml = generate_cobertura_xml(file_lines)

    with open(args.output, "w", encoding="utf-8") as f:
        f.write(cobertura_xml)

    print(f"Successfully converted '{args.input}' to '{args.output}'")


if __name__ == "__main__":
    main()