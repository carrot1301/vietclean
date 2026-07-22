# Kiến trúc VietClean

## Mục tiêu và ranh giới

VietClean là thư viện/CLI xử lý bảng dữ liệu cục bộ, không phải dịch vụ web hay workflow
engine. Thiết kế hiện tại chọn pipeline nhỏ, dễ audit thay vì hệ plugin động. Core runtime
không gọi HTTP, không telemetry và không tải rule. Một URI PostgreSQL/MySQL/SQL Server
chỉ có thể mở kết nối mạng sau opt-in `allow_remote_database`; query tùy chỉnh còn có
opt-in riêng. Trường hợp này nằm ngoài bảo đảm xử lý hoàn toàn cục bộ.

Luồng chính:

```text
CSV / XLSX / SQLite / URI được chỉ định
                 │
                 ▼
      kiểm tra file + giới hạn tài nguyên
                 │
                 ▼
       read_data / read_chunks (CSV)
                 │
        ┌────────┴────────┐
        ▼                 ▼
 inspect_dataframe   DataCleaner.clean
   (read-only)       (copy mặc định)
                          │
                          ▼
              audit + quality metrics
                          │
                          ▼
              formula protection
                          │
                          ▼
          atomic file writer / DB writer
```

CLI điều phối các bước này; `DataCleaner` không tự đọc hoặc tự ghi file. Sự tách biệt đó
cho phép dùng `pandas.DataFrame` trực tiếp mà không cần I/O.

## Thành phần

| Module | Trách nhiệm | Không chịu trách nhiệm |
|---|---|---|
| `config.py` | Đọc TOML/JSON, merge mặc định, kiểm tra option cơ bản | Thực thi code hoặc I/O data |
| `profiles.py` | Alias tên cột và rule mặc định cho generic/F&B/finance/ecommerce/marketing | Đoán nghiệp vụ doanh nghiệp cụ thể |
| `text.py` | Hàm scalar Unicode, mojibake, whitespace, missing, email, phone, số/tiền | Đọc file hoặc quyết định xóa dòng |
| `pipeline.py` | Điều phối cleaning, conversion, rule cột, missing, duplicate và audit | Ghi file hoặc kết nối mạng |
| `io.py` | Nhận diện/đọc/ghi CSV, Excel, Parquet, SQLite/SQLAlchemy; atomic local output | Tự chọn rule cleaning |
| `inspection.py` | Thống kê read-only, aggregate mặc định | Sửa dữ liệu |
| `quality.py`, `report.py` | Audit và quality report aggregate | Lưu sample/raw PII mặc định |
| `security/` | Formula guard, PII classifier/mask, SQL allowlist, resource limits | Thay thế quyền OS/database |
| `logging_utils.py` | Text/JSONL log, correlation ID và redaction ở mọi level | Cho phép log raw row/cell |
| `cli.py` | Parse cờ, redaction lỗi, bảo vệ input/output, đặt tên artifact và exit code | API ổn định thay cho module lõi |

## Thứ tự cleaning

`DataCleaner.clean()` thực hiện trên bản sao sâu trừ khi người gọi đặt `inplace=True`:

1. chuẩn hóa và deduplicate tên cột;
2. chuẩn hóa Unicode/ký tự ẩn/mojibake/whitespace, rồi canonicalize missing token;
3. lấy rule cột rõ ràng hoặc semantic type từ alias profile;
4. parse email, phone, số, phần trăm, tiền, ngày hoặc boolean;
5. áp dụng mapping, case, min/max, regex, allowed set và chính sách invalid;
6. áp dụng missing strategy đã cấu hình;
7. report/xóa empty và duplicate chỉ khi được bật;
8. hoàn tất `CleaningReport` với số liệu tổng hợp.

Rule cột rõ ràng được áp dụng dù tỷ lệ parse thấp. Với auto-type từ profile, conversion
chỉ được áp dụng khi đạt `minimum_success_rate`; nếu không dữ liệu gốc được giữ và có
cảnh báo. Đây là cơ chế bảo toàn dữ liệu, không phải schema inference đầy đủ.

Transformation dữ liệu hướng tới deterministic và các hàm normalize hướng tới
idempotent. Audit có timestamp bắt đầu/kết thúc nên file report không byte-identical giữa
hai lần chạy dù output data giống nhau.

## I/O và dependency

- CSV/TSV/TXT: phát hiện BOM/UTF-8/UTF-16 và một số encoding legacy bằng standard
  library; delimiter tự nhận diện hoặc chỉ định. CSV mặc định đọc dạng string để giữ số
  `0` đầu; `--infer-dtypes` là opt-in.
- XLSX: cần OpenPyXL. `.xls` cần `xlrd`; ghi `.xls` không được hỗ trợ. `.xlsm` bị từ
  chối mặc định và chỉ đọc khi bật rõ ràng; VietClean không chạy/bảo toàn macro.
- SQLite: dùng `sqlite3`; input path mở `mode=ro` và connection được đặt `query_only`.
- Database khác: SQLAlchemy và driver là optional; quyền read-only thực sự vẫn phải được
  enforce bằng account database.
- Parquet: cần PyArrow/fastparquet và không đi qua formula protection vì không phải định
  dạng spreadsheet.

CSV, XLSX và Parquet local được ghi vào file tạm cùng thư mục rồi `os.replace`. Database
write dùng transaction mà driver cung cấp; không có atomic rename cho toàn database.

## Báo cáo và dữ liệu nhạy cảm

Inspection, audit và quality report mặc định chỉ chứa count/ratio/tên cột. `--samples` là
opt-in và có thể lộ PII. Rejects chứa raw field của dòng CSV lỗi để sửa lại, vì vậy nhạy
cảm ngang input và phải có quyền truy cập/retention tương ứng.

Formula protection chạy trước export CSV/XLSX với mode `sanitize` mặc định. CLI ghi số
cell phát hiện/sanitize vào audit. `report_only` và `allow` là lựa chọn có rủi ro rõ ràng.

## Điểm mở rộng được phép

- Thêm alias/profile bằng dữ liệu tĩnh và test, không import Python từ config.
- Thêm transformation thuần nhận/trả `DataFrame` hoặc scalar.
- Thêm loader/exporter rõ định dạng, fail-safe và dependency optional khi nặng.

Không có plugin loader tùy ý, `eval`, `exec`, pickle cache hoặc monkey-patch pandas.

Logging dùng logger namespace `vietclean`, không thay root logger. Formatter chỉ phát hành
schema allowlist và redact message/exception ngay trước khi ghi. Xem [logging.md](logging.md).

## Giới hạn hiện tại

- CLI mặc định xử lý worksheet được chọn và hỗ trợ toàn workbook bằng `--all-sheets`;
  exporter không bảo toàn formatting, chart, formula hay macro của workbook nguồn.
- CSV chunk mode stream từng phần qua cả API và CLI. Duplicate chỉ được đối chiếu trong
  từng chunk; dùng full mode cho duplicate xuyên chunk, `keep=last`/`most_complete` hoặc
  group imputation phụ thuộc dữ liệu ở chunk khác.
- Mode `capture` chạy một pre-pass bằng `csv` chuẩn để bắt cả dòng thừa/thiếu field và
  ghi số dòng/record. Đổi lại, mode này chỉ nhận dialect CSV chuẩn cùng một tập option
  giới hạn và cần dung lượng đĩa tạm xấp xỉ file đã lọc; dialect tùy chỉnh phải dùng
  `error` rồi chuẩn hóa nguồn trước.
- Strict config hiện kiểm tra key cấp cao; không phải JSON Schema hoàn chỉnh cho mọi key
  lồng nhau.
- Regex của người dùng chạy bằng Python `re`; heuristic/giới hạn độ dài không chứng minh
  mọi pattern đều an toàn. Chỉ dùng config đã review và pattern ngắn, anchored.
- `--output-root` và secure mode chặn traversal/symlink ra ngoài thư mục cho phép, nhưng
  đây không phải OS sandbox và không loại bỏ hoàn toàn symlink race trong môi trường
  nhiều tenant; vẫn cần quyền thư mục và sandbox ở tầng hệ điều hành.
- Resource limit giảm rủi ro DoS nhưng không phải quota cứng về CPU/RAM của OS.

Xem [configuration.md](configuration.md), [security.md](security.md) và
[threat-model.md](threat-model.md) trước khi tích hợp vào quy trình nhạy cảm.
