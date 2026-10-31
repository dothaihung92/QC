"""Kiểu clip "vẽ tay" (whiteboard doodle) — học theo clip mẫu: nền giấy kem, nhãn + tiêu đề viết ở góc trái có gạch chân,
các hình minh họa phác thảo bằng mực được "vẽ" lần lượt bởi một bàn tay cầm bút, phụ đề đơn giản có tô vàng từ khóa.

Hình minh họa do Gemini vẽ (cần Gemini key, khoảng 0,04 USD/hình); không có hình thì dùng thẻ phác thảo vẽ tay bằng chữ.
"""
import math
import random
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

from . import aimedia, doodle_icons
from . import video as V

PAPER = (247, 243, 226)
INK = (52, 38, 30)
ORANGE = (222, 104, 52)
HIGHLIGHT = (255, 232, 70)
SKIN = (240, 196, 158)
SOFT = 70                                   # độ rộng (px) của mép mờ khi "vẽ" lộ dần
IMG_STYLE = ("Detailed hand-drawn whiteboard doodle illustration, a small rich scene with 3-5 related elements "
             "(characters with expressive faces, objects, icons, arrows, sparkles), black ink outline sketch with flat pastel colour accents "
             "(orange, teal, yellow, pink), cute friendly cartoon style, centered on a plain pure white background with "
             "generous margin, no text, no letters, no numbers, no watermark: ")


def layout(size, n):
    """Khung đặt các hình: [(x, y, w, h)] cho n hình."""
    W, H = size
    vertical = W < H
    pad = int(min(size) * 0.05)
    top, bottom = int(H * (0.2 if vertical else 0.27)), int(H * (0.72 if vertical else 0.8))
    gap = int(pad * 0.6)
    n = max(1, min(4, n))
    if not vertical:
        cw = (W - 2 * pad - gap * (n - 1)) // n
        return [(pad + k * (cw + gap), top, cw, bottom - top) for k in range(n)]
    avail_h, avail_w = bottom - top, W - 2 * pad
    if n == 1:
        s = min(avail_w, avail_h)
        return [((W - s) // 2, top + (avail_h - s) // 2, s, s)]
    cw = (avail_w - gap) // 2
    ch = min(cw + int(cw * 0.12), (avail_h - gap) // 2)
    if n == 2:
        ch = min(int(cw * 1.1), (avail_h - gap) // 2)
        return [((W - cw * 2 - gap) // 2 + k * (cw + gap), top + (avail_h - ch) // 2, cw, ch) for k in range(2)]
    boxes = [(pad + (k % 2) * (cw + gap), top + (k // 2) * (ch + gap), cw, ch) for k in range(4)]
    if n == 3:
        boxes[2] = ((W - cw) // 2, boxes[2][1], cw, ch)
        return boxes[:3]
    return boxes


# ---------------------------------------------------------------- hình trong khung

def _wobbly_rect(d, box, color, width, rng, amp=3):
    x0, y0, x1, y1 = box
    pts = []
    for (ax, ay, bx, by) in ((x0, y0, x1, y0), (x1, y0, x1, y1), (x1, y1, x0, y1), (x0, y1, x0, y0)):
        steps = max(6, int(math.hypot(bx - ax, by - ay) / 40))
        for k in range(steps):
            t = k / steps
            pts.append((ax + (bx - ax) * t + rng.uniform(-amp, amp), ay + (by - ay) * t + rng.uniform(-amp, amp)))
    pts.append(pts[0])
    d.line(pts, fill=color, width=width, joint="curve")


def panel_image(art: bytes | None, label: str, size, seed: int, visual: str = "") -> Image.Image:
    """Ảnh đặc (nền giấy) của 1 khung: hình minh họa + nhãn bên dưới."""
    w, h = size
    canvas = Image.new("RGB", (w, h), PAPER)
    d = ImageDraw.Draw(canvas)
    base = min(w, h)
    label_h = int(base * 0.17) if label else 0
    area = (w, h - label_h)
    placed = False
    if art:
        try:
            import io
            src = Image.open(io.BytesIO(art)).convert("RGB")
            src = ImageOps.contain(src, (int(area[0] * 0.98), int(area[1] * 0.98)))
            tile = Image.new("RGB", src.size, PAPER)
            canvas.paste(ImageChops.multiply(src, tile), ((w - src.width) // 2, (area[1] - src.height) // 2))
            placed = True
        except Exception:  # noqa: BLE001 — ảnh hỏng thì dùng thẻ phác thảo
            placed = False
    if not placed:                                       # không có hình AI: tự vẽ bằng bộ biểu tượng phác thảo
        side = int(min(area) * 0.98)
        canvas.paste(doodle_icons.draw_scene(side, label, visual, seed), ((w - side) // 2, (area[1] - side) // 2))
    if label:
        f = V._font(int(base * 0.062), bold=True)
        lines = V._wrap(d, label, f, w - 20)[:2]
        lh = int(f.size * 1.2)
        y = h - label_h / 2 - lh * (len(lines) - 1) / 2
        tw = max(d.textlength(x, font=f) for x in lines)
        d.rounded_rectangle((w / 2 - tw / 2 - 16, y - lh / 2 - 6, w / 2 + tw / 2 + 16, y + lh * (len(lines) - 0.5) + 2 - lh / 2),
                            radius=12, fill=(255, 241, 150))
        for line in lines:
            d.text((w / 2, y), line, font=f, fill=INK, anchor="mm")
            y += lh
    return canvas


def reveal_mask(w: int, h: int, dest: Path):
    """Ảnh xám rộng 2w+SOFT: trái trắng, phải đen, mép mờ. Cửa sổ w trượt từ phải sang trái = "vẽ" lộ dần từ trái."""
    m = Image.new("L", (2 * w + SOFT, h), 0)
    d = ImageDraw.Draw(m)
    d.rectangle((0, 0, w, h), fill=255)
    for k in range(SOFT):
        d.line((w + k, 0, w + k, h), fill=int(255 * (1 - k / SOFT)))
    m.save(dest, "PNG")


# ---------------------------------------------------------------- bàn tay cầm bút

def hand_image(size: int, dest: Path) -> tuple:
    """Bàn tay hoạt hình cầm bút dạ đỏ. Trả về vị trí đầu bút (hotspot) trong ảnh."""
    S = 4
    n = size * S
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    u = n / 100
    out = (96, 62, 46, 255)
    # cổ tay + bàn tay (từ góc phải-dưới tràn vào)
    d.polygon([(100 * u, 52 * u), (100 * u, 100 * u), (58 * u, 100 * u), (46 * u, 66 * u)], fill=SKIN + (255,), outline=out)
    d.ellipse((34 * u, 36 * u, 74 * u, 76 * u), fill=SKIN + (255,), outline=out, width=int(u * 1.2))
    # bút dạ
    ang = math.radians(42)
    tip = (14 * u, 12 * u)
    length, width = 44 * u, 7 * u
    dx, dy = math.cos(ang), math.sin(ang)
    nx, ny = -dy, dx
    def pt(a, b):
        return (tip[0] + dx * a + nx * b, tip[1] + dy * a + ny * b)
    d.polygon([pt(0, 0), pt(8 * u, -width / 2), pt(8 * u, width / 2)], fill=(40, 28, 24, 255))
    d.polygon([pt(8 * u, -width / 2), pt(length, -width / 2), pt(length, width / 2), pt(8 * u, width / 2)],
              fill=(176, 40, 40, 255), outline=out)
    d.polygon([pt(20 * u, -width / 2), pt(25 * u, -width / 2), pt(25 * u, width / 2), pt(20 * u, width / 2)], fill=(255, 255, 255, 255))
    # ngón tay ôm bút
    for (a, b, r) in ((26, -2, 5.2), (31, 2.5, 5), (22, 3.5, 4.4)):
        cx, cy = pt(a * u, b * u)
        d.ellipse((cx - r * u, cy - r * u, cx + r * u, cy + r * u), fill=SKIN + (255,), outline=out, width=int(u * 1.1))
    img = img.resize((size, size), Image.LANCZOS)
    img.save(dest, "PNG")
    return int(14 * size / 100), int(12 * size / 100)


# ---------------------------------------------------------------- khung cố định + phụ đề

def _cond(text, font, fill, d):
    return d.textlength(text, font=font)


def header_layer(L, sc, i: int, total: int, brand: str, dest: Path):
    ov = Image.new("RGBA", (L.W, L.H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    pad = L.pad
    y = int(L.H * 0.035)
    if sc.get("tag"):
        f = V._font(int(L.base * 0.026), bold=True)
        tw = d.textlength(sc["tag"].upper(), font=f)
        d.rounded_rectangle((pad, y, pad + tw + f.size * 1.4, y + f.size * 1.9), radius=int(f.size), fill=(252, 228, 214),
                            outline=ORANGE, width=2)
        d.text((pad + f.size * 0.7, y + f.size * 0.95), sc["tag"].upper(), font=f, fill=ORANGE, anchor="lm")
    k = 1 + (i * 3) // max(1, total)
    r = int(L.base * 0.011)
    for j in range(3):                                       # 3 chấm: tiến độ các phần
        cx = L.W - pad - (2 - j) * r * 3
        d.ellipse((cx - r, y + r * 1.5 - r, cx + r, y + r * 1.5 + r), fill=ORANGE if j < k else (216, 208, 188))
    f = V._font(int(L.base * 0.056), bold=True)
    lines = V._wrap(d, sc["headline"].replace("|", " "), f, L.W - 2 * pad)[:2]
    ty = int(L.H * 0.075)
    lh = int(f.size * 1.2)
    for n, line in enumerate(lines):
        d.text((pad, ty + n * lh), line, font=f, fill=INK, anchor="lt")
    uy = ty + len(lines) * lh + int(L.base * 0.012)
    rng = random.Random(i)
    pts = [(pad + x, uy + rng.uniform(-2, 2) + math.sin(x / 40) * 2) for x in range(0, int(L.W * 0.38), 12)]
    d.line(pts, fill=ORANGE, width=max(3, L.base // 260))
    if brand:
        fb = V._font(int(L.base * 0.026), bold=True)
        d.text((L.W / 2, int(L.H * 0.955)), brand, font=fb, fill=(150, 130, 110, 200), anchor="mm")
    return V._save_layer(ov, dest)


def _norm(w: str) -> str:
    return re.sub(r"[^\w%/]", "", w).lower()


def highlight_flags(words: list, terms: list) -> list:
    """Đánh dấu các từ thuộc cụm từ khóa (so khớp theo cụm từ liên tiếp, không phân biệt hoa thường / dấu câu)."""
    flags = [False] * len(words)
    norm = [_norm(w) for w in words]
    for t in terms:
        tw = [_norm(x) for x in t.split() if _norm(x)]
        for i in range(len(norm) - len(tw) + 1):
            if tw and norm[i:i + len(tw)] == tw:
                for j in range(len(tw)):
                    flags[i + j] = True
    return flags


def caption_layer(L, words: list, dest: Path):
    """Phụ đề chữ đậm màu mực; words = [(từ, có tô vàng không)] — từ khóa tô vàng như bút dạ quang."""
    ov = Image.new("RGBA", (L.W, L.H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    f = V._font(int(L.base * 0.05), bold=True)
    space = d.textlength(" ", font=f)
    lines, cur, cur_w = [], [], 0.0
    for w, flag in words:
        ww = d.textlength(w, font=f)
        if cur and cur_w + space + ww > L.W - 3 * L.pad:
            lines.append(cur)
            cur, cur_w = [], 0.0
        cur.append((w, flag, ww))
        cur_w += ww + (space if len(cur) > 1 else 0)
    if cur:
        lines.append(cur)
    lines = lines[:3]
    lh = int(f.size * 1.4)
    top = L.cap_y + int(L.H * 0.02) - lh * len(lines) // 2
    for k, line in enumerate(lines):
        x = (L.W - (sum(w[2] for w in line) + space * (len(line) - 1))) / 2
        y = top + k * lh
        for idx, (w, flag, ww) in enumerate(line):
            if flag:
                p = int(f.size * 0.12)
                nxt = idx + 1 < len(line) and line[idx + 1][1]
                d.rounded_rectangle((x - p, y + lh * 0.12, x + ww + (space if nxt else p), y + lh * 0.92),
                                    radius=int(p * 0.8), fill=HIGHLIGHT + (255,))
            d.text((x, y + lh / 2), w, font=f, fill=INK, anchor="lm")
            x += ww + space
    return V._save_layer(ov, dest)


# ---------------------------------------------------------------- dựng 1 trang

class AIState:
    """Dùng chung cho cả clip: lỗi vẽ AI "cứng" (hết hạn mức, sai quyền...) thì dừng thử các hình sau, khỏi chờ vô ích."""
    def __init__(self):
        self.off = False
        self.fails = 0
        self.reason = ""
        self.ok = 0


def _is_hard_error(e: Exception) -> bool:
    msg = str(e).lower()
    return any(k in msg for k in ("quota", "limit: 0", "permission", "api key", "billing", "not found", "not supported",
                                  "http 400", "http 401", "http 403", "http 404"))


def make_panels(sc, size, work: Path, i: int, gkey: str, log, use_ai: bool, state: AIState = None):
    """Tạo ảnh các khung của 1 trang (vẽ AI song song nếu có key). Trả về [(file, (x,y,w,h), label)]."""
    state = state or AIState()
    panels = sc["panels"][:4] or [{"label": t, "visual": ""} for t in sc["items"][:3]] or \
        [{"label": sc["headline"].replace("|", " "), "visual": sc["visual"]}]
    boxes = layout(size, len(panels))

    def one(k):
        art = None
        pv = panels[k]
        if use_ai and gkey and pv.get("visual") and not state.off:
            try:
                art = aimedia.image(IMG_STYLE + pv["visual"], "1:1", gkey)
                state.ok += 1
            except aimedia.AIError as e:
                state.fails += 1
                if not state.reason:
                    state.reason = str(e)[:300]
                if _is_hard_error(e) and not state.ok:
                    state.off = True
                    log(f"⚠ Gemini không vẽ được hình ({str(e)[:200]}) — các hình còn lại dùng bộ hình phác thảo có sẵn.")
                else:
                    log(f"Trang {i + 1}, hình {k + 1}: vẽ AI lỗi, dùng hình phác thảo có sẵn — {str(e)[:140]}")
        return panel_image(art, pv.get("label", ""), boxes[k][2:], seed=i * 10 + k, visual=pv.get("visual", ""))

    with ThreadPoolExecutor(max_workers=3 if use_ai and gkey and not state.off else 1) as ex:
        imgs = list(ex.map(one, range(len(panels))))
    out = []
    for k, (im, box) in enumerate(zip(imgs, boxes)):
        name = f"pn{i}_{k}.png"
        im.save(work / name, "PNG")
        reveal_mask(box[2], box[3], work / f"mk{i}_{k}.png")
        out.append((name, box, panels[k].get("label", "")))
    return out


def render_page(L, sc, i, total, work: Path, dur: float, voice_len: float, brand: str, panels, hand, fps: int, bg_hex: str):
    """Ghép 1 trang bằng FFmpeg: giấy → tiêu đề → từng hình được vẽ lộ dần kèm bàn tay → phụ đề."""
    W, H = L.W, L.H
    d = f"{dur:.3f}"
    inputs = ["-f", "lavfi", "-i", f"color=c={bg_hex}:s={W}x{H}:r={fps}:d={d}"]
    flt, n, cur = [], 1, "0:v"
    pos = header_layer(L, sc, i, total, brand, work / f"dh{i}.png")
    if pos:
        inputs += ["-framerate", str(fps), "-i", f"dh{i}.png"]
        flt.append(f"[{n}:v]format=rgba,loop=loop=-1:size=1:start=0,setpts=N/{fps}/TB,fade=t=in:st=0:d=0.4:alpha=1[l{n}]")
        flt.append(f"[{cur}][l{n}]overlay=x={pos[0]}:y={pos[1]}:eof_action=repeat[s{n}]")
        cur, n = f"s{n}", n + 1
    k_panels = len(panels)
    t0 = 0.5
    span = max(1.2, (dur - 0.9 - t0) / k_panels)
    hx, hy = hand[1]
    for k, (name, (x, y, w, h), _label) in enumerate(panels):
        s = t0 + k * span
        dd = min(3.6, max(1.0, span * 0.78))
        inputs += ["-framerate", str(fps), "-loop", "1", "-t", d, "-i", name,
                   "-framerate", str(fps), "-loop", "1", "-t", d, "-i", f"mk{i}_{k}.png"]
        p = f"min(1,max(0,(t-{s:.2f})/{dd:.2f}))"
        flt.append(f"[{n}:v]format=rgb24[pa{n}]")
        flt.append(f"[{n + 1}:v]crop=w={w}:h={h}:x='({w}+{SOFT})*(1-{p})':y=0,format=gray[mk{n}]")
        flt.append(f"[pa{n}][mk{n}]alphamerge[pk{n}]")
        flt.append(f"[{cur}][pk{n}]overlay=x={x}:y={y}:eof_action=repeat:format=auto[s{n}]")
        cur, n = f"s{n}", n + 2
    hand_at = n                                    # mỗi lớp bàn tay có 1 đầu vào riêng (tránh bộ tách `split` gây treo FFmpeg)
    for _ in panels:
        inputs += ["-framerate", str(fps), "-loop", "1", "-t", d, "-i", hand[0]]
        n += 1
    for k, (name, (x, y, w, h), _label) in enumerate(panels):      # bàn tay đi theo mép lộ dần, nguệch ngoạc lên xuống
        s0 = t0 + k * span
        dd = min(3.6, max(1.0, span * 0.78))
        p = f"min(1,max(0,(t-{s0:.2f})/{dd:.2f}))"
        hxx = f"{x}+{w}*{p}-{hx}"
        hyy = f"{y}+{h}*(0.5+0.36*sin((t-{s0:.2f})*9))-{hy}"
        flt.append(f"[{hand_at + k}:v]format=rgba[hd{k}]")
        flt.append(f"[{cur}][hd{k}]overlay=x='{hxx}':y='{hyy}':enable='between(t,{s0:.2f},{s0 + dd + 0.12:.2f})':eof_action=repeat[ho{k}]")
        cur = f"ho{k}"
    captions, chunks = [], V.caption_chunks(sc["narration"], 7)
    weights = [len(c) + 8 for c in chunks]
    all_words = " ".join(chunks).split()
    flags = highlight_flags(all_words, sc.get("hl") or [])
    t, pos_w = 0.0, 0
    for k, c in enumerate(chunks):
        end = dur if k == len(chunks) - 1 else t + voice_len * weights[k] / sum(weights)
        cw = c.split()
        p = caption_layer(L, list(zip(cw, flags[pos_w:pos_w + len(cw)])), work / f"dc{i}_{k}.png")
        pos_w += len(cw)
        if p:
            captions.append((f"dc{i}_{k}.png", p, t, end))
        t = end
    for name, (x, y), a, b in captions:
        inputs += ["-framerate", str(fps), "-i", name]
        flt.append(f"[{n}:v]format=rgba,loop=loop=-1:size=1:start=0,setpts=N/{fps}/TB[l{n}]")
        flt.append(f"[{cur}][l{n}]overlay=x={x}:y={y}:enable='between(t,{a:.2f},{b:.2f})'[s{n}]")
        cur, n = f"s{n}", n + 1
    inputs += ["-i", f"voice{i}.mp3"]
    flt.append(f"[{cur}]format=yuv420p[v]")
    flt.append(f"[{n}:a]apad,atrim=duration={d}[a]")
    V._ffmpeg([*inputs, "-filter_complex", ";".join(flt), "-map", "[v]", "-map", "[a]", "-t", d, "-r", str(fps),
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
               "-ac", "2", f"scene{i}.mp4"], work)
