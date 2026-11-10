import subprocess

import pytest
from fastapi.testclient import TestClient

from app import db, server, video, voiceover

HAS_TOOLS = not video.missing_tools()
pytestmark = pytest.mark.skipif(not HAS_TOOLS, reason="thiếu ffmpeg")


@pytest.fixture
def client():
    return TestClient(server.app)


@pytest.fixture
def src_clip(tmp_path):
    """Clip thử 4 giây, 320x568, có tiếng bíp."""
    out = tmp_path / "src.mp4"
    video._ffmpeg(["-f", "lavfi", "-i", "testsrc=size=320x568:rate=30:duration=4", "-f", "lavfi", "-i", "sine=frequency=300:duration=4",
                   "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(out)], tmp_path)
    return out


@pytest.fixture(autouse=True)
def fake_voice(monkeypatch, tmp_path):
    monkeypatch.setattr(voiceover, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(video, "VIDEO_DIR", tmp_path / "videos")
    monkeypatch.setattr(video, "missing_tools", lambda: [])
    monkeypatch.setattr(video, "_run_bg", lambda fn, *a: fn(*a))

    def tts(text, voice, rate, dest, style=""):                       # mỗi chữ ~0.3 giây tiếng bíp
        n = max(1, len(text.split())) * 0.3
        video._ffmpeg(["-f", "lavfi", "-i", f"sine=frequency=440:duration={n:.2f}", "-c:a", "libmp3lame", str(dest)], dest.parent)
        return video.VOICES.get(voice, "x").split(" — ")[0]
    monkeypatch.setattr(video, "tts", tts)


def _make(src, tmp_path, **opt):
    up = voiceover.new_upload_path("a.mp4")
    up.write_bytes(src.read_bytes())
    return db.video_add("T", "", [], kind="voiceover", script=opt.pop("script", "Xin chào các bạn. Hôm nay mình giới thiệu phần mềm mới.\n\nHẹn gặp lại các bạn nhé."),
                        source=str(up), options=opt)


def _streams(path):
    r = subprocess.run([video.ffmpeg_exe(), "-hide_banner", "-i", str(path)], capture_output=True, text=True)
    return r.stderr


def test_split_script_makes_readable_chunks():
    parts = voiceover.split_script("Câu một. Câu hai ngắn.\n\nĐoạn mới bắt đầu ở đây! Và thêm một câu nữa?")
    assert [t for t, _ in parts] == ["Câu một. Câu hai ngắn.", "Đoạn mới bắt đầu ở đây! Và thêm một câu nữa?"]
    assert parts[0][1] == voiceover.PARA_PAUSE and parts[1][1] == 0.0                       # nghỉ lâu hơn khi sang đoạn mới
    long = "từ " * 300
    assert all(len(t) <= 230 * 1.7 for t, _ in voiceover.split_script(long))              # câu dài không dấu chấm vẫn được cắt
    assert voiceover.split_script("   \n  ") == []


@pytest.mark.parametrize("fit,audio,caps", [("keep", "none", True), ("loop", "low", False), ("trim", "full", False), ("stretch", "none", False)])
def test_voiceover_render_all_options(src_clip, tmp_path, fit, audio, caps):
    long_script = "Một hai ba bốn năm sáu bảy tám chín mười. " * 3 + "\n\nMười một mười hai mười ba mười bốn mười lăm."      # lời đọc ~ 8-9 giây, dài hơn clip 4 giây
    vid = _make(src_clip, tmp_path, fit=fit, audio=audio, captions=caps, script=long_script)
    video.start_render(vid)
    v = db.video_get(vid)
    assert v["status"] == "done", v["error"]
    out = v["path"]
    info = _streams(out)
    assert "Video:" in info and "Audio:" in info and "320x568" in info
    narr = sum(voiceover.split_script(long_script) and [0.3 * len(t.split()) + p for t, p in voiceover.split_script(long_script)])
    if fit == "stretch":
        assert abs(v["duration"] - (narr + voiceover.TAIL)) < 1.2                         # clip được co giãn khớp lời đọc
    else:
        assert v["duration"] >= narr - 1.0                                                # lời đọc dài hơn clip → kéo dài / lặp, không bị cắt mất lời
    assert [p.name for p in (tmp_path / "videos" / str(vid)).iterdir()] == ["clip.mp4"]  # chỉ giữ clip kết quả


def test_trim_cuts_a_longer_clip_to_the_narration(src_clip, tmp_path):
    vid = _make(src_clip, tmp_path, fit="trim", captions=False, script="Ngắn thôi.")
    video.start_render(vid)
    v = db.video_get(vid)
    assert v["status"] == "done" and v["duration"] < 3.0                                  # clip 4s bị cắt theo lời đọc ~1s + đuôi


def test_api_upload_create_edit_publish_delete(client, src_clip, tmp_path, monkeypatch):
    assert client.post("/api/voiceover/upload?filename=x.exe", content=b"abc").status_code == 400
    assert client.post("/api/voiceover/upload?filename=x.mp4", content=b"khong phai video").status_code == 400
    r = client.post("/api/voiceover/upload?filename=clip.mp4", content=src_clip.read_bytes())
    assert r.status_code == 200
    up = r.json()
    assert up["width"] == 320 and up["height"] == 568 and up["has_audio"] and 3.5 < up["duration"] < 4.5
    assert client.post("/api/voiceover", json={"token": "zzzz", "script": "Xin chào các bạn"}).status_code == 400
    assert client.post("/api/voiceover", json={"token": up["token"], "script": "ab"}).status_code == 400
    v = client.post("/api/voiceover", json={"token": up["token"], "script": "Xin chào các bạn, đây là clip thử.", "title": "Clip thử",
                                            "fit": "xyz", "audio": "low", "captions": False}).json()
    assert v["kind"] == "voiceover" and v["status"] == "done" and v["has_file"] and v["options"] == {"fit": "keep", "audio": "low", "captions": False, "caption_pos": "none", "sync": True}
    assert "source" not in v and v["source_name"].endswith(".mp4")
    assert client.get(f"/api/videos/{v['id']}/file").status_code == 200
    e = client.put(f"/api/voiceover/{v['id']}", json={"script": "Kịch bản mới được sửa.", "fit": "loop", "captions": True, "description": "mô tả"}).json()
    assert e["script"] == "Kịch bản mới được sửa." and e["options"]["fit"] == "loop" and e["options"]["captions"] is True and e["description"] == "mô tả"
    assert client.post(f"/api/videos/{v['id']}/render").json()["status"] == "done"
    from app import facebook
    sent = []
    monkeypatch.setattr(facebook, "publish_video", lambda path, d="", t="": sent.append((d, t)) or "v9")
    assert client.post(f"/api/videos/{v['id']}/publish").json()["fb_video_id"] == "v9" and sent[0][0] == "mô tả"
    src = voiceover.upload_file(up["token"])
    assert src is not None
    assert client.delete(f"/api/videos/{v['id']}").json() == {"ok": True}
    assert not src.exists()                                                                # xóa luôn clip gốc đã tải lên


def test_render_fails_clearly_when_source_deleted(src_clip, tmp_path):
    vid = _make(src_clip, tmp_path)
    db.video_get(vid)
    from pathlib import Path
    Path(db.video_get(vid)["source"]).unlink()
    with pytest.raises(video.VideoError, match="Clip gốc đã bị xóa"):
        video.start_render(vid)


def test_ui_has_voiceover_card():
    html = TestClient(server.app).get("/").text
    assert "Lồng giọng đọc vào clip có sẵn" in html and "voCreate()" in html and "/api/voiceover/upload" in html and "function voCard" in html


def test_captions_of_consecutive_chunks_never_overlap(src_clip, tmp_path, monkeypatch):
    seen = []
    real = voiceover._burn_captions
    monkeypatch.setattr(voiceover, "_burn_captions", lambda work, base, audio, caps, total, out, step: seen.extend(caps) or real(work, base, audio, caps, total, out, step))
    vid = _make(src_clip, tmp_path, fit="keep", captions=True, script="Một hai ba bốn năm sáu bảy tám chín mười.\n\nMười một mười hai mười ba mười bốn.")
    video.start_render(vid)
    assert db.video_get(vid)["status"] == "done" and seen
    ordered = sorted(seen, key=lambda c: c[2])
    assert all(a[3] <= b[2] + 1e-6 for a, b in zip(ordered, ordered[1:]))


SCRIPT = """KỊCH BẢN LỜI ĐỌC — Clip hướng dẫn Tra cứu & tải tờ khai thuế hàng loạt
(dùng để thu âm lại giọng người thật nếu muốn)

Cảnh 1 — Tra cứu & tải tờ khai thuế HÀNG LOẠT
Chào mừng bạn đến với hướng dẫn chức năng tra cứu. Chỉ với một lần bấm, phần mềm tự tra cứu.

Cảnh 2 — NỔI BẬT: Tải được cả tờ khai Quyết toán TNCN năm
Điểm nổi bật: tờ khai quyết toán TNCN năm không cho tải về.

Cảnh 3 — BƯỚC 1: Mở chức năng
Bước một. Ở thanh bên trái, bấm Hỗ trợ kê khai tự động.
"""


def test_parse_script_skips_headings_and_scene_markers():
    p = voiceover.parse_script(SCRIPT)
    assert [s["n"] for s in p["scenes"]] == [1, 2, 3]
    assert len(p["skipped"]) == 2 and "KỊCH BẢN" in p["skipped"][0] and p["skipped"][1].startswith("(dùng")
    spoken = " ".join(s["text"] for s in p["scenes"])
    for bad in ("Cảnh", "KỊCH BẢN", "BƯỚC 1", "NỔI BẬT:", "thu âm lại", "người thật"):
        assert bad not in spoken
    assert p["scenes"][0]["text"].startswith("Chào mừng") and p["scenes"][2]["label"] == "BƯỚC 1: Mở chức năng"
    # không có "Cảnh" → một cảnh, tiêu đề đầu vẫn bỏ; "Phần mềm ..." không bị nhầm là mốc cảnh
    q = voiceover.parse_script("# Tiêu đề\n(ghi chú đạo diễn)\nPhần mềm này rất tiện.\nCâu hai.")
    assert len(q["scenes"]) == 1 and q["scenes"][0]["text"] == "Phần mềm này rất tiện.\nCâu hai." and len(q["skipped"]) == 2
    t = voiceover.parse_script("Cảnh 1 [00:00] — A\nLời một.\nCảnh 2 (01:05) — B\nLời hai.")
    assert [s["time"] for s in t["scenes"]] == [0, 65]


def test_summarize_and_parse_endpoint(client):
    r = client.post("/api/voiceover/parse", json={"script": SCRIPT}).json()
    assert len(r["scenes"]) == 3 and r["skipped_count"] == 2 and r["seconds"] > 0
    assert "ghi chú" not in " ".join(x["preview"] for x in r["scenes"])


def test_abbreviations_are_spoken_in_full():
    assert video.expand_abbr("Quyết toán TNCN và MST của NNT") == "Quyết toán thuế thu nhập cá nhân và mã số thuế của người nộp thuế"
    assert video.expand_abbr("TNCNX không đổi") == "TNCNX không đổi"
    assert video.phonetic("Hạn token còn 3 ngày") == "Hạn tô-ken còn 3 ngày"
    assert "tô-ken" not in video.clean_tts_text("token")                         # phụ đề giữ nguyên chữ, chỉ giọng đọc đổi cách đọc


@pytest.fixture
def three_scene_clip(tmp_path):
    """Clip 9 giây gồm 3 cảnh màu khác hẳn nhau (đỏ / xanh lá / xanh dương), mỗi cảnh 3 giây."""
    out = tmp_path / "three.mp4"
    parts = ["color=c=red", "color=c=green", "color=c=blue"]
    cmd = []
    for c in parts:
        cmd += ["-f", "lavfi", "-i", f"{c}:size=320x240:rate=30:duration=3"]
    video._ffmpeg([*cmd, "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]", "-map", "[v]", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)], tmp_path)
    return out


def _frame_color(path, t, tmp_path):
    """Màu trội của khung hình tại giây t: trả về 'r' / 'g' / 'b'."""
    png = tmp_path / f"f{t}.png"
    video._ffmpeg(["-ss", str(t), "-i", str(path), "-frames:v", "1", str(png)], tmp_path)
    from PIL import Image
    r, g, b = Image.open(png).convert("RGB").resize((1, 1)).getpixel((0, 0))
    return max((r, "r"), (g, "g"), (b, "b"))[1]


@pytest.mark.parametrize("audio", ["none", "low"])
def test_lines_stay_in_sync_with_scenes_of_the_clip(three_scene_clip, tmp_path, audio):
    """Mỗi đoạn lời đọc phải rơi đúng cảnh: cảnh 1 đỏ, cảnh 2 xanh lá, cảnh 3 xanh dương — và không đọc dòng "Cảnh N"."""
    spoken, hows = [], []
    real, real_sb = video.tts, voiceover.scene_bounds
    video.tts = lambda text, *a, **k: spoken.append(text) or real(text, *a, **k)
    voiceover.scene_bounds = lambda *a: hows.append(real_sb(*a)) or hows[-1]
    try:
        script = ("Tiêu đề kịch bản lời đọc\nCảnh 1 — Đỏ\nMột hai ba.\nCảnh 2 — Lục\nBốn năm sáu bảy tám.\nCảnh 3 — Lam\nChín mười.")
        vid = _make(three_scene_clip, tmp_path, fit="keep", audio=audio, caption_pos="bottom", script=script)
        video.start_render(vid)
    finally:
        video.tts, voiceover.scene_bounds = real, real_sb
    v = db.video_get(vid)
    assert v["status"] == "done", v["error"]
    assert hows[0][1] == "detect" and abs(hows[0][0][1] - 3) < 0.4 and abs(hows[0][0][2] - 6) < 0.4        # tự dò đúng chỗ chuyển cảnh
    assert spoken == ["Một hai ba.", "Bốn năm sáu bảy tám.", "Chín mười."]            # không đọc tiêu đề / "Cảnh N"
    assert 8.5 < v["duration"] < 10.5
    assert [_frame_color(v["path"], t, tmp_path) for t in (1.0, 4.5, 8.0)] == ["r", "g", "b"]


def test_scene_sync_with_explicit_times_and_long_narration(three_scene_clip, tmp_path):
    """Ghi thời điểm [mm:ss]; cảnh 1 có lời đọc dài hơn cảnh gốc (~4,2s > 3s) → cảnh 1 kéo dài, cảnh 2 vẫn bắt đầu bằng hình xanh lá."""
    script = ("Cảnh 1 [00:00] — A\n" + "chữ " * 14 + "\nCảnh 2 [00:03] — B\nHai.\nCảnh 3 [00:06] — C\nBa.")
    vid = _make(three_scene_clip, tmp_path, fit="keep", caption_pos="none", script=script)
    video.start_render(vid)
    v = db.video_get(vid)
    assert v["status"] == "done", v["error"]
    assert v["duration"] > 9.8                                                       # cảnh 1 đã dài ra so với 3s
    assert _frame_color(v["path"], 1.0, tmp_path) == "r"
    start2 = 0.3 * 14 + voiceover.SCENE_GAP                                           # lời đọc cảnh 1 xong → cảnh 2 bắt đầu
    assert _frame_color(v["path"], start2 + 0.4, tmp_path) == "g"
    assert _frame_color(v["path"], v["duration"] - 0.3, tmp_path) == "b"


def test_scene_bounds_fallback_and_detect(three_scene_clip, tmp_path):
    scenes = [{"time": None}] * 3
    b, how = voiceover.scene_bounds(three_scene_clip, 9.0, scenes, [3, 3, 3])
    assert how == "detect" and abs(b[1] - 3) < 0.4 and abs(b[2] - 6) < 0.4
    b, how = voiceover.scene_bounds(three_scene_clip, 9.0, [{"time": None}] * 4, [3, 3, 3, 3])      # cần 3 mốc nhưng chỉ có 2 → chia theo lời đọc
    assert how == "prop" and [round(x, 1) for x in b] == [0.0, 2.2, 4.5, 6.8, 9.0]


def test_caption_position_option(src_clip, tmp_path, monkeypatch):
    ys = {}
    for pos in ("bottom", "top"):
        seen = []
        real = voiceover._burn_captions
        monkeypatch.setattr(voiceover, "_burn_captions", lambda work, base, audio, caps, total, out, step, _r=real, _s=seen: _s.extend(caps) or _r(work, base, audio, caps, total, out, step))
        vid = _make(src_clip, tmp_path, caption_pos=pos, script="Một hai ba bốn năm sáu bảy tám.")
        video.start_render(vid)
        assert db.video_get(vid)["status"] == "done"
        ys[pos] = seen
        monkeypatch.setattr(voiceover, "_burn_captions", real)
    assert ys["bottom"] and ys["top"]
    assert min(c[1][1] for c in ys["bottom"]) > max(c[1][1] for c in ys["top"])                  # phụ đề "trên" nằm cao hơn "dưới"
    assert voiceover.clean_options({"captions": False})["caption_pos"] == "none" and voiceover.clean_options({})["caption_pos"] == "bottom"
    vid = _make(src_clip, tmp_path, caption_pos="none", script="Một hai ba.")
    video.start_render(vid)
    assert db.video_get(vid)["status"] == "done"
