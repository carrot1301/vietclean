# Ví dụ theo ngành

Các lệnh dưới đây chạy local/offline và dùng dữ liệu synthetic trong `examples/`. Không
dùng rejected rows hoặc report từ dữ liệu thật để mở issue công khai.

## F&B / Excel

```bash
dataclean profile examples/fnb/orders_dirty.xlsx --preset fnb
dataclean clean examples/fnb/orders_dirty.xlsx \
  --config configs/fnb.toml \
  -o output/fnb_orders_clean.xlsx
```

Trên PowerShell, viết lệnh một dòng hoặc thay `\` cuối dòng bằng backtick.

## Finance / CSV

```bash
dataclean profile examples/finance/transactions_dirty.csv --preset finance
dataclean clean examples/finance/transactions_dirty.csv \
  --config configs/finance.toml \
  -o output/finance_transactions_clean.csv
```

Config giữ nguyên số tiền hoặc ngày mơ hồ và ghi lỗi để review; không tự sửa số tiền thiếu
đơn vị hoặc forward-fill giao dịch.

## E-commerce / CSV

```bash
dataclean clean examples/ecommerce/orders_dirty.csv \
  --config configs/ecommerce.toml \
  -o output/ecommerce_orders_clean.xlsx
```

Ví dụ chứa formula payload synthetic. Export CSV/XLSX mặc định prefix cell có rủi ro và
audit số cell đã sanitize.

## Marketing / CSV

```bash
dataclean clean examples/marketing/campaigns_dirty.csv \
  --config configs/marketing.toml \
  -o output/marketing_campaigns_clean.csv
```

Outlier và KPI/domain rule ở chế độ `report_only`; số gốc không bị winsorize hoặc thay đổi
chỉ vì khác KPI tính lại.

## SQLite

Tạo database synthetic, sau đó đọc bảng `orders` ở chế độ read-only và ghi database khác:

```bash
python examples/sqlite/create_example.py
dataclean profile examples/sqlite/orders_dirty.sqlite --table orders --preset ecommerce
dataclean clean examples/sqlite/orders_dirty.sqlite \
  --table orders \
  --config configs/ecommerce.toml \
  -o output/orders_clean.sqlite \
  --output-table orders_clean
```

Script tạo fixture từ chối ghi đè. VietClean cũng từ chối output trùng input; SQLite input
được mở `mode=ro` và query tùy chỉnh chỉ nhận một `SELECT`/`WITH`.

## Chỉ kiểm tra, không ghi data

```bash
dataclean clean examples/marketing/campaigns_dirty.csv \
  --config configs/marketing.toml \
  --dry-run
```

Kiểm tra audit, quality report và rejected rows trước khi đưa output vào hệ thống chính.
