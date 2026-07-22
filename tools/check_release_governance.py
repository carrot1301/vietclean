"""Fail a release until repository-specific governance is configured."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys


_TAG_RE = re.compile(r"^v(?P<version>0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_OWNER_RE = re.compile(
    r"^\S+\s+@(?P<owner>[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})(?:/[A-Za-z0-9_.-]+)?)"
)
_PLACEHOLDERS = {"owner", "username", "user", "org/team", "organization/team"}


def active_codeowners(path: Path) -> list[str]:
    """Return non-placeholder owner handles from active CODEOWNERS rules."""

    owners: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _OWNER_RE.match(line)
        if match is None:
            continue
        owner = match.group("owner")
        if owner.casefold() not in _PLACEHOLDERS and "example" not in owner.casefold():
            owners.append(owner)
    return owners


def project_version(pyproject: Path) -> str:
    """Read the static PEP 621 version without importing build code."""

    in_project = False
    for raw_line in pyproject.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith("["):
            in_project = line == "[project]"
            continue
        if in_project:
            match = re.fullmatch(r'version\s*=\s*"([^"]+)"', line)
            if match:
                return match.group(1)
    raise ValueError("Không tìm thấy [project].version tĩnh trong pyproject.toml.")


def validate_release(root: Path, tag: str) -> list[str]:
    """Return all release-governance errors without changing the repository."""

    errors: list[str] = []
    if _TAG_RE.fullmatch(tag) is None:
        errors.append("Release tag phải có dạng vMAJOR.MINOR.PATCH.")
    else:
        version = project_version(root / "pyproject.toml")
        if tag.removeprefix("v") != version:
            errors.append(f"Tag {tag} không khớp project version {version}.")

    codeowners = root / ".github" / "CODEOWNERS"
    if not codeowners.is_file() or not active_codeowners(codeowners):
        errors.append(
            "CODEOWNERS chưa có rule với GitHub account/team thật; release bị chặn có chủ đích."
        )

    issue_config = root / ".github" / "ISSUE_TEMPLATE" / "config.yml"
    if not issue_config.is_file() or "blank_issues_enabled:" not in issue_config.read_text(
        encoding="utf-8"
    ):
        errors.append("ISSUE_TEMPLATE/config.yml chưa có cấu hình hợp lệ.")
    return errors


def main() -> int:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--tag", required=True)
    args = parser.parse_args()
    errors = validate_release(args.root.resolve(), args.tag)
    if errors:
        for error in errors:
            print(f"[RELEASE-GATE] {error}")
        return 1
    print("Release governance gate: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
