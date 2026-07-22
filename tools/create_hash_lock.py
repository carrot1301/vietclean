"""Create a pip ``--require-hashes`` lock from a resolved wheelhouse."""

from __future__ import annotations

import argparse
from collections import defaultdict
from email.parser import BytesParser
import hashlib
from pathlib import Path
import re
from typing import DefaultDict
from zipfile import BadZipFile, ZipFile


def _canonical_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _wheel_identity(path: Path) -> tuple[str, str]:
    try:
        with ZipFile(path) as archive:
            metadata_names = [
                name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
            ]
            if len(metadata_names) != 1:
                raise ValueError(f"Wheel không có đúng một METADATA: {path.name}")
            package_metadata = BytesParser().parsebytes(archive.read(metadata_names[0]))
    except BadZipFile as exc:
        raise ValueError(f"Wheel không hợp lệ: {path.name}") from exc
    name, version = package_metadata.get("Name"), package_metadata.get("Version")
    if not name or not version:
        raise ValueError(f"Wheel thiếu Name/Version: {path.name}")
    return _canonical_name(name), version


def build_lock(wheelhouse: Path) -> str:
    """Return deterministic hash-locked requirements for every wheel."""

    packages: DefaultDict[tuple[str, str], list[str]] = defaultdict(list)
    versions_by_name: DefaultDict[str, set[str]] = defaultdict(set)
    wheels = sorted(wheelhouse.glob("*.whl"), key=lambda item: item.name.casefold())
    if not wheels:
        raise ValueError(f"Không tìm thấy wheel trong {wheelhouse}.")
    for wheel in wheels:
        name, version = _wheel_identity(wheel)
        digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
        packages[(name, version)].append(digest)
        versions_by_name[name].add(version)
    conflicts = {name: versions for name, versions in versions_by_name.items() if len(versions) > 1}
    if conflicts:
        raise ValueError(f"Wheelhouse chứa nhiều version cho cùng package: {conflicts}")

    lines = [
        "# Generated from a resolved, platform-specific wheelhouse.",
        "# Install with: pip install --require-hashes -r <this-file>",
    ]
    for (name, version), digests in sorted(packages.items()):
        hashes = " ".join(f"--hash=sha256:{digest}" for digest in sorted(set(digests)))
        lines.append(f"{name}=={version} {hashes}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("wheelhouse", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    content = build_lock(args.wheelhouse.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(content, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
