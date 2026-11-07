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
SIMILAR = 0.72


def _plain(html_text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html_text or "")).strip()


def similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, _plain(a).lower(), _plain(b).lower()).ratio()


def _clean(text: str, link: str) -> str:
    t = str(text or "").strip()
    if link:
        t = t.replace(link, "").strip()
    t = re.sub(r"https?://\S+", "", t)                     # link do phần mềm gắn cuối bài, AI không tự chèn
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def _fallback(article: dict, groups: list) -> dict:
    """Không có AI: ghép mở bài khác nhau + ý chính của bài."""
    title = article.get("title", "")
    desc = _plain(article.get("description") or article.get("content", ""))[:320]
    hooks = ["❓ Doanh nghiệp của bạn đã nắm rõ điều này chưa?", "⚠️ Lưu ý quan trọng cho kế toán và chủ doanh nghiệp:",
             "📌 Chia sẻ để anh chị em trong nhóm cùng tham khảo:", "💡 Một kinh nghiệm thực tế đáng để lưu lại:",
             "📢 Cập nhật mới cho anh chị làm kế toán – thuế:", "🔎 Nhiều doanh nghiệp vẫn đang làm sai điểm này:",
             "✅ Ghi nhớ nhanh trước khi kê khai:"]
    ends = ["Ai cần trao đổi thêm cứ bình luận bên dưới nhé.", "Anh chị thấy hữu ích thì lưu lại để dùng khi cần.",
            "Mọi người có kinh nghiệm gì thêm thì chia sẻ cùng nhóm nhé.", "Chi tiết đầy đủ trong bài viết bên dưới."]
    return {g["id"]: f"{hooks[k % len(hooks)]}\n\n{title}\n\n{desc}\n\n{ends[k % len(ends)]}" for k, g in enumerate(groups)}


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

    def ask(targets, avoid=None):
        lines = "\n".join(f'{k}. Nhóm "{g["name"]}" — cách viết: {STYLES[(g.get("_k", k)) % len(STYLES)]}'
                          for k, g in enumerate(targets))
        prompt = (f'Bạn là kế toán viên đang chia sẻ bài viết trong các nhóm Facebook về kế toán – thuế.\n'
                  f'BÀI GỐC: "{article.get("title", "")}" (từ khóa chính: "{article.get("keyword", "")}").\n'
                  f'Tóm tắt: {article.get("description", "")}\nNội dung: {body}\n\n'
                  f'Viết {len(targets)} bài đăng nhóm, MỖI NHÓM MỘT BÀI theo cách viết được giao:\n{lines}\n\n'
                  'Yêu cầu cho từng bài:\n'
                  '- Cùng trọng tâm là nội dung bài gốc (giữ đúng số liệu, số hiệu văn bản, mức phạt có trong bài; không bịa).\n'
                  '- 5-9 dòng, câu chữ, câu mở đầu và bố cục KHÁC HẲN các bài còn lại (không lặp câu, không chỉ đổi vài từ).\n'
                  '- Giọng chia sẻ tự nhiên trong cộng đồng, không quảng cáo lộ liễu, không "inbox", tối đa 2 biểu tượng cảm xúc.\n'
                  '- Có thể có 1-3 hashtag cuối bài. KHÔNG chèn đường link (phần mềm tự gắn link bài viết ở cuối).\n'
                  '- Câu cuối mời đọc chi tiết / bình luận trao đổi.\n'
                  + (f'- TRÁNH viết giống các bài đã có: {" || ".join(_plain(a)[:200] for a in avoid)}\n' if avoid else '')
                  + 'Chỉ trả về JSON {"posts":[{"n":0,"text":"..."}]}')
        out = newsagent.gemini_json(prompt, cfg)
        res = {}
        for p in (out.get("posts") or []):
            try:
                n = int(p.get("n"))
            except (TypeError, ValueError):
                continue
            t = _clean(p.get("text", ""), article.get("url", ""))
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
        if not t or any(similarity(t, o) > SIMILAR for o in kept):
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
            res[g["id"]] = t if t and all(similarity(t, o) <= SIMILAR for o in kept) else fb[g["id"]]
            kept.append(res[g["id"]])
    for g in groups:
        g.pop("_k", None)
    return res
