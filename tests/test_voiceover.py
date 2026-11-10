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
    assert v["kind"] == "voiceover" and v["status"] == "done" and v["has_file"] and v["options"] == {"fit": "keep", "audio": "low", "captions": False}
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
