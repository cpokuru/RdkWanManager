#!/usr/bin/env python3
"""
extract_datamodels.py
=====================
Extracts TR-181 datamodel information OWNED by the RdkWanManager component.

Only paths under "Device.X_RDK_WanManager.*" are reported — paths belonging
to other components (VlanAgent, CellularManager, EthAgent, PAM, etc.) are
intentionally excluded.

What it collects:
  1. Registered DML handler functions  (wanmgr_plugin_main.c  → RegisterFunction)
  2. WanManager-owned Device.X_RDK_WanManager.* path macros  (#define strings)
  3. WanManager-owned PSM datamodel path macros  (dmsb.wanmanager.* #define strings)
  4. typedef struct / enum definitions  (wanmgr_dml.h and related headers)

Usage:
    python3 tools/extract_datamodels.py [--repo-root <path>] [--output <json|text|csv>]

Examples:
    python3 tools/extract_datamodels.py
    python3 tools/extract_datamodels.py --output json
    python3 tools/extract_datamodels.py --output csv > datamodels.csv
    python3 tools/extract_datamodels.py --repo-root /path/to/RdkWanManager --output json
"""

import argparse
import csv
import io
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List


# ---------------------------------------------------------------------------
# Ownership filter — only these prefixes are reported as WanManager-owned
# ---------------------------------------------------------------------------
# DM paths owned by this component
OWNED_DM_PREFIXES = (
    "Device.X_RDK_WanManager.",
)

# PSM paths owned by this component
OWNED_PSM_PREFIXES = (
    "dmsb.wanmanager.",
    "dmsb.selfheal.",          # used internally
    "dmsb.Mesh.WAN.",          # WAN mesh config owned here
)

# Source files that define this component's own DM paths / handlers
OWNED_SOURCE_FILES = (
    "wanmgr_plugin_main.c",
    "wanmgr_dml.h",
    "wanmgr_rbus_handler_apis.h",
    "wanmgr_rdkbus_utils.h",
    "wanmgr_rdkbus_common.h",
    "dmsb_tr181_psm_definitions.h",
    "wanmgr_dml_apis.h",
    "wanmgr_dml_iface_apis.h",
    "wanmgr_dml_iface_v2_apis.h",
    "wanmgr_dml_dhcpv4.h",
    "wanmgr_dml_dhcpv6.h",
    "wanmgr_dml_map.h",
    "wanmgr_dml_dslite_apis.h",
    "wanmgr_plugin_main_apis.h",
)


def is_owned_dm_path(path: str) -> bool:
    return any(path.startswith(p) for p in OWNED_DM_PREFIXES)


def is_owned_psm_path(path: str) -> bool:
    return any(path.startswith(p) for p in OWNED_PSM_PREFIXES)


def is_owned_source(fpath: Path) -> bool:
    return fpath.name in OWNED_SOURCE_FILES


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class RegisteredFunction:
    name: str          # handler name string passed to RegisterFunction
    c_symbol: str      # C function pointer name
    source_file: str
    line_number: int


@dataclass
class DmPathMacro:
    macro_name: str    # e.g. WANMGR_CONFIG_WAN_CURRENTACTIVEINTERFACE
    path_value: str    # e.g. "Device.X_RDK_WanManager.CurrentActiveInterface"
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
class DataModelReport:
    registered_functions: List[RegisteredFunction] = field(default_factory=list)
    dm_path_macros: List[DmPathMacro] = field(default_factory=list)
    psm_path_macros: List[PsmPathMacro] = field(default_factory=list)
    type_definitions: List[TypeDefinition] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def read_lines(path: Path):
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []


def iter_owned_sources(repo_root: Path, extensions=(".c", ".h")):
    """Yield only source files that belong to this component."""
    for ext in extensions:
        for fpath in repo_root.rglob(f"*{ext}"):
            if is_owned_source(fpath):
                yield fpath


# ---------------------------------------------------------------------------
# Extractor 1 — Registered DML handler functions
# ---------------------------------------------------------------------------
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
# Extractor 2 — Device.X_RDK_WanManager.* path macros
# ---------------------------------------------------------------------------
_RE_DM_DEFINE = re.compile(
    r'^\s*#\s*define\s+(\w+)\s+"(Device\.[^"]+)"'
)


def extract_dm_path_macros(repo_root: Path) -> List[DmPathMacro]:
    results = []
    seen = set()
    for fpath in iter_owned_sources(repo_root):
        lines = read_lines(fpath)
        for lineno, line in enumerate(lines, start=1):
            m = _RE_DM_DEFINE.match(line)
            if m:
                path_val = m.group(2)
                # Only keep WanManager-owned paths
                if not is_owned_dm_path(path_val):
                    continue
                key = (m.group(1), path_val)
                if key not in seen:
                    seen.add(key)
                    results.append(DmPathMacro(
                        macro_name=m.group(1),
                        path_value=path_val,
                        source_file=relative(fpath, repo_root),
                        line_number=lineno,
                    ))
    return results


# ---------------------------------------------------------------------------
# Extractor 3 — PSM datamodel path macros (dmsb.wanmanager.*)
# ---------------------------------------------------------------------------
_RE_PSM_DEFINE = re.compile(
    r'^\s*#\s*define\s+(\w+)\s+"(dmsb\.[^"]+)"'
)


def extract_psm_path_macros(repo_root: Path) -> List[PsmPathMacro]:
    results = []
    seen = set()
    for fpath in iter_owned_sources(repo_root):
        lines = read_lines(fpath)
        for lineno, line in enumerate(lines, start=1):
            m = _RE_PSM_DEFINE.match(line)
            if m:
                path_val = m.group(2)
                if not is_owned_psm_path(path_val):
                    continue
                key = (m.group(1), path_val)
                if key not in seen:
                    seen.add(key)
                    results.append(PsmPathMacro(
                        macro_name=m.group(1),
                        path_value=path_val,
                        source_file=relative(fpath, repo_root),
                        line_number=lineno,
                    ))
    return results


# ---------------------------------------------------------------------------
# Extractor 4 — typedef struct / enum from wanmgr_dml.h and related headers
# ---------------------------------------------------------------------------
_RE_TYPEDEF_START = re.compile(
    r'^\s*typedef\s+(struct|enum)\b'
)
_RE_TYPEDEF_END_NAME = re.compile(
    r'\}\s*([\w]+)\s*;'
)
_RE_MEMBER_LINE = re.compile(r'^\s*(\w[\w\s\*\[\]]+)\s*;')
_RE_ENUM_MEMBER = re.compile(r'^\s*([A-Z_][A-Z0-9_]+)\s*(?:=\s*[^,]+)?\s*,?')

# Only extract types from these specific headers (the DML data model headers)
TYPE_EXTRACT_FILES = {
    "wanmgr_dml.h",
    "wanmgr_dml_apis.h",
    "wanmgr_dml_iface_apis.h",
    "wanmgr_dml_iface_v2_apis.h",
    "wanmgr_dml_dhcpv4.h",
    "wanmgr_dml_dhcpv6.h",
    "wanmgr_dml_map.h",
    "wanmgr_dml_dslite_apis.h",
}


def extract_type_definitions(repo_root: Path) -> List[TypeDefinition]:
    results = []
    for fpath in repo_root.rglob("*.h"):
        if fpath.name not in TYPE_EXTRACT_FILES:
            continue
        lines = read_lines(fpath)
        i = 0
        while i < len(lines):
            line = lines[i]
            m = _RE_TYPEDEF_START.match(line)
            if m:
                kind = m.group(1)
                start_line = i + 1
                members = []
                depth = line.count("{") - line.count("}")
                j = i + 1
                while j < len(lines):
                    inner = lines[j]
                    depth += inner.count("{") - inner.count("}")
                    end_m = _RE_TYPEDEF_END_NAME.search(inner)
                    if end_m and depth <= 0:
                        type_name = end_m.group(1)
                        results.append(TypeDefinition(
                            kind=kind,
                            name=type_name,
                            source_file=relative(fpath, repo_root),
                            line_number=start_line,
                            members=members,
                        ))
                        i = j
                        break
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
# Build full report
# ---------------------------------------------------------------------------

def build_report(repo_root: Path) -> DataModelReport:
    report = DataModelReport()

    print("[*] Extracting registered DML handler functions ...", file=sys.stderr)
    report.registered_functions = extract_registered_functions(repo_root)

    print("[*] Extracting Device.X_RDK_WanManager.* path macros ...", file=sys.stderr)
    report.dm_path_macros = extract_dm_path_macros(repo_root)

    print("[*] Extracting PSM (dmsb.wanmanager.*) path macros ...", file=sys.stderr)
    report.psm_path_macros = extract_psm_path_macros(repo_root)

    print("[*] Extracting DML type definitions (struct/enum) ...", file=sys.stderr)
    report.type_definitions = extract_type_definitions(repo_root)

    return report


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------

def _sep(title: str, width: int = 80) -> str:
    return f"\n{'='*width}\n  {title}\n{'='*width}"


def format_text(report: DataModelReport) -> str:
    out = []

    out.append(_sep(f"1. Registered DML Handler Functions  ({len(report.registered_functions)} total)"))
    for rf in report.registered_functions:
        out.append(f"  {rf.name:<60s}  [{rf.c_symbol}]")
        out.append(f"      {rf.source_file}:{rf.line_number}")

    out.append(_sep(f"2. Device.X_RDK_WanManager.* DM Path Macros  ({len(report.dm_path_macros)} total)"))
    for dm in report.dm_path_macros:
        out.append(f"  {dm.macro_name}")
        out.append(f"      -> \"{dm.path_value}\"")
        out.append(f"      {dm.source_file}:{dm.line_number}")

    out.append(_sep(f"3. PSM Path Macros (dmsb.wanmanager.*)  ({len(report.psm_path_macros)} total)"))
    for pm in report.psm_path_macros:
        out.append(f"  {pm.macro_name}")
        out.append(f"      -> \"{pm.path_value}\"")
        out.append(f"      {pm.source_file}:{pm.line_number}")

    out.append(_sep(f"4. DML Type Definitions (struct/enum)  ({len(report.type_definitions)} total)"))
    for td in report.type_definitions:
        out.append(f"  typedef {td.kind} {td.name}  ({td.source_file}:{td.line_number})")
        for mb in td.members[:8]:
            out.append(f"      - {mb}")
        if len(td.members) > 8:
            out.append(f"      ... +{len(td.members)-8} more")

    return "\n".join(out)


def format_json(report: DataModelReport) -> str:
    return json.dumps(asdict(report), indent=2)


def format_csv(report: DataModelReport) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["category", "name", "value", "source_file", "line_number"])
    for rf in report.registered_functions:
        writer.writerow(["RegisteredFunction", rf.name, rf.c_symbol, rf.source_file, rf.line_number])
    for dm in report.dm_path_macros:
        writer.writerow(["DmPathMacro", dm.macro_name, dm.path_value, dm.source_file, dm.line_number])
    for pm in report.psm_path_macros:
        writer.writerow(["PsmPathMacro", pm.macro_name, pm.path_value, pm.source_file, pm.line_number])
    for td in report.type_definitions:
        writer.writerow(["TypeDefinition", f"{td.kind} {td.name}", "|".join(td.members), td.source_file, td.line_number])
    return buf.getvalue()


FORMATTERS = {"text": format_text, "json": format_json, "csv": format_csv}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    default_root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(
        description=(
            "Extract TR-181 datamodels OWNED by RdkWanManager "
            "(Device.X_RDK_WanManager.* only)."
        )
    )
    parser.add_argument(
        "--repo-root", default=str(default_root),
        help=f"Path to the repository root (default: {default_root})",
    )
    parser.add_argument(
        "--output", choices=list(FORMATTERS.keys()), default="text",
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
        f"\n[*] Summary:"
        f"\n    {len(report.registered_functions):>4}  Registered DML handler functions"
        f"\n    {len(report.dm_path_macros):>4}  Device.X_RDK_WanManager.* path macros"
        f"\n    {len(report.psm_path_macros):>4}  PSM (dmsb.wanmanager.*) path macros"
        f"\n    {len(report.type_definitions):>4}  DML type definitions (struct/enum)",
        file=sys.stderr,
    )

    print(FORMATTERS[args.output](report))


if __name__ == "__main__":
    main()
