from __future__ import annotations

import csv
import sqlite3
import types
from contextlib import nullcontext
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pandas as pd
import pytest

import vietclean.io as io
from vietclean.exceptions import ResourceLimitError, UnsafeInputError, UnsupportedFormatError
from vietclean.io import (
    ReadDiagnostics,
    detect_csv_format,
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
from vietclean.security.resources import ResourceLimits, check_input_file, enforce_frame_limits


def test_encoding_and_dialect_edge_cases(tmp_path: Path) -> None:
    empty = tmp_path / "empty.csv"
    empty.write_bytes(b"")
    utf16 = tmp_path / "utf16.tsv"
    utf16.write_text("a\tb\n1\t2\n", encoding="utf-16")
    western = tmp_path / "western.csv"
    western.write_bytes("name\nAndré\n".encode("cp1252"))
    quoted = tmp_path / "quoted.csv"
    quoted.write_text("id|'a|b'\n1|'x|y'\n", encoding="utf-8")

    assert detect_encoding(empty) == "utf-8"
    assert detect_encoding(utf16) == "utf-16"
    assert detect_encoding(western) == "cp1252"
    detected = detect_csv_format(quoted)
    assert detected.delimiter == "|"
    assert detected.quotechar == "'"


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"timeout_seconds": "1"}, TypeError),
        ({"timeout_seconds": 0}, ValueError),
        ({"cancel_callback": 1}, TypeError),
        ({"bad_line_policy": "skip"}, ValueError),
        ({"sep": ",", "delimiter": ";"}, ValueError),
        ({"chunksize": 2}, ValueError),
        ({"header_row": -1}, ValueError),
        ({"header_row": False}, TypeError),
    ],
)
def test_read_data_validates_dangerous_options(
    tmp_path: Path,
    kwargs: dict[str, object],
    error: type[Exception],
) -> None:
    source = tmp_path / "source.csv"
    source.write_text("a\n1\n", encoding="utf-8")
    with pytest.raises(error):
        read_data(source, **kwargs)


def test_read_data_rejects_wrong_source_and_database_options(tmp_path: Path) -> None:
    source = tmp_path / "source.csv"
    source.write_text("a\n1\n", encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        read_data(tmp_path / "missing.csv")
    with pytest.raises(ValueError, match="not a file"):
        read_data(tmp_path, file_format="csv")
    with pytest.raises(ValueError, match="database"):
        read_data(source, table="x")
    with pytest.raises(ValueError, match="either table or query"):
        read_data(source, table="x", query="SELECT 1")
    with pytest.raises(TypeError, match="table"):
        read_data(source, table=1)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="query"):
        read_data(source, query=1)  # type: ignore[arg-type]

    connection = sqlite3.connect(":memory:")
    try:
        with pytest.raises(ValueError, match="file_format"):
            read_data(connection, file_format="csv")
        with pytest.raises(ValueError, match="no readable tables"):
            read_data(connection)
    finally:
        connection.close()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"chunksize": 0},
        {"chunksize": True},
        {"start_row": -1},
        {"start_row": "1"},
        {"checkpoint_callback": 1},
        {"sep": ",", "delimiter": ";"},
        {"bad_line_policy": "capture"},
    ],
)
def test_read_chunks_validates_stream_controls(
    tmp_path: Path,
    kwargs: dict[str, object],
) -> None:
    source = tmp_path / "source.csv"
    source.write_text("a\n1\n", encoding="utf-8")
    with pytest.raises((TypeError, ValueError)):
        list(read_chunks(source, **kwargs))

    workbook = tmp_path / "source.xlsx"
    pd.DataFrame({"a": [1]}).to_excel(workbook, index=False)
    with pytest.raises(UnsupportedFormatError):
        list(read_chunks(workbook))


def test_capture_dialect_header_none_names_and_option_guards(tmp_path: Path) -> None:
    source = tmp_path / "data.txt"
    source.write_text("001|'A|B'\n002|'C'\n", encoding="utf-8")
    diagnostics = ReadDiagnostics()
    frame = read_data(
        source,
        sep="|",
        quotechar="'",
        header_row=None,
        names=["id", "name"],
        bad_line_policy="capture",
        diagnostics=diagnostics,
    )
    assert frame["id"].tolist() == ["001", "002"]
    assert diagnostics.source_records == 2

    with pytest.raises(ValueError, match="ánh xạ dòng"):
        read_data(
            source,
            bad_line_policy="capture",
            diagnostics=ReadDiagnostics(),
            skiprows=1,
        )
    with pytest.raises(ValueError, match="on_bad_lines"):
        list(read_chunks(source, on_bad_lines="skip"))
    with pytest.raises(ValueError, match="on_bad_lines"):
        list(
            read_chunks(
                source,
                bad_line_policy="capture",
                diagnostics=ReadDiagnostics(),
                on_bad_lines="error",
            )
        )


def test_closing_chunk_generator_releases_filtered_temp_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.csv"
    source.write_text("a,b\n1,2\n3,4,extra\n5,6\n", encoding="utf-8")
    created: list[Path] = []
    original_mkstemp = io.tempfile.mkstemp

    def tracked_mkstemp(**kwargs: object) -> tuple[int, str]:
        kwargs["dir"] = str(tmp_path)
        descriptor, name = original_mkstemp(**kwargs)
        created.append(Path(name))
        return descriptor, name

    monkeypatch.setattr(io.tempfile, "mkstemp", tracked_mkstemp)
    chunks = read_chunks(
        source,
        chunksize=1,
        bad_line_policy="capture",
        diagnostics=ReadDiagnostics(),
    )
    assert next(chunks).iloc[0].tolist() == ["1", "2"]
    chunks.close()

    assert created and all(not path.exists() for path in created)
    source.rename(tmp_path / "renamed.csv")  # also proves no Windows source handle leak


def test_excel_public_api_validation_and_selection(tmp_path: Path) -> None:
    pytest.importorskip("openpyxl")
    workbook = tmp_path / "book.xlsx"
    write_excel_sheets(
        {"One": pd.DataFrame({"a": [1]}), "Two": pd.DataFrame({"b": [2]})},
        workbook,
    )
    assert list(read_excel_sheets(workbook, sheets=-1)) == ["Two"]
    with pytest.raises(ValueError, match="Không có sheet"):
        read_excel_sheets(workbook, sheets="Missing")
    with pytest.raises(ValueError, match="ít nhất"):
        read_excel_sheets(workbook, sheets=[])
    with pytest.raises(TypeError, match="sheets"):
        read_excel_sheets(workbook, sheets=True)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="allow_macros"):
        inspect_excel_workbook(workbook, allow_macros=1)  # type: ignore[arg-type]
    with pytest.raises(UnsupportedFormatError):
        inspect_excel_workbook(tmp_path / "not-excel.csv")
    with pytest.raises(ValueError, match="header_row"):
        read_excel_tables(workbook, header_row=-1)
    with pytest.raises(TypeError, match="table_indices"):
        read_excel_tables(workbook, table_indices="0")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="table index"):
        read_excel_tables(workbook, table_indices=[True])
    with pytest.raises(ValueError, match="table index"):
        read_excel_tables(workbook, table_indices=[99])


@pytest.mark.parametrize("bad_name", ["", "x" * 32, "bad/name", "'quoted"])
def test_multi_sheet_writer_rejects_unsafe_names(tmp_path: Path, bad_name: str) -> None:
    with pytest.raises(ValueError):
        write_excel_sheets({bad_name: pd.DataFrame({"a": [1]})}, tmp_path / "x.xlsx")


def test_multi_sheet_writer_validates_shape_format_and_overwrite(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="không rỗng"):
        write_excel_sheets({}, tmp_path / "x.xlsx")
    with pytest.raises(UnsupportedFormatError, match="xlsx"):
        write_excel_sheets({"A": pd.DataFrame()}, tmp_path / "x.xlsm")
    with pytest.raises(ValueError, match="trùng"):
        write_excel_sheets(
            {"A": pd.DataFrame(), "a": pd.DataFrame()},
            tmp_path / "x.xlsx",
        )
    with pytest.raises(TypeError, match="DataFrame"):
        write_excel_sheets({"A": object()}, tmp_path / "x.xlsx")  # type: ignore[dict-item]
    destination = tmp_path / "exists.xlsx"
    write_excel_sheets({"A": pd.DataFrame({"x": [1]})}, destination)
    with pytest.raises(FileExistsError):
        write_excel_sheets({"A": pd.DataFrame({"x": [2]})}, destination)
    with pytest.raises(ResourceLimitError, match="sheet"):
        write_excel_sheets(
            {"A": pd.DataFrame(), "B": pd.DataFrame()},
            tmp_path / "many.xlsx",
            resource_limits={"max_excel_sheets": 1},
        )


def test_chunk_writer_validates_controls_and_limits(tmp_path: Path) -> None:
    destination = tmp_path / "chunks.csv"
    with pytest.raises(ValueError, match="Không có chunk"):
        write_chunks([], destination)
    with pytest.raises(TypeError, match="DataFrame"):
        write_chunks([object()], destination)  # type: ignore[list-item]
    with pytest.raises(ValueError, match="mode/header"):
        write_chunks([pd.DataFrame({"a": [1]})], destination, header=True)
    with pytest.raises(TypeError, match="checkpoint"):
        write_chunks([pd.DataFrame({"a": [1]})], destination, checkpoint_callback=1)  # type: ignore[arg-type]
    with pytest.raises(UnsupportedFormatError):
        write_chunks([pd.DataFrame({"a": [1]})], tmp_path / "x.xlsx")
    with pytest.raises(ResourceLimitError, match="Tổng chunk"):
        write_chunks(
            [pd.DataFrame({"a": [1]}), pd.DataFrame({"a": [2]})],
            destination,
            resource_limits={"max_rows": 1},
        )
    assert not destination.exists()


def test_output_path_null_directory_and_secure_mode_validation(tmp_path: Path) -> None:
    with pytest.raises(UnsafeInputError, match="null byte"):
        validate_output_path("bad\x00.csv")
    with pytest.raises(TypeError, match="secure_mode"):
        validate_output_path(tmp_path / "x.csv", secure_mode=1)  # type: ignore[arg-type]
    directory = tmp_path / "directory.csv"
    directory.mkdir()
    with pytest.raises(UnsafeInputError, match="không phải file"):
        validate_output_path(directory)
    nested = validate_output_path(
        tmp_path / "root" / "nested" / "out.csv",
        output_root=tmp_path / "root",
    )
    assert nested.parent.is_dir()


def test_write_data_database_and_format_guards(tmp_path: Path) -> None:
    frame = pd.DataFrame({"a": [1]})
    with pytest.raises(ValueError, match="if_exists"):
        write_data(frame, tmp_path / "x.db", table="t", if_exists="drop")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="table is required"):
        write_data(frame, tmp_path / "x.db")
    with pytest.raises(ValueError, match="table is only"):
        write_data(frame, tmp_path / "x.csv", table="t")
    with pytest.raises(ValueError, match="disagree"):
        write_data(frame, tmp_path / "x.csv", sep=",", delimiter=";")
    with pytest.raises(UnsupportedFormatError):
        write_data(frame, tmp_path / "x.unknown")
    with pytest.raises(ImportError, match="write .xlsx"):
        write_data(frame, tmp_path / "x.xlsb")


def test_sqlite_uri_and_progress_cancellation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    database = Path("relative.sqlite")
    write_data(pd.DataFrame({"x": [1]}), database, table="records")
    assert read_data("sqlite:///relative.sqlite", table="records").loc[0, "x"] == 1
    with pytest.raises(ValueError, match="parameters/fragments"):
        read_data("sqlite:///relative.sqlite?mode=ro", table="records")
    with pytest.raises(ValueError, match="syntax"):
        read_data("sqlite://relative.sqlite", table="records")

    calls = 0

    def cancel_during_query() -> bool:
        nonlocal calls
        calls += 1
        return calls > 4

    with pytest.raises(InterruptedError, match="VC-CANCEL"):
        read_data(
            database,
            query=(
                "WITH RECURSIVE seq(x) AS (SELECT 1 UNION ALL "
                "SELECT x + 1 FROM seq WHERE x < 1000000) SELECT x FROM seq"
            ),
            cancel_callback=cancel_during_query,
            resource_limits={"max_rows": 500_000},
        )


def test_bounded_sql_chunk_consumer() -> None:
    guard = io._OperationGuard(30, None)
    empty = io._consume_sql_chunks([], limits=ResourceLimits(), guard=guard)
    assert empty.empty
    with pytest.raises(ResourceLimitError, match="cột"):
        io._consume_sql_chunks(
            [pd.DataFrame([[1, 2]])],
            limits=ResourceLimits(max_columns=1),
            guard=guard,
        )
    with pytest.raises(ResourceLimitError, match="dòng/ô"):
        io._consume_sql_chunks(
            [pd.DataFrame({"a": [1, 2]})],
            limits=ResourceLimits(max_rows=1),
            guard=guard,
        )


@pytest.mark.parametrize(
    "values",
    [
        {"max_rows": True},
        {"max_rows": 1.5},
        {"max_rows": 0},
        {"max_zip_ratio": True},
        {"max_zip_ratio": 1},
        {"unknown": 1},
    ],
)
def test_resource_limit_configuration_is_strict(values: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        ResourceLimits.from_mapping(values)


def test_input_symlink_is_rejected_when_platform_supports_it(tmp_path: Path) -> None:
    target = tmp_path / "target.csv"
    target.write_text("a\n1\n", encoding="utf-8")
    link = tmp_path / "link.csv"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("Nền tảng không cho tạo symlink.")
    with pytest.raises(UnsafeInputError, match="symbolic link"):
        check_input_file(link)
    assert check_input_file(link, allow_symlinks=True) == link


def test_custom_csv_dialect_can_be_captured(tmp_path: Path) -> None:
    class PipeDialect(csv.Dialect):
        delimiter = "|"
        quotechar = '"'
        doublequote = True
        escapechar = None
        lineterminator = "\n"
        quoting = csv.QUOTE_MINIMAL
        skipinitialspace = False

    source = tmp_path / "dialect.csv"
    source.write_text('id|note\n001|"a|b"\n', encoding="utf-8")
    frame = read_data(
        source,
        sep="|",
        dialect=PipeDialect,
        bad_line_policy="capture",
        diagnostics=ReadDiagnostics(),
    )
    assert frame.loc[0, "note"] == "a|b"


class _FakeSQLAlchemyError(Exception):
    pass


class _FakeNoSuchModuleError(_FakeSQLAlchemyError):
    pass


class _FakeConnection:
    def execution_options(self, **_options: object) -> "_FakeConnection":
        return self

    def __enter__(self) -> "_FakeConnection":
        return self

    def __exit__(self, *_args: object) -> None:
        return None


class _FakeEngine:
    def __init__(self, *, fail_connect: bool = False) -> None:
        self.fail_connect = fail_connect
        self.disposed = False
        self.connection = _FakeConnection()

    def connect(self) -> _FakeConnection:
        if self.fail_connect:
            raise _FakeSQLAlchemyError("postgresql://user:secret@example.invalid/db")
        return self.connection

    def begin(self) -> nullcontext[_FakeConnection]:
        if self.fail_connect:
            raise _FakeSQLAlchemyError("postgresql://user:secret@example.invalid/db")
        return nullcontext(self.connection)

    def dispose(self) -> None:
        self.disposed = True


class _FakeSQLAlchemy:
    class exc:
        SQLAlchemyError = _FakeSQLAlchemyError
        NoSuchModuleError = _FakeNoSuchModuleError

    def __init__(self, engine: _FakeEngine | None = None) -> None:
        self.engine = engine or _FakeEngine()
        self.fail_create = False

    def create_engine(self, _uri: str) -> _FakeEngine:
        if self.fail_create:
            raise _FakeNoSuchModuleError("driver with secret")
        return self.engine

    @staticmethod
    def text(statement: str) -> str:
        return statement


def test_remote_sql_reads_are_streamed_bounded_and_parameterized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeSQLAlchemy()
    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(io, "_load_sqlalchemy", lambda: fake)

    def fake_query(
        statement: str,
        _connection: object,
        **options: object,
    ) -> list[pd.DataFrame]:
        calls.append((statement, options.get("params")))
        return [pd.DataFrame({"id": [1, 2]})]

    def fake_table(
        table: str,
        _connection: object,
        **_options: object,
    ) -> list[pd.DataFrame]:
        calls.append((table, None))
        return [pd.DataFrame({"id": [3]})]

    monkeypatch.setattr(pd, "read_sql_query", fake_query)
    monkeypatch.setattr(pd, "read_sql_table", fake_table)
    uri = "postgresql://user:secret@example.invalid/db"
    queried = read_data(
        uri,
        query="SELECT id FROM orders WHERE id >= :minimum",
        params={"minimum": 1},
        allow_remote_database=True,
        allow_remote_query=True,
    )
    table = read_data(uri, table="orders", allow_remote_database=True)

    assert queried["id"].tolist() == [1, 2]
    assert table["id"].tolist() == [3]
    assert calls[0][1] == {"minimum": 1}
    assert fake.engine.disposed


def test_remote_sql_errors_redact_credentials_and_driver_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uri = "postgresql://user:secret@example.invalid/db"
    failing = _FakeSQLAlchemy(_FakeEngine(fail_connect=True))
    monkeypatch.setattr(io, "_load_sqlalchemy", lambda: failing)
    with pytest.raises(ConnectionError) as read_error:
        read_data(uri, table="orders", allow_remote_database=True)
    assert "secret" not in str(read_error.value)

    failing.fail_create = True
    with pytest.raises(ImportError) as driver_error:
        read_data(uri, table="orders", allow_remote_database=True)
    assert "secret" not in str(driver_error.value)


def test_remote_sql_write_is_explicit_and_redacts_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uri = "postgresql://user:secret@example.invalid/db"
    fake = _FakeSQLAlchemy()
    writes: list[tuple[str, str]] = []
    monkeypatch.setattr(io, "_load_sqlalchemy", lambda: fake)

    def fake_to_sql(
        self: pd.DataFrame,
        table: str,
        _connection: object,
        **options: object,
    ) -> None:
        writes.append((table, str(options["if_exists"])))

    monkeypatch.setattr(pd.DataFrame, "to_sql", fake_to_sql)
    write_data(
        pd.DataFrame({"id": [1]}),
        uri,
        table="cleaned",
        allow_remote_database=True,
    )
    assert writes == [("cleaned", "fail")]

    failing = _FakeSQLAlchemy(_FakeEngine(fail_connect=True))
    monkeypatch.setattr(io, "_load_sqlalchemy", lambda: failing)
    with pytest.raises(ConnectionError) as error:
        write_data(
            pd.DataFrame({"id": [1]}),
            uri,
            table="cleaned",
            allow_remote_database=True,
        )
    assert "secret" not in str(error.value)


def test_parquet_public_path_is_preflighted_and_dependency_error_is_clear(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "data.parquet"
    source.write_bytes(b"PAR1payloadPAR1")
    preflighted: list[Path] = []
    monkeypatch.setattr(
        io,
        "_preflight_parquet",
        lambda path, **_kwargs: preflighted.append(path),
    )
    monkeypatch.setattr(pd, "read_parquet", lambda *_args, **_kwargs: pd.DataFrame({"x": [1]}))
    assert read_data(source).loc[0, "x"] == 1
    assert preflighted == [source]

    def missing_engine(*_args: object, **_kwargs: object) -> pd.DataFrame:
        raise ImportError("missing")

    monkeypatch.setattr(pd, "read_parquet", missing_engine)
    with pytest.raises(ImportError, match="optional"):
        read_data(source)
    with pytest.raises(ValueError, match="database"):
        read_data(source, table="x")


def test_parquet_metadata_limits_are_checked_before_load(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "data.parquet"
    source.write_bytes(b"PAR1payloadPAR1")

    class RowGroup:
        total_byte_size = 64

    class Metadata:
        num_rows = 3
        num_columns = 2
        num_row_groups = 2

        @staticmethod
        def row_group(_index: int) -> RowGroup:
            return RowGroup()

    class ParquetFile:
        metadata = Metadata()

    parquet_module = types.ModuleType("pyarrow.parquet")
    parquet_module.ParquetFile = lambda _path: ParquetFile()  # type: ignore[attr-defined]
    pyarrow_module = types.ModuleType("pyarrow")
    pyarrow_module.parquet = parquet_module  # type: ignore[attr-defined]
    monkeypatch.setitem(__import__("sys").modules, "pyarrow", pyarrow_module)
    monkeypatch.setitem(__import__("sys").modules, "pyarrow.parquet", parquet_module)

    io._preflight_parquet(source, options={"columns": ["a"]}, limits=ResourceLimits())
    with pytest.raises(TypeError, match="sequence"):
        io._preflight_parquet(source, options={"columns": "a"}, limits=ResourceLimits())
    with pytest.raises(ResourceLimitError, match="dòng"):
        io._preflight_parquet(source, options={}, limits=ResourceLimits(max_rows=2))
    with pytest.raises(ResourceLimitError, match="cột"):
        io._preflight_parquet(source, options={}, limits=ResourceLimits(max_columns=1))
    with pytest.raises(ResourceLimitError, match="ô"):
        io._preflight_parquet(source, options={}, limits=ResourceLimits(max_cells=5))


def test_legacy_excel_metadata_is_bounded_without_loading_cells(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "legacy.xls"
    source.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1payload")

    class FakeExcelFile:
        sheet_names = ["One", "Two"]

        def __init__(self, _path: Path) -> None:
            pass

        def __enter__(self) -> "FakeExcelFile":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr(pd, "ExcelFile", FakeExcelFile)
    info = inspect_excel_workbook(source)
    assert [sheet.name for sheet in info.sheets] == ["One", "Two"]
    with pytest.raises(ResourceLimitError, match="worksheet"):
        inspect_excel_workbook(source, resource_limits={"max_excel_sheets": 1})


def test_resource_file_and_memory_branches(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match="allow_symlinks"):
        check_input_file(tmp_path / "missing.csv", allow_symlinks=1)  # type: ignore[arg-type]
    assert check_input_file(tmp_path / "missing.csv").name == "missing.csv"
    short = tmp_path / "short.parquet"
    short.write_bytes(b"PAR1")
    with pytest.raises(UnsafeInputError, match="quá ngắn"):
        check_input_file(short)
    with pytest.raises(ResourceLimitError, match="cột"):
        enforce_frame_limits(pd.DataFrame([[1, 2]]), ResourceLimits(max_columns=1))
    with pytest.raises(ResourceLimitError, match="RAM"):
        enforce_frame_limits(
            pd.DataFrame({"text": ["x" * 2_000_000]}),
            ResourceLimits(max_memory_mb=1, max_cell_length=3_000_000),
        )


def test_zip_container_entry_expansion_memory_and_structure_limits(tmp_path: Path) -> None:
    required = {
        "[Content_Types].xml": "x",
        "_rels/.rels": "x",
        "xl/workbook.xml": "x",
    }
    entries = tmp_path / "entries.xlsx"
    with ZipFile(entries, "w") as archive:
        for name, value in required.items():
            archive.writestr(name, value)
        archive.writestr("extra", "x")
    with pytest.raises(ResourceLimitError, match="archive entries"):
        check_input_file(entries, ResourceLimits(max_archive_entries=3))

    expanded = tmp_path / "expanded.xlsx"
    with ZipFile(expanded, "w", compression=ZIP_DEFLATED) as archive:
        for name, value in required.items():
            archive.writestr(name, value)
        archive.writestr("xl/sharedStrings.xml", "x" * (1024 * 1024 + 1))
    with pytest.raises(ResourceLimitError, match="bung nén"):
        check_input_file(
            expanded,
            ResourceLimits(max_archive_uncompressed_mb=1, max_zip_ratio=10_000),
        )
    with pytest.raises(ResourceLimitError, match="ngân sách RAM"):
        check_input_file(
            expanded,
            ResourceLimits(max_memory_mb=8, max_zip_ratio=10_000),
        )

    malformed = tmp_path / "structure.xlsx"
    with ZipFile(malformed, "w") as archive:
        archive.writestr("[Content_Types].xml", "x")
    with pytest.raises(UnsafeInputError, match="không khớp"):
        check_input_file(malformed)


def test_additional_bounded_reader_and_excel_failure_branches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    csv_path = tmp_path / "wide.csv"
    csv_path.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")
    with pytest.raises(ResourceLimitError, match="cột"):
        read_data(csv_path, resource_limits={"max_columns": 1})
    with pytest.raises(ResourceLimitError, match="cột"):
        list(read_chunks(csv_path, resource_limits={"max_columns": 1}))
    with pytest.raises(ResourceLimitError, match="ô"):
        list(read_chunks(csv_path, chunksize=1, resource_limits={"max_cells": 2}))
    with pytest.raises(ValueError, match="error hoặc capture"):
        list(read_chunks(csv_path, bad_line_policy="skip"))  # type: ignore[arg-type]

    workbook = tmp_path / "book.xlsx"
    write_excel_sheets({"A": pd.DataFrame({"x": [1]})}, workbook)
    with pytest.raises(ValueError, match="database"):
        read_data(workbook, table="x")
    with pytest.raises(UnsupportedFormatError):
        io.detect_excel_tables(tmp_path / "legacy.xls")
    with pytest.raises(TypeError, match="infer_dtypes"):
        read_excel_tables(workbook, infer_dtypes=1)  # type: ignore[arg-type]

    monkeypatch.setattr(pd, "read_excel", lambda *_args, **_kwargs: {})
    with pytest.raises(ValueError, match="exactly one"):
        read_data(workbook)

    def missing_excel(*_args: object, **_kwargs: object) -> pd.DataFrame:
        raise ImportError("missing")

    monkeypatch.setattr(pd, "read_excel", missing_excel)
    with pytest.raises(ImportError, match="openpyxl"):
        read_data(workbook)


def test_excel_multi_sheet_aggregate_row_limit(tmp_path: Path) -> None:
    workbook = tmp_path / "aggregate.xlsx"
    write_excel_sheets(
        {"A": pd.DataFrame({"x": [1]}), "B": pd.DataFrame({"x": [2]})},
        workbook,
    )
    with pytest.raises(ResourceLimitError, match="Tổng dữ liệu"):
        read_excel_sheets(workbook, resource_limits={"max_rows": 1})


def test_parquet_writer_is_atomic_and_format_helpers_are_strict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "data.parquet"

    def fake_to_parquet(
        self: pd.DataFrame,
        path: Path,
        **_options: object,
    ) -> None:
        Path(path).write_bytes(b"PAR1payloadPAR1")

    monkeypatch.setattr(pd.DataFrame, "to_parquet", fake_to_parquet)
    write_data(pd.DataFrame({"x": [1]}), destination)
    assert destination.read_bytes().startswith(b"PAR1")
    with pytest.raises(ValueError, match="Unsupported file_format"):
        write_data(pd.DataFrame(), tmp_path / "x", file_format="pickle")
    with pytest.raises(TypeError, match="file_format"):
        io._normalise_format(1)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="ResourceLimits"):
        read_data(tmp_path / "missing.csv", resource_limits=1)  # type: ignore[arg-type]


def test_operation_timeout_and_internal_selection_guards(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = iter([0.0, 2.0])
    monkeypatch.setattr(io.time, "monotonic", lambda: next(clock))
    guard = io._OperationGuard(1, None)
    with pytest.raises(TimeoutError, match="VC-TIMEOUT"):
        guard.check()

    with pytest.raises(ResourceLimitError, match="Yêu cầu đọc"):
        io._select_excel_sheets(["A", "B"], "all", 1)
    with pytest.raises(ValueError, match="sheet index"):
        io._select_excel_sheets(["A"], 2, 1)
    with pytest.raises(TypeError, match="selector"):
        io._select_excel_sheets(["A"], [object()], 1)  # type: ignore[list-item]
    with pytest.raises(ResourceLimitError, match="dòng"):
        io._enforce_excel_dimensions(3, 1, ResourceLimits(max_rows=1), "A")
    with pytest.raises(ResourceLimitError, match="cột"):
        io._enforce_excel_dimensions(1, 2, ResourceLimits(max_columns=1), "A")
    with pytest.raises(ResourceLimitError, match="ô"):
        io._enforce_excel_dimensions(2, 2, ResourceLimits(max_cells=3), "A")


def test_reject_byte_budget_and_csv_dialect_validation() -> None:
    diagnostics = ReadDiagnostics()
    with pytest.raises(ResourceLimitError, match="MB"):
        io._record_rejected_row(
            diagnostics,
            ["x" * (1024 * 1024 + 1)],
            ResourceLimits(max_rejected_bytes_mb=1),
        )
    with pytest.raises(ValueError, match="dialect"):
        io._csv_reader_options(",", {"dialect": "missing-dialect"})
    with pytest.raises(ValueError, match="quotechar"):
        io._csv_reader_options(",", {"quotechar": ""})
