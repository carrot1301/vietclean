# Threat model

## Phạm vi và tài sản cần bảo vệ

Mô hình này áp dụng cho VietClean `0.1.x` chạy như CLI hoặc thư viện trên máy người dùng.
Tài sản chính là input/output nghiệp vụ, PII, credential database, tính toàn vẹn file
nguồn, tính đúng của số tiền/ngày và máy chạy framework.

Các trust boundary:

```text
file/config không tin cậy ──> process VietClean ──> output/report/rejects
                                  │
                                  └──> database do người dùng chỉ định

package index/GitHub ──> dependency + wheel ──> môi trường runtime
```

Giả định người chạy có quyền hợp lệ với input/output. VietClean không bảo vệ trước admin
máy, malware đã chạy cùng user, database account quá quyền hoặc thư mục đã bị attacker
kiểm soát hoàn toàn. Remote database URI là hành động có chủ đích và không thuộc chế độ
offline cục bộ.

## Tác nhân và mục tiêu

- Người gửi CSV/XLSX muốn thực thi công thức, làm cạn RAM/CPU hoặc che giấu dòng lỗi.
- Người cung cấp config muốn gây DoS hoặc thay đổi/xóa dữ liệu ngoài dự kiến.
- Attacker cùng máy muốn đổi output qua symlink/race hoặc đọc file tạm.
- Kẻ tấn công supply chain muốn chèn mã vào dependency/action/wheel.
- Sai sót vận hành: overwrite nhầm, log URI, bật sample hoặc upload rejects.

## Ma trận rủi ro và kiểm soát

| Mối đe dọa | Kiểm soát hiện có | Rủi ro còn lại / trách nhiệm người dùng |
|---|---|---|
| CSV độc hại, field count sai | Bad-line mặc định capture ở CLI; pre-pass `csv` bắt dòng thừa/thiếu field và ghi vị trí; giới hạn file/row/column/cell/memory/rejects | Capture chỉ hỗ trợ dialect/option chuẩn, tạo file tạm và rejects chứa raw PII; parser vẫn dùng CPU trước một số kiểm tra |
| Formula injection CSV/XLSX | Detect + `sanitize` mặc định, audit count; số âm hợp lệ được phân biệt | `report_only`/`allow` là opt-in nguy hiểm; tool downstream có thể gỡ prefix |
| XLSX giả/ZIP bomb | Mở như ZIP, giới hạn entry, dung lượng bung nén và ratio; fail-safe | Heuristic không thay antivirus/quota OS; workbook phức tạp vẫn có thể tốn CPU/RAM |
| Macro-enabled workbook | `.xlsm` từ chối mặc định; allow chỉ đọc; không chạy/bảo toàn macro | Không tuyên bố sanitize mọi embedded object/external link |
| Path traversal/output overwrite | Output trùng input bị từ chối; overwrite opt-in; local write dùng temp + replace; CLI `--output-root` + secure mode chặn thoát root/symlink/reparse point | Ứng dụng multi-tenant vẫn cần quyền thư mục/OS sandbox để giảm TOCTOU race |
| SQL injection/arbitrary SQL | Chỉ một `SELECT`/`WITH`; cấm comment/keyword ghi; SQLite `mode=ro` + `query_only`; table SQLite được quote; API hỗ trợ params | Validator không phải SQL parser; SQLAlchemy account phải read-only; backend/driver có semantics riêng |
| Credential leakage | CLI/log formatter redact URI, credential, token và PII; audit không lưu URI đầy đủ | Command line có thể lộ qua history/process; exception từ Python API/driver cần được caller xử lý |
| PII trong report/log | Inspection/audit/quality aggregate mặc định; PII classifier/mask helper | `--samples` và rejects chứa raw value; tên cột/hash vẫn có thể nhạy cảm |
| Malicious config | TOML/JSON bằng parser chuẩn; không `eval`/`exec`/plugin import; allowlist nhiều option | Strict mới kiểm tra key cấp cao; regex và mapping lớn có thể tốn tài nguyên |
| Regex DoS | Pattern lỗi bị từ chối; implementation có thể đặt heuristic/giới hạn pattern | Python `re` không có timeout tuyệt đối; chỉ dùng config được review, pattern ngắn/anchored |
| File quá lớn / DoS | `ResourceLimits`, preflight + frame checks, CSV chunk mode ở API/CLI, timeout/cancellation checkpoint | Limit không phải quota OS cứng và một số parser phải làm việc trước post-load check |
| Unsafe deserialization/code execution | Không pickle/YAML/object deserialization, không shell command, không config-as-code | Lỗ hổng dependency parser vẫn có thể tồn tại |
| Temporary-file exposure | `mkstemp` cùng thư mục, cleanup khi exception, atomic replace | Không mã hóa; hard kill có thể để file; quyền thư mục quyết định khả năng đọc |
| Dependency compromise | Dependency tối thiểu; Dependabot, dependency review, CodeQL; action pin full SHA; release tạo hashed platform lock/checksum/SPDX SBOM | Scanner không chứng minh an toàn; cần review update và giữ artifact release |
| Untrusted plugin execution | Không có plugin system động | Code do người dùng tự import nằm ngoài trust boundary |
| Network exfiltration | Core không HTTP/telemetry/download; test runtime không network | URI database từ xa chủ động tạo network; dependency install/CI có network |

## Abuse case quan trọng

### CSV formula + PII

Attacker đặt `=HYPERLINK(...)` trong tên khách hàng. Cleaning text không được phép coi đó
là lỗi encoding. Exporter phải sanitize và chỉ audit count. Nếu bật `allow`, người vận
hành chịu rủi ro khi mở spreadsheet.

### Query read-looking nhưng có side effect

Một backend có function side effect trong `SELECT`. Keyword allowlist không phát hiện
được mọi semantics. Do đó account input phải chỉ có quyền đọc và database phải enforce
transaction/statement timeout; validator là lớp bổ sung, không phải boundary duy nhất.

### Output path từ web form

Nếu một ứng dụng khác chuyển nguyên path do người dùng nhập vào VietClean, dùng
`--output-root` và giữ secure mode mặc định để canonicalize, allowlist root và chặn
symlink/reparse point. Với dịch vụ multi-tenant, vẫn chạy bằng account riêng và giới hạn
quyền thư mục vì preflight trong process không thay OS sandbox.

### ReDoS qua config

Regex hợp lệ cú pháp vẫn có thể backtracking mạnh. Config không phải code nhưng vẫn là
input tính toán. Chỉ nhận config từ nguồn tin cậy, giới hạn kích thước file/config ở lớp
tích hợp và tránh nested quantifier/backreference trên text dài.

## Release gate bảo mật

Trước mỗi release:

1. chạy unit/integration/security tests và network-isolation test;
2. chạy Ruff, mypy, Bandit, CodeQL và `pip-audit`; triage finding thay vì bỏ qua;
3. kiểm tra mọi `uses:` trong workflow được pin full SHA và review thay đổi Dependabot;
4. build wheel từ commit/tag sạch, tạo checksum/lock và lưu provenance phù hợp;
5. kiểm tra artifact/source distribution không chứa `.env`, DB, Excel thật hoặc temp;
6. tạo SBOM SPDX/CycloneDX nếu pipeline release hỗ trợ và xem license dependency;
7. cập nhật [../SECURITY.md](../SECURITY.md) và supported versions.

## Rủi ro được chấp nhận ở MVP

VietClean không sandbox parser bằng process riêng, không antivirus, không mã hóa file,
không quota CPU của OS và không cung cấp SQL parser đầy đủ. Chunk mode CSV là opt-in và
không làm mọi transformation trở thành thuật toán global-streaming.
Các giới hạn này phải được xem xét lại trước khi dùng như dịch vụ multi-tenant hoặc xử lý
input Internet tự động.
