"""Deterministic naming and atomic writers for one cleaning run bundle."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class RunArtifactPaths:
    data: Path
    audit: Path
    quality_json: Path
    quality_html: Path
    rejects: Path
    column_mapping: Path
    run_summary: Path

    def all_paths(self) -> tuple[Path, ...]:
        return (
            self.data,
            self.audit,
            self.quality_json,
            self.quality_html,
            self.rejects,
            self.column_mapping,
            self.run_summary,
        )


def default_artifact_paths(
    source: str | os.PathLike[str],
    *,
    output_path: str | os.PathLike[str] | None = None,
    output_dir: str | os.PathLike[str] | None = None,
) -> RunArtifactPaths:
    """Return collision-resistant default paths for a complete run bundle."""

    input_path = Path(source)
    if output_path is None:
        bundle = (
            Path(output_dir)
            if output_dir is not None
            else input_path.with_name(f"{input_path.stem}_output")
        )
        suffix = input_path.suffix or ".csv"
        data = bundle / f"{input_path.stem}_cleaned{suffix}"
    else:
        data = Path(output_path)
        bundle = (
            Path(output_dir)
            if output_dir is not None
            else data.parent / f"{data.stem}_artifacts"
        )
    return RunArtifactPaths(
        data=data,
        audit=bundle / "audit_log.json",
        quality_json=bundle / "quality_report.json",
        quality_html=bundle / "quality_report.html",
        rejects=bundle / "rejected_rows.csv",
        column_mapping=bundle / "column_mapping.json",
        run_summary=bundle / "run_summary.txt",
    )


def sha256_file(path: str | os.PathLike[str] | None) -> str | None:
    if path is None:
        return None
    candidate = Path(path)
    if not candidate.is_file():
        return None
    digest = hashlib.sha256()
    with candidate.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_write_text(
    path: str | os.PathLike[str],
    content: str,
    *,
    overwrite: bool = False,
) -> Path:
    destination = Path(path)
    if destination.exists() and not overwrite:
        raise FileExistsError(f"File đã tồn tại: {destination}. Bật overwrite rõ ràng để thay.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=str(destination.parent)
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, destination)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise
    return destination


def atomic_write_json(
    path: str | os.PathLike[str],
    value: Mapping[str, Any],
    *,
    overwrite: bool = False,
) -> Path:
    content = json.dumps(
        dict(value), ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False
    ) + "\n"
    return atomic_write_text(path, content, overwrite=overwrite)


def render_run_summary(report: Mapping[str, Any]) -> str:
    """Render an aggregate-only human-readable run summary."""

    lines = [
        "VietClean run summary",
        f"Run ID: {report.get('run_id', '')}",
        f"Status: {report.get('status', '')}",
        f"Profile: {report.get('profile', '')}",
        f"Rows: {report.get('rows_before', 0)} -> {report.get('rows_after', 0)}",
        f"Columns: {report.get('columns_before', 0)} -> {report.get('columns_after', 0)}",
        f"Changed cells: {report.get('cells_changed', 0)}",
        f"Rejected rows: {report.get('rejected_rows', 0)}",
        f"Duplicate rows detected: {report.get('duplicates_detected', 0)}",
        f"Validation failures: {report.get('validation_failed', 0)}",
        f"Quality score: {report.get('quality_score', '')}",
        f"Warnings: {len(report.get('warnings', []))}",
    ]
    return "\n".join(lines) + "\n"


__all__ = [
    "RunArtifactPaths",
    "atomic_write_json",
    "atomic_write_text",
    "default_artifact_paths",
    "render_run_summary",
    "sha256_file",
]
