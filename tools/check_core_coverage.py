"""Enforce aggregate line coverage for cleaning/security core modules."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


CORE_MODULES = {
    "src/vietclean/config.py",
    "src/vietclean/domain.py",
    "src/vietclean/pipeline.py",
    "src/vietclean/profiles.py",
    "src/vietclean/quality.py",
    "src/vietclean/report.py",
    "src/vietclean/text.py",
    "src/vietclean/security/formulas.py",
    "src/vietclean/security/pii.py",
    "src/vietclean/security/resources.py",
    "src/vietclean/security/sql.py",
}


def core_coverage(payload: dict[str, Any]) -> tuple[float, list[str]]:
    """Return aggregate core percent and missing module names from coverage JSON."""

    files = {
        str(name).replace("\\", "/"): details
        for name, details in payload.get("files", {}).items()
    }
    missing = sorted(CORE_MODULES - set(files))
    covered = 0
    statements = 0
    for name in sorted(CORE_MODULES & set(files)):
        summary = files[name].get("summary", {})
        covered += int(summary.get("covered_lines", 0))
        statements += int(summary.get("num_statements", 0))
    percent = 100.0 if statements == 0 and not missing else (100.0 * covered / statements if statements else 0.0)
    return percent, missing


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("coverage_json", type=Path)
    parser.add_argument("--minimum", type=float, default=90.0)
    args = parser.parse_args()
    payload = json.loads(args.coverage_json.read_text(encoding="utf-8"))
    percent, missing = core_coverage(payload)
    if missing:
        print(f"Core coverage thiếu module: {', '.join(missing)}")
        return 1
    print(f"Core aggregate line coverage: {percent:.2f}% (required {args.minimum:.2f}%)")
    return 0 if percent >= args.minimum else 1


if __name__ == "__main__":
    raise SystemExit(main())
