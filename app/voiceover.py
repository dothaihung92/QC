"""Lồng giọng đọc vào CLIP CÓ SẴN: người dùng tải clip lên + dán kịch bản → phần mềm tạo giọng đọc tiếng Việt
(giọng đã chọn ở Cài đặt clip: VieNeu / Gemini / Microsoft...) rồi ghép vào clip, tùy chọn kèm phụ đề tô sáng từng chữ.

Các bước: đọc clip → chia kịch bản thành các đoạn → giọng đọc từng đoạn (nghỉ giữa đoạn) → xử lý độ dài clip cho khớp lời đọc
(kéo dài bằng khung hình cuối / lặp lại / cắt / co giãn tốc độ) → trộn âm thanh (tắt / giữ nhỏ / giữ nguyên tiếng gốc)
→ vẽ phụ đề → ghép thành clip.mp4.
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
DEFAULTS = {"fit": "keep", "audio": "none", "captions": True}
PAUSE = 0.25                                   # nghỉ giữa các đoạn (giây)
PARA_PAUSE = 0.55                              # nghỉ khi sang đoạn văn mới
TAIL = 0.5                                     # chừa đuôi sau lời đọc cuối
MAX_SIDE = 1080                                # cạnh ngắn tối đa của clip xuất ra


class VoiceoverError(Exception):
    pass


def clean_options(o) -> dict:
    o = o if isinstance(o, dict) else {}
    return {"fit": o.get("fit") if o.get("fit") in FIT else DEFAULTS["fit"],
            "audio": o.get("audio") if o.get("audio") in ORIG else DEFAULTS["audio"],
            "captions": bool(o.get("captions", DEFAULTS["captions"]))}


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


# ---------------------------------------------------------------- kịch bản → các đoạn đọc

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


def render(video_id: int):
    v = db.video_get(video_id)
    if not v or v["kind"] != "voiceover":
        raise VoiceoverError("Không có clip lồng tiếng này")
    src = Path(v["source"])
    if not src.is_file():
        raise VoiceoverError("Clip gốc đã bị xóa — tải lại clip lên")
    opts = clean_options(v["options"])
    cfg = V.get_config()
    parts = split_script(v["script"])
    if not parts:
        raise VoiceoverError("Kịch bản trống — nhập lời đọc vào ô kịch bản")
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
    from . import techlook, themes
    themes.apply(themes.pick("dem", 0))
    style = V.STYLES[cfg["tts_style"]][1]
    total = len(parts)

    # 1) giọng đọc từng đoạn + vị trí bắt đầu trên trục thời gian
    starts, seg_files, seg_len, lead = [], [], [], 0.0
    t = 0.0
    for k, (text, gap) in enumerate(parts):
        step(f"Giọng đọc {k + 1}/{total}")
        mp3 = work / f"v{k}.mp3"
        used = V.tts(text, cfg["voice"], cfg["rate"], mp3, style)
        if k == 0 and used != V.VOICES.get(cfg["voice"], "").split(" — ")[0]:
            V._log(f"Giọng đã chọn lỗi, đã dùng giọng {used}")
        n = V.media_duration(mp3)
        padded = work / f"p{k}.wav"                                 # giọng + khoảng nghỉ, cùng định dạng để nối liền
        V._ffmpeg(["-i", f"v{k}.mp3", "-af", f"apad=pad_dur={gap:.2f}", "-ar", "44100", "-ac", "1", padded.name], work)
        starts.append(t)
        seg_files.append(padded.name)
        seg_len.append(n)
        t += V.media_duration(padded)
    narr_len = t
    (work / "list.txt").write_text("".join(f"file '{f}'\n" for f in seg_files), encoding="utf-8")
    V._ffmpeg(["-f", "concat", "-safe", "0", "-i", "list.txt", "-c:a", "pcm_s16le", "narration.wav"], work)
    need = narr_len + TAIL

    # 2) chọn cách khớp độ dài clip
    vlen = info["duration"]
    fit = opts["fit"]
    vf, vin, total_len, note = [], [], vlen, ""
    if fit == "stretch":
        k = need / vlen
        if 0.6 <= k <= 1.6:
            vf.append(f"setpts=PTS*{k:.5f}")
            total_len = need
        else:
            fit, note = "keep", f"Lời đọc ({need:.0f}s) lệch quá nhiều so với clip ({vlen:.0f}s) để co giãn — dùng cách giữ nguyên clip."
    if fit == "loop":
        vin = ["-stream_loop", "-1"]
        total_len = need if need > vlen else vlen
    elif fit == "trim":
        total_len = need
        if need > vlen:                                              # clip ngắn hơn lời đọc: kéo bằng khung hình cuối
            vf.append(f"tpad=stop_mode=clone:stop_duration={need - vlen + 0.1:.3f}")
    elif fit == "keep":
        total_len = max(vlen, need)
        if need > vlen:
            vf.append(f"tpad=stop_mode=clone:stop_duration={need - vlen + 0.1:.3f}")
    if note:
        V._log(note)
    step("Xử lý clip gốc")
    vf += [f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black",
           "setsar=1", f"fps={V.FPS}", "format=yuv420p"]
    base = work / "base.mp4"
    V._ffmpeg([*vin, "-i", str(src), "-t", f"{total_len:.3f}", "-an", "-vf", ",".join(vf),
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", str(V.FPS), base.name], work)

    # 3) âm thanh: giọng đọc (+ tiếng gốc nếu giữ)
    step("Trộn âm thanh")
    audio = work / "audio.m4a"
    keep_orig = opts["audio"] != "none" and info["has_audio"] and fit != "stretch"
    if opts["audio"] != "none" and not info["has_audio"]:
        V._log("Clip gốc không có tiếng — chỉ dùng giọng đọc")
    if keep_orig:
        vol = 0.14 if opts["audio"] == "low" else 0.7
        ain = [*(["-stream_loop", "-1"] if fit == "loop" else []), "-i", str(src)]
        V._ffmpeg([*ain, "-i", "narration.wav", "-filter_complex",
                   f"[0:a]volume={vol},apad,atrim=duration={total_len:.3f}[o];[1:a]apad,atrim=duration={total_len:.3f}[n];"
                   "[o][n]amix=inputs=2:duration=longest,volume=2[a]",
                   "-map", "[a]", "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2", audio.name], work)
    else:
        V._ffmpeg(["-i", "narration.wav", "-af", f"apad,atrim=duration={total_len:.3f}", "-c:a", "aac", "-b:a", "160k",
                   "-ar", "44100", "-ac", "2", audio.name], work)

    # 4) phụ đề tô sáng từng chữ
    caps = []
    if opts["captions"]:
        step("Vẽ phụ đề")
        for k, (text, gap) in enumerate(parts):
            pad = math.ceil((seg_len[k] + gap) * V.FPS) / V.FPS
            try:
                cs = V.karaoke_captions(L, work, f"vc{k}", text, work / f"v{k}.mp3", pad, seg_len[k],
                                        lambda w, a, dest: techlook.caption_layer(L, w, a, dest), 6)
            except Exception as e:  # noqa: BLE001 — phụ đề lỗi không làm hỏng cả clip
                V._log(f"Đoạn {k + 1}: không vẽ được phụ đề ({str(e)[:80]})")
                continue
            limit = starts[k + 1] if k + 1 < len(starts) else narr_len + TAIL      # phụ đề đoạn này hết trước khi đoạn sau bắt đầu
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
    db.log("video", f"Lồng giọng đọc xong clip #{video_id} ({dur:.0f}s)")


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
