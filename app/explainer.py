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


def caption_layer(L, text, dest: Path):
    words = text.split()
    if not words:
        return None
    size = int(L.base * 0.072)
    key = _key_word(words)
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
    marked = False
    for li, line in enumerate(lines):
        total = sum(im.width for _, im in line) + space * (len(line) - 1)
        x = (L.W - total) / 2
        y = top + li * lh
        for w, im in line:
            if w == key and not marked:
                marked = True
                p = int(size * 0.16)
                d.rounded_rectangle((x - p, y - p // 2, x + im.width + p, y + im.height + p), radius=p,
                                    fill=PURPLE + (255,))
            ov.alpha_composite(im, (int(x), int(y + (lh - im.height) / 2 - size * 0.18)))
            x += im.width + space
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
    def __init__(self, L, work: Path, i: int):
        self.L, self.work, self.i, self.out, self.n = L, work, i, [], 0

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


def _list(c: Cards, sc, top, bottom):
    L = c.L
    items = sc["items"][:4]
    f = V._font(int(L.base * (0.052 if len(items) <= 3 else 0.046)))
    meas = ImageDraw.Draw(c.new())
    r = int(L.base * 0.04)
    tw = L.W - 2 * L.pad - 3 * r - L.pad
    rows = [_wrap_text(meas, t, f, tw, 2) for t in items]
    lh = int(f.size * 1.3)
    heights = [max(2 * r, len(w) * lh) + int(L.pad * 0.6) for w in rows]
    gap = int(L.pad * 0.35)
    y = top + max(0, (bottom - top - sum(heights) - gap * (len(rows) - 1)) // 3)
    for k, (lines, h) in enumerate(zip(rows, heights)):
        ov = c.new()
        _glass(ov, (L.pad, y, L.W - L.pad, y + h))
        d = ImageDraw.Draw(ov)
        cx, cy = L.pad + int(L.pad * 0.5) + r, y + h // 2
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=CYAN + (255,))
        d.text((cx, cy), str(k + 1), font=V._font(int(r * 1.15), bold=True), fill=(4, 28, 42), anchor="mm")
        for j, line in enumerate(lines):
            d.text((cx + r + int(L.pad * 0.5), cy + (j - (len(lines) - 1) / 2) * lh), line, font=f, fill=BODY, anchor="lm")
        c.add(ov, 0.4 + 0.5 * k)
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
        c.add(ov, 0.95 + 0.4 * k)


def _steps(c: Cards, sc, top, bottom):
    """Các bước nối nhau bằng đường dọc."""
    L = c.L
    items = sc["items"][:4]
    f = V._font(int(L.base * 0.05))
    meas = ImageDraw.Draw(c.new())
    r = int(L.base * 0.045)
    tw = L.W - 2 * L.pad - 3 * r - L.pad
    rows = [_wrap_text(meas, t, f, tw, 2) for t in items]
    lh = int(f.size * 1.3)
    hs = [max(2 * r + 8, len(w) * lh) for w in rows]
    gap = int(L.pad * 0.55)
    y = top + max(0, (bottom - top - sum(hs) - gap * (len(rows) - 1)) // 3)
    cx = L.pad + r + 6
    for k, (lines, h) in enumerate(zip(rows, hs)):
        ov = c.new()
        d = ImageDraw.Draw(ov)
        if k < len(rows) - 1:
            d.line((cx, y + h // 2, cx, y + h + gap + hs[k + 1] // 2), fill=LINE, width=4)
        d.ellipse((cx - r, y + h // 2 - r, cx + r, y + h // 2 + r), fill=(6, 50, 70, 255), outline=CYAN + (255,), width=4)
        d.text((cx, y + h // 2), str(k + 1), font=V._font(int(r * 1.1), bold=True), fill=CYAN + (255,), anchor="mm")
        for j, line in enumerate(lines):
            d.text((cx + r + int(L.pad * 0.5), y + h // 2 + (j - (len(lines) - 1) / 2) * lh), line, font=f, fill=BODY, anchor="lm")
        c.add(ov, 0.4 + 0.55 * k, "slide")
        y += h + gap


def build(L, sc, i: int, total: int, work: Path, brand: str, dur: float, voice_len: float):
    """Trả về (các lớp hình, các lớp phụ đề) của 1 cảnh kiểu giải thích."""
    layers = []
    pos = heading_layer(L, sc, work / f"xh{i}.png")
    if pos:
        layers.append((f"xh{i}.png", pos, 0.0, "head"))
    top, bottom = int(L.H * 0.255), int(L.H * 0.70)
    c = Cards(L, work, i)
    typ, items = sc["type"], sc["items"]
    if typ == "stat" and sc["big"]:
        _stat(c, sc, top, bottom)
    elif typ == "flow" and items:
        _flow(c, sc, top, bottom)
    elif typ == "steps" and items:
        _steps(c, sc, top, bottom)
    elif items:
        _list(c, sc, top, bottom)
    layers += c.out
    if brand:                                           # tên thương hiệu mờ ở đáy, không chiếm chỗ
        ov = c.new()
        ImageDraw.Draw(ov).text((L.W / 2, int(L.H * 0.935)), brand, font=V._font(int(L.base * 0.03), bold=True),
                                fill=(190, 215, 225, 170), anchor="mm")
        pos = V._save_layer(ov, work / f"xb{i}.png")
        if pos:
            layers.append((f"xb{i}.png", pos, 0.0, "none"))
    captions, chunks = [], V.caption_chunks(sc["narration"], 5)
    weights = [len(ch) + 6 for ch in chunks]
    t = 0.0
    for k, ch in enumerate(chunks):
        end = dur if k == len(chunks) - 1 else t + voice_len * weights[k] / sum(weights)
        p = caption_layer(L, ch, work / f"xc{i}_{k}.png")
        if p:
            captions.append((f"xc{i}_{k}.png", p, t, end))
        t = end
    return layers, captions
