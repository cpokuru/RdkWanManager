#!/usr/bin/env python3
"""
extract_datamodels.py
=====================
Extracts available TR-181 datamodel information from the RdkWanManager source code.

What it collects:
  1. Registered DML handler functions   (from wanmgr_plugin_main.c  RegisterFunction calls)
  2. PSM / TR-181 datamodel path macros (from dmsb_tr181_psm_definitions.h  #define strings)
  3. DML struct/enum type definitions    (from wanmgr_dml.h  typedef struct/enum blocks)
  4. Datamodel paths defined as string   (all "Device.*" string literals in .c/.h files)

Usage:
    python3 tools/extract_datamodels.py [--repo-root <path>] [--output <json|text|csv>]

    Defaults: repo root = directory two levels above this script,
              output format = text (printed to stdout).

Examples:
    python3 tools/extract_datamodels.py
    python3 tools/extract_datamodels.py --repo-root /path/to/RdkWanManager --output json
    python3 tools/extract_datamodels.py --output csv > datamodels.csv
"""

import argparse
import csv
import io
import json
import os
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Dict, Optional


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class RegisteredFunction:
    name: str          # first string argument to RegisterFunction (the handler name)
    c_symbol: str      # second argument (the C function pointer)
    source_file: str
    line_number: int


@dataclass
class PsmPathMacro:
    macro_name: str    # e.g. PSM_WANMANAGER_WANENABLE
    path_value: str    # e.g. "dmsb.wanmanager.wanenable"
    source_file: str
    line_number: int


@dataclass
class TypeDefinition:
    kind: str          # "struct" | "enum"
    name: str
    source_file: str
    line_number: int
    members: List[str] = field(default_factory=list)


@dataclass
class DevicePath:
    path: str          # e.g. "Device.IP.InterfaceNumberOfEntries"
    source_file: str
    line_number: int


@dataclass
class DataModelReport:
    registered_functions: List[RegisteredFunction] = field(default_factory=list)
    psm_path_macros: List[PsmPathMacro] = field(default_factory=list)
    type_definitions: List[TypeDefinition] = field(default_factory=list)
    device_paths: List[DevicePath] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def iter_source_files(repo_root: Path, extensions=(".c", ".h")):
    """Yield all source files under repo_root with the given extensions."""
    for ext in extensions:
        yield from repo_root.rglob(f"*{ext}")


def relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def read_lines(path: Path):
    """Read file lines, ignoring encoding errors."""
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []


# ---------------------------------------------------------------------------
# Extractor 1 – RegisterFunction calls
# ---------------------------------------------------------------------------
# Pattern: pPlugInfo->RegisterFunction(pPlugInfo->hContext, "HandlerName", CSymbol);
_RE_REGISTER = re.compile(
    r'RegisterFunction\s*\(\s*\w+\s*,\s*"([^"]+)"\s*,\s*(\w+)\s*\)'
)


def extract_registered_functions(repo_root: Path) -> List[RegisteredFunction]:
    results = []
    for fpath in repo_root.rglob("wanmgr_plugin_main.c"):
        lines = read_lines(fpath)
        for lineno, line in enumerate(lines, start=1):
            m = _RE_REGISTER.search(line)
            if m:
                results.append(RegisteredFunction(
                    name=m.group(1),
                    c_symbol=m.group(2),
                    source_file=relative(fpath, repo_root),
                    line_number=lineno,
                ))
    return results


# ---------------------------------------------------------------------------
# Extractor 2 – PSM / TR-181 path macros
# ---------------------------------------------------------------------------
# Pattern: #define PSM_WANMANAGER_xxx   "dmsb.wanmanager..."
_RE_PSM_MACRO = re.compile(
    r'^\s*#\s*define\s+(PSM_\w+|DMSB_\w+|PAM_\w+|WAN_\w+_PARAM\w*)\s+"([^"]+)"'
)

# Also pick up generic Device.xxx defines
_RE_DEVICE_MACRO = re.compile(
    r'^\s*#\s*define\s+(\w+)\s+"(Device\.[^"]+)"'
)


def extract_psm_macros(repo_root: Path) -> List[PsmPathMacro]:
    results = []
    seen = set()
    for fpath in iter_source_files(repo_root):
        lines = read_lines(fpath)
        for lineno, line in enumerate(lines, start=1):
            for pattern in (_RE_PSM_MACRO, _RE_DEVICE_MACRO):
                m = pattern.match(line)
                if m:
                    key = (m.group(1), m.group(2))
                    if key not in seen:
                        seen.add(key)
                        results.append(PsmPathMacro(
                            macro_name=m.group(1),
                            path_value=m.group(2),
                            source_file=relative(fpath, repo_root),
                            line_number=lineno,
                        ))
    return results


# ---------------------------------------------------------------------------
# Extractor 3 – typedef struct / typedef enum
# ---------------------------------------------------------------------------
_RE_TYPEDEF_START = re.compile(
    r'^\s*typedef\s+(struct|enum)\s*(?:_[\w]+)?\s*\{?'
)
_RE_TYPEDEF_END_NAME = re.compile(
    r'\}\s*([\w]+)\s*;'
)
_RE_MEMBER_LINE = re.compile(r'^\s*(\w[\w\s\*\[\]]+)\s*;')
_RE_ENUM_MEMBER = re.compile(r'^\s*([A-Z_][A-Z0-9_]+)\s*(?:=\s*[^,]+)?\s*,?')


def extract_type_definitions(repo_root: Path) -> List[TypeDefinition]:
    results = []
    for fpath in iter_source_files(repo_root, extensions=(".h",)):
        lines = read_lines(fpath)
        i = 0
        while i < len(lines):
            line = lines[i]
            m = _RE_TYPEDEF_START.match(line)
            if m:
                kind = m.group(1)
                start_line = i + 1
                members = []
                # Scan forward until we find the closing } TypeName;
                depth = line.count("{") - line.count("}")
                j = i + 1
                while j < len(lines):
                    inner = lines[j]
                    depth += inner.count("{") - inner.count("}")
                    end_m = _RE_TYPEDEF_END_NAME.search(inner)
                    if end_m and depth <= 0:
                        type_name = end_m.group(1)
                        td = TypeDefinition(
                            kind=kind,
                            name=type_name,
                            source_file=relative(fpath, repo_root),
                            line_number=start_line,
                            members=members,
                        )
                        results.append(td)
                        i = j
                        break
                    # collect members
                    if kind == "struct":
                        mm = _RE_MEMBER_LINE.match(inner)
                        if mm and "{" not in inner and "}" not in inner:
                            members.append(inner.strip().rstrip(";"))
                    elif kind == "enum":
                        em = _RE_ENUM_MEMBER.match(inner)
                        if em:
                            members.append(em.group(1))
                    j += 1
            i += 1
    return results


# ---------------------------------------------------------------------------
# Extractor 4 – "Device." string literals
# ---------------------------------------------------------------------------
_RE_DEVICE_STR = re.compile(r'"(Device\.[^"]{4,})"')


def extract_device_paths(repo_root: Path) -> List[DevicePath]:
    results = []
    seen = set()
    for fpath in iter_source_files(repo_root):
        lines = read_lines(fpath)
        for lineno, line in enumerate(lines, start=1):
            for m in _RE_DEVICE_STR.finditer(line):
                path = m.group(1)
                if path not in seen:
                    seen.add(path)
                    results.append(DevicePath(
                        path=path,
                        source_file=relative(fpath, repo_root),
                        line_number=lineno,
                    ))
    return results


# ---------------------------------------------------------------------------
# Report builders
# ---------------------------------------------------------------------------

def build_report(repo_root: Path) -> DataModelReport:
    report = DataModelReport()
    print("[*] Scanning registered DML handler functions ...", file=sys.stderr)
    report.registered_functions = extract_registered_functions(repo_root)

    print("[*] Scanning PSM / TR-181 path macros ...", file=sys.stderr)
    report.psm_path_macros = extract_psm_macros(repo_root)

    print("[*] Scanning typedef struct / enum definitions ...", file=sys.stderr)
    report.type_definitions = extract_type_definitions(repo_root)

    print("[*] Scanning Device.* string literals ...", file=sys.stderr)
    report.device_paths = extract_device_paths(repo_root)

    return report


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------

def _section(title: str, width: int = 80) -> str:
    return f"\n{'='*width}\n  {title}\n{'='*width}"


def format_text(report: DataModelReport) -> str:
    out = []

    out.append(_section("1. Registered DML Handler Functions"))
    out.append(f"  Total: {len(report.registered_functions)}\n")
    for rf in report.registered_functions:
        out.append(f"  [{rf.line_number:4d}]  {rf.name:<55s}  C: {rf.c_symbol}")
        out.append(f"         File: {rf.source_file}")

    out.append(_section("2. PSM / TR-181 Path Macros"))
    out.append(f"  Total: {len(report.psm_path_macros)}\n")
    for pm in report.psm_path_macros:
        out.append(f"  {pm.macro_name}")
        out.append(f"    -> \"{pm.path_value}\"")
        out.append(f"    File: {pm.source_file}:{pm.line_number}")

    out.append(_section("3. Datamodel Type Definitions (struct / enum)"))
    out.append(f"  Total: {len(report.type_definitions)}\n")
    for td in report.type_definitions:
        out.append(f"  typedef {td.kind} {td.name}  ({td.source_file}:{td.line_number})")
        if td.members:
            for mb in td.members[:10]:          # first 10 to keep output readable
                out.append(f"    - {mb}")
            if len(td.members) > 10:
                out.append(f"    ... and {len(td.members)-10} more members")

    out.append(_section("4. Device.* Datamodel Paths (string literals)"))
    out.append(f"  Total: {len(report.device_paths)}\n")
    for dp in report.device_paths:
        out.append(f"  {dp.path}")
        out.append(f"    File: {dp.source_file}:{dp.line_number}")

    return "\n".join(out)


def format_json(report: DataModelReport) -> str:
    def _serialise(obj):
        if hasattr(obj, "__dataclass_fields__"):
            return asdict(obj)
        raise TypeError(f"Not serialisable: {type(obj)}")

    return json.dumps(asdict(report), indent=2, default=_serialise)


def format_csv(report: DataModelReport) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["category", "name", "value", "source_file", "line_number"])

    for rf in report.registered_functions:
        writer.writerow(["RegisteredFunction", rf.name, rf.c_symbol,
                         rf.source_file, rf.line_number])
    for pm in report.psm_path_macros:
        writer.writerow(["PsmPathMacro", pm.macro_name, pm.path_value,
                         pm.source_file, pm.line_number])
    for td in report.type_definitions:
        writer.writerow(["TypeDefinition", f"{td.kind} {td.name}",
                         "|".join(td.members), td.source_file, td.line_number])
    for dp in report.device_paths:
        writer.writerow(["DevicePath", dp.path, "", dp.source_file, dp.line_number])

    return buf.getvalue()


FORMATTERS = {
    "text": format_text,
    "json": format_json,
    "csv":  format_csv,
}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    default_root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(
        description="Extract TR-181 datamodel information from RdkWanManager source."
    )
    parser.add_argument(
        "--repo-root",
        default=str(default_root),
        help=f"Path to the repository root (default: {default_root})",
    )
    parser.add_argument(
        "--output",
        choices=list(FORMATTERS.keys()),
        default="text",
        help="Output format (default: text)",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()

    if not repo_root.is_dir():
        print(f"ERROR: repo root not found: {repo_root}", file=sys.stderr)
        sys.exit(1)

    print(f"[*] Repository root : {repo_root}", file=sys.stderr)

    report = build_report(repo_root)

    print(
        f"[*] Summary: {len(report.registered_functions)} handlers | "
        f"{len(report.psm_path_macros)} PSM macros | "
        f"{len(report.type_definitions)} type defs | "
        f"{len(report.device_paths)} Device.* paths",
        file=sys.stderr,
    )

    formatter = FORMATTERS[args.output]
    print(formatter(report))


if __name__ == "__main__":
    main()
