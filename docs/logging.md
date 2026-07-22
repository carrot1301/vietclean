# Logging an toàn

`vietclean.logging_utils` dùng Python `logging`, mặc định `INFO`, không đổi root logger và
không cần dependency. Formatter text và JSON Lines chỉ phát hành timestamp UTC, level,
logger, run ID, message đã redact và exception đã redact.

```python
from vietclean.logging_utils import configure_logging, log_event

context = configure_logging(
    level="INFO",
    log_file="output/run.log",
    log_format="json",
)
log_event(context.logger, "INFO", "clean_complete", rows=125390, rejected=30)
```

Run ID ngẫu nhiên không chứa thông tin máy/người dùng; caller có thể truyền ID gồm chữ,
số, `.`, `_`, `-` để liên kết audit nội bộ. File log dùng UTF-8 và append, không âm thầm
xóa run cũ.

Lớp redaction cuối cùng che:

- username/password, query và fragment trong URI;
- assignment như `password=`, `api_key=`, `token=` và connection string;
- email;
- chuỗi phone/account 9–19 chữ số;
- newline/tab có thể giả mạo log entry;
- cùng nội dung trong traceback ở DEBUG.

Redaction không thể biến việc log raw row/cell thành an toàn. Chỉ gọi `log_event()` với
count, rule ID, tên cột đã review và trạng thái tổng hợp. Rejects chứa raw field phải được
bảo vệ như input và không được copy vào log.

Các lệnh `clean`, `inspect`, `validate` và `explain` expose `--log-file`, `--log-format`,
`--log-level` và `--run-id` bằng utility này. Ví dụ:

```bash
dataclean clean input.xlsx --log-file output/run.jsonl --log-format json --run-id daily-01
```

Mọi handler khác do ứng dụng tích hợp thêm phải áp formatter/redaction tương đương.
