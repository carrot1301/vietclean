# Cài đặt VietClean trên máy offline/air-gapped

Core runtime không tải model/rule, không gọi API và không gửi telemetry. Cần Internet
hoặc package mirror ở máy staging để lấy Python wheel trước. Kết nối database từ xa là
ngoại lệ do người dùng chủ động và không phải chế độ air-gapped.

## 1. Chọn máy staging tương thích

Wheel của pandas/numpy phụ thuộc hệ điều hành, kiến trúc và phiên bản Python. Chuẩn bị
wheelhouse riêng cho từng tổ hợp đích, ví dụ Windows x64 + Python 3.11 hoặc Ubuntu x64 +
Python 3.12. Không tải wheel cho một nền tảng rồi giả định dùng được ở nền tảng khác.

Trên máy staging có mạng, từ commit/tag VietClean đã review:

```bash
python -m venv .venv-build
```

Kích hoạt virtualenv rồi chạy:

```bash
python -m pip install -U pip build
python -m pip wheel --wheel-dir wheelhouse ".[all]"
```

Thay `.[all]` bằng `.` nếu chỉ cần core. Lệnh tạo wheel VietClean và tải/build toàn bộ
dependency cần thiết vào `wheelhouse/`. Với release chính thức, dùng tag/commit cố định,
package index tin cậy và lưu log resolver.

Nếu release có `requirements-lock.txt` với hash, ưu tiên quy trình khóa đó:

```bash
python -m pip download --require-hashes -r requirements-lock.txt -d wheelhouse
python -m build --wheel
python -m pip download --no-deps dist/vietclean-*.whl -d wheelhouse
```

Không tự thêm `--trusted-host`; tùy chọn đó có thể bỏ kiểm tra TLS. Với CA nội bộ, cấu
hình certificate qua chính sách pip của tổ chức.

## 2. Tạo checksum trên staging tin cậy

Linux/macOS:

```bash
(cd wheelhouse && sha256sum *.whl) > SHA256SUMS
```

Windows PowerShell:

```powershell
Get-ChildItem .\wheelhouse\*.whl | Sort-Object Name | ForEach-Object {
    $hash = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower()
    "$hash  $($_.Name)"
} | Set-Content -Encoding ascii .\SHA256SUMS
```

Chuyển `wheelhouse/`, `SHA256SUMS` và metadata commit/tag qua kênh được tổ chức phê
duyệt. SHA-256 phát hiện file thay đổi sau khi tạo manifest; nó không chứng minh nguồn
ban đầu đáng tin nếu staging đã bị xâm nhập.

## 3. Xác minh trên máy offline

Linux/macOS:

```bash
(cd wheelhouse && sha256sum -c ../SHA256SUMS)
```

Windows PowerShell:

```powershell
Get-Content .\SHA256SUMS | ForEach-Object {
    $expected, $name = $_ -split '\s+', 2
    $actual = (Get-FileHash (Join-Path .\wheelhouse $name) -Algorithm SHA256).Hash.ToLower()
    if ($actual -ne $expected) { throw "Checksum sai: $name" }
}
```

Dừng cài đặt nếu thiếu file, checksum sai hoặc tên wheel không đúng nền tảng dự kiến.

## 4. Cài không truy cập package index

```bash
python -m venv .venv
```

Kích hoạt môi trường rồi chạy:

```bash
python -m pip install --no-index --find-links=./wheelhouse vietclean==0.1.0
```

Nếu wheelhouse được tạo với extra `all` và cần các integration đó:

```bash
python -m pip install --no-index --find-links=./wheelhouse "vietclean[all]==0.1.0"
```

`--no-index` là kiểm soát quan trọng: pip chỉ dùng wheelhouse. Không dùng `--no-deps`
trừ khi bạn đã cài và xác minh dependency bằng quy trình khác.

## 5. Smoke test offline

```bash
vietclean --version
vietclean profiles
vietclean inspect examples/ecommerce_dirty.csv --profile ecommerce
```

Nếu chỉ chuyển wheelhouse mà không chuyển source/examples, tạo một CSV synthetic nhỏ.
Không dùng dữ liệu thật để smoke test. Có thể dùng firewall/network namespace của tổ
chức để xác nhận process không có outbound; tránh truyền database URI từ xa trong test.

## Internal package registry

Máy staging có thể tải từ registry nội bộ:

```bash
python -m pip wheel --index-url https://packages.example.invalid/simple \
  --wheel-dir wheelhouse ".[all]"
```

Thay URL ví dụ bằng registry thật và CA hợp lệ của tổ chức. Máy runtime air-gapped vẫn
nên cài bằng `--no-index` từ wheelhouse đã phê duyệt. Nếu máy runtime được phép truy cập
registry nội bộ, đó là mô hình restricted-network chứ không phải air gap; lưu lock và
checksum để tránh resolver thay đổi theo thời gian.

## Cập nhật

Không chép đè lẻ từng wheel. Tạo wheelhouse/manifest mới từ release đã review, kiểm thử
trên staging, sao lưu môi trường cũ và triển khai như một bộ. `pip-audit`, Dependabot và
CodeQL cần advisory/source trên mạng hoặc mirror; chúng chạy ở staging/CI, không cần chạy
trên máy xử lý dữ liệu production.

## Artifact của release chính thức

Workflow release tạo:

```text
vietclean-<version>-py3-none-any.whl
vietclean-<version>.tar.gz
requirements-linux-py312.lock
resolved-linux-py312.txt
vietclean.spdx.json
SHA256SUMS
```

`requirements-linux-py312.lock` được sinh từ wheelhouse đã resolve và mỗi package có
`--hash=sha256:...`; workflow chạy lại `pip download --require-hashes` trước khi publish.
Lock này chỉ đại diện Linux/Python 3.12. Windows, macOS, Python khác hoặc CPU khác phải tạo
wheelhouse/lock riêng theo các bước trên, không dùng nhầm lock chỉ vì wheel VietClean là
`py3-none-any`.

`vietclean.spdx.json` là SPDX 2.3 của môi trường runtime cô lập. `SHA256SUMS` bao phủ
wheel, sdist, lock, resolved list và SBOM. Luôn xác minh checksum trước khi chuyển artifact
sang máy offline; checksum không thay thế chữ ký/provenance hoặc sự tin cậy của staging.
