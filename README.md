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
3. Trình duyệt mở `http://127.0.0.1:8787` — mặc định **không cần đăng nhập** (chỉ chạy trên máy bạn).

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
   `FB_VERIFY_TOKEN` (tự đặt).
5. Webhook cần địa chỉ **HTTPS công khai**. Có thể chạy trên VPS có tên miền, hoặc trên máy mình với
   `cloudflared tunnel --url http://localhost:8787`.
   - Callback URL: `https://<địa-chỉ>/webhook`
   - Verify token: giá trị `FB_VERIFY_TOKEN`
   - Đăng ký trường: `messages`, `messaging_postbacks`, `feed`
6. Khởi động lại phần mềm → tab *Tổng quan* → **Kiểm tra kết nối Fanpage**.

> Mặc định bảng điều khiển không cần đăng nhập (chỉ nghe ở `127.0.0.1`, không ai ngoài máy bạn vào
> được). `/webhook` thì công khai nhưng được xác thực bằng chữ ký `X-Hub-Signature-256` từ
> `FB_APP_SECRET`. **Nếu mở tunnel ra Internet** (để cấu hình webhook), người khác cũng gõ được đúng
> địa chỉ tunnel để mở bảng điều khiển — khi đó nên bật lại mật khẩu bằng cách thêm vào `.env`:
> ```
> DASHBOARD_LOGIN=true
> ADMIN_PASSWORD=matkhaucuaban
> ```

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
app/newsagent.py  # Agent tin tức: dò bài thuế/kế toán, AI viết lại, đăng web + Fanpage
app/video.py      # Tạo clip ngắn từ bài viết (kịch bản AI, giọng đọc, phụ đề, FFmpeg)
static/index.html # Giao diện
static/seo-writer.html, static/qc-bridge.js  # Công cụ viết bài SEO + nút đẩy bài sang Fanpage
update.py         # Tự cập nhật phần mềm từ GitHub, chạy mỗi lần bấm start.bat
start.bat / run_server.bat / start.sh  # Chạy nhanh trên Windows / Mac-Linux
tests/            # pytest
data/             # CSDL (tự tạo — KHÔNG commit)
```

## Bình luận, thống kê, đăng nhóm

| Tab | Làm được gì | Cần gì |
|---|---|---|
| **Bình luận** | Mọi bình luận trên bài Fanpage hiện ở đây (tự về qua webhook; nút *Đồng bộ* kéo bù khi máy/tunnel từng tắt). Trả lời công khai, nhắn riêng, bỏ qua. Số đỏ trên menu + thông báo trình duyệt khi có bình luận mới. | Trả lời công khai cần quyền `pages_manage_engagement`; đọc nội dung khi *Đồng bộ* cần `pages_read_user_content` (webhook không cần) |
| **Bình luận — nâng cấp** | 🆕 Bình luận mới có nhãn **MỚI** và số đỏ trên menu cho tới khi bạn mở xem. Mỗi bình luận ghi rõ **bài nào, Fanpage nào**. Bấm vào một bình luận → khung bên phải hiện **toàn bộ bình luận của bài đó như trên Facebook** (kèm các câu trả lời, kể cả của Fanpage) và trả lời ngay trong đó. | — |
| **Trả lời tự động** (đầu tab Bình luận) | Đặt quy tắc *từ khóa → câu trả lời công khai + tin nhắn riêng*; quy tắc đầu tiên khớp sẽ trả lời **ngay dưới bình luận trên Facebook**. Có câu trả lời mặc định, mỗi người chỉ 1 lần/bài, giới hạn/ngày, và ô **Thử** để xem trước. Không khớp thì để bạn trả lời tay. | Trả lời công khai cần `pages_manage_engagement`; phần mềm tự kiểm tra và báo thiếu quyền ở đầu tab |
| **Thống kê** | Lượt thích, bình luận, chia sẻ, lượt xem của từng bài + tổng, bấm tiêu đề cột để sắp xếp. | Lượt xem cần quyền `read_insights`; thiếu thì hiện "—" |
| **Đăng nhóm** | Hẹn giờ nhắc đăng nhiều nhóm: đến giờ phần mềm báo, mở sẵn nhóm, chép sẵn nội dung; bạn dán, bấm đăng, rồi bấm *✓ Đã đăng*. | Mở sẵn trang phần mềm để nhận nhắc |

### 🤖 Tự động đăng nhóm bằng trình duyệt (thử nghiệm, có rủi ro)

Trong tab **Đăng nhóm** có khung 🤖: phần mềm mở **Microsoft Edge/Chrome thật** trên máy, vào từng nhóm và đăng như người dùng.

1. Bấm **Cài đặt trình điều khiển** (1 lần, tự `pip install playwright`) — không cần tải thêm trình duyệt.
2. Bấm **Đăng nhập Facebook (1 lần)** → đăng nhập tay trong cửa sổ hiện ra (có thể có mã xác thực 2 bước). Phần mềm **không lưu mật khẩu**;
   phiên đăng nhập nằm trong `data/browser-profile`, các lần sau tự dùng lại.
3. Từ đây trình duyệt **chạy ẩn** (không hiện cửa sổ) — chỉ lúc đăng nhập/xác minh mới hiện. Muốn xem trực tiếp thì tick
   *"Hiện cửa sổ trình duyệt khi đăng"*.
4. Tick *"Tôi hiểu và chấp nhận rủi ro"*, rồi bấm **🤖 Tự đăng các nhóm còn lại** ở một lịch, hoặc tick
   *"Đến giờ tự đăng bằng trình duyệt"* khi hẹn giờ (máy phải bật, phần mềm đang chạy, đừng khóa màn hình).

Bảo vệ tài khoản: tối đa `GROUPBOT_DAILY_LIMIT` bài/ngày (mặc định 15), nghỉ `GROUPBOT_DELAY_MIN`–`MAX` giây (60–150) giữa các nhóm.
Gặp chỗ lạ (Facebook đòi đăng nhập lại, không thấy ô viết bài, hộp soạn không đóng...) phần mềm **dừng** và chụp ảnh vào
`data/groupbot-errors`; ở chế độ hiện cửa sổ thì còn **giữ cửa sổ mở** để bạn tự đăng nốt. Nhóm nào đã đăng xong được đánh dấu ✅, nhóm lỗi để ⭕.
Facebook đòi xác minh → bấm *Đăng nhập lại Facebook* (cửa sổ đăng nhập luôn hiện).
Nhóm bật duyệt bài thì ghi nhận "đang chờ quản trị viên duyệt".

> ⚠️ Việc này **trái điều khoản Facebook** và có thể khiến tài khoản bị xác minh hoặc khóa. Chỉ đăng ở nhóm cho phép quảng cáo.
> Logic đã được thử trên trang giả lập; chưa có bảo đảm với giao diện Facebook thật (Facebook đổi giao diện thường xuyên).
> Nếu lần đầu thấy báo "không thấy ô viết bài" dù nhóm đăng được, hãy gửi ảnh trong `data/groupbot-errors` để chỉnh lại.

**Vì sao nhóm không tự động hoàn toàn?** Facebook đã khóa API đăng bài và đọc bình luận trong group (2024), nên chỉ còn cách nhắc giờ hoặc điều khiển
trình duyệt như trên. Bài đăng trong nhóm **không có** thống kê/bình luận trên phần mềm — chỉ Fanpage mới có.

## Viết bài bằng AI

- **✍️ Viết bài SEO** (nút trên thanh menu, mở `/seo-writer`): công cụ SEO Article Writer dùng Gemini. Ở tab *Tin tức AI*, nút **✍️ SEO bài viết** chuyển bài tin sang đây, tự điền form (từ khóa, văn bản pháp luật, nội dung nguồn) và tự bấm tạo bài chuẩn SEO (cần Gemini key đã nhập ở tab này).
- **📌 SEO bài viết bám sát bài gốc**: bài gửi từ Tin tức AI được viết lại KHÔNG dùng Google Search / Nghiên cứu sâu, giữ đủ tình huống, số liệu, số hiệu văn bản và kết luận của bài gốc; viết xong phần mềm đối chiếu (số tiền, tỷ lệ, số hiệu, ngày, năm) — có thông tin lạ hoặc thiếu số liệu thì AI tự sửa lại và hiện thẻ "Đối chiếu với bài gốc". Mục lục "Nội dung chính" mặc định tắt (tránh trùng plugin mục lục của web).
- **✨ AI viết bài đăng nhóm + ảnh đính kèm** (tab Đăng nhóm): điền nội dung vào khung, tick các nhóm, bấm "✨ AI viết bài & đăng lên nhóm" — AI viết lại mỗi nhóm một bài khác nhau (giữ đúng ý / thông tin của bạn, kiểm tra độ giống nhau), kèm ảnh bạn chọn từ máy (tối đa 10 ảnh, tải lên cùng bài ở mỗi nhóm), rồi tự đăng bằng trình duyệt, nhóm đông thành viên nhất trước. Có nút "xem trước, chưa đăng" để duyệt / sửa từng bài trước khi đăng. Điền link thì link được bình luận dưới bài. Ô "Link kèm theo": mặc định **gắn thẳng vào cuối bài viết** (có thể đổi sang bình luận dưới bài); ô "Hướng viết của AI" mặc định **kêu gọi tải & dùng thử phần mềm** (hoặc giới thiệu dịch vụ / chia sẻ kiến thức).
- **📣 Đăng nhóm từ bài SEO**: đăng bài web (Live) ở tab Viết bài SEO xong, phần mềm tự tạo lịch ở tab Đăng nhóm — AI viết lại **mỗi nhóm một nội dung khác nhau** (khác mở bài, bố cục, câu chữ; kiểm tra độ giống nhau) nhưng cùng trọng tâm bài SEO, link bài gắn cuối. Mỗi nhóm hiện trạng thái: ✅ lên bài ngay / ⏳ chờ duyệt / ✔ đã duyệt / ⛔ bị từ chối / 🚫 không cho đăng (tự nhận biết khi đăng bằng trình duyệt, nút "🔍 Kiểm tra duyệt bài", hoặc đánh dấu tay). Lưu số thành viên (tự đọc hoặc nhập tay) — **nhóm đông nhất được đăng trước**. Bài đăng nhóm viết **ngắn gọn (tối đa ~4 dòng, nêu ý chính)**; **link bài viết KHÔNG nằm trong bài mà được bình luận ngay dưới bài** sau khi đăng (nhóm chờ duyệt thì bình luận sau khi được duyệt; có nút "💬 Bình luận link các nhóm đã đăng", "💬 Copy link" và ô đánh dấu đã bình luận).
- **🔗 Internal Links SEO**: chọn bài cũ liên quan theo nội dung (không cần trùng nguyên văn từ khóa), kiểm tra link còn mở được rồi nhờ AI chọn cụm từ có sẵn trong bài để gắn (tối đa 3 link; không có chỗ hợp lý thì thêm khung "Đọc thêm"). Danh sách bài đã đăng lưu cả trên máy chủ QC. Trạng thái **Nháp** chỉ lưu nháp (không công khai, không dùng làm link nội bộ cho đến khi xuất bản); **Live** phải xác nhận trước khi đăng công khai. Độ dài mặc định ~800–1000 từ.
- **🚀 Đăng WordPress chuẩn SEO (Rank Math/Yoast)**: permalink ngắn có từ khóa (đếm cả tên miền, ≤ 75 ký tự); từ khóa ở đầu bài và thẻ H2; mục lục + id cho H2; ảnh tải lên WordPress với tên file có từ khóa và alt / title / chú thích / mô tả rõ ràng; gắn thẻ (tags) và chuyên mục; trạng thái Nháp/Live đúng như đã chọn; gửi tiêu đề SEO (≤ 60 ký tự), mô tả, từ khóa chính vào Rank Math; thẻ "Kiểm tra kiểu Rank Math" trước khi đăng.
- **🔌 Kết nối WordPress (tab Viết bài SEO)**: yêu cầu tới website đi qua máy chủ QC (`/api/wp-proxy`) nên không còn lỗi CORS "Failed to fetch"; URL tự bỏ `/wp-admin`; lỗi đăng nhập có gợi ý tiếng Việt. Hướng dẫn tạo Mật khẩu ứng dụng ở nút "Lấy ở đâu?".
- **✏️ Tiêu đề SEO trọn câu, đúng từ khóa (tab Viết bài SEO)**: không còn cắt cụt tiêu đề ở 70 ký tự; tiêu đề dài, thiếu từ khóa hoặc bỏ lửng thì AI viết lại (45-65 ký tự, chứa nguyên văn từ khóa, ưu tiên đặt đầu); meta description cũng phải chứa từ khóa và trọn câu. Giữ nguyên số hiệu văn bản (398/2026/NĐ-CP). Bài chuyển từ Tin tức AI được đặt từ khóa ngắn (2-6 từ) thay vì cả tiêu đề bài tin.
- **🖼 Ảnh khớp nội dung (tab Viết bài SEO)**: AI đọc từng đoạn và đặt từ khóa ảnh tiếng Anh cụ thể; phần mềm chấm điểm mô tả ảnh Pexels/Pixabay với từ khóa, loại ảnh du lịch/phong cảnh/món ăn; không có ảnh khớp (hoặc chưa nhập key ảnh) thì tạo ảnh bìa có tiêu đề đoạn thay vì ảnh ngẫu nhiên. Bài chuyển từ Tin tức AI dùng ảnh của bài tin làm ảnh đầu. Nút "Tìm ảnh mới" lấy ảnh khớp tiếp theo.
- **🔎 Tự gắn link văn bản pháp luật**: bài Tin tức AI và bài ở tab Viết bài SEO (chế độ "Tự tìm & gắn link THẬT") được tự tìm các Nghị định / Thông tư / Luật / Công văn có số hiệu trong bài trên thuvienphapluat.vn, vanban.chinhphu.vn, luatvietnam.vn…; phần mềm mở thử từng link (đúng số hiệu, không 404) rồi mới gắn vào lần nhắc đầu tiên. Bài web có thêm mục "Văn bản pháp luật liên quan", bài Facebook có dòng "📄 Xem văn bản gốc". Không tìm được link chắc chắn thì giữ nguyên tên văn bản. Phần mềm **không bao giờ dùng link do AI tự viết**: mọi link tới trang luật mà phần mềm chưa kiểm tra đều bị gỡ (giữ chữ); chỉ nhận trang văn bản của cơ sở dữ liệu pháp luật (không nhận bài báo nhắc tới văn bản) và văn bản đầu tiên trong tiêu đề trang phải đúng số hiệu.
  Viết xong, trong khung "Đăng lên Facebook" có thêm 2 nút **💾 Lưu nháp vào QC** và
  **📤 Đăng ngay lên Fanpage** — bài được đưa thẳng vào tab *Bài đăng* (kèm link bài viết).
  Thay `static/seo-writer.html` bằng bản mới hơn vẫn giữ 2 nút này (máy chủ tự chèn `qc-bridge.js`).
- **✨ Viết lại từ bài nguồn** (tab *Bài đăng*): dán nội dung + link bài hay trong group/page khác,
  AI viết lại thành bài mới của Fanpage và ghi "📌 Nguồn tham khảo: <link>" ở cuối.
  Phần mềm **không tự vào group lấy bài** (Facebook không cho phép, dễ bị khóa tài khoản) — bạn chọn bài, AI viết.

Cả hai dùng chung một Gemini API key (lấy miễn phí tại <https://aistudio.google.com/apikey>),
nhập một lần là dùng được ở cả hai nơi.

## Lên lịch & tăng tương tác (ý tưởng từ Postiz)

Lấy ý tưởng từ [Postiz](https://github.com/gitroomhq/postiz-app) (công cụ lên lịch mạng xã hội mã nguồn mở,
giấy phép AGPL — chỉ học ý tưởng, mã viết lại riêng cho phần mềm này):

- **⏰ Khung giờ vàng + hàng đợi**: đặt các giờ đăng (vd 07:30, 11:45, 20:00), bấm **➕ Thêm vào hàng đợi**
  là bài tự xếp vào giờ còn trống gần nhất. Agent tin tức cũng xếp bài Fanpage vào giờ vàng (tắt được).
- **📅 Lịch tuần**: xem bài đã đăng / đã hẹn theo từng ngày, thấy luôn giờ vàng còn trống.
- **💬 Bình luận đầu tiên**: Fanpage tự bình luận ngay dưới bài vừa đăng (hay dùng để đặt link).
- **🔁 Đăng lặp lại** mỗi 7 / 14 / 30 ngày.
- **🔥 Tự bình luận khi bài hot**: bài đạt N lượt cảm xúc thì Fanpage tự bình luận thêm 1 lần
  (người đã tương tác nhận thông báo). Kiểm tra mỗi 30 phút trong 7 ngày sau khi đăng.
- **🖼 Nhiều ảnh trong 1 bài** (tối đa 10, mỗi dòng 1 link) và **tải ảnh từ máy** (lưu ở `data/media`).
- **✍ Chữ ký**: đoạn hotline / hashtag hay dùng, 1 chữ ký có thể tự gắn cuối mọi bài.
- **👁 Xem trước** bài giống trên Facebook khi đang soạn.

## Tạo clip từ bài viết (tab 🎬 Tạo clip)

Làm theo quy trình của [MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo) nhưng gọn hơn:
Gemini viết kịch bản theo cảnh → giọng đọc tiếng Việt miễn phí (Edge-TTS, cần Internet) →
ảnh nền (ảnh của bài, ảnh miễn phí Pexels nếu có key, hoặc nền màu thương hiệu) →
chữ lớn + phụ đề → FFmpeg ghép thành video dọc 9:16 (hoặc ngang 16:9).

- **🎙 Lồng giọng đọc vào clip có sẵn** (tab Tạo clip): tải clip của bạn lên (MP4, MOV, WEBM… tối đa 1 GB) + dán kịch bản → phần mềm tạo giọng đọc tiếng Việt (giọng chọn ở Cài đặt clip: VieNeu / Gemini / Microsoft…) và ghép vào clip. Tự khớp độ dài (kéo dài bằng khung hình cuối / lặp clip / cắt theo lời đọc / co giãn tốc độ), chọn tắt hoặc giữ tiếng gốc (nhỏ làm nền), có phụ đề tô sáng từng chữ; xem, tải về, đăng Fanpage như các clip khác.
  Kịch bản chia cảnh ("Cảnh 1 — tên cảnh", có thể ghi thời điểm `Cảnh 2 [00:12] — ...`): dòng "Cảnh N", tiêu đề, ghi chú trong (ngoặc) **không được đọc**; phần mềm tự dò chỗ chuyển cảnh trong clip để lời đọc cảnh nào khớp đúng cảnh đó; có bản xem trước "nhận N cảnh, bỏ qua K dòng". Phụ đề chọn dưới / cao hơn / trên / không (clip đã có phụ đề sẵn). Từ viết tắt (TNCN, MST, GTGT…) và từ như "token" được đọc đúng.
- **🧩 Kiểu nội dung đổi theo từng clip** (ô "Kiểu nội dung", mặc định tự đổi): Bản tin nóng · Hỏi – Đáp · Top sai lầm · Câu chuyện tình huống · So sánh cũ – mới · Hướng dẫn từng bước · Hiểu lầm – Sự thật · Luật sư – kế toán giải trình. Mỗi kiểu có mạch kể, câu mở đầu, câu kết và trình tự cảnh riêng, dùng thêm 6 bố cục mới: so sánh 2 cột, trích dẫn lớn, dòng thời gian, checklist tích dần, hỏi – đáp, xếp hạng Top.
- **🎨 Giao diện clip đổi theo từng clip** (kiểu Công nghệ / Giải thích): 7 bộ màu (Xanh đêm, Ngọc lục bảo, Tím hoàng hôn, Cam năng lượng, Xanh biển, Đỏ cảnh báo, Than chì – vàng) × 6 họa tiết nền × 3 kiểu tiêu đề; mặc định "Tự đổi mỗi clip". Trong một clip: cảnh 1-2 ý dùng thẻ lớn có biểu tượng đặt giữa khung, danh sách ngắn xen kẽ dạng lưới ô / danh sách đánh số, số cảnh lớn mờ làm nền, nội dung tự căn giữa khoảng trống.
- **Kiểu clip "Vẽ tay" (mặc định)**: nền giấy kem, nhãn + tiêu đề góc trái, 2-4 hình minh họa phác thảo do Gemini vẽ
  được "vẽ" lộ dần bởi một bàn tay cầm bút, phụ đề có tô vàng từ khóa. Kịch bản chi tiết, giải thích thuật ngữ và có
  **ví dụ cụ thể có số liệu**. Dựng ở 720p cho nhanh; mỗi hình AI khoảng 0,04 USD, hình nào lỗi thì dùng thẻ phác thảo vẽ tay.
- **Kiểu "Công nghệ"** (học theo clip review repo bạn gửi): nền xanh đen có lưới và hạt sáng, nhãn "01 — ÁP DỤNG" + tiêu đề 2 dòng
  (dòng 2 xanh dương), **chip có biểu tượng**, **cửa sổ trình duyệt giả có khung tô sáng dòng quan trọng**, số liệu lớn + biểu đồ,
  bong bóng chat + nút kêu gọi, phụ đề trắng đậm tô nền xanh. Có ô **"Lấy nội dung repo GitHub"**: dán link repo, phần mềm lấy mô tả, số sao,
  giấy phép, README làm nguồn để AI viết kịch bản.
- **Vẽ từng nét (tùy chọn)**: chọn "Vẽ từng nét như người thật" ở Cài đặt clip để dùng
  [whiteboard-animator](https://github.com/masihsultani/whiteboard-animator) (MIT, chạy CPU): chữ được viết từng từ, nét mực
  vẽ theo đường, hình tô màu được tô bằng nét cọ. Cần cài thêm (~200 MB) và dựng lâu hơn; lỗi thì tự quay về kiểu quét nhanh.
- **Giọng VieNeu-TTS** ([pnnbao97/VieNeu-TTS](https://github.com/pnnbao97/VieNeu-TTS), Apache-2.0): chạy hoàn toàn trên CPU
  bằng ONNX, không cần card đồ họa, 10 giọng Bắc/Trung/Nam. Cài bằng nút **Cài / cập nhật công cụ**; lần đầu tự tải mô hình.
- **Kiểu clip "Giải thích"** (mặc định, học theo clip công nghệ bạn gửi): nền xanh đậm có vầng sáng, tiêu đề 2 dòng
  chữ hẹp đậm (dòng 2 chuyển màu), thẻ kính mờ dựng dần — **sơ đồ cây, các bước nối nhau, danh sách, số lớn** —
  phụ đề vàng với từ khóa nổi nền tím. Chọn "Cổ điển" ở Cài đặt clip nếu muốn kiểu cũ.
- Mỗi cảnh (kiểu cổ điển) gồm: nền chuyển động (video Pexels nếu có key, ảnh của bài làm mờ, hoặc nền màu có hiệu ứng),
  tiêu đề trượt vào, thẻ **con số nổi bật** hoặc **gạch đầu dòng hiện lần lượt**, phụ đề chạy theo lời đọc
  (số liệu tô vàng), chuyển cảnh mượt giữa các cảnh. Kịch bản 2–3 phút được AI viết đủ số từ (thiếu thì tự viết lại).
- Lần đầu bấm **⬇ Cài công cụ** (cài `pillow`, `edge-tts`, `imageio-ffmpeg` — đã kèm FFmpeg).
- Chọn bài ở tab *Tin tức AI* / *Bài đăng* hoặc dán nội dung → **✨ AI viết kịch bản** → sửa từng cảnh →
  **🎬 Dựng clip** → xem thử → **⬇ Tải về** (TikTok, YouTube) hoặc **📤 Đăng lên Fanpage**.
- **Giọng Gemini AI (tự nhiên nhất, dùng Gemini key có sẵn)**: 10 giọng (Leda, Zephyr, Kore, Puck...) kèm
  *phong cách đọc* (năng động tin nhanh / ấm áp tư vấn / chuyên gia). **Ảnh AI** vẽ riêng cho từng cảnh và
  **video AI Veo** (công nghệ của Google Flow, có phí ~0,8 USD/cảnh 8 giây, mặc định tắt) — chọn ở Cài đặt clip.
- Giọng đọc khác: Microsoft (Hoài My, Nam Minh — hay nhất, cần Internet) hoặc **Piper offline**
  ([OHF-Voice/piper1-gpl](https://github.com/OHF-Voice/piper1-gpl), giọng VAIS1000 / 25hours / VIVOS — chạy ngay trên máy,
  lần đầu tự tải mô hình về `data/piper-voices`). Giọng lỗi thì tự chuyển giọng khác, cuối cùng là Google.
  Bấm **🔊 Nghe thử** để so sánh.
- Nhạc nền: chép file nhạc **không bản quyền** (.mp3) vào `data/music`, phần mềm chọn ngẫu nhiên và để nhỏ tiếng.

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
