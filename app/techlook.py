"""Kiểu clip "công nghệ" (tech review) — học theo clip giới thiệu công cụ / repo GitHub: nền xanh đen có lưới + hạt sáng,
nhãn "01 — ÁP DỤNG" + tiêu đề lớn (dòng 2 xanh dương), hàng "chip" có biểu tượng, cửa sổ trình duyệt giả có khung tô sáng
dòng quan trọng, bong bóng chat, nút kêu gọi, phụ đề trắng đậm với từ khóa tô nền xanh.
"""
import math
import random
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from . import explainer as X
from . import video as V

BG = (6, 10, 24)
BLUE, BLUE2 = (78, 146, 255), (70, 190, 255)
GOLD, GOLD2 = (255, 176, 56), (255, 226, 96)
RED, GREEN, ORANGE = (244, 112, 104), (84, 206, 128), (255, 170, 70)
WHITE, GRAY, DIM = (245, 247, 252), (150, 162, 186), (96, 106, 130)
CARD = (16, 22, 44, 230)
CARD_EDGE = (60, 74, 120, 255)
KEYBOX = (36, 104, 232)


def background(size, dest: Path, seed: int = 0):
    w, h = int(size[0] * V.OVERSIZE), int(size[1] * V.OVERSIZE)
    rng = random.Random(seed)
    img = Image.new("RGB", (w, h), BG)
    glow = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(glow)
    cx, cy = rng.uniform(0.3, 0.7) * w, rng.uniform(0.3, 0.6) * h
    d.ellipse((cx - w * 0.45, cy - h * 0.25, cx + w * 0.45, cy + h * 0.25), fill=200)
    img = Image.composite(Image.new("RGB", (w, h), (16, 36, 84)), img, glow.filter(ImageFilter.GaussianBlur(min(w, h) * 0.22)))
    grid = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    g = ImageDraw.Draw(grid)
    step = max(40, min(w, h) // 12)
    for x in range(0, w, step):
        g.line((x, 0, x, h), fill=(110, 140, 220, 14))
    for y in range(0, h, step):
        g.line((0, y, w, y), fill=(110, 140, 220, 14))
    img = Image.alpha_composite(img.convert("RGBA"), grid)
    dots = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    dd = ImageDraw.Draw(dots)
    for _ in range(26):                                   # hạt sáng mờ
        r = rng.uniform(3, 14)
        x, y = rng.uniform(0, w), rng.uniform(0, h)
        dd.ellipse((x - r, y - r, x + r, y + r), fill=(90, 140, 255, rng.randint(24, 70)))
    img = Image.alpha_composite(img, dots.filter(ImageFilter.GaussianBlur(3)))
    img.convert("RGB").save(dest, "PNG")


# ---------------------------------------------------------------- biểu tượng nhỏ

def icon(d, name: str, cx, cy, r, color=WHITE):
    w = max(2, int(r * 0.16))
    if name == "lock":
        d.rounded_rectangle((cx - r * 0.7, cy - r * 0.1, cx + r * 0.7, cy + r * 0.85), radius=r * 0.18, fill=ORANGE + (255,))
        d.arc((cx - r * 0.45, cy - r * 0.85, cx + r * 0.45, cy + r * 0.2), 180, 360, fill=ORANGE + (255,), width=w + 1)
    elif name == "check":
        d.rounded_rectangle((cx - r * 0.85, cy - r * 0.85, cx + r * 0.85, cy + r * 0.85), radius=r * 0.25, fill=GREEN + (255,))
        d.line((cx - r * 0.45, cy, cx - r * 0.1, cy + r * 0.4, cx + r * 0.5, cy - r * 0.35), fill=(8, 40, 24), width=w + 1)
    elif name == "warn":
        d.polygon([(cx, cy - r), (cx + r * 1.05, cy + r * 0.85), (cx - r * 1.05, cy + r * 0.85)], fill=ORANGE + (255,))
        d.line((cx, cy - r * 0.35, cx, cy + r * 0.3), fill=(60, 30, 0), width=w + 1)
        d.ellipse((cx - w * 0.7, cy + r * 0.5, cx + w * 0.7, cy + r * 0.5 + w * 1.4), fill=(60, 30, 0))
    elif name == "star":
        pts = []
        for k in range(10):
            a = -math.pi / 2 + k * math.pi / 5
            rr = r if k % 2 == 0 else r * 0.45
            pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
        d.polygon(pts, fill=GOLD2 + (255,))
    elif name == "search":
        d.ellipse((cx - r * 0.8, cy - r * 0.8, cx + r * 0.3, cy + r * 0.3), outline=BLUE2 + (255,), width=w + 2, fill=(180, 230, 255, 90))
        d.line((cx + r * 0.2, cy + r * 0.2, cx + r * 0.85, cy + r * 0.85), fill=BLUE2 + (255,), width=w + 3)
    elif name == "globe":
        d.ellipse((cx - r * 0.85, cy - r * 0.85, cx + r * 0.85, cy + r * 0.85), outline=BLUE2 + (255,), width=w + 1)
        d.ellipse((cx - r * 0.4, cy - r * 0.85, cx + r * 0.4, cy + r * 0.85), outline=BLUE2 + (255,), width=w)
        d.line((cx - r * 0.85, cy, cx + r * 0.85, cy), fill=BLUE2 + (255,), width=w)
    elif name == "play":
        d.rounded_rectangle((cx - r * 0.85, cy - r * 0.6, cx + r * 0.85, cy + r * 0.6), radius=r * 0.2, fill=(150, 90, 200, 255))
        d.polygon([(cx - r * 0.25, cy - r * 0.3), (cx - r * 0.25, cy + r * 0.3), (cx + r * 0.35, cy)], fill=WHITE + (255,))
    elif name == "bell":
        d.pieslice((cx - r * 0.7, cy - r * 0.8, cx + r * 0.7, cy + r * 0.6), 180, 360, fill=GOLD + (255,))
        d.rectangle((cx - r * 0.7, cy - r * 0.1, cx + r * 0.7, cy + r * 0.45), fill=GOLD + (255,))
        d.ellipse((cx - r * 0.2, cy + r * 0.45, cx + r * 0.2, cy + r * 0.85), fill=GOLD + (255,))
    elif name == "chat":
        d.rounded_rectangle((cx - r * 0.85, cy - r * 0.7, cx + r * 0.85, cy + r * 0.35), radius=r * 0.3, fill=GRAY + (255,))
        d.polygon([(cx - r * 0.4, cy + r * 0.3), (cx - r * 0.6, cy + r * 0.85), (cx, cy + r * 0.3)], fill=GRAY + (255,))
    elif name == "no":
        d.ellipse((cx - r * 0.85, cy - r * 0.85, cx + r * 0.85, cy + r * 0.85), outline=RED + (255,), width=w + 2)
        d.line((cx - r * 0.6, cy + r * 0.6, cx + r * 0.6, cy - r * 0.6), fill=RED + (255,), width=w + 2)
    elif name == "bolt":
        d.polygon([(cx + r * 0.2, cy - r), (cx - r * 0.6, cy + r * 0.1), (cx - r * 0.05, cy + r * 0.1), (cx - r * 0.2, cy + r), (cx + r * 0.6, cy - r * 0.2), (cx + r * 0.05, cy - r * 0.2)], fill=GOLD2 + (255,))
    elif name == "doc":
        d.rounded_rectangle((cx - r * 0.65, cy - r * 0.85, cx + r * 0.65, cy + r * 0.85), radius=r * 0.12, fill=WHITE + (255,))
        for k in range(3):
            d.line((cx - r * 0.4, cy - r * 0.4 + k * r * 0.4, cx + r * 0.4, cy - r * 0.4 + k * r * 0.4), fill=DIM + (255,), width=w)
    else:                                                  # chấm tròn mặc định
        d.ellipse((cx - r * 0.5, cy - r * 0.5, cx + r * 0.5, cy + r * 0.5), fill=BLUE + (255,))


ICON_NAMES = {"lock", "check", "warn", "star", "search", "globe", "play", "bell", "chat", "no", "bolt", "doc", "dot"}


def split_chip(text: str):
    a, _, b = text.partition("|")
    return (a.strip().lower(), b.strip()) if b and a.strip().lower() in ICON_NAMES else ("dot", text.strip())


# ---------------------------------------------------------------- khối giao diện

class Layers(X.Cards):
    pass


def _wrap(d, text, font, width, limit):
    return V._wrap(d, text, font, width)[:limit]


def header(L, sc, i: int, work: Path):
    """Nhãn + tiêu đề (dòng 1 trắng, dòng 2 xanh dương) + logo cho cảnh mở đầu. Trả về (vị trí, đáy tiêu đề)."""
    ov = Image.new("RGBA", (L.W, L.H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    hero = sc["type"] == "hero"
    y = int(L.H * (0.17 if hero else 0.085))
    pad = L.pad
    if hero:
        r = int(L.base * 0.055)
        d.rounded_rectangle((pad, y - r, pad + 2 * r, y + r), radius=int(r * 0.4), fill=(14, 22, 48, 255))
        d.arc((pad + r * 0.3, y - r * 0.7, pad + r * 1.7, y + r * 0.7), 20, 340, fill=BLUE + (255,), width=3)
        d.ellipse((pad + r * 0.45, y - r * 0.12, pad + r * 0.75, y + r * 0.18), fill=BLUE2 + (255,))
        if sc["tag"]:
            img = X.cond_text(sc["tag"], int(L.base * 0.052), grad=(BLUE, BLUE2), scale=1.0)
            ov.alpha_composite(img, (pad + 2 * r + int(r * 0.4), y - img.height // 2))
        y += int(r * 1.9)
    elif sc["tag"]:
        f = V._font(int(L.base * 0.034), bold=True)
        d.text((pad, y), sc["tag"].upper(), font=f, fill=BLUE + (255,), anchor="lm")
        y += int(L.base * 0.06)
    lines = X.split_heading(sc["headline"])[:2]
    size = int(L.base * (0.108 if hero else 0.085))
    for k, line in enumerate(lines):
        kw = {"grad": (BLUE, BLUE2)} if k == 1 or (len(lines) == 1 and not hero) else {"fill": WHITE}
        img = X._fit(line, size, L.W - 2 * pad, scale=1.0, **kw)
        ov.alpha_composite(img, (pad, int(y)))
        y += int(img.height * 1.08)
    return V._save_layer(ov, work / f"th{i}.png"), int(y)


def chip(d, box, text: str, border=RED, fill=(34, 18, 32, 235)):
    name, label = split_chip(text)
    x0, y0, x1, y1 = box
    d.rounded_rectangle(box, radius=(y1 - y0) // 2.6, fill=fill, outline=border + (255,), width=3)
    r = (y1 - y0) * 0.26
    icon(d, name, x0 + (y1 - y0) * 0.55, (y0 + y1) / 2, r)
    size = int((y1 - y0) * 0.42)
    room = x1 - x0 - (y1 - y0) * 1.25
    f = V._font(size, bold=True)
    while d.textlength(label, font=f) > room and size > 12:      # chữ dài thì thu nhỏ cho vừa chip
        size -= 1
        f = V._font(size, bold=True)
    d.text((x0 + (y1 - y0) * 1.0, (y0 + y1) / 2), label, font=f, fill=WHITE + (255,), anchor="lm")


def chips_layers(c: X.Cards, L, chips: list, top: int, cols: int = 2, start=0.5, border=RED, spread=True):
    if not chips:
        return top
    rows = (len(chips) + cols - 1) // cols
    gap = int(L.pad * 0.3)
    cw = (L.W - 2 * L.pad - gap * (cols - 1)) // cols
    ch = int(L.base * (0.1 if cols == 2 else 0.085))
    for k, t in enumerate(chips):
        ov = c.new()
        r_, c_ = divmod(k, cols)
        x0 = L.pad + c_ * (cw + gap)
        y0 = top + r_ * (ch + gap)
        chip(ImageDraw.Draw(ov), (x0, y0, x0 + cw, y0 + ch), t, border)
        c.add(ov, (c.when(k, len(chips), start) if spread else start + 0.18 * k), "pop")
    return top + rows * (ch + gap)


def browser(c: X.Cards, L, sc, top: int, bottom: int, start=0.45):
    """Cửa sổ trình duyệt giả: thanh địa chỉ + nội dung dạng trang tài liệu, dòng focus có khung tô sáng."""
    W = L.W
    x0, x1 = L.pad, W - L.pad
    lines = sc["items"][:6]
    f = V._font(int(L.base * 0.032 * getattr(L, "ts", 1.0)))
    ft = V._font(int(L.base * 0.045 * getattr(L, "ts", 1.0)), bold=True)
    meas = ImageDraw.Draw(c.new())
    tw = x1 - x0 - 3 * L.pad
    wrapped = [_wrap(meas, t, f, tw, 3) for t in lines]
    lh = int(f.size * 1.35)
    bar = int(L.base * 0.075)
    title = sc["url_title"] or ""
    body_h = (int(ft.size * 1.8) if title else 0) + sum(len(w) * lh + int(lh * 0.55) for w in wrapped) + L.pad
    y1 = min(bottom, top + bar + body_h)
    ov = c.new()
    d = ImageDraw.Draw(ov)
    d.rounded_rectangle((x0 + 6, top + 10, x1 + 6, y1 + 10), radius=18, fill=(0, 0, 0, 120))
    d.rounded_rectangle((x0, top, x1, y1), radius=18, fill=(236, 238, 244, 255))
    d.rounded_rectangle((x0, top, x1, top + bar), radius=18, fill=(28, 32, 48, 255))
    d.rectangle((x0, top + bar - 18, x1, top + bar), fill=(28, 32, 48, 255))
    for k, col in enumerate(((255, 95, 86), (255, 189, 46), (39, 201, 63))):
        d.ellipse((x0 + 20 + k * 26, top + bar / 2 - 7, x0 + 34 + k * 26, top + bar / 2 + 7), fill=col + (255,))
    d.rounded_rectangle((x0 + 100, top + bar * 0.2, x1 - 16, top + bar * 0.8), radius=int(bar * 0.3), fill=(46, 52, 72, 255))
    d.text((x0 + 120, top + bar / 2), sc["url"] or "github.com", font=V._font(int(bar * 0.34)), fill=(220, 226, 240, 255), anchor="lm")
    y = top + bar + int(L.pad * 0.5)
    if title:
        d.text((x0 + L.pad, y), title, font=ft, fill=(30, 34, 46, 255), anchor="lt")
        y += int(ft.size * 1.8)
    focus_box = None
    for k, ws in enumerate(wrapped):
        ys = y
        d.ellipse((x0 + L.pad * 0.7 - 4, y + lh * 0.45 - 4, x0 + L.pad * 0.7 + 4, y + lh * 0.45 + 4), fill=(60, 66, 84, 255))
        for line in ws:
            d.text((x0 + L.pad * 1.2, y), line, font=f, fill=(40, 46, 62, 255), anchor="lt")
            y += lh
        if k == sc["focus"]:
            focus_box = (x0 + L.pad * 0.45, ys - 6, x1 - L.pad * 0.4, y + 4)
        y += int(lh * 0.55)
    c.add(ov, start, "rise")
    if focus_box:                                         # khung tô sáng hiện sau khi cửa sổ đã lên
        col = {"good": GREEN, "bad": RED}.get(sc["tone"], BLUE)
        ov = c.new()
        d = ImageDraw.Draw(ov)
        d.rounded_rectangle(focus_box, radius=12, fill=col + (40,), outline=col + (255,), width=4)
        c.add(ov, max(start + 1.1, c.span * 0.35), "none")        # khung sáng hiện khi lời đọc tới ý đó
    return y1


def stat_block(c: X.Cards, L, sc, top: int):
    ov = c.new()
    d = ImageDraw.Draw(ov)
    big = X._fit(sc["big"], int(L.base * 0.15), L.W - 2 * L.pad - int(L.base * 0.13), grad=(GOLD, GOLD2), scale=1.0)
    ov.alpha_composite(big, (L.pad + int(L.base * 0.13), top))
    icon(d, "star", L.pad + int(L.base * 0.06), top + big.height * 0.5, int(L.base * 0.05))
    if sc["items"]:
        lab = X._fit(sc["items"][0], int(L.base * 0.07), L.W - 2 * L.pad, grad=(BLUE, BLUE2), scale=1.0)
        ov.alpha_composite(lab, (L.pad, top + big.height + int(L.base * 0.01)))
        bottom = top + big.height + lab.height
    else:
        bottom = top + big.height
    c.add(ov, 0.4, "pop")
    ov = c.new()                                          # biểu đồ đường tăng dần
    d = ImageDraw.Draw(ov)
    cy0, cy1 = bottom + int(L.base * 0.05), bottom + int(L.base * 0.05) + int(L.base * 0.5)
    d.rounded_rectangle((L.pad, cy0, L.W - L.pad, cy1), radius=16, fill=CARD, outline=CARD_EDGE, width=2)
    rng = random.Random(len(sc["big"]) * 7)
    pts, v = [], 0.1
    n = 28
    for k in range(n):
        v = min(0.95, v + rng.uniform(0.0, 0.05) + k / n * 0.025)
        pts.append((L.pad + L.pad * 0.6 + (L.W - 2 * L.pad - 1.2 * L.pad) * k / (n - 1), cy1 - L.pad * 0.6 - (cy1 - cy0 - 1.2 * L.pad) * v))
    for g in range(1, 4):
        yy = cy0 + (cy1 - cy0) * g / 4
        d.line((L.pad * 1.4, yy, L.W - L.pad * 1.4, yy), fill=(60, 74, 120, 90), width=1)
    d.line(pts, fill=BLUE2 + (255,), width=5, joint="curve")
    d.ellipse((pts[-1][0] - 8, pts[-1][1] - 8, pts[-1][0] + 8, pts[-1][1] + 8), fill=GOLD2 + (255,))
    c.add(ov, 0.9, "rise")
    return cy1


def cta_block(c: X.Cards, L, sc, top: int):
    ov = c.new()
    d = ImageDraw.Draw(ov)
    f = V._font(int(L.base * 0.062), bold=True)
    text = sc["items"][0] if sc["items"] else sc["headline"].replace("|", " ")
    lines = _wrap(d, text, f, L.W - 4 * L.pad, 3)
    lh = int(f.size * 1.3)
    bw = min(L.W - 2 * L.pad, int(max(d.textlength(x, font=f) for x in lines)) + 3 * L.pad)
    bh = lh * len(lines) + int(L.pad * 1.1)
    x0 = (L.W - bw) // 2
    d.rounded_rectangle((x0, top, x0 + bw, top + bh), radius=24, fill=WHITE + (255,))
    d.polygon([(x0 + 40, top + bh - 2), (x0 + 22, top + bh + 24), (x0 + 74, top + bh - 2)], fill=WHITE + (255,))
    for k, line in enumerate(lines):
        d.text((L.W / 2, top + L.pad * 0.55 + k * lh + lh / 2), line, font=f, fill=(20, 24, 40, 255), anchor="mm")
    c.add(ov, 0.4, "pop")
    y = top + bh + int(L.pad * 0.8)
    if len(sc["items"]) > 1:
        ov = c.new()
        d = ImageDraw.Draw(ov)
        fs = V._font(int(L.base * 0.04), bold=True)
        tw = d.textlength(sc["items"][1], font=fs)
        icon(d, "chat", L.W / 2 - tw / 2 - 22, y + fs.size / 2, int(fs.size * 0.5))
        d.text((L.W / 2 - tw / 2, y + fs.size / 2), sc["items"][1], font=fs, fill=GRAY + (255,), anchor="lm")
        c.add(ov, 0.9, "rise")
        y += int(fs.size * 2)
    btn = next((t for t in sc["chips"][:1]), "")
    if btn:
        ov = c.new()
        d = ImageDraw.Draw(ov)
        name, label = split_chip(btn)
        fb = V._font(int(L.base * 0.048), bold=True)
        w = int(d.textlength(label, font=fb)) + int(L.base * 0.2)
        h = int(L.base * 0.115)
        x0 = (L.W - w) // 2
        d.rounded_rectangle((x0, y, x0 + w, y + h), radius=h // 2, fill=(36, 118, 255, 255))
        icon(d, name if name != "dot" else "bell", x0 + h * 0.55, y + h / 2, h * 0.24)
        d.text((x0 + h * 0.95, y + h / 2), label, font=fb, fill=WHITE + (255,), anchor="lm")
        c.add(ov, 1.4, "pop")
        y += h
    return y


def caption_layer(L, words: list, active: int, dest: Path):
    """Phụ đề trắng đậm; từ đang được đọc (chỉ số active) nổi lên trên nền xanh."""
    if not words:
        return None
    size = int(L.base * 0.056 * getattr(L, "ts", 1.0))
    f = V._font(size, bold=True)
    ov = Image.new("RGBA", (L.W, L.H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    space = d.textlength(" ", font=f)
    lines, cur, cur_w = [], [], 0.0
    for w in words:
        ww = d.textlength(w, font=f)
        if cur and cur_w + space + ww > L.W - 2.5 * L.pad:
            lines.append(cur)
            cur, cur_w = [], 0.0
        cur.append((w, ww))
        cur_w += ww + (space if len(cur) > 1 else 0)
    lines.append(cur)
    lh = int(size * 1.4)
    top = int(L.H * 0.875) - lh * len(lines) // 2
    wi = 0
    for li, line in enumerate(lines):
        x = (L.W - (sum(w[1] for w in line) + space * (len(line) - 1))) / 2
        y = top + li * lh
        bg = Image.new("RGBA", (L.W, L.H), (0, 0, 0, 0))
        ImageDraw.Draw(bg).rounded_rectangle((x - 18, y - 4, x + sum(w[1] for w in line) + space * (len(line) - 1) + 18, y + lh - 6),
                                             radius=14, fill=(0, 0, 0, 120))
        ov.alpha_composite(bg)
        for w, ww in line:
            if wi == active:
                d.rounded_rectangle((x - 6, y + 2, x + ww + 6, y + lh - 8), radius=8, fill=KEYBOX + (255,))
            d.text((x, y + lh / 2 - 2), w, font=f, fill=WHITE + (255,), anchor="lm")
            x += ww + space
            wi += 1
    return V._save_layer(ov, dest)


def build(L, sc, i: int, total: int, work: Path, brand: str, dur: float, voice_len: float):
    layers = []
    pos, hb = header(L, sc, i, work)
    if pos:
        layers.append((f"th{i}.png", pos, 0.0, "head"))
    c = X.Cards(L, work, i, voice_len)
    top = hb + int(L.base * 0.05)
    bottom = int(L.H * 0.80)
    typ = sc["type"]
    recap_pos = None
    if sc.get("recap"):
        recap_pos = X.recap_layer(L, sc["recap"], work / f"tr{i}.png", BLUE)
        if recap_pos[0]:
            bottom = min(bottom, recap_pos[1] - int(L.pad * 0.5))
    if typ == "hero":
        top = chips_layers(c, L, sc["chips"] or sc["items"], top, 2, 0.5)
    elif typ == "stat" and sc["big"]:
        bot = stat_block(c, L, sc, top)
        chips_layers(c, L, sc["chips"], bot + int(L.base * 0.05), 1, 1.4, border=BLUE)
    elif typ == "browser" and sc["items"]:
        bot = browser(c, L, sc, top, bottom - int(L.base * 0.2) if sc["chips"] else bottom)
        chips_layers(c, L, sc["chips"], bot + int(L.base * 0.045), 1 if len(sc["chips"]) < 3 else 2, 1.8,
                     border={"good": GREEN, "bad": RED}.get(sc["tone"], BLUE))
    elif typ == "cta":
        cta_block(c, L, sc, top + int(L.base * 0.1))
    elif typ == "flow" and sc["items"]:
        X._flow(c, sc, top, bottom)
    elif typ == "steps" and sc["items"]:
        X._steps(c, sc, top, bottom)
    elif typ == "calc" and sc["items"]:
        X._calc(c, sc, top, bottom)
    elif sc["items"]:
        X._list(c, sc, top, bottom)
    elif sc["chips"]:
        chips_layers(c, L, sc["chips"], top, 1, 0.5, border=BLUE)
    layers += c.out
    if recap_pos and recap_pos[0]:
        layers.append((f"tr{i}.png", recap_pos[0], max(1.0, voice_len * 0.6), "rise"))
    note = sc.get("note") or ("* Ví dụ minh hoạ" if typ == "browser" else "")
    if note:
        ov = c.new()
        ImageDraw.Draw(ov).text((L.pad, int(L.H * 0.805)), note, font=V._font(int(L.base * 0.028)), fill=DIM + (255,), anchor="lm")
        pos = V._save_layer(ov, work / f"tn{i}.png")
        if pos:
            layers.append((f"tn{i}.png", pos, 0.5, "none"))
    captions = V.karaoke_captions(L, work, f"tc{i}", sc["narration"], work / f"voice{i}.mp3", dur, voice_len,
                                  lambda w, k, dest: caption_layer(L, w, k, dest), 5)
    return layers, captions
