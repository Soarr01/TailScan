# TailScan

Ứng dụng quét tài liệu cho iPhone, xử lý ảnh và OCR trên máy chủ của bạn qua Tailscale.

[Kết quả thí nghiệm model, phương pháp đo và ảnh kiểm thử tổng hợp](experiments/README.md).

## Chức năng

- Chụp / nhập nhiều trang, tự gợi ý góc giấy, chỉnh góc và xoay trang.
- Làm phẳng giấy cong bằng UVDoc khi cần.
- Sáu bộ lọc: DocRes, DocShadow, trắng giấy, màu, ảnh gốc và đen trắng.
- Sau khi chuẩn bị xong, chạm bộ lọc để xem ngay từ ảnh đã lưu sẵn.
- OCR PaddleOCR-VL-1.6, xuất PDF có thể tìm kiếm chữ.
- Thư viện tài liệu lưu lâu dài trên server, tìm kiếm, đổi tên và chỉnh tiếp.
- Model GPU tự tải khi cần và tự nhả sau 5 phút rảnh.

## Sử dụng

1. [Cài server](docs/SELF_HOSTING.md) trên Linux có GPU NVIDIA.
2. Kết nối iPhone và server qua Tailscale.
3. Tải IPA từ [Releases](https://github.com/Soarr01/TailScan/releases), ký và cài
   bằng công cụ sideload của bạn. Hoặc dùng giao diện trình duyệt.
4. Mở app, nhập địa chỉ server riêng của bạn, rồi bắt đầu quét.

App yêu cầu iOS 16+. Model không chạy trên iPhone; server cần hoạt động khi xử lý
trang mới. Thư viện được lưu trên server, không phải thư viện ngoại tuyến trên iPhone.
Ảnh, PDF và cấu hình máy cá nhân không được đưa vào repo này.

Mã TailScan dùng giấy phép [MIT](LICENSE). Các model và mã bên thứ ba giữ giấy phép
riêng; xem [NOTICE.md](NOTICE.md). [Hướng dẫn build iPhone](docs/IOS.md).
