# Quảng cáo Fanpage tự động — cho Phần mềm Kế toán Đa công ty

Công cụ giới thiệu phần mềm [KE-TOAN](https://github.com/dothaihung92/KE-TOAN) tới dịch vụ kế toán
qua **Fanpage Facebook**, dùng **API chính thức của Meta**:

| Chức năng | Mô tả |
|---|---|
| 📝 **Đăng bài / hẹn giờ** | Mẫu bài sẵn cho từng tính năng (tải hóa đơn hàng loạt, tờ khai, MISA, đối chiếu ngân hàng…). Đăng ngay hoặc hẹn giờ lên Fanpage. |
| 💬 **Bình luận → nhắn riêng** | Ai bình luận “quan tâm”, “ib”, “báo giá”, hoặc để lại SĐT dưới bài Fanpage → bot tự nhắn riêng giới thiệu tính năng (Private Reply) và trả lời công khai “đã inbox”. |
| 🤖 **Chatbot Messenger** | Người nhắn tin cho Page nhận menu tính năng dạng nút bấm, chi tiết từng tính năng, báo giá, dùng thử. Bot tự nhận số điện thoại, chuyển tư vấn viên khi khách yêu cầu, và dừng khi khách gõ “stop / hủy”. |
| 👥 **Khách tiềm năng** | Mọi người đã tương tác được lưu lại: tên, SĐT, tính năng quan tâm, trạng thái (cần gọi lại / đã mua…). Xuất CSV. |
| 🧪 **Thử kịch bản** | Giả lập Messenger và bình luận ngay trên máy, không cần Facebook. |
| 📋 **Bài cho nhóm** | Sao chép bài để **tự tay** đăng vào nhóm cho phép quảng cáo. |

Giao diện tiếng Việt, chạy trên máy bạn, cùng kiểu với KE-TOAN (FastAPI + SQLite + 1 trang web).

## Vì sao KHÔNG có chức năng cào thành viên nhóm và tự nhắn tin?

Công cụ **cố ý không** thu thập thông tin thành viên nhóm và **không** nhắn tin cho người chưa từng
liên hệ Page, vì:

- **Luật Việt Nam**: thu thập, xử lý dữ liệu cá nhân khi chưa có sự đồng ý vi phạm Luật Bảo vệ dữ
  liệu cá nhân (hiệu lực từ 01/01/2026). Gửi tin quảng cáo cho người chưa đồng ý nhận cũng vi phạm quy
  định về quảng cáo và chống tin nhắn rác. Cả hai đều có thể bị xử phạt.
- **Facebook**: cào dữ liệu tự động và nhắn tin hàng loạt vi phạm điều khoản. Tài khoản bị khóa rất
  nhanh, và Fanpage/tên miền có thể bị đánh dấu spam, ảnh hưởng cả uy tín thương hiệu.
- **Hiệu quả**: kế toán nhận tin lạ thường chặn hoặc báo cáo. Người **tự bình luận / nhắn tin** mới là
  khách thật sự quan tâm.

Công cụ này chỉ trả lời người **đã chủ động** bình luận hoặc nhắn tin cho Fanpage. Đây là cách Meta cho
phép, và cũng là cách mang lại khách chất lượng hơn.

## Cách chạy

1. Cài Python 3.10+ (Windows: tick **“Add Python to PATH”**).
2. **Windows:** bấm đúp `start.bat`. **Mac/Linux:** `./start.sh`.
3. Trình duyệt mở `http://127.0.0.1:8787`, đăng nhập bằng tài khoản `admin` và mật khẩu
   `ADMIN_PASSWORD` trong `.env`. Nếu để trống, mật khẩu được tự sinh, in ra cửa sổ đen và lưu ở
   `data/.admin_password`.

Chưa khai báo Page ID/Token thì phần mềm chạy ở **chế độ thử**: mọi lệnh gửi lên Facebook chỉ được ghi
vào tab *Nhật ký*. Bạn có thể dùng tab *Thử kịch bản* để chỉnh nội dung trước.

## Kết nối Fanpage (làm 1 lần)

1. <https://developers.facebook.com> → *My Apps* → *Create App* → loại **Business**.
2. Thêm **Messenger** và **Webhooks**, kết nối Fanpage, tạo **Page Access Token** (nên dùng token dài
   hạn / System User token trong Meta Business Suite).
3. Quyền cần có: `pages_manage_posts`, `pages_read_engagement`, `pages_manage_engagement`,
   `pages_messaging`, `pages_show_list`. Quản trị viên Page dùng được ngay ở chế độ Development. Muốn
   bot trả lời **mọi người** thì app cần qua **App Review** và chuyển sang Live.
4. Sao chép `.env.example` thành `.env` và điền `FB_PAGE_ID`, `FB_PAGE_ACCESS_TOKEN`, `FB_APP_SECRET`,
   `FB_VERIFY_TOKEN` (tự đặt), `ADMIN_PASSWORD`.
5. Webhook cần địa chỉ **HTTPS công khai**. Có thể chạy trên VPS có tên miền, hoặc trên máy mình với
   `cloudflared tunnel --url http://localhost:8787`.
   - Callback URL: `https://<địa-chỉ>/webhook`
   - Verify token: giá trị `FB_VERIFY_TOKEN`
   - Đăng ký trường: `messages`, `messaging_postbacks`, `feed`
6. Khởi động lại phần mềm → tab *Tổng quan* → **Kiểm tra kết nối Fanpage**.

> Bảng điều khiển luôn yêu cầu mật khẩu, còn `/webhook` thì công khai nhưng được xác thực bằng chữ ký
> `X-Hub-Signature-256` từ `FB_APP_SECRET`. Khi mở tunnel ra Internet, nhớ đặt `ADMIN_PASSWORD` mạnh.

## Giới hạn của Meta cần biết

- **Private Reply**: mỗi bình luận chỉ được nhắn riêng **1 lần**, trong vòng **7 ngày**.
- **Messenger**: chỉ trả lời trong vòng **24 giờ** kể từ tin nhắn gần nhất của khách. Bot chỉ trả lời
  tin đến nên luôn nằm trong giới hạn này.
- **Nhóm**: Meta đã ngừng API đăng bài vào nhóm (2024). Hãy dùng nút *Sao chép để đăng nhóm*, chỉ đăng
  ở nhóm cho phép, và mời mọi người bình luận / nhắn tin ở Fanpage.

## Mẹo tăng khách (hợp lệ)

- Chạy **Facebook Ads** cho bài giới thiệu, nhắm sở thích “Kế toán”, “Dịch vụ kế toán”, “MISA”. Người
  bình luận dưới quảng cáo sẽ được bot nhắn riêng.
- Dùng quảng cáo mục tiêu **Tin nhắn (Click-to-Messenger)**: người bấm mở thẳng Messenger và bot trả
  lời ngay.
- Làm video ngắn quay màn hình, ví dụ “tải hóa đơn 20 công ty trong 3 phút”.
- Tham gia nhóm kế toán, trả lời câu hỏi chuyên môn và chỉ giới thiệu phần mềm khi phù hợp.

## Cấu trúc

```
app/server.py     # FastAPI: bảng điều khiển, API, webhook, lịch đăng bài
app/bot.py        # Xử lý bình luận & tin nhắn (từ khóa, SĐT, menu, chuyển tư vấn viên)
app/facebook.py   # Gọi Graph API + xác thực chữ ký webhook
app/content.py    # Tính năng KE-TOAN, kịch bản mặc định, mẫu bài đăng
app/db.py         # SQLite: bài đăng, khách tiềm năng, cài đặt, nhật ký
static/index.html # Giao diện
update.py         # Tự cập nhật phần mềm từ GitHub, chạy mỗi lần bấm start.bat
start.bat / run_server.bat / start.sh  # Chạy nhanh trên Windows / Mac-Linux
tests/            # pytest
data/             # CSDL (tự tạo — KHÔNG commit)
```

## Tự động cập nhật

Mỗi lần bấm `start.bat`, phần mềm tự kiểm tra và tải phiên bản mới nhất từ nhánh
`claude/facebook-auto-advertising-tool-ireuil` trên GitHub (chỉ tải file mã nguồn,
không đụng đến `.env` hay dữ liệu trong `data/`). Nếu không có mạng, phần mềm bỏ
qua bước này và chạy tiếp với bản đang có sẵn — không bao giờ bị treo vì thiếu mạng.

## Chạy test

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```
