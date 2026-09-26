"""Nội dung mặc định: tính năng phần mềm KE-TOAN, kịch bản tin nhắn, mẫu bài đăng.

Tất cả đều sửa được trên giao diện (tab "Kịch bản"); đây chỉ là giá trị ban đầu.
"""

PRODUCT_NAME = "Phần mềm Kế toán Đa công ty"

FEATURES = [
    {
        "key": "hoa_don",
        "short": "Tải hóa đơn",
        "title": "📥 Tải hóa đơn điện tử hàng loạt",
        "keywords": ["hoa don", "hddt", "xml", "tai hoa don", "mua vao", "ban ra", "gdt"],
        "detail": (
            "📥 TẢI HÓA ĐƠN ĐIỆN TỬ HÀNG LOẠT\n"
            "• Kết nối trang hoadondientu.gdt.gov.vn, mỗi công ty một tài khoản riêng\n"
            "• Tự đọc captcha, tự đăng nhập\n"
            "• Tra cứu mua vào / bán ra, cả hóa đơn máy tính tiền\n"
            "• Tải XML (.zip), HTML, xuất Excel tổng hợp\n"
            "• Chạy hàng loạt cho nhiều công ty trong 1 lần bấm"
        ),
    },
    {
        "key": "to_khai",
        "short": "Tờ khai thuế",
        "title": "🧾 Lập & nộp tờ khai thuế",
        "keywords": ["to khai", "htkk", "gtgt", "tncn", "nop thue", "nop to khai", "thue dien tu"],
        "detail": (
            "🧾 TỜ KHAI & NỘP THUẾ\n"
            "• Tạm tính thuế GTGT trong kỳ ngay từ hóa đơn đã tải\n"
            "• Xuất tờ khai HTKK 01/GTGT, 05/TNCN dạng XML\n"
            "• Tự động nộp tờ khai và kiểm tra trạng thái đã nộp\n"
            "• Tải hàng loạt tờ khai / báo cáo đã nộp của nhiều công ty"
        ),
    },
    {
        "key": "misa",
        "short": "Nhập liệu MISA",
        "title": "⚙️ Nhập liệu tự động vào MISA",
        "keywords": ["misa", "nhap lieu", "hach toan", "ccdc", "tscd", "khau hao", "phan bo"],
        "detail": (
            "⚙️ NHẬP LIỆU TỰ ĐỘNG VÀO MISA\n"
            "• Đẩy thẳng hóa đơn mua vào / bán ra vào MISA, không gõ tay\n"
            "• Import danh mục hàng hóa, khách hàng, nhà cung cấp\n"
            "• Ghi tăng CCDC, TSCĐ; phân bổ CCDC, khấu hao TSCĐ\n"
            "• Tờ khai khấu trừ GTGT, ủy nhiệm thu / chi\n"
            "• Chẩn đoán và sửa lỗi dữ liệu thường gặp"
        ),
    },
    {
        "key": "doi_chieu",
        "short": "Đối chiếu NH",
        "title": "🏦 Đối chiếu ngân hàng & công nợ",
        "keywords": ["ngan hang", "sao ke", "doi chieu", "cong no", "bu tru"],
        "detail": (
            "🏦 ĐỐI CHIẾU NGÂN HÀNG & CÔNG NỢ\n"
            "• Khớp sao kê ngân hàng với hóa đơn tự động\n"
            "• Đối chiếu công nợ 3 tầng, xem chi tiết từng đối tượng\n"
            "• Bù trừ công nợ, xuất bảng điều chỉnh"
        ),
    },
    {
        "key": "kho",
        "short": "Kho & giá thành",
        "title": "📦 Xuất kho, tồn kho & giá thành",
        "keywords": ["kho", "ton kho", "xuat kho", "gia thanh", "xuat khau", "nhap khau"],
        "detail": (
            "📦 KHO & GIÁ THÀNH\n"
            "• Import tồn kho, tự tạo phiếu xuất theo hóa đơn bán ra\n"
            "• Tính giá thành tự động\n"
            "• Xử lý tờ khai xuất khẩu / nhập khẩu"
        ),
    },
    {
        "key": "tmdt",
        "short": "Sàn TMĐT",
        "title": "🛒 Hóa đơn cho sàn TMĐT",
        "keywords": ["shopee", "lazada", "tiktok", "san tmdt", "tmdt", "thuong mai dien tu"],
        "detail": (
            "🛒 HỖ TRỢ XUẤT HÓA ĐƠN SÀN TMĐT\n"
            "• Kết nối Shopee, Lazada, TikTok Shop\n"
            "• Lấy đơn hàng để lập hóa đơn và đối chiếu doanh thu"
        ),
    },
]

DEFAULT_SCRIPT = {
    "welcome": (
        "Chào {name} 👋 Cảm ơn bạn đã quan tâm {product}!\n\n"
        "Phần mềm dành cho dịch vụ kế toán quản lý NHIỀU công ty cùng lúc: "
        "tải hóa đơn hàng loạt, lập & nộp tờ khai, nhập liệu MISA tự động, "
        "đối chiếu ngân hàng…\n\n"
        "Bạn muốn xem tính năng nào? Chọn bên dưới nhé 👇"
    ),
    "comment_private_reply": (
        "Chào {name} 👋 Cảm ơn bạn đã bình luận!\n\n"
        "{product} giúp dịch vụ kế toán tiết kiệm hàng giờ mỗi tháng:\n"
        "📥 Tải hóa đơn điện tử hàng loạt nhiều công ty\n"
        "🧾 Lập & nộp tờ khai thuế tự động\n"
        "⚙️ Đẩy dữ liệu thẳng vào MISA\n"
        "🏦 Đối chiếu ngân hàng & công nợ\n\n"
        "Bạn trả lời tin này (ví dụ: \"hóa đơn\", \"tờ khai\", \"giá\") để mình gửi chi tiết nhé!"
    ),
    "comment_public_reply": "Mình đã gửi thông tin qua tin nhắn, {name} kiểm tra hộp thư giúp mình nhé ❤️",
    "comment_keywords": [
        "quan tam", "tu van", "demo", "dung thu", "bao gia", "gia bao nhieu", "ib",
        "inbox", "info", "xin thong tin", "check",
    ],
    "reply_all_comments": False,
    "pricing": (
        "💰 BẢNG GIÁ\n"
        "Vui lòng để lại SỐ ĐIỆN THOẠI, bộ phận tư vấn sẽ gọi lại báo giá theo số "
        "công ty bạn đang quản lý và hỗ trợ cài đặt dùng thử miễn phí."
    ),
    "demo": (
        "🎁 DÙNG THỬ\n"
        "Bạn để lại SỐ ĐIỆN THOẠI (hoặc Zalo), mình sẽ gửi bản cài đặt và hướng dẫn "
        "dùng thử trực tiếp với dữ liệu công ty của bạn."
    ),
    "phone_thanks": (
        "✅ Đã nhận số {phone}. Bộ phận tư vấn sẽ liên hệ bạn trong giờ hành chính. "
        "Cảm ơn bạn!"
    ),
    "human_handover": (
        "👩‍💼 Mình đã chuyển cho tư vấn viên, bạn chờ trong giây lát nhé. "
        "Muốn quay lại menu tự động, gõ \"menu\"."
    ),
    "opt_out": (
        "Đã dừng tin nhắn tự động cho bạn. Khi cần, gõ \"menu\" để xem lại thông tin. "
        "Chúc bạn một ngày tốt lành!"
    ),
    "fallback": "Mình chưa hiểu ý bạn 😅 Bạn chọn một mục bên dưới hoặc để lại số điện thoại để được tư vấn nhé.",
    "human_pause_hours": 12,
    "features": FEATURES,
}

HASHTAGS = "#ketoan #dichvuketoan #hoadondientu #misa #tokhaithue #phanmemketoan"
CTA = "👉 Bình luận \"QUAN TÂM\" để nhận tài liệu & bản dùng thử qua tin nhắn."

POST_TEMPLATES = [
    {
        "key": "tong_quan",
        "title": "Giới thiệu tổng quan",
        "text": (
            "📣 Làm dịch vụ kế toán cho 10, 20, 50 công ty? Đừng đăng nhập từng tài khoản nữa!\n\n"
            "{product} gom tất cả về một màn hình:\n"
            "✅ Tải hóa đơn điện tử hàng loạt cho nhiều công ty\n"
            "✅ Tạm tính thuế GTGT, xuất tờ khai HTKK, tự động nộp\n"
            "✅ Đẩy dữ liệu thẳng vào MISA — hết cảnh gõ tay\n"
            "✅ Đối chiếu ngân hàng & công nợ tự động\n"
            "✅ Dữ liệu lưu ngay trên máy bạn, bảo mật\n\n"
            "{cta}\n\n{hashtags}"
        ),
    },
    {
        "key": "hoa_don",
        "title": "Tải hóa đơn hàng loạt",
        "text": (
            "⏱️ Cuối tháng tải hóa đơn cho cả chục công ty mất cả buổi?\n\n"
            "Với {product}:\n"
            "• Tự đọc captcha, tự đăng nhập hoadondientu.gdt.gov.vn\n"
            "• Chọn nhiều công ty → 1 lần bấm lấy hết mua vào / bán ra\n"
            "• Tải XML, HTML, xuất Excel tổng hợp\n\n"
            "Việc cả buổi còn vài phút ☕\n\n"
            "{cta}\n\n{hashtags}"
        ),
    },
    {
        "key": "to_khai",
        "title": "Tờ khai & nộp thuế",
        "text": (
            "🧾 Mùa nộp tờ khai không còn là nỗi ám ảnh!\n\n"
            "• Tạm tính thuế GTGT ngay từ hóa đơn đã tải\n"
            "• Xuất XML tờ khai HTKK 01/GTGT, 05/TNCN\n"
            "• Tự động nộp tờ khai, kiểm tra trạng thái đã nộp cho từng công ty\n"
            "• Tải hàng loạt tờ khai đã nộp để lưu hồ sơ\n\n"
            "{cta}\n\n{hashtags}"
        ),
    },
    {
        "key": "misa",
        "title": "Nhập liệu MISA tự động",
        "text": (
            "⚙️ Kế toán dùng MISA ơi, còn nhập hóa đơn bằng tay à?\n\n"
            "{product} kết nối thẳng dữ liệu MISA:\n"
            "• Import mua hàng, bán hàng từ hóa đơn điện tử\n"
            "• Tự tạo danh mục hàng hóa, khách hàng, nhà cung cấp\n"
            "• Ghi tăng CCDC/TSCĐ, phân bổ, khấu hao\n"
            "• Chẩn đoán & sửa lỗi dữ liệu thường gặp\n\n"
            "{cta}\n\n{hashtags}"
        ),
    },
    {
        "key": "doi_chieu",
        "title": "Đối chiếu ngân hàng & công nợ",
        "text": (
            "🏦 Khớp sao kê ngân hàng với hóa đơn — tự động.\n\n"
            "• Đối chiếu sao kê ↔ hóa đơn trong vài giây\n"
            "• Đối chiếu công nợ 3 tầng, bù trừ công nợ\n"
            "• Xuất bảng điều chỉnh gửi khách hàng\n\n"
            "{cta}\n\n{hashtags}"
        ),
    },
]


def render(template: str, **values) -> str:
    """Thay {name}, {product}… — bỏ qua biến không có thay vì báo lỗi."""
    values.setdefault("product", PRODUCT_NAME)
    values.setdefault("cta", CTA)
    values.setdefault("hashtags", HASHTAGS)

    class _Safe(dict):
        def __missing__(self, key):
            return "{" + key + "}"

    return template.format_map(_Safe(values))
