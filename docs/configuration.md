# Cấu hình VietClean

TOML là định dạng chính trên Python 3.11; JSON vẫn được hỗ trợ. Config chỉ chứa dữ liệu,
không có biến môi trường, biểu thức Python, lambda hay import plugin.

Tạo và kiểm tra file mẫu:

```bash
vietclean config init rules.toml --profile ecommerce
vietclean config validate rules.toml
```

Repository cũng có năm config đã review tại `configs/basic.toml`, `fnb.toml`,
`finance.toml`, `ecommerce.toml`, `marketing.toml`. Hãy copy một file rồi chỉnh rule theo
nghiệp vụ; không đặt credential, URI database hoặc dữ liệu khách hàng vào đó.

Thứ tự ưu tiên là mặc định an toàn → mặc định profile → config người dùng. Nếu truyền
`--profile` trên CLI, giá trị đó ưu tiên hơn `profile`/`preset` trong file.

## Ví dụ TOML đầy đủ

```toml
version = 1
strict = true
profile = "ecommerce"
locale = "vi_VN"
auto_types = true

[text]
unicode_form = "NFC"
repair_mojibake = true
remove_invisible = true
line_breaks = "keep"
trim = true

[missing]
tokens = ["", "N/A", "NULL", "--", "không có", "chưa có"]
case_sensitive = false

[type_conversion]
minimum_success_rate = 0.90
day_first = true
decimal_separator = ","
thousands_separator = "."
currency = "VND"
timezone_policy = "preserve"
min_year = 2000
max_year = 2100
invalid = "keep"

[column_names]
strip = true
line_breaks = "space"
deduplicate = true
lowercase = false
snake_case = false

[drop]
empty_rows = false
empty_columns = false

[duplicates]
enabled = false
subset = ["mã đơn hàng"]
keep = "first"

[columns."mã đơn hàng"]
type = "identifier"
required = true
missing_strategy = "flag_only"
flag_column = "order_id_was_missing"

[columns."tổng tiền"]
type = "currency"
currency = "VND"
decimal_comma = true
min = 0
invalid = "keep"

[columns."giảm giá"]
type = "percentage"
percent_as_fraction = true
bare_percentage = "reject"
min = 0
max = 1

[columns.email]
type = "email"
invalid = "missing"

[columns."trạng thái"]
type = "category"
allowed = ["Mới", "Đang giao", "Hoàn tất", "Đã hủy"]

[columns."ngày đặt"]
type = "date"
invalid = "keep"
```

TOML không có literal `null`; muốn bỏ giới hạn `min_year`/`max_year` thì không khai báo
key đó.

## Nhóm option

### Cấp cao nhất

- `version`: hiện chỉ nhận `1`.
- `strict`: khi `true`, từ chối key không biết ở cấp cao nhất. Validation lồng nhau còn
  có giới hạn; lệnh validate không thay thế test trên dữ liệu đại diện.
- `profile` hoặc `preset`: `generic`, `fnb`, `finance`, `ecommerce`, `marketing`.
- `locale`: metadata/giá trị mặc định nghiệp vụ; parsing số cụ thể dùng separator bên
  dưới.
- `auto_types`: dùng alias profile để chọn semantic type cho cột chưa có rule rõ ràng.

### `text`

- `unicode_form`: `NFC` (khuyến nghị) hoặc `NFKC` khi thật sự cần chuẩn hóa mã/search.
- `repair_mojibake`: thử các sửa lỗi có confidence cao và đảo ngược được.
- `remove_invisible`: loại BOM/zero-width và chuẩn hóa non-breaking space.
- `line_breaks`: `keep`, `space`, `remove`. Mặc định an toàn là `keep`.
- `trim`: bỏ whitespace đầu/cuối.

### `missing`

- `tokens`: danh sách token được chuyển thành `pd.NA`; `0` và `False` không phải missing
  mặc định.
- `case_sensitive`: so token phân biệt hoa/thường hay không.

Mỗi rule cột có thể đặt `missing_tokens` để thay danh sách toàn cục.

### `type_conversion`

- `minimum_success_rate`: ngưỡng `[0, 1]` cho auto-type từ profile; không chặn type được
  khai báo rõ ở cột.
- `day_first`: cách hiểu ngày số; dùng cẩn trọng với ngày mơ hồ.
- `decimal_separator`, `thousands_separator`, `currency`: ngữ cảnh parsing số/tiền.
  `currency` hiện nhận `VND` hoặc `USD`; marker khác đơn vị mong đợi bị coi là invalid.
- `timezone_policy`: `preserve`, `naive`, `utc`, `naive_utc`.
- `min_year`, `max_year`: năm hợp lệ nếu có.
- `excel_serial`: cho phép số serial Excel trong cột date/datetime (mặc định `true`).
- `invalid`: `keep`, `missing`, `raise` làm chính sách mặc định.

### `column_names`

`strip`, `lowercase`, `snake_case`, `line_breaks` điều khiển tên cột. `deduplicate=true`
thêm hậu tố `_2`, `_3`; nếu tắt mà tên vẫn trùng, cleaning dừng thay vì xử lý mơ hồ.
Mapping tên cũ/mới được ghi vào audit.

### `drop` và `duplicates`

`drop.empty_rows` và `drop.empty_columns` đều `false` mặc định. `duplicates.enabled=false`
mặc định chỉ report. Khi bật, `subset` là tên cột/danh sách cột và `keep` là `first`,
`last` hoặc `false` (JSON/Python; TOML dùng một trong hai chuỗi).

## Rule theo cột

Các `type` đang hỗ trợ:

```text
text, identifier, category, address, email, phone,
integer, number, percentage, currency, date, datetime, boolean
```

Option dùng chung:

- `invalid`: `keep` an toàn mặc định, `missing`, hoặc `raise`;
- `required`: thêm cảnh báo nếu vẫn còn missing;
- `map`/`replace`: mapping trực tiếp rồi fallback case-insensitive cho key text;
- `case`: `lower`, `upper`, `title`, `casefold`;
- `min`, `max`, `regex`, `allowed`: validation; invalid được xử lý theo policy;
- `fill`: giá trị dùng với `fill_constant` hoặc tương thích shorthand;
- `default_country`: mặc định `VN` cho phone;
- `decimal_comma`: override cách parse số của cột;
- `percent_as_fraction`: `15%` thành `0.15` khi `true`;
- `bare_percentage`: số không có ký hiệu `%` được `reject` (mặc định), hiểu là
  `fraction` (`0.15` là 15%), hoặc `percent` (`15` là 15%);
- `currency`: override đơn vị tiền mong đợi của riêng cột (`VND` hoặc `USD`). Cột chứa
  marker tiền hỗn hợp bị giữ/đưa về missing/raise theo chính sách `invalid`.
- `format`: định dạng ngày strftime rõ ràng; `excel_serial` có thể override theo cột.

`missing_strategy` nhận:

```text
keep, drop_row, drop_column, fill_constant, fill_zero,
fill_mean, fill_median, fill_mode, forward_fill, backward_fill,
group_median, group_mode, flag_only
```

`group_median`/`group_mode` cần `group_by` là tên cột hoặc danh sách. `flag_only` nhận
`flag_column`; nếu không có sẽ dùng `<tên_cột>_was_missing`. Mọi fill/xóa/cột cờ được
đếm trong audit. Không dùng mean/forward-fill cho mã hoặc số tiền chỉ vì tiện; quyết định
imputation phải dựa trên nghiệp vụ.

## An toàn config

- Chỉ nhận file `.toml` hoặc JSON; extension khác được parse như JSON.
- Không đặt credential, database URI hoặc dữ liệu thật trong config được commit.
- Regex phải ngắn, anchored và được review. Python regex không có timeout tuyệt đối.
- `config validate` kiểm tra cấu trúc được triển khai, không kiểm tra sự tồn tại của mọi
  cột trong file dữ liệu; lỗi cột được phát hiện khi clean.
- Các cờ input/output/resource của CLI được truyền trên command line; không giả định
  table `[input]`/`[output]` trong config sẽ điều khiển I/O nếu chưa có tài liệu API rõ.
