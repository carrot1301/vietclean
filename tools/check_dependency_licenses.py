"""Audit installed runtime dependency licenses against a conservative policy."""

from __future__ import annotations

import argparse
from collections import deque
from importlib import metadata
import re


_DENIED_MARKERS = ("AGPL", "GPL-", "SSPL", "BUSINESS SOURCE", "PROPRIETARY")
_KNOWN_PERMISSIVE = (
    "MIT",
    "APACHE",
    "BSD",
    "ISC",
    "PSF",
    "PYTHON SOFTWARE FOUNDATION",
    "MPL-2.0",
    "ZPL",
    "HPND",
)


def _canonical_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _dependency_name(requirement: str) -> str | None:
    if re.search(r"\bextra\s*==", requirement, flags=re.IGNORECASE):
        return None
    match = re.match(r"\s*([A-Za-z0-9_.-]+)", requirement)
    return _canonical_name(match.group(1)) if match else None


def _license_evidence(distribution: metadata.Distribution) -> list[str]:
    evidence: list[str] = []
    expression = distribution.metadata.get("License-Expression")
    if expression and expression.strip() and expression.strip().upper() != "UNKNOWN":
        evidence.append(expression.strip())
    legacy = distribution.metadata.get("License")
    if (
        legacy
        and legacy.strip()
        and legacy.strip().upper() != "UNKNOWN"
        and len(legacy.strip()) <= 200
    ):
        evidence.append(legacy.strip())
    evidence.extend(
        classifier.removeprefix("License :: ")
        for classifier in distribution.metadata.get_all("Classifier") or []
        if classifier.startswith("License ::")
    )
    return list(dict.fromkeys(evidence))


def audit_runtime_licenses(root_package: str) -> tuple[list[str], list[str]]:
    """Return human-readable accepted entries and policy failures."""

    installed: dict[str, metadata.Distribution] = {}
    for distribution in metadata.distributions():
        name = distribution.metadata.get("Name")
        if name:
            installed[_canonical_name(name)] = distribution
    root = _canonical_name(root_package)
    if root not in installed:
        return [], [f"Package gốc {root_package!r} chưa được cài."]

    queue: deque[str] = deque([root])
    visited: set[str] = set()
    accepted: list[str] = []
    errors: list[str] = []
    while queue:
        name = queue.popleft()
        if name in visited:
            continue
        visited.add(name)
        distribution = installed.get(name)
        if distribution is None:
            continue
        if name != root:
            evidence = _license_evidence(distribution)
            combined = " | ".join(evidence).upper()
            if not evidence:
                errors.append(f"{name}=={distribution.version}: thiếu license metadata")
            elif any(marker in combined for marker in _DENIED_MARKERS):
                errors.append(f"{name}=={distribution.version}: license cần legal review: {evidence}")
            elif not any(marker in combined for marker in _KNOWN_PERMISSIVE):
                errors.append(f"{name}=={distribution.version}: license chưa nằm trong policy: {evidence}")
            else:
                accepted.append(f"{name}=={distribution.version}: {' | '.join(evidence)}")
        for requirement in distribution.requires or []:
            dependency = _dependency_name(requirement)
            if dependency is not None and dependency in installed:
                queue.append(dependency)
    return sorted(accepted), sorted(errors)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root-package", default="vietclean")
    args = parser.parse_args()
    accepted, errors = audit_runtime_licenses(args.root_package)
    for entry in accepted:
        print(f"[LICENSE-OK] {entry}")
    for error in errors:
        print(f"[LICENSE-REVIEW] {error}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
