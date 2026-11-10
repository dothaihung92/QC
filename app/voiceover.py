"""Lồng giọng đọc vào CLIP CÓ SẴN: người dùng tải clip lên + dán kịch bản → phần mềm tạo giọng đọc tiếng Việt
(giọng đã chọn ở Cài đặt clip: VieNeu / Gemini / Microsoft...) rồi ghép vào clip, tùy chọn kèm phụ đề tô sáng từng chữ.

Các bước: đọc clip → đọc kịch bản (dòng "Cảnh 1 — ...", tiêu đề, ghi chú trong ngoặc KHÔNG được đọc) → giọng đọc từng đoạn →
tìm các điểm chuyển cảnh trong clip để lời đọc cảnh nào khớp đúng cảnh đó → xử lý độ dài từng cảnh (giữ khung hình cuối /
lặp lại / cắt / co giãn tốc độ) → trộn âm thanh (tắt / giữ nhỏ / giữ nguyên tiếng gốc) → vẽ phụ đề → ghép thành clip.mp4.
"""
import math
import re
import shutil
import subprocess
import os
import uuid
from pathlib import Path

from . import config, db
from . import video as V

UPLOAD_DIR = config.DATA_DIR / "voiceovers"
EXTS = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}
MAX_UPLOAD = 1024 * 1024 * 1024               # 1 GB
FIT = {
    "keep": "Giữ nguyên clip; lời đọc dài hơn thì kéo dài bằng khung hình cuối",
    "loop": "Lặp lại clip cho tới khi hết lời đọc",
    "trim": "Cắt clip đúng bằng độ dài lời đọc",
    "stretch": "Co giãn tốc độ clip cho vừa lời đọc (làm chậm / nhanh nhẹ)",
}
ORIG = {"none": "Tắt tiếng gốc của clip", "low": "Giữ tiếng gốc nhỏ (nền)", "full": "Giữ tiếng gốc"}
CAPS = {"bottom": "Phụ đề ở dưới (mặc định)", "high": "Phụ đề cao hơn (tránh phụ đề có sẵn trong clip)",
        "top": "Phụ đề ở trên cùng", "none": "Không hiện phụ đề (clip đã có phụ đề)"}
CAP_Y = {"bottom": 0.875, "high": 0.74, "top": 0.12}
DEFAULTS = {"fit": "keep", "audio": "none", "caption_pos": "bottom", "sync": True}
SCENE_GAP = 0.3                                # nghỉ giữa hai cảnh
CUT_FPS = 8                                    # số khung/giây dùng để dò chuyển cảnh
CUT_MIN = 3.0                                  # mức thay đổi trung bình tối thiểu (0-255) để coi là chuyển cảnh
PAUSE = 0.25                                   # nghỉ giữa các đoạn (giây)
PARA_PAUSE = 0.55                              # nghỉ khi sang đoạn văn mới
TAIL = 0.5                                     # chừa đuôi sau lời đọc cuối
MAX_SIDE = 1080                                # cạnh ngắn tối đa của clip xuất ra


class VoiceoverError(Exception):
    pass


def clean_options(o) -> dict:
    o = o if isinstance(o, dict) else {}
    pos = o.get("caption_pos")
    if pos not in CAPS:                                   # tương thích bản cũ: captions True/False
        pos = DEFAULTS["caption_pos"] if o.get("captions", True) else "none"
    return {"fit": o.get("fit") if o.get("fit") in FIT else DEFAULTS["fit"],
            "audio": o.get("audio") if o.get("audio") in ORIG else DEFAULTS["audio"],
            "caption_pos": pos, "captions": pos != "none",
            "sync": bool(o.get("sync", DEFAULTS["sync"]))}


# ---------------------------------------------------------------- tải lên

def new_upload_path(filename: str) -> Path:
    ext = Path(filename or "").suffix.lower()
    if ext not in EXTS:
        raise VoiceoverError("Chỉ nhận clip MP4, MOV, M4V, WEBM, MKV, AVI")
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    return UPLOAD_DIR / f"{uuid.uuid4().hex[:16]}{ext}"


def upload_file(token: str):
    """token (tên tệp đã tải lên) → đường dẫn tệp; không hợp lệ thì None."""
    if not re.fullmatch(r"[0-9a-f]{16}\.\w{2,4}", token or ""):
        return None
    p = UPLOAD_DIR / token
    return p if p.is_file() else None


def probe(path: Path) -> dict:
    """{duration, width, height, has_audio} của clip (đọc từ thông tin FFmpeg)."""
    kw = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    r = subprocess.run([V.ffmpeg_exe(), "-hide_banner", "-i", str(path)], capture_output=True, text=True, **kw)
    err = r.stderr
    m = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", err)
    v = re.search(r"Video: .*?, (\d{2,5})x(\d{2,5})", err)
    if not m or not v:
        raise VoiceoverError("Không đọc được clip này (tệp hỏng hoặc không phải video)")
    w, h = int(v[1]), int(v[2])
    rot = re.search(r"rotate\s*:\s*(-?\d+)", err) or re.search(r"rotation of (-?\d+(?:\.\d+)?) degrees", err)
    if rot and round(abs(float(rot[1]))) in (90, 270):
        w, h = h, w
    dur = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])
    return {"duration": dur, "width": w, "height": h, "has_audio": bool(re.search(r"Stream #.*Audio:", err))}


# ---------------------------------------------------------------- kịch bản → các cảnh

_MARK = re.compile(r"^\s*[#>*\-\s]*(Cảnh|Canh|Scene|Phần|Phan|Đoạn)\s*(\d+)\s*(.*)$", re.I)
_TIME = re.compile(r"[\[(@]\s*(?:(\d{1,2}):)?(\d{1,2}):(\d{2})(?:[.,]\d+)?\s*[\])]?")


def _meta_line(line: str, first: bool) -> bool:
    """Dòng không phải lời đọc: tiêu đề, ghi chú trong ngoặc, đường kẻ..."""
    t = line.strip()
    if not t or re.fullmatch(r"[-_=*~#\s.]{3,}", t):
        return True
    if re.fullmatch(r"[(\[（].*[)\]）]", t):                       # (ghi chú), [hướng dẫn]
        return True
    if re.match(r"#{1,6}\s", t):                                  # tiêu đề markdown
        return True
    if first and re.search(r"kịch bản|lời đọc|voice\s*over|script", t, re.I) and not re.search(r"[.!?…]$", t) and len(t) < 160:
        return True
    return False


def parse_script(script: str) -> dict:
    """{"scenes": [{"n","label","time","text"}], "skipped": [dòng bỏ qua], "markers": số cảnh}.
    Dòng "Cảnh 3 — BƯỚC 1: Mở chức năng" chỉ đánh dấu cảnh mới (không đọc); có thể kèm thời điểm [00:12] để ép đúng chỗ."""
    scenes, skipped, cur, first = [], [], None, True
    for raw in (script or "").replace("\r", "").split("\n"):
        line = raw.strip()
        if not line:
            if cur:
                cur["lines"].append("")
            continue
        m = _MARK.match(line)
        if m and (not m[3] or re.match(r"[—–:.\-\[(@|]", m[3]) or m[1].lower() in ("cảnh", "canh", "scene")):
            tm = _TIME.search(m[3])
            t = int(tm[1] or 0) * 3600 + int(tm[2]) * 60 + int(tm[3]) if tm else None
            label = _TIME.sub(" ", m[3]).strip(" —–:.-|\t")
            cur = {"n": int(m[2]), "label": label, "time": t, "lines": []}
            scenes.append(cur)
            first = False
            continue
        if _meta_line(line, first):
            skipped.append(line)
            first = False
            continue
        first = False
        if cur is None:
            cur = {"n": 1, "label": "", "time": None, "lines": []}
            scenes.append(cur)
        cur["lines"].append(line)
    markers = len(scenes)
    out = []
    for s in scenes:
        text = "\n".join(s["lines"]).strip()
        if V.clean_tts_text(text):
            out.append({"n": s["n"], "label": s["label"], "time": s["time"], "text": text})
    return {"scenes": out, "skipped": skipped, "markers": markers}


def summarize(script: str) -> dict:
    """Bản xem trước cho giao diện: mỗi cảnh đọc những gì, bỏ qua dòng nào, ước tính thời lượng."""
    p = parse_script(script)
    sc = []
    for s in p["scenes"]:
        chars = len(V.clean_tts_text(s["text"]))
        sc.append({"n": s["n"], "label": s["label"], "time": s["time"], "chars": chars,
                   "seconds": round(chars / 14.0, 1), "preview": V.clean_tts_text(s["text"])[:90]})
    return {"scenes": sc, "skipped": p["skipped"][:8], "skipped_count": len(p["skipped"]),
            "seconds": round(sum(x["seconds"] for x in sc), 1)}


# ---------------------------------------------------------------- một cảnh → các đoạn đọc

def split_script(script: str, max_chars: int = 230) -> list:
    """[(đoạn chữ, nghỉ sau đoạn)] — cắt theo đoạn văn rồi theo câu, mỗi đoạn tối đa ~max_chars ký tự."""
    out = []
    paras = [p.strip() for p in re.split(r"\n\s*\n|\n", script or "") if p.strip()]
    for pi, para in enumerate(paras):
        sentences = re.findall(r"[^.!?…]+(?:[.!?…]+|$)", para) or [para]
        cur = ""
        for sen in (x.strip() for x in sentences if x.strip()):
            if cur and len(cur) + 1 + len(sen) > max_chars:
                out.append([cur, PAUSE])
                cur = sen
            else:
                cur = (cur + " " + sen).strip()
            while len(cur) > max_chars * 1.6:                    # câu quá dài không có dấu chấm: cắt ở dấu phẩy / khoảng trắng
                cut = max(cur.rfind(",", 0, max_chars), cur.rfind(" ", 0, max_chars))
                cut = cut if cut > 40 else max_chars
                out.append([cur[:cut + 1].strip(), PAUSE])
                cur = cur[cut + 1:].strip()
        if cur:
            out.append([cur, PARA_PAUSE if pi < len(paras) - 1 else 0.0])
    return [(t, p) for t, p in out if V.clean_tts_text(t)]


# ---------------------------------------------------------------- dựng

def _even(n: float) -> int:
    n = int(round(n))
    return n if n % 2 == 0 else n + 1


def out_size(w: int, h: int) -> tuple:
    f = min(1.0, MAX_SIDE / min(w, h))
    return _even(w * f), _even(h * f)


def detect_cuts(path: Path, dur: float) -> list:
    """[(giây, mức thay đổi)] — các chỗ hình ảnh đổi mạnh trong clip (chuyển cảnh / đổi màn hình).
    Tự so sánh các khung hình thu nhỏ 48x27 (8 khung/giây, đủ cả màu) nên không phụ thuộc bộ lọc "scene" của FFmpeg."""
    kw = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    r = subprocess.run([V.ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-i", str(path), "-an", "-vf",
                        f"fps={CUT_FPS},scale=48:27:flags=area,format=rgb24", "-f", "rawvideo", "-"],
                       capture_output=True, timeout=1800, **kw)
    raw, n = r.stdout, 48 * 27 * 3
    frames = [raw[i:i + n] for i in range(0, len(raw) - n + 1, n)]
    out = []
    try:
        import numpy as np
        arr = np.frombuffer(b"".join(frames), dtype=np.uint8).reshape(-1, n).astype(np.int16) if frames else None
        diffs = [] if arr is None else np.abs(np.diff(arr, axis=0)).mean(axis=1).tolist()
    except ImportError:
        diffs = [sum(abs(a - b) for a, b in zip(x, y)) / n for x, y in zip(frames, frames[1:])]
    for i, d in enumerate(diffs):
        if d >= CUT_MIN:
            out.append(((i + 1) / CUT_FPS, d / 255.0))
    return out


def scene_bounds(src: Path, vlen: float, scenes: list, narr: list) -> tuple:
    """Thời điểm bắt đầu từng cảnh trong clip gốc: [0, b1, ..., vlen] và cách xác định (marker / detect / prop / single)."""
    n = len(scenes)
    if n == 1:
        return [0.0, vlen], "single"
    times = [s.get("time") for s in scenes[1:]]
    if all(t is not None for t in times) and times == sorted(times) and 0 < times[0] and times[-1] < vlen - 0.5:
        return [0.0, *[float(t) for t in times], vlen], "marker"
    gap = min(max(1.0, vlen * 0.02), vlen / (2.0 * n))
    try:
        cuts = detect_cuts(src, vlen)
    except Exception as e:  # noqa: BLE001
        V._log(f"Không dò được điểm chuyển cảnh ({str(e)[:60]})")
        cuts = []
    picked = []
    for t, _score in sorted(cuts, key=lambda c: -c[1]):
        if t < gap or t > vlen - gap or any(abs(t - p) < gap for p in picked):
            continue
        picked.append(t)
        if len(picked) == n - 1:
            return [0.0, *sorted(picked), vlen], "detect"
    tot = sum(narr) or 1.0                                   # không đủ điểm chuyển cảnh: chia theo độ dài lời đọc
    b, acc = [0.0], 0.0
    for x in narr[:-1]:
        acc += x
        b.append(vlen * acc / tot)
    return [*b, vlen], "prop"


def render(video_id: int):
    v = db.video_get(video_id)
    if not v or v["kind"] != "voiceover":
        raise VoiceoverError("Không có clip lồng tiếng này")
    src = Path(v["source"])
    if not src.is_file():
        raise VoiceoverError("Clip gốc đã bị xóa — tải lại clip lên")
    opts = clean_options(v["options"])
    cfg = V.get_config()
    parsed = parse_script(v["script"])
    scenes = parsed["scenes"]
    if not scenes:
        raise VoiceoverError("Kịch bản trống — nhập lời đọc vào ô kịch bản")
    if parsed["skipped"]:
        V._log(f"Bỏ qua {len(parsed['skipped'])} dòng ghi chú/tiêu đề (không đọc): " + " | ".join(x[:40] for x in parsed["skipped"][:3]))
    if len(scenes) > 1 and not opts["sync"]:                        # không khớp theo cảnh: đọc liền một mạch
        scenes = [{"n": 1, "label": "", "time": None, "text": "\n\n".join(s["text"] for s in scenes)}]
    work = V.VIDEO_DIR / str(video_id)
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)

    def step(msg):
        db.video_update(video_id, progress=msg)
        V._log(msg)

    info = probe(src)
    W, H = out_size(info["width"], info["height"])
    L = V.Layout((W, H))
    L.ts = 1.0
    L.cap_frac = CAP_Y.get(opts["caption_pos"], CAP_Y["bottom"])
    from . import techlook, themes
    themes.apply(themes.pick("dem", 0))
    style = V.STYLES[cfg["tts_style"]][1]
    chunk_sets = [split_script(s["text"]) for s in scenes]
    total = sum(len(c) for c in chunk_sets)
    S = len(scenes)

    # 1) giọng đọc từng đoạn của từng cảnh (đoạn cuối mỗi cảnh không nghỉ thêm — nghỉ giữa cảnh tính riêng)
    items, scene_files, scene_narr = [], [], []       # items: [cảnh, văn bản hiện, độ dài giọng, nghỉ, bắt đầu trong cảnh, tên mp3]
    j = 0
    for si, chunks in enumerate(chunk_sets):
        t, files = 0.0, []
        for ci, (text, gap) in enumerate(chunks):
            if ci == len(chunks) - 1:
                gap = 0.0
            step(f"Giọng đọc {j + 1}/{total}")
            mp3 = work / f"v{j}.mp3"
            used = V.tts(text, cfg["voice"], cfg["rate"], mp3, style)
            if j == 0 and used != V.VOICES.get(cfg["voice"], "").split(" — ")[0]:
                V._log(f"Giọng đã chọn lỗi, đã dùng giọng {used}")
            n = V.media_duration(mp3)
            padded = work / f"p{j}.wav"                              # giọng + khoảng nghỉ, cùng định dạng để nối liền
            V._ffmpeg(["-i", mp3.name, "-af", f"apad=pad_dur={gap:.2f}", "-ar", "44100", "-ac", "1", padded.name], work)
            items.append([si, V.expand_abbr(V.clean_tts_text(text)), n, gap, t, mp3.name])
            files.append(padded.name)
            t += V.media_duration(padded)
            j += 1
        scene_files.append(files)
        scene_narr.append(t)

    # 2) mỗi cảnh của kịch bản ↔ một đoạn của clip gốc
    vlen = info["duration"]
    bounds, how = scene_bounds(src, vlen, scenes, scene_narr)
    if S > 1:
        label = {"marker": "theo thời điểm bạn ghi trong kịch bản", "detect": "theo các điểm chuyển cảnh dò được trong clip",
                 "prop": "chia theo độ dài lời đọc (clip ít điểm chuyển cảnh)"}[how]
        step(f"Khớp {S} đoạn lời đọc với {S} cảnh của clip — {label}")
        V._log("Mốc cảnh trong clip: " + ", ".join(f"{x:.1f}s" for x in bounds))
    need = [scene_narr[i] + (TAIL if i == S - 1 else SCENE_GAP) for i in range(S)]
    fit = opts["fit"]
    segs, tlen, factors = [], [], []
    for i in range(S):
        D = max(0.2, bounds[i + 1] - bounds[i])
        f = 1.0
        if fit == "stretch":
            f = min(1.6, max(0.6, need[i] / D))
            T = max(D * f, need[i])
        elif fit == "trim":
            T = need[i]
        else:                                                         # keep / loop: không ngắn hơn cảnh gốc
            T = max(D, need[i])
        step(f"Xử lý cảnh {i + 1}/{S} của clip")
        vf = [f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black",
              "setsar=1", f"fps={V.FPS}", "format=yuv420p"]
        cut = f"cut{i}.mp4"
        V._ffmpeg(["-ss", f"{bounds[i]:.3f}", "-t", f"{D:.3f}", "-i", str(src), "-an", "-vf", ",".join(vf), "-c:v", "libx264",
                   "-preset", "veryfast", "-crf", "20", "-r", str(V.FPS), cut], work)
        out_seg = f"seg{i}.mp4"
        pre, flt = [], []
        if f != 1.0:
            flt.append(f"setpts=PTS*{f:.5f}")
        shown = D * f
        if fit == "loop" and T > D + 0.05:
            pre = ["-stream_loop", "-1"]
        elif T > shown + 0.03:
            flt.append(f"tpad=stop_mode=clone:stop_duration={T - shown + 0.2:.3f}")
        if not pre and not flt and abs(T - D) < 0.03:
            out_seg = cut
        else:
            V._ffmpeg([*pre, "-i", cut, "-t", f"{T:.3f}", *(["-vf", ",".join(flt)] if flt else []), "-c:v", "libx264",
                       "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(V.FPS), out_seg], work)
        segs.append(out_seg)
        tlen.append(T)
        factors.append(f)
    total_len = sum(tlen)
    (work / "vsegs.txt").write_text("".join(f"file '{f}'\n" for f in segs), encoding="utf-8")
    base = work / "base.mp4"
    V._ffmpeg(["-f", "concat", "-safe", "0", "-i", "vsegs.txt", "-c:v", "copy", base.name], work)

    # 3) âm thanh: lời đọc từng cảnh bắt đầu đúng lúc cảnh đó bắt đầu (+ tiếng gốc nếu giữ)
    step("Trộn âm thanh")
    nfiles, starts_scene, acc = [], [], 0.0
    for i in range(S):
        (work / f"nl{i}.txt").write_text("".join(f"file '{f}'\n" for f in scene_files[i]), encoding="utf-8")
        V._ffmpeg(["-f", "concat", "-safe", "0", "-i", f"nl{i}.txt", "-af", f"apad,atrim=duration={tlen[i]:.3f}",
                   "-ar", "44100", "-ac", "1", f"ns{i}.wav"], work)
        nfiles.append(f"ns{i}.wav")
        starts_scene.append(acc)
        acc += tlen[i]
    (work / "nlist.txt").write_text("".join(f"file '{f}'\n" for f in nfiles), encoding="utf-8")
    V._ffmpeg(["-f", "concat", "-safe", "0", "-i", "nlist.txt", "-c:a", "pcm_s16le", "narration.wav"], work)
    audio = work / "audio.m4a"
    keep_orig = opts["audio"] != "none" and info["has_audio"]
    if opts["audio"] != "none" and not info["has_audio"]:
        V._log("Clip gốc không có tiếng — chỉ dùng giọng đọc")
    if keep_orig:
        vol = 0.14 if opts["audio"] == "low" else 0.7
        ofiles = []
        for i in range(S):
            af = [f"volume={vol}"]
            if factors[i] != 1.0:
                af.append(f"atempo={1 / factors[i]:.5f}")
            af.append(f"apad,atrim=duration={tlen[i]:.3f}")
            V._ffmpeg(["-ss", f"{bounds[i]:.3f}", "-t", f"{max(0.2, bounds[i + 1] - bounds[i]):.3f}", "-i", str(src), "-vn", "-af",
                       ",".join(af), "-ar", "44100", "-ac", "1", f"os{i}.wav"], work)
            ofiles.append(f"os{i}.wav")
        (work / "olist.txt").write_text("".join(f"file '{f}'\n" for f in ofiles), encoding="utf-8")
        V._ffmpeg(["-f", "concat", "-safe", "0", "-i", "olist.txt", "-c:a", "pcm_s16le", "orig.wav"], work)
        V._ffmpeg(["-i", "orig.wav", "-i", "narration.wav", "-filter_complex",
                   "[0:a][1:a]amix=inputs=2:duration=longest,volume=2[a]",
                   "-map", "[a]", "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2", audio.name], work)
    else:
        V._ffmpeg(["-i", "narration.wav", "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2", audio.name], work)

    # 4) phụ đề tô sáng từng chữ (đúng chữ đang đọc; hết trước khi đoạn sau bắt đầu)
    caps = []
    if opts["caption_pos"] != "none":
        step("Vẽ phụ đề")
        starts = [starts_scene[it[0]] + it[4] for it in items]
        for k, (si, text, n, gap, _t, mp3) in enumerate(items):
            pad = math.ceil((n + gap) * V.FPS) / V.FPS
            try:
                cs = V.karaoke_captions(L, work, f"vc{k}", text, work / mp3, pad, n,
                                        lambda w, a, dest: techlook.caption_layer(L, w, a, dest), 6)
            except Exception as e:  # noqa: BLE001 — phụ đề lỗi không làm hỏng cả clip
                V._log(f"Đoạn {k + 1}: không vẽ được phụ đề ({str(e)[:80]})")
                continue
            limit = starts[k + 1] if k + 1 < len(starts) else total_len
            caps += [(name, pos, starts[k] + a, min(starts[k] + b, limit)) for name, pos, a, b in cs if starts[k] + a < limit]

    out = work / "clip.mp4"
    if caps:
        _burn_captions(work, base, audio, caps, total_len, out, step)
    else:
        step("Ghép clip")
        V._ffmpeg(["-i", base.name, "-i", audio.name, "-c:v", "copy", "-c:a", "copy", "-t", f"{total_len:.3f}",
                   "-movflags", "+faststart", out.name], work)
    for f in work.iterdir():                                        # chỉ giữ clip kết quả
        if f.name != "clip.mp4":
            f.unlink(missing_ok=True)
    dur = V.media_duration(out)
    db.video_update(video_id, status="done", progress="", path=str(out), duration=dur, error="")
    db.log("video", f"Lồng giọng đọc xong clip #{video_id} ({dur:.0f}s, {S} cảnh)")


def _burn_captions(work: Path, base: Path, audio: Path, caps: list, total: float, out: Path, step, window: float = 10.0):
    """Vẽ phụ đề theo từng khoảng ~10 giây (mỗi lần FFmpeg chỉ ghép vài chục ảnh — nhẹ và ổn định), rồi nối lại + gắn âm thanh."""
    nwin = max(1, math.ceil(total / window))
    segs = []
    for w in range(nwin):
        t0, t1 = w * window, min(total, (w + 1) * window)
        step(f"Ghép phụ đề {w + 1}/{nwin}")
        inputs, flt, cur, n = ["-ss", f"{t0:.3f}", "-t", f"{t1 - t0:.3f}", "-i", base.name], [], "0:v", 1
        for name, (x, y), a, b in caps:
            if b <= t0 or a >= t1:
                continue
            inputs += ["-framerate", str(V.FPS), "-i", name]
            flt.append(f"[{n}:v]format=rgba,loop=loop=-1:size=1:start=0,setpts=N/{V.FPS}/TB[l{n}]")
            flt.append(f"[{cur}][l{n}]overlay=x={x}:y={y}:enable='between(t,{max(0, a - t0):.2f},{b - t0:.2f})'[s{n}]")
            cur, n = f"s{n}", n + 1
        seg = f"seg{w}.mp4"
        cmd = [*inputs]
        if flt:
            cmd += ["-filter_complex", ";".join(flt), "-map", f"[{cur}]"]
        cmd += ["-t", f"{t1 - t0:.3f}", "-r", str(V.FPS), "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-pix_fmt", "yuv420p", seg]
        V._ffmpeg(cmd, work)
        segs.append(seg)
    (work / "segs.txt").write_text("".join(f"file '{s}'\n" for s in segs), encoding="utf-8")
    step("Ghép clip")
    V._ffmpeg(["-f", "concat", "-safe", "0", "-i", "segs.txt", "-i", audio.name, "-c:v", "copy", "-c:a", "copy",
               "-t", f"{total:.3f}", "-movflags", "+faststart", out.name], work)


def render_safe(video_id: int):
    try:
        render(video_id)
    except Exception as e:  # noqa: BLE001
        db.video_update(video_id, status="failed", error=str(e)[:400], progress="")
        db.log("error", f"lồng giọng clip #{video_id}: {e}")
        raise
