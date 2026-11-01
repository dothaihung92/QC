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

from . import aimedia, config, db, newsagent

VIDEO_DIR = config.DATA_DIR / "videos"
MUSIC_DIR = config.DATA_DIR / "music"
FPS = 30
OVERSIZE = 1.10                      # ảnh nền lớn hơn khung 10% để trượt chậm
SIZES = {"doc": (1080, 1920), "ngang": (1920, 1080)}
GEMINI_VOICES = {"Leda": "Leda (nữ trẻ)", "Zephyr": "Zephyr (nữ, tươi sáng)", "Kore": "Kore (nữ, chắc giọng)",
                 "Aoede": "Aoede (nữ, nhẹ nhàng)", "Sulafat": "Sulafat (nữ, ấm áp)",
                 "Puck": "Puck (nam, vui tươi)", "Charon": "Charon (nam, thông tin)",
                 "Fenrir": "Fenrir (nam, sôi nổi)", "Orus": "Orus (nam, vững vàng)", "Achird": "Achird (nam, thân thiện)"}
STYLES = {
    "nang_dong": ("Năng động, tin nhanh", "Đọc như một MC bản tin kinh tế trẻ trung, tươi sáng và nhiệt huyết, nhịp nhanh "
                  "vừa phải, nhấn mạnh con số và mốc thời gian, ngắt nghỉ tự nhiên như đang nói chuyện với bạn bè, "
                  "tuyệt đối không đọc đều đều"),
    "tu_van": ("Ấm áp, tư vấn", "Đọc bằng giọng ấm áp, thân thiện của một chuyên viên tư vấn đang nhiệt tình giải thích cho khách, "
               "tốc độ vừa phải, nhấn nhá cảm xúc, có nụ cười trong giọng"),
    "chuyen_gia": ("Chuyên gia, rõ ràng", "Đọc bằng giọng tự tin, rõ ràng của một chuyên gia thuế, nhịp độ khá nhanh, "
                   "nhấn mạnh ý quan trọng, không kéo dài giọng"),
}
VIENEU_VOICES = {"Mai Anh": "Mai Anh (nữ, giọng tin tức, miền Bắc)", "Trúc Ly": "Trúc Ly (nữ, tự nhiên, miền Bắc)",
                 "Ngọc Huyền": "Ngọc Huyền (nữ, tự nhiên, miền Bắc)", "Thùy Dung": "Thùy Dung (nữ, tin tức, miền Nam)",
                 "Ngọc Trân": "Ngọc Trân (nữ, tự nhiên, miền Trung)", "Hải Đăng": "Hải Đăng (nam, tự nhiên, miền Bắc)",
                 "Minh Đức": "Minh Đức (nam, tin tức, miền Bắc)", "Thiện Minh": "Thiện Minh (nam, kể chuyện, miền Bắc)",
                 "Quang Sơn": "Quang Sơn (nam, tự nhiên, miền Trung)", "Minh Triết": "Minh Triết (nam, tin tức, miền Nam)"}
VOICES = {f"vieneu:{k}": f"{v} — VieNeu-TTS, offline, miễn phí" for k, v in VIENEU_VOICES.items()}
VOICES.update({f"gemini:{k}": f"{v} — Gemini AI, tự nhiên nhất" for k, v in GEMINI_VOICES.items()})
VOICES.update({"vi-VN-HoaiMyNeural": "Hoài My (nữ) — Microsoft, cần Internet",
          "vi-VN-NamMinhNeural": "Nam Minh (nam) — Microsoft, cần Internet",
          # Piper (github.com/OHF-Voice/piper1-gpl): chạy ngay trên máy, không cần Internet sau lần tải đầu
          "piper:vi_VN-vais1000-medium": "VAIS1000 (nữ) — Piper, offline",
          "piper:vi_VN-25hours_single-low": "25hours (nữ) — Piper, offline",
          "piper:vi_VN-vivos-x_low": "VIVOS (nhiều giọng) — Piper, offline"})
EDGE_VOICES = [v for v in VOICES if v.startswith("vi-VN-")]
PIPER_DIR = config.DATA_DIR / "piper-voices"
OPTIONAL_TOOLS = {"vieneu": "vieneu", "piper": "piper-tts"}                  # cài lỗi (vd Python quá mới) vẫn dùng được giọng khác
LENGTHS = {30: 5, 45: 7, 60: 9, 120: 14, 180: 20}      # giây → số cảnh
TOOLS = {"PIL": "pillow", "edge_tts": "edge-tts", "imageio_ffmpeg": "imageio-ffmpeg",
         "gtts": "gTTS"}                                 # gTTS: giọng dự phòng khi Edge-TTS từ chối

DEFAULTS = {
    "voice": "vieneu:Mai Anh",        # VieNeu-TTS chạy ngay trên máy; chưa cài thì tự dùng giọng khác
    "tts_style": "nang_dong",         # phong cách đọc (chỉ giọng Gemini)
    "rate": 8,                        # tốc độ đọc, % (-30..+30)
    "audience": "senior",             # senior = người lớn tuổi (chữ to, đọc chậm, lời rất dễ hiểu); general = phổ thông
    "look": "doodle",                 # doodle = vẽ tay trên giấy (hình AI vẽ lộ dần); explainer = sơ đồ thẻ kính; classic = cũ
    "pen": "wipe",                    # wipe = quét lộ dần kèm bàn tay; strokes = vẽ từng nét (whiteboard-animator, cài thêm)
    "visual": "stock",                # stock = video/ảnh Pexels hoặc nền màu; ai = ảnh AI riêng cho từng cảnh
    "veo_scenes": 0,                  # số cảnh dùng video AI Veo (TRẢ PHÍ ~0,8 USD/cảnh); 0 = tắt
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
            lo, hi = (0, 8) if k == "veo_scenes" else (-30, 30)
            try:
                v = max(lo, min(hi, int(v)))
            except (TypeError, ValueError):
                v = default
        else:
            v = str(v or "").strip()
        cur[k] = v
    if cur["voice"] not in VOICES:
        cur["voice"] = DEFAULTS["voice"]
    if cur["tts_style"] not in STYLES:
        cur["tts_style"] = DEFAULTS["tts_style"]
    if cur["audience"] not in ("senior", "general"):
        cur["audience"] = DEFAULTS["audience"]
    if cur["look"] not in ("doodle", "tech", "explainer", "classic"):
        cur["look"] = DEFAULTS["look"]
    if cur["pen"] not in ("wipe", "strokes"):
        cur["pen"] = DEFAULTS["pen"]
    if cur["visual"] not in ("stock", "ai"):
        cur["visual"] = DEFAULTS["visual"]
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
    cfg["styles"] = {k: v[0] for k, v in STYLES.items()}
    cfg["veo_cost"] = round(aimedia.VEO_SECONDS * aimedia.VEO_PRICE_PER_SEC, 2)
    cfg["piper"] = piper_available()
    cfg["vieneu"] = vieneu_available()
    cfg["wba"] = importlib.util.find_spec("whiteboard_animator") is not None
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


def _pip(pkgs: list, timeout: int = 900, only_binary: bool = False):
    """Chạy pip, ghi các dòng tiến độ vào nhật ký ngay khi có. Trả về (mã lỗi, phần cuối đầu ra).
    only_binary: chỉ nhận bản cài sẵn (wheel) — thiếu thì báo lỗi ngay thay vì biên dịch từ mã nguồn hàng chục phút."""
    cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "--progress-bar", "off", "--disable-pip-version-check"]
    if only_binary:
        cmd.append("--only-binary=:all:")
    kw = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    proc = subprocess.Popen(cmd + list(pkgs), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace", **kw)
    timer = threading.Timer(timeout, proc.kill)
    timer.start()
    tail, last_log = [], 0.0
    try:
        for line in proc.stdout:
            line = line.rstrip()
            tail = (tail + [line])[-12:]
            if re.match(r"(Collecting|Downloading|Building|Installing collected|Using cached|ERROR)", line) and time.time() - last_log > 4:
                _log("   pip: " + line[:110])
                last_log = time.time()
        proc.wait()
    finally:
        timer.cancel()
    if proc.returncode in (-9, 137) or (proc.returncode and proc.returncode < 0):
        return 1, f"quá {timeout // 60} phút nên bị dừng\n" + "\n".join(tail)
    return proc.returncode, "\n".join(tail)


def _install():
    # luôn cài/cập nhật bản mới nhất: Edge-TTS hay phải cập nhật khi Microsoft đổi cách xác thực
    pkgs = list(TOOLS.values())
    _log(f"Đang cài / cập nhật {', '.join(pkgs)} (1-3 phút)...")
    rc, out = _pip(pkgs)
    if rc != 0:
        raise VideoError("Cài thất bại: " + out[-400:])
    for mod, pkg in OPTIONAL_TOOLS.items():
        label = "VieNeu-TTS (giọng Việt offline, khoảng 3-8 phút)" if mod == "vieneu" else "Piper (giọng offline dự phòng)"
        if sys.version_info >= (3, 14) and mod == "vieneu":
            _log("ℹ Python 3.14 còn rất mới, nhiều thư viện của VieNeu-TTS có thể chưa có bản cài sẵn; "
                 "nếu lỗi, cài Python 3.12 rồi xóa thư mục .venv và chạy lại start.bat.")
        _log(f"Đang cài {label}...")
        rc, out = _pip([pkg])
        if rc != 0:
            _log(f"⚠ Không cài được {pkg} — vẫn dùng giọng Gemini / Microsoft / Google được. " + out[-300:])
    if get_config()["pen"] == "strokes":
        _log("Đang cài whiteboard-animator (vẽ từng nét, ~200 MB gồm opencv, scipy, mô hình nhận chữ 83 MB; tối đa 30 phút)...")
        rc, out = _pip(["whiteboard-animator"], timeout=1800, only_binary=True)
        if rc != 0:
            ver = f"{sys.version_info.major}.{sys.version_info.minor}"
            _log(f"⚠ Không cài được whiteboard-animator trên Python {ver} — clip vẫn dựng được bằng kiểu quét nhanh. "
                 "Thường do thư viện (scipy, opencv, scikit-image) chưa có bản cài sẵn cho bản Python này. "
                 "Cách xử lý: cài thêm Python 3.12, chạy `<python 3.12> -m pip install whiteboard-animator`, rồi thêm dòng "
                 "QC_WBA_PYTHON=<đường dẫn python.exe 3.12> vào file .env. Chi tiết: " + out[-300:])
    importlib.invalidate_caches()
    for mod in ("edge_tts", "gtts"):                     # dùng bản vừa cập nhật mà không cần khởi động lại
        if mod in sys.modules:
            try:
                importlib.reload(sys.modules[mod])
            except Exception:  # noqa: BLE001
                pass
    _log("✅ Đã cài / cập nhật xong công cụ làm video.")


def vieneu_available() -> bool:
    return importlib.util.find_spec("vieneu") is not None


def piper_available() -> bool:
    return importlib.util.find_spec("piper") is not None


# ---------------------------------------------------------------- nguồn nội dung: repo GitHub

def github_source(url: str) -> dict:
    """Lấy mô tả, số sao, giấy phép và README của một repo GitHub công khai để làm nguồn viết kịch bản clip."""
    m = re.match(r"\s*(?:https?://)?(?:www\.)?github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?(?:[/?#].*)?\s*$", url or "")
    if not m:
        raise VideoError("Dán link repo GitHub dạng https://github.com/chủ-repo/tên-repo")
    owner, repo = m[1], m[2]
    hdr = {"User-Agent": newsagent.UA, "Accept": "application/vnd.github+json"}
    try:
        r = requests.get(f"https://api.github.com/repos/{owner}/{repo}", headers=hdr, timeout=20)
        if r.status_code == 404:
            raise VideoError("Không tìm thấy repo (hoặc repo riêng tư)")
        if r.status_code in (403, 429):
            raise VideoError("GitHub đang giới hạn lượt gọi, đợi vài phút rồi thử lại")
        r.raise_for_status()
        info = r.json()
        rd = requests.get(f"https://api.github.com/repos/{owner}/{repo}/readme",
                          headers={**hdr, "Accept": "application/vnd.github.raw"}, timeout=20)
        readme = rd.text if rd.ok else ""
    except requests.RequestException as e:
        raise VideoError(f"Không kết nối được GitHub: {e}") from e
    lic = (info.get("license") or {}).get("spdx_id") or "không rõ"
    readme = re.sub(r"<[^>]+>|!\[[^\]]*\]\([^)]*\)", " ", readme)              # bỏ thẻ HTML, ảnh
    readme = re.sub(r"\n{3,}", "\n\n", readme).strip()[:8000]
    text = (f"Repo GitHub: {info.get('full_name')}\nMô tả: {info.get('description') or ''}\n"
            f"Số sao: {info.get('stargazers_count')}; Số fork: {info.get('forks_count')}; Giấy phép: {lic}; "
            f"Ngôn ngữ: {info.get('language') or ''}; Tạo ngày: {(info.get('created_at') or '')[:10]}; "
            f"Chủ đề: {', '.join(info.get('topics') or [])}\n\nREADME:\n{readme}")
    return {"text": text, "name": info.get("full_name") or f"{owner}/{repo}", "stars": info.get("stargazers_count", 0)}


# ---------------------------------------------------------------- 1. kịch bản

SENIOR_BLOCK = (
    "\n\nCHẾ ĐỘ DỄ HIỂU TỐI ĐA (rất quan trọng, ưu tiên hơn mọi quy tắc về độ ngắn gọn). Người xem không rành về thuế / kế toán, "
    "nhiều người đã lớn tuổi: nghe và nhìn một lần phải HIỂU và HÌNH DUNG ĐƯỢC.\n"
    "- Xưng hô thân thiện: gọi người xem là \"bạn\" (không gọi bác, cô chú, anh chị).\n"
    "- MỖI CÂU CHỈ MỘT Ý, tối đa 14 từ. Dùng từ thông thường; KHÔNG dùng từ tiếng Anh, không viết tắt, không từ hàn lâm. "
    "Thuật ngữ bắt buộc phải nhắc (doanh thu, giá vốn, kê khai...) thì giải nghĩa NGAY bằng lời đời thường.\n"
    "- LUÔN LẤY VÍ DỤ CỤ THỂ, HÌNH DUNG ĐƯỢC: một cửa hàng / hộ kinh doanh có tên và mặt hàng thật (vd \"cửa hàng quần áo của chị Lan\", "
    "\"quán bún của anh Nam\") với số tiền cụ thể, con số tròn dễ nhẩm. Không nói chung chung.\n"
    "- VÍ DỤ TÍNH LÃI / LỖ (bắt buộc khi nội dung liên quan thuế, doanh thu, chi phí): tính TỪNG BƯỚC "
    "Doanh thu − Giá vốn hàng bán − Chi phí = Lãi (hoặc Lỗ), rồi mới tới thuế. Phải có ĐỦ HAI ví dụ: một cửa hàng CÓ LÃI (tính ra tiền thuế) "
    "và một cửa hàng BỊ LỖ (nói rõ trường hợp lỗ ảnh hưởng thế nào tới thuế theo nội dung nguồn; nếu nguồn không nói thì ghi \"cần đối chiếu văn bản gốc\"). "
    "Phép tính phải ĐÚNG. Dùng cảnh \"calc\" (bảng tính từng dòng; dòng cuối là Lãi hoặc Lỗ) và cảnh \"bars\" (biểu đồ cột: "
    "items là các dòng \"Nhãn | số tiền\" như \"Doanh thu | 500 triệu\", \"Giá vốn | 300 triệu\", \"Chi phí | 120 triệu\", \"Lãi | 80 triệu\").\n"
    "- HÌNH MINH HỌA CỤ THỂ: ít nhất MỘT NỬA số cảnh là cảnh type \"visual\" gồm 2-4 hình trong \"panels\", mỗi hình có \"label\" (nhãn tiếng Việt tối đa 4 từ) "
    "và \"visual\" (2-3 câu TIẾNG ANH mô tả một cảnh nhỏ chi tiết minh họa đúng ý đang nói: cửa hàng, hàng hóa, tiền, hóa đơn, máy tính, "
    "người bán / người mua với biểu cảm, mũi tên chỉ dòng tiền; không có chữ trong hình). Cảnh visual đặt NGAY TRƯỚC cảnh giải thích chi tiết cùng ý đó.\n"
    "- Cuối mỗi cảnh có 1 câu nhắc lại ý chính bắt đầu bằng \"Tóm lại...\"; điền câu đó vào \"recap\" (tối đa 12 từ).\n"
    "- Trên màn hình mỗi cảnh chữ sẽ rất to nên TỐI ĐA 3 mục: tiêu đề tối đa 5 từ, giải thích tối đa 15 từ. Mỗi cảnh chỉ giải thích MỘT điều; cần nói nhiều thì chia thành nhiều cảnh.\n"
)
SENIOR_WPS = 2.4                 # người lớn tuổi: đọc chậm hơn (từ / giây)
WORDS_PER_SEC = 3.0                  # tốc độ đọc tiếng Việt trung bình của giọng máy (đo từ clip thật)
SCENE_TYPES = ("hook", "stat", "list", "flow", "steps", "text", "cta", "doodle", "hero", "browser", "calc", "visual", "bars")
DOODLE_PAGES = {30: 3, 45: 4, 60: 5, 120: 8, 180: 12}   # giây → số trang của clip vẽ tay (~15 giây / trang)

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
- Câu ngắn (tối đa 18 từ), có từ nối ("Vậy", "Đặc biệt", "Lưu ý nhé"), xưng "bạn", có câu hỏi gợi mở và cảm thán nhẹ
  để giọng đọc lên xuống tự nhiên; các cảnh nối tiếp nhau như một câu chuyện liền mạch, KHÔNG mở đầu mỗi cảnh bằng "Cảnh tiếp theo".
- KHÔNG viết tắt: viết "thu nhập doanh nghiệp" thay "TNDN", "nghị định" thay "NĐ-CP", "hộ kinh doanh" thay "HKD".
- Ngày tháng viết kiểu nói: "ngày 29 tháng 10 năm 2026". Không emoji, không ký hiệu markdown.


NẾU NỘI DUNG LÀ QUY ĐỊNH / VĂN BẢN PHÁP LUẬT / CHÍNH SÁCH THUẾ, phải giải thích RÕ RÀNG, ĐẦY ĐỦ theo trình tự:
 1) Căn cứ pháp lý (số hiệu văn bản, cơ quan ban hành, ngày ban hành, ngày hiệu lực);
 2) Đối tượng áp dụng và KHÔNG áp dụng;
 3) Điều kiện cụ thể (con số, mốc thời gian, cách xác định);
 4) Nội dung / mức ưu đãi / nghĩa vụ và cách tính, kèm ví dụ có số liệu;
 5) Thủ tục, hồ sơ, thời hạn thực hiện;
 6) Lưu ý, sai sót thường gặp, mức phạt nếu có;
 7) Tóm tắt và kêu gọi liên hệ tư vấn.

GIẢI THÍCH DỄ HIỂU (rất quan trọng): coi người xem là chủ cửa hàng nhỏ chưa biết gì về thuế.
- Mỗi thuật ngữ khi xuất hiện lần đầu phải được giải nghĩa ngay bằng lời đời thường, kèm so sánh gần gũi nếu được (vd "doanh thu là tổng tiền bán hàng thu về, chưa trừ chi phí").
- Với mỗi quy định: nói nó LÀ GÌ → áp vào TRƯỜNG HỢP CỦA BẠN như thế nào → ví dụ cụ thể có tên người và số tiền.
- Ít nhất 2 cảnh type "calc" = VÍ DỤ TÍNH TOÁN TỪNG BƯỚC: items là các dòng "Nội dung | Số tiền" theo đúng thứ tự tính, dòng CUỐI là kết quả
  (vd "Doanh thu cả năm | 8 tỷ đồng", "Thuế phải nộp | 200 triệu", "Được giảm 30% | − 60 triệu", "Thực nộp | 140 triệu"). Phép tính phải ĐÚNG; ghi rõ đây là ví dụ minh họa.
- Câu văn ngắn, không dùng từ hàn lâm; nếu buộc phải dùng thuật ngữ pháp lý thì giải thích ngay sau đó.
Mỗi cảnh phải có 3-5 mục thông tin CHI TIẾT hiện trên màn hình, mỗi mục viết dạng "Tiêu đề ngắn | giải thích đầy đủ 10-25 từ" (không chỉ liệt kê từ khóa).
Chỉ dùng thông tin có trong nội dung nguồn; chỗ nguồn chưa nói rõ thì ghi "cần đối chiếu văn bản gốc", không tự bịa.

Mỗi cảnh có phần hình trên màn hình:
- type: "hook" | "stat" | "list" | "flow" | "steps" | "calc" | "bars" | "visual" | "text" | "cta"
  ("flow" = sơ đồ cây: items[0] là ý gốc, các items sau là 2-4 nhánh con, mỗi nhánh dạng "Tiêu đề ngắn | mô tả ngắn";
   "steps" = các bước nối tiếp nhau; "list" = các ý song song; "stat" = một con số nổi bật. Dùng đa dạng các kiểu.)
- headline: tiêu đề lớn gồm 2 DÒNG NGẮN ngăn bằng dấu "|", tổng tối đa 7 từ, vd "GIẢM 30% THUẾ|CHO HỘ KINH DOANH".
- big: (cho "stat") con số / tỷ lệ / mốc thời gian nổi bật, tối đa 12 ký tự, vd "30%", "10 tỷ", "29/10/2026".
- items: 2-4 ý ngắn (mỗi ý tối đa 9 từ) hiện thành thẻ thông tin; với "stat" thì items[0] là chú thích cho con số
  (tùy chọn items[1] = nhãn nhỏ, items[2] = nội dung thẻ nguồn, vd "VĂN BẢN" và "Nghị định 398/2026").
  Cảnh nào cũng phải có items (trừ "hook" có thể để trống).
- keyword: 1-3 từ TIẾNG ANH để tìm video/ảnh minh họa (vd "tax documents", "calculator", "small shop owner").
- visual: 1 câu TIẾNG ANH mô tả cảnh quay minh họa cho cảnh này (ảnh thật, người Việt Nam, văn phòng / cửa hàng hiện đại,
  ánh sáng đẹp, KHÔNG có chữ hay logo trong ảnh), vd "A Vietnamese shop owner smiling while checking invoices on a tablet".
- description: lời giới thiệu đăng kèm video, 2-3 câu, kết bằng 3 hashtag.
{brand}
Trả về DUY NHẤT JSON: {{"title": "...", "description": "...", "scenes": [{{"type": "hook", "headline": "...",
"narration": "...", "big": "", "items": ["..."], "keyword": "...", "visual": "..."}}]}}

NỘI DUNG:
{text}
"""

DOODLE_PROMPT = """Bạn là biên tập viên video giải thích (Facebook Reels / TikTok / YouTube) cho một công ty dịch vụ kế toán - thuế ở Việt Nam.
Từ nội dung dưới đây, viết kịch bản video "vẽ tay trên giấy" dài khoảng {seconds} giây gồm đúng {n} TRANG.
Mỗi trang là một ý trọn vẹn, có 2-4 hình minh họa phác thảo được vẽ lần lượt trong lúc người dẫn đọc.

ĐỘ DÀI (BẮT BUỘC): tổng lời đọc khoảng {total} từ, mỗi trang {lo}-{hi} từ.

NỘI DUNG PHẢI CHI TIẾT, DỄ HIỂU CHO NGƯỜI KHÔNG CHUYÊN:
- Giải thích rõ từng thuật ngữ bằng lời đời thường ("hóa đơn đầu vào nghĩa là...").
- Ít nhất {examples} trang là VÍ DỤ CỤ THỂ có số liệu và tên nhân vật: vd "Chị Lan bán quần áo, doanh thu năm 8 tỷ đồng,
  thuế phải nộp là 200 triệu, được giảm 30% nên chỉ còn 140 triệu". Tính toán phải đúng; nói rõ đây là ví dụ minh họa.
- Giữ ĐÚNG số liệu, mức thuế, ngày hiệu lực, số hiệu văn bản trong bài nguồn. Không bịa số liệu pháp lý.
- Trang đầu: nêu vấn đề / lợi ích gây chú ý. Các trang giữa: điều kiện, cách tính, thủ tục, lưu ý hay sai sót. Trang cuối: tóm tắt và kêu gọi nhắn Fanpage để được tư vấn miễn phí.

Quy tắc lời đọc (narration): như người dẫn chương trình đang nói, câu ngắn tự nhiên, xưng "bạn", có từ nối và câu hỏi gợi mở.
KHÔNG viết tắt (viết "thu nhập doanh nghiệp" thay "TNDN"), ngày tháng viết kiểu nói ("ngày 29 tháng 10 năm 2026"), số tiền viết
dạng đọc được ("tám tỷ đồng", "hai trăm triệu"), không emoji, không ký hiệu markdown. Các trang nối nhau thành một câu chuyện liền mạch.

Mỗi trang có:
- type: luôn là "doodle".
- tag: nhãn nhỏ phía trên, tối đa 4 từ, viết hoa (vd "BƯỚC 1 · ĐIỀU KIỆN", "VÍ DỤ THỰC TẾ").
- headline: tiêu đề của trang, tối đa 10 từ, viết thường như một câu.
- panels: ĐÚNG 4 hình mỗi trang (tối thiểu 3), được vẽ lần lượt theo đúng thứ tự lời đọc. Mỗi hình gồm "label" (nhãn tiếng Việt
  tối đa 4 từ, hiện dưới hình) và "visual" (2-3 câu TIẾNG ANH mô tả một CẢNH NHỎ chi tiết gồm 3-5 yếu tố: nhân vật hoạt hình
  dễ thương có biểu cảm + đồ vật + biểu tượng + mũi tên / tia sáng, vd "A cute cartoon shop owner with a happy face holding
  a tax invoice, a calculator and a stack of coins beside her, a small percent badge and sparkles around").
  Hình phải minh họa đúng ý đang nói, không chứa chữ.
- hl: 1-4 từ hoặc cụm quan trọng trong lời đọc (chép đúng từng chữ) để tô vàng ở phụ đề (số liệu, thuật ngữ chính).
- description: (chỉ một lần ở cuối JSON) lời giới thiệu đăng kèm video, 2-3 câu, kết bằng 3 hashtag.
{brand}
Trả về DUY NHẤT JSON: {{"title": "...", "description": "...", "scenes": [{{"type": "doodle", "tag": "...", "headline": "...",
"narration": "...", "panels": [{{"label": "...", "visual": "..."}}], "hl": ["..."]}}]}}

NỘI DUNG:
{text}
"""

TECH_PROMPT = """Bạn là biên tập viên video "review công cụ / công nghệ" (Facebook Reels / TikTok / YouTube) bằng tiếng Việt.
Từ nội dung dưới đây (thông tin về một công cụ, phần mềm, repo GitHub hoặc chủ đề công nghệ), viết kịch bản video giải thích dài khoảng {seconds} giây gồm đúng {n} cảnh.

ĐỘ DÀI (BẮT BUỘC): tổng lời đọc khoảng {total} từ, mỗi cảnh {lo}-{hi} từ.


NẾU NỘI DUNG LÀ QUY ĐỊNH / VĂN BẢN PHÁP LUẬT / CHÍNH SÁCH THUẾ, phải giải thích RÕ RÀNG, ĐẦY ĐỦ theo trình tự:
 1) Căn cứ pháp lý (số hiệu văn bản, cơ quan ban hành, ngày ban hành, ngày hiệu lực);
 2) Đối tượng áp dụng và KHÔNG áp dụng;
 3) Điều kiện cụ thể (con số, mốc thời gian, cách xác định);
 4) Nội dung / mức ưu đãi / nghĩa vụ và cách tính, kèm ví dụ có số liệu;
 5) Thủ tục, hồ sơ, thời hạn thực hiện;
 6) Lưu ý, sai sót thường gặp, mức phạt nếu có;
 7) Tóm tắt và kêu gọi liên hệ tư vấn.
GIẢI THÍCH DỄ HIỂU (rất quan trọng): coi người xem là chủ cửa hàng nhỏ chưa biết gì về thuế.
- Mỗi thuật ngữ khi xuất hiện lần đầu phải được giải nghĩa ngay bằng lời đời thường, kèm so sánh gần gũi nếu được (vd "doanh thu là tổng tiền bán hàng thu về, chưa trừ chi phí").
- Với mỗi quy định: nói nó LÀ GÌ → áp vào TRƯỜNG HỢP CỦA BẠN như thế nào → ví dụ cụ thể có tên người và số tiền.
- Ít nhất 2 cảnh type "calc" = VÍ DỤ TÍNH TOÁN TỪNG BƯỚC: items là các dòng "Nội dung | Số tiền" theo đúng thứ tự tính, dòng CUỐI là kết quả
  (vd "Doanh thu cả năm | 8 tỷ đồng", "Thuế phải nộp | 200 triệu", "Được giảm 30% | − 60 triệu", "Thực nộp | 140 triệu"). Phép tính phải ĐÚNG; ghi rõ đây là ví dụ minh họa.
- Câu văn ngắn, không dùng từ hàn lâm; nếu buộc phải dùng thuật ngữ pháp lý thì giải thích ngay sau đó.
Mỗi cảnh phải có 3-5 mục thông tin CHI TIẾT hiện trên màn hình, mỗi mục viết dạng "Tiêu đề ngắn | giải thích đầy đủ 10-25 từ" (không chỉ liệt kê từ khóa).
Chỉ dùng thông tin có trong nội dung nguồn; chỗ nguồn chưa nói rõ thì ghi "cần đối chiếu văn bản gốc", không tự bịa.

NỘI DUNG (nếu là công cụ / phần mềm): nói rõ công cụ là gì, giải quyết vấn đề gì, điểm mạnh (con số cụ thể: số sao, số kênh, miễn phí, giấy phép), cách cài / dùng, các tình huống áp dụng KÈM VÍ DỤ CỤ THỂ, rủi ro và lưu ý bảo mật,
rồi kết bằng câu hỏi tương tác (vd "Bạn muốn ... nào? Bình luận cho mình biết nhé"). Chỉ dùng thông tin có trong nội dung nguồn, không bịa số liệu; ví dụ minh họa phải ghi rõ là ví dụ.
Lời đọc: câu ngắn tự nhiên như người dẫn chương trình, xưng "bạn", không viết tắt khó đọc, không emoji / markdown; số lớn đọc thành chữ ("một trăm lẻ sáu nghìn chín trăm sao").

Mỗi cảnh có:
- type: "hero" (cảnh đầu: logo + tiêu đề + 4-6 chip), "stat" (một con số nổi bật + biểu đồ), "browser" (cửa sổ trình duyệt hiển thị đoạn trích / ví dụ),
  "steps" (các bước), "calc" (ví dụ tính toán từng bước), "bars" (biểu đồ cột các khoản tiền), "visual" (2-4 hình minh họa trong "panels"), "list" (các ý), "flow" (sơ đồ cây), "cta" (cảnh cuối: câu hỏi + nút), "text".
- tag: nhãn nhỏ phía trên, viết hoa, vd "01 — ÁP DỤNG", "BẢO MẬT" (tối đa 4 từ).
- headline: tiêu đề 2 DÒNG ngăn bằng "|", tổng tối đa 7 từ, dòng 2 sẽ tô xanh, vd "Cho AI “mắt”|nhìn Internet".
- chips: các nhãn ngắn hiện thành chip, mỗi chip dạng "biểu_tượng|Nhãn" với biểu_tượng thuộc: lock, check, warn, star, search, globe, play, bell, chat, no, bolt, doc (vd "lock|Cần đăng nhập"). Cảnh "hero" cần 4-6 chip.
- big: (cho "stat") con số nổi bật, vd "106,9K"; items[0] là dòng chú thích dưới số, vd "trong 8 tháng"; chips[0] là nhãn phụ.
- url, url_title, items, focus, tone: (cho "browser") url là địa chỉ giả hiển thị (vd "github.com · tên-repo / README"), url_title là tiêu đề trang, items là 3-5 dòng nội dung
  của trang (trích / diễn giải từ nguồn), focus là số thứ tự dòng (từ 0) cần tô khung sáng, tone là "info" | "good" | "bad" (xanh dương | xanh lá | đỏ).
- items: (cho "steps" / "list" / "flow" / "cta") 3-5 ý, mỗi ý dạng "Tiêu đề ngắn | giải thích đầy đủ 10-25 từ" (riêng "cta" thì ngắn); với "cta": items[0] là câu hỏi hiện trong bong bóng, items[1] là dòng phụ, chips[0] là nhãn nút (vd "bell|Đăng ký kênh").
- note: chú thích nhỏ cuối khung nếu nội dung là minh họa, vd "* Ví dụ minh hoạ".
- description: (một lần ở cuối JSON) lời giới thiệu đăng kèm video, 2-3 câu, kết bằng 3 hashtag.
{brand}
Trả về DUY NHẤT JSON: {{"title": "...", "description": "...", "scenes": [{{"type": "hero", "tag": "...", "headline": "...|...", "narration": "...", "chips": ["lock|..."], "big": "", "url": "", "url_title": "", "items": [], "focus": 0, "tone": "info", "note": ""}}]}}

NỘI DUNG:
{text}
"""

EXPAND = """Video dài nên phải giải thích ĐẦY ĐỦ và có VÍ DỤ CỤ THỂ có số liệu (nói rõ là ví dụ), không chỉ tóm tắt: ai được áp dụng, điều kiện, mức ưu đãi cụ thể,
thời gian hiệu lực, cách tính (có ví dụ minh họa ghi rõ là ví dụ), các bước doanh nghiệp cần làm, hồ sơ / thời hạn,
lưu ý và sai lầm thường gặp, câu hỏi hay gặp. Dùng nhiều cảnh "stat" và "list" để màn hình luôn có thông tin."""


def word_count(text: str) -> int:
    return len(re.findall(r"\w+", text or ""))


def estimate_seconds(scenes) -> int:
    wps = SENIOR_WPS if get_config()["audience"] == "senior" else WORDS_PER_SEC
    return round(sum(word_count(s.get("narration", "")) for s in scenes) / wps + 0.6 * len(scenes))


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
        items = [str(x).strip(" -•*\t")[:220] for x in items if str(x).strip(" -•*\t")][:5]
        typ = str(s.get("type", "")).strip().lower()
        panels = []
        for pv in (s.get("panels") or [])[:4]:
            if isinstance(pv, str):
                pv = {"label": pv}
            if isinstance(pv, dict) and (str(pv.get("label", "")).strip() or str(pv.get("visual", "")).strip()):
                panels.append({"label": str(pv.get("label", "")).strip()[:40], "visual": str(pv.get("visual", "")).strip()[:300]})
        hl = s.get("hl") or []
        hl = [x.strip() for x in (hl.split(",") if isinstance(hl, str) else map(str, hl)) if x.strip()][:6]
        if panels and not items:
            items = [pv["label"] for pv in panels if pv["label"]][:4]
        if panels and typ not in SCENE_TYPES:
            typ = "doodle"
        chips = s.get("chips") or []
        chips = [str(x).strip()[:60] for x in (chips.splitlines() if isinstance(chips, str) else chips) if str(x).strip()][:8]
        try:
            focus = int(s.get("focus", -1))
        except (TypeError, ValueError):
            focus = -1
        out.append({"type": typ if typ in SCENE_TYPES else ("stat" if s.get("big") else "list" if items else "text"),
                    "chips": chips, "url": str(s.get("url", "")).strip()[:60], "url_title": str(s.get("url_title", "")).strip()[:50],
                    "recap": str(s.get("recap", "")).strip()[:140],
                    "focus": focus, "tone": str(s.get("tone", "")).strip().lower()[:8], "note": str(s.get("note", "")).strip()[:60],
                    "tag": str(s.get("tag", "")).strip()[:40], "panels": panels, "hl": hl,
                    "headline": str(s.get("headline", "")).strip()[:120],
                    "narration": narration[:900],
                    "big": str(s.get("big", "")).strip()[:16],
                    "items": items,
                    "keyword": str(s.get("keyword", "")).strip()[:60],
                    "visual": str(s.get("visual", "")).strip()[:300]})
    return out[:30]


def make_script(text: str, seconds: int = 45) -> dict:
    text = (text or "").strip()
    if len(text) < 80:
        raise VideoError("Nội dung quá ngắn để làm clip (cần ít nhất vài câu)")
    seconds = seconds if seconds in LENGTHS else 45
    cfg = get_config()
    doodle = cfg["look"] == "doodle"
    tech = cfg["look"] == "tech"
    n = DOODLE_PAGES[seconds] if doodle else LENGTHS[seconds]
    brand = f'- {"Trang" if doodle else "Cảnh"} cuối nhắc tên: "{cfg["brand"]}"\n' if cfg["brand"] else ""
    senior = cfg["audience"] == "senior"
    wps = SENIOR_WPS if senior else WORDS_PER_SEC
    total = int(seconds * wps)
    per = total / n
    if tech:
        prompt = TECH_PROMPT.format(seconds=seconds, n=n, total=total, lo=int(per * 0.8), hi=int(per * 1.25), brand=brand, text=text[:12000])
    elif doodle:
        prompt = DOODLE_PROMPT.format(seconds=seconds, n=n, total=total, lo=int(per * 0.8), hi=int(per * 1.25),
                                      examples=max(1, n // 3), brand=brand, text=text[:12000])
    else:
        prompt = SCRIPT_PROMPT.format(seconds=seconds, n=n, total=total, lo=int(per * 0.8), hi=int(per * 1.25),
                                      expand=EXPAND if seconds >= 90 else "", brand=brand, text=text[:12000])
    if senior:
        prompt += SENIOR_BLOCK
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
        rich = [x for x in scenes if x["type"] in ("list", "steps", "flow", "browser", "calc")]
        def detailed(x):
            return sum(1 for t in x["items"] if "|" in t and len(t.split("|", 1)[1].strip()) >= 25)
        thin = [x for x in rich if len(x["items"]) < 3 or (x["type"] not in ("browser", "calc") and detailed(x) < min(3, len(x["items"])))]
        enough = not thin or len(thin) <= len(rich) * 0.25 or cfg["look"] in ("doodle", "classic")
        if scenes and (not best or (enough, words) > (best[3], best[1])):
            best = (out, words, scenes, enough)
        if scenes and words >= total * 0.8 and len(scenes) >= n * 0.75 and enough:
            break
        if scenes and words >= total * 0.8 and not enough:
            prompt += ("\n\nLƯU Ý: bản trước có quá nhiều cảnh thiếu thông tin trên màn hình. Mỗi cảnh phải có 3-5 mục, mỗi mục "
                       "\"Tiêu đề | giải thích đầy đủ 10-25 từ\", viết cụ thể, có số liệu, điều kiện, thời hạn.")
            continue
        prompt += (f"\n\nLƯU Ý: bản trước chỉ có {len(scenes)} {'trang' if doodle else 'cảnh'} / {words} từ — QUÁ NGẮN. Viết lại đủ {n} {'trang' if doodle else 'cảnh'} "
                   f"và khoảng {total} từ lời đọc, giải thích chi tiết hơn.")
    if not best:
        raise VideoError("AI không trả về kịch bản hợp lệ, thử lại")
    out, words, scenes, _ = best
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
            try:
                media_duration(dest)                 # tải dở / hỏng thì bỏ, thử video khác
            except VideoError:
                dest.unlink(missing_ok=True)
                continue
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


_vieneu_model = {}


def _vieneu(text: str, voice: str, rate: int, dest: Path):
    """VieNeu-TTS v3 Turbo (Apache-2.0) chạy hoàn toàn trên CPU bằng ONNX Runtime, không cần card đồ họa.
    Lần đầu tự tải mô hình từ Hugging Face (vài trăm MB) về thư mục cache của máy."""
    if not vieneu_available():
        raise VideoError("Chưa cài VieNeu-TTS — bấm 'Cài / cập nhật công cụ'")
    if "tts" not in _vieneu_model:
        _log("Đang nạp VieNeu-TTS (lần đầu tải mô hình, vài phút)...")
        from vieneu import Vieneu
        _vieneu_model["tts"] = Vieneu(backend="onnx")
    import soundfile as sf
    tts_engine = _vieneu_model["tts"]
    audio = tts_engine.infer(text, voice=voice)
    if audio is None or len(audio) == 0:
        raise VideoError("VieNeu-TTS không tạo được âm thanh")
    wav = dest.with_suffix(".wav")
    sf.write(str(wav), audio, tts_engine.sample_rate)
    trim = "silenceremove=start_periods=1:start_threshold=-45dB"
    flt = f"{trim},areverse,{trim},areverse,atempo={1 + max(-30, min(30, rate)) / 100:.2f}"
    _ffmpeg(["-i", wav.name, "-af", flt, "-c:a", "libmp3lame", "-q:a", "3", dest.name], dest.parent)
    wav.unlink(missing_ok=True)


def _gemini_voice(text: str, voice: str, style: str, rate: int, dest: Path):
    import wave
    key = newsagent.get_config()["gemini_key"]
    if not key:
        raise VideoError("Chưa có Gemini API key (nhập ở tab Tin tức AI)")
    try:
        pcm, hz = aimedia.tts_pcm(text, voice, style, key)
    except aimedia.AIError as e:
        raise VideoError(str(e)) from e
    wav = dest.with_suffix(".wav")
    with wave.open(str(wav), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(hz)
        f.writeframes(pcm)
    trim = "silenceremove=start_periods=1:start_threshold=-45dB"       # cắt khoảng lặng đầu và cuối cho nhịp liền mạch
    flt = f"{trim},areverse,{trim},areverse,atempo={1 + max(-30, min(30, rate)) / 100:.2f}"
    _ffmpeg(["-i", wav.name, "-af", flt, "-c:a", "libmp3lame", "-q:a", "3", dest.name], dest.parent)
    wav.unlink(missing_ok=True)


def tts(text: str, voice: str, rate: int, dest: Path, style: str = "") -> str:
    """Tạo giọng đọc, thử lần lượt tới khi được. Giọng Microsoft: giọng đã chọn → tốc độ chuẩn →
    giọng Microsoft còn lại → Piper offline (nếu đã cài) → Google. Giọng Piper: Piper → Microsoft → Google.
    Trả về tên giọng đã dùng."""
    text = clean_tts_text(text)
    if not text:
        raise VideoError("Lời đọc trống sau khi bỏ ký tự đặc biệt")
    label = lambda v: VOICES.get(v, v).split(" — ")[0]
    piper_fallback = next((v for v in VOICES if v.startswith("piper:") and
                           (PIPER_DIR / f"{v[6:]}.onnx").exists()), None)
    if voice.startswith("vieneu:"):
        edge = EDGE_VOICES[0]
        attempts = [(label(voice), lambda: _vieneu(text, voice[7:], rate, dest)),
                    (label(voice), lambda: _vieneu(text, voice[7:], rate, dest)),
                    (label(edge), lambda: _edge(text, edge, f"{int(rate):+d}%", dest))]
    elif voice.startswith("gemini:"):
        edge = EDGE_VOICES[0]
        attempts = [(label(voice), lambda: _gemini_voice(text, voice[7:], style, rate, dest)),
                    (label(edge), lambda: _edge(text, edge, f"{int(rate):+d}%", dest))]
    elif voice.startswith("piper:"):
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
                     "khác. Chi tiết: " + " | ".join(errors))


SAMPLE = ("Xin chào, đây là giọng đọc thử cho Fanpage kế toán. Từ ngày một tháng bảy năm hai nghìn "
          "không trăm hai mươi sáu, doanh nghiệp nhỏ được giảm thuế.")


def voice_sample(voice: str, rate: int) -> Path:
    if voice not in VOICES:
        raise VideoError("Giọng không hợp lệ")
    d = VIDEO_DIR / "_nghe-thu"
    d.mkdir(parents=True, exist_ok=True)
    dest = d / f"{re.sub(r'[^A-Za-z0-9_-]', '_', voice)}.mp3"
    used = tts(SAMPLE, voice, rate, dest, STYLES[get_config()["tts_style"]][1])
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
        self.ts = 1.0                      # hệ số cỡ chữ (người lớn tuổi: 1.25)


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
    headline = scene["headline"].replace("|", " ")
    text = headline.upper() if hook else headline
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


# ---------------------------------------------------------------- phụ đề chạy theo giọng đọc (từng từ)

def speech_span(audio: Path, total: float):
    """Đo file giọng đọc: (lúc bắt đầu nói, lúc nói xong, [(đầu, cuối) các khoảng lặng giữa chừng]) bằng silencedetect."""
    kw = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    r = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", str(audio), "-af", "silencedetect=n=-36dB:d=0.11", "-f", "null", "-"],
                       capture_output=True, text=True, timeout=120, **kw)
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", r.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", r.stderr)]
    sils = []
    for k, st in enumerate(starts):
        sils.append((max(0.0, st), ends[k] if k < len(ends) else total))
    begin, end = 0.0, total
    if sils and sils[0][0] <= 0.05:
        begin = sils.pop(0)[1]
    if sils and sils[-1][1] >= total - 0.05:
        end = sils.pop()[0]
    return begin, max(begin + 0.3, end), [x for x in sils if begin < x[0] and x[1] < end]


def align_words(words: list, audio: Path, total: float) -> list:
    """Thời điểm bắt đầu nói từng từ. Ước lượng theo độ dài chữ (dấu câu = chỗ ngắt), rồi khớp các chỗ ngắt đó với
    khoảng lặng THẬT trong file âm thanh để mỗi câu / cụm bắt đầu đúng lúc giọng đọc."""
    n = len(words)
    if not n:
        return []
    try:
        begin, end, sils = speech_span(audio, total)
    except Exception:  # noqa: BLE001 — đo lỗi thì chia đều theo độ dài chữ
        begin, end, sils = 0.0, total, []

    def w_len(w):
        t = re.sub(r"[^\w%]", "", w)
        return max(2.0, len(t) * 1.0 + 1.0)
    pause = [(6.0 if re.search(r"[.!?…]$", w) else 3.0 if re.search(r"[,;:]$", w) else 0.0) for w in words]
    weights = [w_len(w) + pause[k] for k, w in enumerate(words)]
    tot_w = sum(weights)
    est, acc = [], 0.0
    for k in range(n):
        est.append(begin + (end - begin) * acc / tot_w)
        acc += weights[k]
    est.append(end)
    # neo các chỗ ngắt (sau từ có dấu câu) vào khoảng lặng gần nhất chưa dùng
    anchors, used = {}, set()
    for k in range(n - 1):
        if pause[k] <= 0:
            continue
        exp = est[k + 1] - (end - begin) * pause[k] / tot_w * 0.5
        best = None
        for si, (a, b) in enumerate(sils):
            if si in used:
                continue
            dist = abs((a + b) / 2 - exp)
            if dist < 0.9 and (best is None or dist < best[0]):
                best = (dist, si)
        if best:
            used.add(best[1])
            anchors[k] = sils[best[1]]
    starts = [0.0] * n
    seg_from, seg_t0 = 0, begin
    cut_points = sorted(anchors) + [n - 1]
    for cut in cut_points:
        if cut == n - 1 and cut not in anchors:
            seg_end_t, nxt_t0, last = end, end, n - 1
        else:
            a, b = anchors[cut]
            seg_end_t, nxt_t0, last = max(a, seg_t0 + 0.2), b, cut
        seg_w = sum(w_len(words[j]) for j in range(seg_from, last + 1)) or 1.0
        acc = 0.0
        for j in range(seg_from, last + 1):
            starts[j] = seg_t0 + (seg_end_t - seg_t0) * acc / seg_w
            acc += w_len(words[j])
        seg_from, seg_t0 = last + 1, nxt_t0
        if seg_from >= n:
            break
    for j in range(1, n):                                   # đảm bảo tăng dần
        starts[j] = max(starts[j], starts[j - 1] + 0.05)
    return starts


def karaoke_captions(L, work: Path, prefix: str, narration: str, audio: Path, dur: float, voice_len: float, draw,
                     max_words: int = 6) -> list:
    """Phụ đề: mỗi cụm hiện đủ chữ, từ đang được đọc được tô nổi lên. draw(words, active, dest) vẽ 1 trạng thái.
    Trả về [(file, vị trí, từ giây, đến giây)] liền nhau, bắt đầu từ giây 0 đến hết cảnh."""
    chunks = caption_chunks(narration, max_words)
    allw = " ".join(chunks).split()
    times = align_words(allw, audio, voice_len)
    out, idx = [], 0
    for ci, ch in enumerate(chunks):
        cw = ch.split()
        for wi in range(len(cw)):
            pos = draw(cw, wi, work / f"{prefix}_{ci}_{wi}.png")
            a = 0.0 if idx == 0 else times[idx]
            b = times[idx + 1] if idx + 1 < len(times) else dur
            if pos and b > a:
                out.append((f"{prefix}_{ci}_{wi}.png", pos, a, b))
            idx += 1
    return out


def render_scene(work: Path, i: int, size, duration: float, bg_video: bool, layers: list, captions: list,
                 fade_out: float = 0.0, pan=None):
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
        if pan:                                                   # trượt liên tục xuyên suốt clip: cuối cảnh này = đầu cảnh sau
            k = f"({pan[0]:.4f}+({pan[1] - pan[0]:.4f})*t/{d})"
        else:
            k = f"(t/{d})" if i % 2 == 0 else f"(1-t/{d})"        # đổi hướng trượt mỗi cảnh
        flt.append(f"[0:v]crop={W}:{H}:x='(iw-ow)*{k}':y='(ih-oh)*{k}',setsar=1[s0]")
    cur, n = "s0", 1
    for name, (x, y), start, kind in layers:
        inputs += ["-framerate", str(FPS), "-i", name]
        lx, ly = _motion(kind, x, y, start, min(size))
        fades = "" if kind == "keep" else f",fade=t=in:st={start:.2f}:d=0.4:alpha=1"
        if fade_out and kind != "keep":                           # nội dung mờ dần ở cuối cảnh, cảnh sau hiện lên từ nền liền mạch
            fades += f",fade=t=out:st={max(start + 0.5, duration - fade_out):.2f}:d={fade_out:.2f}:alpha=1"
        flt.append(f"[{n}:v]format=rgba,loop=loop=-1:size=1:start=0,setpts=N/{FPS}/TB{fades}[l{n}]")
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


JOIN_GROUP = 4                  # nối tối đa 4 đoạn mỗi lần: xfade giữ các đoạn sau trong bộ nhớ nên nối 20 đoạn một lượt dễ hết RAM


def _xfade_group(work: Path, files: list, durations: list, out: str, trans: float, names: list, start: int):
    """Nối vài đoạn bằng xfade (hình) + acrossfade (tiếng). Trả về độ dài đoạn kết quả."""
    n = len(files)
    inputs, flt = [], []
    for k, f in enumerate(files):
        inputs += ["-i", f]
        flt.append(f"[{k}:v]settb=AVTB,setpts=PTS-STARTPTS,fps={FPS}[v{k}]")
    length, vcur, acur = durations[0], "v0", "0:a"
    for k in range(1, n):
        tr = names[(start + k - 1) % len(names)]
        flt.append(f"[{vcur}][v{k}]xfade=transition={tr}:duration={trans}:offset={length - trans:.3f}[x{k}]")
        flt.append(f"[{acur}][{k}:a]acrossfade=d={trans}[a{k}]")
        vcur, acur = f"x{k}", f"a{k}"
        length += durations[k] - trans
    flt.append(f"[{vcur}]format=yuv420p[v]")
    _ffmpeg(["-filter_complex_threads", "2", *inputs, "-filter_complex", ";".join(flt), "-map", "[v]", "-map", f"[{acur}]",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2",
             "-movflags", "+faststart", out], work)
    return length


def _concat_copy(work: Path, files: list, out: str):
    (work / "list.txt").write_text("".join(f"file '{f}'\n" for f in files), encoding="utf-8")
    _ffmpeg(["-f", "concat", "-safe", "0", "-i", "list.txt", "-c", "copy", "-movflags", "+faststart", out], work)


def join_scenes(work: Path, durations: list, out: Path, music: Path | None,
                trans: float = TRANSITION, names: list = None):
    """Nối các cảnh có hiệu ứng chuyển cảnh, rồi trộn nhạc nền. Nối theo nhóm nhỏ (cây nhị phân) để không tốn RAM;
    nếu xfade vẫn lỗi thì nối thẳng không hiệu ứng (vẫn ra clip)."""
    names = names or TRANSITIONS
    joined = "joined.mp4" if music else str(out)
    files = [f"scene{k}.mp4" for k in range(len(durations))]
    if trans <= 0 and len(files) > 1:                  # nền liền mạch + nội dung mờ dần: nối thẳng, không chồng hình
        (work / "list.txt").write_text("".join(f"file '{f}'\n" for f in files), encoding="utf-8")
        _ffmpeg(["-f", "concat", "-safe", "0", "-i", "list.txt", "-c:v", "copy", "-af", "aresample=async=1:first_pts=0",
                 "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2", "-movflags", "+faststart", joined], work)
    elif len(files) == 1:
        _ffmpeg(["-i", files[0], "-c", "copy", "-movflags", "+faststart", joined], work)
    else:
        try:
            level, durs, pos = 0, list(durations), 0
            while len(files) > 1:
                nxt_files, nxt_durs = [], []
                for g in range(0, len(files), JOIN_GROUP):
                    grp, gd = files[g:g + JOIN_GROUP], durs[g:g + JOIN_GROUP]
                    if len(grp) == 1:
                        nxt_files.append(grp[0])
                        nxt_durs.append(gd[0])
                        continue
                    final = len(files) <= JOIN_GROUP
                    name = joined if final else f"join{level}_{g}.mp4"
                    nxt_durs.append(_xfade_group(work, grp, gd, name, trans, names, pos))
                    nxt_files.append(name)
                    pos += len(grp) - 1
                files, durs, level = nxt_files, nxt_durs, level + 1
        except VideoError as e:
            _log(f"⚠ Nối có hiệu ứng chuyển cảnh lỗi, nối thẳng các cảnh — {str(e)[:160]}")
            _concat_copy(work, [f"scene{k}.mp4" for k in range(len(durations))], joined)
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
    if cfg["look"] == "doodle":                  # kiểu vẽ tay có nhiều lớp chồng: dựng 720p cho nhanh (đúng độ phân giải clip mẫu)
        size = (size[0] * 2 // 3, size[1] * 2 // 3)
    L = Layout(size)
    senior = cfg["audience"] == "senior"
    L.ts = 1.25 if senior else 1.0
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
    from . import doodle, explainer
    from . import techlook
    tech = cfg["look"] == "tech"
    expl = cfg["look"] == "explainer" or tech
    paper = cfg["look"] == "doodle"
    # explainer / công nghệ: nền liền mạch xuyên suốt + nội dung mờ dần cuối cảnh → nối thẳng (mượt, không chồng hình)
    trans, tnames = (0.0, ["fade"]) if expl else (0.3, ["fade"]) if paper else (TRANSITION, TRANSITIONS)
    ai_state = doodle.AIState()
    hand = None
    if paper:
        hand_file = work / "hand.png"
        hand = (hand_file.name, doodle.hand_image(int(L.base * 0.24), hand_file))
    used_videos, durations = set(), []
    style = STYLES[cfg["tts_style"]][1]
    gkey = newsagent.get_config()["gemini_key"]
    aspect = "9:16" if L.vertical else "16:9"
    veo_at = set()
    if cfg["veo_scenes"] and gkey:                    # rải đều các cảnh dùng Veo, luôn gồm cảnh mở đầu
        k = min(cfg["veo_scenes"], total)
        veo_at = {round(j * (total - 1) / max(1, k - 1)) for j in range(k)} if k > 1 else {0}
    for i, sc in enumerate(scenes):
        step(f"Cảnh {i + 1}/{total}: giọng đọc")
        used = tts(sc["narration"], cfg["voice"], min(cfg["rate"], -6) if senior else cfg["rate"], work / f"voice{i}.mp3", style)
        if used != VOICES.get(cfg["voice"], "").split(" — ")[0]:
            _log(f"Cảnh {i + 1}: giọng đã chọn lỗi, đã dùng giọng {used}")
        voice_len = media_duration(work / f"voice{i}.mp3")
        dur = math.ceil((voice_len + (0.9 if senior else 0.35)) * FPS) / FPS

        if paper:
            step(f"Trang {i + 1}/{total}: vẽ hình minh họa" + (" (AI)" if gkey else ""))
            panels = doodle.make_panels(sc, size, work, i, gkey, _log, True, ai_state, cfg["pen"], dur)
            step(f"Trang {i + 1}/{total}: dựng video")
            doodle.render_page(L, sc, i, total, work, dur, voice_len, cfg["brand"], panels, hand, FPS, "f7f3e2")
            durations.append(dur)
            continue
        step(f"Cảnh {i + 1}/{total}: hình ảnh")
        visual = sc["visual"] or sc["keyword"] or sc["headline"]
        bg_video = False
        if i in veo_at:
            step(f"Cảnh {i + 1}/{total}: tạo video AI Veo (1-3 phút)")
            try:
                aimedia.veo(f"{visual}. Cinematic, realistic, smooth camera movement, no text, no logos, no speech.",
                            aspect, gkey, work / f"bgv{i}.mp4")
                bg_video = True
            except aimedia.AIError as e:
                _log(f"Cảnh {i + 1}: Veo lỗi, dùng ảnh thay thế — {str(e)[:160]}")
        ai_photo = None
        if not bg_video and cfg["visual"] == "ai" and gkey and visual:
            step(f"Cảnh {i + 1}/{total}: vẽ ảnh AI")
            try:
                data = aimedia.image(f"{visual}. Photorealistic, natural lighting, vibrant, high detail, "
                                     f"no text, no watermark, no logos.", aspect, gkey)
                ai_photo = work / f"ai{i}.img"
                ai_photo.write_bytes(data)
            except aimedia.AIError as e:
                _log(f"Cảnh {i + 1}: ảnh AI lỗi, dùng nền thay thế — {str(e)[:160]}")
        if ai_photo:
            render_background(ai_photo, size, cfg["color"], work / f"bg{i}.png", "blur" if expl else "photo")
        elif not bg_video:
            bg_video = pexels_video(sc["keyword"], cfg["pexels_key"], size, work / f"bgv{i}.mp4", used_videos)
        if not bg_video and not ai_photo:
            if pexels_photo(sc["keyword"], cfg["pexels_key"], L.vertical, work / f"photo{i}.img"):
                render_background(work / f"photo{i}.img", size, cfg["color"], work / f"bg{i}.png", "photo")
            elif article_img and not expl:
                mode = "photo" if sc["type"] == "hook" and not sc["headline"] else "blur"
                render_background(article_img, size, cfg["color"], work / f"bg{i}.png", mode)
            elif tech:
                techlook.background(size, work / f"bg{i}.png", seed=video_id)          # cùng 1 nền cho cả clip
            elif expl:
                explainer.background(size, work / f"bg{i}.png", seed=video_id)
            else:
                render_background(None, size, cfg["color"], work / f"bg{i}.png", "none", seed=video_id * 100 + i)

        if expl:
            builder = techlook.build if tech else explainer.build
            illus_fn = None
            if sc["type"] == "visual" and sc["panels"]:
                step(f"Cảnh {i + 1}/{total}: vẽ hình minh họa" + (" (AI)" if gkey else ""))
                arts = doodle.panel_arts(sc, gkey, ai_state, _log)

                def illus_fn(k, wh, sc=sc, arts=arts, i=i):
                    pv = sc["panels"][k]
                    return doodle.panel_image(arts[k] if k < len(arts) else None, pv.get("label", ""), wh, seed=i * 10 + k,
                                              visual=pv.get("visual", ""))
            layers, captions = builder(L, sc, i, total, work, cfg["brand"], dur, voice_len, illus=illus_fn)
        else:
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
        try:
            render_scene(work, i, size, dur, bg_video, layers, captions, fade_out=0.3 if expl else 0.0,
                         pan=(i / total, (i + 1) / total) if expl else None)
        except VideoError as e:
            if not bg_video:
                raise VideoError(f"Cảnh {i + 1}: {e}") from e
            _log(f"Cảnh {i + 1}: video nền lỗi, dùng nền tĩnh — {str(e)[:120]}")      # video tải về hỏng → nền tĩnh, không bỏ cả clip
            if tech:
                techlook.background(size, work / f"bg{i}.png", seed=video_id)
            elif expl:
                explainer.background(size, work / f"bg{i}.png", seed=video_id)
            else:
                render_background(None, size, cfg["color"], work / f"bg{i}.png", "none", seed=video_id * 100 + i)
            render_scene(work, i, size, dur, False, layers, captions, fade_out=0.3 if expl else 0.0,
                         pan=(i / total, (i + 1) / total) if expl else None)
        durations.append(dur)
    music = random.choice(_music_files()) if cfg["music"] and _music_files() else None
    step("Ghép các cảnh + hiệu ứng chuyển cảnh" + (" + nhạc nền" if music else ""))
    out = work / "clip.mp4"
    join_scenes(work, durations, out, music, trans, tnames)
    for p in work.iterdir():                          # dọn file tạm, chỉ giữ clip
        if p != out:
            p.unlink(missing_ok=True)
    length = sum(durations) - trans * (len(durations) - 1)
    note = ""
    if (paper or ai_state.fails or ai_state.ok) and ai_state.fails and not paper:
        note = (f"Hình minh họa: AI vẽ được {ai_state.ok} hình, {ai_state.fails} hình lỗi nên dùng hình phác thảo có sẵn. "
                f"Lý do: {ai_state.reason}")
    elif paper and not gkey:
        note = "Chưa có Gemini key nên dùng bộ hình phác thảo có sẵn. Nhập key ở tab Tin tức AI để AI vẽ hình riêng cho từng cảnh."
    elif paper and ai_state.fails:
        note = (f"AI vẽ được {ai_state.ok} hình, {ai_state.fails} hình lỗi nên dùng hình phác thảo có sẵn. "
                f"Lý do: {ai_state.reason}")
    db.video_update(video_id, status="done", path=str(out), duration=round(length, 1), progress="", error=note)
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

