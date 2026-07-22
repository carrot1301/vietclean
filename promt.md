# PROMPT: Xây dựng framework làm sạch và chuẩn hóa dữ liệu offline bằng Python

## 1. Vai trò của bạn

Bạn là một **Principal Python Engineer, Data Engineer và Application Security Engineer**.

Nhiệm vụ của bạn là thiết kế và triển khai hoàn chỉnh một repository GitHub mã nguồn mở dùng để:

* Làm sạch dữ liệu.
* Chuẩn hóa dữ liệu.
* Phát hiện và xử lý dữ liệu thiếu.
* Sửa lỗi encoding và lỗi font tiếng Việt.
* Xử lý lỗi xuống dòng, cách dòng, khoảng trắng và ký tự ẩn.
* Chuẩn hóa kiểu dữ liệu.
* Kiểm tra chất lượng dữ liệu.
* Xuất báo cáo thay đổi và báo cáo chất lượng.
* Giảm nhu cầu viết công thức Excel thủ công trong công việc hằng ngày.

Framework phải hướng tới các nhóm người dùng:

* Data Analyst.
* Business Analyst.
* Marketing Analyst.
* Finance Analyst.
* Operations Analyst.
* Nhân viên F&B.
* Nhân viên bán hàng và thương mại điện tử.
* Người dùng thường xuyên xử lý Excel nhưng không muốn viết nhiều code.

Tên làm việc tạm thời của dự án:

```text
dataclean-offline
```

Có thể đề xuất tên tốt hơn, nhưng tên package Python phải:

* Ngắn.
* Dễ nhớ.
* Không gây nhầm lẫn với package phổ biến.
* Không chứa dấu tiếng Việt.
* Phù hợp để phát hành lên PyPI trong tương lai.

---

## 2. Mục tiêu sản phẩm

Xây dựng một framework Python nhẹ, an toàn và chạy hoàn toàn offline, cho phép người dùng clone repository về và thực hiện các tác vụ như:

```bash
git clone <repository-url>
cd dataclean-offline
python -m venv .venv
pip install -e .
dataclean profile input.xlsx
dataclean clean input.xlsx --config configs/fnb.toml
```

Framework phải giúp người dùng chuyển từ quy trình:

```text
Mở Excel
→ viết nhiều hàm TRIM, CLEAN, SUBSTITUTE, IFERROR, VLOOKUP
→ copy/paste value
→ sửa font thủ công
→ xóa dòng trống
→ tìm dữ liệu trùng
→ định dạng ngày tháng
→ lưu nhiều phiên bản file
```

sang quy trình:

```text
Chọn file
→ chọn preset hoặc config
→ chạy một câu lệnh
→ nhận file sạch + báo cáo thay đổi + báo cáo chất lượng
```

---

## 3. Nguyên tắc bắt buộc

### 3.1. Offline-first

Framework phải hoạt động hoàn toàn offline khi chạy.

Không được:

* Gửi dữ liệu ra Internet.
* Gọi API bên ngoài.
* Thu thập telemetry.
* Thu thập analytics.
* Gửi crash report.
* Tự động upload file.
* Tải model hoặc rule từ Internet khi runtime.
* Yêu cầu tài khoản cloud.
* Yêu cầu API key.
* Phụ thuộc vào dịch vụ SaaS.

CI/CD của repository có thể sử dụng Internet để cài dependency và chạy kiểm tra, nhưng package sau khi được cài đặt phải chạy offline.

Thêm test tự động để xác nhận core runtime không thực hiện network request.

### 3.2. Lightweight

Ưu tiên Python standard library và số lượng dependency tối thiểu.

Core dependency đề xuất:

```text
pandas
openpyxl
```

Sử dụng standard library cho các chức năng có thể:

```text
argparse
csv
sqlite3
json
tomllib
pathlib
logging
hashlib
re
unicodedata
decimal
datetime
tempfile
shutil
```

Không thêm dependency chỉ để xử lý một tác vụ đơn giản có thể triển khai an toàn trong ít code.

Các chức năng nặng phải được đưa vào optional extras:

```toml
[project.optional-dependencies]
encoding = ["charset-normalizer"]
fuzzy = ["rapidfuzz"]
sql = ["sqlalchemy"]
xls = ["xlrd"]
xlsb = ["pyxlsb"]
dev = [
    "pytest",
    "pytest-cov",
    "ruff",
    "mypy",
    "bandit",
    "pip-audit"
]
```

Không sử dụng trong core:

* Spark.
* Dask.
* Airflow.
* Great Expectations.
* Streamlit.
* Django.
* FastAPI.
* Machine learning model.
* LLM.
* Cloud SDK.
* Database server bắt buộc.
* Docker bắt buộc.

Có thể cung cấp integration tùy chọn trong tương lai nhưng không được làm nặng core package.

### 3.3. Secure by default

Mọi tính năng phải hoạt động theo nguyên tắc:

```text
deny by default
least privilege
explicit configuration
safe failure
no silent destructive action
```

Không được tuyên bố repository đạt ISO 27001, SOC 2, PCI DSS hoặc một chứng nhận khác nếu chưa được đánh giá chính thức.

Chỉ được mô tả repository là:

```text
Designed following secure software development practices.
```

---

## 4. Phạm vi file đầu vào

### 4.1. CSV

Hỗ trợ:

* `.csv`
* `.tsv`
* File phân cách bằng dấu phẩy.
* File phân cách bằng dấu chấm phẩy.
* File phân cách bằng tab.
* Delimiter tùy chỉnh.
* UTF-8.
* UTF-8 BOM.
* UTF-16.
* Các encoding phổ biến trong file tiếng Việt.
* Chunk processing cho file lớn.

Tự động phát hiện hoặc cho phép cấu hình:

* Encoding.
* Delimiter.
* Quote character.
* Header row.
* Decimal separator.
* Thousands separator.
* Dòng lỗi.
* Dòng rỗng.
* Số cột không đồng nhất.

Không được âm thầm bỏ dòng lỗi.

Mọi dòng bị bỏ qua hoặc không parse được phải được ghi vào:

```text
rejects.csv
```

và báo cáo rõ lý do.

### 4.2. Excel

Core hỗ trợ tốt:

* `.xlsx`

Optional support:

* `.xls`
* `.xlsb`
* `.xlsm`

Hỗ trợ:

* Một sheet.
* Nhiều sheet.
* Chọn sheet theo tên.
* Chọn sheet theo index.
* Header không nằm ở dòng đầu.
* Dòng ghi chú trước bảng.
* Merge cell.
* Cột unnamed.
* Dòng và cột hoàn toàn rỗng.
* Công thức Excel.
* Giá trị ngày dạng Excel serial.
* File có nhiều bảng dữ liệu.

Các file macro-enabled như `.xlsm` phải:

* Bị từ chối mặc định trong secure mode; hoặc
* Chỉ được đọc khi người dùng bật tùy chọn rõ ràng.
* Không chạy macro.
* Không thực thi VBA.
* Không tự động bảo toàn macro trong file output.
* Hiển thị cảnh báo rõ ràng.

Không được tự động đánh giá hoặc thực thi công thức Excel.

### 4.3. SQL và database

Core hỗ trợ:

* SQLite `.db`.
* SQLite `.sqlite`.
* Kết nối SQLite read-only.
* Đọc kết quả của câu lệnh `SELECT`.
* Xuất DataFrame vào bảng SQLite mới khi người dùng cho phép.

Optional extra hỗ trợ:

* PostgreSQL.
* MySQL.
* SQL Server.
* Các database được SQLAlchemy hỗ trợ.

Yêu cầu bảo mật:

* Chế độ mặc định là read-only.
* Chỉ cho phép `SELECT` trong lệnh import.
* Không nối chuỗi dữ liệu người dùng vào SQL.
* Luôn dùng parameterized query.
* Không lưu username, password hoặc connection string trong source code.
* Không ghi credential vào log.
* Không cho phép nhiều statement trong một query.
* Từ chối các câu lệnh nguy hiểm như `DROP`, `DELETE`, `TRUNCATE`, `ALTER`, `ATTACH`, `PRAGMA writable_schema` trong read-only mode.
* Không hỗ trợ thực thi SQL tùy ý từ file config.
* Không sử dụng `eval`, `exec` hoặc dynamic code generation.

---

## 5. Kiến trúc mong muốn

Thiết kế framework theo pipeline:

```text
Source
  ↓
Safe loader
  ↓
Profiler
  ↓
Schema inference
  ↓
Cleaning plan
  ↓
Transformations
  ↓
Validation
  ↓
Quality report
  ↓
Safe exporter
```

Các thành phần phải độc lập, dễ test và có type hint.

Giao diện lõi đề xuất:

```python
result = (
    DataCleaner(config)
    .load("input.xlsx")
    .profile()
    .clean()
    .validate()
    .export("output/cleaned.xlsx")
)
```

Hoặc functional API:

```python
from dataclean import clean_file

result = clean_file(
    input_path="input.xlsx",
    output_dir="output",
    config_path="configs/fnb.toml",
)
```

CLI:

```bash
dataclean profile data.xlsx
dataclean clean data.xlsx
dataclean clean data.xlsx --preset fnb
dataclean clean data.csv --config cleaning.toml
dataclean validate cleaned.xlsx --schema schema.json
dataclean explain report.json
```

Các câu lệnh CLI phải có:

```bash
dataclean --help
dataclean clean --help
```

Không yêu cầu người dùng viết Python cho các tác vụ phổ biến.

---

## 6. Cấu trúc repository

Sử dụng `src layout`.

```text
dataclean-offline/
├── .github/
│   ├── workflows/
│   │   ├── ci.yml
│   │   ├── codeql.yml
│   │   ├── dependency-review.yml
│   │   └── release.yml
│   ├── CODEOWNERS
│   ├── dependabot.yml
│   ├── ISSUE_TEMPLATE/
│   └── pull_request_template.md
├── configs/
│   ├── basic.toml
│   ├── fnb.toml
│   ├── finance.toml
│   ├── ecommerce.toml
│   └── marketing.toml
├── docs/
│   ├── architecture.md
│   ├── configuration.md
│   ├── security.md
│   ├── threat-model.md
│   ├── vietnamese-text.md
│   ├── examples.md
│   └── offline-installation.md
├── examples/
│   ├── fnb/
│   ├── finance/
│   ├── ecommerce/
│   └── marketing/
├── src/
│   └── dataclean/
│       ├── __init__.py
│       ├── __main__.py
│       ├── cli.py
│       ├── api.py
│       ├── config.py
│       ├── exceptions.py
│       ├── models.py
│       ├── pipeline.py
│       ├── profiling/
│       │   ├── profiler.py
│       │   ├── inference.py
│       │   └── metrics.py
│       ├── loaders/
│       │   ├── base.py
│       │   ├── csv_loader.py
│       │   ├── excel_loader.py
│       │   └── sqlite_loader.py
│       ├── cleaners/
│       │   ├── missing.py
│       │   ├── text.py
│       │   ├── vietnamese.py
│       │   ├── whitespace.py
│       │   ├── numbers.py
│       │   ├── dates.py
│       │   ├── columns.py
│       │   ├── duplicates.py
│       │   └── outliers.py
│       ├── validation/
│       │   ├── rules.py
│       │   ├── schema.py
│       │   └── validator.py
│       ├── exporters/
│       │   ├── csv_exporter.py
│       │   ├── excel_exporter.py
│       │   └── sqlite_exporter.py
│       ├── reporting/
│       │   ├── audit.py
│       │   ├── quality.py
│       │   └── html_report.py
│       ├── presets/
│       │   ├── fnb.py
│       │   ├── finance.py
│       │   ├── ecommerce.py
│       │   └── marketing.py
│       └── security/
│           ├── file_checks.py
│           ├── formula_injection.py
│           ├── pii.py
│           └── resource_limits.py
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── security/
│   ├── fixtures/
│   └── conftest.py
├── CHANGELOG.md
├── CODE_OF_CONDUCT.md
├── CONTRIBUTING.md
├── LICENSE
├── README.md
├── SECURITY.md
├── pyproject.toml
└── requirements-lock.txt
```

Có thể đơn giản hóa cấu trúc nếu một module quá nhỏ, nhưng không được gom toàn bộ logic vào một file lớn.

---

## 7. Chức năng profiling

Trước khi thay đổi dữ liệu, framework phải tạo hồ sơ dữ liệu gồm:

* Tên file.
* Hash SHA-256 của file.
* Kích thước file.
* Số sheet hoặc bảng.
* Số dòng.
* Số cột.
* Tên cột.
* Kiểu dữ liệu hiện tại.
* Kiểu dữ liệu được đề xuất.
* Số lượng missing.
* Tỷ lệ missing.
* Số giá trị duy nhất.
* Số bản ghi trùng.
* Min, max, median cho số.
* Min, max cho ngày.
* Độ dài nhỏ nhất và lớn nhất của text.
* Encoding được phát hiện.
* Delimiter được phát hiện.
* Ký tự Unicode bất thường.
* Số ô có xuống dòng.
* Số ô có khoảng trắng đầu hoặc cuối.
* Số ô có khoảng trắng lặp.
* Số ô nghi ngờ lỗi font tiếng Việt.
* Số ô bắt đầu bằng ký tự có nguy cơ formula injection.
* Số dòng parse lỗi.
* Các cột có cardinality cao.
* Các cột có khả năng chứa PII.

Không đưa raw PII vào báo cáo mặc định.

Ví dụ không được log:

```text
nguyenvana@gmail.com
0901234567
012345678901
```

Thay vào đó:

```text
email_column: 1,240 non-null values
phone_column: 985 values matching phone pattern
```

---

## 8. Xử lý dữ liệu missing

Framework phải nhận diện các dạng missing phổ biến:

```text
""
" "
null
NULL
None
none
NaN
N/A
NA
n/a
#N/A
-
--
---
?
unknown
Unknown
UNKNOWN
not available
không có
khong co
chưa có
chua co
không xác định
```

Không được mặc định coi `"0"`, `0`, `"False"` hoặc `False` là missing.

Mỗi cột có thể cấu hình danh sách missing token riêng.

Các chiến lược:

```text
keep
drop_row
drop_column
fill_constant
fill_zero
fill_mean
fill_median
fill_mode
forward_fill
backward_fill
group_median
group_mode
flag_only
```

Nguyên tắc:

* Không tự động impute dữ liệu tài chính quan trọng nếu chưa được cấu hình.
* Không dùng mean cho mã định danh.
* Không forward-fill giao dịch tài chính mặc định.
* Mọi giá trị được điền phải có thống kê trong audit report.
* Cho phép tạo cột cờ như `amount_was_missing`.
* Mặc định ưu tiên `flag_only` hoặc `keep` khi không chắc chắn.
* Không âm thầm xóa dòng.

---

## 9. Chuẩn hóa văn bản và tiếng Việt

### 9.1. Unicode

Hỗ trợ:

* Chuẩn hóa Unicode NFC.
* Tùy chọn NFKC cho dữ liệu mã hoặc tìm kiếm.
* Loại BOM trong nội dung.
* Loại zero-width space.
* Loại zero-width non-joiner khi được cấu hình.
* Loại non-breaking space hoặc đổi thành space.
* Phát hiện replacement character `�`.
* Phát hiện ký tự điều khiển không mong muốn.
* Giữ nguyên emoji theo mặc định.
* Không loại dấu tiếng Việt mặc định.

Không được sử dụng NFKD rồi xóa combining mark trong chế độ mặc định vì có thể làm mất dấu tiếng Việt.

### 9.2. Lỗi encoding và mojibake tiếng Việt

Phát hiện các chuỗi nghi ngờ như:

```text
Ã
Â
Æ
áº
á»
Ä
�
```

Triển khai chiến lược sửa có kiểm soát:

1. Giữ nguyên giá trị ban đầu.
2. Tạo các candidate decoding hợp lý.
3. Chỉ áp dụng phép sửa có khả năng đảo ngược.
4. Chấm điểm candidate dựa trên:

   * Số ký tự mojibake giảm.
   * Số replacement character giảm.
   * Tỷ lệ ký tự tiếng Việt hợp lệ tăng.
   * Không làm mất dữ liệu.
5. Chỉ tự động sửa khi confidence vượt ngưỡng cấu hình.
6. Nếu không đủ confidence:

   * Giữ nguyên.
   * Gắn cờ review.
   * Ghi candidate vào báo cáo mà không đưa raw PII vào log.
7. Không thử hàng chục encoding một cách không giới hạn.
8. Không double-decode dữ liệu đã đúng.
9. Hàm phải idempotent: chạy hai lần không tiếp tục thay đổi text.

Ví dụ test bắt buộc:

```text
"Nguyá»…n VÄƒn A" → "Nguyễn Văn A"
"ThÃ nh phá»‘ Há»“ ChÃ­ Minh" → chuỗi tiếng Việt đúng
"Cà phê sữa đá" → giữ nguyên
"SKU-ÁO-001" → không làm hỏng mã
```

Các ví dụ cụ thể phải được xác minh bằng test; không hard-code chỉ để vượt test.

### 9.3. Khoảng trắng và xuống dòng

Hỗ trợ các mode:

```text
preserve
trim
normalize_spaces
single_line
canonical_multiline
```

Quy tắc:

* Xóa khoảng trắng đầu và cuối.
* Thay tab bằng space khi được cấu hình.
* Gộp nhiều space thành một.
* Chuẩn hóa `\r\n`, `\r`, `\n`.
* Xóa dòng trống lặp.
* Không gộp paragraph khi mode là `canonical_multiline`.
* Với địa chỉ và mô tả sản phẩm, không tự động xóa toàn bộ dấu xuống dòng nếu chưa cấu hình.
* Với cột mã, tên, email, phone có thể dùng `single_line`.

Ví dụ:

```text
"  Cà   phê\r\nsữa  " → tùy mode:
trim: "Cà   phê\r\nsữa"
normalize_spaces: "Cà phê\nsữa"
single_line: "Cà phê sữa"
```

---

## 10. Chuẩn hóa tên cột

Cung cấp các kiểu:

```text
snake_case
lower_snake_case
upper_snake_case
preserve
```

Xử lý:

* Khoảng trắng.
* Dấu chấm.
* Dấu gạch ngang.
* Dấu `/`.
* Ký tự xuống dòng.
* Cột unnamed.
* Tên cột trùng.
* Tên cột tiếng Việt.

Tạo mapping trong audit:

```json
{
  "Doanh Thu ": "doanh_thu",
  "Ngày bán": "ngay_ban",
  "Tên SP": "ten_sp"
}
```

Không tự động xóa cột chỉ vì tên là `Unnamed: 0`; trước tiên phải kiểm tra liệu đó có phải index được xuất từ Excel hay không.

---

## 11. Chuẩn hóa kiểu dữ liệu

### 11.1. Số

Hỗ trợ:

```text
1,234.56
1.234,56
1 234,56
1.234
1,234
1.000.000
1,000,000
(1,250.00)
-1.250
₫1.200.000
1.200.000 VNĐ
$1,200.50
15%
15,5%
```

Phải có cấu hình locale rõ ràng:

```toml
locale = "vi_VN"
decimal_separator = ","
thousands_separator = "."
currency = "VND"
```

Không đoán sai khi chuỗi có thể mang nhiều nghĩa.

Với giá trị không chắc chắn:

* Giữ nguyên.
* Gắn cờ.
* Không ép kiểu im lặng.

Dữ liệu tiền tệ phải ưu tiên `Decimal` trong logic cần độ chính xác, không dùng float cho phép tính tài chính quan trọng.

### 11.2. Ngày tháng

Hỗ trợ:

```text
dd/mm/yyyy
dd-mm-yyyy
yyyy-mm-dd
yyyy/mm/dd
Excel serial date
ISO 8601
datetime có giờ
```

Yêu cầu:

* Có `day_first`.
* Có timezone policy.
* Không tự đoán ngày mơ hồ nếu cả ngày và tháng đều nhỏ hơn hoặc bằng 12.
* Ví dụ `03/04/2026` phải được gắn cờ nếu chưa có locale hoặc `day_first`.
* Không biến ngày không hợp lệ thành missing mà không báo cáo.
* Có min/max year hợp lý theo config.
* Hỗ trợ ngày tài chính và kỳ kế toán.

### 11.3. Boolean và category

Chuẩn hóa configurable:

```text
yes/no
y/n
true/false
1/0
có/không
co/khong
active/inactive
```

Không tự động chuyển mã `"0"` và `"1"` thành boolean nếu cột có khả năng là mã định danh.

---

## 12. Duplicate detection

Core hỗ trợ:

* Duplicate toàn bộ dòng.
* Duplicate theo primary key.
* Duplicate theo tổ hợp cột.
* Duplicate sau khi normalize.
* Giữ first.
* Giữ last.
* Giữ bản ghi đầy đủ hơn.
* Chỉ report, không xóa.

Mặc định:

```text
report_only
```

Optional fuzzy matching sử dụng `rapidfuzz`, không nằm trong core.

Fuzzy duplicate phải:

* Có threshold.
* Có blocking key.
* Có giới hạn số phép so sánh.
* Không so sánh Cartesian toàn bộ dataset lớn.
* Không tự động merge dữ liệu khi confidence thấp.
* Xuất danh sách candidate để review.

---

## 13. Outlier và anomaly

Core chỉ cần các phương pháp nhẹ:

* IQR.
* Z-score tùy chọn.
* Min/max business rule.
* Invalid negative value.
* Percentage ngoài khoảng.
* Date ngoài khoảng.
* Quantity không nguyên.
* Giá trị không thuộc allowed set.

Mặc định chỉ report outlier.

Không tự động:

* Xóa doanh thu lớn.
* Xóa đơn hàng giá trị cao.
* Winsorize dữ liệu tài chính.
* Thay đổi số tiền.
* Thay đổi số lượng.
* Chỉnh KPI.

Chỉ thay đổi khi config yêu cầu rõ ràng.

---

## 14. Preset theo ngành

Preset chỉ cung cấp rule mặc định có thể chỉnh sửa. Không hard-code theo một doanh nghiệp cụ thể.

### 14.1. F&B

Nhận diện các trường thường gặp:

```text
order_id
order_date
order_time
branch
store
table
item_name
category
sku
quantity
unit_price
discount
tax
total
payment_method
customer_name
customer_phone
staff
channel
```

Kiểm tra:

* Quantity không âm.
* Unit price không âm.
* Total hợp lý với quantity, price, discount và tax.
* Order ID không trống.
* Ngày bán hợp lệ.
* Tên món được chuẩn hóa khoảng trắng.
* Tên chi nhánh nhất quán.
* Payment method thuộc allowed values.
* Số điện thoại được chuẩn hóa nhưng không làm mất số 0 đầu.
* Tên món tiếng Việt không bị lỗi encoding.

### 14.2. Finance

Các trường:

```text
transaction_id
transaction_date
posting_date
account
account_code
debit
credit
amount
balance
currency
description
reference
counterparty
tax_code
cost_center
```

Kiểm tra:

* Transaction ID không trùng.
* Amount parse chính xác.
* Debit và credit theo rule cấu hình.
* Currency theo ISO code hoặc mapping nội bộ.
* Không tự động sửa số tiền không chắc chắn.
* Không log account number đầy đủ.
* Có thể mask số tài khoản.
* Ngày giao dịch không vượt phạm vi cấu hình.
* Reconciliation rule phải report sai lệch.
* Dùng Decimal cho tính toán kiểm tra.

### 14.3. Online shopping / E-commerce

Các trường:

```text
order_id
customer_id
product_id
sku
product_name
category
quantity
unit_price
discount
shipping_fee
order_total
order_status
payment_status
shipping_status
email
phone
province
district
address
channel
created_at
```

Kiểm tra:

* Order ID.
* SKU.
* Quantity.
* Price.
* Discount.
* Tổng đơn.
* Trạng thái đơn hàng.
* Email.
* Số điện thoại.
* Tỉnh/thành.
* Dữ liệu trùng.
* Text mô tả sản phẩm.
* CSV/Excel formula injection trong các trường do khách hàng nhập.

### 14.4. Marketing

Các trường:

```text
campaign
campaign_id
date
channel
source
medium
content
spend
impressions
reach
clicks
leads
conversions
revenue
ctr
cpc
cpm
cpl
cpa
roas
```

Kiểm tra:

* Spend không âm.
* Clicks không lớn hơn impressions trừ trường hợp được giải thích.
* CTR trong khoảng hợp lệ.
* Các KPI được tính lại và so sánh.
* Source/medium được normalize.
* Campaign name được trim.
* UTM có format thống nhất.
* Missing campaign ID được report.
* Không tự động thay đổi số liệu gốc khi KPI tính lại khác biệt.

---

## 15. Configuration

Sử dụng TOML làm định dạng config chính vì Python 3.11 có thể đọc bằng `tomllib`.

Không dùng YAML trong core nếu phải thêm dependency chỉ để parse config.

Ví dụ:

```toml
version = 1
preset = "fnb"
locale = "vi_VN"

[input]
sheet = "Orders"
header_row = 2
encoding = "auto"
delimiter = "auto"
max_file_size_mb = 500

[output]
format = "xlsx"
directory = "./output"
overwrite = false
sanitize_formulas = true
include_audit_report = true
include_quality_report = true

[text]
unicode_form = "NFC"
trim = true
normalize_spaces = true
line_break_mode = "single_line"
repair_vietnamese_mojibake = true
mojibake_confidence_threshold = 0.90

[missing]
default_strategy = "keep"
tokens = ["", "N/A", "NULL", "-", "không có"]

[duplicates]
mode = "report_only"
keys = ["order_id"]

[columns.order_date]
type = "date"
day_first = true
required = true

[columns.quantity]
type = "integer"
required = true
min = 1

[columns.unit_price]
type = "decimal"
required = true
min = 0

[columns.customer_phone]
type = "string"
trim = true
pii = true
mask_in_report = true
```

Config phải có:

* Version.
* Validation.
* Error message dễ hiểu.
* Không cho phép key không xác định trong strict mode.
* Không chứa Python expression.
* Không chứa lambda.
* Không được thực thi như code.
* Có JSON Schema hoặc schema Python tương đương.
* Có lệnh kiểm tra config:

```bash
dataclean config validate cleaning.toml
```

---

## 16. Auditability và reproducibility

Mọi lần chạy phải tạo:

```text
output/
├── cleaned.xlsx
├── quality_report.json
├── quality_report.html
├── audit_log.json
├── column_mapping.json
├── rejected_rows.csv
└── run_summary.txt
```

Audit report cần ghi:

* Phiên bản framework.
* Thời gian bắt đầu và kết thúc.
* Input file hash.
* Config file hash.
* Output file hash.
* Tên preset.
* Các bước đã chạy.
* Số ô thay đổi theo từng rule.
* Số dòng bị loại.
* Số dòng bị reject.
* Số duplicate được phát hiện.
* Số lỗi encoding được sửa.
* Số lỗi không sửa được.
* Số missing được điền.
* Số validation pass/fail.
* Cảnh báo.
* Error code.
* Python version.
* OS chung, không thu thập thông tin máy nhạy cảm.

Không đưa vào audit mặc định:

* Raw customer name.
* Email đầy đủ.
* Phone đầy đủ.
* Account number.
* Address đầy đủ.
* Nội dung giao dịch nhạy cảm.
* Password.
* Connection string.
* API key.
* Environment variable value.

Pipeline phải deterministic trong cùng input, config và package version.

Các transformation phù hợp phải idempotent.

---

## 17. Quality report

Tạo score từ 0 đến 100 nhưng phải minh bạch.

Ví dụ:

```text
Completeness: 30%
Validity: 25%
Uniqueness: 20%
Consistency: 15%
Integrity: 10%
```

Công thức phải:

* Được tài liệu hóa.
* Có thể cấu hình.
* Không dựa vào AI.
* Không dùng confidence mơ hồ.
* Có chi tiết để người dùng biết tại sao bị trừ điểm.

Kết quả CLI:

```text
Data Quality Score: 87/100

Rows read:               125,420
Rows written:            125,390
Rejected rows:                30
Missing cells:             2,481
Duplicate rows:               42
Encoding repairs:            315
Ambiguous text values:         18
Validation errors:             67
Security warnings:              3
```

CLI phải có exit code:

```text
0 = success
1 = validation threshold failed
2 = invalid configuration
3 = unsafe input
4 = unsupported format
5 = processing error
```

---

## 18. Export an toàn

### 18.1. Formula Injection

Khi xuất CSV hoặc Excel, phát hiện các chuỗi bắt đầu bằng:

```text
=
+
-
@
\t
\r
```

Không phải mọi dấu `-` đều nguy hiểm vì có thể là số âm. Cần phân biệt số hợp lệ và chuỗi có nguy cơ công thức.

Cung cấp mode:

```text
sanitize
report_only
allow
```

Mặc định:

```text
sanitize
```

Khi sanitize:

* Prefix bằng dấu nháy đơn hoặc chiến lược an toàn phù hợp.
* Ghi số ô đã xử lý.
* Không thay đổi numeric cell hợp lệ.
* Không âm thầm thay đổi mà không audit.

### 18.2. Ghi file

* Không overwrite mặc định.
* Sử dụng atomic write.
* Ghi ra file tạm rồi rename.
* Không để output hỏng nếu process thất bại.
* Kiểm tra output path.
* Chống path traversal.
* Không cho ghi ra ngoài output directory khi secure mode bật.
* Không theo symbolic link không an toàn.
* Giữ input nguyên vẹn.
* Không sửa trực tiếp file nguồn.

---

## 19. Resource protection

Framework phải chống file độc hại hoặc file quá lớn:

* Giới hạn kích thước file.
* Giới hạn số sheet.
* Giới hạn số dòng.
* Giới hạn số cột.
* Giới hạn độ dài một cell.
* Giới hạn số unique value dùng trong report.
* Giới hạn số candidate fuzzy match.
* Kiểm tra XLSX zip expansion ratio.
* Phát hiện archive nghi ngờ zip bomb.
* Không load toàn bộ CSV lớn nếu có thể xử lý chunk.
* Cho phép `--max-memory-mb` hoặc warning theo ước lượng.
* Có timeout hoặc cancellation point cho bước dài.
* Không regex có nguy cơ catastrophic backtracking.
* Test với input cực dài và Unicode bất thường.

Khi vượt giới hạn phải fail an toàn với thông báo rõ ràng.

---

## 20. Security requirements của repository

Tạo tối thiểu:

### `SECURITY.md`

Bao gồm:

* Supported versions.
* Cách báo cáo lỗ hổng riêng tư.
* Không yêu cầu người báo cáo đăng dữ liệu thật.
* Thời gian phản hồi mục tiêu.
* Quy trình disclosure.
* Phạm vi bảo mật.
* Hướng dẫn xóa dữ liệu nhạy cảm khỏi issue.

### Threat model

Phân tích:

* Malicious CSV.
* Formula injection.
* Malicious XLSX.
* Zip bomb.
* Macro-enabled workbook.
* Path traversal.
* Symlink attack.
* SQL injection.
* Arbitrary SQL execution.
* Credential leakage.
* PII leakage trong log.
* Dependency compromise.
* Malicious config.
* Denial of service qua file lớn.
* Regex denial of service.
* Unsafe deserialization.
* Temporary-file exposure.
* Output overwrite.
* Untrusted plugin execution.

### Secure coding

Cấm:

```python
eval(...)
exec(...)
pickle.load(untrusted_file)
yaml.load(...)
subprocess(..., shell=True)
os.system(...)
```

Không dùng pickle làm định dạng config hoặc cache đầu vào.

Nếu cần subprocess trong tooling, phải:

* Không dùng shell.
* Dùng argument list.
* Không nhận executable path tùy ý từ dữ liệu đầu vào.
* Có test bảo mật.

### SQL

* Parameterized queries.
* Read-only mặc định.
* Allowlist thao tác.
* Không đưa credential vào exception.
* Redact connection URL.
* Test SQL injection.

### Secrets

* `.env` nằm trong `.gitignore`.
* Có `.env.example` nhưng không có secret thật.
* Secret scanning.
* Pre-commit secret detection nếu phù hợp.
* Không commit sample data thật.
* Không commit database thật.
* Không commit file Excel chứa thông tin khách hàng.

### Dependency security

* Dependency tối thiểu.
* Pin version hoặc range có kiểm soát.
* Tạo lock file có hash cho release.
* Chạy `pip-audit`.
* Dependabot.
* Dependency review.
* SBOM dạng CycloneDX hoặc SPDX trong release.
* Kiểm tra license dependency.
* Không tự động merge dependency update quan trọng nếu chưa test.

### Static analysis

CI phải chạy:

```text
ruff
mypy
bandit
pip-audit
pytest
pytest-cov
CodeQL
```

GitHub Actions bên thứ ba phải được pin bằng full commit SHA, không chỉ dùng tag như `@v4`, nếu mục tiêu là hardened supply chain.

Workflow phải có permissions tối thiểu.

Ví dụ:

```yaml
permissions:
  contents: read
```

Chỉ tăng permission ở job thực sự cần.

Không chạy code từ pull request không tin cậy với secret của repository.

---

## 21. Testing

Mục tiêu coverage:

```text
Core modules: >= 90%
Toàn repository: >= 85%
```

Test gồm:

### Unit tests

* Missing values.
* Vietnamese Unicode.
* Mojibake.
* Whitespace.
* Line breaks.
* Number parsing.
* Decimal parsing.
* Date parsing.
* Column names.
* Duplicate.
* Formula injection.
* PII masking.
* Config parsing.

### Integration tests

* CSV → cleaned CSV.
* CSV → cleaned XLSX.
* XLSX nhiều sheet → output.
* SQLite → DataFrame → output.
* Pipeline với preset F&B.
* Pipeline với preset finance.
* Chunked CSV.
* Atomic write.
* Không overwrite.

### Security tests

* SQL injection payload.
* CSV formula payload.
* Path traversal.
* Symlink output.
* XLSX zip bomb simulation.
* Oversized cell.
* Oversized row.
* Malicious config.
* Embedded null byte.
* Invalid Unicode.
* Credential redaction.
* Network call detection.
* Macro-enabled input.
* Multiple SQL statements.
* Unsafe file extension.
* File giả mạo extension.

### Property-based thinking

Không bắt buộc thêm Hypothesis vào core. Có thể dùng trong dev dependency nếu thực sự hữu ích.

Các invariant cần test:

```text
normalize(normalize(x)) == normalize(x)
cleaning không thay đổi input object ngoài dự kiến
input file không bị sửa
row count thay đổi phải được audit
mọi rejected row phải truy vết được
output hash phải được ghi
```

Chỉ sử dụng synthetic test data.

Không đưa dữ liệu khách hàng hoặc dữ liệu sản xuất vào repository.

---

## 22. Documentation

README phải dành cho người dùng không chuyên Python.

README gồm:

1. Framework giải quyết vấn đề gì.
2. Đối tượng sử dụng.
3. Screenshot hoặc output text mẫu.
4. Cài đặt nhanh.
5. Cách dùng CLI.
6. Ví dụ với Excel.
7. Ví dụ với CSV.
8. Ví dụ với SQLite.
9. Preset theo ngành.
10. Cách tạo config.
11. File output.
12. Offline guarantee.
13. Security model.
14. Các giới hạn.
15. Contributing.
16. License.

Quick start phải tối đa khoảng 5 phút:

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux/macOS
source .venv/bin/activate

pip install -e .
dataclean profile examples/fnb/orders_dirty.xlsx
dataclean clean examples/fnb/orders_dirty.xlsx --preset fnb
```

Tạo hướng dẫn cài offline:

```bash
pip download -r requirements-lock.txt -d wheels/
pip install --no-index --find-links=./wheels -r requirements-lock.txt
```

Giải thích rõ:

* Core runtime không gọi mạng.
* Người dùng phải tải dependency trước nếu máy hoàn toàn air-gapped.
* Cách kiểm tra wheel.
* Cách xác minh checksum.
* Cách cài từ internal package registry.

---

## 23. API usability

Tham khảo tư duy API dễ đọc của các thư viện như pyjanitor, nhưng không copy mã nguồn.

API transformation nên có tên dạng động từ:

```python
clean_names()
normalize_unicode()
repair_vietnamese_text()
normalize_whitespace()
standardize_missing()
coerce_types()
flag_duplicates()
validate_schema()
```

Hỗ trợ `pandas.DataFrame.pipe`:

```python
df = (
    df
    .pipe(normalize_unicode)
    .pipe(normalize_whitespace)
    .pipe(standardize_missing, config=missing_config)
    .pipe(coerce_types, schema=schema)
)
```

Không monkey-patch pandas trong phiên bản đầu tiên nếu điều đó làm tăng rủi ro hoặc khó bảo trì.

Ưu tiên hàm thuần:

```python
def normalize_whitespace(
    df: pd.DataFrame,
    columns: Sequence[str] | None = None,
    *,
    mode: WhitespaceMode = WhitespaceMode.NORMALIZE,
) -> pd.DataFrame:
    ...
```

Mỗi hàm phải:

* Có type hint.
* Có docstring.
* Không mutate input mặc định.
* Có tùy chọn copy rõ ràng.
* Có unit test.
* Có error message dễ hiểu.
* Có hành vi deterministic.

---

## 24. Error handling

Tạo exception hierarchy:

```python
DataCleanError
├── ConfigurationError
├── InputFileError
├── UnsupportedFormatError
├── UnsafeInputError
├── EncodingDetectionError
├── SchemaValidationError
├── ExportError
└── ResourceLimitError
```

Không hiển thị stack trace dài cho người dùng CLI mặc định.

Có `--debug` để hiển thị thông tin kỹ thuật.

Thông báo lỗi phải gồm:

* Vấn đề.
* File hoặc cột liên quan.
* Cách khắc phục.
* Error code.

Ví dụ:

```text
[DC-INPUT-003] Không thể xác định delimiter của file sales.csv.

Thử chỉ định delimiter:
dataclean clean sales.csv --delimiter ";"
```

Không đưa raw data nhạy cảm vào exception.

---

## 25. Logging

Sử dụng Python `logging`.

Các level:

```text
ERROR
WARNING
INFO
DEBUG
```

Mặc định:

```text
INFO
```

Không log từng row.

Không log raw cell value ở INFO.

DEBUG vẫn phải mask PII và secret.

Cho phép:

```bash
dataclean clean input.xlsx --log-file output/run.log
```

Log phải hỗ trợ:

* Text format.
* JSON format tùy chọn.
* Correlation/run ID.
* Không chứa credential.
* Không chứa connection string đầy đủ.
* Không chứa customer data mặc định.

---

## 26. Performance

Mục tiêu ban đầu:

* CSV vài trăm MB có thể xử lý theo chunk.
* Excel được xử lý trong giới hạn của pandas/openpyxl và phải có cảnh báo rõ.
* Không copy DataFrame không cần thiết nhiều lần.
* Chỉ profile metric cần thiết.
* Không tính `value_counts()` không giới hạn trên cột cardinality rất cao.
* Không fuzzy matching mặc định.
* Không tạo HTML report quá lớn.
* Sample dữ liệu trong report phải tắt mặc định hoặc được mask.

Thêm benchmark đơn giản:

```text
100,000 rows
1,000,000 rows CSV
text-heavy Vietnamese dataset
numeric finance dataset
```

Benchmark không phải là điều kiện CI bắt buộc ở mọi commit.

---

## 27. Compatibility

Mục tiêu:

```text
Python 3.11+
Windows 10/11
Ubuntu LTS
macOS
```

Windows là nền tảng quan trọng vì nhiều người dùng Excel sử dụng Windows.

Mọi path phải dùng `pathlib`.

Không giả định terminal luôn hỗ trợ màu.

CLI màu phải tự tắt khi redirect output hoặc có:

```bash
--no-color
```

Text file mặc định xuất UTF-8.

CSV dùng tùy chọn UTF-8 BOM khi cần tương thích Excel:

```bash
--csv-encoding utf-8-sig
```

---

## 28. License và governance

Đề xuất license phù hợp cho mã nguồn mở, ví dụ Apache-2.0 hoặc MIT, và giải thích ngắn gọn lựa chọn.

Không copy code từ repository tham khảo nếu license không tương thích.

Nếu sử dụng hoặc chuyển thể code:

* Kiểm tra license.
* Ghi attribution.
* Giữ copyright notice theo yêu cầu.
* Ghi rõ trong `NOTICE` nếu cần.

Tạo:

* `CONTRIBUTING.md`
* `CODE_OF_CONDUCT.md`
* `SECURITY.md`
* `CHANGELOG.md`
* `CODEOWNERS`
* Pull request template.
* Bug report template.
* Feature request template.
* Security issue không được báo qua public issue.

Sử dụng semantic versioning.

---

## 29. Những điều không được làm

Không được:

* Chỉ tạo một notebook demo.
* Chỉ viết pseudocode.
* Chỉ tạo README.
* Chỉ cung cấp kiến trúc mà không có code.
* Tạo một file Python chứa toàn bộ framework.
* Thêm web UI vào core.
* Yêu cầu Internet khi runtime.
* Dùng AI để quyết định sửa dữ liệu.
* Gửi dữ liệu lên cloud.
* Tự động xóa dữ liệu không chắc chắn.
* Tự động sửa số tiền không chắc chắn.
* Tự động chạy macro.
* Tự động chạy SQL ghi dữ liệu.
* Dùng `eval` hoặc `exec`.
* Dùng pickle với input không tin cậy.
* Log PII.
* Ghi đè input.
* Im lặng bỏ dòng lỗi.
* Đưa dữ liệu thật vào sample.
* Tuyên bố đạt chứng nhận bảo mật khi chưa audit.
* Tạo quá nhiều abstraction không cần thiết.
* Thêm dependency nặng chỉ để làm đẹp.
* Tạo plugin system cho phép import Python tùy ý từ config.
* Dùng config như một ngôn ngữ lập trình.

---

## 30. Definition of Done

Repository chỉ được xem là hoàn thành khi:

* Có package cài được bằng `pip install -e .`.
* Có CLI chạy được.
* Có API Python.
* Đọc được CSV.
* Đọc được XLSX.
* Đọc SQLite read-only.
* Xuất CSV.
* Xuất XLSX.
* Xuất SQLite khi được cho phép.
* Xử lý missing.
* Chuẩn hóa Unicode.
* Sửa một số lỗi mojibake tiếng Việt có confidence cao.
* Chuẩn hóa whitespace và line break.
* Chuẩn hóa số.
* Chuẩn hóa ngày.
* Phát hiện duplicate.
* Có validation rule.
* Có preset F&B.
* Có preset finance.
* Có preset e-commerce.
* Có preset marketing.
* Có audit JSON.
* Có quality report.
* Có rejected rows.
* Có formula injection protection.
* Có PII masking.
* Có resource limits.
* Không overwrite mặc định.
* Không gọi network trong core runtime.
* Có unit test.
* Có integration test.
* Có security test.
* CI pass.
* Ruff pass.
* Mypy pass cho core module.
* Bandit không còn finding mức High.
* Pip-audit không còn vulnerability mức nghiêm trọng chưa được giải thích.
* README cho người mới.
* Có tài liệu offline installation.
* Có threat model.
* Có SECURITY.md.
* Có lock file hoặc quy trình build reproducible.
* Có license.
* Ví dụ chạy được trên Windows và Linux.

---

## 31. Kế hoạch triển khai

Thực hiện theo từng phase.

### Phase 1: Foundation

* Tạo repository structure.
* Tạo `pyproject.toml`.
* Tạo exception hierarchy.
* Tạo config parser.
* Tạo CLI skeleton.
* Tạo CI.
* Tạo security documentation.

### Phase 2: Input/output

* CSV loader.
* XLSX loader.
* SQLite loader.
* CSV exporter.
* XLSX exporter.
* SQLite exporter.
* File safety.
* Atomic write.

### Phase 3: Cleaning core

* Missing normalization.
* Unicode normalization.
* Vietnamese mojibake detection.
* Whitespace normalization.
* Column name normalization.
* Number parsing.
* Date parsing.
* Duplicate detection.

### Phase 4: Validation và reporting

* Schema.
* Rule engine.
* Quality metrics.
* Audit report.
* HTML report nhẹ.
* CLI summary.
* Exit codes.

### Phase 5: Domain presets

* F&B.
* Finance.
* E-commerce.
* Marketing.
* Synthetic example files.

### Phase 6: Hardening

* Security tests.
* Resource limits.
* Formula injection.
* PII masking.
* SQL protections.
* Network isolation test.
* Dependency audit.
* CodeQL.
* SBOM.
* Documentation review.

Sau mỗi phase:

* Chạy test.
* Chạy lint.
* Cập nhật README.
* Cập nhật changelog.
* Liệt kê quyết định kiến trúc.
* Không để TODO quan trọng mà không có issue hoặc giải thích.

---

## 32. Cách trả lời và tạo repository

Trước khi viết code:

1. Tóm tắt yêu cầu.
2. Liệt kê giả định.
3. Đề xuất kiến trúc.
4. Liệt kê dependency core và lý do.
5. Liệt kê threat model chính.
6. Nêu các trade-off.
7. Nêu những tính năng được đưa sang optional extras.

Sau đó triển khai repository thực tế.

Nếu môi trường cho phép tạo file, hãy tạo trực tiếp toàn bộ file trong workspace.

Nếu chỉ có thể trả lời bằng văn bản, với mỗi file hãy dùng định dạng:

```text
# File: pyproject.toml
```

sau đó là code fence chứa đầy đủ nội dung file.

Không cung cấp đoạn code rời rạc không biết đặt ở đâu.

Không dùng ký hiệu:

```text
...
TODO
implementation here
same as above
```

trong các file quan trọng.

Mọi file cần thiết để chạy MVP phải có nội dung đầy đủ.

Sau khi triển khai:

1. Hiển thị cây thư mục cuối cùng.
2. Hiển thị lệnh cài đặt.
3. Hiển thị lệnh chạy test.
4. Hiển thị ví dụ CLI.
5. Hiển thị output mẫu.
6. Liệt kê các kiểm soát bảo mật.
7. Liệt kê dependency.
8. Nêu giới hạn hiện tại.
9. Nêu roadmap nhưng không thay thế phần code còn thiếu.
10. Xác nhận các acceptance criteria bằng checklist có bằng chứng test.

---

## 33. Quy tắc ra quyết định khi yêu cầu chưa rõ

Không dừng triển khai chỉ vì thiếu một chi tiết nhỏ.

Khi chưa rõ, chọn theo thứ tự:

1. Không làm mất dữ liệu.
2. Không thay đổi dữ liệu không chắc chắn.
3. Secure by default.
4. Offline by default.
5. Report trước, mutate sau.
6. Giữ dependency tối thiểu.
7. Giữ API đơn giản.
8. Hỗ trợ Windows tốt.
9. Hành vi deterministic.
10. Ghi rõ giả định trong tài liệu.

Các quyết định có nguy cơ làm mất hoặc sai dữ liệu phải yêu cầu cấu hình rõ ràng, không được tự suy đoán.

---

## 34. Nguồn tham khảo định hướng

Có thể tham khảo về tư duy và kiến trúc từ:

* Repository Data Portfolio do người dùng cung cấp để hiểu các bài toán F&B, retail, finance, e-commerce và marketing.
* Pyjanitor để tham khảo cách thiết kế API làm sạch dữ liệu dễ đọc.
* Great Expectations để tham khảo tư duy data validation và expectation-based rules.
* Pandas để triển khai DataFrame transformations.
* OpenPyXL để xử lý XLSX.
* OWASP để kiểm soát injection và spreadsheet formula injection.
* GitHub security documentation để thiết lập code scanning, dependency review và secret scanning.
* OpenSSF Scorecard để tham khảo các tiêu chí bảo mật của repository mã nguồn mở.

Chỉ tham khảo pattern và ý tưởng.

Không sao chép mã nguồn mà chưa kiểm tra license và attribution.

---

## 35. Yêu cầu cuối cùng

Hãy xây dựng một MVP có thể chạy thật, không phải demo trình diễn.

Ưu tiên:

```text
an toàn
nhẹ
offline
dễ dùng
dễ audit
không làm mất dữ liệu
phù hợp công việc hằng ngày
```

Kết quả phải cho phép một người dùng phổ thông thực hiện:

```bash
dataclean clean messy_sales.xlsx --preset fnb
```

và nhận được:

```text
messy_sales_cleaned.xlsx
quality_report.html
quality_report.json
audit_log.json
rejected_rows.csv
```

mà không cần viết hàng loạt công thức Excel thủ công.
