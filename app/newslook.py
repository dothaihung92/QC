"""Kiểu clip "Tin nhanh" (bản tin ngắn 9:16): nửa trên là ẢNH MINH HỌA đổi theo từng ý, nửa dưới nền xanh với CHỮ TO NHẤN MẠNH
những cụm quan trọng (con số vàng, hành động cam) chạy đúng theo lời đọc; cảnh cuối là thẻ liên hệ + lời kêu gọi.

AI chỉ chọn lọc những ý QUAN TRỌNG của bài (ai – việc gì – con số – mốc thời gian – doanh nghiệp cần làm), mỗi cảnh 1 câu ngắn.
Kèm sẵn nội dung đăng Facebook: câu tiêu đề + đường kẻ + chữ ký thương hiệu (tên, giới thiệu, địa chỉ, hotline) + hashtag.
"""
import math
import re
import shutil
import unicodedata
from pathlib import Path

from . import aimedia, db, newsagent
from . import video as V

SIZE = (720, 1280)                     # dựng 720p dọc cho nhanh, đúng độ phân giải clip mẫu
NEWS_SCENES = {30: 7, 45: 10, 60: 13, 120: 22, 180: 30}      # giây → số cảnh (~4,3 giây mỗi ý)
BLUE_TOP, BLUE_BOT = (150, 170, 222), (26, 88, 212)
ORANGE, YELLOW, NAVY = (255, 140, 40), (255, 214, 64), (14, 54, 138)
STRIP = (255, 122, 26)
LABEL = "HÌNH MINH HỌA"

PROMPT = """Bạn là biên tập viên bản tin ngắn (Facebook Reels / TikTok) cho một công ty dịch vụ kế toán - thuế ở Việt Nam.
Đọc bài viết dưới đây và CHỈ GHI NHỮNG NỘI DUNG QUAN TRỌNG NHẤT thành clip khoảng {seconds} giây, gồm đúng {n} cảnh.

QUY TẮC:
- Chỉ giữ thông tin cốt lõi: AI làm gì / điều gì xảy ra, CON SỐ chính, MỐC THỜI GIAN, hệ quả, việc doanh nghiệp cần làm. Bỏ dẫn dắt, chi tiết phụ, trích dẫn dài, lặp ý.
- Mỗi cảnh MỘT ý, MỘT câu văn nói ngắn gọn ({lo}–{hi} từ). Cảnh 1 nêu ngay tin chính kèm con số nổi bật nhất. Cảnh gần cuối là lời khuyên / việc cần làm cho doanh nghiệp (chỉ nêu điều có trong bài hoặc suy ra hợp lý, KHÔNG bịa quy định).
- TRUNG THỰC: giữ nguyên số tiền, tỷ lệ, ngày tháng, số hiệu văn bản, tên cơ quan/người như bài gốc. Không thêm số liệu, không thêm điều bài không nói.
- Con số / số tiền / tỷ lệ viết bằng chữ số như bài gốc (vd "10.000 tỷ đồng", "30%", "50 ngày") để hiện nổi bật trên màn hình; ngày tháng viết "ngày 12 tháng 11" (không dùng dấu /).
- "keyword": từ khóa TIẾNG ANH 2–4 từ để tìm ảnh minh họa (văn phòng thuế, tiền, hóa đơn, họp quốc hội, doanh nghiệp...), ảnh không chứa chữ; mỗi cảnh một từ khóa KHÁC nhau.
- "hl": 1–3 cụm từ viết NGUYÊN VĂN như trong "narration" cần nhấn mạnh trên màn hình (con số, hành động chính, vd "từ chối hoàn", "10.000 tỷ đồng").
- "headline": 1–2 câu (tối đa 40 từ) tóm tắt tin để làm dòng đầu bài đăng Facebook, có con số chính, trung thực, không emoji, không giật tít sai sự thật.
- "hashtags": 3–4 hashtag không dấu viết liền dạng CamelCase (vd #HoanThue #HoaDonDauVao).
- Không tự thêm cảnh giới thiệu công ty hay kêu gọi liên hệ (phần mềm tự thêm cảnh cuối).
{brand}
Trả về JSON: {{"title": "tiêu đề ngắn của clip", "headline": "...", "hashtags": ["#..."],
 "scenes": [{{"narration": "...", "keyword": "english stock photo keywords", "hl": ["cụm nhấn mạnh"]}}]}}

BÀI VIẾT:
{text}
"""


# ---------------------------------------------------------------- kịch bản + nội dung đăng Facebook

def bold_unicode(text: str) -> str:
    """Chữ đậm kiểu Facebook (Unicode): bỏ dấu rồi đổi A-Z a-z 0-9 sang chữ đậm — giống tên thương hiệu in đậm trong bài mẫu."""
    s = unicodedata.normalize("NFD", text.replace("đ", "d").replace("Đ", "D"))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    out = []
    for c in s:
        if "A" <= c <= "Z":
            out.append(chr(0x1D5D4 + ord(c) - 65))
        elif "a" <= c <= "z":
            out.append(chr(0x1D5EE + ord(c) - 97))
        elif "0" <= c <= "9":
            out.append(chr(0x1D7EC + ord(c) - 48))
        else:
            out.append(c)
    return "".join(out)


def compose_caption(headline: str, tags: list, cfg: dict) -> str:
    """Câu tiêu đề + đường kẻ + chữ ký thương hiệu + hashtag (đúng bố cục bài đăng mẫu)."""
    name = (cfg.get("sig_name") or "").strip()
    sig = []
    if name:
        sig.append(bold_unicode(name) if cfg.get("sig_bold", True) else name)
    if (cfg.get("sig_tagline") or "").strip():
        sig.append(cfg["sig_tagline"].strip())
    if (cfg.get("sig_address") or "").strip():
        sig.append("📍 " + cfg["sig_address"].strip())
    if (cfg.get("sig_phone") or "").strip():
        sig.append("📞 Hotline: " + cfg["sig_phone"].strip())
    all_tags = []
    for t in [*(tags or []), *re.split(r"[\s,]+", cfg.get("sig_tags") or "")]:
        t = t.strip()
        if t:
            t = t if t.startswith("#") else "#" + t
            if t.lower() not in [x.lower() for x in all_tags]:
                all_tags.append(t)
    if all_tags:
        sig.append(" ".join(all_tags))
    head = (headline or "").strip()
    if not sig:
        return head
    return (head + "\n\n" if head else "") + "______________________\n" + "\n".join(sig)


def make_script(text: str, seconds: int, cfg: dict) -> dict:
    seconds = seconds if seconds in NEWS_SCENES else 45
    n = NEWS_SCENES[seconds]
    total = int(seconds * 2.7)
    per = total / (n + 1)
    brand = ""
    prompt = PROMPT.format(seconds=seconds, n=n, lo=max(6, int(per * 0.7)), hi=max(12, int(per * 1.3)), brand=brand, text=text[:12000])
    best = None
    for _ in range(2):
        try:
            out = newsagent.gemini_json(prompt, newsagent.get_config())
        except RuntimeError as e:
            if best:
                break
            raise V.VideoError(str(e)) from e
        scenes = []
        for s in out.get("scenes") or []:
            if isinstance(s, dict) and str(s.get("narration", "")).strip():
                scenes.append({**s, "type": "news"})
        scenes = V.clean_scenes(scenes)
        if scenes and (not best or len(scenes) > len(best[1])):
            best = (out, scenes)
        if len(scenes) >= n * 0.7:
            break
        prompt += f"\n\nLƯU Ý: bản trước chỉ có {len(scenes)} cảnh — viết lại ĐỦ {n} cảnh, mỗi cảnh một ý quan trọng khác nhau."
    if not best:
        raise V.VideoError("AI không trả về kịch bản hợp lệ, thử lại")
    out, scenes = best
    tags = [str(t) for t in (out.get("hashtags") or []) if str(t).strip()][:4]
    title = str(out.get("title", "")).strip()[:200]
    headline = str(out.get("headline", "")).strip() or title
    return {"title": title, "format": "news", "format_name": "Tin nhanh (ảnh + chữ nhấn mạnh)",
            "description": compose_caption(headline, tags, cfg)[:2000], "scenes": scenes}


# ---------------------------------------------------------------- vẽ khung

def _gradient(size, top, bot):
    from PIL import Image
    W, H = size
    col = Image.linear_gradient("L").resize((1, H))             # 0 → 255 theo chiều dọc
    base = Image.new("RGB", (W, H), top)
    return Image.composite(Image.new("RGB", (W, H), bot), base, col.resize((W, H)))


def _logo(cfg: dict, height: int, dark: bool = False):
    """Logo thương hiệu: ảnh người dùng tải lên (Cài đặt clip) hoặc chữ thương hiệu."""
    from PIL import Image, ImageDraw
    path = None
    if cfg.get("logo"):
        from . import facebook
        path = facebook.local_media(cfg["logo"])
    if path:
        try:
            im = Image.open(path).convert("RGBA")
            return im.resize((max(1, int(im.width * height / im.height)), height))
        except Exception:  # noqa: BLE001 — logo hỏng thì dùng chữ
            pass
    text = (cfg.get("logo_text") or cfg.get("sig_name") or "").strip()
    if not text:
        return None
    f = V._font(int(height * 0.8), black=True)
    d = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    w = int(d.textlength(text, font=f)) + 4
    im = Image.new("RGBA", (w, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.text((2, int(height * 0.44)), text, font=f, fill=(NAVY if dark else (255, 255, 255)) + (255,), anchor="lm")
    d.rectangle((2, height - max(3, height // 12), int(w * 0.42), height - 1), fill=STRIP + (255,))
    return im


def _paste(img, layer, x, y, alpha: float = 1.0):
    if layer is None:
        return
    if alpha < 1.0:
        a = layer.getchannel("A").point(lambda v: int(v * alpha))
        layer = layer.copy()
        layer.putalpha(a)
    img.paste(layer, (int(x), int(y)), layer)


def _cover(path: Path, w: int, h: int):
    from PIL import Image, ImageOps
    im = Image.open(path)
    im = ImageOps.exif_transpose(im).convert("RGB")
    return ImageOps.fit(im, (w, h), Image.LANCZOS, centering=(0.5, 0.4))


def _stat_panel(w: int, h: int, text: str, cfg: dict):
    """Không có ảnh: ô xanh đậm với con số / cụm quan trọng nhất thật to (không để trống khung ảnh)."""
    from PIL import Image, ImageDraw
    im = _gradient((w, h), (22, 62, 150), (10, 30, 90)).convert("RGBA")
    d = ImageDraw.Draw(im)
    text = (text or "").upper()
    if text:
        size = int(w * 0.13)
        while size > 20:
            f = V._font(size, black=True)
            lines = V._wrap(d, text, f, int(w * 0.84))
            if len(lines) <= 3:
                break
            size = int(size * 0.9)
        lh = int(size * 1.25)
        y = (h - lh * len(lines)) // 2
        for ln in lines:
            d.text((w // 2, y + lh // 2), ln, font=f, fill=YELLOW + (255,), anchor="mm")
            y += lh
    return im.convert("RGB")


def scene_background(cfg: dict, photo, stat_text: str, dest: Path, show_label: bool):
    """Khung 720x1280: dải đầu (nhãn + logo) · ảnh minh họa · nền xanh · dải cam bên trái · logo mờ."""
    from PIL import Image, ImageDraw
    W, H = SIZE
    img = _gradient(SIZE, BLUE_TOP, BLUE_BOT)
    hh, ph = int(H * 0.085), int(H * 0.47)
    sx = int(W * 0.022)
    bar = _gradient((W, hh), (64, 80, 150), (88, 108, 176))
    img.paste(bar, (0, 0))
    d = ImageDraw.Draw(img)
    if photo is not None:
        img.paste(_cover(photo, W - sx, ph - hh), (sx, hh))
    else:
        img.paste(_stat_panel(W - sx, ph - hh, stat_text, cfg), (sx, hh))
    if show_label:
        f = V._font(int(H * 0.0155), bold=True)
        d.text((int(W * 0.06), hh // 2), LABEL, font=f, fill=(235, 240, 255), anchor="lm")
    logo = _logo(cfg, int(hh * 0.62))
    if logo is not None:
        _paste(img, logo, W - logo.width - int(W * 0.05), (hh - logo.height) // 2)
    wm = _logo(cfg, int(H * 0.09))                                        # logo lớn rất mờ làm nền phần chữ
    if wm is not None:
        scale = min(1.0, (W * 0.74) / wm.width)
        wm = wm.resize((int(wm.width * scale), int(wm.height * scale)))
        _paste(img, wm, (W - wm.width) // 2, int(H * 0.80), 0.16)
    ImageDraw.Draw(img).rectangle((0, 0, sx - 1, H), fill=STRIP)
    img.save(dest, "PNG")


def cta_background(cfg: dict, cta_text: str, dest: Path):
    """Cảnh cuối: nền sáng, logo lớn, thẻ thương hiệu (tên – giới thiệu – hotline) và dòng kêu gọi màu cam."""
    from PIL import Image, ImageDraw, ImageFilter
    W, H = SIZE
    img = _gradient(SIZE, (255, 255, 255), (196, 216, 250)).convert("RGBA")
    logo = _logo(cfg, int(H * 0.075), dark=True)
    if logo is not None:
        _paste(img, logo, (W - logo.width) // 2, int(H * 0.06))
    cx0, cx1, cy0 = int(W * 0.09), int(W * 0.91), int(H * 0.19)
    d = ImageDraw.Draw(img)
    name = (cfg.get("sig_name") or "").strip()
    tag = (cfg.get("sig_tagline") or "").strip()
    addr = (cfg.get("sig_address") or "").strip()
    phone = (cfg.get("sig_phone") or "").strip()
    f_name, f_tag, f_lab = V._font(int(W * 0.056), black=True), V._font(int(W * 0.033), bold=True), V._font(int(W * 0.03), bold=True)
    f_ph = V._font(int(W * 0.088), black=True)
    inner = cx1 - cx0 - int(W * 0.1)
    name_l = V._wrap(d, name, f_name, inner)[:3] if name else []
    tag_l = V._wrap(d, tag, f_tag, inner)[:4] if tag else []
    addr_l = V._wrap(d, addr, f_tag, inner)[:3] if addr else []
    gap = int(W * 0.04)
    h = gap + len(name_l) * int(f_name.size * 1.3) + (gap if tag_l else 0) + len(tag_l) * int(f_tag.size * 1.35)
    if phone:
        h += gap + int(f_lab.size * 1.6) + int(f_ph.size * 1.7)
    if addr_l:
        h += gap + len(addr_l) * int(f_tag.size * 1.35)
    h += gap
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((cx0 + 4, cy0 + 14, cx1 + 4, cy0 + h + 14), radius=int(W * 0.05), fill=(20, 40, 100, 90))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(14)))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((cx0, cy0, cx1, cy0 + h), radius=int(W * 0.05), fill=(255, 255, 255, 255))
    y = cy0 + gap
    for ln in name_l:
        d.text((W // 2, y + f_name.size * 0.65), ln, font=f_name, fill=NAVY, anchor="mm")
        y += int(f_name.size * 1.3)
    if tag_l:
        y += gap // 2
        for ln in tag_l:
            d.text((W // 2, y + f_tag.size * 0.65), ln, font=f_tag, fill=(80, 92, 120), anchor="mm")
            y += int(f_tag.size * 1.35)
        y += gap // 2
    if phone:
        d.text((W // 2, y + f_lab.size * 0.8), "HOTLINE", font=f_lab, fill=(110, 122, 150), anchor="mm")
        y += int(f_lab.size * 1.6)
        pw = int(d.textlength(phone, font=f_ph)) + int(W * 0.1)
        d.rounded_rectangle((W // 2 - pw // 2, y, W // 2 + pw // 2, y + int(f_ph.size * 1.5)), radius=int(f_ph.size * 0.7), fill=(30, 100, 230, 255))
        d.text((W // 2, y + f_ph.size * 0.78), phone, font=f_ph, fill=(255, 255, 255), anchor="mm")
        y += int(f_ph.size * 1.7)
    if addr_l:
        y += gap // 2
        for ln in addr_l:
            d.text((W // 2, y + f_tag.size * 0.65), ln, font=f_tag, fill=(80, 92, 120), anchor="mm")
            y += int(f_tag.size * 1.35)
    f_cta = V._font(int(W * 0.062), black=True)
    lines = V._wrap(d, (cta_text or "").upper(), f_cta, int(W * 0.86))[:4]
    lh = int(f_cta.size * 1.3)
    y = max(cy0 + h + int(H * 0.04), int(H * 0.72))
    for ln in lines:
        d.text((W // 2, y + lh // 2), ln, font=f_cta, fill=(240, 100, 20), anchor="mm", stroke_width=1, stroke_fill=(240, 100, 20))
        y += lh
    img.convert("RGB").save(dest, "PNG")


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", (s or "").lower().replace("đ", "d"))
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def color_words(words: list, hl: list) -> list:
    """Màu từng từ: cụm 'hl' của AI → cam; con số + đơn vị (tỷ, triệu, %, đồng, ngày...) → vàng; còn lại trắng."""
    cols = [(255, 255, 255)] * len(words)
    toks = [_norm(re.sub(r"[^\w%./]", "", w)) for w in words]
    for ph in hl or []:
        p = [_norm(re.sub(r"[^\w%./]", "", x)) for x in ph.split()]
        p = [x for x in p if x]
        for i in range(len(toks) - len(p) + 1):
            if p and toks[i:i + len(p)] == p:
                for k in range(i, i + len(p)):
                    cols[k] = ORANGE
    unit = re.compile(r"^(ty|trieu|nghin|dong|%|usd|phan|ngay|thang|nam|vnd)$")
    for i, t in enumerate(toks):
        if re.search(r"\d", t):
            cols[i] = YELLOW
            j = i + 1
            while j < len(toks) and unit.match(toks[j]):
                cols[j] = YELLOW
                j += 1
    return cols


def news_chunks(narration: str, hl: list, max_words: int = 5) -> list:
    """Cụm chữ hiện lần lượt theo lời đọc; không để cụm nhấn mạnh (vd "từ chối hoàn") bị cắt đôi giữa hai màn hình chữ."""
    chunks = V.caption_chunks(narration, max_words)
    words = " ".join(chunks).split()
    toks = [_norm(re.sub(r"[^\w%./]", "", w)) for w in words]
    bounds, acc = [], 0
    for c in chunks[:-1]:
        acc += len(c.split())
        bounds.append(acc)
    for ph in hl or []:
        p = [x for x in (_norm(re.sub(r"[^\w%./]", "", x)) for x in ph.split()) if x]
        for i in range(len(toks) - len(p) + 1):
            if p and toks[i:i + len(p)] == p:
                for k, b in enumerate(bounds):
                    if i < b < i + len(p):                         # ranh giới nằm giữa cụm
                        prev = bounds[k - 1] if k else 0
                        bounds[k] = i if i > prev else i + len(p)
    bounds = sorted({b for b in bounds if 0 < b < len(words)})
    out, last = [], 0
    for b in [*bounds, len(words)]:
        if b > last:
            out.append(" ".join(words[last:b]))
            last = b
    return out or chunks


def chunk_layer(chunk_words: list, colors: list, dest: Path):
    """Một cụm chữ to, in hoa, căn giữa nửa dưới khung; từ nhấn mạnh đổi màu."""
    from PIL import Image, ImageDraw
    W, H = SIZE
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    words = [w.upper() for w in chunk_words]
    size = int(W * 0.085)
    while True:
        f = V._font(size, black=True)
        space = d.textlength(" ", font=f)
        lines, cur, curw = [], [], 0.0
        for k, w in enumerate(words):
            ww = d.textlength(w, font=f)
            if cur and curw + space + ww > W * 0.86:
                lines.append(cur)
                cur, curw = [], 0.0
            cur.append((w, ww, colors[k]))
            curw += ww + (space if len(cur) > 1 else 0)
        lines.append(cur)
        if len(lines) <= 3 or size <= int(W * 0.05):
            break
        size = int(size * 0.92)
    lh = int(size * 1.28)
    y = int(H * 0.645) - lh * len(lines) // 2
    stroke = max(2, size // 22)
    for line in lines:
        total = sum(w[1] for w in line) + space * (len(line) - 1)
        x = (W - total) / 2
        for w, ww, col in line:
            d.text((x, y + lh / 2), w, font=f, fill=col + (255,), anchor="lm", stroke_width=stroke, stroke_fill=(10, 30, 90))
            x += ww + space
        y += lh
    return V._save_layer(ov, dest)


# ---------------------------------------------------------------- dựng clip

def _photo_for(i: int, sc: dict, cfg: dict, work: Path, gkey: str, article, seen: set, aspect: str):
    """Ảnh minh họa cho cảnh: ảnh AI (nếu bật) → Pexels (ảnh khác nhau mỗi cảnh) → ảnh của bài → None."""
    import hashlib
    dest = work / f"photo{i}.img"
    kw = sc["keyword"] or sc["visual"] or sc["headline"]
    if cfg["visual"] == "ai" and gkey and kw:
        try:
            dest.write_bytes(aimedia.image(f"{kw}. Photorealistic news photo, natural lighting, no text, no logos, no watermark.", aspect, gkey))
            return dest
        except aimedia.AIError as e:
            V._log(f"Cảnh {i + 1}: ảnh AI lỗi, dùng ảnh Pexels — {str(e)[:100]}")
    for attempt in range(3):
        if V.pexels_photo(kw if attempt == 0 else f"{kw} business office", cfg["pexels_key"], True, dest):
            h = hashlib.md5(dest.read_bytes()).hexdigest()
            if h in seen and attempt < 2:
                continue                                   # trùng ảnh cảnh trước → lấy ảnh khác
            seen.add(h)
            return dest
    return article


def render(video_id: int):
    v = db.video_get(video_id)
    cfg = V.get_config()
    scenes = V.clean_scenes(v["scenes"])
    if not scenes:
        raise V.VideoError("Kịch bản chưa có cảnh nào")
    work = V.VIDEO_DIR / str(video_id)
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)

    def step(msg):
        db.video_update(video_id, progress=msg)
        V._log(msg)

    article = None
    if v["image_url"]:
        article = work / "article.img"
        if not V._download(v["image_url"], article):
            article = None
    gkey = newsagent.get_config()["gemini_key"] if cfg["ai_images"] else ""
    style = V.STYLES[cfg["tts_style"]][1]
    items = [(sc, False) for sc in scenes]
    cta_text = (cfg.get("cta_text") or "").strip()
    phone = (cfg.get("sig_phone") or "").strip()
    if cta_text or phone:                                         # cảnh cuối tự thêm: thẻ liên hệ + lời kêu gọi
        spoken = (cta_text.rstrip(". ") + ". " if cta_text else "") + (f"Liên hệ số điện thoại {phone}." if phone else "")
        items.append(({"narration": spoken.strip(), "type": "cta", "hl": [], "keyword": "", "visual": "", "headline": ""}, True))
    durations, seen, total = [], set(), len(items)
    for i, (sc, is_cta) in enumerate(items):
        step(f"Cảnh {i + 1}/{total}: giọng đọc")
        used = V.tts(sc["narration"], cfg["voice"], cfg["rate"], work / f"voice{i}.mp3", style)
        if used != V.VOICES.get(cfg["voice"], "").split(" — ")[0]:
            V._log(f"Cảnh {i + 1}: giọng đã chọn lỗi, đã dùng giọng {used}")
        voice_len = V.media_duration(work / f"voice{i}.mp3")
        dur = math.ceil((voice_len + (1.0 if is_cta else 0.3)) * V.FPS) / V.FPS
        captions = []
        if is_cta:
            step(f"Cảnh {i + 1}/{total}: thẻ liên hệ")
            cta_background(cfg, cta_text or "Liên hệ ngay để được hỗ trợ", work / f"bg{i}.png")
        else:
            step(f"Cảnh {i + 1}/{total}: ảnh minh họa")
            photo = _photo_for(i, sc, cfg, work, gkey, article, seen, "9:16")
            stat = (sc["hl"] or [""])[0]
            scene_background(cfg, photo, stat, work / f"bg{i}.png", show_label=photo is not None)
            chunks = news_chunks(sc["narration"], sc["hl"], 5)
            allw = " ".join(chunks).split()
            cols = color_words(allw, sc["hl"])
            times = V.align_words(allw, work / f"voice{i}.mp3", voice_len)
            idx = 0
            for k, ch in enumerate(chunks):
                cw = ch.split()
                pos = chunk_layer(cw, cols[idx:idx + len(cw)], work / f"ch{i}_{k}.png")
                a = 0.0 if idx == 0 else times[idx]
                nxt = idx + len(cw)
                b = times[nxt] if nxt < len(times) else dur
                if pos and b > a:
                    captions.append((f"ch{i}_{k}.png", pos, a, b))
                idx = nxt
        step(f"Cảnh {i + 1}/{total}: dựng video")
        V.render_scene(work, i, SIZE, dur, False, [], captions)
        durations.append(dur)
    music = None
    if cfg["music"] and V._music_files():
        import random
        music = random.choice(V._music_files())
    step("Ghép các cảnh" + (" + nhạc nền" if music else ""))
    out = work / "clip.mp4"
    V.join_scenes(work, durations, out, music, 0.0, ["fade"])
    for p in work.iterdir():
        if p != out:
            p.unlink(missing_ok=True)
    length = sum(durations)
    note = "" if cfg["pexels_key"] or gkey else \
        "Chưa có Pexels API key nên khung ảnh hiện con số chính thay cho ảnh minh họa. Nhập key (miễn phí) ở Cài đặt clip để có ảnh thật."
    db.video_update(video_id, status="done", path=str(out), duration=round(length, 1), progress="", error=note)
    db.log("video", f"Đã dựng clip tin nhanh #{video_id}: {v['title']} ({length:.0f}s)")
    V._log("✅ Xong clip")
