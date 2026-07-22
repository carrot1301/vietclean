# VietClean

VietClean là framework Python nhẹ, chạy hoàn toàn offline để làm sạch dữ liệu nghiệp vụ
Việt Nam bằng `pandas`. Mục tiêu là thay các chuỗi công thức Excel lặp đi lặp lại bằng một
lệnh có thể kiểm tra, tái sử dụng và ghi lại mọi thay đổi.

Framework xử lý các lỗi thường gặp:

- giá trị thiếu như `N/A`, `null`, `--`, `không có`, `chưa có dữ liệu`;
- Unicode tiếng Việt, ký tự ẩn/BOM và một số dạng mojibake như `Nguyá»…n`;
- xuống dòng, tab, khoảng trắng thừa và non-breaking space;
- email, số điện thoại Việt Nam, số tiền và cách ghi số kiểu Việt Nam/quốc tế;
- ngày tháng, boolean, danh mục, giới hạn giá trị và mapping tùy chỉnh;
- dòng/cột rỗng và bản ghi trùng (chỉ xóa khi được bật);
- CSV/TSV/TXT, Excel, Parquet và cơ sở dữ liệu SQL.

VietClean không gọi API hay gửi telemetry và không cần Internet khi xử lý file/database
cục bộ. Internet chỉ cần ở lần cài Python/dependency ban đầu; kết nối database từ xa chỉ
xảy ra khi chính bạn truyền một URI database từ xa.

## Cài đặt

Yêu cầu Python 3.11 trở lên.

Clone public repository rồi chạy từ thư mục checkout:

```bash
git clone https://github.com/carrot1301/vietclean.git
cd vietclean
python -m venv .venv
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
pip install -e .
```

macOS/Linux:

```bash
source .venv/bin/activate
pip install -e .
```

Gói lõi hỗ trợ CSV, SQLite và `.xlsx` bằng `pandas` + `openpyxl`. Các lựa chọn khác:

```bash
pip install -e ".[sql]"       # PostgreSQL/MySQL/... qua SQLAlchemy
pip install -e ".[parquet]"   # Parquet
pip install -e ".[legacy-excel]" # đọc file .xls cũ
pip install -e ".[binary-excel]" # đọc file .xlsb qua pyxlsb
pip install -e ".[all]"       # tất cả định dạng
```

## Dùng ngay

Lệnh ngắn nhất cho công việc hằng ngày:

```bash
dataclean clean messy_sales.xlsx --preset fnb
```

Không cần chỉ định output. Lệnh tạo một bundle an toàn, không sửa file nguồn:

```text
messy_sales_output/
├── messy_sales_cleaned.xlsx
├── quality_report.json
├── quality_report.html
├── audit_log.json
├── column_mapping.json
├── rejected_rows.csv
└── run_summary.txt
```

Làm sạch Excel theo profile bán hàng online:

```bash
vietclean clean don_hang.xlsx -o don_hang_sach.xlsx --profile ecommerce
```

CLI cũng cung cấp alias `dataclean`, `profile` (cho `inspect`) và `--preset` (cho
`--profile`) để dùng theo cú pháp ngắn:

```bash
dataclean profile examples/fnb/orders_dirty.xlsx
dataclean clean examples/fnb/orders_dirty.xlsx --preset fnb -o orders_clean.xlsx
```

CSV:

```bash
vietclean clean khach_hang.csv -o khach_hang_sach.csv --profile marketing
```

Xem vấn đề trước khi sửa (mặc định không in dữ liệu mẫu để tránh lộ PII):

```bash
vietclean inspect khach_hang.csv --profile marketing
```

Chạy thử, chỉ tạo báo cáo và chưa ghi dữ liệu:

```bash
vietclean clean don_hang.xlsx --profile ecommerce --dry-run
```

Sau khi clone, có thể kiểm tra ngay luồng CSV hoàn toàn offline bằng dữ liệu mẫu đi kèm:

```bash
vietclean inspect examples/ecommerce_dirty.csv --profile ecommerce
vietclean clean examples/ecommerce_dirty.csv -o ecommerce_clean.csv --config examples/ecommerce_config.json
```

Kết quả mẫu còn 3 dòng sau khi bỏ một bản ghi trùng, sửa tên tiếng Việt, chuẩn hóa số
điện thoại và chuyển `1.250.000 đ`/`850,000 VND` thành số. CSV output mặc định dùng
`utf-8-sig` để Excel trên Windows nhận đúng tiếng Việt.

Mỗi lần chạy mặc định tạo `audit_log.json` chứa số ô đã đổi, missing trước/sau,
số dòng bị loại, hash input/config/output, lỗi theo rule và cảnh báo. VietClean cũng tạo
`quality_report.json` và `quality_report.html` tự chứa để xem Data Quality Score hoàn toàn offline. Quality report
chỉ chứa số liệu tổng hợp, không đưa giá trị thô hay mẫu dữ liệu vào HTML. Dùng
`--no-quality-html` nếu chỉ cần JSON, hoặc `--no-quality-report` để tắt cả hai. Dòng CSV
lỗi được đưa vào `*.rejected-rows.csv` theo mặc định; file này chứa dữ liệu thô và có thể
có PII, nên cần bảo vệ hoặc dùng `--no-rejects` nếu không cần. File nguồn luôn được giữ
nguyên; `--overwrite` chỉ cho phép thay output/report đã tồn tại.

Kiểm tra file theo schema và giải thích báo cáo:

```bash
dataclean validate cleaned.xlsx --schema schema.json
dataclean explain messy_sales_output/quality_report.json
```

Đặt ngưỡng chất lượng cho pipeline/CI; artifact vẫn được ghi trước khi trả exit code `1`:

```bash
dataclean clean input.csv --quality-threshold 85
```

## Profile có sẵn

| Profile | Dữ liệu tiêu biểu |
|---|---|
| `generic` | Dữ liệu doanh nghiệp nói chung |
| `fnb` | Menu, POS, đặt bàn, chi nhánh, món ăn |
| `finance` | Giao dịch, tài khoản, hóa đơn, khoản vay |
| `ecommerce` | Đơn hàng, sản phẩm, tồn kho, vận chuyển |
| `marketing` | Campaign, ads, lead, email và chuyển đổi |

Profile nhận diện cột theo tên tiếng Việt/tiếng Anh. Cột lạ được giữ nguyên; VietClean
không đoán kiểu chỉ dựa vào vài dòng dữ liệu. Xem danh sách bằng `vietclean profiles`.

## Cấu hình công việc thực tế

Tạo file TOML mẫu rồi kiểm tra trước khi chạy:

```bash
vietclean config init rules.toml --profile ecommerce
vietclean config validate rules.toml
```

JSON vẫn được hỗ trợ; có thể tạo trực tiếp theo phần mở rộng:

```bash
vietclean init-config rules.json --profile ecommerce
```

Ví dụ `rules.json`:

```json
{
  "profile": "ecommerce",
  "text": {
    "line_breaks": "keep",
    "repair_mojibake": true
  },
  "duplicates": {
    "enabled": true,
    "subset": ["mã đơn hàng"],
    "keep": "first"
  },
  "columns": {
    "email": {
      "type": "email",
      "invalid": "missing",
      "required": true
    },
    "số điện thoại": {
      "type": "phone",
      "invalid": "keep"
    },
    "tổng tiền": {
      "type": "currency",
      "currency": "VND",
      "min": 0,
      "invalid": "keep"
    },
    "trạng thái": {
      "type": "category",
      "map": {
        "done": "Hoàn tất",
        "completed": "Hoàn tất",
        "cancel": "Đã hủy"
      }
    },
    "ngày đặt": {
      "type": "date",
      "invalid": "missing"
    }
  }
}
```

Chạy cấu hình:

```bash
vietclean clean raw.xlsx -o clean.xlsx --config rules.json
```

Các rule theo cột:

- `type`: `text`, `identifier`, `email`, `phone`, `integer`, `number`, `percentage`, `currency`,
  `date`, `datetime`, `boolean`, `category`, `address`;
- `invalid`: `keep` (an toàn mặc định), `missing` hoặc `raise`;
- `map`/`replace`, `case`: `lower`, `upper`, `title`, `casefold`;
- `min`, `max`, `regex`, `allowed`, `required`;
- `fill`: giá trị cố định; `fill_strategy`: `mode`, `median`, `mean`.
- `currency`: đơn vị duy nhất mong đợi (`VND` hoặc `USD`) cho cột tiền; marker khác đơn
  vị bị coi là invalid thay vì bị bỏ âm thầm;
- `bare_percentage`: cách hiểu số phần trăm không có `%`: `reject` (mặc định),
  `fraction` (`0.15` là 15%) hoặc `percent` (`15` là 15%).

`line_breaks` nhận `keep`, `space`, hoặc `remove`. Mặc định `keep` để không làm mất cấu trúc
đoạn; chỉ chọn `space`/`remove` khi quy tắc nghiệp vụ yêu cầu rõ ràng.

## Excel nhiều sheet

Các ví dụ nhiều dòng dưới đây dùng dấu `\` của Bash. Trong PowerShell, dùng dấu
backtick (`` ` ``) ở cuối dòng hoặc viết toàn bộ lệnh trên một dòng.

```bash
vietclean clean bao_cao.xlsx -o bao_cao_sach.xlsx \
  --sheet "Tháng 7" --output-sheet "Du lieu sach" --profile finance
```

Xử lý toàn bộ sheet và ghi một workbook `.xlsx` macro-free:

```bash
dataclean clean bao_cao.xlsx --all-sheets --preset finance
```

Audit ghi report riêng theo sheet, số formula/merged range và cảnh báo schema khác nhau.
API còn có `inspect_excel_workbook()`, `read_excel_sheets()`, `read_excel_tables()` và
`write_excel_sheets()` để chọn sheet hoặc vùng bảng rõ ràng. Công thức không được thực thi;
macro không được bảo toàn trong output.

## CSV lớn theo chunk

```bash
dataclean clean giao_dich.csv --chunksize 100000 --preset finance
```

Luồng này đọc, làm sạch và ghi CSV theo từng chunk vào file tạm rồi replace atomically.
`--timeout-seconds`, các giới hạn `--max-*`, checkpoint/cancellation trong Python API và
reject trace theo dòng giúp job dài fail an toàn. Các chunk phải tạo cùng schema output.

## SQLite và SQL

Đọc một bảng SQLite và ghi sang database mới:

```bash
vietclean clean ban_hang.db -o ban_hang_sach.db \
  --table orders --output-table orders_clean --profile ecommerce
```

Hoặc dùng câu truy vấn chỉ đọc:

```bash
vietclean clean ban_hang.db -o ban_hang_sach.csv \
  --query "SELECT * FROM orders WHERE created_at >= '2026-01-01'"
```

Với PostgreSQL/MySQL và các database khác, cài extra `sql` cùng driver tương ứng, truyền
URI SQLAlchemy làm input/output và cung cấp `--table`. Kết nối mạng bị tắt mặc định: phải
thêm `--allow-remote-database`; riêng `--query` còn cần `--allow-remote-query`. Luôn dùng
tài khoản chỉ đọc cho input. VietClean không lưu thông tin kết nối.

SQLite lưu giá trị tiền `Decimal` thành `TEXT` chuẩn để giữ chính xác, không tự ép sang
`float`. Nếu hệ thống đích cần phép tính SQL, hãy tạo schema `NUMERIC` rõ ràng và kiểm thử
quy tắc làm tròn trước khi import.

## Python API

Luồng file phổ biến tạo trọn bundle chỉ bằng một hàm:

```python
from dataclean import clean_file

run = clean_file(
    "input.xlsx",
    output_dir="output",
    profile="fnb",
    config_path="configs/fnb.toml",
)
print(run.quality_score, run.audit_path)
```

`dataclean` là import tương thích với đặc tả; package triển khai chính `vietclean` cung cấp
cùng public API.

```python
import pandas as pd
from vietclean import DataCleaner, clean_dataframe

df = pd.read_excel("don_hang.xlsx")

# Nhanh: chỉ lấy DataFrame sạch
clean = clean_dataframe(df, profile="ecommerce", config="rules.json")

# Có audit report
result = DataCleaner(profile="ecommerce", config="rules.json").clean(df)
result.data.to_excel("don_hang_sach.xlsx", index=False)
result.report.to_json("audit.json")
```

Đọc/ghi thống nhất:

```python
from vietclean.io import read_data, write_data

df = read_data("input.csv", encoding="auto")
write_data(df, "output.xlsx", sheet_name="cleaned")
```

Các transformation thuần hỗ trợ `DataFrame.pipe`, không monkey-patch pandas và không
mutate input mặc định:

```python
from vietclean import (
    clean_names,
    coerce_types,
    normalize_unicode,
    normalize_whitespace,
    standardize_missing,
)

clean = (
    df
    .pipe(clean_names)
    .pipe(normalize_unicode)
    .pipe(normalize_whitespace, mode="normalize_spaces")
    .pipe(standardize_missing, config={"tokens": ["N/A", "--"]})
    .pipe(coerce_types, schema={"tổng tiền": "currency"})
)
```

## Nguyên tắc an toàn dữ liệu

- Không sửa trực tiếp DataFrame đầu vào trừ khi `inplace=True`.
- Không tự xóa duplicate; phải bật `duplicates.enabled`.
- ID, mã tài khoản, SKU được giữ dạng chuỗi để không mất số `0` đầu.
- Kiểu được suy ra từ alias tên cột; nếu tỷ lệ parse dưới ngưỡng, cột được giữ nguyên.
- Giá trị sai được giữ nguyên mặc định và được ghi trong report.
- Khi xuất CSV/Excel, chuỗi có nguy cơ công thức như `=...`, `@...` hoặc `+cmd...` được
  vô hiệu hóa; số âm hợp lệ được giữ nguyên. Chỉ dùng `--formula-mode report_only`/`allow`
  khi đã hiểu rủi ro.
- CLI từ chối query không bắt đầu bằng `SELECT`/`WITH` và các từ khóa ghi phổ biến. Với
  database từ xa bắt buộc opt-in và vẫn phải dùng tài khoản chỉ có quyền đọc, vì kiểm tra
  chuỗi không thể thay thế quyền hạn do database thực thi. Các giới hạn file, số dòng/cột,
  tổng số ô (`--max-cells`), độ dài ô, rejected rows và memory có thể đặt bằng các cờ
  `--max-*` của CLI.
- `--output-root` cùng secure mode mặc định chặn path traversal, symlink/reparse point và
  mọi artifact nằm ngoài thư mục output được phép. Chỉ tắt bằng `--no-secure-mode` trong
  môi trường desktop đã tin cậy và sau khi review đường dẫn.
- `--log-file`, `--log-format json`, `--log-level` và `--run-id` tạo log aggregate có
  redaction credential/PII; DEBUG cũng không log raw cell.
- Không chạy macro Excel, không thực thi SQL lấy từ ô dữ liệu và không tự gọi network;
  chỉ URI database do người dùng truyền mới có thể mở kết nối từ xa.

Với dữ liệu tài chính quan trọng, hãy chạy `--dry-run`, đọc report và thử trên một bản sao
trước khi dùng kết quả trong quy trình chính thức.

## Giới hạn hiện tại

- Excel bị giới hạn bởi `pandas`/engine và resource guard; output nhiều sheet luôn là
  `.xlsx`, không bảo toàn formatting, công thức hay macro của workbook nguồn.
- Chunk mode giữ memory có giới hạn nhưng duplicate được đối chiếu trong từng chunk;
  dùng full mode nếu cần `keep=last`/`most_complete` hoặc duplicate xuyên chunk. Group
  imputation phụ thuộc dữ liệu ngoài chunk cũng nên chạy full mode.
- SQLAlchemy là extra và remote database phải opt-in. Bộ lọc SQL không thay thế quyền
  read-only của tài khoản database; query tùy chỉnh là opt-in thứ hai.
- Sửa mojibake chỉ áp dụng candidate có độ tin cậy cao; chuỗi không chắc chắn được giữ lại.
- `.xls`/`.xlsb` chỉ đọc khi cài optional engine; fuzzy duplicate, OCR và machine learning
  không thuộc core nhẹ hiện tại.

## Tài liệu và cộng đồng

- [Kiến trúc](docs/architecture.md) và [cấu hình](docs/configuration.md)
- [Cài đặt air-gapped](docs/offline-installation.md)
- [Vận hành an toàn](docs/security.md), [threat model](docs/threat-model.md) và
  [chính sách báo lỗi bảo mật](SECURITY.md)
- Đóng góp theo [CONTRIBUTING.md](CONTRIBUTING.md) và quy tắc ứng xử tại
  [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)

VietClean phát hành theo giấy phép [MIT](LICENSE).

## Phát triển

```bash
pip install -e ".[dev,all]"
pytest
ruff check src tests
mypy src/vietclean
bandit -q -lll -r src/vietclean
python -m build
```

Kiến trúc cố ý nhỏ: `text.py` chứa chuẩn hóa scalar, `profiles.py` nhận diện ý nghĩa cột,
`pipeline.py` điều phối rule/report, và `io.py` chỉ lo đọc ghi. Có thể thêm profile mới mà
không cần thêm dependency hay dịch vụ bên ngoài.
