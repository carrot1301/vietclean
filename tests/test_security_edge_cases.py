from pathlib import Path
from zipfile import ZIP_STORED, ZipFile

import pandas as pd
import pytest

from vietclean.exceptions import ResourceLimitError, UnsafeInputError, UnsafeQueryError
from vietclean.report import CleaningReport
from vietclean.security.formulas import is_formula_risk, protect_spreadsheet_formulas
from vietclean.security.pii import infer_pii_type, mask_pii
from vietclean.security.resources import ResourceLimits, check_input_file, enforce_frame_limits
from vietclean.security.sql import validate_read_query


def test_formula_boundary_types_modes_columns_and_categories() -> None:
    assert not is_formula_risk(None)
    assert not is_formula_risk(12)
    assert not is_formula_risk("   ")
    assert not is_formula_risk("  '=SUM(A1)")
    assert is_formula_risk("-not-a-number")

    frame = pd.DataFrame(
        {
            "category": pd.Series(["=1+1", "safe"], dtype="category"),
            "numeric": [1, 2],
        }
    )
    result = protect_spreadsheet_formulas(frame, columns=["category", "numeric"])
    assert result.data["category"].tolist() == ["'=1+1", "safe"]
    assert result.by_column == {"category": 1}

    report_only = protect_spreadsheet_formulas(frame, mode="report_only", copy=False)
    assert report_only.risks_detected == 1
    assert report_only.cells_sanitized == 0
    with pytest.raises(ValueError, match="formula mode"):
        protect_spreadsheet_formulas(frame, mode="invalid")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="DataFrame"):
        protect_spreadsheet_formulas([])  # type: ignore[arg-type]
    with pytest.raises(KeyError, match="không tồn tại"):
        protect_spreadsheet_formulas(frame, columns=["missing"])


def test_pii_helpers_cover_empty_and_non_email_sensitive_classes() -> None:
    assert infer_pii_type("") is None
    assert infer_pii_type("Địa chỉ") == "address"
    assert mask_pii(None) == "[NULL]"
    assert mask_pii("") == "[EMPTY]"
    assert mask_pii("không-có-số", "account") == "***"
    assert mask_pii("Nguyễn Văn A", "name") == "N***"
    assert mask_pii("12 Lê Lợi", "address") == "1***"
    assert mask_pii("opaque", None) == "***"


def test_resource_limit_configuration_rejects_unknown_and_ambiguous_values() -> None:
    assert ResourceLimits.from_mapping(None) == ResourceLimits()
    assert ResourceLimits.from_mapping({"max_rows": 10}).max_rows == 10
    with pytest.raises(ValueError, match="không được hỗ trợ"):
        ResourceLimits.from_mapping({"unknown": 1})
    with pytest.raises(ValueError, match="max_rows"):
        ResourceLimits(max_rows=False)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="max_zip_ratio"):
        ResourceLimits(max_zip_ratio=True)  # type: ignore[arg-type]


def test_input_preflight_rejects_bad_paths_magic_and_archives(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match="allow_symlinks"):
        check_input_file(tmp_path / "input.csv", allow_symlinks=1)  # type: ignore[arg-type]
    with pytest.raises(UnsafeInputError, match="null byte"):
        check_input_file("bad\0.csv")
    assert check_input_file(tmp_path / "missing.csv") == tmp_path / "missing.csv"

    for suffix in (".xls", ".sqlite"):
        invalid = tmp_path / f"invalid{suffix}"
        invalid.write_bytes(b"not the expected file signature")
        with pytest.raises(UnsafeInputError, match="định dạng"):
            check_input_file(invalid)

    short_parquet = tmp_path / "short.parquet"
    short_parquet.write_bytes(b"PAR1")
    with pytest.raises(UnsafeInputError, match="quá ngắn"):
        check_input_file(short_parquet)
    corrupt_parquet = tmp_path / "corrupt.parquet"
    corrupt_parquet.write_bytes(b"PAR1payloadFAIL")
    with pytest.raises(UnsafeInputError, match="Parquet"):
        check_input_file(corrupt_parquet)

    invalid_xlsx = tmp_path / "invalid.xlsx"
    invalid_xlsx.write_bytes(b"not a zip")
    with pytest.raises(UnsafeInputError, match="ZIP"):
        check_input_file(invalid_xlsx)


def test_archive_entry_expansion_memory_and_identity_limits(tmp_path: Path) -> None:
    too_many = tmp_path / "entries.xlsx"
    with ZipFile(too_many, "w", compression=ZIP_STORED) as archive:
        archive.writestr("one", b"1")
        archive.writestr("two", b"2")
    with pytest.raises(ResourceLimitError, match="archive entries"):
        check_input_file(too_many, ResourceLimits(max_archive_entries=1))

    expanded = tmp_path / "expanded.xlsx"
    with ZipFile(expanded, "w", compression=ZIP_STORED) as archive:
        archive.writestr("payload", b"x" * (1024 * 1024 + 1))
    with pytest.raises(ResourceLimitError, match="bung nén"):
        check_input_file(expanded, ResourceLimits(max_archive_uncompressed_mb=1))

    memory_heavy = tmp_path / "memory.xlsx"
    with ZipFile(memory_heavy, "w", compression=ZIP_STORED) as archive:
        archive.writestr("payload", b"x" * 140_000)
    with pytest.raises(ResourceLimitError, match="ngân sách RAM"):
        check_input_file(memory_heavy, ResourceLimits(max_memory_mb=1))

    disguised = tmp_path / "disguised.xlsx"
    with ZipFile(disguised, "w", compression=ZIP_STORED) as archive:
        archive.writestr("payload", b"small")
    with pytest.raises(UnsafeInputError, match="khớp phần mở rộng"):
        check_input_file(disguised)


def test_dataframe_column_memory_and_success_boundaries() -> None:
    with pytest.raises(ResourceLimitError, match="cột"):
        enforce_frame_limits(
            pd.DataFrame([[1, 2]]),
            ResourceLimits(max_columns=1),
        )
    with pytest.raises(ResourceLimitError, match="RAM"):
        enforce_frame_limits(
            pd.DataFrame({"payload": ["x" * (1024 * 1024 + 1)]}),
            ResourceLimits(max_memory_mb=1, max_cell_length=2_000_000),
        )
    frame = pd.DataFrame({"value": [1]})
    assert enforce_frame_limits(frame) is frame


def test_sql_empty_null_and_trailing_semicolon_boundaries() -> None:
    for query in ("", "   ", None):
        with pytest.raises(UnsafeQueryError, match="để trống"):
            validate_read_query(query)  # type: ignore[arg-type]
    with pytest.raises(UnsafeQueryError, match="null byte"):
        validate_read_query("SELECT 1\0")
    assert validate_read_query(" SELECT 1; ") == "SELECT 1"


def test_audit_report_rejects_invalid_state_and_preserves_existing_file(tmp_path: Path) -> None:
    report = CleaningReport()
    with pytest.raises(ValueError, match="status"):
        report.finish(status="unknown")
    with pytest.raises(TypeError, match="overwrite"):
        report.to_json(overwrite=1)  # type: ignore[arg-type]

    destination = tmp_path / "audit.json"
    destination.write_text("keep", encoding="utf-8")
    with pytest.raises(FileExistsError, match="đã tồn tại"):
        report.to_json(destination)
    assert destination.read_text(encoding="utf-8") == "keep"
