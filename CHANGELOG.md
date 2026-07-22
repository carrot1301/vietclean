# Changelog

## 0.1.0 - 2026-07-22

- Lõi làm sạch Unicode/tiếng Việt, whitespace, missing và semantic types.
- Profile generic, F&B, finance, ecommerce và marketing.
- CSV/Excel/Parquet/SQLite/SQL I/O, CLI và ghi file local theo cơ chế atomic.
- Cấu hình TOML/JSON theo cột, validate config và chế độ dry-run.
- Bundle mặc định gồm cleaned data, audit, quality JSON/HTML, rejected rows, column mapping
  và run summary; có `validate`, `explain` và quality-threshold exit code.
- Làm sạch workbook nhiều sheet và CSV streaming theo chunk với timeout/cancellation point.
- Public `clean_file()` cùng các transformation `DataFrame.pipe` theo API trong đặc tả.
- Import tương thích `dataclean` để các ví dụ trong đặc tả chạy nguyên trạng.
- Domain validation chéo cột cho F&B, finance, e-commerce và marketing; outlier report-only.
- Audit JSON có hash đầu vào/đầu ra; quality report JSON/HTML chỉ chứa số liệu tổng hợp.
- Có thể capture dòng CSV lỗi sang rejected-rows riêng để xử lý lại.
- Giới hạn tài nguyên, query SQL chỉ đọc và bảo vệ formula injection cho spreadsheet.
- Logging text/JSONL có run ID và redaction PII/credential kể cả DEBUG/exception.
- CI smoke trên Windows/macOS; release gate tạo checksum, SPDX SBOM và hashed platform lock.
- Release từ chối archive chứa path traversal, credential/key hoặc workbook/database thật.
- Config và dữ liệu synthetic cho generic, F&B, finance, e-commerce, marketing và SQLite.
- Benchmark tách riêng cho DataFrame 100k, CSV 1 triệu dòng, text tiếng Việt và số tài chính.
