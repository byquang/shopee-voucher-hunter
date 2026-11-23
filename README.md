# Shopee Voucher Hunter Việt Nam

Bot Python miễn phí theo dõi [mã giảm giá Shopee Việt Nam](https://magiamgia.com/shopee/)
và gửi mã hoặc link lưu voucher mới qua Telegram. Không cần tài khoản Shopee,
Gemini hay máy chủ riêng; bot không tự lưu voucher hoặc mua hàng.

## Bật thông báo

1. Mở chat với bot Telegram và bấm **Start**. Bạn có thể dùng lại bot và chat ID
   của AI Discount Hunter; nếu dùng nhóm hoặc kênh, cấp quyền gửi tin cho bot.
2. Thêm `TELEGRAM_BOT_TOKEN` và `TELEGRAM_CHAT_ID` trong
   [GitHub Actions secrets](https://github.com/byquang/shopee-voucher-hunter/settings/secrets/actions).
   Không dán giá trị vào code hoặc workflow.
3. Vào [Shopee Voucher Hunter](https://github.com/byquang/shopee-voucher-hunter/actions/workflows/hunt.yml)
   → **Run workflow** → `test-telegram` để nhận một bản xem trước tin nhắn.
   Mã trong bản xem trước chỉ dùng để minh họa.
   Sau đó chọn `hunt` để săn ngay, hoặc chờ lịch. Chọn `preview` nếu chỉ muốn
   xem kết quả trong log, không gửi tin và không cần secret.

## Cách hoạt động

- GitHub Actions chạy vào phút 07 và 37 mỗi giờ; GitHub có thể chạy trễ hoặc bỏ
  qua lượt. Trên repo công khai, GitHub có thể tắt lịch sau 60 ngày không hoạt
  động; vào **Actions** để bật lại nếu cần.
- Bot chỉ đọc mục của ngày hiện tại (giờ Việt Nam) trên Mã Giảm Giá. Mỗi lượt
  gửi tối đa 10 voucher mới; nếu không có mục mới, bot không gửi tin.
- Bot kiểm tra lịch nhắc ở phút 25 và 55 mỗi giờ, để nhắc trước tối đa 5 phút
  cho các mốc mở voucher vào đầu giờ hoặc giữa giờ được nguồn ghi rõ. Nhắc mốc
  00:00 chỉ khi nguồn đã đăng danh sách ngày mới. Nếu GitHub chạy trễ qua
  giờ mở hoặc nguồn chưa đăng giờ, bot không gửi nhắc. Không tự lưu voucher.
- Mỗi voucher chỉ được nhắc một lần cho mỗi giờ mở; lịch sử nhắc được lưu riêng
  trong `reminders.json`. Có thể chạy `reminders` thủ công để kiểm tra giờ sắp mở.
- Bot ghi ngày và mã băm của voucher vào `seen.json` trên nhánh mặc định sau khi
  Telegram xác nhận. Workflow cần quyền ghi vào nhánh để lưu lịch sử. Voucher
  được đăng lại ngày hôm sau có thể được gửi lại; lỗi lưu lịch sử sau khi gửi có
  thể gây gửi trùng.
- Nguồn không phải Shopee chính thức và không bao phủ mọi voucher. Lượt dùng, giờ
  mở và điều kiện tài khoản có thể thay đổi; xác nhận trong ứng dụng Shopee.

## Chạy thử trên máy

Yêu cầu Python 3.10 trở lên.

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python hunter.py --dry-run
```
