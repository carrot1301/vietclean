# Đóng góp cho VietClean

Cảm ơn bạn muốn cải thiện VietClean. Dự án ưu tiên không làm mất dữ liệu, hành vi rõ
ràng, chạy offline, dependency nhỏ và hỗ trợ tốt tiếng Việt trên Windows.

## Trước khi bắt đầu

- Với bug hoặc đề xuất nhỏ, dùng issue template tương ứng và chỉ cung cấp dữ liệu tổng
  hợp đã tạo riêng cho test.
- Với thay đổi API, định dạng config, dependency hoặc kiến trúc, hãy mở feature request
  trước để thống nhất trade-off.
- Với lỗ hổng bảo mật, làm theo [SECURITY.md](SECURITY.md), không mở public issue.
- Không commit dữ liệu khách hàng, database thật, workbook có thông tin cá nhân,
  credential, `.env` hoặc connection string.

## Thiết lập môi trường

Yêu cầu Python 3.11 trở lên. Từ thư mục repository:

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install -e ".[dev,all]"
```

Linux/macOS:

```bash
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[dev,all]"
```

Các extra nặng chỉ dùng cho phát triển/integration. Thay đổi core không nên thêm
dependency nếu standard library giải quyết an toàn và dễ bảo trì.

## Kiểm tra trước khi gửi PR

```bash
pytest
pytest --cov=vietclean --cov-report=term-missing
ruff check src tests tools benchmarks
mypy src/vietclean
bandit -q -r src/vietclean
python -m build
```

Tooling/release script và benchmark cũng nằm trong lệnh Ruff ở trên. Chạy thêm policy
license:

```bash
python tools/check_dependency_licenses.py
```

`pip-audit` tra cơ sở dữ liệu advisory và có thể cần mạng; chạy trên máy staging/CI có
mạng hoặc mirror nội bộ:

```bash
python -m pip freeze --exclude-editable > audit-requirements.txt
pip-audit --strict --requirement audit-requirements.txt
```

Nếu một kiểm tra không thể chạy trong môi trường của bạn, ghi rõ lệnh, lý do và phần đã
kiểm tra trong PR. Không hạ ngưỡng hoặc bỏ qua finding bảo mật chỉ để CI xanh.

## Nguyên tắc triển khai

- Giữ API có type hint, docstring và hành vi deterministic.
- Không mutate `DataFrame` đầu vào mặc định; mọi xóa dòng/cột phải opt-in và có audit.
- Không dùng `eval`, `exec`, pickle cho input không tin cậy, `os.system` hoặc subprocess
  với `shell=True`.
- Config TOML/JSON là dữ liệu, không phải ngôn ngữ lập trình; không thêm import plugin
  hoặc biểu thức Python từ config.
- Không gọi Internet, gửi telemetry hoặc tải rule/model trong core runtime. Database URI
  từ xa chỉ được mở khi người dùng truyền rõ ràng.
- Dùng query tham số hóa; SQLite input phải giữ read-only. Không log URI đầy đủ.
- Output CSV/XLSX phải giữ bảo vệ formula injection mặc định. Thêm test với `=`, `+`,
  `-`, `@`, tab và carriage return khi sửa exporter.
- Dùng `Decimal` cho logic tiền tệ cần độ chính xác; không tự sửa giá trị mơ hồ.
- Dùng dữ liệu test synthetic nhỏ, bao gồm Unicode tiếng Việt và Windows path khi phù
  hợp. Test không được phụ thuộc mạng.
- Dùng `apply_patch`/thay đổi nhỏ, không format lại file không liên quan.

## Test cần bổ sung

Mỗi sửa lỗi cần test hồi quy. Thay đổi I/O hoặc security nên có cả trường hợp thành công
và fail-safe, đặc biệt cho:

- input không bị sửa và output không overwrite mặc định;
- số `0` đầu của identifier/phone;
- Unicode/mojibake idempotent;
- dòng CSV lỗi và rejects có thể truy vết;
- macro, ZIP ratio, giới hạn row/column/cell/memory;
- SQL nhiều statement, comment, keyword ghi và credential redaction;
- báo cáo không chứa raw PII;
- không có network call trong core runtime.

## Pull request và phát hành

Giữ PR tập trung vào một vấn đề. Mô tả tác động dữ liệu, rủi ro bảo mật, compatibility và
các lệnh kiểm tra đã chạy. Cập nhật tài liệu/config mẫu/CHANGELOG khi hành vi người dùng
thay đổi.

Dự án dùng Semantic Versioning: sửa tương thích ở patch, tính năng tương thích ở minor,
thay đổi phá vỡ ở major. Vì `0.x` là alpha, thay đổi phá vỡ vẫn phải được ghi rõ trong
CHANGELOG và migration note.

Bằng việc gửi đóng góp, bạn đồng ý phân phối phần đóng góp theo giấy phép MIT của
repository và xác nhận bạn có quyền cung cấp mã/tài liệu đó.

Mọi tương tác phải tuân theo [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## Vì sao dùng MIT

MIT được chọn vì ngắn, dễ hiểu và cho phép sử dụng trong quy trình nội bộ/thương mại với
điều kiện giữ copyright và license notice; phần miễn trừ bảo hành cũng phù hợp một công cụ
dữ liệu alpha. License của dependency vẫn độc lập và được kiểm tra ở CI/release; MIT không
tự động làm mọi dependency trở thành MIT.

Trước release, điền GitHub account/team thật vào `.github/CODEOWNERS`. Workflow cố ý chặn
release nếu file chỉ còn comment hoặc placeholder; không thay bằng username đoán.
