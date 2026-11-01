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
             "generous margin, no text, no letters, no numbers, no watermark. If a person or mascot appears, always use the same recurring "
             "character: a friendly round-faced accountant with big round glasses, an orange tie and a small notebook: ")


def layout(size, n):
    """Khung đặt các hình: [(x, y, w, h)] cho n hình."""
    W, H = size
    vertical = W < H
    pad = int(min(size) * 0.05)
    top, bottom = int(H * (0.19 if vertical else 0.27)), int(H * (0.78 if vertical else 0.82))
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
    ch = min(cw + int(cw * 0.3), (avail_h - gap) // 2)
    if n == 2:
        full = avail_w
        ch = min(int(full * 0.95), (avail_h - gap) // 2)
        return [(pad, top + (avail_h - 2 * ch - gap) // 2 + k * (ch + gap), full, ch) for k in range(2)]
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


def panel_image(art: bytes | None, label: str, size, seed: int, visual: str = "", bg=PAPER) -> Image.Image:
    """Ảnh đặc (nền giấy) của 1 khung: hình minh họa + nhãn bên dưới."""
    w, h = size
    canvas = Image.new("RGB", (w, h), bg)
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
            tile = Image.new("RGB", src.size, bg)
            canvas.paste(ImageChops.multiply(src, tile), ((w - src.width) // 2, (area[1] - src.height) // 2))
            placed = True
        except Exception:  # noqa: BLE001 — ảnh hỏng thì dùng thẻ phác thảo
            placed = False
    if not placed:                                       # không có hình AI: tự vẽ bằng bộ biểu tượng phác thảo
        side = int(min(area) * 0.98)
        canvas.paste(doodle_icons.draw_scene(side, label, visual, seed, bg), ((w - side) // 2, (area[1] - side) // 2))
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


def caption_layer(L, words: list, active: int, dest: Path):
    """Phụ đề chữ đậm màu mực; từ đang được đọc (chỉ số active) được tô vàng như bút dạ quang."""
    ov = Image.new("RGBA", (L.W, L.H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    f = V._font(int(L.base * 0.05), bold=True)
    space = d.textlength(" ", font=f)
    lines, cur, cur_w = [], [], 0.0
    for w in words:
        ww = d.textlength(w, font=f)
        if cur and cur_w + space + ww > L.W - 3 * L.pad:
            lines.append(cur)
            cur, cur_w = [], 0.0
        cur.append((w, ww))
        cur_w += ww + (space if len(cur) > 1 else 0)
    if cur:
        lines.append(cur)
    lines = lines[:3]
    lh = int(f.size * 1.4)
    top = int(L.H * (0.865 if L.vertical else 0.88)) - lh * len(lines) // 2
    wi = 0
    for k, line in enumerate(lines):
        x = (L.W - (sum(w[1] for w in line) + space * (len(line) - 1))) / 2
        y = top + k * lh
        for w, ww in line:
            if wi == active:
                p = int(f.size * 0.12)
                d.rounded_rectangle((x - p, y + lh * 0.12, x + ww + p, y + lh * 0.92), radius=int(p * 0.8), fill=HIGHLIGHT + (255,))
            d.text((x, y + lh / 2), w, font=f, fill=INK, anchor="lm")
            x += ww + space
            wi += 1
    return V._save_layer(ov, dest)


# ---------------------------------------------------------------- dựng 1 trang

def timing(dur: float, n: int):
    """Thời điểm bắt đầu và độ dài "vẽ" của từng hình trong 1 trang: trả về (t0, span, dd)."""
    t0 = 0.5
    span = max(1.2, (dur - 0.9 - t0) / max(1, n))
    return t0, span, min(3.6, max(1.0, span * 0.78))


def wba_python() -> str:
    """Python dùng để chạy whiteboard-animator. Mặc định là Python của phần mềm; đặt biến QC_WBA_PYTHON trong .env
    để trỏ tới một môi trường Python khác (vd Python 3.12) nếu bản Python hiện tại không cài được thư viện này."""
    import sys
    return V.os.environ.get("QC_WBA_PYTHON", "").strip() or sys.executable


def wba_available() -> bool:
    import importlib.util
    import subprocess
    if V.os.environ.get("QC_WBA_PYTHON", "").strip():
        try:
            return subprocess.run([wba_python(), "-c", "import whiteboard_animator"], capture_output=True,
                                  timeout=60).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False
    return importlib.util.find_spec("whiteboard_animator") is not None


def _ffmpeg_shim_dir() -> Path:
    """whiteboard-animator gọi lệnh `ffmpeg` trong PATH: tạo bản sao FFmpeg đi kèm phần mềm với đúng tên đó."""
    import shutil
    from . import config
    d = config.DATA_DIR / "bin"
    d.mkdir(exist_ok=True)
    exe = d / ("ffmpeg.exe" if V.os.name == "nt" else "ffmpeg")
    if not exe.exists():
        shutil.copy2(V.ffmpeg_exe(), exe)
        exe.chmod(0o755)
    return d


def stroke_clip(png: Path, seconds: float, dest: Path, timeout: int = 300) -> bool:
    """Vẽ hình theo từng nét (thư viện whiteboard-animator, MIT, chạy CPU): trả về True nếu tạo được video."""
    import subprocess
    if not wba_available():
        return False
    env = dict(V.os.environ)
    env["PATH"] = str(_ffmpeg_shim_dir()) + V.os.pathsep + env.get("PATH", "")
    kw = {"creationflags": subprocess.CREATE_NO_WINDOW} if V.os.name == "nt" else {}
    try:
        r = subprocess.run([wba_python(), "-m", "whiteboard_animator.cli", str(png), "-o", str(dest),
                            "--duration", f"{seconds:.2f}", "--quality", "low"],
                           capture_output=True, text=True, timeout=timeout, env=env, **kw)
    except (subprocess.TimeoutExpired, OSError):
        return False
    return r.returncode == 0 and dest.exists() and dest.stat().st_size > 0


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


def make_panels(sc, size, work: Path, i: int, gkey: str, log, use_ai: bool, state: AIState = None,
                pen: str = "wipe", dur: float = 0.0):
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
        im = panel_image(art, pv.get("label", ""), boxes[k][2:], seed=i * 10 + k, visual=pv.get("visual", ""))
        vid = None
        if pen == "strokes" and wba_available() and dur:             # vẽ từng nét: cần ảnh nền trắng tinh
            white = panel_image(art, pv.get("label", ""), boxes[k][2:], seed=i * 10 + k, visual=pv.get("visual", ""), bg=(255, 255, 255))
            white.save(work / f"pw{i}_{k}.png", "PNG")
            if stroke_clip(work / f"pw{i}_{k}.png", timing(dur, len(panels))[2], work / f"pv{i}_{k}.mp4"):
                vid = f"pv{i}_{k}.mp4"
            else:
                log(f"Trang {i + 1}, hình {k + 1}: không vẽ từng nét được, dùng kiểu quét nhanh")
        return im, vid

    with ThreadPoolExecutor(max_workers=3 if (use_ai and gkey and not state.off) or pen == "strokes" else 1) as ex:
        imgs = list(ex.map(one, range(len(panels))))
    out = []
    for k, ((im, vid), box) in enumerate(zip(imgs, boxes)):
        name = f"pn{i}_{k}.png"
        im.save(work / name, "PNG")
        reveal_mask(box[2], box[3], work / f"mk{i}_{k}.png")
        out.append((name, box, panels[k].get("label", ""), vid))
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
    t0, span, dd = timing(dur, k_panels)
    hx, hy = hand[1]
    hand_ks, hand_free = [], set()                 # hình cần bàn tay; hand_free = hình vẽ từng nét (tay đi tự do trong khung)
    paper = "r='val*{:.4f}':g='val*{:.4f}':b='val*{:.4f}'".format(*(c / 255 for c in PAPER))
    for k, (name, (x, y, w, h), _label, vid) in enumerate(panels):
        s = t0 + k * span
        if vid:                                    # video do whiteboard-animator vẽ từng nét (tự có bàn tay trong video)
            inputs += ["-i", vid]
            flt.append(f"[{n}:v]fps={fps},scale={w}:{h}:force_original_aspect_ratio=decrease,"
                       f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:white,setsar=1,setpts=PTS-STARTPTS+{s:.2f}/TB,"
                       f"tpad=stop_mode=clone:stop_duration=60,format=rgb24,lutrgb={paper}[pv{n}]")
            flt.append(f"[{cur}][pv{n}]overlay=x={x}:y={y}:enable='gte(t,{s:.2f})':eof_action=repeat[s{n}]")
            cur, n = f"s{n}", n + 1
            hand_ks.append(k)                      # video của công cụ không có bàn tay: thêm bàn tay nguệch ngoạc trong khung
            hand_free.add(k)
            continue
        hand_ks.append(k)
        inputs += ["-framerate", str(fps), "-loop", "1", "-t", d, "-i", name,
                   "-framerate", str(fps), "-loop", "1", "-t", d, "-i", f"mk{i}_{k}.png"]
        p = f"min(1,max(0,(t-{s:.2f})/{dd:.2f}))"
        flt.append(f"[{n}:v]format=rgb24[pa{n}]")
        flt.append(f"[{n + 1}:v]crop=w={w}:h={h}:x='({w}+{SOFT})*(1-{p})':y=0,format=gray[mk{n}]")
        flt.append(f"[pa{n}][mk{n}]alphamerge[pk{n}]")
        flt.append(f"[{cur}][pk{n}]overlay=x={x}:y={y}:eof_action=repeat:format=auto[s{n}]")
        cur, n = f"s{n}", n + 2
    hand_at = n                                    # mỗi lớp bàn tay có 1 đầu vào riêng (tránh bộ tách `split` gây treo FFmpeg)
    for _ in hand_ks:
        inputs += ["-framerate", str(fps), "-loop", "1", "-t", d, "-i", hand[0]]
        n += 1
    for j, k in enumerate(hand_ks):                # bàn tay đi theo mép lộ dần, nguệch ngoạc lên xuống
        name, (x, y, w, h), _label, _vid = panels[k]
        s0 = t0 + k * span
        p = f"min(1,max(0,(t-{s0:.2f})/{dd:.2f}))"
        if k in hand_free:
            q = f"(t-{s0:.2f})"
            hxx = f"{x}+{w}*(0.5+0.38*sin({q}*2.3+1))-{hx}"
            hyy = f"{y}+{h}*(0.5+0.34*sin({q}*3.1))-{hy}"
        else:
            hxx = f"{x}+{w}*{p}-{hx}"
            hyy = f"{y}+{h}*(0.5+0.36*sin((t-{s0:.2f})*9))-{hy}"
        flt.append(f"[{hand_at + j}:v]format=rgba[hd{k}]")
        flt.append(f"[{cur}][hd{k}]overlay=x='{hxx}':y='{hyy}':enable='between(t,{s0:.2f},{s0 + dd + 0.12:.2f})':eof_action=repeat[ho{k}]")
        cur = f"ho{k}"
    captions = V.karaoke_captions(L, work, f"dc{i}", sc["narration"], work / f"voice{i}.mp3", dur, voice_len,
                                  lambda w, k, dest: caption_layer(L, w, k, dest), 7)
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
