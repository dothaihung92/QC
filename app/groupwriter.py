"""Viết lại bài (vd bài SEO vừa đăng web) thành bài đăng nhóm Facebook — MỖI NHÓM MỘT CÁCH VIẾT KHÁC NHAU
(mở bài, bố cục, câu chữ khác) nhưng cùng trọng tâm nội dung. Facebook dễ đánh dấu spam khi cùng một nội dung
đăng y hệt vào nhiều nhóm, nên các bản được kiểm tra độ giống nhau; quá giống thì viết lại.
"""
import difflib
import re

from . import newsagent

STYLES = [
    "mở bằng một CÂU HỎI chạm đúng nỗi lo của chủ doanh nghiệp / kế toán",
    "mở bằng MỘT CON SỐ hoặc mức phạt cụ thể có trong bài",
    "mở bằng một TÌNH HUỐNG thực tế ngắn (1-2 câu) rồi rút ra bài học",
    "mở bằng lời CẢNH BÁO ngắn gọn, sau đó liệt kê việc cần làm",
    "viết dạng CHIA SẺ KINH NGHIỆM của người làm kế toán lâu năm, giọng gần gũi",
    "viết dạng DANH SÁCH 3-4 gạch đầu dòng 'cần nhớ', mở bằng một câu tóm tắt",
    "viết dạng HỎI – ĐÁP: nêu 1 câu hỏi hay gặp rồi trả lời ngắn",
]
GOALS = {
    "trial": ("KÊU GỌI NGƯỜI XEM TẢI VÀ DÙNG THỬ PHẦN MỀM",
              "Mỗi bài nêu 1-2 lợi ích cụ thể (tiết kiệm thời gian, bớt sai sót, làm được việc gì…) lấy từ nội dung gốc, rồi kêu gọi HÀNH ĐỘNG rõ ràng: "
              "tải về dùng thử (ưu tiên nói dùng thử / miễn phí nếu nội dung gốc có nói). Mỗi bài một lời kêu gọi khác nhau. "
              "Không phóng đại, không hứa hẹn điều nội dung gốc không có, không viết như quảng cáo spam."),
    "service": ("GIỚI THIỆU DỊCH VỤ VÀ MỜI LIÊN HỆ TƯ VẤN",
                "Nêu điểm mạnh của dịch vụ từ nội dung gốc và mời liên hệ tư vấn; mỗi bài một lời mời khác nhau; không phóng đại."),
    "share": ("CHIA SẺ KIẾN THỨC, THU HÚT TRAO ĐỔI", "Giọng chia sẻ hữu ích, kết bằng câu mời trao đổi."),
}
SIMILAR = 0.72
SIMILAR_PRODUCT = 0.88               # bài giới thiệu tính năng cùng nói về một danh sách tính năng nên giống nhau hơn bài chia sẻ
PRODUCT_GOALS = ("trial", "service")
# Mỗi nhóm một bộ biểu tượng + kiểu tiêu đề khác nhau (đảm bảo bài không y hệt dù cùng danh sách tính năng)
BULLETS = ["✅", "🔹", "▪️", "➡️", "✔️", "📌", "⭐"]
BENEFIT = ["⏱", "💡", "🚀", "⚡", "🎯"]
CONTACT = ["📩", "📞", "💬", "👉", "☎️"]
TITLES = ["Tên sản phẩm + giá trị chính của nó, kết thúc bằng dấu hai chấm",
          "Mở bằng 'Giới thiệu' + tên sản phẩm, rồi nói nó làm được gì cho kế toán dịch vụ",
          "Tên sản phẩm viết IN HOA, xuống dòng một câu mô tả ngắn",
          "Một câu khẳng định sản phẩm giúp được việc gì (KHÔNG phải câu hỏi), có tên sản phẩm",
          "Tên sản phẩm + 'có những tính năng sau:' (hoặc 'làm được những việc này:'), KHÔNG dùng dấu hỏi"]
BAD_PHRASES = re.compile(r"đau đầu|(bạn|anh chị( em)?|mọi người) có đang|bạn đã (bao giờ|từng)|hoàn toàn có thể|hãy trải nghiệm|"
                         r"giải pháp (tối ưu|hoàn hảo|toàn diện|đột phá)|cuộc cách mạng|mình (mới )?tìm được|mình đang dùng|"
                         r"không còn (phải )?(lo|đau)|bước tiến|tối ưu hóa quy trình|nâng tầm", re.I)
MAX_CHARS = 520                      # bài đăng nhóm ngắn gọn: đọc lướt là nắm ý chính
LINK_NOTE = ["Link bài viết đầy đủ em để ở bình luận nhé.", "Chi tiết mình để link ở bình luận ạ.", "Link bài đầy đủ ở phần bình luận.",
             "Anh chị xem chi tiết ở link bình luận nhé.", "Bài viết chi tiết em gắn ở bình luận."]


def too_ai(text: str) -> bool:
    """Dấu hiệu 'giọng AI / quảng cáo sáo rỗng': mở bằng câu hỏi tu từ, 'đau đầu', 'hãy trải nghiệm ngay', bịa trải nghiệm cá nhân..."""
    first = next((l.strip() for l in str(text).split("\n") if l.strip()), "")
    return bool(BAD_PHRASES.search(text)) or first.endswith("?")


_BUL = re.compile(r"^\s*(?:✅|✔️|✔|🔹|▪️|▪|➡️|➡|📌|⭐|•|-|\*|👉|🔸|☑️)\s+")


def _swap_bullets(text: str, k: int) -> str:
    """Nội dung gốc đã là danh sách tính năng: giữ nguyên, chỉ đổi biểu tượng đầu dòng theo từng nhóm."""
    mark = BULLETS[k % len(BULLETS)]
    return "\n".join((_BUL.sub(mark + " ", l, count=1) if _BUL.match(l) else l) for l in str(text).split("\n"))


def _phones(text: str) -> list:
    return [m.group(0).strip() for m in re.finditer(r"(?<!\d)0\d(?:[\s.]?\d){8,9}(?!\d)", text or "")]


def _ensure_contact(text: str, source: str, k: int) -> str:
    """Số điện thoại / Zalo trong nội dung gốc phải còn nguyên trong bài (AI hay bỏ hoặc viết sai)."""
    digits = re.sub(r"\D", "", text)
    miss = [p for p in _phones(source) if re.sub(r"\D", "", p) not in digits]
    return text if not miss else text.rstrip() + f"\n{CONTACT[k % len(CONTACT)]} Liên hệ: {miss[0]}"


def _plain(html_text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html_text or "")).strip()


def similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, _plain(a).lower(), _plain(b).lower()).ratio()


def _clean(text: str, link: str) -> str:
    t = str(text or "").strip()
    if link:
        t = t.replace(link, "").strip()
    t = re.sub(r"https?://\S+", "", t)                     # link do phần mềm bình luận dưới bài, AI không tự chèn
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def _shorten(t: str, limit: int = MAX_CHARS) -> str:
    """Quá dài thì bỏ bớt dòng giữa (giữ mở bài, câu kết và hashtag) cho gọn."""
    if len(t) <= limit:
        return t
    lines = [l for l in t.split("\n") if l.strip()]
    tags = [l for l in lines if l.strip().startswith("#")]
    body = [l for l in lines if l not in tags]
    while len(body) > 3 and len("\n".join(body + tags)) > limit:
        body.pop(len(body) // 2)
    out = "\n".join(body + tags)
    return out if len(out) <= limit * 1.25 else out[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "…"


HOOKS = ["❓ Doanh nghiệp của bạn đã nắm rõ điều này chưa?", "⚠️ Lưu ý quan trọng cho kế toán và chủ doanh nghiệp:",
         "📌 Chia sẻ để anh chị em trong nhóm cùng tham khảo:", "💡 Một kinh nghiệm thực tế đáng để lưu lại:",
         "📢 Cập nhật mới cho anh chị làm kế toán – thuế:", "🔎 Nhiều doanh nghiệp vẫn đang làm sai điểm này:",
         "✅ Ghi nhớ nhanh trước khi kê khai:"]


def hooks_for(k: int) -> str:
    return HOOKS[k % len(HOOKS)]


def _fallback(article: dict, groups: list) -> dict:
    """Không có AI: ghép mở bài khác nhau + ý chính của bài."""
    title = article.get("title", "")
    text_mode = article.get("mode") == "text"
    desc = _plain(article.get("description") or article.get("content", ""))
    lim = 420 if text_mode else 200
    desc = (desc[:lim].rsplit(" ", 1)[0] + "…") if len(desc) > lim else desc
    raw = str(article.get("content", ""))
    if text_mode and sum(1 for l in raw.split("\n") if _BUL.match(l)) >= 2:       # đã là danh sách tính năng: giữ nguyên bố cục
        return {g["id"]: _swap_bullets(_clean(raw, article.get("url", "")), k) for k, g in enumerate(groups)}
    if text_mode:                                       # nội dung do người dùng viết: giữ nguyên ý, chỉ đổi câu mở đầu / kết
        if article.get("goal") == "trial" and article.get("link_mode") == "post":
            ctas = ["Tải về dùng thử ngay tại link bên dưới nhé!", "Bấm link bên dưới để tải và dùng thử miễn phí.",
                    "Anh chị tải về trải nghiệm thử ở link bên dưới ạ.", "Dùng thử ngay, link tải ở bên dưới."]
            note = lambda k: ctas[k % len(ctas)]                                          # noqa: E731
        else:
            note = lambda k: LINK_NOTE[k % len(LINK_NOTE)] if article.get("url") else ""   # noqa: E731
        return {g["id"]: "\n".join(x for x in (hooks_for(k), desc, note(k)) if x) for k, g in enumerate(groups)}
    hooks = ["❓ Doanh nghiệp của bạn đã nắm rõ điều này chưa?", "⚠️ Lưu ý quan trọng cho kế toán và chủ doanh nghiệp:",
             "📌 Chia sẻ để anh chị em trong nhóm cùng tham khảo:", "💡 Một kinh nghiệm thực tế đáng để lưu lại:",
             "📢 Cập nhật mới cho anh chị làm kế toán – thuế:", "🔎 Nhiều doanh nghiệp vẫn đang làm sai điểm này:",
             "✅ Ghi nhớ nhanh trước khi kê khai:"]
    return {g["id"]: f"{hooks[k % len(hooks)]}\n{title}\n{desc}\n{LINK_NOTE[k % len(LINK_NOTE)]}" for k, g in enumerate(groups)}


def make_variants(article: dict, groups: list, gemini_key: str = "", model: str = "gemini-2.5-flash") -> dict:
    """article: {title, url, keyword, description, content}. Trả về {group_id: nội dung} — mỗi nhóm một bản khác nhau."""
    if not groups:
        return {}
    cfg = dict(newsagent.get_config())
    if gemini_key:
        cfg["gemini_key"] = gemini_key
    cfg["model"] = cfg.get("model") or model
    if not cfg.get("gemini_key"):
        return _fallback(article, groups)
    body = _plain(article.get("content", ""))[:5000]
    text_mode = article.get("mode") == "text"
    has_link = bool(article.get("url"))
    link_in_post = has_link and article.get("link_mode") == "post"
    goal = GOALS.get(article.get("goal", ""))
    product = text_mode and article.get("goal") in PRODUCT_GOALS          # giới thiệu phần mềm / dịch vụ: viết như người giới thiệu tính năng
    sim_limit = SIMILAR_PRODUCT if product else SIMILAR

    def ask(targets, avoid=None):
        lines = "\n".join(f'{k}. Nhóm "{g["name"]}" — cách viết: {STYLES[(g.get("_k", k)) % len(STYLES)]}'
                          for k, g in enumerate(targets))
        source = (f'NỘI DUNG GỐC do người dùng soạn (là ý cần truyền tải, viết lại cho hay hơn nhưng giữ đúng ý):\n{body}\n\n' if text_mode else
                  f'BÀI GỐC: "{article.get("title", "")}" (từ khóa chính: "{article.get("keyword", "")}").\n'
                  f'Tóm tắt: {article.get("description", "")}\nNội dung: {body}\n\n')
        length = ('- Độ dài vừa phải: 4-8 dòng, dưới 700 ký tự; GIỮ ĐỦ các ý chính, số liệu, thông tin liên hệ / ưu đãi có trong nội dung gốc.\n' if text_mode else
                  '- NGẮN GỌN: tối đa 4 dòng ngắn, tổng dưới 380 ký tự — chỉ nêu Ý CHÍNH (điều gì thay đổi / kết luận / con số quan trọng nhất), '
                  'không giải thích dài dòng, không liệt kê hết chi tiết (chi tiết nằm ở bài viết).\n')
        if link_in_post:
            ending = ('- KHÔNG tự viết đường link (phần mềm sẽ tự gắn link ngay dưới bài). Dòng cuối là lời mời bấm vào LINK BÊN DƯỚI '
                      '(vd "Tải về dùng thử tại link bên dưới nhé"), mỗi bài nói một cách khác nhau.\n')
        elif has_link:
            ending = ('- KHÔNG chèn đường link. Dòng cuối là câu mời xem chi tiết ở BÌNH LUẬN (vd "Link bài viết đầy đủ em để ở bình luận nhé"), mỗi bài nói một cách khác nhau.\n')
        else:
            ending = '- KHÔNG chèn đường link. Dòng cuối là một câu mời trao đổi / bình luận, mỗi bài nói một cách khác nhau.\n'
        goal_line = (f'- MỤC TIÊU CỦA BÀI: {goal[0]}. {goal[1]}\n' if goal else '')
        if product:
            rows = "\n".join(f'{k}. Nhóm "{g["name"]}" — biểu tượng đầu dòng tính năng: {BULLETS[g.get("_k", k) % len(BULLETS)]} · biểu tượng dòng lợi ích: '
                              f'{BENEFIT[g.get("_k", k) % len(BENEFIT)]} · biểu tượng dòng liên hệ: {CONTACT[g.get("_k", k) % len(CONTACT)]} · '
                              f'dòng tiêu đề: {TITLES[g.get("_k", k) % len(TITLES)]}' for k, g in enumerate(targets))
            tail = ('Dòng liên hệ: GIỮ NGUYÊN số điện thoại / Zalo / cách liên hệ như trong nội dung gốc (không đổi số, không bỏ). '
                    + ('Thêm 1 dòng ngắn mời tải / dùng thử ở LINK BÊN DƯỚI (mỗi bài nói một cách), KHÔNG tự viết đường link.\n' if link_in_post else
                       'Thêm 1 dòng ngắn mời xem chi tiết ở BÌNH LUẬN (mỗi bài nói một cách), KHÔNG tự viết đường link.\n' if has_link else
                       'KHÔNG chèn đường link.\n'))
            prompt = (f'Bạn là người trong đơn vị làm phần mềm kế toán, đang đăng bài GIỚI THIỆU SẢN PHẨM trong các nhóm Facebook của kế toán – thuế. '
                      'Viết như người thật đăng bài: thẳng, gọn, kể rõ phần mềm LÀM ĐƯỢC những gì — không văn mẫu, không giọng quảng cáo, không giọng AI.\n\n' + source +
                      f'Viết {len(targets)} bài đăng, MỖI NHÓM MỘT BÀI theo cấu hình được giao:\n{rows}\n\n'
                      'CẤU TRÚC MỖI BÀI (xuống dòng rõ ràng như bài mẫu):\n'
                      '1) Dòng tiêu đề theo kiểu được giao (tên sản phẩm + giá trị chính; có thể kết bằng dấu ":").\n'
                      '2) 4–6 dòng tính năng, MỖI DÒNG MỘT TÍNH NĂNG, bắt đầu bằng biểu tượng được giao, ngắn (6–16 từ), động từ ở đầu (Tải, Tự động, Xuất, Đối chiếu...). '
                      'Lấy từ nội dung gốc, diễn đạt lại nhẹ cho khác nhau giữa các nhóm; chọn tính năng và SẮP XẾP THỨ TỰ khác các nhóm còn lại.\n'
                      '3) 1 dòng lợi ích (tiết kiệm thời gian / công sức) với biểu tượng được giao — chỉ nêu nếu nội dung gốc có ý đó.\n'
                      '4) ' + tail +
                      '5) 3–5 hashtag cuối bài (khác nhau giữa các nhóm).\n\n'
                      'QUY TẮC:\n' + goal_line +
                      '- Chỉ dùng tính năng và thông tin có trong nội dung gốc. KHÔNG bịa tính năng, số liệu, khách hàng, giá, ưu đãi.\n'
                      '- CẤM: câu hỏi mở bài, "anh chị em có đang…", "đau đầu", "hoàn toàn có thể", "giải pháp tối ưu / hoàn hảo", "hãy trải nghiệm ngay", '
                      '"mình mới tìm được / mình đang dùng" (đừng bịa trải nghiệm cá nhân), các từ sáo rỗng như "đột phá", "nâng tầm", "cuộc cách mạng".\n'
                      '- Mỗi bài tối đa 2 biểu tượng cảm xúc ngoài các biểu tượng đầu dòng được giao. Không chào hỏi dài dòng.\n'
                      + (f'- TRÁNH viết giống các bài đã có: {" || ".join(_plain(a)[:200] for a in avoid)}\n' if avoid else '')
                      + 'Chỉ trả về JSON {"posts":[{"n":0,"text":"..."}]}')
            return _collect(prompt, targets, 1200)
        prompt = (f'Bạn là kế toán viên đang chia sẻ bài viết trong các nhóm Facebook về kế toán – thuế.\n' + source +
                  f'Viết {len(targets)} bài đăng nhóm, MỖI NHÓM MỘT BÀI theo cách viết được giao:\n{lines}\n\n'
                  'Yêu cầu cho từng bài:\n' + goal_line + length +
                  '- Giữ đúng số liệu, số hiệu văn bản, mức phạt có trong nội dung gốc; không bịa.\n'
                  '- Câu chữ, câu mở đầu và bố cục KHÁC HẲN các bài còn lại (không lặp câu, không chỉ đổi vài từ).\n'
                  '- Giọng chia sẻ tự nhiên trong cộng đồng, không quảng cáo lộ liễu, không "inbox", tối đa 1-2 biểu tượng cảm xúc, tối đa 2 hashtag cuối bài.\n'
                  + ending
                  + (f'- TRÁNH viết giống các bài đã có: {" || ".join(_plain(a)[:200] for a in avoid)}\n' if avoid else '')
                  + 'Chỉ trả về JSON {"posts":[{"n":0,"text":"..."}]}')
        return _collect(prompt, targets, 900 if text_mode else MAX_CHARS)

    def _collect(prompt, targets, limit):
        out = newsagent.gemini_json(prompt, cfg)
        res = {}
        for p in (out.get("posts") or []):
            try:
                n = int(p.get("n"))
            except (TypeError, ValueError):
                continue
            t = _shorten(_clean(p.get("text", ""), article.get("url", "")), limit)
            if product and t:
                if too_ai(t):
                    continue                                   # giọng AI / quảng cáo sáo rỗng → viết lại
                t = _ensure_contact(t, article.get("content", ""), targets[n].get("_k", n) if 0 <= n < len(targets) else 0)
            if 0 <= n < len(targets) and len(t) > 60:
                res[targets[n]["id"]] = t
        return res

    for k, g in enumerate(groups):
        g["_k"] = k
    try:
        res = ask(groups)
    except Exception:                                        # noqa: BLE001 — AI lỗi thì vẫn có bài để đăng
        res = {}
    # thiếu bài hoặc 2 bài quá giống nhau → viết lại những nhóm đó (1 lần)
    redo, kept = [], []
    for g in groups:
        t = res.get(g["id"])
        if not t or any(similarity(t, o) > sim_limit for o in kept):
            redo.append(g)
        else:
            kept.append(t)
    if redo:
        for k, g in enumerate(redo):
            g["_k"] = g["_k"] + 3                              # đổi cách viết
        try:
            more = ask(redo, avoid=kept[:4])
        except Exception:                                    # noqa: BLE001
            more = {}
        fb = _fallback(article, redo)
        for g in redo:
            t = more.get(g["id"])
            res[g["id"]] = t if t and all(similarity(t, o) <= sim_limit for o in kept) else fb[g["id"]]
            kept.append(res[g["id"]])
    for g in groups:
        g.pop("_k", None)
    return res
