"""Resource limits for untrusted local tabular files."""

from __future__ import annotations

from dataclasses import dataclass
import os
import stat
from pathlib import Path
from typing import Any, Mapping
from zipfile import BadZipFile, ZipFile

import pandas as pd

from ..exceptions import ResourceLimitError, UnsafeInputError


@dataclass(frozen=True, slots=True)
class ResourceLimits:
    """Conservative defaults that can be overridden explicitly by callers."""

    max_file_size_mb: int = 100
    max_rows: int = 500_000
    max_columns: int = 5_000
    max_cells: int = 5_000_000
    max_cell_length: int = 100_000
    max_memory_mb: int = 1_024
    max_archive_entries: int = 20_000
    max_archive_uncompressed_mb: int = 512
    max_excel_sheets: int = 100
    max_zip_ratio: float = 200.0
    max_rejected_rows: int = 100_000
    max_rejected_bytes_mb: int = 64
    max_operation_seconds: int = 900

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any] | None) -> "ResourceLimits":
        if values is None:
            return cls()
        allowed = set(cls.__dataclass_fields__)
        unknown = set(values) - allowed
        if unknown:
            raise ValueError(f"Resource limit không được hỗ trợ: {sorted(unknown)}")
        return cls(**dict(values))

    def __post_init__(self) -> None:
        for name in (
            "max_file_size_mb",
            "max_rows",
            "max_columns",
            "max_cells",
            "max_cell_length",
            "max_memory_mb",
            "max_archive_entries",
            "max_archive_uncompressed_mb",
            "max_excel_sheets",
            "max_rejected_rows",
            "max_rejected_bytes_mb",
            "max_operation_seconds",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} phải lớn hơn 0.")
        if (
            isinstance(self.max_zip_ratio, bool)
            or not isinstance(self.max_zip_ratio, (int, float))
            or self.max_zip_ratio <= 1
        ):
            raise ValueError("max_zip_ratio phải lớn hơn 1.")


def check_input_file(
    path: str | Path,
    limits: ResourceLimits | None = None,
    *,
    allow_symlinks: bool = False,
) -> Path:
    """Check size and suspicious ZIP expansion before pandas opens the file."""

    selected = limits or ResourceLimits()
    if not isinstance(allow_symlinks, bool):
        raise TypeError("allow_symlinks phải là true hoặc false.")
    candidate = Path(path)
    if "\x00" in str(candidate):
        raise UnsafeInputError("[VC-SAFE-001] Đường dẫn chứa null byte.")
    if candidate.exists() and not allow_symlinks and _is_link_or_reparse_point(candidate):
        raise UnsafeInputError(
            f"[VC-SAFE-001] Không đọc symbolic link/reparse point: {candidate.name}"
        )
    if not candidate.exists() or not candidate.is_file():
        return candidate
    size = candidate.stat().st_size
    if size > selected.max_file_size_mb * 1024 * 1024:
        raise ResourceLimitError(
            f"[VC-LIMIT-001] File vượt {selected.max_file_size_mb} MB: {candidate.name}"
        )
    suffix = candidate.suffix.lower()
    if suffix in {".xlsx", ".xlsm", ".xlsb"}:
        _check_zip_container(candidate, selected)
    elif suffix == ".xls":
        _check_magic(candidate, b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "Excel .xls")
    elif suffix in {".parquet", ".pq"}:
        _check_parquet_magic(candidate)
    elif suffix in {".db", ".db3", ".sqlite", ".sqlite3"}:
        _check_magic(candidate, b"SQLite format 3\x00", "SQLite")
    return candidate


def _check_zip_container(path: Path, limits: ResourceLimits) -> None:
    try:
        with ZipFile(path) as archive:
            entries = archive.infolist()
    except BadZipFile as exc:
        raise UnsafeInputError(f"[VC-SAFE-001] File Excel không phải ZIP hợp lệ: {path.name}") from exc
    if len(entries) > limits.max_archive_entries:
        raise ResourceLimitError(
            f"[VC-LIMIT-001] Excel có quá {limits.max_archive_entries} archive entries."
        )
    worksheet_entries = {
        entry.filename
        for entry in entries
        if entry.filename.casefold().startswith("xl/worksheets/")
        and entry.filename.casefold().endswith(".xml")
    }
    if len(worksheet_entries) > limits.max_excel_sheets:
        raise ResourceLimitError(
            f"[VC-LIMIT-001] Excel có quá {limits.max_excel_sheets} worksheet."
        )
    expanded = sum(entry.file_size for entry in entries)
    compressed = sum(max(entry.compress_size, 1) for entry in entries)
    if expanded > limits.max_archive_uncompressed_mb * 1024 * 1024:
        raise ResourceLimitError(
            f"[VC-LIMIT-001] Excel bung nén vượt {limits.max_archive_uncompressed_mb} MB."
        )
    # OpenPyXL materialises Python objects whose overhead can be many times the
    # worksheet XML. Reserve most of the budget for that expansion and for the
    # non-mutating cleaning/report copies made after load.
    if expanded > (limits.max_memory_mb * 1024 * 1024) // 8:
        raise ResourceLimitError(
            "[VC-LIMIT-001] Excel ước tính cần quá ngân sách RAM sau khi giải nén."
        )
    if expanded and expanded / compressed > limits.max_zip_ratio:
        raise ResourceLimitError(
            f"[VC-LIMIT-001] Excel có tỷ lệ nén nghi ngờ ({expanded / compressed:.1f}x)."
        )
    names = {entry.filename.casefold() for entry in entries}
    required = {"[content_types].xml", "_rels/.rels"}
    workbook_entry = (
        "xl/workbook.bin" if path.suffix.lower() == ".xlsb" else "xl/workbook.xml"
    )
    if not required.issubset(names) or workbook_entry not in names:
        raise UnsafeInputError(
            f"[VC-SAFE-001] Nội dung file không khớp phần mở rộng {path.suffix.lower()}."
        )


def _check_magic(path: Path, expected: bytes, label: str) -> None:
    with path.open("rb") as stream:
        prefix = stream.read(len(expected))
    if prefix != expected:
        raise UnsafeInputError(
            f"[VC-SAFE-001] Nội dung file không phải định dạng {label} hợp lệ."
        )


def _check_parquet_magic(path: Path) -> None:
    if path.stat().st_size < 8:
        raise UnsafeInputError("[VC-SAFE-001] File Parquet quá ngắn hoặc không hợp lệ.")
    with path.open("rb") as stream:
        prefix = stream.read(4)
        stream.seek(-4, os.SEEK_END)
        suffix = stream.read(4)
    if prefix != b"PAR1" or suffix != b"PAR1":
        raise UnsafeInputError(
            "[VC-SAFE-001] Nội dung file không khớp phần mở rộng Parquet."
        )


def _is_link_or_reparse_point(path: Path) -> bool:
    """Return True for POSIX symlinks and Windows junction/reparse points."""

    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(metadata.st_mode):
        return True
    attributes = getattr(metadata, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse_flag)


def enforce_frame_limits(
    frame: pd.DataFrame, limits: ResourceLimits | None = None
) -> pd.DataFrame:
    """Fail safely when a loaded DataFrame exceeds configured limits."""

    selected = limits or ResourceLimits()
    rows, columns = frame.shape
    if rows > selected.max_rows:
        raise ResourceLimitError(f"[VC-LIMIT-001] Dữ liệu vượt {selected.max_rows:,} dòng.")
    if columns > selected.max_columns:
        raise ResourceLimitError(f"[VC-LIMIT-001] Dữ liệu vượt {selected.max_columns:,} cột.")
    if rows * columns > selected.max_cells:
        raise ResourceLimitError(
            f"[VC-LIMIT-001] Dữ liệu vượt {selected.max_cells:,} ô (rows × columns)."
        )
    memory = int(frame.memory_usage(index=True, deep=True).sum())
    if memory > selected.max_memory_mb * 1024 * 1024:
        raise ResourceLimitError(
            f"[VC-LIMIT-001] DataFrame ước tính vượt {selected.max_memory_mb} MB RAM."
        )
    for column in frame.select_dtypes(include=["object", "string"]).columns:
        lengths = frame[column].dropna().map(lambda value: len(value) if isinstance(value, str) else 0)
        if not lengths.empty and int(lengths.max()) > selected.max_cell_length:
            raise ResourceLimitError(
                f"[VC-LIMIT-001] Cột {column} có cell dài quá {selected.max_cell_length:,} ký tự."
            )
    return frame
