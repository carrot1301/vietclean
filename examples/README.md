# Dữ liệu ví dụ synthetic

Toàn bộ file trong thư mục này được tạo riêng cho VietClean, không lấy từ khách hàng hay
hệ thống production. Email dùng miền dành cho ví dụ; số điện thoại, mã giao dịch và số
tài khoản (nếu có) không đại diện cho cá nhân thật.

- `fnb/orders_dirty.xlsx`: workbook F&B nhỏ.
- `finance/transactions_dirty.csv`: tiền tệ, ngày mơ hồ, missing và duplicate.
- `ecommerce/orders_dirty.csv`: tiếng Việt lỗi encoding, phone/email giả và formula payload.
- `marketing/campaigns_dirty.csv`: KPI, phần trăm, outlier và missing campaign ID.
- `sqlite/create_example.py`: tạo SQLite synthetic bằng query tham số hóa.

Không gửi các file output/rejected rows tạo từ dữ liệu thật vào issue hoặc pull request.
