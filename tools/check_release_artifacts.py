"""Reject unsafe or accidentally sensitive files in release archives."""

from __future__ import annotations

import argparse
from pathlib import Path, PurePosixPath
import tarfile
from zipfile import BadZipFile, ZipFile


_FORBIDDEN_NAMES = {
    ".env",
    "credentials.json",
    "id_dsa",
    "id_ed25519",
    "id_rsa",
    "secrets.json",
}
_FORBIDDEN_SUFFIXES = {
    ".db",
    ".db3",
    ".key",
    ".p12",
    ".pem",
    ".pfx",
    ".sqlite",
    ".sqlite3",
    ".xls",
    ".xlsm",
    ".xlsx",
}
_MAX_ENTRIES = 20_000
_MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024


def _validate_member(name: str) -> str | None:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts:
        return f"archive path không an toàn: {name!r}"
    lowered = [part.casefold() for part in path.parts]
    if "__pycache__" in lowered or path.suffix.casefold() in {".pyc", ".pyo"}:
        return f"bytecode/cache không được đóng gói: {name!r}"
    basename = path.name.casefold()
    if basename in _FORBIDDEN_NAMES or (
        basename.startswith(".env.") and basename != ".env.example"
    ):
        return f"file secret/config cục bộ không được đóng gói: {name!r}"
    if path.suffix.casefold() in _FORBIDDEN_SUFFIXES:
        return f"data/key artifact không được đóng gói: {name!r}"
    return None


def inspect_artifact(path: Path) -> list[str]:
    """Return archive policy violations without extracting any member."""

    errors: list[str] = []
    names: list[str] = []
    sizes: list[int] = []
    try:
        if path.suffix.casefold() == ".whl":
            with ZipFile(path) as archive:
                entries = archive.infolist()
                names = [entry.filename for entry in entries]
                sizes = [entry.file_size for entry in entries]
        elif path.name.casefold().endswith((".tar.gz", ".tgz")):
            with tarfile.open(path, mode="r:gz") as archive:
                entries = archive.getmembers()
                for entry in entries:
                    if entry.issym() or entry.islnk():
                        errors.append(f"archive link không được phép: {entry.name!r}")
                    names.append(entry.name)
                    sizes.append(entry.size)
        else:
            return [f"artifact không được hỗ trợ: {path.name}"]
    except (BadZipFile, OSError, tarfile.TarError) as exc:
        return [f"artifact không đọc được {path.name}: {type(exc).__name__}"]

    if len(names) > _MAX_ENTRIES:
        errors.append(f"artifact vượt {_MAX_ENTRIES} entries: {path.name}")
    if sum(sizes) > _MAX_UNCOMPRESSED_BYTES:
        errors.append(f"artifact bung nén vượt 200 MB: {path.name}")
    errors.extend(error for name in names if (error := _validate_member(name)) is not None)
    if not any(name.replace("\\", "/").endswith("vietclean/__init__.py") for name in names):
        errors.append(f"artifact thiếu package vietclean: {path.name}")
    if path.suffix.casefold() == ".whl" and not any(
        name.endswith(".dist-info/METADATA") for name in names
    ):
        errors.append(f"wheel thiếu METADATA: {path.name}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifacts", nargs="+", type=Path)
    args = parser.parse_args()
    errors: list[str] = []
    for artifact in args.artifacts:
        if not artifact.is_file():
            errors.append(f"artifact không tồn tại: {artifact}")
        else:
            errors.extend(inspect_artifact(artifact))
    for error in errors:
        print(f"[ARTIFACT-GATE] {error}")
    if errors:
        return 1
    print(f"Release artifact gate: OK ({len(args.artifacts)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
