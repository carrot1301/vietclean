from contextlib import closing
from pathlib import Path
import socket
import sqlite3
from zipfile import ZIP_DEFLATED, ZipFile

import pandas as pd
import pytest

from vietclean import clean_dataframe
from vietclean.exceptions import ResourceLimitError, UnsafeInputError, UnsafeQueryError
from vietclean.io import read_chunks, read_data, write_data
from vietclean.security.formulas import is_formula_risk, protect_spreadsheet_formulas
from vietclean.security.pii import infer_pii_type, mask_pii
from vietclean.security.resources import ResourceLimits, check_input_file, enforce_frame_limits
from vietclean.security.sql import validate_read_query


@pytest.mark.parametrize(
    "value",
    [
        "=1+1",
        "+cmd|'/C calc'!A0",
        "-HYPERLINK('x')",
        "@SUM(A1)",
        "\t=1",
        "\n=WEBSERVICE('x')",
    ],
)
def test_formula_payloads_are_detected(value: str) -> None:
    assert is_formula_risk(value)


@pytest.mark.parametrize("value", ["-1250", "1.250,50", "'=SUM(A1)", "normal"])
def test_legitimate_or_already_sanitized_values_are_not_formula_risks(value: str) -> None:
    assert not is_formula_risk(value)


def test_plus_prefixed_phone_is_sanitized_for_spreadsheets() -> None:
    result = protect_spreadsheet_formulas(pd.DataFrame({"phone": ["+84901234567"]}))

    assert result.data.loc[0, "phone"] == "'+84901234567"
    assert result.cells_sanitized == 1


def test_formula_sanitization_is_copying_audited_and_idempotent() -> None:
    source = pd.DataFrame({"note": ["=2+2", "ok", "+cmd|x"], "amount": [-10, 20, 30]})

    first = protect_spreadsheet_formulas(source)
    second = protect_spreadsheet_formulas(first.data)

    assert list(source["note"]) == ["=2+2", "ok", "+cmd|x"]
    assert list(first.data["note"]) == ["'=2+2", "ok", "'+cmd|x"]
    assert first.risks_detected == first.cells_sanitized == 2
    assert first.by_column == {"note": 2}
    assert second.risks_detected == second.cells_sanitized == 0


def test_csv_export_sanitizes_formulas_by_default(tmp_path: Path) -> None:
    output = tmp_path / "safe.csv"
    write_data(pd.DataFrame({"customer_note": ["=WEBSERVICE('x')"]}), output)

    exported = pd.read_csv(output, dtype=str)
    assert exported.loc[0, "customer_note"] == "'=WEBSERVICE('x')"


@pytest.mark.parametrize(
    "query",
    [
        "DELETE FROM orders",
        "SELECT * FROM orders; DROP TABLE orders",
        "WITH gone AS (DELETE FROM orders RETURNING *) SELECT * FROM gone",
        "PRAGMA writable_schema=ON",
        "SELECT * FROM orders -- comment",
    ],
)
def test_read_query_allowlist_rejects_mutation_and_multiple_statements(query: str) -> None:
    with pytest.raises(UnsafeQueryError):
        validate_read_query(query)


def test_read_query_accepts_parameterized_select_and_sqlite_remains_unchanged(tmp_path: Path) -> None:
    database = tmp_path / "safe.db"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("CREATE TABLE orders (id INTEGER, amount INTEGER)")
        connection.execute("INSERT INTO orders VALUES (1, 100)")
        connection.commit()

    frame = read_data(
        database,
        query="SELECT * FROM orders WHERE amount >= ?",
        params=(50,),
    )

    assert frame.to_dict("records") == [{"id": 1, "amount": 100}]
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 1


def test_file_and_dataframe_resource_limits_fail_safely(tmp_path: Path) -> None:
    oversized = tmp_path / "large.csv"
    oversized.write_bytes(b"x" * 1025)
    tiny_limit = ResourceLimits(max_file_size_mb=1)
    # Adjust by replacing the frozen instance with a byte-level fixture that
    # exceeds a valid positive one-megabyte limit.
    oversized.write_bytes(b"x" * (1024 * 1024 + 1))
    with pytest.raises(ResourceLimitError, match="VC-LIMIT"):
        check_input_file(oversized, tiny_limit)

    with pytest.raises(ResourceLimitError, match="dòng"):
        enforce_frame_limits(pd.DataFrame({"x": [1, 2]}), ResourceLimits(max_rows=1))
    with pytest.raises(ResourceLimitError, match="cell"):
        enforce_frame_limits(
            pd.DataFrame({"text": ["12345"]}), ResourceLimits(max_cell_length=4)
        )
    with pytest.raises(ResourceLimitError, match="rows × columns"):
        enforce_frame_limits(
            pd.DataFrame([[1, 2, 3], [4, 5, 6]]), ResourceLimits(max_cells=4)
        )


def test_suspicious_xlsx_expansion_ratio_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "bomb.xlsx"
    with ZipFile(archive, "w", compression=ZIP_DEFLATED) as output:
        output.writestr("xl/worksheets/sheet1.xml", "A" * 100_000)

    with pytest.raises(ResourceLimitError, match="tỷ lệ nén"):
        check_input_file(archive, ResourceLimits(max_zip_ratio=5))


def test_xlsx_sheet_count_is_bounded_before_openpyxl_loads_it(tmp_path: Path) -> None:
    archive = tmp_path / "too-many-sheets.xlsx"
    with ZipFile(archive, "w") as output:
        output.writestr("xl/worksheets/sheet1.xml", "<worksheet/>")
        output.writestr("xl/worksheets/sheet2.xml", "<worksheet/>")

    with pytest.raises(ResourceLimitError, match="worksheet"):
        check_input_file(archive, ResourceLimits(max_excel_sheets=1))


def test_macro_enabled_workbook_is_denied_by_default(tmp_path: Path) -> None:
    pytest.importorskip("openpyxl")
    xlsx = tmp_path / "source.xlsx"
    xlsm = tmp_path / "source.xlsm"
    pd.DataFrame({"x": [1]}).to_excel(xlsx, index=False)
    xlsm.write_bytes(xlsx.read_bytes())

    with pytest.raises(UnsafeInputError, match="từ chối mặc định"):
        read_data(xlsm)


def test_pii_helpers_never_echo_full_sensitive_value() -> None:
    assert infer_pii_type("Số điện thoại") == "phone"
    assert infer_pii_type("ghi chú") is None
    assert mask_pii("user@example.com", "email") == "u***@example.com"
    assert mask_pii("0901234567", "phone") == "***4567"
    assert "0901234567" not in mask_pii("0901234567", "phone")


def test_local_core_workflow_does_not_open_network(monkeypatch, tmp_path: Path) -> None:
    def blocked(*_args, **_kwargs):
        raise AssertionError("core runtime attempted a network connection")

    monkeypatch.setattr(socket, "create_connection", blocked)
    source = tmp_path / "input.csv"
    output = tmp_path / "output.csv"
    source.write_text("ghi chú\n  Cà   phê  \n", encoding="utf-8")

    cleaned = clean_dataframe(read_data(source), config={"auto_types": False})
    write_data(cleaned, output)

    assert output.exists()


def test_remote_database_is_explicit_opt_in_without_loading_driver() -> None:
    uri = "postgresql://user:secret@db.invalid/data"

    with pytest.raises(UnsafeInputError, match="tắt mặc định"):
        read_data(uri, table="orders")
    with pytest.raises(UnsafeInputError, match="tắt mặc định"):
        write_data(pd.DataFrame({"x": [1]}), uri, table="cleaned")
    with pytest.raises(UnsafeInputError, match="Query tùy chỉnh"):
        read_data(
            uri,
            query="SELECT current_date",
            allow_remote_database=True,
        )


def test_security_sensitive_boolean_api_flags_do_not_use_truthiness(tmp_path: Path) -> None:
    frame = pd.DataFrame({"x": ["=1+1"]})
    with pytest.raises(TypeError, match="copy"):
        protect_spreadsheet_formulas(frame, copy=0)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="inplace"):
        clean_dataframe(frame, inplace="false")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="overwrite"):
        write_data(frame, tmp_path / "x.csv", overwrite="false")  # type: ignore[arg-type]
    source = tmp_path / "source.csv"
    source.write_text("x\n1\n", encoding="utf-8")
    with pytest.raises(TypeError, match="infer_dtypes"):
        read_data(source, infer_dtypes="false")  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="infer_dtypes"):
        list(read_chunks(source, infer_dtypes="false"))  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="chunksize"):
        list(read_chunks(source, chunksize=True))
