"""Kiểu clip "giải thích" (motion graphics) — học theo clip mẫu: nền xanh đậm có vầng sáng, tiêu đề 2 dòng chữ
hẹp đậm (dòng 1 trắng, dòng 2 chuyển màu xanh ngọc), thẻ thông tin kính mờ dựng dần (sơ đồ, danh sách, số lớn),
phụ đề vàng chữ hẹp đậm với từ khóa nổi trên nền tím.

Chữ "hẹp" được tạo bằng cách ép ngang một font đậm có sẵn (Arial / Segoe...) nên luôn đủ dấu tiếng Việt.
"""
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from . import video as V

WHITE = (236, 255, 250)
MINT, CYAN = (120, 255, 205), (40, 205, 255)
GOLD1, GOLD2 = (255, 176, 56), (255, 226, 80)
ORANGE = (245, 184, 76)
YELLOW = (255, 221, 45)
PURPLE = (98, 30, 165)
GLASS = (14, 42, 60, 218)
EDGE = (72, 140, 172, 190)
LINE = (58, 196, 230, 255)
BODY = (232, 242, 247, 255)


# ---------------------------------------------------------------- chữ hẹp, chữ chuyển màu

def cond_text(text: str, size: int, fill=(255, 255, 255), grad=None, scale=0.82, stroke=0) -> Image.Image:
    """Ảnh RGBA của chữ đậm ép ngang. grad=(màu trái, màu phải) để tô chuyển màu."""
    f = V._font(size, bold=True)
    pad = size // 2
    mask = Image.new("L", (int(f.getlength(text)) + 2 * pad, int(size * 1.7)), 0)
    ImageDraw.Draw(mask).text((pad, size * 0.2), text, font=f, fill=255)
    box = mask.getbbox()
    if not box:
        return Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    mask = mask.crop(box)
    mask = mask.resize((max(1, int(mask.width * scale)), mask.height), Image.LANCZOS)
    if stroke:
        mask = ImageFilter.MaxFilter(2 * stroke + 1).filter(mask)
    w, h = mask.size
    if grad:
        strip = Image.new("RGB", (w, 1))
        for x in range(w):
            strip.putpixel((x, 0), V._mix(grad[0], grad[1], x / max(1, w - 1)))
        colour = strip.resize((w, h))
    else:
        colour = Image.new("RGB", (w, h), fill[:3])
    out = colour.convert("RGBA")
    out.putalpha(mask)
    return out


def _fit(text, size, max_w, **kw):
    img = cond_text(text, size, **kw)
    while img.width > max_w and size > 20:
        size = int(size * 0.92)
        img = cond_text(text, size, **kw)
    return img


def split_heading(h: str) -> list:
    h = re.sub(r"\s+", " ", (h or "").replace("\n", "|")).strip()
    if "|" in h:
        return [x.strip() for x in h.split("|") if x.strip()][:2]
    words = h.split()
    if len(words) <= 2:
        return [h] if h else []
    best = min(range(1, len(words)), key=lambda k: abs(len(" ".join(words[:k])) - len(" ".join(words[k:]))))
    return [" ".join(words[:best]), " ".join(words[best:])]


def _put(layer: Image.Image, img: Image.Image, cx=None, x=None, y=0):
    layer.alpha_composite(img, (int(cx - img.width / 2) if cx is not None else int(x), int(y)))


# ---------------------------------------------------------------- nền

def background(size, dest: Path, seed: int = 0):
    """Xanh đậm có vầng sáng xanh ngọc ở một bên (nhích theo từng cảnh để mắt không chán)."""
    import random
    w, h = int(size[0] * V.OVERSIZE), int(size[1] * V.OVERSIZE)
    rng = random.Random(seed)
    base = Image.new("RGB", (w, h), (4, 20, 32))
    blur = int(min(w, h) * 0.2)
    spots = [((16, 96, 122), rng.uniform(0.12, 0.45) * w, rng.uniform(0.25, 0.5) * h, 0.5, 0.36, 235),
             ((10, 66, 98), rng.uniform(0.6, 0.9) * w, rng.uniform(0.55, 0.9) * h, 0.4, 0.3, 190)]
    for colr, cx, cy, rw, rh, strength in spots:
        m = Image.new("L", (w, h), 0)
        ImageDraw.Draw(m).ellipse((cx - rw * w / 2, cy - rh * h / 2, cx + rw * w / 2, cy + rh * h / 2), fill=strength)
        base = Image.composite(Image.new("RGB", (w, h), colr), base, m.filter(ImageFilter.GaussianBlur(blur)))
    base.save(dest, "PNG")


# ---------------------------------------------------------------- tiêu đề, phụ đề

def heading_layer(L, scene, dest: Path, prev_same=False):
    lines = split_heading(scene["headline"])
    if not lines:
        return None
    ov = Image.new("RGBA", (L.W, L.H), (0, 0, 0, 0))
    size = int(L.base * (0.108 if L.vertical else 0.1))
    y = int(L.H * 0.075)
    for k, line in enumerate(lines):
        kw = {"grad": (MINT, CYAN)} if k == 1 or len(lines) == 1 else {"fill": WHITE}
        img = _fit(line.upper(), size, L.W - 2 * L.pad, **kw)
        glow = Image.new("RGBA", img.size, (0, 0, 0, 0))                       # bóng đổ nhẹ cho chữ nổi trên nền
        glow.putalpha(img.getchannel("A").filter(ImageFilter.GaussianBlur(6)).point(lambda v: v // 2))
        _put(ov, glow, cx=L.W / 2, y=y + 6)
        _put(ov, img, cx=L.W / 2, y=y)
        y += int(img.height * 1.12)
    return V._save_layer(ov, dest)


def _key_word(words):
    """Từ khóa tô nền tím: số, viết tắt / tên riêng, hoặc từ dài nhất."""
    for w in words:
        t = re.sub(r"\W", "", w)
        if t and (any(c.isdigit() for c in t) or (len(t) > 1 and t.isupper())):
            return w
    caps = [w for w in words[1:] if w[:1].isupper() and len(w) > 2]
    if caps:
        return caps[0]
    long_ = [w for w in words if len(re.sub(r"\W", "", w)) >= 5]
    return max(long_, key=len) if long_ else max(words, key=len)


def caption_layer(L, words, active, dest: Path):
    """Phụ đề vàng chữ hẹp; từ đang được đọc (chỉ số active) nổi lên trên nền tím."""
    if not words:
        return None
    size = int(L.base * 0.072 * getattr(L, "ts", 1.0))
    imgs = [cond_text(w, size, fill=YELLOW, scale=0.84) for w in words]
    space = int(size * 0.28)
    lines, cur, cur_w = [], [], 0
    for w, im in zip(words, imgs):
        if cur and cur_w + space + im.width > L.W - 2 * L.pad:
            lines.append(cur)
            cur, cur_w = [], 0
        cur.append((w, im))
        cur_w += im.width + (space if len(cur) > 1 else 0)
    lines.append(cur)
    ov = Image.new("RGBA", (L.W, L.H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    lh = int(size * 1.45)
    top = L.cap_y - lh * len(lines) // 2
    wi = 0
    for li, line in enumerate(lines):
        total = sum(im.width for _, im in line) + space * (len(line) - 1)
        x = (L.W - total) / 2
        y = top + li * lh
        for w, im in line:
            if wi == active:
                p = int(size * 0.16)
                d.rounded_rectangle((x - p, y - p // 2, x + im.width + p, y + im.height + p), radius=p,
                                    fill=PURPLE + (255,))
            ov.alpha_composite(im, (int(x), int(y + (lh - im.height) / 2 - size * 0.18)))
            x += im.width + space
            wi += 1
    return V._save_layer(ov, dest)


# ---------------------------------------------------------------- thẻ kính mờ

def _glass(layer, box, radius=None, fill=GLASS, edge=EDGE):
    d = ImageDraw.Draw(layer)
    r = radius or 18
    sh = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((box[0], box[1] + 8, box[2], box[3] + 8), radius=r, fill=(0, 0, 0, 110))
    layer.alpha_composite(sh.filter(ImageFilter.GaussianBlur(10)))
    d.rounded_rectangle(box, radius=r, fill=fill, outline=edge, width=2)


def _wrap_text(d, text, font, width, limit=3):
    return V._wrap(d, text, font, width)[:limit]


def _split_item(t):
    a, _, b = t.partition("|")
    return (a.strip(), b.strip()) if b else ("", a.strip())


class Cards:
    """Gom các lớp của 1 cảnh: mỗi lớp là 1 PNG đã cắt gọn + thời điểm hiện + kiểu chuyển động."""
    def __init__(self, L, work: Path, i: int, span: float = 8.0):
        self.L, self.work, self.i, self.out, self.n = L, work, i, [], 0
        self.span = span                    # độ dài lời đọc của cảnh: các mục hiện dần rải đều theo lời đọc

    def when(self, k: int, n: int, base: float = 0.5) -> float:
        """Giây hiện của mục thứ k trong n mục: mục đầu ngay, các mục sau rải trong ~75% lời đọc."""
        return base + max(0.0, self.span * 0.75 - base) * k / max(1, n)

    def new(self):
        return Image.new("RGBA", (self.L.W, self.L.H), (0, 0, 0, 0))

    def add(self, layer, start, motion="rise"):
        name = f"xl{self.i}_{self.n}.png"
        self.n += 1
        pos = V._save_layer(layer, self.work / name)
        if pos:
            self.out.append((name, pos, start, motion))


def _stat(c: Cards, sc, top, bottom):
    L = c.L
    items = sc["items"]
    ov = c.new()
    y = top
    if len(items) >= 3:                                  # thẻ nhãn nhỏ phía trên (vd "NGUỒN | Nghị định 398")
        lab, val = items[1], items[2]
        ft, fv = V._font(int(L.base * 0.032)), V._font(int(L.base * 0.048))
        box = (L.pad, y, L.W - L.pad, y + int(L.base * 0.2))
        _glass(ov, box)
        d = ImageDraw.Draw(ov)
        d.text((box[0] + L.pad * 0.6, box[1] + L.base * 0.05), lab.upper(), font=ft, fill=ORANGE, anchor="lm")
        d.text((box[0] + L.pad * 0.6, box[1] + L.base * 0.133), val, font=fv, fill=BODY, anchor="lm")
        c.add(ov, 0.2)
        y = box[3] + int(L.base * 0.05)
    ov = c.new()
    big = _fit(sc["big"], int(L.base * 0.26), L.W - 2 * L.pad, grad=(GOLD1, GOLD2), scale=0.86)
    _put(ov, big, cx=L.W / 2, y=y)
    ft = V._font(int(L.base * 0.045))
    d = ImageDraw.Draw(ov)
    ly = y + big.height + int(L.base * 0.07)
    for line in _wrap_text(d, items[0] if items else "", ft, L.W - 3 * L.pad):
        d.text((L.W / 2, ly), line, font=ft, fill=(190, 210, 220, 255), anchor="mm")
        ly += int(ft.size * 1.4)
    c.add(ov, 0.45, "pop")


def _fit_items(c: Cards, items, text_w: int, avail_h: int, gap: int, pad_v: int, lines_d: int = 5):
    """Chia mỗi ý thành (tiêu đề | giải thích), thu nhỏ chữ dần cho tới khi cả danh sách vừa khung.
    Trả về (font tiêu đề, font giải thích, [(dòng tiêu đề, dòng giải thích, chiều cao thẻ)])."""
    L = c.L
    meas = ImageDraw.Draw(c.new())
    parts = [_split_item(t) for t in items]
    scale = 1.9 * getattr(L, "ts", 1.0) / 1.25                  # bắt đầu từ cỡ chữ to nhất rồi thu nhỏ vừa đủ lấp đầy khung
    while True:
        ft = V._font(max(14, min(int(L.base * 0.046 * scale), int(L.base * 0.075))), bold=True)
        fd = V._font(max(12, min(int(L.base * 0.038 * scale), int(L.base * 0.06))))
        lt, ld = int(ft.size * 1.28), int(fd.size * 1.32)
        rows, total = [], 0
        for title, detail in parts:
            if not title:                                  # ý không có tiêu đề: chữ đậm là cả câu
                tl, dl = _wrap_text(meas, detail, ft, text_w, 3), []
            else:
                tl, dl = _wrap_text(meas, title, ft, text_w, 2), _wrap_text(meas, detail, fd, text_w, lines_d)
            h = len(tl) * lt + len(dl) * ld + 2 * pad_v
            rows.append((tl, dl, h))
            total += h
        total += gap * max(0, len(rows) - 1)
        if total <= avail_h or scale < 0.55:
            return ft, fd, rows
        scale *= 0.93


def _list(c: Cards, sc, top, bottom):
    """Danh sách thẻ: số thứ tự + tiêu đề đậm + dòng giải thích chi tiết (viết "Tiêu đề | giải thích")."""
    L = c.L
    items = sc["items"][:5]
    r = int(L.base * 0.04)
    pad_v = int(L.pad * 0.5)
    gap = int(L.pad * 0.3)
    text_w = L.W - 2 * L.pad - 3 * r - L.pad
    ft, fd, rows = _fit_items(c, items, text_w, bottom - top, gap, pad_v)
    lt, ld = int(ft.size * 1.28), int(fd.size * 1.32)
    y = top
    for k, (tl, dl, h) in enumerate(rows):
        ov = c.new()
        _glass(ov, (L.pad, y, L.W - L.pad, y + h))
        d = ImageDraw.Draw(ov)
        cx, cy = L.pad + int(L.pad * 0.5) + r, y + h // 2
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=CYAN + (255,))
        d.text((cx, cy), str(k + 1), font=V._font(int(r * 1.15), bold=True), fill=(4, 28, 42), anchor="mm")
        tx = cx + r + int(L.pad * 0.5)
        ty = y + pad_v
        for line in tl:
            d.text((tx, ty), line, font=ft, fill=WHITE + (255,), anchor="lt")
            ty += lt
        for line in dl:
            d.text((tx, ty), line, font=fd, fill=BODY, anchor="lt")
            ty += ld
        c.add(ov, c.when(k, len(rows), 0.4))
        y += h + gap


def _flow(c: Cards, sc, top, bottom):
    """Sơ đồ cây: ô gốc ở trên, 2-4 ô con bên dưới nối bằng đường kẻ (như clip mẫu)."""
    L = c.L
    items = sc["items"]
    root, kids = items[0], items[1:5]
    if not kids:
        return _list(c, sc, top, bottom)
    n = len(kids)
    ov = c.new()
    rf, ft = V._font(int(L.base * 0.05), bold=True), V._font(int(L.base * 0.038))
    d = ImageDraw.Draw(ov)
    rw = min(L.W - 2 * L.pad, int(d.textlength(root, font=rf)) + 3 * L.pad)
    rh = int(L.base * 0.14)
    rx0 = (L.W - rw) // 2
    _glass(ov, (rx0, top, rx0 + rw, top + rh))
    d.text((L.W / 2, top + rh / 2), root, font=rf, fill=WHITE + (255,), anchor="mm")
    c.add(ov, 0.25)
    gap = int(L.pad * 0.4)
    cw = (L.W - 2 * L.pad - gap * (n - 1)) // n
    ytop = top + rh + int(L.base * 0.12)
    lh = int(ft.size * 1.3)
    meas = ImageDraw.Draw(c.new())
    parts = [_split_item(t) for t in kids]
    bold = V._font(int(ft.size * 1.05), bold=True)
    wrapped = [(_wrap_text(meas, a, bold, cw - L.pad, 2), _wrap_text(meas, b, ft, cw - L.pad, 4)) for a, b in parts]
    ch = int(L.base * 0.05) + max(len(a) + len(b) for a, b in wrapped) * lh + L.pad
    ov = c.new()
    d = ImageDraw.Draw(ov)
    cxs = [L.pad + k * (cw + gap) + cw // 2 for k in range(n)]
    ymid = top + rh + int(L.base * 0.06)
    d.line((L.W // 2, top + rh, L.W // 2, ymid), fill=LINE, width=3)
    d.line((cxs[0], ymid, cxs[-1], ymid), fill=LINE, width=3)
    for cx in cxs:
        d.line((cx, ymid, cx, ytop), fill=LINE, width=3)
    c.add(ov, 0.7, "none")
    for k, ((ta, tb), cx) in enumerate(zip(wrapped, cxs)):
        ov = c.new()
        _glass(ov, (cx - cw // 2, ytop, cx + cw // 2, ytop + ch), radius=14)
        d = ImageDraw.Draw(ov)
        y = ytop + int(L.pad * 0.5)
        for line in ta:
            d.text((cx - cw // 2 + int(L.pad * 0.4), y), line, font=V._font(int(ft.size * 1.05), bold=True), fill=ORANGE, anchor="lt")
            y += lh
        for line in tb:
            d.text((cx - cw // 2 + int(L.pad * 0.4), y), line, font=ft, fill=BODY, anchor="lt")
            y += lh
        c.add(ov, c.when(k + 1, n + 1, 0.95))


def _calc(c: Cards, sc, top, bottom):
    """Ví dụ tính toán từng bước: bảng "Nội dung | Số tiền", dòng cuối là kết quả nổi bật. Mỗi dòng hiện khi lời đọc tới."""
    L = c.L
    rows = [_split_item(t) for t in sc["items"][:6]]
    meas = ImageDraw.Draw(c.new())
    x0, x1 = L.pad, L.W - L.pad
    inner = x1 - x0 - 2 * L.pad
    scale = 1.7 * getattr(L, "ts", 1.0) / 1.25
    while True:
        fl = V._font(max(14, min(int(L.base * 0.042 * scale), int(L.base * 0.062))))
        fv = V._font(max(14, min(int(L.base * 0.05 * scale), int(L.base * 0.072))), bold=True)
        lh = int(max(fl.size, fv.size) * 1.45)
        wrapped = []
        for a, b in rows:                                  # chừa chỗ cho số tiền bên phải rồi mới xuống dòng phần nhãn
            vw = int(meas.textlength(b, font=fv)) if a else 0
            wrapped.append((_wrap_text(meas, a or b, fl, max(int(inner * 0.3), inner - vw - int(L.pad * 0.8)), 3), b if a else ""))
        heights = [max(lh, len(w) * int(fl.size * 1.3)) + int(L.pad * 0.55) for w, _ in wrapped]
        if sum(heights) + L.pad <= bottom - top or scale < 0.55:
            break
        scale *= 0.93
    total_h = sum(heights) + L.pad
    ov = c.new()
    _glass(ov, (x0, top, x1, top + total_h))
    c.add(ov, 0.25, "rise")
    y = top + L.pad // 2
    for k, ((lines, val), h) in enumerate(zip(wrapped, heights)):
        last = k == len(wrapped) - 1 and len(wrapped) > 1
        ov = c.new()
        d = ImageDraw.Draw(ov)
        if last:                                          # dòng kết quả: nền nổi bật
            d.rounded_rectangle((x0 + 10, y, x1 - 10, y + h), radius=14, fill=(255, 190, 70, 60), outline=GOLD1 + (255,), width=3)
        elif k:
            d.line((x0 + L.pad, y, x1 - L.pad, y), fill=(72, 140, 172, 110), width=2)
        for j, line in enumerate(lines):
            d.text((x0 + L.pad, y + h / 2 + (j - (len(lines) - 1) / 2) * int(fl.size * 1.3)), line, font=fl,
                   fill=(255, 235, 190, 255) if last else BODY, anchor="lm")
        if val:
            col = GOLD2 if last else (120, 255, 205)
            d.text((x1 - L.pad, y + h / 2), val, font=fv, fill=col + (255,), anchor="rm")
        c.add(ov, c.when(k, len(wrapped), 0.7), "rise")
        y += h
    return top + total_h


def _steps(c: Cards, sc, top, bottom):
    """Các bước nối nhau bằng đường dọc; mỗi bước có thể kèm giải thích ("Tiêu đề | giải thích")."""
    L = c.L
    items = sc["items"][:5]
    r = int(L.base * 0.042)
    gap = int(L.pad * 0.5)
    text_w = L.W - 2 * L.pad - 3 * r - L.pad
    ft, fd, rows = _fit_items(c, items, text_w, bottom - top, gap, int(L.pad * 0.15))
    lt, ld = int(ft.size * 1.28), int(fd.size * 1.32)
    hs = [max(2 * r + 8, h) for _, _, h in rows]
    y = top
    cx = L.pad + r + 6
    for k, ((tl, dl, _h), h) in enumerate(zip(rows, hs)):
        ov = c.new()
        d = ImageDraw.Draw(ov)
        mid = y + r + 4
        if k < len(rows) - 1:
            d.line((cx, mid, cx, y + h + gap + r + 4), fill=LINE, width=4)
        d.ellipse((cx - r, mid - r, cx + r, mid + r), fill=(6, 50, 70, 255), outline=CYAN + (255,), width=4)
        d.text((cx, mid), str(k + 1), font=V._font(int(r * 1.1), bold=True), fill=CYAN + (255,), anchor="mm")
        ty = y
        for line in tl:
            d.text((cx + r + int(L.pad * 0.5), ty), line, font=ft, fill=WHITE + (255,), anchor="lt")
            ty += lt
        for line in dl:
            d.text((cx + r + int(L.pad * 0.5), ty), line, font=fd, fill=BODY, anchor="lt")
            ty += ld
        c.add(ov, c.when(k, len(rows), 0.4), "slide")
        y += h + gap


def recap_layer(L, text: str, dest: Path, fill=(255, 190, 70)):
    """Khung ghi nhớ nổi bật ("Bác nhớ giúp là ..."): chữ to, nền vàng nhạt, viền vàng."""
    ov = Image.new("RGBA", (L.W, L.H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    f = V._font(int(L.base * 0.046 * getattr(L, "ts", 1.0)), bold=True)
    lines = V._wrap(d, text, f, L.W - 3 * L.pad - int(f.size * 1.6))[:3]
    lh = int(f.size * 1.3)
    h = lh * len(lines) + int(L.pad * 0.9)
    y0 = int(L.H * 0.80) - h
    d.rounded_rectangle((L.pad, y0, L.W - L.pad, y0 + h), radius=20, fill=(60, 44, 10, 235), outline=fill + (255,), width=4)
    d.text((L.pad + int(L.pad * 0.5), y0 + h / 2 - (len(lines) - 1) * lh / 2), "★", font=f, fill=GOLD2 + (255,), anchor="lm")
    for k, line in enumerate(lines):
        d.text((L.pad + int(f.size * 1.5), y0 + L.pad * 0.45 + k * lh + lh / 2), line, font=f, fill=(255, 244, 214, 255), anchor="lm")
    return V._save_layer(ov, dest), y0


def build(L, sc, i: int, total: int, work: Path, brand: str, dur: float, voice_len: float):
    """Trả về (các lớp hình, các lớp phụ đề) của 1 cảnh kiểu giải thích."""
    layers = []
    pos = heading_layer(L, sc, work / f"xh{i}.png")
    if pos:
        layers.append((f"xh{i}.png", pos, 0.0, "head"))
    top, bottom = int(L.H * 0.255), int(L.H * 0.70)
    recap_pos = None
    if sc.get("recap"):
        recap_pos = recap_layer(L, sc["recap"], work / f"xr{i}.png")
        if recap_pos and recap_pos[0]:
            bottom = min(bottom, recap_pos[1] - int(L.pad * 0.5))
    c = Cards(L, work, i, voice_len)
    typ, items = sc["type"], sc["items"]
    if typ == "stat" and sc["big"]:
        _stat(c, sc, top, bottom)
    elif typ == "flow" and items:
        _flow(c, sc, top, bottom)
    elif typ == "steps" and items:
        _steps(c, sc, top, bottom)
    elif typ == "calc" and items:
        _calc(c, sc, top, bottom)
    elif items:
        _list(c, sc, top, bottom)
    layers += c.out
    if recap_pos and recap_pos[0]:
        layers.append((f"xr{i}.png", recap_pos[0], max(1.0, voice_len * 0.6), "rise"))
    if brand:                                           # tên thương hiệu mờ ở đáy, không chiếm chỗ
        ov = c.new()
        ImageDraw.Draw(ov).text((L.W / 2, int(L.H * 0.935)), brand, font=V._font(int(L.base * 0.03), bold=True),
                                fill=(190, 215, 225, 170), anchor="mm")
        pos = V._save_layer(ov, work / f"xb{i}.png")
        if pos:
            layers.append((f"xb{i}.png", pos, 0.0, "keep"))
    captions = V.karaoke_captions(L, work, f"xc{i}", sc["narration"], work / f"voice{i}.mp3", dur, voice_len,
                                  lambda w, k, dest: caption_layer(L, w, k, dest), 5)
    return layers, captions
