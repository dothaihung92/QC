"""Tạo clip ngắn (Reels / TikTok / Shorts) từ bài viết.

Làm theo quy trình của MoneyPrinterTurbo (github.com/harry0703/MoneyPrinterTurbo) nhưng gọn hơn:
  1. AI (Gemini) viết kịch bản: mỗi cảnh có tiêu đề lớn + lời đọc + từ khóa ảnh
  2. Ảnh nền mỗi cảnh: ảnh của bài viết, ảnh miễn phí Pexels (nếu có key) hoặc nền màu thương hiệu
  3. Giọng đọc tiếng Việt miễn phí bằng Edge-TTS
  4. Chữ trên màn hình + phụ đề vẽ bằng Pillow
  5. Ghép bằng FFmpeg (ảnh trượt chậm, chuyển cảnh mờ dần, nhạc nền nếu có trong data/music)

Thư viện cần thêm (pillow, edge-tts, imageio-ffmpeg — đã kèm sẵn FFmpeg) được cài bằng nút
"Cài công cụ" trong tab Tạo clip, không bắt buộc với các phần khác của phần mềm.
"""
import asyncio
import importlib
import importlib.util
import os
import random
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import requests

from . import config, db, newsagent

VIDEO_DIR = config.DATA_DIR / "videos"
MUSIC_DIR = config.DATA_DIR / "music"
FPS = 30
OVERSIZE = 1.10                      # ảnh nền lớn hơn khung 10% để trượt chậm
SIZES = {"doc": (1080, 1920), "ngang": (1920, 1080)}
VOICES = {"vi-VN-HoaiMyNeural": "Hoài My (nữ)", "vi-VN-NamMinhNeural": "Nam Minh (nam)"}
LENGTHS = {30: 4, 45: 6, 60: 7}      # giây → số cảnh
TOOLS = {"PIL": "pillow", "edge_tts": "edge-tts", "imageio_ffmpeg": "imageio-ffmpeg"}

DEFAULTS = {
    "voice": "vi-VN-HoaiMyNeural",
    "rate": 5,                        # tốc độ đọc, % (-30..+30)
    "format": "doc",                  # doc = 9:16 (Reels/TikTok), ngang = 16:9 (YouTube)
    "brand": "",                      # dòng chữ nhỏ cuối khung: tên Fanpage / số điện thoại
    "color": "#0b4f8a",               # màu thương hiệu (nền + khung tiêu đề)
    "pexels_key": "",                 # tùy chọn: ảnh minh họa miễn phí từ pexels.com
    "music": True,                    # trộn nhạc nền nếu có file trong data/music
}

_lock = threading.Lock()
state = {"busy": False, "log": []}


class VideoError(Exception):
    pass


def _log(msg: str):
    state["log"] = (state["log"] + [f"{time.strftime('%H:%M:%S')}  {msg}"])[-100:]


# ---------------------------------------------------------------- cấu hình / công cụ

def get_config() -> dict:
    cfg = dict(DEFAULTS)
    cfg.update(db.get_setting("video", {}) or {})
    return cfg


def save_config(body: dict) -> dict:
    cur = get_config()
    for k, default in DEFAULTS.items():
        if k not in body:
            continue
        v = body[k]
        if k == "pexels_key" and not str(v or "").strip():
            continue                                  # để trống = giữ key cũ
        if isinstance(default, bool):
            v = bool(v)
        elif isinstance(default, int):
            try:
                v = max(-30, min(30, int(v)))
            except (TypeError, ValueError):
                v = default
        else:
            v = str(v or "").strip()
        cur[k] = v
    if cur["voice"] not in VOICES:
        cur["voice"] = DEFAULTS["voice"]
    if cur["format"] not in SIZES:
        cur["format"] = DEFAULTS["format"]
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", cur["color"]):
        cur["color"] = DEFAULTS["color"]
    db.set_setting("video", cur)
    return public_config()


def missing_tools() -> list:
    return [pkg for mod, pkg in TOOLS.items() if importlib.util.find_spec(mod) is None]


def public_config() -> dict:
    cfg = get_config()
    cfg["has_pexels_key"] = bool(cfg.pop("pexels_key"))
    cfg["voices"] = VOICES
    cfg["lengths"] = list(LENGTHS)
    cfg["missing"] = missing_tools()
    cfg["has_gemini_key"] = bool(newsagent.get_config()["gemini_key"])
    MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    cfg["music_files"] = len(_music_files())
    cfg["music_dir"] = str(MUSIC_DIR)
    cfg["busy"], cfg["log"] = state["busy"], state["log"]
    return cfg


def _run_bg(fn, *args):
    with _lock:
        if state["busy"]:
            raise VideoError("Đang dựng một clip khác — đợi xong rồi thử lại")
        state.update(busy=True, log=[])

    def target():
        try:
            fn(*args)
        except Exception as e:  # noqa: BLE001
            _log(f"⚠ {e}")
        finally:
            state["busy"] = False

    threading.Thread(target=target, daemon=True).start()


def start_install():
    _run_bg(_install)


def _install():
    pkgs = missing_tools()
    if not pkgs:
        _log("Đã có đủ công cụ.")
        return
    _log(f"Đang cài {', '.join(pkgs)} (1-3 phút)...")
    r = subprocess.run([sys.executable, "-m", "pip", "install", *pkgs],
                       capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        raise VideoError("Cài thất bại: " + (r.stderr or r.stdout)[-400:])
    importlib.invalidate_caches()
    _log("✅ Đã cài xong công cụ làm video.")


# ---------------------------------------------------------------- 1. kịch bản

SCRIPT_PROMPT = """Bạn là biên tập viên video ngắn (Facebook Reels / TikTok) cho một công ty dịch vụ kế toán - thuế ở Việt Nam.
Từ nội dung dưới đây, viết kịch bản video khoảng {seconds} giây gồm đúng {n} cảnh.

Quy tắc:
- Cảnh 1: câu mở đầu gây chú ý trong 3 giây đầu (nêu vấn đề / lợi ích cho người xem).
- Các cảnh giữa: mỗi cảnh MỘT ý quan trọng. Giữ ĐÚNG số liệu, mức thuế, ngày hiệu lực, số hiệu văn bản. Không bịa.
- Cảnh cuối: kêu gọi theo dõi Fanpage hoặc nhắn tin để được tư vấn miễn phí.
- narration: lời đọc văn nói tự nhiên, 1-2 câu, tối đa 35 từ.
- headline: chữ lớn trên màn hình, tối đa 8 từ, không lặp nguyên văn lời đọc.
- keyword: 1-3 từ TIẾNG ANH để tìm ảnh minh họa (vd "tax documents", "calculator", "business meeting").
- description: lời giới thiệu đăng kèm video, 2-3 câu, kết bằng 3 hashtag.
{brand}
Trả về DUY NHẤT JSON: {{"title": "...", "description": "...", "scenes": [{{"headline": "...", "narration": "...", "keyword": "..."}}]}}

NỘI DUNG:
{text}
"""


def clean_scenes(scenes) -> list:
    out = []
    for s in scenes or []:
        if not isinstance(s, dict):
            continue
        narration = str(s.get("narration", "")).strip()
        if not narration:
            continue
        out.append({"headline": str(s.get("headline", "")).strip()[:120],
                    "narration": narration[:600],
                    "keyword": str(s.get("keyword", "")).strip()[:60]})
    return out[:12]


def make_script(text: str, seconds: int = 45) -> dict:
    text = (text or "").strip()
    if len(text) < 80:
        raise VideoError("Nội dung quá ngắn để làm clip (cần ít nhất vài câu)")
    seconds = seconds if seconds in LENGTHS else 45
    cfg = get_config()
    brand = f'- Cảnh cuối nhắc tên: "{cfg["brand"]}"\n' if cfg["brand"] else ""
    try:
        out = newsagent.gemini_json(SCRIPT_PROMPT.format(
            seconds=seconds, n=LENGTHS[seconds], brand=brand, text=text[:6000]), newsagent.get_config())
    except RuntimeError as e:
        raise VideoError(str(e)) from e
    scenes = clean_scenes(out.get("scenes"))
    if not scenes:
        raise VideoError("AI không trả về kịch bản hợp lệ, thử lại")
    return {"title": str(out.get("title", "")).strip()[:200],
            "description": str(out.get("description", "")).strip()[:2000], "scenes": scenes}


# ---------------------------------------------------------------- 2. ảnh nền

def _download(url: str, dest: Path) -> bool:
    try:
        r = requests.get(url, headers={"User-Agent": newsagent.UA}, timeout=30)
        r.raise_for_status()
        if not r.headers.get("Content-Type", "image").startswith("image"):
            return False
        dest.write_bytes(r.content)
        return True
    except requests.RequestException:
        return False


def pexels_photo(keyword: str, key: str, vertical: bool, dest: Path) -> bool:
    """Ảnh miễn phí bản quyền từ Pexels (dùng thương mại được, không bắt buộc ghi nguồn)."""
    if not key or not keyword:
        return False
    try:
        r = requests.get("https://api.pexels.com/v1/search", headers={"Authorization": key}, timeout=20,
                         params={"query": keyword, "per_page": 10,
                                 "orientation": "portrait" if vertical else "landscape"})
        photos = r.json().get("photos", []) if r.ok else []
    except (requests.RequestException, ValueError):
        return False
    if not photos:
        return False
    src = random.choice(photos[:5]).get("src", {})
    url = src.get("portrait" if vertical else "landscape") or src.get("large2x") or src.get("original")
    return bool(url) and _download(url, dest)


# ---------------------------------------------------------------- 3. giọng đọc

def tts(text: str, voice: str, rate: int, dest: Path):
    import edge_tts

    async def go():
        await edge_tts.Communicate(text, voice, rate=f"{int(rate):+d}%").save(str(dest))
    try:
        asyncio.run(go())
    except Exception as e:  # noqa: BLE001
        raise VideoError(f"Không tạo được giọng đọc (cần Internet): {e}") from e
    if not dest.exists() or dest.stat().st_size == 0:
        raise VideoError("Không tạo được giọng đọc")


# ---------------------------------------------------------------- 4. vẽ khung hình

FONT_DIRS = [Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts",
             Path("/usr/share/fonts/truetype/dejavu"), Path("/usr/share/fonts/truetype/liberation"),
             Path("/Library/Fonts"), Path("/System/Library/Fonts/Supplemental")]
FONTS_BOLD = ["arialbd.ttf", "segoeuib.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"]
FONTS_REG = ["arial.ttf", "segoeui.ttf", "Arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"]


def _font(size: int, bold=False):
    from PIL import ImageFont
    for name in (FONTS_BOLD if bold else FONTS_REG):
        for d in FONT_DIRS:
            if (d / name).exists():
                return ImageFont.truetype(str(d / name), size)
    return ImageFont.load_default(size)


def _wrap(draw, text: str, font, width: int) -> list:
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if draw.textlength(trial, font=font) <= width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def _hex(color: str):
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


def render_background(image: Path | None, size, color: str, dest: Path):
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps
    w, h = int(size[0] * OVERSIZE), int(size[1] * OVERSIZE)
    img = None
    if image and image.exists():
        try:
            img = Image.open(image).convert("RGB")
        except Exception:  # noqa: BLE001 — ảnh hỏng thì dùng nền màu
            img = None
    if img is not None:
        if img.width / img.height > w / h * 1.6 or img.height / img.width > h / w * 1.6:
            # ảnh lệch khung quá nhiều: nền mờ + ảnh gốc ở giữa (không bị cắt mất nội dung)
            bg = ImageOps.fit(img, (w, h)).filter(ImageFilter.GaussianBlur(40))
            fg = ImageOps.contain(img, (w, int(h * 0.6)))
            bg.paste(fg, ((w - fg.width) // 2, (h - fg.height) // 2))
            img = bg
        else:
            img = ImageOps.fit(img, (w, h))
        img = ImageEnhance.Brightness(img).enhance(0.72)
    else:
        top, bottom = _hex(color), tuple(max(0, int(c * 0.35)) for c in _hex(color))
        col = Image.new("RGB", (1, 256))
        for y in range(256):
            col.putpixel((0, y), tuple(int(top[i] * (1 - y / 255) + bottom[i] * y / 255) for i in range(3)))
        img = col.resize((w, h), Image.BILINEAR)
    img.save(dest, "PNG")


def render_overlay(scene: dict, size, color: str, brand: str, index: int, total: int, dest: Path):
    from PIL import Image, ImageDraw
    W, H = size
    base = min(W, H)
    pad = int(base * 0.06)
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    r, g, b = _hex(color)

    # Tiêu đề lớn: khung màu thương hiệu ở 1/4 trên
    if scene["headline"]:
        f = _font(int(base * (0.085 if index == 0 else 0.072)), bold=True)
        lines = _wrap(d, scene["headline"].upper() if index == 0 else scene["headline"], f, W - 4 * pad)
        lh = int(f.size * 1.25)
        top = int(H * (0.16 if W < H else 0.10))
        half = min(W // 2 - pad, int(max(d.textlength(x, font=f) for x in lines) / 2) + pad)
        d.rounded_rectangle((W // 2 - half, top - pad // 2, W // 2 + half, top + lh * len(lines) + pad // 2),
                            radius=int(base * 0.03), fill=(r, g, b, 225), outline=(255, 255, 255, 110),
                            width=max(2, base // 300))
        for i, line in enumerate(lines):
            d.text((W // 2, top + i * lh + lh // 2), line, font=f, fill="white", anchor="mm")

    # Phụ đề (lời đọc): khung tối phía dưới
    f = _font(int(base * 0.05))
    lines = _wrap(d, scene["narration"], f, W - 4 * pad)[:6]
    lh = int(f.size * 1.35)
    box_h = lh * len(lines) + pad
    bottom = int(H * (0.86 if W < H else 0.88))
    d.rounded_rectangle((pad, bottom - box_h, W - pad, bottom), radius=int(base * 0.025), fill=(0, 0, 0, 170))
    for i, line in enumerate(lines):
        d.text((W // 2, bottom - box_h + pad // 2 + i * lh + lh // 2), line, font=f,
               fill=(255, 255, 255), anchor="mm")

    # Thanh tiến độ + thương hiệu
    bar_y = H - int(base * 0.02)
    d.rectangle((0, bar_y, int(W * (index + 1) / total), H), fill=(r, g, b, 255))
    if brand:
        fb = _font(int(base * 0.032), bold=True)
        d.text((W // 2, bottom + int(base * 0.06)), brand, font=fb, fill=(255, 255, 255, 235), anchor="mm")
    ov.save(dest, "PNG")


# ---------------------------------------------------------------- 5. ghép bằng FFmpeg

def ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        exe = shutil.which("ffmpeg")
        if exe:
            return exe
        raise VideoError("Thiếu FFmpeg — bấm 'Cài công cụ' trong tab Tạo clip")


def _ffmpeg(args: list, cwd: Path):
    kw = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    r = subprocess.run([ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error", *args],
                       cwd=str(cwd), capture_output=True, text=True, timeout=900, **kw)
    if r.returncode != 0:
        raise VideoError("FFmpeg lỗi: " + (r.stderr or "")[-400:])


def media_duration(path: Path) -> float:
    kw = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    r = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", str(path)], capture_output=True, text=True, **kw)
    m = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", r.stderr)
    if not m:
        raise VideoError(f"Không đọc được độ dài {path.name}")
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])


def render_scene(work: Path, i: int, size, duration: float):
    """bg{i}.png trượt chậm + overlay{i}.png đứng yên + voice{i}.mp3 → scene{i}.mp4."""
    W, H = size
    d = f"{duration:.3f}"
    k = f"(t/{d})" if i % 2 == 0 else f"(1-t/{d})"          # đổi hướng trượt mỗi cảnh
    flt = (f"[0:v]crop={W}:{H}:x='(iw-ow)*{k}':y='(ih-oh)*{k}'[b];"
           f"[b][1:v]overlay=0:0,fade=t=in:st=0:d=0.35,format=yuv420p[v];[2:a]apad[a]")
    _ffmpeg(["-loop", "1", "-framerate", str(FPS), "-i", f"bg{i}.png",
             "-loop", "1", "-framerate", str(FPS), "-i", f"overlay{i}.png",
             "-i", f"voice{i}.mp3", "-filter_complex", flt, "-map", "[v]", "-map", "[a]",
             "-t", d, "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
             "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2", f"scene{i}.mp4"], work)


def _music_files() -> list:
    if not MUSIC_DIR.is_dir():
        return []
    return [p for p in MUSIC_DIR.iterdir() if p.suffix.lower() in (".mp3", ".m4a", ".wav", ".aac")]


def join_scenes(work: Path, n: int, out: Path, music: Path | None):
    (work / "list.txt").write_text("".join(f"file 'scene{i}.mp4'\n" for i in range(n)), encoding="utf-8")
    if not music:
        _ffmpeg(["-f", "concat", "-safe", "0", "-i", "list.txt", "-c", "copy",
                 "-movflags", "+faststart", str(out)], work)
        return
    _ffmpeg(["-f", "concat", "-safe", "0", "-i", "list.txt", "-c", "copy", "joined.mp4"], work)
    _ffmpeg(["-i", "joined.mp4", "-stream_loop", "-1", "-i", str(music), "-filter_complex",
             "[1:a]volume=0.12[m];[0:a][m]amix=inputs=2:duration=first:normalize=0[a]",
             "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
             "-movflags", "+faststart", str(out)], work)


# ---------------------------------------------------------------- quy trình dựng clip

def start_render(video_id: int):
    v = db.video_get(video_id)
    if not v:
        raise VideoError("Không có clip này")
    if not v["scenes"]:
        raise VideoError("Kịch bản chưa có cảnh nào")
    if missing_tools():
        raise VideoError("Chưa cài công cụ làm video — bấm 'Cài công cụ' trước")
    db.video_update(video_id, status="rendering", progress="Bắt đầu...", error="")
    try:
        _run_bg(_render_safe, video_id)
    except VideoError:
        db.video_update(video_id, status="draft", progress="")
        raise


def _render_safe(video_id: int):
    try:
        render(video_id)
    except Exception as e:  # noqa: BLE001
        db.video_update(video_id, status="failed", error=str(e)[:400], progress="")
        db.log("error", f"clip #{video_id}: {e}")
        raise


def render(video_id: int):
    v = db.video_get(video_id)
    cfg = get_config()
    size = SIZES[cfg["format"]]
    vertical = size[0] < size[1]
    work = VIDEO_DIR / str(video_id)
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)
    scenes, total = v["scenes"], len(v["scenes"])

    def step(msg):
        db.video_update(video_id, progress=msg)
        _log(msg)

    article_img = None
    if v["image_url"]:
        article_img = work / "article.img"
        if not _download(v["image_url"], article_img):
            article_img = None
    durations = []
    for i, sc in enumerate(scenes):
        step(f"Cảnh {i + 1}/{total}: giọng đọc")
        tts(sc["narration"], cfg["voice"], cfg["rate"], work / f"voice{i}.mp3")
        dur = media_duration(work / f"voice{i}.mp3") + 0.6
        step(f"Cảnh {i + 1}/{total}: hình ảnh")
        img = None
        if pexels_photo(sc["keyword"], cfg["pexels_key"], vertical, work / f"photo{i}.img"):
            img = work / f"photo{i}.img"
        elif article_img and i in (0, total - 1):
            img = article_img
        render_background(img, size, cfg["color"], work / f"bg{i}.png")
        render_overlay(sc, size, cfg["color"], cfg["brand"], i, total, work / f"overlay{i}.png")
        step(f"Cảnh {i + 1}/{total}: dựng video")
        render_scene(work, i, size, dur)
        durations.append(dur)
    step("Ghép các cảnh" + (" + nhạc nền" if cfg["music"] and _music_files() else ""))
    music = random.choice(_music_files()) if cfg["music"] and _music_files() else None
    out = work / "clip.mp4"
    join_scenes(work, total, out, music)
    for p in work.iterdir():                          # dọn file tạm, chỉ giữ clip
        if p != out:
            p.unlink(missing_ok=True)
    db.video_update(video_id, status="done", path=str(out), duration=round(sum(durations), 1),
                    progress="")
    db.log("video", f"Đã dựng clip #{video_id}: {v['title']} ({sum(durations):.0f}s)")
    _log("✅ Xong clip")


def delete(video_id: int):
    shutil.rmtree(VIDEO_DIR / str(video_id), ignore_errors=True)
    db.video_delete(video_id)


def to_json(v: dict) -> dict:
    v = dict(v)
    v["has_file"] = bool(v["path"]) and Path(v["path"]).exists()
    v.pop("path", None)
    return v

