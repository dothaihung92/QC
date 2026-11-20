"""Kiểu clip "Tin nhanh" (bản tin ngắn 9:16): nửa trên là ẢNH MINH HỌA đổi theo từng ý, nửa dưới nền xanh với CHỮ TO NHẤN MẠNH
những cụm quan trọng (con số vàng, hành động cam) chạy đúng theo lời đọc; cảnh cuối là thẻ liên hệ + lời kêu gọi.

AI chỉ chọn lọc những ý QUAN TRỌNG của bài (ai – việc gì – con số – mốc thời gian – doanh nghiệp cần làm), mỗi cảnh 1 câu ngắn.
Kèm sẵn nội dung đăng Facebook: câu tiêu đề + đường kẻ + chữ ký thương hiệu (tên, giới thiệu, địa chỉ, hotline) + hashtag.
"""
import html as htmllib
import math
import re
import shutil
import unicodedata
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

from . import aimedia, db, imgsearch, newsagent
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
- "query": cụm TÌM ẢNH bằng TIẾNG VIỆT 3–6 từ cho đúng ý của cảnh (vd "cơ quan thuế hoàn thuế", "hóa đơn điện tử", "kế toán làm việc văn phòng"), không chứa con số hay tên riêng quá hiếm; mỗi cảnh một cụm KHÁC nhau.
- "hl": 1–3 cụm từ viết NGUYÊN VĂN như trong "narration" cần nhấn mạnh trên màn hình (con số, hành động chính, vd "từ chối hoàn", "10.000 tỷ đồng").
- "headline": 1–2 câu (tối đa 40 từ) tóm tắt tin để làm dòng đầu bài đăng Facebook, có con số chính, trung thực, không emoji, không giật tít sai sự thật.
- "hashtags": 3–4 hashtag không dấu viết liền dạng CamelCase (vd #HoanThue #HoaDonDauVao).
- Không tự thêm cảnh giới thiệu công ty hay kêu gọi liên hệ (phần mềm tự thêm cảnh cuối).
{brand}
Trả về JSON: {{"title": "tiêu đề ngắn của clip", "headline": "...", "hashtags": ["#..."],
 "scenes": [{{"narration": "...", "keyword": "english stock photo keywords", "query": "cụm tìm ảnh tiếng Việt", "hl": ["cụm nhấn mạnh"]}}]}}

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


# Khi phải dùng lại một ảnh cho nhiều cảnh: mỗi lần cắt một chỗ khác (toàn ảnh / phóng to trái / phóng to phải / cận giữa) để nhìn khác nhau
CROPS = [(1.0, 0.5, 0.4), (1.45, 0.2, 0.3), (1.45, 0.8, 0.35), (1.9, 0.5, 0.5), (1.45, 0.5, 0.75), (1.7, 0.15, 0.6), (1.7, 0.85, 0.6)]


def _cover(path: Path, w: int, h: int, variant: int = 0):
    from PIL import Image, ImageOps
    im = Image.open(path)
    im = ImageOps.exif_transpose(im).convert("RGB")
    zoom, cx, cy = CROPS[variant % len(CROPS)]
    if zoom > 1.0:                                           # cắt một vùng rồi phóng ra khung
        cw, ch = im.width / zoom, im.height / zoom
        x0 = min(max(0, im.width * cx - cw / 2), im.width - cw)
        y0 = min(max(0, im.height * cy - ch / 2), im.height - ch)
        im = im.crop((int(x0), int(y0), int(x0 + cw), int(y0 + ch)))
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


def scene_background(cfg: dict, photo, stat_text: str, dest: Path, label: str = LABEL, variant: int = 0):
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
        img.paste(_cover(photo, W - sx, ph - hh, variant), (sx, hh))
    else:
        img.paste(_stat_panel(W - sx, ph - hh, stat_text, cfg), (sx, hh))
    if label:
        f = V._font(int(H * 0.0155), bold=True)
        d.text((int(W * 0.06), hh // 2), label, font=f, fill=(235, 240, 255), anchor="lm")
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


# ---------------------------------------------------------------- ảnh trong bài viết

_BAD_IMG = re.compile(r"logo|icon|avatar|sprite|banner|(?<![a-z])ads?[-_/]|advert|pixel|tracking|spacer|blank|loading|placeholder|emoji|badge|button|share|social|qr|favicon", re.I)


class _Imgs(HTMLParser):
    def __init__(self, base: str):
        super().__init__(convert_charrefs=True)
        self.base, self.found, self.meta = base, [], []
        self._art = 0
        self._ld = False
        self._ldtxt = ""

    def handle_data(self, data):
        if self._ld:
            self._ldtxt += data

    def handle_endtag(self, tag):
        if tag == "article" and self._art:
            self._art -= 1
        elif tag == "script" and self._ld:                       # JSON-LD: nhiều báo khai báo toàn bộ ảnh bài ở đây
            self._ld = False
            for u in re.findall(r'https?://[^"\s\\]+?\.(?:jpe?g|png|webp)(?:\?[^"\s\\]*)?', self._ldtxt.replace("\\/", "/"), re.I):
                self.meta.append(u)
            self._ldtxt = ""

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        if tag == "article":
            self._art += 1
        if tag == "script" and "ld+json" in a.get("type", ""):
            self._ld, self._ldtxt = True, ""
        elif tag == "source" and a.get("srcset"):                # <picture><source srcset=...>
            best = max(((float(re.sub(r"[^\d.]", "", w) or 0), u) for u, _, w in (q.strip().partition(" ") for q in a["srcset"].split(",") if q.strip())), default=(0, ""))
            if best[1] and not best[1].startswith("data:"):
                self.found.append((urljoin(self.base, best[1]), self._art > 0, ""))
        elif tag == "a" and re.search(r"\.(?:jpe?g|png|webp)(?:\?|$)", a.get("href", ""), re.I):   # liên kết phóng to ảnh
            self.found.append((urljoin(self.base, a["href"]), self._art > 0, ""))
        if tag == "meta" and (a.get("property") in ("og:image", "twitter:image") or a.get("name") == "twitter:image") and a.get("content"):
            self.meta.append(urljoin(self.base, a["content"]))
        elif tag == "img":
            src = a.get("data-src") or a.get("data-original") or a.get("data-lazy-src") or a.get("src") or ""
            ss = a.get("srcset") or a.get("data-srcset") or ""
            if ss:                                                   # lấy bản lớn nhất trong srcset
                best = max(((float(re.sub(r"[^\d.]", "", w) or 0), u) for u, _, w in
                            (p.strip().partition(" ") for p in ss.split(",") if p.strip())), default=(0, ""))
                src = best[1] or src
            if not src or src.startswith("data:"):
                return
            try:
                w, h = int(re.sub(r"\D", "", a.get("width", "")) or 0), int(re.sub(r"\D", "", a.get("height", "")) or 0)
            except ValueError:
                w = h = 0
            if (w and w < 250) or (h and h < 150):
                return
            self.found.append((urljoin(self.base, src), self._art > 0, a.get("alt", "")))


def article_images(url: str, limit: int = 12) -> list:
    """Địa chỉ các ảnh nằm trong bài báo: ảnh đại diện (og:image) trước, rồi ảnh trong nội dung bài (bỏ logo, icon, quảng cáo...)."""
    from . import backlinks
    try:
        status, final, body = backlinks.fetch_page(url)
    except backlinks.FetchError:
        return []
    if status >= 400:
        return []
    p = _Imgs(final)
    try:
        p.feed(body)
    except Exception:  # noqa: BLE001
        pass
    inside = [u for u, art, _alt in p.found if art]
    rest = [u for u, art, _alt in p.found if not art]
    out, seen = [], set()
    for u in [*p.meta[:1], *inside, *p.meta[1:], *rest[:6]]:
        path = urlparse(u).path.lower()
        key = re.sub(r"[-_]?\d{2,4}x\d{2,4}", "", path)             # cùng ảnh ở nhiều kích thước → giữ 1
        if not u.startswith("http") or path.endswith((".svg", ".gif", ".ico")) or _BAD_IMG.search(path) or key in seen:
            continue
        seen.add(key)
        out.append(u)
    return out[:limit]


def _fetch_image(url: str, referer: str, dest: Path, min_w: int = 360, min_h: int = 240) -> bool:
    """Tải ảnh (có Referer của bài — nhiều báo chặn tải trực tiếp); bỏ ảnh quá nhỏ và địa chỉ nội bộ."""
    from PIL import Image
    from . import backlinks
    try:
        backlinks._public_host(urlparse(url).hostname or "")
        r = requests.get(url, headers={"User-Agent": newsagent.UA, "Referer": referer or url, "Accept": "image/*"}, timeout=30, stream=True)
        ct = (r.headers.get("Content-Type") or "").split(";")[0].lower()
        if r.status_code >= 400 or not ct.startswith("image/") or "svg" in ct or "gif" in ct:
            return False
        data = b""
        for chunk in r.iter_content(1 << 16):
            data += chunk
            if len(data) > 15 * 1024 * 1024:
                return False
        dest.write_bytes(data)
        with Image.open(dest) as im:
            return im.width >= min_w and im.height >= min_h
    except (requests.RequestException, OSError, ValueError, backlinks.FetchError):
        return False


# ---------------------------------------------------------------- dựng clip

GENERIC_KW = ["tax office accounting", "business meeting", "calculator money documents", "invoice paperwork desk", "company building city",
              "laptop spreadsheet finance", "handshake partnership", "government building", "office team working", "coins savings growth",
              "businessman signing contract", "financial report charts"]


class Photos:
    """Kho ảnh của clip: mọi cảnh đều phải có ảnh. Thứ tự: ảnh trong bài → ảnh AI (nếu bật) → Pexels (nhiều từ khóa, ảnh khác nhau)
    → dùng lại ảnh đã có nhưng CẮT Ở CHỖ KHÁC → ảnh đại diện của bài → (cuối cùng) ô con số."""

    def __init__(self, cfg: dict, work: Path, gkey: str, article, pool: list, title: str = ""):
        self.cfg, self.work, self.gkey, self.article, self.title = cfg, work, gkey, article, title
        self.pool, self.gallery, self.seen, self.uses = list(pool), list(pool), set(), {}
        self.pexels_ok = self.pexels_fail = self.web_ok = self.web_fail = 0
        self.web_cache, self.web_used, self.hashes = {}, set(), []
        for path, _label in pool:                                         # dấu vân ảnh trong bài: ảnh tìm trên web phải KHÁC những ảnh này
            try:
                self.hashes.append(imgsearch.ahash(path))
            except Exception:  # noqa: BLE001
                pass

    def _web(self, i: int, sc: dict):
        """Tìm ảnh trên web (Google / Bing) cùng chủ đề cảnh, khác mọi ảnh đã dùng. Trả (đường dẫn, nhãn) hoặc None."""
        q = imgsearch.scene_query(sc, self.title)
        if not q:
            return None
        if q not in self.web_cache:
            self.web_cache[q] = imgsearch.search(q, self.cfg, 10)
        tries = 0
        for c in self.web_cache[q]:
            if c["url"] in self.web_used or tries >= 6:
                continue
            tries += 1
            dest = self.work / f"web{i}_{tries}.img"
            if not _fetch_image(c["url"], c.get("page", ""), dest, 480, 300):
                continue
            try:
                h = imgsearch.ahash(dest)
            except Exception:  # noqa: BLE001
                continue
            if any(imgsearch.similar(h, o) for o in self.hashes):
                continue                                                  # giống ảnh đã có → lấy ảnh khác
            self.hashes.append(h)
            self.web_used.add(c["url"])
            host = (urlparse(c.get("page") or c["url"]).hostname or "").removeprefix("www.")
            return dest, (f"ẢNH: {host.upper()}" if host else "ẢNH TRÊN WEB")
        return None

    def _reuse(self, i: int):
        if not self.gallery:
            return None
        path, label = self.gallery[i % len(self.gallery)]
        n = self.uses.get(str(path), 0)
        self.uses[str(path)] = n + 1
        return path, label, n % len(CROPS)

    def get(self, i: int, sc: dict, aspect: str = "9:16"):
        """(đường dẫn ảnh | None, nhãn, kiểu cắt)"""
        import hashlib
        if i < len(self.pool):                                           # mỗi cảnh một ảnh trong bài, theo thứ tự
            path, label = self.pool[i]
            self.uses[str(path)] = self.uses.get(str(path), 0) + 1
            return path, label, 0
        if self.cfg.get("web_images", True):
            got = self._web(i, sc)
            if got:
                self.gallery.append(got)
                self.web_ok += 1
                return got[0], got[1], 0
            self.web_fail += 1
        dest = self.work / f"photo{i}.img"
        kw = sc.get("keyword") or sc.get("visual") or sc.get("headline") or ""
        if self.cfg["visual"] == "ai" and self.gkey and kw:
            try:
                dest.write_bytes(aimedia.image(f"{kw}. Photorealistic news photo, natural lighting, no text, no logos, no watermark.", aspect, self.gkey))
                self.gallery.append((dest, LABEL))
                return dest, LABEL, 0
            except aimedia.AIError as e:
                V._log(f"Cảnh {i + 1}: ảnh AI lỗi, dùng ảnh Pexels — {str(e)[:100]}")
        if self.cfg["pexels_key"]:
            tries = [kw, f"{kw} business", GENERIC_KW[i % len(GENERIC_KW)], GENERIC_KW[(i + 5) % len(GENERIC_KW)]]
            for k, q in enumerate(x for x in tries if x):
                if V.pexels_photo(q, self.cfg["pexels_key"], True, dest):
                    h = hashlib.md5(dest.read_bytes()).hexdigest()
                    if h in self.seen:
                        continue                                         # trùng ảnh đã dùng → thử từ khóa khác
                    self.seen.add(h)
                    keep = self.work / f"pex{i}.img"
                    dest.replace(keep)
                    try:
                        self.hashes.append(imgsearch.ahash(keep))
                    except Exception:  # noqa: BLE001
                        pass
                    self.gallery.append((keep, LABEL))
                    self.pexels_ok += 1
                    return keep, LABEL, 0
                if V.pexels_last["err"]:
                    break                                                # key sai / hết lượt: không thử tiếp từ khóa khác
            self.pexels_fail += 1
        r = self._reuse(i)
        if r:
            return r
        return (self.article, LABEL, 0) if self.article else (None, LABEL, 0)


def _article_pool(opts: dict, work: Path) -> list:
    """Tải các ảnh trong bài (đã lưu ở options.images) → [(đường dẫn, nhãn nguồn)] — ảnh hỏng / quá nhỏ bị bỏ."""
    pool, ref = [], opts.get("article_url") or ""
    src = (urlparse(ref).hostname or "").removeprefix("www.")
    for k, u in enumerate(opts.get("images") or []):
        dest = work / f"art{k}.img"
        if _fetch_image(u, ref, dest):
            pool.append((dest, f"ẢNH: {src.upper()}" if src else "ẢNH TRONG BÀI"))
    return pool


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
    opts = v.get("options") or {}
    step("Tải ảnh trong bài viết")
    pool = _article_pool(opts, work)
    if opts.get("images") and not pool:
        V._log("Không tải được ảnh nào trong bài (báo chặn tải ảnh hoặc ảnh quá nhỏ) — dùng ảnh Pexels / ảnh đại diện")
    gkey = newsagent.get_config()["gemini_key"] if cfg["ai_images"] else ""
    style = V.STYLES[cfg["tts_style"]][1]
    items = [(sc, False) for sc in scenes]
    cta_text = (cfg.get("cta_text") or "").strip()
    phone = (cfg.get("sig_phone") or "").strip()
    if cta_text or phone:                                         # cảnh cuối tự thêm: thẻ liên hệ + lời kêu gọi
        spoken = (cta_text.rstrip(". ") + ". " if cta_text else "") + (f"Liên hệ số điện thoại {phone}." if phone else "")
        items.append(({"narration": spoken.strip(), "type": "cta", "hl": [], "keyword": "", "visual": "", "headline": ""}, True))
    photos = Photos(cfg, work, gkey, article, pool, v["title"])
    durations, total = [], len(items)
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
            photo, label, variant = photos.get(i, sc)
            stat = (sc["hl"] or [""])[0]
            scene_background(cfg, photo, stat, work / f"bg{i}.png", label if photo is not None else "", variant)
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
    notes = []
    if photos.web_fail and not photos.web_ok and not photos.pexels_ok:
        notes.append("Không tìm được ảnh trên web (Google/Bing có thể đang chặn truy cập tự động) — nhập Google API key + cx ở Cài đặt clip để tìm bằng Google chính thức, hoặc dùng Pexels.")
    if not (cfg["pexels_key"] or gkey or pool or photos.web_ok):
        notes.append("Chưa có Pexels API key nên khung ảnh hiện con số chính thay cho ảnh minh họa. Nhập key (miễn phí) ở Cài đặt clip để có ảnh thật.")
    elif photos.pexels_fail:
        why = V.pexels_last["err"] or "không tìm được ảnh phù hợp"
        notes.append(f"{photos.pexels_fail} cảnh không lấy được ảnh Pexels ({why}) — đã dùng lại ảnh khác của bài (cắt chỗ khác)."
                     if photos.gallery else f"{photos.pexels_fail} cảnh không lấy được ảnh Pexels ({why}) nên hiện ô con số.")
    note = " ".join(notes)
    db.video_update(video_id, status="done", path=str(out), duration=round(length, 1), progress="", error=note)
    db.log("video", f"Đã dựng clip tin nhanh #{video_id}: {v['title']} ({length:.0f}s)")
    V._log("✅ Xong clip")
