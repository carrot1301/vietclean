from __future__ import annotations

import sqlite3
import unicodedata
from contextlib import closing
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from vietclean.exceptions import ResourceLimitError
from vietclean.io import (
    ChunkCheckpoint,
    ReadDiagnostics,
    detect_excel_tables,
    detect_delimiter,
    detect_encoding,
    inspect_excel_workbook,
    read_chunks,
    read_data,
    read_excel_sheets,
    read_excel_tables,
    validate_output_path,
    write_chunks,
    write_data,
    write_excel_sheets,
)
from vietclean.exceptions import UnsafeInputError


def test_read_semicolon_csv_with_utf8_bom(tmp_path: Path) -> None:
    source = tmp_path / "don_hang.csv"
    source.write_text(
        "ma;khach_hang;thanh_pho\n001;Nguyễn An;Hồ Chí Minh\n",
        encoding="utf-8-sig",
    )

    assert detect_encoding(source) == "utf-8-sig"
    assert detect_delimiter(source) == ";"

    frame = read_data(source, dtype={"ma": "string"})
    assert frame.loc[0, "ma"] == "001"
    assert frame.loc[0, "khach_hang"] == "Nguyễn An"


def test_detect_cp1258_when_sample_has_vietnamese_tone_marks(tmp_path: Path) -> None:
    source = tmp_path / "legacy.csv"
    decomposed = "name\nTi\u00ea\u0301ng Vi\u00ea\u0323t\n"
    source.write_bytes(decomposed.encode("cp1258"))

    assert detect_encoding(source) == "cp1258"
    value = read_data(source).loc[0, "name"]
    assert unicodedata.normalize("NFC", value) == "Tiếng Việt"


def test_write_csv_is_excel_friendly_and_round_trips(tmp_path: Path) -> None:
    destination = tmp_path / "ket_qua.csv"
    expected = pd.DataFrame(
        {"mã": pd.Series(["001"], dtype="string"), "tên": ["Cà phê sữa"]}
    )

    write_data(expected, destination, index=False)

    assert destination.read_bytes().startswith(b"\xef\xbb\xbf")
    actual = read_data(destination, dtype={"mã": "string"})
    pd.testing.assert_frame_equal(actual, expected)


def test_failed_file_write_keeps_existing_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "important.csv"
    destination.write_text("original\n", encoding="utf-8")

    def fail_after_partial_write(self: pd.DataFrame, path: Path, **_: object) -> None:
        Path(path).write_text("partial\n", encoding="utf-8")
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(pd.DataFrame, "to_csv", fail_after_partial_write)

    with pytest.raises(RuntimeError, match="simulated failure"):
        write_data(pd.DataFrame({"a": [1]}), destination, overwrite=True)

    assert destination.read_text(encoding="utf-8") == "original\n"
    assert list(tmp_path.iterdir()) == [destination]


def test_sqlite_round_trip_and_parameterised_query(tmp_path: Path) -> None:
    database = tmp_path / "offline.sqlite"
    expected = pd.DataFrame(
        {"ma": ["001", "002"], "doanh_thu": [125_000, 75_000]}
    )
    write_data(expected, database, table="sales")

    # A single table can be selected automatically.
    pd.testing.assert_frame_equal(read_data(database), expected)

    filtered = read_data(
        database,
        query="SELECT * FROM sales WHERE doanh_thu >= ?",
        params=(100_000,),
    )
    pd.testing.assert_frame_equal(filtered, expected.iloc[[0]].reset_index(drop=True))


def test_sqlite_write_preserves_decimal_precision_as_text(tmp_path: Path) -> None:
    database = tmp_path / "financial.sqlite"
    amount = Decimal("12345678901234567890.123456789")

    write_data(pd.DataFrame({"amount": [amount]}), database, table="ledger")

    with closing(sqlite3.connect(database)) as connection:
        stored, storage_type = connection.execute(
            "SELECT amount, typeof(amount) FROM ledger"
        ).fetchone()
    assert stored == str(amount)
    assert storage_type == "text"


def test_sqlite_read_path_is_read_only(tmp_path: Path) -> None:
    database = tmp_path / "protected.db"
    write_data(pd.DataFrame({"value": [1]}), database, table="records")

    with pytest.raises(Exception):
        read_data(database, query="DELETE FROM records RETURNING value")

    assert read_data(database, table="records").loc[0, "value"] == 1


def test_existing_sqlite_connection_is_not_closed(tmp_path: Path) -> None:
    connection = sqlite3.connect(tmp_path / "shared.db")
    try:
        write_data(pd.DataFrame({"value": [1]}), connection, table="records")
        assert read_data(connection, table="records").loc[0, "value"] == 1
        assert connection.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 1
    finally:
        connection.close()


def test_multiple_sqlite_tables_require_selection(tmp_path: Path) -> None:
    database = tmp_path / "many.sqlite3"
    write_data(pd.DataFrame({"a": [1]}), database, table="first")
    write_data(
        pd.DataFrame({"b": [2]}),
        database,
        table="second",
        if_exists="replace",
    )

    with pytest.raises(ValueError, match="multiple tables"):
        read_data(database)


def test_explicit_tsv_format_uses_tab_for_extensionless_output(tmp_path: Path) -> None:
    destination = tmp_path / "export"
    write_data(pd.DataFrame({"a": [1], "b": [2]}), destination, file_format="tsv")

    assert "a\tb" in destination.read_text(encoding="utf-8-sig")
    actual = read_data(destination, file_format="tsv")
    assert actual.to_dict(orient="records") == [{"a": "1", "b": "2"}]


def test_xlsx_round_trip_preserves_vietnamese_and_decimal_value(
    tmp_path: Path,
) -> None:
    pytest.importorskip("openpyxl")
    destination = tmp_path / "doanh_thu.xlsx"
    expected = pd.DataFrame(
        {
            "sản phẩm": ["Cà phê sữa"],
            "doanh thu": [Decimal("125000.50")],
        }
    )

    write_data(expected, destination, sheet_name="đã làm sạch")
    actual = read_data(destination, sheet_name="đã làm sạch")

    assert actual.loc[0, "sản phẩm"] == "Cà phê sữa"
    assert float(actual.loc[0, "doanh thu"]) == pytest.approx(125000.50)


def test_legacy_xls_output_is_rejected_instead_of_mislabeled(tmp_path: Path) -> None:
    destination = tmp_path / "legacy.xls"

    with pytest.raises(ImportError, match="write .xlsx instead"):
        write_data(pd.DataFrame({"value": [1]}), destination)

    assert not destination.exists()


def test_bad_csv_lines_error_by_default_or_are_explicitly_captured(tmp_path: Path) -> None:
    source = tmp_path / "broken.csv"
    source.write_text("a,b\n0,1\n1,2,extra\n3,4\n", encoding="utf-8")

    with pytest.raises(pd.errors.ParserError):
        read_data(source)

    diagnostics = ReadDiagnostics()
    frame = read_data(source, bad_line_policy="capture", diagnostics=diagnostics)
    assert frame.to_dict("records") == [{"a": "0", "b": "1"}, {"a": "3", "b": "4"}]
    assert len(diagnostics.rejected_rows) == 1
    assert diagnostics.rejected_rows[0].reason == "field_count_mismatch"
    assert diagnostics.rejects_frame().loc[0, "fields_json"] == '["1", "2", "extra"]'

    with pytest.raises(ValueError, match="ReadDiagnostics"):
        read_data(source, bad_line_policy="capture")
    with pytest.raises(ValueError, match="không bỏ dòng lỗi âm thầm"):
        read_data(source, on_bad_lines="skip")


def test_rejected_csv_rows_have_a_hard_memory_bound(tmp_path: Path) -> None:
    source = tmp_path / "many-bad.csv"
    source.write_text("a,b\n0,1\n1,2,extra\n3,4,extra\n", encoding="utf-8")
    diagnostics = ReadDiagnostics()

    with pytest.raises(ResourceLimitError, match="Rejected rows"):
        read_data(
            source,
            bad_line_policy="capture",
            diagnostics=diagnostics,
            resource_limits={"max_rejected_rows": 1},
        )

    assert len(diagnostics.rejected_rows) == 1


def test_read_chunks_streams_csv_and_enforces_total_row_limit(tmp_path: Path) -> None:
    source = tmp_path / "large.csv"
    pd.DataFrame({"x": range(5)}).to_csv(source, index=False)

    chunks = list(read_chunks(source, chunksize=2))
    assert [len(chunk) for chunk in chunks] == [2, 2, 1]
    assert pd.concat(chunks, ignore_index=True)["x"].tolist() == [str(i) for i in range(5)]

    with pytest.raises(ResourceLimitError, match="dòng"):
        list(read_chunks(source, chunksize=2, resource_limits={"max_rows": 3}))


def test_full_csv_preflight_respects_memory_budget_but_chunks_remain_available(
    tmp_path: Path,
) -> None:
    source = tmp_path / "bounded.csv"
    source.write_text("value\n" + ("x" * 100_000) + "\n", encoding="utf-8")

    with pytest.raises(ResourceLimitError, match="ngân sách RAM"):
        read_data(source, resource_limits={"max_memory_mb": 1})

    chunks = list(
        read_chunks(source, chunksize=1, resource_limits={"max_memory_mb": 1})
    )
    assert len(chunks) == 1


def test_csv_and_sqlite_shape_budget_prevents_wide_row_explosion(tmp_path: Path) -> None:
    csv_path = tmp_path / "wide.csv"
    csv_path.write_text("a,b,c,d\n1,2,3,4\n5,6,7,8\n", encoding="utf-8")
    with pytest.raises(ResourceLimitError, match="ô"):
        read_data(csv_path, resource_limits={"max_cells": 4})
    with pytest.raises(ResourceLimitError, match="chunksize"):
        list(read_chunks(csv_path, chunksize=2, resource_limits={"max_cells": 4}))

    database = tmp_path / "wide.db"
    write_data(
        pd.DataFrame({"a": [1, 2], "b": [3, 4], "c": [5, 6]}),
        database,
        table="records",
    )
    with pytest.raises(ResourceLimitError, match="ô"):
        read_data(database, table="records", resource_limits={"max_cells": 3})


def test_capture_prepass_stops_at_row_budget_instead_of_scanning_all_blanks(
    tmp_path: Path,
) -> None:
    source = tmp_path / "blank-flood.csv"
    source.write_text("a\n" + ("\n" * 100), encoding="utf-8")

    with pytest.raises(ResourceLimitError, match="dòng"):
        read_data(
            source,
            bad_line_policy="capture",
            diagnostics=ReadDiagnostics(),
            resource_limits={"max_rows": 3},
        )


def test_csv_preserves_identifier_zeroes_unless_inference_is_explicit(tmp_path: Path) -> None:
    source = tmp_path / "ids.csv"
    source.write_text("id,value\n001,10\n", encoding="utf-8")

    safe = read_data(source)
    inferred = read_data(source, infer_dtypes=True)

    assert safe.loc[0, "id"] == "001"
    assert inferred.loc[0, "id"] == 1


@pytest.mark.parametrize("policy", ["error", "capture"])
def test_csv_blank_records_are_preserved_by_default(tmp_path: Path, policy: str) -> None:
    source = tmp_path / "blank-row.csv"
    source.write_text("id,value\n001,a\n\n002,b\n", encoding="utf-8")
    diagnostics = ReadDiagnostics() if policy == "capture" else None

    frame = read_data(source, bad_line_policy=policy, diagnostics=diagnostics)

    assert len(frame) == 3
    assert frame.loc[0, "id"] == "001"
    assert pd.isna(frame.loc[1, "id"])
    assert frame.loc[2, "id"] == "002"


def test_sqlite_writes_decimal_as_exact_text(tmp_path: Path) -> None:
    destination = tmp_path / "finance.db"
    frame = pd.DataFrame({"amount": [Decimal("125000.50"), Decimal("0.10")]})

    write_data(frame, destination, table="transactions")
    actual = read_data(destination, table="transactions")

    assert actual["amount"].tolist() == ["125000.50", "0.10"]


def test_capture_csv_supports_header_quote_and_traces_syntax_errors(
    tmp_path: Path,
) -> None:
    source = tmp_path / "quoted.csv"
    source.write_text(
        "Ghi chú trước bảng\n"
        "id;name;amount\n"
        "001;'Cà phê; sữa';1.234,50\n"
        "002;'quote lỗi'x;10,00\n"
        "003;'Trà';20,00\n",
        encoding="utf-8",
    )
    diagnostics = ReadDiagnostics()

    frame = read_data(
        source,
        sep=";",
        quotechar="'",
        doublequote=True,
        header_row=1,
        bad_line_policy="capture",
        diagnostics=diagnostics,
    )

    assert frame["id"].tolist() == ["001", "003"]
    assert frame.loc[0, "name"] == "Cà phê; sữa"
    assert diagnostics.source_records == 5
    assert diagnostics.accepted_records == 4
    assert len(diagnostics.rejected_rows) == 1
    rejected = diagnostics.rejected_rows[0]
    assert rejected.reason == "csv_parse_error"
    assert rejected.line_number == rejected.end_line_number == 4
    assert rejected.record_number == 4


def test_capture_csv_rejects_embedded_null_with_source_trace(tmp_path: Path) -> None:
    source = tmp_path / "null.csv"
    source.write_bytes(b"a,b\n1,ok\n2,bad\x00value\n3,ok\n")
    diagnostics = ReadDiagnostics()

    with pytest.raises(UnsafeInputError, match="null byte"):
        read_data(source)
    frame = read_data(source, bad_line_policy="capture", diagnostics=diagnostics)

    assert frame["a"].tolist() == ["1", "3"]
    assert diagnostics.rejected_rows[0].reason == "embedded_null_byte"
    assert diagnostics.rejected_rows[0].line_number == 3


def test_chunk_checkpoint_resume_and_cooperative_cancellation(tmp_path: Path) -> None:
    source = tmp_path / "large.csv"
    pd.DataFrame({"id": range(6)}).to_csv(source, index=False)
    checkpoints: list[ChunkCheckpoint] = []

    resumed = list(
        read_chunks(
            source,
            chunksize=2,
            start_row=2,
            checkpoint_callback=checkpoints.append,
        )
    )

    assert pd.concat(resumed, ignore_index=True)["id"].tolist() == ["2", "3", "4", "5"]
    assert checkpoints[-1].rows_processed == 6
    assert checkpoints[-1].phase == "read"
    with pytest.raises(InterruptedError, match="VC-CANCEL"):
        list(read_chunks(source, cancel_callback=lambda: True))


def test_write_chunks_is_atomic_checks_schema_and_reports_checkpoints(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "chunked.csv"
    checkpoints: list[ChunkCheckpoint] = []
    write_chunks(
        [pd.DataFrame({"id": ["001"]}), pd.DataFrame({"id": ["002"]})],
        destination,
        checkpoint_callback=checkpoints.append,
    )
    assert read_data(destination)["id"].tolist() == ["001", "002"]
    assert checkpoints[-1].rows_processed == 2

    original = destination.read_bytes()
    with pytest.raises(ValueError, match="cùng cột"):
        write_chunks(
            [pd.DataFrame({"id": [1]}), pd.DataFrame({"other": [2]})],
            destination,
            overwrite=True,
        )
    assert destination.read_bytes() == original


def test_multi_sheet_excel_read_write_metadata_and_selection(tmp_path: Path) -> None:
    pytest.importorskip("openpyxl")
    destination = tmp_path / "multi.xlsx"
    frames = {
        "Orders": pd.DataFrame({"id": ["001", "002"], "amount": [10, 20]}),
        "Notes": pd.DataFrame({"note": ["Nội bộ"]}),
    }

    write_excel_sheets(frames, destination)
    info = inspect_excel_workbook(destination)
    selected = read_excel_sheets(destination, sheets=[1, "Orders"])

    assert [sheet.name for sheet in info.sheets] == ["Orders", "Notes"]
    assert list(selected) == ["Notes", "Orders"]
    assert selected["Orders"]["id"].astype(str).tolist() == ["001", "002"]


def test_excel_header_notes_merged_cells_and_multiple_table_selection(
    tmp_path: Path,
) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    destination = tmp_path / "tables.xlsx"
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = "Data"
    worksheet.append(["Ghi chú", None, None, None, None])
    worksheet.append([None, None, None, None, None])
    worksheet.append(["id", "name", None, "code", "value"])
    worksheet.append(["001", "Cà phê", None, "A", 10])
    worksheet.append(["002", "Trà", None, "B", 20])
    worksheet.merge_cells("A4:A5")
    workbook.save(destination)

    frame = read_data(destination, sheet_name="Data", header_row=2)
    regions = detect_excel_tables(destination, sheet_name="Data")
    tables = read_excel_tables(destination, sheet_name="Data", table_indices=[1, 2])
    info = inspect_excel_workbook(destination)

    assert "Unnamed: 2" in frame.columns
    assert pd.isna(frame.iloc[1, 0])  # merged cells are not guessed/forward-filled
    assert len(regions) == 3  # note plus two side-by-side tables
    assert [table.frame.shape[1] for table in tables] == [2, 2]
    assert info.sheets[0].merged_range_count == 1


def test_csv_to_xlsx_integration_and_formula_is_never_evaluated(tmp_path: Path) -> None:
    pytest.importorskip("openpyxl")
    source = tmp_path / "source.csv"
    destination = tmp_path / "clean.xlsx"
    source.write_text("id,note\n001,=1+1\n", encoding="utf-8")

    write_data(read_data(source), destination)

    assert read_data(destination).loc[0, "note"] == "'=1+1"


def test_output_root_traversal_and_symlink_are_rejected(tmp_path: Path) -> None:
    root = tmp_path / "safe"
    outside = tmp_path / "outside.csv"
    with pytest.raises(UnsafeInputError, match="ngoài output_root"):
        write_data(pd.DataFrame({"x": [1]}), outside, output_root=root)

    link = root / "linked.csv"
    root.mkdir()
    target = root / "target.csv"
    target.write_text("original\n", encoding="utf-8")
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("Nền tảng hiện tại không cho tạo symlink trong test.")
    with pytest.raises(UnsafeInputError, match="symbolic link"):
        validate_output_path(link, output_root=root)
    assert target.read_text(encoding="utf-8") == "original\n"


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("fake.xlsx", b"not-a-zip"),
        ("fake.sqlite", b"not-sqlite"),
        ("fake.parquet", b"PAR1bad!"),
    ],
)
def test_fake_file_extensions_fail_safely(
    tmp_path: Path,
    name: str,
    content: bytes,
) -> None:
    source = tmp_path / name
    source.write_bytes(content)

    with pytest.raises(UnsafeInputError, match="VC-SAFE"):
        read_data(source)


def test_failed_sqlite_replace_is_atomic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database = tmp_path / "atomic.sqlite"
    write_data(pd.DataFrame({"value": [1]}), database, table="records")
    original = database.read_bytes()

    def fail_to_sql(self: pd.DataFrame, *_args: object, **_kwargs: object) -> None:
        raise RuntimeError("conversion failed")

    monkeypatch.setattr(pd.DataFrame, "to_sql", fail_to_sql)
    with pytest.raises(RuntimeError, match="conversion failed"):
        write_data(
            pd.DataFrame({"value": [2]}),
            database,
            table="records",
            if_exists="replace",
        )
    assert database.read_bytes() == original
