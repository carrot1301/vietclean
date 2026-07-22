# Chính sách bảo mật

VietClean được thiết kế theo các thực hành phát triển phần mềm an toàn. Câu này không
phải là chứng nhận ISO 27001, SOC 2, PCI DSS hay kết quả kiểm toán độc lập.

## Phiên bản được hỗ trợ

| Dòng phiên bản | Nhận bản vá bảo mật |
|---|---|
| `0.1.x` | Có, trong thời gian đây là dòng phát hành hiện tại |
| `< 0.1` | Không |
| Nhánh phát triển chưa phát hành | Chỉ hỗ trợ theo khả năng, không dùng cho production |

Khi có dòng phát hành mới, maintainers có thể kết thúc hỗ trợ dòng cũ và sẽ cập nhật
bảng này. VietClean đang ở giai đoạn alpha; người dùng cần kiểm thử trên bản sao dữ liệu
trước khi đưa vào quy trình quan trọng.

## Báo cáo lỗ hổng riêng tư

Không mở public issue cho lỗ hổng bảo mật.

1. Trên trang GitHub của repository, mở **Security → Advisories → Report a
   vulnerability** để tạo báo cáo riêng tư. Chủ repository phải bật GitHub Private
   Vulnerability Reporting trước khi phát hành công khai.
2. Nếu nút trên chưa có, liên hệ riêng với chủ repository qua kênh được công bố trên
   hồ sơ GitHub của họ. Không đăng chi tiết khai thác trong issue, discussion hoặc pull
   request công khai.
3. Chỉ dùng dữ liệu tổng hợp hoặc dữ liệu giả lập. Không gửi file khách hàng, database
   thật, credential, connection string, email, số điện thoại, số tài khoản hoặc địa chỉ.

Báo cáo hữu ích nên có:

- phiên bản VietClean, Python, hệ điều hành và định dạng input;
- mô tả tác động và điều kiện cần để tái hiện;
- ví dụ tối thiểu bằng dữ liệu tổng hợp;
- các bước tái hiện, kết quả thực tế và kết quả mong đợi;
- đề xuất khắc phục nếu có và thời điểm disclosure mong muốn.

Không cần chứng minh tác động bằng cách truy cập dữ liệu không thuộc quyền sở hữu của
bạn. Không chạy thử nghiệm gây gián đoạn trên hệ thống production.

## Mục tiêu phản hồi và disclosure

Đây là mục tiêu theo khả năng, không phải SLA:

- xác nhận đã nhận trong 3 ngày làm việc;
- phân loại ban đầu trong 7 ngày làm việc;
- cập nhật trạng thái ít nhất mỗi 14 ngày khi việc xử lý còn tiếp diễn;
- phối hợp ngày công bố sau khi có bản vá hoặc biện pháp giảm thiểu hợp lý.

Maintainers sẽ xác minh, đánh giá phạm vi, chuẩn bị test hồi quy, phát hành bản vá theo
Semantic Versioning và ghi nhận người báo cáo nếu họ đồng ý. Có thể công bố sớm hơn khi
lỗ hổng đang bị khai thác hoặc cần cảnh báo người dùng khẩn cấp.

## Phạm vi

Trong phạm vi:

- đọc/ghi CSV, Excel, SQLite và database URI do người dùng chỉ định;
- parsing, cleaning, reporting và CLI của VietClean;
- formula injection, ghi đè input, rò rỉ PII/credential, SQL injection;
- vượt giới hạn tài nguyên, file Excel/ZIP độc hại và config độc hại;
- dependency hoặc quy trình build khi tạo ra tác động trực tiếp tới người dùng VietClean.

Ngoài phạm vi nhưng vẫn có thể báo để được định tuyến:

- lỗi chỉ tồn tại trong pandas, OpenPyXL, Python hoặc database driver mà VietClean không
  làm tăng tác động;
- cấu hình quyền database sai do người vận hành;
- tấn công cần quyền ghi tùy ý lên máy của người dùng từ trước;
- vấn đề availability của GitHub hoặc package registry.

## Nếu đã vô tình đăng dữ liệu nhạy cảm

Xóa issue/comment/attachment ngay, nhưng không giả định thao tác sửa nội dung đã xóa mọi
bản sao khỏi lịch sử hoặc notification. Hãy xoay vòng credential bị lộ, thông báo chủ dữ
liệu, liên hệ maintainers và GitHub Support qua kênh riêng khi cần purge. Không tiếp tục
đính kèm dữ liệu thật trong báo cáo thay thế.

Mô hình đe dọa chi tiết nằm tại [docs/threat-model.md](docs/threat-model.md); hướng dẫn
vận hành an toàn nằm tại [docs/security.md](docs/security.md).
