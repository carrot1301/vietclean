"""Command-line interface for repeatable everyday cleaning jobs."""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Iterator, Mapping
from copy import deepcopy
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence, cast
from urllib.parse import unquote, urlsplit

import pandas as pd

from . import __version__
from .api import explain_report, validate_file
from .artifacts import atomic_write_json, atomic_write_text, render_run_summary
from .config import ConfigError, starter_config, starter_toml
from .exceptions import (
    SchemaValidationError,
    UnsafeInputError,
    UnsupportedFormatError,
    VietCleanError,
)
from .inspection import inspect_dataframe
from .io import (
    ReadDiagnostics,
    inspect_excel_workbook,
    read_chunks,
    read_data,
    read_excel_sheets,
    validate_output_path,
    write_chunks,
    write_data,
    write_excel_sheets,
)
from .logging_utils import configure_logging, get_logger, get_run_id, log_event
from .pipeline import CleaningError, DataCleaner
from .profiles import get_profile, list_profiles
from .quality import build_quality_report, write_quality_report
from .report import CleaningReport
from .security.formulas import FormulaMode, protect_spreadsheet_formulas


_DATABASE_SUFFIXES = {".db", ".db3", ".sqlite", ".sqlite3"}
_SPREADSHEET_SUFFIXES = {".csv", ".tsv", ".tab", ".txt", ".xlsx", ".xls", ".xlsm"}
_URL_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s\]\[(){}<>]+")


def _sheet(value: str) -> str | int:
    try:
        return int(value)
    except ValueError:
        return value


def _header_row(value: str) -> str | int | None:
    normalized = value.strip().casefold()
    if normalized == "infer":
        return "infer"
    if normalized in {"none", "null"}:
        return None
    try:
        row = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("header row phải là infer, none hoặc số >= 0") from exc
    if row < 0:
        raise argparse.ArgumentTypeError("header row không được âm")
    return row


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dataclean",
        description="Làm sạch dữ liệu Việt Nam hoàn toàn offline.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Tắt màu terminal; output hiện tại luôn là plain text.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    clean = subparsers.add_parser("clean", help="Làm sạch và ghi dữ liệu ra file/database.")
    clean.add_argument("input", help="CSV, Excel, Parquet, SQLite hoặc URI database.")
    clean.add_argument("-o", "--output", help="File/database đích; input không bao giờ bị ghi đè.")
    clean.add_argument(
        "--output-dir",
        help="Thư mục bundle; mặc định <tên_input>_output hoặc <tên_output>_artifacts.",
    )
    clean.add_argument(
        "--profile",
        "--preset",
        dest="profile",
        help="generic, fnb, finance, ecommerce hoặc marketing.",
    )
    clean.add_argument("--config", help="File rule TOML/JSON; profile trong file được hỗ trợ.")
    clean.add_argument("--sheet", type=_sheet, default=0, help="Tên/chỉ số sheet Excel input.")
    clean.add_argument("--all-sheets", action="store_true", help="Làm sạch mọi sheet Excel.")
    clean.add_argument("--header-row", type=_header_row, default="infer")
    clean.add_argument("--output-sheet", default="cleaned", help="Tên sheet Excel output.")
    clean.add_argument("--table", help="Bảng database input.")
    clean.add_argument("--query", help="Câu SELECT database input (thay cho --table).")
    clean.add_argument("--output-table", help="Bảng database output; mặc định *_clean.")
    clean.add_argument(
        "--if-exists",
        choices=("fail", "replace", "append"),
        default="fail",
        help="Cách ghi nếu bảng output đã tồn tại (mặc định: fail).",
    )
    clean.add_argument("--encoding", default="auto", help="Encoding input CSV (mặc định: auto).")
    clean.add_argument(
        "--output-encoding",
        "--csv-encoding",
        dest="output_encoding",
        default="utf-8-sig",
        help="Encoding output CSV (mặc định UTF-8 BOM cho Excel).",
    )
    clean.add_argument("--delimiter", help="Dấu phân cách input; mặc định tự nhận diện.")
    clean.add_argument("--quotechar", help="Ký tự quote CSV; mặc định tự nhận diện.")
    clean.add_argument("--escapechar", help="Ký tự escape CSV; mặc định tự nhận diện.")
    clean.add_argument("--decimal", help="Dấu thập phân input CSV, ví dụ ',' hoặc '.'.")
    clean.add_argument("--thousands", help="Dấu hàng nghìn input CSV.")
    clean.add_argument("--output-delimiter", help="Dấu phân cách output CSV.")
    clean.add_argument(
        "--infer-dtypes",
        action="store_true",
        help="Cho pandas tự đoán dtype CSV (có thể làm mất số 0 đầu).",
    )
    clean.add_argument(
        "--chunksize",
        type=int,
        help="Số dòng mỗi chunk cho CSV lớn; giữ memory có giới hạn.",
    )
    clean.add_argument(
        "--bad-lines",
        choices=("error", "capture"),
        default="capture",
        help="Dừng hoặc ghi dòng CSV lỗi vào rejects (mặc định: capture).",
    )
    clean.add_argument("--timeout-seconds", type=float, help="Giới hạn thời gian thao tác I/O.")
    clean.add_argument("--output-root", help="Giới hạn mọi file output bên trong thư mục này.")
    clean.add_argument(
        "--secure-mode",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Từ chối symlink/reparse output và đường dẫn thoát output-root (mặc định bật).",
    )
    clean.add_argument("--allow-macros", action="store_true", help="Cho phép chỉ đọc .xlsm; không chạy macro.")
    clean.add_argument(
        "--allow-remote-database",
        action="store_true",
        help="Cho phép kết nối URI database từ xa (tắt mặc định; cần credential tối thiểu quyền).",
    )
    clean.add_argument(
        "--allow-remote-query",
        action="store_true",
        help="Cho phép --query trên remote DB sau khi review; cần --allow-remote-database.",
    )
    clean.add_argument(
        "--formula-mode",
        choices=("sanitize", "report_only", "allow"),
        default="sanitize",
        help="Bảo vệ formula injection khi xuất spreadsheet (mặc định: sanitize).",
    )
    _add_resource_arguments(clean)
    clean.add_argument("--report", help="Đường dẫn report JSON.")
    clean.add_argument("--no-report", action="store_true", help="Không ghi report JSON.")
    clean.add_argument("--quality-report", help="Đường dẫn quality report JSON.")
    clean.add_argument("--quality-html", help="Đường dẫn quality report HTML offline.")
    clean.add_argument(
        "--quality-threshold",
        type=float,
        help="Trả exit code 1 sau khi ghi artifact nếu score thấp hơn ngưỡng 0-100.",
    )
    clean.add_argument("--no-quality-report", action="store_true", help="Không ghi quality JSON/HTML.")
    clean.add_argument("--no-quality-html", action="store_true", help="Chỉ ghi quality JSON.")
    clean.add_argument("--rejects", help="Đường dẫn rejected rows CSV.")
    clean.add_argument("--no-rejects", action="store_true", help="Không ghi rejected rows CSV.")
    clean.add_argument("--column-mapping", help="Đường dẫn column_mapping.json.")
    clean.add_argument("--no-column-mapping", action="store_true")
    clean.add_argument("--run-summary", help="Đường dẫn run_summary.txt.")
    clean.add_argument("--no-run-summary", action="store_true")
    clean.add_argument("--dry-run", action="store_true", help="Làm sạch và report nhưng không ghi data.")
    clean.add_argument(
        "--overwrite",
        action="store_true",
        help="Cho phép thay output/report đã tồn tại; file input luôn được giữ nguyên.",
    )
    clean.add_argument("--quiet", action="store_true", help="Chỉ in lỗi.")
    clean.add_argument("--debug", action="store_true", help="Hiện traceback kỹ thuật khi lỗi.")
    _add_logging_arguments(clean)
    clean.set_defaults(handler=_run_clean)

    inspect = subparsers.add_parser(
        "inspect",
        aliases=["profile"],
        help="Kiểm tra chất lượng, không sửa dữ liệu (alias: profile).",
    )
    inspect.add_argument("input")
    inspect.add_argument("--profile", "--preset", dest="profile", default="generic")
    inspect.add_argument("--sheet", type=_sheet, default=0)
    inspect.add_argument("--table")
    inspect.add_argument("--query")
    inspect.add_argument("--encoding", default="auto")
    inspect.add_argument("--delimiter")
    inspect.add_argument("--quotechar")
    inspect.add_argument("--escapechar")
    inspect.add_argument("--decimal")
    inspect.add_argument("--thousands")
    inspect.add_argument("--header-row", type=_header_row, default="infer")
    inspect.add_argument("--infer-dtypes", action="store_true")
    inspect.add_argument("--bad-lines", choices=("error", "capture"), default="capture")
    inspect.add_argument("--allow-macros", action="store_true")
    inspect.add_argument("--allow-remote-database", action="store_true")
    inspect.add_argument("--allow-remote-query", action="store_true")
    _add_resource_arguments(inspect)
    inspect.add_argument("--timeout-seconds", type=float)
    inspect.add_argument("--samples", action="store_true", help="In tối đa 3 mẫu/cột (có thể chứa PII).")
    inspect.add_argument("-o", "--output", help="Ghi JSON thay vì chỉ in ra terminal.")
    inspect.add_argument("--overwrite", action="store_true")
    inspect.add_argument("--debug", action="store_true")
    _add_logging_arguments(inspect)
    inspect.set_defaults(handler=_run_inspect)

    profiles = subparsers.add_parser("profiles", help="Liệt kê profile có sẵn.")
    profiles.add_argument("--debug", action="store_true")
    profiles.set_defaults(handler=_run_profiles)

    init = subparsers.add_parser("init-config", help="Tạo một file cấu hình TOML/JSON mẫu.")
    init.add_argument("path", nargs="?", default="vietclean.toml")
    init.add_argument("--profile", "--preset", dest="profile", default="generic")
    init.add_argument("--force", action="store_true", help="Ghi đè file cấu hình đã có.")
    init.add_argument("--debug", action="store_true")
    init.set_defaults(handler=_run_init_config)

    config = subparsers.add_parser("config", help="Tạo hoặc kiểm tra cấu hình.")
    config_actions = config.add_subparsers(dest="config_action", required=True)
    config_validate = config_actions.add_parser("validate", help="Kiểm tra TOML/JSON config.")
    config_validate.add_argument("path")
    config_validate.add_argument("--debug", action="store_true")
    config_validate.set_defaults(handler=_run_validate_config)
    config_init = config_actions.add_parser("init", help="Tạo TOML/JSON config mẫu.")
    config_init.add_argument("path", nargs="?", default="vietclean.toml")
    config_init.add_argument("--profile", "--preset", dest="profile", default="generic")
    config_init.add_argument("--force", action="store_true")
    config_init.add_argument("--debug", action="store_true")
    config_init.set_defaults(handler=_run_init_config)

    validate = subparsers.add_parser(
        "validate", help="Kiểm tra file theo schema JSON/TOML mà không sửa dữ liệu."
    )
    validate.add_argument("input")
    validate.add_argument("--schema", required=True)
    validate.add_argument("--profile", "--preset", dest="profile")
    validate.add_argument("--sheet", type=_sheet, default=0)
    validate.add_argument("--table")
    validate.add_argument("--query")
    validate.add_argument("--encoding", default="auto")
    validate.add_argument("--delimiter")
    validate.add_argument("--header-row", type=_header_row, default="infer")
    validate.add_argument("-o", "--output", help="Ghi kết quả JSON aggregate-only.")
    validate.add_argument("--overwrite", action="store_true")
    validate.add_argument("--allow-macros", action="store_true")
    validate.add_argument("--allow-remote-database", action="store_true")
    validate.add_argument("--allow-remote-query", action="store_true")
    validate.add_argument("--timeout-seconds", type=float)
    validate.add_argument("--debug", action="store_true")
    _add_resource_arguments(validate)
    _add_logging_arguments(validate)
    validate.set_defaults(handler=_run_validate)

    explain = subparsers.add_parser(
        "explain", help="Giải thích audit/quality report bằng số liệu aggregate."
    )
    explain.add_argument("report")
    explain.add_argument("-o", "--output")
    explain.add_argument("--overwrite", action="store_true")
    explain.add_argument("--debug", action="store_true")
    _add_logging_arguments(explain)
    explain.set_defaults(handler=_run_explain)
    return parser


def _add_logging_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--log-file", help="Ghi log UTF-8 append-only.")
    parser.add_argument("--log-format", choices=("text", "json"), default="text")
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        default="INFO",
    )
    parser.add_argument("--run-id", help="Correlation ID không chứa PII (1-64 ký tự).")
    parser.add_argument("--no-color", action="store_true", help="Tắt màu terminal (CLI hiện dùng plain text).")


def _add_resource_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--max-file-size-mb", type=int)
    parser.add_argument("--max-rows", type=int)
    parser.add_argument("--max-columns", type=int)
    parser.add_argument("--max-cells", type=int)
    parser.add_argument("--max-cell-length", type=int)
    parser.add_argument("--max-memory-mb", type=int)
    parser.add_argument("--max-zip-ratio", type=float)
    parser.add_argument("--max-excel-sheets", type=int)
    parser.add_argument("--max-rejected-rows", type=int)
    parser.add_argument("--max-rejected-mb", type=int)


def _resource_limits_from_args(args: argparse.Namespace) -> dict[str, int | float] | None:
    mapping = {
        "max_file_size_mb": getattr(args, "max_file_size_mb", None),
        "max_rows": getattr(args, "max_rows", None),
        "max_columns": getattr(args, "max_columns", None),
        "max_cells": getattr(args, "max_cells", None),
        "max_cell_length": getattr(args, "max_cell_length", None),
        "max_memory_mb": getattr(args, "max_memory_mb", None),
        "max_zip_ratio": getattr(args, "max_zip_ratio", None),
        "max_excel_sheets": getattr(args, "max_excel_sheets", None),
        "max_rejected_rows": getattr(args, "max_rejected_rows", None),
        "max_rejected_bytes_mb": getattr(args, "max_rejected_mb", None),
    }
    selected = {key: value for key, value in mapping.items() if value is not None}
    return selected or None


def _read_from_args(
    args: argparse.Namespace, diagnostics: ReadDiagnostics | None = None
):
    parser_options = {
        key: value
        for key, value in {
            "quotechar": getattr(args, "quotechar", None),
            "escapechar": getattr(args, "escapechar", None),
            "decimal": getattr(args, "decimal", None),
            "thousands": getattr(args, "thousands", None),
        }.items()
        if value is not None
    }
    return read_data(
        args.input,
        sheet_name=getattr(args, "sheet", 0),
        table=getattr(args, "table", None),
        query=getattr(args, "query", None),
        encoding=getattr(args, "encoding", "auto"),
        delimiter=getattr(args, "delimiter", None),
        allow_macros=bool(getattr(args, "allow_macros", False)),
        allow_remote_database=bool(getattr(args, "allow_remote_database", False)),
        allow_remote_query=bool(getattr(args, "allow_remote_query", False)),
        resource_limits=_resource_limits_from_args(args),
        infer_dtypes=bool(getattr(args, "infer_dtypes", False)),
        bad_line_policy=getattr(args, "bad_lines", "error"),
        diagnostics=diagnostics,
        header_row=getattr(args, "header_row", "infer"),
        timeout_seconds=getattr(args, "timeout_seconds", None),
        **parser_options,
    )


def _clean_locations(args: argparse.Namespace) -> dict[str, str | None]:
    """Resolve deterministic data/artifact destinations without touching disk."""

    source = str(args.input)
    if args.output is not None:
        selected_output = str(args.output)
        output: str | None = selected_output
        if args.output_dir:
            bundle = Path(args.output_dir)
        elif "://" not in selected_output:
            output_path = Path(selected_output)
            bundle = output_path.parent / f"{output_path.stem}_artifacts"
        else:
            bundle = Path("vietclean_output")
    else:
        if "://" in source:
            output = None
            bundle = Path(args.output_dir or args.output_root or "vietclean_output")
        else:
            input_path = Path(source)
            bundle = (
                Path(args.output_dir)
                if args.output_dir
                else (
                    Path(args.output_root) / f"{input_path.stem}_output"
                    if args.output_root
                    else input_path.with_name(f"{input_path.stem}_output")
                )
            )
            output = str(bundle / f"{input_path.stem}_cleaned{input_path.suffix or '.csv'}")

    return {
        "output": output,
        "audit": None if args.no_report else str(args.report or bundle / "audit_log.json"),
        "quality_json": (
            None
            if args.no_quality_report
            else str(args.quality_report or bundle / "quality_report.json")
        ),
        "quality_html": (
            None
            if args.no_quality_report or args.no_quality_html
            else str(args.quality_html or bundle / "quality_report.html")
        ),
        "rejects": (
            None if args.no_rejects else str(args.rejects or bundle / "rejected_rows.csv")
        ),
        "column_mapping": (
            None
            if args.no_column_mapping
            else str(args.column_mapping or bundle / "column_mapping.json")
        ),
        "run_summary": (
            None
            if args.no_run_summary
            else str(args.run_summary or bundle / "run_summary.txt")
        ),
    }


def _preflight_clean_locations(
    args: argparse.Namespace,
    locations: Mapping[str, str | None],
) -> None:
    output = locations["output"]
    if not args.dry_run and output is None:
        raise ConfigError("Database URI input cần chỉ rõ --output.")
    for location in locations.values():
        if location and "://" not in location:
            validate_output_path(
                location,
                output_root=args.output_root,
                secure_mode=args.secure_mode,
            )
    if not args.dry_run:
        assert output is not None
        _guard_local_output(output, args.input, overwrite=args.overwrite)
    labels = {
        "audit": "audit report",
        "quality_json": "quality report",
        "quality_html": "quality HTML",
        "rejects": "rejects",
        "column_mapping": "column mapping",
        "run_summary": "run summary",
    }
    for key, label in labels.items():
        location = locations.get(key)
        if location:
            _guard_existing(location, overwrite=args.overwrite, label=label)
    selected = [
        path
        for key, path in locations.items()
        if path and (key != "output" or not args.dry_run)
    ]
    _ensure_distinct_outputs(selected)
    _ensure_not_input(
        args.input,
        [path for key, path in locations.items() if path and key != "output"],
    )


def _run_clean(args: argparse.Namespace) -> int:
    if args.all_sheets:
        return _run_clean_workbook(args)
    if args.chunksize is not None:
        return _run_clean_chunks(args)
    diagnostics = ReadDiagnostics()
    frame = _read_from_args(args, diagnostics)
    cleaner = DataCleaner(profile=args.profile, config=args.config)
    result = cleaner.clean(frame)
    result.report.run_id = get_run_id()

    locations = _clean_locations(args)
    output = locations["output"]
    report_path = locations["audit"]
    quality_json = locations["quality_json"]
    quality_html = locations["quality_html"]
    rejects_path = locations["rejects"]
    column_mapping_path = locations["column_mapping"]
    run_summary_path = locations["run_summary"]
    _preflight_clean_locations(args, locations)

    result.report.source_name = _safe_source_name(args.input)
    result.report.source_size_bytes = _file_size(args.input)
    result.report.input_sha256 = _file_sha256(args.input)
    result.report.config_sha256 = _file_sha256(args.config) if args.config else None
    result.report.formula_mode = args.formula_mode
    result.report.rejected_rows = len(diagnostics.rejected_rows)
    result.report.rejected_by_reason = dict(
        sorted(
            {
                reason: sum(1 for item in diagnostics.rejected_rows if item.reason == reason)
                for reason in {item.reason for item in diagnostics.rejected_rows}
            }.items()
        )
    )
    result.report.loader_encoding = diagnostics.encoding
    result.report.loader_delimiter = diagnostics.delimiter

    spreadsheet_output = bool(output and _looks_like_spreadsheet(output))
    protection_mode = cast(
        FormulaMode, str(args.formula_mode) if spreadsheet_output else "report_only"
    )
    protection = protect_spreadsheet_formulas(result.data, mode=protection_mode)
    export_data = protection.data
    result.report.formula_risks_detected = protection.risks_detected
    result.report.formula_cells_sanitized = protection.cells_sanitized
    result.report.formula_risks_by_column = protection.by_column
    if protection.risks_detected and protection_mode != "sanitize":
        result.report.warnings.append(
            f"Phát hiện {protection.risks_detected} ô có nguy cơ formula injection chưa được sanitize."
        )

    if not args.dry_run:
        assert output is not None  # Guarded before any output/report mutation above.
        output_table = args.output_table
        if _looks_like_database(output):
            output_table = output_table or (f"{args.table}_clean" if args.table else "cleaned_data")
        write_data(
            export_data,
            output,
            sheet_name=args.output_sheet,
            table=output_table,
            if_exists=args.if_exists,
            encoding=args.output_encoding,
            delimiter=args.output_delimiter,
            index=False,
            overwrite=args.overwrite,
            formula_mode="allow",
            allow_remote_database=bool(args.allow_remote_database),
            output_root=args.output_root,
            secure_mode=args.secure_mode,
        )
        result.report.output_sha256 = _file_sha256(output)
        result.report.steps.append("safe_export")

    quality_profile: str | dict[str, Any] = {
        "name": result.report.profile,
        "quality": cleaner.config.get("quality", {}),
    }
    quality = build_quality_report(frame, export_data, result.report, profile=quality_profile)
    result.report.quality_score = float(quality["score"])
    if quality_json:
        write_quality_report(
            quality, quality_json, quality_html, overwrite=args.overwrite
        )
        result.report.steps.append("quality_report")

    if rejects_path:
        write_data(
            diagnostics.rejects_frame(),
            rejects_path,
            overwrite=args.overwrite,
            formula_mode="sanitize",
            index=False,
        )
        result.report.steps.append("rejected_rows_report")

    if column_mapping_path:
        atomic_write_json(
            column_mapping_path,
            {"run_id": result.report.run_id, "columns": result.report.renamed_columns},
            overwrite=args.overwrite,
        )
        result.report.steps.append("column_mapping_report")

    artifact_locations = {
        "data": output if not args.dry_run else None,
        "quality_json": quality_json,
        "quality_html": quality_html,
        "rejected_rows": rejects_path,
        "column_mapping": column_mapping_path,
    }
    for name, location in artifact_locations.items():
        digest = _file_sha256(location)
        if digest is not None:
            result.report.artifact_sha256[name] = digest

    threshold = args.quality_threshold
    if threshold is None:
        quality_config = cleaner.config.get("quality", {})
        if isinstance(quality_config, dict):
            threshold = quality_config.get("threshold")
    if threshold is not None and not 0 <= float(threshold) <= 100:
        raise ConfigError("quality threshold phải nằm trong 0..100.")
    threshold_failed = threshold is not None and float(quality["score"]) < float(threshold)
    if threshold_failed:
        result.report.warnings.append(
            f"Data Quality Score thấp hơn ngưỡng cấu hình ({quality['score']} < {threshold})."
        )

    result.report.finish(status="success")
    if run_summary_path:
        atomic_write_text(
            run_summary_path,
            render_run_summary(result.report.to_dict()),
            overwrite=args.overwrite,
        )
        result.report.steps.append("run_summary")
        digest = _file_sha256(run_summary_path)
        if digest is not None:
            result.report.artifact_sha256["run_summary"] = digest

    if report_path:
        result.report.steps.append("audit_report")
        result.report.to_json(report_path, overwrite=args.overwrite)

    if not args.quiet:
        destination = "(dry-run, chưa ghi data)" if args.dry_run else str(output)
        print(f"Hoàn tất: {_display_location(destination)}")
        summary = quality["summary"]
        print(f"Data Quality Score: {quality['score']}/100")
        print(f"Rows read:               {result.report.rows_before:,}")
        print(f"Rows written:            {result.report.rows_after:,}")
        print(f"Rejected rows:           {result.report.rejected_rows:,}")
        print(f"Missing cells:           {summary['missing_cells_after']:,}")
        print(f"Duplicate rows:          {result.report.duplicates_detected:,}")
        print(f"Encoding repairs:        {summary['encoding_repairs']:,}")
        print(f"Ambiguous text values:   {summary['ambiguous_text_values']:,}")
        print(f"Validation errors:       {summary['validation_errors']:,}")
        print(f"Security warnings:       {summary['security_warnings']:,}")
        if report_path:
            print(f"Audit report: {report_path}")
        if quality_json:
            print(f"Quality report: {quality_json}")
        if rejects_path:
            print(f"Rejected rows: {result.report.rejected_rows} ({rejects_path})")
            if quality_html:
                print(f"Quality HTML: {quality_html}")
        for warning in result.report.warnings:
            print(f"Cảnh báo: {warning}", file=sys.stderr)
    return 1 if threshold_failed else 0


def _merge_cleaning_reports(
    target: CleaningReport,
    child: CleaningReport,
    *,
    namespace: str | None = None,
) -> None:
    """Merge aggregate counters from one independently cleaned partition."""

    for field in (
        "rows_before",
        "rows_after",
        "cells_changed",
        "missing_rows_removed",
        "duplicates_detected",
        "duplicates_detected_by_subset",
        "duplicates_removed",
        "empty_rows_removed",
        "formula_risks_detected",
        "formula_cells_sanitized",
        "rejected_rows",
        "validation_passed",
        "validation_failed",
    ):
        setattr(target, field, int(getattr(target, field)) + int(getattr(child, field)))

    column_maps = (
        "changed_by_column",
        "missing_before",
        "missing_after",
        "invalid_by_column",
        "encoding_repairs_by_column",
        "mojibake_candidates_by_column",
        "mojibake_review_by_column",
        "mojibake_unrepaired_by_column",
        "ambiguous_dates_by_column",
        "missing_filled_by_column",
        "formula_risks_by_column",
    )
    for field in column_maps:
        output = getattr(target, field)
        for key, value in getattr(child, field).items():
            selected = f"{namespace}:{key}" if namespace else str(key)
            output[selected] = int(output.get(selected, 0)) + int(value)

    for field in ("changed_by_rule", "domain_rule_violations", "rejected_by_reason"):
        output = getattr(target, field)
        for key, value in getattr(child, field).items():
            output[str(key)] = int(output.get(str(key), 0)) + int(value)

    for key, value in child.semantic_types.items():
        selected = f"{namespace}:{key}" if namespace else str(key)
        target.semantic_types.setdefault(selected, value)
    for key, value in child.missing_fill_strategy_by_column.items():
        selected = f"{namespace}:{key}" if namespace else str(key)
        target.missing_fill_strategy_by_column.setdefault(selected, value)
    for key, value in child.renamed_columns.items():
        selected = f"{namespace}:{key}" if namespace else str(key)
        target.renamed_columns[selected] = value
    for key, methods in child.outliers_by_column.items():
        selected = f"{namespace}:{key}" if namespace else str(key)
        target_methods = target.outliers_by_column.setdefault(selected, {})
        for method, count in methods.items():
            target_methods[method] = int(target_methods.get(method, 0)) + int(count)
    for field in (
        "empty_columns_removed",
        "missing_columns_removed",
        "missing_flag_columns_added",
    ):
        output = getattr(target, field)
        for value in getattr(child, field):
            selected = f"{namespace}:{value}" if namespace else str(value)
            if selected not in output:
                output.append(selected)
    for warning in child.warnings:
        selected = f"[{namespace}] {warning}" if namespace else warning
        if selected not in target.warnings:
            target.warnings.append(selected)
    for step in child.steps:
        if step not in target.steps:
            target.steps.append(step)


def _aggregate_partition_quality(
    reports: list[tuple[dict[str, Any], int]],
    *,
    profile: str,
    partition_label: str,
) -> dict[str, Any]:
    """Combine bounded aggregate reports without retaining partition data."""

    if not reports:
        raise ValueError("Không có partition dữ liệu để tạo quality report.")
    total_weight = sum(max(1, weight) for _, weight in reports)
    first = deepcopy(reports[0][0])
    weights = first["formula"]["weights"]
    for name in first["components"]:
        component = first["components"][name]
        score = sum(
            float(report["components"][name]["score"]) * max(1, weight)
            for report, weight in reports
        ) / total_weight
        deduction_count = sum(
            int(report["components"][name]["deduction"]["count"])
            for report, _ in reports
        )
        component["score"] = round(score, 2)
        component["weighted_points"] = round(score * float(weights[name]), 2)
        component["metrics"] = {
            f"{partition_label}_count": len(reports),
            "aggregation_weight_units": total_weight,
        }
        component["deduction"]["count"] = deduction_count
        component["deduction"]["component_points_lost"] = round(100 - score, 2)
    first["score"] = round(
        sum(
            float(first["components"][name]["score"]) * float(weights[name])
            for name in first["components"]
        ),
        2,
    )
    summary_keys = {
        key
        for report, _ in reports
        for key, value in report.get("summary", {}).items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }
    first["summary"] = {
        key: sum(report.get("summary", {}).get(key, 0) for report, _ in reports)
        for key in sorted(summary_keys)
    }
    first["summary"][f"{partition_label}_count"] = len(reports)
    first["profile"] = profile
    first["aggregation"] = {
        "method": "cell_weighted_partition_scores",
        "partition": partition_label,
        "partition_count": len(reports),
        "weight_units": total_weight,
    }
    return first


def _finalize_partitioned_run(
    args: argparse.Namespace,
    *,
    locations: Mapping[str, str | None],
    report: CleaningReport,
    quality: dict[str, Any],
    diagnostics: ReadDiagnostics,
    column_mapping: Mapping[str, Any],
    config: Mapping[str, Any],
) -> int:
    """Write common artifacts after an atomic workbook/chunk export."""

    output = locations.get("output")
    report.source_name = _safe_source_name(args.input)
    report.source_size_bytes = _file_size(args.input)
    report.input_sha256 = _file_sha256(args.input)
    report.config_sha256 = _file_sha256(args.config) if args.config else None
    report.loader_encoding = diagnostics.encoding
    report.loader_delimiter = diagnostics.delimiter
    report.rejected_rows += len(diagnostics.rejected_rows)
    report.rejected_by_reason.update(
        Counter(item.reason for item in diagnostics.rejected_rows)
    )
    report.output_sha256 = _file_sha256(output if not args.dry_run else None)
    report.quality_score = float(quality["score"])

    quality_json = locations.get("quality_json")
    quality_html = locations.get("quality_html")
    if quality_json:
        write_quality_report(
            quality,
            quality_json,
            quality_html,
            overwrite=args.overwrite,
        )
        report.steps.append("quality_report")
    rejects = locations.get("rejects")
    if rejects:
        write_data(
            diagnostics.rejects_frame(),
            rejects,
            overwrite=args.overwrite,
            formula_mode="sanitize",
            output_root=args.output_root,
            secure_mode=args.secure_mode,
            index=False,
        )
        report.steps.append("rejected_rows_report")
    mapping_path = locations.get("column_mapping")
    if mapping_path:
        atomic_write_json(
            mapping_path,
            {"run_id": report.run_id, "columns": dict(column_mapping)},
            overwrite=args.overwrite,
        )
        report.steps.append("column_mapping_report")

    for name, location in {
        "data": output if not args.dry_run else None,
        "quality_json": quality_json,
        "quality_html": quality_html,
        "rejected_rows": rejects,
        "column_mapping": mapping_path,
    }.items():
        digest = _file_sha256(location)
        if digest:
            report.artifact_sha256[name] = digest

    threshold = args.quality_threshold
    quality_config = config.get("quality", {})
    if threshold is None and isinstance(quality_config, Mapping):
        threshold = quality_config.get("threshold")
    if threshold is not None and not 0 <= float(threshold) <= 100:
        raise ConfigError("quality threshold phải nằm trong 0..100.")
    threshold_failed = threshold is not None and float(quality["score"]) < float(threshold)
    if threshold_failed:
        report.warnings.append(
            f"Data Quality Score thấp hơn ngưỡng cấu hình ({quality['score']} < {threshold})."
        )

    report.finish(status="success")
    summary_path = locations.get("run_summary")
    if summary_path:
        atomic_write_text(
            summary_path,
            render_run_summary(report.to_dict()),
            overwrite=args.overwrite,
        )
        report.steps.append("run_summary")
        digest = _file_sha256(summary_path)
        if digest:
            report.artifact_sha256["run_summary"] = digest
    audit = locations.get("audit")
    if audit:
        report.steps.append("audit_report")
        report.to_json(audit, overwrite=args.overwrite)

    if not args.quiet:
        destination = "(dry-run, chưa ghi data)" if args.dry_run else str(output)
        summary = quality["summary"]
        print(f"Hoàn tất: {_display_location(destination)}")
        print(f"Data Quality Score: {quality['score']}/100")
        print(f"Rows read:               {report.rows_before:,}")
        print(f"Rows written:            {report.rows_after:,}")
        print(f"Rejected rows:           {report.rejected_rows:,}")
        print(f"Missing cells:           {int(summary.get('missing_cells_after', 0)):,}")
        print(f"Duplicate rows:          {report.duplicates_detected:,}")
        print(f"Encoding repairs:        {int(summary.get('encoding_repairs', 0)):,}")
        print(
            f"Ambiguous text values:   {int(summary.get('ambiguous_text_values', 0)):,}"
        )
        print(f"Validation errors:       {int(summary.get('validation_errors', 0)):,}")
        print(f"Security warnings:       {int(summary.get('security_warnings', 0)):,}")
        for warning in report.warnings:
            print(f"Cảnh báo: {warning}", file=sys.stderr)
    return 1 if threshold_failed else 0


def _run_clean_workbook(args: argparse.Namespace) -> int:
    if args.chunksize is not None:
        raise ConfigError("Không thể dùng đồng thời --all-sheets và --chunksize.")
    locations = _clean_locations(args)
    output = locations.get("output")
    if output and "://" not in output and Path(output).suffix.casefold() != ".xlsx":
        if args.output:
            raise UnsupportedFormatError("--all-sheets chỉ xuất workbook .xlsx.")
        locations = dict(locations)
        locations["output"] = str(Path(output).with_suffix(".xlsx"))
    _preflight_clean_locations(args, locations)

    workbook_info = inspect_excel_workbook(
        args.input,
        resource_limits=_resource_limits_from_args(args),
        allow_macros=args.allow_macros,
        timeout_seconds=args.timeout_seconds,
    )
    frames = read_excel_sheets(
        args.input,
        sheets="all",
        header_row=args.header_row,
        resource_limits=_resource_limits_from_args(args),
        allow_macros=args.allow_macros,
        timeout_seconds=args.timeout_seconds,
    )
    master = CleaningReport(profile=args.profile or "generic", run_id=get_run_id())
    master.source_sheet_count = len(frames)
    master.formula_mode = args.formula_mode
    cleaned_frames: dict[str, pd.DataFrame] = {}
    mapping: dict[str, Any] = {}
    quality_parts: list[tuple[dict[str, Any], int]] = []
    selected_config: Mapping[str, Any] = {}
    maximum_before_columns = 0
    maximum_after_columns = 0
    for sheet_name, frame in frames.items():
        cleaner = DataCleaner(profile=args.profile, config=args.config)
        selected_config = cleaner.config
        if not master.sheet_reports:
            master.profile = cleaner.profile
        cleaned = cleaner.clean(frame)
        protection = protect_spreadsheet_formulas(
            cleaned.data,
            mode=cast(FormulaMode, args.formula_mode),
        )
        cleaned.report.formula_mode = args.formula_mode
        cleaned.report.formula_risks_detected = protection.risks_detected
        cleaned.report.formula_cells_sanitized = protection.cells_sanitized
        cleaned.report.formula_risks_by_column = protection.by_column
        cleaned_frames[sheet_name] = protection.data
        mapping[sheet_name] = cleaned.report.renamed_columns
        master.sheet_reports[sheet_name] = cleaned.report.to_dict()
        _merge_cleaning_reports(master, cleaned.report, namespace=sheet_name)
        maximum_before_columns = max(maximum_before_columns, len(frame.columns))
        maximum_after_columns = max(maximum_after_columns, len(protection.data.columns))
        quality_profile = {
            "name": cleaned.report.profile,
            "quality": cleaner.config.get("quality", {}),
        }
        part_quality = build_quality_report(
            frame,
            protection.data,
            cleaned.report,
            profile=quality_profile,
        )
        quality_parts.append(
            (part_quality, max(1, frame.shape[0] * max(1, frame.shape[1])))
        )
    master.columns_before = maximum_before_columns
    master.columns_after = maximum_after_columns
    if len({tuple(frame.columns) for frame in frames.values()}) > 1:
        master.warnings.append(
            "Workbook có schema khác nhau giữa các sheet; quality được tổng hợp theo từng sheet."
        )
    formula_cells = sum(sheet.formula_cell_count for sheet in workbook_info.sheets)
    merged_ranges = sum(sheet.merged_range_count for sheet in workbook_info.sheets)
    if formula_cells:
        master.warnings.append(
            f"Input có {formula_cells} formula cell; công thức không được thực thi."
        )
    if merged_ranges:
        master.warnings.append(
            f"Input có {merged_ranges} merged ranges; chỉ giữ giá trị ô trên-trái."
        )
    if workbook_info.has_macros:
        master.warnings.append("Input có macro; output .xlsx không bảo toàn macro.")

    if not args.dry_run:
        assert locations.get("output") is not None
        write_excel_sheets(
            cleaned_frames,
            str(locations["output"]),
            overwrite=args.overwrite,
            formula_mode="allow",
            output_root=args.output_root,
            secure_mode=args.secure_mode,
            resource_limits=_resource_limits_from_args(args),
            timeout_seconds=args.timeout_seconds,
            index=False,
        )
        master.steps.append("safe_multi_sheet_export")
    quality = _aggregate_partition_quality(
        quality_parts,
        profile=master.profile,
        partition_label="sheet",
    )
    return _finalize_partitioned_run(
        args,
        locations=locations,
        report=master,
        quality=quality,
        diagnostics=ReadDiagnostics(),
        column_mapping=mapping,
        config=selected_config,
    )


def _run_clean_chunks(args: argparse.Namespace) -> int:
    if args.chunksize is None or args.chunksize <= 0:
        raise ConfigError("--chunksize phải lớn hơn 0.")
    locations = _clean_locations(args)
    output = locations.get("output")
    if output is None or "://" in output:
        raise UnsupportedFormatError("Chunk mode chỉ xuất CSV/TSV/TXT cục bộ.")
    if Path(output).suffix.casefold() not in {".csv", ".tsv", ".tab", ".txt"}:
        raise UnsupportedFormatError("Chunk mode chỉ xuất CSV/TSV/TXT.")
    _preflight_clean_locations(args, locations)

    diagnostics = ReadDiagnostics()
    cleaner = DataCleaner(profile=args.profile, config=args.config)
    master = CleaningReport(profile=cleaner.profile, run_id=get_run_id())
    master.streaming_mode = True
    master.formula_mode = args.formula_mode
    quality_parts: list[tuple[dict[str, Any], int]] = []
    expected_before_columns = 0
    expected_after_columns = 0
    expected_output_columns: list[Any] | None = None

    parser_options = {
        key: value
        for key, value in {
            "quotechar": args.quotechar,
            "escapechar": args.escapechar,
            "decimal": args.decimal,
            "thousands": args.thousands,
        }.items()
        if value is not None
    }

    def transformed_chunks() -> Iterator[pd.DataFrame]:
        nonlocal expected_before_columns, expected_after_columns, expected_output_columns
        for frame in read_chunks(
            args.input,
            chunksize=args.chunksize,
            encoding=args.encoding,
            delimiter=args.delimiter,
            resource_limits=_resource_limits_from_args(args),
            bad_line_policy=args.bad_lines,
            diagnostics=diagnostics,
            infer_dtypes=args.infer_dtypes,
            header_row=args.header_row,
            timeout_seconds=args.timeout_seconds,
            **parser_options,
        ):
            cleaned = cleaner.clean(frame)
            protection = protect_spreadsheet_formulas(
                cleaned.data,
                mode=cast(FormulaMode, args.formula_mode),
            )
            cleaned.report.formula_mode = args.formula_mode
            cleaned.report.formula_risks_detected = protection.risks_detected
            cleaned.report.formula_cells_sanitized = protection.cells_sanitized
            cleaned.report.formula_risks_by_column = protection.by_column
            if master.chunks_processed == 0:
                expected_before_columns = len(frame.columns)
                expected_after_columns = len(protection.data.columns)
                expected_output_columns = list(protection.data.columns)
            elif list(protection.data.columns) != expected_output_columns:
                raise CleaningError(
                    "Schema output thay đổi giữa các chunk. Tắt rule drop cột phụ thuộc dữ liệu "
                    "hoặc chạy không dùng --chunksize."
                )
            _merge_cleaning_reports(master, cleaned.report)
            master.chunks_processed += 1
            quality_profile = {
                "name": cleaner.profile,
                "quality": cleaner.config.get("quality", {}),
            }
            quality_parts.append(
                (
                    build_quality_report(
                        frame,
                        protection.data,
                        cleaned.report,
                        profile=quality_profile,
                    ),
                    max(1, frame.shape[0] * max(1, frame.shape[1])),
                )
            )
            yield protection.data

    stream = transformed_chunks()
    if args.dry_run:
        for _ in stream:
            pass
    else:
        write_chunks(
            stream,
            output,
            encoding=args.output_encoding,
            delimiter=args.output_delimiter,
            overwrite=args.overwrite,
            formula_mode="allow",
            output_root=args.output_root,
            secure_mode=args.secure_mode,
            resource_limits=_resource_limits_from_args(args),
            timeout_seconds=args.timeout_seconds,
            index=False,
        )
        master.steps.append("safe_chunked_export")
    if master.chunks_processed == 0:
        raise ValueError("CSV không có data row để xử lý theo chunk.")
    master.columns_before = expected_before_columns
    master.columns_after = expected_after_columns
    duplicate_options = cleaner.config.get("duplicates", {})
    if isinstance(duplicate_options, Mapping) and (
        duplicate_options.get("enabled") or duplicate_options.get("action") == "drop"
    ):
        master.warnings.append(
            "Trong chunk mode, duplicate được xử lý trong từng chunk; dùng full mode nếu cần "
            "so khớp duplicate xuyên chunk."
        )
    quality = _aggregate_partition_quality(
        quality_parts,
        profile=master.profile,
        partition_label="chunk",
    )
    return _finalize_partitioned_run(
        args,
        locations=locations,
        report=master,
        quality=quality,
        diagnostics=diagnostics,
        column_mapping=master.renamed_columns,
        config=cleaner.config,
    )


def _run_inspect(args: argparse.Namespace) -> int:
    diagnostics = ReadDiagnostics()
    frame = _read_from_args(args, diagnostics)
    result = inspect_dataframe(frame, profile=args.profile, include_samples=args.samples)
    result["source"] = {
        "name": _safe_source_name(args.input),
        "sha256": _file_sha256(args.input),
        "size_bytes": _file_size(args.input),
        "profile": args.profile,
    }
    result["loader"] = {
        "encoding": diagnostics.encoding,
        "delimiter": diagnostics.delimiter,
        "rejected_rows": len(diagnostics.rejected_rows),
    }
    content = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        _guard_local_output(args.output, args.input, overwrite=args.overwrite)
        path = Path(args.output)
        _write_text_atomic(path, content)
        print(f"Đã ghi: {path}")
    else:
        print(content, end="")
    return 0


def _run_validate(args: argparse.Namespace) -> int:
    read_options: dict[str, Any] = {
        "sheet_name": args.sheet,
        "table": args.table,
        "query": args.query,
        "encoding": args.encoding,
        "delimiter": args.delimiter,
        "header_row": args.header_row,
        "allow_macros": args.allow_macros,
        "allow_remote_database": args.allow_remote_database,
        "allow_remote_query": args.allow_remote_query,
        "resource_limits": _resource_limits_from_args(args),
        "timeout_seconds": args.timeout_seconds,
    }
    validation = validate_file(
        args.input,
        args.schema,
        profile=args.profile,
        **read_options,
    )
    content = json.dumps(validation.to_dict(), ensure_ascii=False, indent=2) + "\n"
    if args.output:
        _guard_local_output(args.output, args.input, overwrite=args.overwrite)
        _write_text_atomic(Path(args.output), content)
        print(f"Đã ghi validation report: {args.output}")
    else:
        print(content, end="")
    if validation.valid:
        print(
            f"Validation hợp lệ: {validation.checks_passed} checks pass, 0 checks fail.",
            file=sys.stderr,
        )
        return 0
    print(
        f"Validation không đạt: {validation.checks_failed} checks fail.",
        file=sys.stderr,
    )
    return 1


def _run_explain(args: argparse.Namespace) -> int:
    content = explain_report(args.report)
    if args.output:
        _guard_existing(args.output, overwrite=args.overwrite, label="explanation")
        _write_text_atomic(Path(args.output), content)
        print(f"Đã ghi: {args.output}")
    else:
        print(content, end="")
    return 0


def _run_profiles(_args: argparse.Namespace) -> int:
    for name in list_profiles():
        print(f"{name:12} {get_profile(name).get('description', '')}")
    return 0


def _run_init_config(args: argparse.Namespace) -> int:
    # Validate the profile before touching the destination.
    try:
        get_profile(args.profile)
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc
    path = Path(args.path)
    if path.exists() and not args.force:
        raise FileExistsError(f"File đã tồn tại: {path}. Dùng --force để ghi đè.")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.casefold() == ".json":
        content = json.dumps(starter_config(args.profile), ensure_ascii=False, indent=2) + "\n"
    else:
        content = starter_toml(args.profile)
    _write_text_atomic(path, content)
    print(f"Đã tạo: {path}")
    return 0


def _run_validate_config(args: argparse.Namespace) -> int:
    cleaner = DataCleaner(config=args.path)
    print(f"Config hợp lệ: {args.path} (profile={cleaner.profile}, version=1)")
    return 0


def _default_output(source: str) -> str | None:
    if "://" in source:
        return None
    path = Path(source)
    suffix = path.suffix or ".csv"
    return str(
        path.with_name(f"{path.stem}_output") / f"{path.stem}_cleaned{suffix}"
    )


def _default_report(output: str | None, source: str) -> str:
    if output and "://" not in output:
        base = Path(output)
    elif "://" not in source:
        base = Path(source)
    else:
        base = Path("vietclean")
    return str(base.with_suffix(".cleaning-report.json"))


def _default_artifact(output: str | None, source: str, suffix: str) -> str:
    if output and "://" not in output:
        base = Path(output)
    elif "://" not in source:
        base = Path(source)
    else:
        base = Path("vietclean")
    return str(base.with_suffix(f".{suffix}"))


def _looks_like_database(location: str) -> bool:
    if "://" in location:
        return not location.lower().startswith("file://")
    return Path(location).suffix.lower() in _DATABASE_SUFFIXES


def _looks_like_spreadsheet(location: str) -> bool:
    return "://" not in location and Path(location).suffix.lower() in _SPREADSHEET_SUFFIXES


def _guard_existing(location: str, *, overwrite: bool, label: str) -> None:
    if "://" in location:
        return
    path = Path(location)
    if path.exists() and not overwrite:
        raise FileExistsError(f"{label.capitalize()} đã tồn tại: {path}. Dùng --overwrite.")


def _guard_local_output(output: str, source: str, *, overwrite: bool) -> None:
    if _canonical_data_location(output) == _canonical_data_location(source):
        raise UnsafeInputError(
            "Output không được trùng nguồn input; VietClean luôn giữ nguyên file/database nguồn."
        )
    if "://" in output or "://" in source:
        _guard_existing(output, overwrite=overwrite, label="output")
        return
    _guard_existing(output, overwrite=overwrite, label="output")


def _canonical_data_location(location: str) -> tuple[object, ...]:
    """Canonicalise local paths and database endpoints for immutability checks."""

    if "://" not in location:
        try:
            resolved = Path(location).resolve()
        except OSError:
            resolved = Path(location).absolute()
        return ("file", os.path.normcase(str(resolved)))

    parts = urlsplit(location)
    base_scheme = parts.scheme.casefold().split("+", 1)[0]
    if base_scheme in {"sqlite", "file"}:
        raw_path = unquote(parts.path)
        if base_scheme == "sqlite":
            # Match io._sqlite_path_from_uri semantics:
            # sqlite:///relative.db and sqlite:////absolute/path.db.
            if raw_path.startswith("//"):
                raw_path = raw_path[1:]
            elif raw_path.startswith("/"):
                raw_path = raw_path[1:]
        elif parts.netloc:
            raw_path = f"//{parts.netloc}{raw_path}"
        try:
            resolved = Path(raw_path).resolve()
        except OSError:
            resolved = Path(raw_path).absolute()
        return ("file", os.path.normcase(str(resolved)))

    return (
        "database",
        base_scheme,
        (parts.hostname or "").casefold(),
        parts.port,
        unquote(parts.path).rstrip("/"),
    )


def _display_location(location: str) -> str:
    """Hide URI credentials/tokens in terminal output."""

    if "://" not in location:
        return location
    scheme, remainder = location.split("://", 1)
    remainder = remainder.split("?", 1)[0].split("#", 1)[0]
    if "@" in remainder:
        remainder = "***@" + remainder.rsplit("@", 1)[1]
    return f"{scheme}://{remainder}"


def _redact_message(message: str, args: argparse.Namespace) -> str:
    for attribute in ("input", "output"):
        raw = getattr(args, attribute, None)
        if isinstance(raw, str) and "://" in raw:
            message = message.replace(raw, _display_location(raw))
    return _URL_RE.sub(lambda match: _display_location(match.group(0)), message)


def _safe_source_name(source: str) -> str:
    if "://" in source:
        return source.split("://", 1)[0] + "://[redacted]"
    return Path(source).name


def _file_sha256(location: str | None) -> str | None:
    if not location or "://" in location:
        return None
    path = Path(location)
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _file_size(location: str | None) -> int | None:
    if not location or "://" in location:
        return None
    path = Path(location)
    return path.stat().st_size if path.is_file() else None


def _ensure_distinct_outputs(locations: list[str]) -> None:
    local = [Path(value).resolve() for value in locations if "://" not in value]
    if len(local) != len(set(local)):
        raise ConfigError("Output data và các report phải dùng đường dẫn khác nhau.")


def _ensure_not_input(source: str, locations: list[str]) -> None:
    if "://" in source:
        return
    source_path = Path(source).resolve()
    for location in locations:
        if "://" not in location and Path(location).resolve() == source_path:
            raise UnsafeInputError("Report không được ghi đè file input.")


def _write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point; returns a process exit code for easy testing."""

    _configure_console()
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        try:
            context = configure_logging(
                level=getattr(args, "log_level", "INFO"),
                log_file=getattr(args, "log_file", None),
                log_format=getattr(args, "log_format", "text"),
                run_id=getattr(args, "run_id", None),
                console=not bool(getattr(args, "quiet", False)),
            )
        except (TypeError, ValueError, OSError) as exc:
            raise ConfigError(f"Cấu hình logging không hợp lệ: {exc}") from exc
        log_event(context.logger, "INFO", "command_started", command=args.command)
        exit_code = int(args.handler(args))
        log_event(
            context.logger,
            "INFO" if exit_code == 0 else "WARNING",
            "command_finished",
            command=args.command,
            exit_code=exit_code,
        )
        return exit_code
    except (ConfigError,) as exc:
        if getattr(args, "debug", False):
            raise
        _record_cli_failure(args, exc)
        log_event(get_logger(), "ERROR", "command_failed", code=exc.code, command=args.command)
        print(f"[{exc.code}] {_redact_message(str(exc), args)}", file=sys.stderr)
        return 2
    except (CleaningError, SchemaValidationError) as exc:
        if getattr(args, "debug", False):
            raise
        _record_cli_failure(args, exc)
        log_event(get_logger(), "ERROR", "command_failed", code=exc.code, command=args.command)
        print(f"[{exc.code}] {_redact_message(str(exc), args)}", file=sys.stderr)
        return 1
    except (UnsafeInputError, FileExistsError) as exc:
        if getattr(args, "debug", False):
            raise
        code = getattr(exc, "code", "VC-SAFE-002")
        _record_cli_failure(args, exc)
        log_event(get_logger(), "ERROR", "command_failed", code=code, command=args.command)
        print(f"[{code}] {_redact_message(str(exc), args)}", file=sys.stderr)
        return 3
    except (UnsupportedFormatError, ImportError) as exc:
        if getattr(args, "debug", False):
            raise
        code = getattr(exc, "code", "VC-FORMAT-002")
        _record_cli_failure(args, exc)
        log_event(get_logger(), "ERROR", "command_failed", code=code, command=args.command)
        print(f"[{code}] {_redact_message(str(exc), args)}", file=sys.stderr)
        return 4
    except (FileNotFoundError, ValueError, OSError, VietCleanError) as exc:
        if getattr(args, "debug", False):
            raise
        code = getattr(exc, "code", "VC-PROCESS-001")
        _record_cli_failure(args, exc)
        log_event(get_logger(), "ERROR", "command_failed", code=code, command=args.command)
        print(f"[{code}] {_redact_message(str(exc), args)}", file=sys.stderr)
        return 5
    except KeyboardInterrupt:
        interruption = KeyboardInterrupt("Đã hủy bởi người dùng.")
        _record_cli_failure(args, interruption, status="cancelled")
        log_event(get_logger(), "WARNING", "command_cancelled", command=args.command)
        print("Đã hủy.", file=sys.stderr)
        return 130
    except Exception as exc:
        if getattr(args, "debug", False):
            raise
        _record_cli_failure(args, exc)
        log_event(
            get_logger(), "ERROR", "command_failed", code="VC-PROCESS-999", command=args.command
        )
        print(f"[VC-PROCESS-999] {_redact_message(str(exc), args)}", file=sys.stderr)
        return 5


def _record_cli_failure(
    args: argparse.Namespace,
    exc: BaseException,
    *,
    status: str = "failed",
) -> None:
    """Best-effort aggregate failure audit for ``clean``; never hides the error."""

    if getattr(args, "command", None) != "clean" or getattr(args, "no_report", True):
        return
    try:
        audit_location = _clean_locations(args).get("audit")
        if not audit_location or "://" in audit_location:
            return
        destination = Path(audit_location)
        overwrite = bool(getattr(args, "overwrite", False))
        if destination.exists() and not overwrite:
            return
        report = CleaningReport(
            profile=getattr(args, "profile", None) or "generic",
            run_id=get_run_id(),
        )
        report.source_name = _safe_source_name(str(getattr(args, "input", "")))
        report.source_size_bytes = _file_size(getattr(args, "input", None))
        report.input_sha256 = _file_sha256(getattr(args, "input", None))
        report.config_sha256 = _file_sha256(getattr(args, "config", None))
        report.error_code = str(getattr(exc, "code", "VC-PROCESS-999"))
        report.error_message = _redact_message(str(exc), args)
        report.finish(status=status)
        report.to_json(destination, overwrite=overwrite)
    except BaseException:
        # Failure auditing is deliberately best-effort and must never replace
        # the original CLI exception or alter its documented exit code.
        return


def _configure_console() -> None:
    """Make Vietnamese output reliable on older Windows code pages."""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, OSError, ValueError):
                pass


if __name__ == "__main__":
    raise SystemExit(main())
