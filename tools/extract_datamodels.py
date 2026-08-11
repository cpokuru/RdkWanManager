#!/usr/bin/env python3
"""
extract_datamodels.py
=====================
Extracts all datamodel paths under Device.X_RDK_WanManager.* from the
RdkWanManager source code.

Only #define macros whose string value starts with "Device.X_RDK_WanManager."
are reported — every other component's paths are ignored.

Usage:
    python3 tools/extract_datamodels.py [--repo-root <path>] [--output <text|json|csv>]

Examples:
    python3 tools/extract_datamodels.py
    python3 tools/extract_datamodels.py --output json
    python3 tools/extract_datamodels.py --output csv > datamodels.csv
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
# The only prefix we care about
# ---------------------------------------------------------------------------
WANMGR_DM_PREFIX = "Device.X_RDK_WanManager."


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class WanMgrDataModel:
    macro_name: str    # C macro name, e.g. WANMGR_CONFIG_WAN_CURRENTACTIVEINTERFACE
    dm_path: str       # DM path,  e.g. Device.X_RDK_WanManager.CurrentActiveInterface
    source_file: str   # relative path inside the repo
    line_number: int


@dataclass
class DataModelReport:
    datamodels: List[WanMgrDataModel] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def read_lines(path: Path) -> list:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []


# ---------------------------------------------------------------------------
# Extractor — every #define whose value starts with Device.X_RDK_WanManager.
# ---------------------------------------------------------------------------
# Matches:  #define  MACRO_NAME   "Device.X_RDK_WanManager...."
_RE_DM_DEFINE = re.compile(
    r'^\s*#\s*define\s+(\w+)\s+"(Device\.X_RDK_WanManager\.[^"]*)"'
)


def extract_wanmgr_datamodels(repo_root: Path) -> List[WanMgrDataModel]:
    results = []
    seen_paths = set()   # deduplicate by DM path value

    for fpath in sorted(repo_root.rglob("*.h")) + sorted(repo_root.rglob("*.c")):
        lines = read_lines(fpath)
        for lineno, line in enumerate(lines, start=1):
            m = _RE_DM_DEFINE.match(line)
            if m:
                macro = m.group(1)
                dm_path = m.group(2)
                if dm_path not in seen_paths:
                    seen_paths.add(dm_path)
                    results.append(WanMgrDataModel(
                        macro_name=macro,
                        dm_path=dm_path,
                        source_file=relative(fpath, repo_root),
                        line_number=lineno,
                    ))

    # Sort alphabetically by DM path for easy reading
    results.sort(key=lambda r: r.dm_path)
    return results


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------

def format_text(report: DataModelReport) -> str:
    lines = []
    lines.append(f"Device.X_RDK_WanManager.* Datamodels — {len(report.datamodels)} found")
    lines.append("=" * 80)
    for dm in report.datamodels:
        lines.append(f"  {dm.dm_path}")
        lines.append(f"      Macro : {dm.macro_name}")
        lines.append(f"      File  : {dm.source_file}:{dm.line_number}")
    return "\n".join(lines)


def format_json(report: DataModelReport) -> str:
    return json.dumps(asdict(report), indent=2)


def format_csv(report: DataModelReport) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["dm_path", "macro_name", "source_file", "line_number"])
    for dm in report.datamodels:
        writer.writerow([dm.dm_path, dm.macro_name, dm.source_file, dm.line_number])
    return buf.getvalue()


FORMATTERS = {"text": format_text, "json": format_json, "csv": format_csv}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    default_root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(
        description="Extract all Device.X_RDK_WanManager.* datamodel paths from source."
    )
    parser.add_argument(
        "--repo-root", default=str(default_root),
        help=f"Path to the repository root (default: {default_root})",
    )
    parser.add_argument(
        "--output", choices=list(FORMATTERS.keys()), default="text",
        help="Output format: text (default), json, csv",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()

    if not repo_root.is_dir():
        print(f"ERROR: repo root not found: {repo_root}", file=sys.stderr)
        sys.exit(1)

    print(f"[*] Scanning: {repo_root}", file=sys.stderr)

    report = DataModelReport()
    report.datamodels = extract_wanmgr_datamodels(repo_root)

    print(f"[*] Found {len(report.datamodels)} unique Device.X_RDK_WanManager.* paths",
          file=sys.stderr)

    print(FORMATTERS[args.output](report))


if __name__ == "__main__":
    main()
