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
import math
import os
import random
import re
import shutil
import subprocess
import sys
import threading
import time
import unicodedata
from pathlib import Path

import requests

from . import config, db, newsagent

VIDEO_DIR = config.DATA_DIR / "videos"
MUSIC_DIR = config.DATA_DIR / "music"
FPS = 30
OVERSIZE = 1.10                      # ảnh nền lớn hơn khung 10% để trượt chậm
SIZES = {"doc": (1080, 1920), "ngang": (1920, 1080)}
VOICES = {"vi-VN-HoaiMyNeural": "Hoài My (nữ) — Microsoft, cần Internet",
          "vi-VN-NamMinhNeural": "Nam Minh (nam) — Microsoft, cần Internet",
          # Piper (github.com/OHF-Voice/piper1-gpl): chạy ngay trên máy, không cần Internet sau lần tải đầu
          "piper:vi_VN-vais1000-medium": "VAIS1000 (nữ) — Piper, offline",
          "piper:vi_VN-25hours_single-low": "25hours (nữ) — Piper, offline",
          "piper:vi_VN-vivos-x_low": "VIVOS (nhiều giọng) — Piper, offline"}
EDGE_VOICES = [v for v in VOICES if not v.startswith("piper:")]
PIPER_DIR = config.DATA_DIR / "piper-voices"
OPTIONAL_TOOLS = {"piper": "piper-tts"}                  # cài lỗi (vd Python quá mới) vẫn dùng được giọng khác
LENGTHS = {30: 5, 45: 7, 60: 9, 120: 14, 180: 20}      # giây → số cảnh
TOOLS = {"PIL": "pillow", "edge_tts": "edge-tts", "imageio_ffmpeg": "imageio-ffmpeg",
         "gtts": "gTTS"}                                 # gTTS: giọng dự phòng khi Edge-TTS từ chối

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
    cfg["piper"] = piper_available()
    cfg["piper_downloaded"] = sorted(p.name[:-5] for p in PIPER_DIR.glob("*.onnx")) if PIPER_DIR.is_dir() else []
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


def _pip(pkgs: list):
    return subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", *pkgs],
                          capture_output=True, text=True, timeout=900)


def _install():
    # luôn cài/cập nhật bản mới nhất: Edge-TTS hay phải cập nhật khi Microsoft đổi cách xác thực
    pkgs = list(TOOLS.values())
    _log(f"Đang cài / cập nhật {', '.join(pkgs)} (1-3 phút)...")
    r = _pip(pkgs)
    if r.returncode != 0:
        raise VideoError("Cài thất bại: " + (r.stderr or r.stdout)[-400:])
    _log("Đang cài giọng đọc offline Piper (tùy chọn)...")
    r = _pip(list(OPTIONAL_TOOLS.values()))
    if r.returncode != 0:
        _log("⚠ Không cài được Piper (giọng offline) — vẫn dùng giọng Microsoft / Google được. "
             + (r.stderr or r.stdout)[-200:])
    importlib.invalidate_caches()
    for mod in ("edge_tts", "gtts"):                     # dùng bản vừa cập nhật mà không cần khởi động lại
        if mod in sys.modules:
            try:
                importlib.reload(sys.modules[mod])
            except Exception:  # noqa: BLE001
                pass
    _log("✅ Đã cài / cập nhật xong công cụ làm video.")


def piper_available() -> bool:
    return importlib.util.find_spec("piper") is not None


# ---------------------------------------------------------------- 1. kịch bản

WORDS_PER_SEC = 3.0                  # tốc độ đọc tiếng Việt trung bình của giọng máy (đo từ clip thật)
SCENE_TYPES = ("hook", "stat", "list", "text", "cta")

SCRIPT_PROMPT = """Bạn là biên tập viên video (Facebook Reels / TikTok / YouTube) cho một công ty dịch vụ kế toán - thuế ở Việt Nam.
Từ nội dung dưới đây, viết kịch bản video dài khoảng {seconds} giây gồm đúng {n} cảnh.

ĐỘ DÀI (BẮT BUỘC): tổng lời đọc của cả kịch bản khoảng {total} từ, mỗi cảnh {lo}-{hi} từ.
{expand}
Quy tắc nội dung:
- Cảnh 1 (type "hook"): câu mở đầu gây chú ý trong 3 giây đầu (nêu vấn đề / lợi ích cho người xem).
- Các cảnh giữa: mỗi cảnh một ý. Giữ ĐÚNG số liệu, mức thuế, ngày hiệu lực, số hiệu văn bản. Không bịa số liệu;
  ví dụ tính toán chỉ được dùng nếu ghi rõ "ví dụ".
- Cảnh cuối (type "cta"): kêu gọi theo dõi Fanpage hoặc nhắn tin để được tư vấn miễn phí.

Quy tắc lời đọc (narration) — viết như người dẫn chương trình đang nói, tự nhiên, có cảm xúc:
- Câu ngắn, có từ nối ("Vậy", "Đặc biệt", "Lưu ý nhé"), xưng "bạn".
- KHÔNG viết tắt: viết "thu nhập doanh nghiệp" thay "TNDN", "nghị định" thay "NĐ-CP", "hộ kinh doanh" thay "HKD".
- Ngày tháng viết kiểu nói: "ngày 29 tháng 10 năm 2026". Không emoji, không ký hiệu markdown.

Mỗi cảnh có phần hình trên màn hình:
- type: "hook" | "stat" | "list" | "text" | "cta"
- headline: tiêu đề lớn, tối đa 8 từ.
- big: (cho "stat") con số / tỷ lệ / mốc thời gian nổi bật, tối đa 12 ký tự, vd "30%", "10 tỷ", "29/10/2026".
- items: 2-4 ý ngắn (mỗi ý tối đa 9 từ) hiện thành gạch đầu dòng; với "stat" thì items[0] là chú thích cho con số.
  Cảnh nào cũng phải có items (trừ "hook" có thể để trống).
- keyword: 1-3 từ TIẾNG ANH để tìm video/ảnh minh họa (vd "tax documents", "calculator", "small shop owner").
- description: lời giới thiệu đăng kèm video, 2-3 câu, kết bằng 3 hashtag.
{brand}
Trả về DUY NHẤT JSON: {{"title": "...", "description": "...", "scenes": [{{"type": "hook", "headline": "...",
"narration": "...", "big": "", "items": ["..."], "keyword": "..."}}]}}

NỘI DUNG:
{text}
"""

EXPAND = """Video dài nên phải giải thích ĐẦY ĐỦ, không chỉ tóm tắt: ai được áp dụng, điều kiện, mức ưu đãi cụ thể,
thời gian hiệu lực, cách tính (có ví dụ minh họa ghi rõ là ví dụ), các bước doanh nghiệp cần làm, hồ sơ / thời hạn,
lưu ý và sai lầm thường gặp, câu hỏi hay gặp. Dùng nhiều cảnh "stat" và "list" để màn hình luôn có thông tin."""


def word_count(text: str) -> int:
    return len(re.findall(r"\w+", text or ""))


def estimate_seconds(scenes) -> int:
    return round(sum(word_count(s.get("narration", "")) for s in scenes) / WORDS_PER_SEC + 0.6 * len(scenes))


def clean_scenes(scenes) -> list:
    out = []
    for s in scenes or []:
        if not isinstance(s, dict):
            continue
        narration = str(s.get("narration", "")).strip()
        if not narration:
            continue
        items = s.get("items") or []
        if isinstance(items, str):
            items = items.splitlines()
        items = [str(x).strip(" -•*\t")[:90] for x in items if str(x).strip(" -•*\t")][:4]
        typ = str(s.get("type", "")).strip().lower()
        out.append({"type": typ if typ in SCENE_TYPES else ("stat" if s.get("big") else "list" if items else "text"),
                    "headline": str(s.get("headline", "")).strip()[:120],
                    "narration": narration[:900],
                    "big": str(s.get("big", "")).strip()[:16],
                    "items": items,
                    "keyword": str(s.get("keyword", "")).strip()[:60]})
    return out[:30]


def make_script(text: str, seconds: int = 45) -> dict:
    text = (text or "").strip()
    if len(text) < 80:
        raise VideoError("Nội dung quá ngắn để làm clip (cần ít nhất vài câu)")
    seconds = seconds if seconds in LENGTHS else 45
    n = LENGTHS[seconds]
    total = int(seconds * WORDS_PER_SEC)
    per = total / n
    cfg = get_config()
    brand = f'- Cảnh cuối nhắc tên: "{cfg["brand"]}"\n' if cfg["brand"] else ""
    prompt = SCRIPT_PROMPT.format(seconds=seconds, n=n, total=total, lo=int(per * 0.8), hi=int(per * 1.25),
                                  expand=EXPAND if seconds >= 90 else "", brand=brand, text=text[:12000])
    best = None
    for attempt in range(2):          # AI hay viết quá ngắn: thiếu thì yêu cầu viết lại 1 lần
        try:
            out = newsagent.gemini_json(prompt, newsagent.get_config())
        except RuntimeError as e:
            if best:
                break
            raise VideoError(str(e)) from e
        scenes = clean_scenes(out.get("scenes"))
        words = sum(word_count(s["narration"]) for s in scenes)
        if scenes and (not best or words > best[1]):
            best = (out, words, scenes)
        if scenes and words >= total * 0.8 and len(scenes) >= n * 0.8:
            break
        prompt += (f"\n\nLƯU Ý: bản trước chỉ có {len(scenes)} cảnh / {words} từ — QUÁ NGẮN. Viết lại đủ {n} cảnh "
                   f"và khoảng {total} từ lời đọc, giải thích chi tiết hơn.")
    if not best:
        raise VideoError("AI không trả về kịch bản hợp lệ, thử lại")
    out, words, scenes = best
    return {"title": str(out.get("title", "")).strip()[:200],
            "description": str(out.get("description", "")).strip()[:2000], "scenes": scenes}


# ---------------------------------------------------------------- 2. hình nền: video / ảnh Pexels, ảnh của bài

def _download(url: str, dest: Path, kind: str = "image") -> bool:
    try:
        with requests.get(url, headers={"User-Agent": newsagent.UA}, timeout=60, stream=True) as r:
            r.raise_for_status()
            if not r.headers.get("Content-Type", kind).startswith(kind):
                return False
            with open(dest, "wb") as f:
                for chunk in r.iter_content(1 << 16):
                    f.write(chunk)
        return dest.stat().st_size > 0
    except (requests.RequestException, OSError):
        return False


def _pexels(path: str, key: str, params: dict) -> list:
    try:
        r = requests.get(f"https://api.pexels.com/{path}", headers={"Authorization": key}, timeout=20, params=params)
        return r.json().get("videos" if "videos" in path else "photos", []) if r.ok else []
    except (requests.RequestException, ValueError):
        return []


def pexels_video(keyword: str, key: str, size, dest: Path, used: set) -> bool:
    """Video ngắn miễn phí bản quyền từ Pexels (giống MoneyPrinterTurbo) — làm nền sống động nhất."""
    if not key or not keyword:
        return False
    vertical = size[0] < size[1]
    vids = _pexels("videos/search", key, {"query": keyword, "per_page": 15, "size": "medium",
                                          "orientation": "portrait" if vertical else "landscape"})
    random.shuffle(vids)
    for v in vids:
        if v.get("id") in used or (v.get("duration") or 0) < 4:
            continue
        files = [f for f in v.get("video_files", []) if f.get("file_type") == "video/mp4" and f.get("width")]
        good = [f for f in files if min(f["width"], f["height"]) >= min(size) * 0.6]
        if not good:
            continue
        f = min(good, key=lambda f: f["width"] * f["height"])      # bản nhỏ nhất đủ nét: tải nhanh
        if _download(f["link"], dest, "video"):
            used.add(v.get("id"))
            return True
    return False


def pexels_photo(keyword: str, key: str, vertical: bool, dest: Path) -> bool:
    """Ảnh miễn phí bản quyền từ Pexels (dùng thương mại được, không bắt buộc ghi nguồn)."""
    if not key or not keyword:
        return False
    photos = _pexels("v1/search", key, {"query": keyword, "per_page": 10,
                                        "orientation": "portrait" if vertical else "landscape"})
    if not photos:
        return False
    src = random.choice(photos[:5]).get("src", {})
    url = src.get("portrait" if vertical else "landscape") or src.get("large2x") or src.get("original")
    return bool(url) and _download(url, dest)


# ---------------------------------------------------------------- 3. giọng đọc

def clean_tts_text(text: str) -> str:
    """Bỏ emoji, ký hiệu markdown... — Edge-TTS hay trả "No audio was received" khi gặp chúng."""
    text = re.sub(r"[#*_`>|~^=\[\]{}<]+", " ", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) not in ("So", "Sk", "Cs", "Co", "Cn", "Cf"))
    return re.sub(r"\s+", " ", text).strip()


def _edge(text: str, voice: str, rate: str, dest: Path):
    import edge_tts

    async def go():
        await edge_tts.Communicate(text, voice, rate=rate).save(str(dest))
    asyncio.run(go())


def _gtts(text: str, dest: Path):
    from gtts import gTTS
    gTTS(text=text, lang="vi").save(str(dest))


_piper_cache = {}


def _piper_voice(name: str):
    """Nạp giọng Piper; lần đầu tự tải mô hình (~20-60 MB) từ Hugging Face về data/piper-voices."""
    if name in _piper_cache:
        return _piper_cache[name]
    if not piper_available():
        raise VideoError("Chưa cài Piper — bấm 'Cài / cập nhật công cụ'")
    from piper import PiperVoice
    from piper.download_voices import download_voice
    PIPER_DIR.mkdir(parents=True, exist_ok=True)
    model = PIPER_DIR / f"{name}.onnx"
    if not model.exists() or not (PIPER_DIR / f"{name}.onnx.json").exists():
        _log(f"Đang tải giọng {name} lần đầu (vài chục MB)...")
        download_voice(name, PIPER_DIR)
    _piper_cache[name] = PiperVoice.load(str(model))
    return _piper_cache[name]


def _piper(text: str, voice: str, rate: int, dest: Path):
    import wave
    from piper import SynthesisConfig
    v = _piper_voice(voice.split(":", 1)[1])
    wav = dest.with_suffix(".wav")
    cfg = SynthesisConfig(length_scale=1 / (1 + max(-30, min(30, rate)) / 100))
    with wave.open(str(wav), "wb") as f:
        v.synthesize_wav(text, f, syn_config=cfg)
    _ffmpeg(["-i", wav.name, "-c:a", "libmp3lame", "-q:a", "3", dest.name], dest.parent)
    wav.unlink(missing_ok=True)


def tts(text: str, voice: str, rate: int, dest: Path) -> str:
    """Tạo giọng đọc, thử lần lượt tới khi được. Giọng Microsoft: giọng đã chọn → tốc độ chuẩn →
    giọng Microsoft còn lại → Piper offline (nếu đã cài) → Google. Giọng Piper: Piper → Microsoft → Google.
    Trả về tên giọng đã dùng."""
    text = clean_tts_text(text)
    if not text:
        raise VideoError("Lời đọc trống sau khi bỏ ký tự đặc biệt")
    label = lambda v: VOICES.get(v, v).split(" — ")[0]
    piper_fallback = next((v for v in VOICES if v.startswith("piper:") and
                           (PIPER_DIR / f"{v[6:]}.onnx").exists()), None)
    if voice.startswith("piper:"):
        attempts = [(label(voice), lambda: _piper(text, voice, rate, dest)),
                    (label(EDGE_VOICES[0]), lambda: _edge(text, EDGE_VOICES[0], "+0%", dest))]
    else:
        other = next((v for v in EDGE_VOICES if v != voice), EDGE_VOICES[0])
        attempts = [(label(voice), lambda: _edge(text, voice, f"{int(rate):+d}%", dest)),
                    (label(voice), lambda: _edge(text, voice, "+0%", dest)),
                    (label(other), lambda: _edge(text, other, "+0%", dest))]
        if piper_fallback and piper_available():
            attempts.append((label(piper_fallback), lambda: _piper(text, piper_fallback, rate, dest)))
    attempts.append(("Google", lambda: _gtts(text, dest)))
    errors = []
    for i, (name, fn) in enumerate(attempts):
        if i:
            time.sleep(1.5)
        dest.unlink(missing_ok=True)
        try:
            fn()
            if dest.exists() and dest.stat().st_size > 0:
                return name
            errors.append(f"{name}: tệp rỗng")
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}: {str(e)[:120]}")
    raise VideoError("Không tạo được giọng đọc. Bấm 'Cài / cập nhật công cụ' rồi thử lại, hoặc chọn giọng "
                     "Piper (offline). Chi tiết: " + " | ".join(errors))


SAMPLE = ("Xin chào, đây là giọng đọc thử cho Fanpage kế toán. Từ ngày một tháng bảy năm hai nghìn "
          "không trăm hai mươi sáu, doanh nghiệp nhỏ được giảm thuế.")


def voice_sample(voice: str, rate: int) -> Path:
    if voice not in VOICES:
        raise VideoError("Giọng không hợp lệ")
    d = VIDEO_DIR / "_nghe-thu"
    d.mkdir(parents=True, exist_ok=True)
    dest = d / f"{re.sub(r'[^A-Za-z0-9_-]', '_', voice)}.mp3"
    used = tts(SAMPLE, voice, rate, dest)
    if used != VOICES[voice].split(" — ")[0]:
        raise VideoError(f"Giọng này đang lỗi (đã phải dùng {used}) — xem thông báo ở ô Cài đặt clip")
    return dest


# ---------------------------------------------------------------- 4. vẽ khung hình (Pillow)
# Mỗi cảnh gồm nhiều lớp PNG nhỏ (đã cắt sát nội dung) để FFmpeg ghép và tạo chuyển động:
# nền trượt chậm → khung cố định → tiêu đề trượt vào → thẻ thông tin hiện lên → từng ý hiện lần lượt
# → phụ đề chạy theo lời đọc.

FONT_DIRS = [Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts",
             Path("/usr/share/fonts/truetype/dejavu"), Path("/usr/share/fonts/truetype/liberation"),
             Path("/Library/Fonts"), Path("/System/Library/Fonts/Supplemental")]
FONTS_BOLD = ["arialbd.ttf", "segoeuib.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"]
FONTS_REG = ["arial.ttf", "segoeui.ttf", "Arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"]
FONTS_BLACK = ["ariblk.ttf", "seguibl.ttf", "Arial Black.ttf"] + FONTS_BOLD
HIGHLIGHT = (255, 214, 64)           # màu vàng làm nổi số liệu trong phụ đề
TRANSITION = 0.5                     # giây chuyển cảnh
TRANSITIONS = ["slideleft", "fade", "smoothup", "circleopen", "wipeleft", "slideup", "smoothleft", "radial"]
_font_cache = {}


def _font(size: int, bold=False, black=False):
    names = FONTS_BLACK if black else FONTS_BOLD if bold else FONTS_REG
    key = (size, tuple(names))
    if key not in _font_cache:
        from PIL import ImageFont
        font = None
        for name in names:
            for d in FONT_DIRS:
                if (d / name).exists():
                    font = ImageFont.truetype(str(d / name), size)
                    break
            if font:
                break
        _font_cache[key] = font or ImageFont.load_default(size)
    return _font_cache[key]


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


def _mix(a, b, k):
    return tuple(int(x * (1 - k) + y * k) for x, y in zip(a, b))


class Layout:
    """Vị trí các vùng trên khung dọc 9:16 hoặc ngang 16:9."""
    def __init__(self, size):
        self.W, self.H = size
        self.vertical = self.W < self.H
        self.base = min(size)
        self.pad = int(self.base * 0.055)
        self.head_top = int(self.H * (0.105 if self.vertical else 0.09))
        self.card_top = int(self.H * (0.27 if self.vertical else 0.27))
        self.card_bottom = int(self.H * (0.66 if self.vertical else 0.68))
        cw = self.W - 3 * self.pad if self.vertical else int(self.W * 0.62)
        self.card_x0 = (self.W - cw) // 2
        self.card_x1 = self.card_x0 + cw
        self.cap_y = int(self.H * (0.775 if self.vertical else 0.835))


def _save_layer(img, dest: Path):
    """Cắt sát phần có nội dung, trả về (x, y) để FFmpeg đặt lại đúng chỗ — lớp nhỏ ghép nhanh hơn nhiều."""
    box = img.getbbox()
    if not box:
        return None
    img.crop(box).save(dest, "PNG")
    return box[0], box[1]


def render_background(image, size, color: str, dest: Path, mode: str = "photo", seed: int = 0):
    """mode: photo = ảnh rõ, tối nhẹ; blur = ảnh làm mờ + phủ màu thương hiệu; none = nền màu có đốm sáng."""
    from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps
    w, h = int(size[0] * OVERSIZE), int(size[1] * OVERSIZE)
    accent = _hex(color)
    img = None
    if image and Path(image).exists():
        try:
            img = Image.open(image).convert("RGB")
        except Exception:  # noqa: BLE001 — ảnh hỏng thì dùng nền màu
            img = None
    if img is not None and mode == "blur":
        img = ImageOps.fit(img, (w, h)).filter(ImageFilter.GaussianBlur(max(w, h) // 45))
        tint = Image.new("RGB", (w, h), _mix(accent, (0, 0, 0), 0.45))
        img = Image.blend(img, tint, 0.55)
    elif img is not None:
        if img.width / img.height > w / h * 1.6 or img.height / img.width > h / w * 1.6:
            # ảnh lệch khung quá nhiều: nền mờ + ảnh gốc ở giữa (không bị cắt mất nội dung)
            bg = ImageOps.fit(img, (w, h)).filter(ImageFilter.GaussianBlur(40))
            fg = ImageOps.contain(img, (w, int(h * 0.6)))
            bg.paste(fg, ((w - fg.width) // 2, (h - fg.height) // 2))
            img = bg
        else:
            img = ImageOps.fit(img, (w, h))
        img = ImageEnhance.Brightness(img).enhance(0.62)
    else:
        rng = random.Random(seed)
        top = _mix(accent, (255, 255, 255), 0.08)
        bottom = _mix(accent, (0, 0, 0), 0.7)
        col = Image.new("RGB", (1, 256))
        for y in range(256):
            col.putpixel((0, y), _mix(top, bottom, y / 255))
        img = col.resize((w, h), Image.BILINEAR)
        glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        g = ImageDraw.Draw(glow)
        base = min(w, h)
        for _ in range(8):                                    # đốm sáng mờ (bokeh)
            r = int(base * rng.uniform(0.08, 0.32))
            cx, cy = rng.randint(0, w), rng.randint(0, h)
            light = _mix(accent, (255, 255, 255), rng.uniform(0.35, 0.8))
            g.ellipse((cx - r, cy - r, cx + r, cy + r), fill=light + (rng.randint(35, 80),))
        k = rng.uniform(0.2, 0.8)                             # dải sáng chéo
        g.polygon([(int(w * k), 0), (int(w * k) + base // 3, 0), (int(w * k) - base // 2, h),
                   (int(w * k) - base // 2 - base // 3, h)], fill=(255, 255, 255, 18))
        glow = glow.filter(ImageFilter.GaussianBlur(base // 14))
        img = Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")
    img.save(dest, "PNG")


def _frame_layer(L, color, brand, index, total, dest):
    """Lớp cố định: bóng tối trên/dưới cho chữ dễ đọc, tên thương hiệu, số cảnh, thanh tiến độ."""
    from PIL import Image, ImageDraw
    ov = Image.new("RGBA", (L.W, L.H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    accent = _hex(color)
    shade = int(L.H * 0.30)
    for y in range(shade):                                    # bóng dưới cho phụ đề
        a = int(150 * (y / shade) ** 1.6)
        d.line((0, L.H - shade + y, L.W, L.H - shade + y), fill=(0, 0, 0, a))
    for y in range(int(L.H * 0.12)):                          # bóng trên
        a = int(110 * (1 - y / (L.H * 0.12)))
        d.line((0, y, L.W, y), fill=(0, 0, 0, a))
    f = _font(int(L.base * 0.03), bold=True)
    y = int(L.H * 0.035)
    if brand:
        tw = d.textlength(brand, font=f)
        d.rounded_rectangle((L.pad, y - f.size, L.pad + tw + f.size * 1.6, y + f.size), radius=f.size,
                            fill=accent + (235,))
        d.text((L.pad + f.size * 0.8, y), brand, font=f, fill="white", anchor="lm")
    d.text((L.W - L.pad, y), f"{index + 1}/{total}", font=f, fill=(255, 255, 255, 220), anchor="rm")
    bar = max(6, L.base // 120)
    d.rectangle((0, L.H - bar, L.W, L.H), fill=(255, 255, 255, 60))
    d.rectangle((0, L.H - bar, int(L.W * (index + 1) / total), L.H), fill=_mix(accent, (255, 255, 255), 0.35) + (255,))
    return _save_layer(ov, dest)


def _headline_layer(L, scene, color, dest, center=False):
    from PIL import Image, ImageDraw
    if not scene["headline"]:
        return None
    ov = Image.new("RGBA", (L.W, L.H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    hook = scene["type"] == "hook"
    text = scene["headline"].upper() if hook else scene["headline"]
    f = _font(int(L.base * (0.085 if hook else 0.066)), bold=True, black=hook)
    lines = _wrap(d, text, f, L.W - 4 * L.pad)[:3]
    lh = int(f.size * 1.22)
    top = int(L.H * 0.36) if center else L.head_top
    half = min(L.W // 2 - L.pad, int(max(d.textlength(x, font=f) for x in lines) / 2) + L.pad)
    accent = _hex(color)
    box = (L.W // 2 - half, top - L.pad // 2, L.W // 2 + half, top + lh * len(lines) + L.pad // 2)
    d.rounded_rectangle((box[0] + 8, box[1] + 10, box[2] + 8, box[3] + 10), radius=int(L.base * 0.03),
                        fill=(0, 0, 0, 90))                   # bóng đổ
    d.rounded_rectangle(box, radius=int(L.base * 0.03), fill=accent + (240,),
                        outline=(255, 255, 255, 140), width=max(2, L.base // 300))
    for i, line in enumerate(lines):
        d.text((L.W // 2, top + i * lh + lh // 2), line, font=f, fill="white", anchor="mm")
    return _save_layer(ov, dest)


def _check(d, cx, cy, r, accent):
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=accent + (255,))
    w = max(3, r // 4)
    d.line((cx - r * 0.45, cy + r * 0.02, cx - r * 0.1, cy + r * 0.38, cx + r * 0.5, cy - r * 0.35),
           fill="white", width=w, joint="curve")


def _card_layers(L, scene, color, brand, work: Path, i: int, image=None) -> list:
    """Thẻ thông tin giữa màn hình. Trả về [(file, (x, y), thời điểm hiện, kiểu chuyển động)]."""
    from PIL import Image, ImageDraw, ImageOps
    accent = _hex(color)
    dark = (28, 34, 48)
    out = []
    W, H = L.W, L.H
    x0, x1 = L.card_x0, L.card_x1
    area_h = L.card_bottom - L.card_top
    typ = scene["type"]
    items = scene["items"]

    def new():
        ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        return ov, ImageDraw.Draw(ov)

    def add(ov, name, start, motion):
        pos = _save_layer(ov, work / name)
        if pos:
            out.append((name, pos, start, motion))

    # ảnh của bài viết dạng thẻ bo góc (khung ngang thấp: chỉ ở cảnh mở đầu cho đủ chỗ)
    if image is not None and (typ == "hook" or (typ == "cta" and L.vertical)):
        try:
            src = Image.open(image).convert("RGB")
            box_w, box_h = x1 - x0, area_h if typ == "hook" else int(area_h * 0.45)
            pic = ImageOps.fit(src, (box_w, box_h))
            mask = Image.new("L", pic.size, 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, box_w, box_h), radius=int(L.base * 0.035), fill=255)
            ov, d = new()
            top = L.card_top
            d.rounded_rectangle((x0 - 8, top - 8, x1 + 8, top + box_h + 8), radius=int(L.base * 0.04),
                                fill=(255, 255, 255, 235))
            ov.paste(pic, (x0, top), mask)
            add(ov, f"pic{i}.png", 0.25, "rise")
            if typ == "hook":
                return out
            area_top = top + box_h + L.pad
        except Exception:  # noqa: BLE001
            area_top = L.card_top
    else:
        area_top = L.card_top

    if typ == "stat" and scene["big"]:
        ov, d = new()
        fb = int(L.base * 0.24)
        f = _font(fb, black=True)
        while d.textlength(scene["big"], font=f) > (x1 - x0) - 2 * L.pad and fb > 40:
            fb = int(fb * 0.9)
            f = _font(fb, black=True)
        fl = _font(int(L.base * 0.046), bold=True)
        label = _wrap(d, items[0], fl, (x1 - x0) - 2 * L.pad)[:3] if items else []
        lh = int(fl.size * 1.3)
        h = int(fb * 1.15) + lh * len(label) + 2 * L.pad
        top = area_top + max(0, (L.card_bottom - area_top - h) // 2)
        d.rounded_rectangle((x0, top, x1, top + h), radius=int(L.base * 0.04), fill=(255, 255, 255, 238))
        d.rounded_rectangle((x0, top, x0 + max(10, L.base // 70), top + h), radius=4, fill=accent + (255,))
        d.text((W // 2, top + L.pad + int(fb * 0.55)), scene["big"], font=f, fill=accent, anchor="mm")
        for k, line in enumerate(label):
            d.text((W // 2, top + L.pad + int(fb * 1.15) + k * lh + lh // 2), line, font=fl, fill=dark, anchor="mm")
        add(ov, f"card{i}.png", 0.3, "pop")
        return out

    rows_src = items[:4]
    if typ == "cta" and brand:
        rows_src = rows_src[:3]
    if not rows_src and typ != "cta":
        return out
    # danh sách gạch đầu dòng: thẻ nền trước, từng ý hiện lần lượt
    size_f = L.base * (0.046 if len(rows_src) <= 3 else 0.042)
    meas = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    brand_h = int(L.base * 0.11) if typ == "cta" and brand else 0
    while True:                                   # chữ nhỏ dần cho tới khi thẻ vừa khung
        fr = _font(int(size_f), bold=True)
        r = int(fr.size * 0.55)
        text_w = (x1 - x0) - 3 * L.pad - 2 * r
        wrapped = [_wrap(meas, t, fr, text_w)[:3] for t in rows_src]
        lh = int(fr.size * 1.28)
        gap = int(L.pad * 0.7)
        h = sum(len(w) * lh for w in wrapped) + gap * max(0, len(wrapped) - 1) + 2 * L.pad + brand_h
        if area_top + h <= L.cap_y - int(L.base * 0.13) or size_f < L.base * 0.03:
            break
        size_f *= 0.9
    top = area_top + max(0, (L.card_bottom - area_top - h) // 2)
    ov, d = new()
    d.rounded_rectangle((x0, top, x1, top + h), radius=int(L.base * 0.04), fill=(255, 255, 255, 232))
    if brand_h:
        fbig = _font(int(L.base * 0.058), black=True)
        d.text((W // 2, top + h - L.pad - brand_h // 2), brand, font=fbig, fill=accent, anchor="mm")
    add(ov, f"card{i}.png", 0.25, "rise")
    y = top + L.pad
    for k, lines in enumerate(wrapped):
        ov, d = new()
        _check(d, x0 + L.pad + r, y + lh // 2, r, accent)
        for j, line in enumerate(lines):
            d.text((x0 + 2 * L.pad + 2 * r, y + j * lh + lh // 2), line, font=fr, fill=dark, anchor="lm")
        add(ov, f"row{i}_{k}.png", 0.65 + 0.45 * k, "slide")
        y += len(lines) * lh + gap
    return out


def caption_chunks(text: str, max_words: int = 8) -> list:
    """Chia lời đọc thành các cụm ngắn để hiện phụ đề lần lượt."""
    parts = [p.strip() for p in re.split(r"(?<=[.!?;:,])\s+", clean_tts_text(text)) if p.strip()]
    chunks = []
    for p in parts:
        words = p.split()
        while len(words) > max_words:
            cut = max_words if len(words) - max_words >= 3 else len(words) - 3
            chunks.append(" ".join(words[:cut]))
            words = words[cut:]
        if words:
            if chunks and len(words) <= 2 and len(chunks[-1].split()) + len(words) <= max_words + 2:
                chunks[-1] += " " + " ".join(words)
            else:
                chunks.append(" ".join(words))
    return chunks or [text]


def _caption_layer(L, text, dest):
    """Phụ đề kiểu TikTok: chữ đậm, viền đen, số liệu tô vàng."""
    from PIL import Image, ImageDraw
    ov = Image.new("RGBA", (L.W, L.H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    f = _font(int(L.base * 0.056), bold=True)
    lines = _wrap(d, text, f, L.W - 3 * L.pad)[:3]
    lh = int(f.size * 1.3)
    stroke = max(3, L.base // 160)
    top = L.cap_y - lh * len(lines) // 2
    space = d.textlength(" ", font=f)
    for k, line in enumerate(lines):
        words = line.split()
        widths = [d.textlength(w, font=f) for w in words]
        x = (L.W - (sum(widths) + space * (len(words) - 1))) / 2
        y = top + k * lh + lh // 2
        for w, ww in zip(words, widths):
            color = HIGHLIGHT if re.search(r"\d", w) else (255, 255, 255)
            d.text((x, y), w, font=f, fill=color, anchor="lm", stroke_width=stroke, stroke_fill=(0, 0, 0))
            x += ww + space
    return _save_layer(ov, dest)


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
                       cwd=str(cwd), capture_output=True, text=True, timeout=1800, **kw)
    if r.returncode != 0:
        raise VideoError("FFmpeg lỗi: " + (r.stderr or "")[-400:])


def media_duration(path: Path) -> float:
    kw = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    r = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", str(path)], capture_output=True, text=True, **kw)
    m = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", r.stderr)
    if not m:
        raise VideoError(f"Không đọc được độ dài {path.name}")
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])


def _motion(kind: str, x: int, y: int, start: float, base: int):
    """Biểu thức vị trí cho FFmpeg overlay: phần tử trượt / nổi lên trong ~0.45 giây."""
    p = f"max(0,1-(t-{start:.2f})/0.45)"
    if kind == "slide":
        return f"{x}+{base // 12}*{p}", str(y)
    if kind == "rise":
        return str(x), f"{y}+{base // 10}*{p}"
    if kind == "pop":
        return str(x), f"{y}+{base // 14}*{p}"
    if kind == "head":
        return f"{x}-{base // 6}*{p}", str(y)
    return str(x), str(y)


def render_scene(work: Path, i: int, size, duration: float, bg_video: bool, layers: list, captions: list):
    """Dựng 1 cảnh. layers: [(file, (x, y), start, motion)]; captions: [(file, (x, y), từ giây, đến giây)]."""
    W, H = size
    d = f"{duration:.3f}"
    inputs, flt = [], []
    if bg_video:
        inputs += ["-stream_loop", "-1", "-i", f"bgv{i}.mp4"]
        flt.append(f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,fps={FPS},"
                   f"eq=brightness=-0.10:saturation=1.08,trim=duration={d},setpts=PTS-STARTPTS[s0]")
    else:
        inputs += ["-loop", "1", "-framerate", str(FPS), "-t", d, "-i", f"bg{i}.png"]
        k = f"(t/{d})" if i % 2 == 0 else f"(1-t/{d})"          # đổi hướng trượt mỗi cảnh
        flt.append(f"[0:v]crop={W}:{H}:x='(iw-ow)*{k}':y='(ih-oh)*{k}',setsar=1[s0]")
    cur, n = "s0", 1
    for name, (x, y), start, kind in layers:
        inputs += ["-framerate", str(FPS), "-i", name]
        lx, ly = _motion(kind, x, y, start, min(size))
        flt.append(f"[{n}:v]format=rgba,loop=loop=-1:size=1:start=0,setpts=N/{FPS}/TB,"
                   f"fade=t=in:st={start:.2f}:d=0.4:alpha=1[l{n}]")
        flt.append(f"[{cur}][l{n}]overlay=x='{lx}':y='{ly}':eof_action=repeat[s{n}]")
        cur, n = f"s{n}", n + 1
    for name, (x, y), a, b in captions:
        inputs += ["-framerate", str(FPS), "-i", name]
        flt.append(f"[{n}:v]format=rgba,loop=loop=-1:size=1:start=0,setpts=N/{FPS}/TB[l{n}]")
        flt.append(f"[{cur}][l{n}]overlay=x={x}:y={y}:enable='between(t,{a:.2f},{b:.2f})'[s{n}]")
        cur, n = f"s{n}", n + 1
    inputs += ["-i", f"voice{i}.mp3"]
    flt.append(f"[{cur}]format=yuv420p[v]")
    flt.append(f"[{n}:a]apad,atrim=duration={d}[a]")
    _ffmpeg([*inputs, "-filter_complex", ";".join(flt), "-map", "[v]", "-map", "[a]",
             "-t", d, "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
             "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2", f"scene{i}.mp4"], work)


def _music_files() -> list:
    if not MUSIC_DIR.is_dir():
        return []
    return [p for p in MUSIC_DIR.iterdir() if p.suffix.lower() in (".mp3", ".m4a", ".wav", ".aac")]


def join_scenes(work: Path, durations: list, out: Path, music: Path | None):
    """Nối các cảnh bằng hiệu ứng chuyển cảnh (xfade) + giọng đọc nối mượt (acrossfade), rồi trộn nhạc nền."""
    n = len(durations)
    joined = "joined.mp4" if music else str(out)
    if n == 1:
        _ffmpeg(["-i", "scene0.mp4", "-c", "copy", "-movflags", "+faststart", joined], work)
    else:
        inputs, flt = [], []
        for k in range(n):
            inputs += ["-i", f"scene{k}.mp4"]
            flt.append(f"[{k}:v]settb=AVTB,setpts=PTS-STARTPTS,fps={FPS}[v{k}]")
        length, vcur, acur = durations[0], "v0", "0:a"
        for k in range(1, n):
            off = length - TRANSITION
            tr = TRANSITIONS[(k - 1) % len(TRANSITIONS)]
            flt.append(f"[{vcur}][v{k}]xfade=transition={tr}:duration={TRANSITION}:offset={off:.3f}[x{k}]")
            flt.append(f"[{acur}][{k}:a]acrossfade=d={TRANSITION}[a{k}]")
            vcur, acur = f"x{k}", f"a{k}"
            length += durations[k] - TRANSITION
        flt.append(f"[{vcur}]format=yuv420p[v]")
        _ffmpeg([*inputs, "-filter_complex", ";".join(flt), "-map", "[v]", "-map", f"[{acur}]",
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-c:a", "aac", "-b:a", "160k",
                 "-movflags", "+faststart", joined], work)
    if music:
        _ffmpeg(["-i", "joined.mp4", "-stream_loop", "-1", "-i", str(music), "-filter_complex",
                 "[1:a]volume=0.10[m];[0:a][m]amix=inputs=2:duration=first:normalize=0[a]",
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
    L = Layout(size)
    work = VIDEO_DIR / str(video_id)
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)
    scenes = clean_scenes(v["scenes"])
    total = len(scenes)

    def step(msg):
        db.video_update(video_id, progress=msg)
        _log(msg)

    article_img = None
    if v["image_url"]:
        article_img = work / "article.img"
        if not _download(v["image_url"], article_img):
            article_img = None
    used_videos, durations = set(), []
    for i, sc in enumerate(scenes):
        step(f"Cảnh {i + 1}/{total}: giọng đọc")
        used = tts(sc["narration"], cfg["voice"], cfg["rate"], work / f"voice{i}.mp3")
        if used != VOICES.get(cfg["voice"], "").split(" — ")[0]:
            _log(f"Cảnh {i + 1}: giọng đã chọn lỗi, đã dùng giọng {used}")
        voice_len = media_duration(work / f"voice{i}.mp3")
        dur = math.ceil((voice_len + 0.8) * FPS) / FPS

        step(f"Cảnh {i + 1}/{total}: hình ảnh")
        bg_video = pexels_video(sc["keyword"], cfg["pexels_key"], size, work / f"bgv{i}.mp4", used_videos)
        if not bg_video:
            if pexels_photo(sc["keyword"], cfg["pexels_key"], not L.vertical, work / f"photo{i}.img"):
                render_background(work / f"photo{i}.img", size, cfg["color"], work / f"bg{i}.png", "photo")
            elif article_img:
                mode = "photo" if sc["type"] == "hook" and not sc["headline"] else "blur"
                render_background(article_img, size, cfg["color"], work / f"bg{i}.png", mode)
            else:
                render_background(None, size, cfg["color"], work / f"bg{i}.png", "none", seed=video_id * 100 + i)

        layers = []
        pos = _frame_layer(L, cfg["color"], cfg["brand"], i, total, work / f"frame{i}.png")
        if pos:
            layers.append((f"frame{i}.png", pos, 0.0, "none"))
        cards = _card_layers(L, sc, cfg["color"], cfg["brand"], work, i, article_img)
        center_head = not cards and sc["type"] in ("hook", "text")
        pos = _headline_layer(L, sc, cfg["color"], work / f"head{i}.png", center=center_head)
        if pos:
            layers.append((f"head{i}.png", pos, 0.0, "head"))
        layers += cards
        captions, chunks = [], caption_chunks(sc["narration"])
        weights = [len(c) + 8 for c in chunks]
        t = 0.0
        for k, c in enumerate(chunks):
            end = dur if k == len(chunks) - 1 else t + voice_len * weights[k] / sum(weights)
            p = _caption_layer(L, c, work / f"cap{i}_{k}.png")
            if p:
                captions.append((f"cap{i}_{k}.png", p, t, end))
            t = end
        step(f"Cảnh {i + 1}/{total}: dựng video")
        render_scene(work, i, size, dur, bg_video, layers, captions)
        durations.append(dur)
    music = random.choice(_music_files()) if cfg["music"] and _music_files() else None
    step("Ghép các cảnh + hiệu ứng chuyển cảnh" + (" + nhạc nền" if music else ""))
    out = work / "clip.mp4"
    join_scenes(work, durations, out, music)
    for p in work.iterdir():                          # dọn file tạm, chỉ giữ clip
        if p != out:
            p.unlink(missing_ok=True)
    length = sum(durations) - TRANSITION * (len(durations) - 1)
    db.video_update(video_id, status="done", path=str(out), duration=round(length, 1), progress="")
    db.log("video", f"Đã dựng clip #{video_id}: {v['title']} ({length:.0f}s)")
    _log("✅ Xong clip")


def delete(video_id: int):
    shutil.rmtree(VIDEO_DIR / str(video_id), ignore_errors=True)
    db.video_delete(video_id)


def to_json(v: dict) -> dict:
    v = dict(v)
    v["has_file"] = bool(v["path"]) and Path(v["path"]).exists()
    v.pop("path", None)
    return v

