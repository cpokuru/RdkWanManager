#!/usr/bin/env python3
"""
extract_datamodels.py
=====================
Generates the complete list of Device.X_RDK_WanManager.* datamodel parameters
from the RdkWanManager XML config files — matching the output of:

    dmcli eRT getv Device.X_RDK_WanManager.

Two sources are combined:
  1. config/RdkWanManager.xml     — v1 model (CPEInterface)
  2. config/RdkWanManager_v2.xml  — v2 model (Interface / VirtualInterface / Group)

Table objects (dynamicTable / writableTable / staticTable) are expanded with
configurable instance counts so you see real paths like:
    Device.X_RDK_WanManager.Interface.1.Selection.Enable
    Device.X_RDK_WanManager.Interface.1.VirtualInterface.1.IP.Mode
    ...

Usage:
    python3 tools/extract_datamodels.py [OPTIONS]

Options:
    --repo-root PATH     Path to the repo root (default: two levels above this script)
    --instances N        Number of instances to expand for each table (default: 2)
    --output FORMAT      text (default) | dmcli | json | csv
    --xml v1|v2|both     Which XML file(s) to parse (default: both)

Examples:
    python3 tools/extract_datamodels.py
    python3 tools/extract_datamodels.py --instances 1 --output dmcli
    python3 tools/extract_datamodels.py --xml v2 --output csv > params.csv
    python3 tools/extract_datamodels.py --output json
"""

import argparse
import csv
import io
import json
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class DmParameter:
    dm_path: str       # Full path e.g. Device.X_RDK_WanManager.Interface.1.Selection.Enable
    param_name: str    # Short name e.g. Enable
    data_type: str     # e.g. boolean, string, unsignedInt, int
    writable: bool     # True if writable
    object_path: str   # Parent object path
    xml_file: str      # Which XML file it came from


@dataclass
class DataModelReport:
    parameters: List[DmParameter] = field(default_factory=list)


# ---------------------------------------------------------------------------
# XML parser
# ---------------------------------------------------------------------------

TABLE_TYPES = {"dynamicTable", "writableTable", "staticTable"}


def parse_type(raw_type: str) -> str:
    """Simplify the XML type string to a short readable form."""
    if not raw_type:
        return "string"
    raw = raw_type.strip()
    if raw.startswith("boolean"):
        return "boolean"
    if raw.startswith("unsignedInt") or raw.startswith("uint"):
        return "unsignedInt"
    if raw == "int":
        return "int"
    if raw.startswith("string"):
        if ":" in raw:
            return "string(mapped)"
        return "string"
    return raw.split(":")[0].split("[")[0].strip()


def parse_writable(elem) -> bool:
    w = elem.findtext("writable")
    if w is None:
        return False
    return w.strip().lower() == "true"


def collect_parameters(obj_elem, obj_path: str, xml_file: str,
                       results: List[DmParameter]):
    """Add all <parameter> children of this object element to results."""
    params_elem = obj_elem.find("parameters")
    if params_elem is None:
        return
    for param in params_elem.findall("parameter"):
        pname = (param.findtext("name") or "").strip()
        if not pname:
            continue
        raw_type = (param.findtext("type") or "string").strip()
        results.append(DmParameter(
            dm_path=f"{obj_path}.{pname}",
            param_name=pname,
            data_type=parse_type(raw_type),
            writable=parse_writable(param),
            object_path=obj_path,
            xml_file=xml_file,
        ))


def walk_objects(objects_elem, parent_path: str, instances: int,
                 xml_file: str, results: List[DmParameter]):
    """Recursively walk <objects><object>...</object></objects>."""
    if objects_elem is None:
        return
    for obj in objects_elem.findall("object"):
        obj_name = (obj.findtext("name") or "").strip()
        obj_type = (obj.findtext("objectType") or "object").strip()

        if obj_type in TABLE_TYPES:
            for idx in range(1, instances + 1):
                obj_path = f"{parent_path}.{obj_name}.{idx}"
                collect_parameters(obj, obj_path, xml_file, results)
                walk_objects(obj.find("objects"), obj_path, instances, xml_file, results)
        else:
            obj_path = f"{parent_path}.{obj_name}"
            collect_parameters(obj, obj_path, xml_file, results)
            walk_objects(obj.find("objects"), obj_path, instances, xml_file, results)


def parse_xml(xml_path: Path, instances: int) -> List[DmParameter]:
    """Parse one XML config file and return a flat list of DmParameter."""
    results = []
    xml_file = xml_path.name

    raw = xml_path.read_text(encoding="utf-8", errors="replace")
    # Strip <?ifdef ...?>, <?ifndef ...?>, <?else?>, <?endif?> processing instructions
    # which are RDK-specific and not valid XML.
    cleaned = re.sub(r'<\?(?:ifdef|ifndef|else|endif)[^?]*\?>', '', raw)

    try:
        root = ET.fromstring(cleaned)
    except ET.ParseError as e:
        print(f"WARNING: Could not parse {xml_path.name}: {e}", file=sys.stderr)
        return results

    top_objects = root.find("objects")
    if top_objects is None:
        return results

    for top_obj in top_objects.findall("object"):
        top_name = (top_obj.findtext("name") or "").strip()
        obj_path = f"Device.{top_name}"
        collect_parameters(top_obj, obj_path, xml_file, results)
        walk_objects(top_obj.find("objects"), obj_path, instances, xml_file, results)

    return results


# ---------------------------------------------------------------------------
# Main extractor
# ---------------------------------------------------------------------------

def extract_all(repo_root: Path, instances: int, xml_filter: str) -> DataModelReport:
    report = DataModelReport()
    seen = set()

    xml_map = {
        "v1": repo_root / "config" / "RdkWanManager.xml",
        "v2": repo_root / "config" / "RdkWanManager_v2.xml",
    }

    to_parse = []
    if xml_filter in ("v1", "both"):
        to_parse.append(xml_map["v1"])
    if xml_filter in ("v2", "both"):
        to_parse.append(xml_map["v2"])

    for xml_path in to_parse:
        if not xml_path.exists():
            print(f"WARNING: XML not found: {xml_path}", file=sys.stderr)
            continue
        print(f"[*] Parsing {xml_path.name} ...", file=sys.stderr)
        for p in parse_xml(xml_path, instances):
            if not p.dm_path.startswith("Device.X_RDK_WanManager"):
                continue
            if p.dm_path not in seen:
                seen.add(p.dm_path)
                report.parameters.append(p)

    # Sort alphabetically so output matches dmcli order
    report.parameters.sort(key=lambda p: p.dm_path)
    return report


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------

def format_text(report: DataModelReport) -> str:
    lines = [
        f"Device.X_RDK_WanManager.* Parameters — {len(report.parameters)} total",
        "=" * 80,
    ]
    for i, p in enumerate(report.parameters, start=1):
        rw = "RW" if p.writable else "RO"
        lines.append(f"  [{i:>3}]  {p.dm_path}")
        lines.append(f"          type={p.data_type:<22} {rw}  ({p.xml_file})")
    return "\n".join(lines)


def format_dmcli(report: DataModelReport) -> str:
    """Mirror dmcli eRT getv output style."""
    lines = []
    for i, p in enumerate(report.parameters, start=1):
        lines.append(f"Parameter {i:>4} name: {p.dm_path}")
        lines.append(f"               type:     {p.data_type}")
    return "\n".join(lines)


def format_json(report: DataModelReport) -> str:
    return json.dumps(asdict(report), indent=2)


def format_csv(report: DataModelReport) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["index", "dm_path", "param_name", "data_type",
                     "writable", "object_path", "xml_file"])
    for i, p in enumerate(report.parameters, start=1):
        writer.writerow([i, p.dm_path, p.param_name, p.data_type,
                         p.writable, p.object_path, p.xml_file])
    return buf.getvalue()


FORMATTERS = {
    "text":  format_text,
    "dmcli": format_dmcli,
    "json":  format_json,
    "csv":   format_csv,
}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    default_root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(
        description=(
            "Generate the full Device.X_RDK_WanManager.* parameter list "
            "from XML config files (matches dmcli output)."
        )
    )
    parser.add_argument(
        "--repo-root", default=str(default_root),
        help=f"Path to the repository root (default: {default_root})",
    )
    parser.add_argument(
        "--instances", type=int, default=2,
        help="Number of table instances to expand per table object (default: 2)",
    )
    parser.add_argument(
        "--output", choices=list(FORMATTERS.keys()), default="text",
        help="Output format: text (default), dmcli, json, csv",
    )
    parser.add_argument(
        "--xml", choices=["v1", "v2", "both"], default="both",
        help="Which XML file(s) to parse: v1, v2, or both (default: both)",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()

    if not repo_root.is_dir():
        print(f"ERROR: repo root not found: {repo_root}", file=sys.stderr)
        sys.exit(1)

    report = extract_all(repo_root, args.instances, args.xml)

    print(
        f"[*] Total parameters extracted: {len(report.parameters)}",
        file=sys.stderr,
    )

    print(FORMATTERS[args.output](report))


if __name__ == "__main__":
    main()
