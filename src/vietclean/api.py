"""High-level file API for common offline cleaning workflows."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
import json
import os
from pathlib import Path
import re
from typing import Any

from .artifacts import (
    atomic_write_json,
    atomic_write_text,
    default_artifact_paths,
    render_run_summary,
    sha256_file,
)
from .inspection import inspect_dataframe
from .io import HeaderRow, IfExists, ReadDiagnostics, read_data, validate_output_path, write_data
from .models import FileCleaningResult, ValidationResult
from .pipeline import DataCleaner
from .quality import build_quality_report, write_quality_report
from .report import CleaningReport
from .security.formulas import FormulaMode, protect_spreadsheet_formulas
from .validation import validate_dataframe


_URI_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s]+")


def _redact_uri(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        raw = match.group(0)
        scheme, remainder = raw.split("://", 1)
        remainder = remainder.split("?", 1)[0].split("#", 1)[0]
        if "@" in remainder:
            remainder = "***@" + remainder.rsplit("@", 1)[1]
        return f"{scheme}://{remainder}"

    return _URI_RE.sub(replace, value)


def clean_file(
    input_path: str | os.PathLike[str],
    *,
    output_dir: str | os.PathLike[str] | None = None,
    output_path: str | os.PathLike[str] | None = None,
    config_path: str | os.PathLike[str] | Mapping[str, Any] | None = None,
    profile: str | None = None,
    sheet_name: str | int = 0,
    table: str | None = None,
    query: str | None = None,
    encoding: str = "auto",
    delimiter: str | None = None,
    header_row: HeaderRow = "infer",
    output_sheet: str = "cleaned",
    output_table: str | None = None,
    if_exists: IfExists = "fail",
    output_encoding: str = "utf-8-sig",
    output_delimiter: str | None = None,
    overwrite: bool = False,
    formula_mode: FormulaMode = "sanitize",
    resource_limits: Mapping[str, Any] | None = None,
    allow_macros: bool = False,
    allow_remote_database: bool = False,
    allow_remote_query: bool = False,
    infer_dtypes: bool = False,
    timeout_seconds: float | None = None,
    output_root: str | os.PathLike[str] | None = None,
    secure_mode: bool = True,
    **read_options: Any,
) -> FileCleaningResult:
    """Clean one local table and create a complete aggregate-only artifact bundle.

    The input is never modified. When no output location is supplied, artifacts
    are placed in ``<input_stem>_output`` and the cleaned data is named
    ``<input_stem>_cleaned.<extension>``.
    """

    if not isinstance(overwrite, bool):
        raise TypeError("overwrite phải là true hoặc false.")
    if not isinstance(secure_mode, bool):
        raise TypeError("secure_mode phải là true hoặc false.")
    source_text = os.fspath(input_path)
    if "://" in source_text and output_path is None:
        raise ValueError("Database URI input cần output_path rõ ràng.")
    if output_path is not None and "://" in os.fspath(output_path):
        raise ValueError(
            "clean_file tạo bundle file cục bộ; dùng read_data/write_data cho remote output."
        )
    paths = default_artifact_paths(
        source_text, output_path=output_path, output_dir=output_dir
    )
    resolved_source = Path(source_text).resolve() if "://" not in source_text else None
    resolved_outputs = [
        validate_output_path(path, output_root=output_root, secure_mode=secure_mode)
        for path in paths.all_paths()
    ]
    if len(set(resolved_outputs)) != len(resolved_outputs):
        raise ValueError("Các artifact phải có đường dẫn khác nhau.")
    if resolved_source is not None and resolved_source in resolved_outputs:
        raise ValueError("Output/report không được ghi đè input.")
    if not overwrite:
        existing = [path for path in paths.all_paths() if path.exists()]
        if existing:
            raise FileExistsError(
                f"Artifact đã tồn tại: {existing[0]}. Bật overwrite rõ ràng để thay."
            )

    diagnostics = ReadDiagnostics()
    report: CleaningReport | None = None
    try:
        before = read_data(
            source_text,
            sheet_name=sheet_name,
            table=table,
            query=query,
            encoding=encoding,
            delimiter=delimiter,
            resource_limits=resource_limits,
            bad_line_policy="capture",
            diagnostics=diagnostics,
            header_row=header_row,
            allow_macros=allow_macros,
            allow_remote_database=allow_remote_database,
            allow_remote_query=allow_remote_query,
            infer_dtypes=infer_dtypes,
            timeout_seconds=timeout_seconds,
            **read_options,
        )
        cleaner_config: str | Mapping[str, Any] | None = (
            os.fspath(config_path)
            if isinstance(config_path, os.PathLike)
            else config_path
        )
        cleaner = DataCleaner(profile=profile, config=cleaner_config)
        cleaning = cleaner.clean(before, inplace=False)
        report = cleaning.report
        report.source_name = (
            Path(source_text).name if "://" not in source_text else source_text.split("://", 1)[0] + "://[redacted]"
        )
        report.source_size_bytes = (
            Path(source_text).stat().st_size
            if "://" not in source_text and Path(source_text).is_file()
            else None
        )
        report.input_sha256 = sha256_file(source_text if "://" not in source_text else None)
        report.config_sha256 = (
            sha256_file(config_path)
            if isinstance(config_path, (str, os.PathLike))
            else None
        )
        report.loader_encoding = diagnostics.encoding
        report.loader_delimiter = diagnostics.delimiter
        report.rejected_rows = len(diagnostics.rejected_rows)
        report.rejected_by_reason = dict(
            Counter(rejected.reason for rejected in diagnostics.rejected_rows)
        )
        spreadsheet_output = paths.data.suffix.casefold() in {
            ".csv",
            ".tsv",
            ".tab",
            ".txt",
            ".xlsx",
            ".xlsm",
        }
        protection_mode: FormulaMode = formula_mode if spreadsheet_output else "report_only"
        report.formula_mode = protection_mode

        protection = protect_spreadsheet_formulas(cleaning.data, mode=protection_mode)
        export_data = protection.data
        report.formula_risks_detected = protection.risks_detected
        report.formula_cells_sanitized = protection.cells_sanitized
        report.formula_risks_by_column = protection.by_column

        selected_output_table = output_table
        if paths.data.suffix.casefold() in {".db", ".db3", ".sqlite", ".sqlite3"}:
            selected_output_table = selected_output_table or (
                f"{table}_clean" if table else "cleaned_data"
            )

        write_data(
            export_data,
            paths.data,
            overwrite=overwrite,
            formula_mode="allow",
            sheet_name=output_sheet,
            table=selected_output_table,
            if_exists=if_exists,
            encoding=output_encoding,
            delimiter=output_delimiter,
            allow_remote_database=allow_remote_database,
            output_root=output_root,
            secure_mode=secure_mode,
            index=False,
        )
        report.output_sha256 = sha256_file(paths.data)
        report.steps.append("safe_export")

        quality_profile: str | Mapping[str, Any] = {
            "name": report.profile,
            "quality": cleaner.config.get("quality", {}),
        }
        quality = build_quality_report(before, export_data, report, profile=quality_profile)
        report.quality_score = float(quality["score"])
        write_quality_report(
            quality,
            paths.quality_json,
            paths.quality_html,
            overwrite=overwrite,
        )
        report.steps.append("quality_report")

        write_data(
            diagnostics.rejects_frame(),
            paths.rejects,
            overwrite=overwrite,
            formula_mode="sanitize",
            output_root=output_root,
            secure_mode=secure_mode,
            index=False,
        )
        report.steps.append("rejected_rows_report")
        atomic_write_json(
            paths.column_mapping,
            {"run_id": report.run_id, "columns": report.renamed_columns},
            overwrite=overwrite,
        )
        report.steps.append("column_mapping_report")

        for name, path in {
            "data": paths.data,
            "quality_json": paths.quality_json,
            "quality_html": paths.quality_html,
            "rejected_rows": paths.rejects,
            "column_mapping": paths.column_mapping,
        }.items():
            digest = sha256_file(path)
            if digest is not None:
                report.artifact_sha256[name] = digest
        report.finish(status="success")
        atomic_write_text(
            paths.run_summary,
            render_run_summary(report.to_dict()),
            overwrite=overwrite,
        )
        summary_hash = sha256_file(paths.run_summary)
        if summary_hash is not None:
            report.artifact_sha256["run_summary"] = summary_hash
        report.steps.extend(["run_summary", "audit_report"])
        report.to_json(paths.audit, overwrite=overwrite)

        return FileCleaningResult(
            output_path=paths.data,
            audit_path=paths.audit,
            quality_json_path=paths.quality_json,
            quality_html_path=paths.quality_html,
            rejects_path=paths.rejects,
            column_mapping_path=paths.column_mapping,
            run_summary_path=paths.run_summary,
            rows_before=report.rows_before,
            rows_after=report.rows_after,
            quality_score=float(report.quality_score or 0.0),
            run_id=report.run_id,
        )
    except BaseException as exc:
        failure = report or CleaningReport(profile=profile or "generic")
        failure.source_name = (
            Path(source_text).name if "://" not in source_text else source_text.split("://", 1)[0] + "://[redacted]"
        )
        failure.input_sha256 = sha256_file(source_text if "://" not in source_text else None)
        failure.error_code = str(getattr(exc, "code", "VC-PROCESS-999"))
        failure.error_message = _redact_uri(str(exc))
        failure.finish(status="cancelled" if isinstance(exc, KeyboardInterrupt) else "failed")
        try:
            failure.to_json(paths.audit, overwrite=overwrite)
        except (OSError, ValueError):
            pass
        raise


def profile_file(
    input_path: str | os.PathLike[str],
    *,
    profile: str = "generic",
    include_samples: bool = False,
    **read_options: Any,
) -> dict[str, Any]:
    """Profile a local table without modifying it or exposing samples by default."""

    diagnostics = ReadDiagnostics()
    frame = read_data(input_path, diagnostics=diagnostics, **read_options)
    result = inspect_dataframe(frame, profile=profile, include_samples=include_samples)
    result["source"] = {
        "name": Path(input_path).name,
        "size_bytes": Path(input_path).stat().st_size,
        "sha256": sha256_file(input_path),
        "profile": profile,
    }
    result["loader"] = {
        "encoding": diagnostics.encoding,
        "delimiter": diagnostics.delimiter,
        "rejected_rows": len(diagnostics.rejected_rows),
    }
    return result


def validate_file(
    input_path: str | os.PathLike[str],
    schema: str | Path | Mapping[str, Any],
    *,
    profile: str | None = None,
    **read_options: Any,
) -> ValidationResult:
    """Read one table and validate it against a non-executable local schema."""

    return validate_dataframe(
        read_data(input_path, **read_options), schema, profile=profile
    )


def explain_report(report: str | os.PathLike[str] | Mapping[str, Any]) -> str:
    """Return a concise aggregate-only explanation of an audit/quality report."""

    if isinstance(report, Mapping):
        payload = dict(report)
    else:
        payload = json.loads(Path(report).read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("Report phải là JSON object.")
    if "components" in payload and "score" in payload:
        lines = [f"Data Quality Score: {payload.get('score')}/100"]
        components = payload.get("components", {})
        if isinstance(components, Mapping):
            for name, component in components.items():
                if isinstance(component, Mapping):
                    deduction = component.get("deduction", {})
                    reason = deduction.get("reason", "") if isinstance(deduction, Mapping) else ""
                    lines.append(f"- {name}: {component.get('score')}/100 — {reason}")
        return "\n".join(lines) + "\n"
    return render_run_summary(payload)


__all__ = ["clean_file", "explain_report", "profile_file", "validate_file"]
