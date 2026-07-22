# Vận hành VietClean an toàn

Tài liệu này dành cho người chạy framework. Quy trình báo lỗ hổng nằm ở
[../SECURITY.md](../SECURITY.md); phân tích rủi ro kỹ thuật nằm ở
[threat-model.md](threat-model.md).

## Checklist trước khi xử lý dữ liệu thật

1. Làm việc trên bản sao input và thư mục output chỉ người cần thiết được truy cập.
2. Chạy `vietclean inspect` rồi `vietclean clean --dry-run`; không bật `--samples` với
   dữ liệu có PII.
3. Đặt giới hạn `--max-file-size-mb`, `--max-rows`, `--max-columns`,
   `--max-cell-length`, `--max-memory-mb`, `--max-zip-ratio` phù hợp máy.
4. Giữ `--formula-mode sanitize`, `--bad-lines capture` và không dùng `--overwrite` ở
   lần chạy đầu.
5. Kiểm tra audit, quality report và rejected rows trước khi đưa output vào Excel/ERP.
6. Xác minh row count, tổng tiền và các control total độc lập cho dữ liệu tài chính.
7. Xóa artifact tạm/rejects theo retention policy của tổ chức.

## Mức nhạy cảm của artifact

| Artifact | Nội dung mặc định | Cách bảo vệ |
|---|---|---|
| Cleaned CSV/XLSX/DB | Dữ liệu nghiệp vụ đầy đủ | Nhạy cảm ngang input |
| Rejected rows | Raw field của dòng parser từ chối | Nhạy cảm ngang input; không gửi vào issue |
| Inspection với `--samples` | Tối đa vài raw value/cột | Chỉ bật trên dữ liệu synthetic/redacted |
| Audit JSON | Count, hash, tên cột, warning tổng hợp | Không thiết kế để chứa raw PII, vẫn hạn chế chia sẻ |
| Quality JSON/HTML | Metric tổng hợp | Kiểm tra tên cột có thể tự nó nhạy cảm |
| Text/JSON log | Event, count, level, run ID đã redact | Không log raw row/cell dù có redaction |

Hash SHA-256 chứng minh hai file giống nhau, không mã hóa nội dung và không ẩn được tên
file. VietClean không tự mã hóa output; dùng BitLocker/FileVault/LUKS hoặc cơ chế của tổ
chức khi cần.

## Log và correlation ID

`vietclean.logging_utils` dùng level `INFO` mặc định, text hoặc JSON Lines và run ID không
định danh. URI credential/query, secret assignment, email, phone/account và exception text
được redact ở cả DEBUG. Đây là lớp phòng vệ cuối; code vẫn chỉ được log count/rule/status,
không log raw cell. Hướng dẫn và API nằm tại [logging.md](logging.md).

## Spreadsheet và formula injection

Chuỗi bắt đầu bằng `=`, `+`, `@`, tab, carriage return và một số chuỗi `-` có thể được
Excel/LibreOffice diễn giải. Mode mặc định `sanitize` prefix dấu nháy đơn cho cell có rủi
ro, không sửa numeric cell hợp lệ. Audit ghi count, không ghi payload.

- `report_only`: chỉ dùng khi bước sau có sanitizer tương đương và bạn review report.
- `allow`: coi output là dữ liệu không tin cậy; không mở bằng spreadsheet và không gửi
  cho người khác nếu chưa lọc.

Bảo vệ này giảm rủi ro ở exporter của VietClean, không bảo vệ file nếu một công cụ khác
gỡ prefix hoặc tái tạo CSV từ dữ liệu chưa sanitize.

## Excel và macro

`.xlsm` bị từ chối mặc định. `--allow-macros` chỉ cho đọc dữ liệu; VietClean không chạy
VBA và không bảo toàn macro trong output. Không dùng VietClean để "làm sạch an toàn" một
workbook rồi giả định mọi embedded object, external link hoặc nội dung khác đã được gỡ.
Output mới chỉ chứa bảng do pandas/OpenPyXL ghi.

XLSX được kiểm tra số entry, kích thước bung nén và tỷ lệ nén trước khi đọc. Đây là
heuristic, không phải antivirus; mở file không tin cậy trong môi trường giới hạn quyền.

## SQL và credential

SQLite input path được mở read-only. Query import chỉ nhận một `SELECT`/`WITH`, từ chối
comment, dấu `;` nhúng và keyword ghi phổ biến. Giá trị động trong Python API phải truyền
qua `params`, không nối chuỗi.

Với URI SQLAlchemy:

- kết nối bị từ chối mặc định; CLI cần `--allow-remote-database`, và query tùy chỉnh cần
  thêm `--allow-remote-query` sau khi review;
- tạo account riêng chỉ có quyền `SELECT` cho input;
- dùng account/table riêng cho output, và chỉ bật ghi khi đã review;
- tránh đặt password trực tiếp trong command line vì có thể lộ qua shell history/process
  list; dùng cơ chế credential của driver hoặc wrapper nội bộ đã được kiểm soát;
- không đưa URI vào config, report, screenshot hoặc issue;
- đặt timeout/TLS ở driver/database vì VietClean không cấu hình thay mọi backend.

Validator chuỗi không thay thế database authorization hoặc SQL parser đầy đủ.

## Filesystem và overwrite

VietClean từ chối output trùng input và không overwrite file/report mặc định. Local CSV,
XLSX/Parquet dùng file tạm cùng thư mục rồi replace. `--overwrite` chỉ dùng khi đã sao lưu
và xác minh đúng đích.

Dùng `--output-root <thu-muc>` và giữ secure mode mặc định để mọi data/report nằm trong
root đã resolve, đồng thời từ chối symlink/reparse point. Với dịch vụ nhận path từ người
dùng khác, vẫn chạy bằng account ít quyền hoặc OS sandbox để giảm symlink race. File tạm
không được mã hóa; một process bị kill cứng có thể để lại file ẩn cần dọn theo quy trình.

## Chạy offline và supply chain

Core không cần Internet sau khi đã cài wheel. Ngoại lệ là URI database từ xa do người
dùng chủ động bật. Cài trên máy air-gapped theo [offline-installation.md](offline-installation.md)
và xác minh checksum trên máy staging tin cậy.

CodeQL, dependency review, Dependabot và `pip-audit` là kiểm soát repository/CI, không
chạy với dữ liệu người dùng. Trước khi public repository, chủ dự án cần bật branch
protection, private vulnerability reporting, secret scanning và dependency graph trong
GitHub Settings; chỉ có file workflow không tự bật mọi tính năng đó.
