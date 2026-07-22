# Ma trận truy vết `promt.md`

Tài liệu này ánh xạ 35 phần của đặc tả sang code, test và công việc vận hành. `Implemented`
nghĩa là có implementation/evidence trong repository, không tự động có nghĩa một GitHub
workflow đã chạy xanh. `External` là việc chỉ chủ repository có thể hoàn tất sau khi biết
GitHub account/URL. Kết quả gate cuối phải được ghi từ run thực tế, không suy đoán.

| # | Phạm vi trong prompt | Trạng thái | Evidence trong repository | Việc ngoài repository / giới hạn |
|---:|---|---|---|---|
| 1 | Vai trò và bài toán (`promt.md:3-42`) | Implemented | `README.md`, package `src/vietclean/` | Tên PyPI chỉ được xác nhận khi đăng ký thật |
| 2 | Mục tiêu sản phẩm (`46-79`) | Implemented | CLI `dataclean`/`vietclean`, API file-level, `docs/examples.md`, public repo `carrot1301/vietclean` | Tên PyPI chỉ được xác nhận khi đăng ký thật |
| 3 | Offline, nhẹ, secure default (`83-192`) | Implemented | `pyproject.toml`, `tests/test_security.py`, `docs/security.md` | Remote DB là opt-in và nằm ngoài air gap |
| 4 | CSV/Excel/SQL input (`196-303`) | Implemented | `io.py`, CLI `--all-sheets`, chunk mode, I/O/CLI/security tests | Driver `.xls`, Parquet và SQLAlchemy là optional theo môi trường |
| 5 | Pipeline và API (`306-375`) | Implemented | Pipeline độc lập, CLI và functional API `from dataclean import clean_file` | Chọn nhánh functional API được đặc tả cho phép thay vì fluent loader |
| 6 | Cấu trúc repository (`379-481`) | Implemented | `src/`, `tests/`, `.github/`, `configs/`, `docs/`, `examples/` | Module nhỏ được gộp theo quyền đơn giản hóa của prompt |
| 7 | Profiling (`485-532`) | Implemented | `inspection.py`, CLI `inspect/profile`, `tests/test_inspection.py` | Raw samples chỉ opt-in và có thể chứa PII |
| 8 | Missing (`536-598`) | Implemented | `config.py`, `text.py`, `pipeline.py`, `tests/test_pipeline.py` | Imputation phá hủy dữ liệu vẫn phải opt-in |
| 9 | Unicode/mojibake/whitespace (`601-696`) | Implemented | `text.py`, `tests/test_text.py`, `docs/vietnamese-text.md` | Replacement character có thể không phục hồi được |
| 10 | Tên cột (`700-732`) | Implemented | `pipeline.py`, mapping trong `report.py`, pipeline tests | Unnamed column không bị xóa chỉ vì tên |
| 11 | Kiểu dữ liệu (`736-816`) | Implemented | `text.py`, `pipeline.py`, `config.py`, text/pipeline tests | Giá trị mơ hồ được giữ/flag theo config |
| 12 | Duplicate (`820-848`) | Implemented | `pipeline.py`, `config.py`, pipeline tests | Fuzzy matching không thuộc core MVP |
| 13 | Outlier/anomaly (`852-876`) | Implemented | `pipeline.py`, `inspection.py`, `report.py`, pipeline/inspection tests | Chỉ report, không tự sửa số nghiệp vụ |
| 14 | Preset ngành (`880-1039`) | Implemented | `profiles.py`, `domain.py`, `configs/*.toml`, `tests/test_profiles.py` | Rule là mặc định chỉnh được, không thay validation doanh nghiệp |
| 15 | Config (`1043-1123`) | Implemented | `config.py`, `docs/configuration.md`, `tests/test_config.py` | Config chỉ là TOML/JSON data, không thực thi code |
| 16 | Audit/reproducibility (`1127-1179`) | Implemented | `report.py`, `artifacts.py`, bundle API/CLI, API/CLI/pipeline tests | Transformation deterministic; timestamp/run ID làm audit cố ý không byte-identical |
| 17 | Quality/exit code (`1183-1230`) | Implemented | `quality.py`, `tests/test_quality.py`, CLI exit mapping | Threshold nghiệp vụ phải được cấu hình rõ |
| 18 | Export an toàn (`1234-1283`) | Implemented | Formula modes, atomic writer, `--output-root`, secure mode, traversal/symlink tests | OS attacker đổi path đồng thời vẫn cần sandbox/quyền thư mục ở môi trường multi-tenant |
| 19 | Resource protection (`1287-1306`) | Implemented | `security/resources.py`, chunk CLI/API, memory/ZIP/reject limits, timeout/cancellation tests | Là application guard, không thay OS CPU/RAM quota |
| 20 | Repository security (`1310-1430`) | Implemented / CI enforcement pending | Security docs/workflows; vulnerability alerts, Dependabot security updates, PVR, secret scanning/push protection và baseline `main` protection đã bật | Required CI checks chờ GitHub Billing cấp runner |
| 21 | Testing/coverage (`1434-1509`) | Implemented; local gates pass | 311 pass, 2 platform skips; total 89.84%, core 90.56%; gates trong `ci.yml` | GitHub runner chưa khởi chạy do account bị khóa bởi billing; symlink tests skip khi Windows không cấp quyền tạo link |
| 22 | Documentation/offline install (`1513-1565`) | Implemented | `README.md`, `docs/offline-installation.md`, `docs/examples.md` | Wheelhouse phải tạo đúng OS/CPU/Python đích |
| 23 | API usability (`1569-1620`) | Implemented | Public helpers trong `__init__.py`, pure functions và type hints/tests | Không monkey-patch pandas |
| 24 | Error handling (`1624-1660`) | Implemented | `exceptions.py`, CLI `--debug` và exit mapping, CLI tests | Driver exception trong API phải được caller xử lý/redact |
| 25 | Logging (`1664-1702`) | Implemented | `logging_utils.py`, CLI flags/integration tests, `tests/test_logging.py`, `docs/logging.md` | Handler do ứng dụng ngoài thêm phải dùng redaction tương đương |
| 26 | Performance/benchmark (`1706-1728`) | Implemented; run optional | Bounded profiling/resource checks, `read_chunks`, `benchmarks/benchmark.py` | Benchmark lớn không phải CI gate; lưu môi trường/kết quả riêng khi chạy |
| 27 | Compatibility (`1732-1761`) | Local verification / External blocked | Python 3.11–3.13 matrix; Windows/macOS smoke job; UTF-8/UTF-8 BOM tests | GitHub-hosted jobs chưa được cấp runner vì account bị khóa bởi billing |
| 28 | License/governance (`1765-1790`) | Implemented | MIT, governance docs/templates, release gate; GitHub xác nhận CODEOWNERS không lỗi; `main` cấm force-push/xóa branch | Required checks sẽ bật sau khi hosted CI chạy được |
| 29 | Điều cấm (`1794-1821`) | Implemented | Không web UI/AI/eval/exec/pickle/config plugin; security tests | Review dependency mới trước merge |
| 30 | Definition of Done (`1825-1872`) | Implemented locally / External verification | Package/CLI/API/tests/docs; local quality, security, build và governance gates pass | Cần CI run xanh, CodeQL/dependency review và GitHub settings thật |
| 31 | Kế hoạch phase (`1876-1950`) | Implemented theo module | CHANGELOG, architecture, I/O, cleaners, report, profiles, hardening | Release gate tạo SBOM/checksum/hashed platform lock |
| 32 | Cách tạo repository (`1954-2004`) | Implemented | Public repository `https://github.com/carrot1301/vietclean`, nhánh `main`, docs lệnh và matrix này | GitHub Billing phải được mở khóa để workflow nhận runner |
| 33 | Quy tắc quyết định (`2008-2025`) | Implemented | Safe defaults trong config/I/O/pipeline, threat model | Destructive option tiếp tục cần explicit opt-in |
| 34 | Nguồn tham khảo (`2029-2044`) | Implemented | Code gốc MIT; dependency/license gate; không vendor code tham khảo | Maintainer review attribution nếu thêm code ngoài |
| 35 | Kết quả cuối (`2048-2080`) | Implemented and public | CLI/API default bundle: cleaned, quality JSON/HTML, audit, mapping, rejects, summary; E2E tests; public clone URL | Hosted CI/release còn phụ thuộc trạng thái GitHub Billing |

## Trạng thái release và GitHub settings

Đã cấu hình trực tiếp trên public repository:

1. GitHub nhận diện `@carrot1301` trong `.github/CODEOWNERS` và báo không có lỗi;
2. vulnerability alerts, Dependabot security updates và dependency graph;
3. Private Vulnerability Reporting, secret scanning và push protection;
4. baseline protection cho `main`: linear history, cấm force-push/xóa branch và yêu cầu
   giải quyết hội thoại trước merge.

Còn phải mở khóa GitHub Billing, rerun CI/CodeQL/dependency review, rồi thêm các check xanh
đó vào required status checks. Release environment/reviewer là tùy chính sách tài khoản.

`tools/check_release_governance.py` xác minh tag/version và yêu cầu CODEOWNERS thật trước release.
Workflow release pin action theo full SHA, dùng quyền `contents: write` chỉ ở job publish,
tạo wheel/sdist, platform lock có SHA-256, SPDX SBOM và `SHA256SUMS`. Lock release hiện gắn
với Linux/Python 3.12; wheelhouse air-gapped cho nền tảng khác phải được resolve/checksum
theo `offline-installation.md`.

## Bằng chứng kiểm tra local ngày 2026-07-22

Chạy trong virtual environment mới trên Windows, Python 3.13.12 và dependency resolve tại
thời điểm kiểm tra:

| Gate | Kết quả local |
|---|---|
| Pytest, coi `ResourceWarning` là lỗi | PASS — 311 passed, 2 skipped do Windows không cấp quyền tạo symlink |
| Coverage toàn package | PASS — 89.84% (yêu cầu ≥85%) |
| Coverage cleaning/security core | PASS — 90.56% (yêu cầu ≥90%) |
| Ruff (`src`, `tests`, `tools`, `benchmarks`) | PASS |
| Mypy (`src/vietclean`, `src/dataclean`) | PASS — 26 source files |
| Bandit mức High | PASS |
| `pip-audit --strict` trên dependency freeze không gồm editable project | PASS — không thấy vulnerability đã biết |
| Runtime dependency license audit và `pip check` | PASS |
| Build wheel/sdist và kiểm tra member archive | PASS |
| Cài wheel vào môi trường tách biệt, import public API và chạy CLI | PASS |
| E2E Excel F&B (`dataclean clean ... --preset fnb`) và bundle 7 artifacts | PASS |
| Parse bốn workflow YAML + full-SHA action test | PASS |
| Release governance (`v0.1.0`) | PASS — CODEOWNER `@carrot1301` |
| GitHub repository security settings | PASS — alerts, security updates, PVR, secret scanning/push protection và baseline branch protection |

Con số trên là snapshot local, không thay thế GitHub run URL hoặc việc audit lại dependency
tại thời điểm release.

Public repository: `https://github.com/carrot1301/vietclean`. Lần push đầu đã tạo CI và
CodeQL run, nhưng GitHub không cấp runner và trả annotation: account bị khóa do billing.
Đây là trạng thái tài khoản bên ngoài source; workflow chưa chạy bất kỳ step nào.

## Gate bên ngoài còn phải ghi sau cùng

Maintainer chỉ đổi các trạng thái `External`/`Verification pending` sau khi lưu được bằng
chứng thực tế cho:

```text
Mở khóa GitHub Billing và rerun Actions trên Ubuntu, Windows và macOS
CodeQL + dependency review
release dry run/checksum/SBOM/hashed lock
```
