# Văn bản tiếng Việt, Unicode và mojibake

VietClean xử lý văn bản theo hướng bảo toàn dữ liệu: chuẩn hóa dạng biểu diễn trước, chỉ
sửa lỗi encoding khi phép sửa có bằng chứng mạnh, rồi mới xử lý whitespace và missing.
Framework không bỏ dấu tiếng Việt, không dịch nội dung và không dùng AI.

## Unicode

Mặc định `unicode_form = "NFC"`. NFC ghép các dấu thanh đang ở dạng combining mark nhưng
không thay ký tự tương thích, phù hợp cho tên người, địa chỉ và mô tả tiếng Việt. `NFKC`
chỉ nên bật rõ ràng cho mã/search khi việc đồng nhất ký tự full-width hoặc ký tự tương
thích là mong muốn nghiệp vụ.

`remove_invisible_chars()` loại BOM, zero-width space, soft hyphen và control character
không mong muốn. Newline/tab được giữ để bước whitespace quyết định. ZWNJ/ZWJ được giữ
mặc định vì có ý nghĩa ở ngôn ngữ khác và emoji; chỉ bỏ bằng `remove_joiners = true` khi
dataset chắc chắn là văn bản Việt thuần.

## Sửa mojibake có kiểm soát

Các chuỗi như `Nguyá»…n` hoặc `PhÃ­` thường xuất hiện khi byte UTF-8 bị đọc nhầm như
CP1252/Latin-1. `analyze_mojibake()`:

1. giữ bản gốc;
2. tạo một tập candidate CP1252/Latin-1 hữu hạn, đảo ngược được;
3. chấm penalty cho marker mojibake/replacement character;
4. chỉ chọn candidate làm penalty giảm nghiêm ngặt;
5. chỉ áp dụng khi `confidence >= mojibake_confidence_threshold` (mặc định `0.90`);
6. trả `needs_review`/`unrepaired` khi không đủ chắc chắn.

Candidate có thể chứa PII nên low-level API trả chúng cho caller nhưng audit/report mặc
định chỉ ghi số lượng. Không đưa candidate thô vào log hoặc issue. Thuật toán bị giới hạn
số pass và idempotent với output đã chấp nhận.

Ví dụ Python:

```python
from vietclean.text import analyze_mojibake

decision = analyze_mojibake("Nguyá»…n VÄƒn A", confidence_threshold=0.90)
print(decision.value)
print(decision.changed, decision.needs_review)
```

## Whitespace và xuống dòng

Các mode mới:

| Mode | Hành vi |
|---|---|
| `preserve` | Giữ cấu trúc whitespace, chỉ chuẩn hóa newline cơ bản khi cần |
| `trim` | Chỉ bỏ whitespace đầu/cuối |
| `normalize_spaces` | Gộp space/tab nhưng giữ newline |
| `single_line` | Chuyển newline thành một space |
| `canonical_multiline` | Giữ paragraph, chuẩn hóa newline và bỏ dòng trống lặp |

Alias cũ `keep`, `space`, `remove` vẫn được hỗ trợ; config mới nên ưu tiên năm mode trên.
Địa chỉ/mô tả dùng `preserve`, `normalize_spaces` hoặc `canonical_multiline`; email, phone,
mã và tên ngắn có thể dùng `single_line` nếu rule nghiệp vụ yêu cầu.

## Encoding file và encoding nội dung

Encoding của CSV là cách byte được giải mã (`UTF-8`, BOM, UTF-16, CP1258...). Mojibake là
text đã bị giải mã sai từ trước. Chọn đúng `--encoding` xử lý lớp thứ nhất; sửa mojibake xử
lý một số trường hợp lớp thứ hai. Replacement character `�` thường cho biết byte gốc đã
mất, nên không phải lúc nào có thể phục hồi an toàn.

Luôn chạy `vietclean inspect` hoặc `dataclean profile` trước, thử trên bản sao, xem audit
và giữ nguyên giá trị bị gắn cờ nếu không có nguồn đối chiếu đáng tin cậy.
