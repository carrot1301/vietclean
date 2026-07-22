## Mục tiêu

Mô tả vấn đề, hành vi trước/sau và phạm vi thay đổi.

## Tác động dữ liệu và bảo mật

Nêu thay đổi row/column/value, backward compatibility, PII, formula/SQL/path/resource
risks và cách fail-safe. Nếu không có, giải thích ngắn gọn vì sao.

## Kiểm tra đã chạy

Liệt kê lệnh và kết quả thực tế.

- [ ] `pytest`
- [ ] `ruff check src tests`
- [ ] `mypy src/vietclean` (nếu thay core)
- [ ] `bandit -q -r src/vietclean` (nếu thay security/I/O)
- [ ] Build/smoke test phù hợp

## Checklist

- [ ] PR tập trung, không format/chạm file không liên quan.
- [ ] Có test hồi quy bằng dữ liệu synthetic; không có dữ liệu khách hàng/PII/secret.
- [ ] Input không bị sửa và hành vi xóa/overwrite vẫn opt-in, có audit.
- [ ] Core runtime không thêm network/telemetry hoặc dependency không cần thiết.
- [ ] Error/report/log không chứa raw PII hay credential.
- [ ] Đã cập nhật tài liệu/config mẫu/CHANGELOG nếu hành vi người dùng thay đổi.
- [ ] Không dùng `eval`, `exec`, pickle input, config-as-code hoặc shell command nguy hiểm.
- [ ] Tôi có quyền đóng góp nội dung này theo giấy phép MIT.
