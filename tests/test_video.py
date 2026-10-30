import importlib.util

import pytest
from fastapi.testclient import TestClient

from app import db, facebook, newsagent, server, video

HAS_TOOLS = all(importlib.util.find_spec(m) for m in ("PIL", "imageio_ffmpeg"))

SCRIPT = {"title": "Thuế GTGT giảm 2%", "description": "Mô tả #thue",
          "scenes": [{"headline": "Giảm thuế GTGT", "narration": "Từ 1/7 giảm 2% thuế GTGT.", "keyword": "tax"},
                     {"headline": "Cần làm gì", "narration": "Cập nhật thuế suất trên hóa đơn.", "keyword": ""},
                     {"narration": ""}, "rác"]}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(video, "VIDEO_DIR", tmp_path / "videos")
    monkeypatch.setattr(video, "MUSIC_DIR", tmp_path / "music")
    return TestClient(server.app)


def test_script_needs_content_and_cleans_ai_output(client, monkeypatch):
    monkeypatch.setattr(newsagent, "gemini_json", lambda p, cfg: SCRIPT)
    assert client.post("/api/videos", json={"text": "ngắn"}).status_code == 400
    v = client.post("/api/videos", json={"text": "Nội dung bài viết về thuế. " * 10, "seconds": 30}).json()
    assert v["status"] == "draft" and len(v["scenes"]) == 2 and v["has_file"] is False
    assert "path" not in v


def test_config_masks_pexels_key_and_validates(client):
    c = client.put("/api/video/config", json={"pexels_key": "abc", "color": "đỏ", "rate": 99,
                                              "voice": "xx"}).json()
    assert c["has_pexels_key"] and "pexels_key" not in c
    assert c["color"] == video.DEFAULTS["color"] and c["rate"] == 30 and c["voice"] == video.DEFAULTS["voice"]
    client.put("/api/video/config", json={"pexels_key": ""})
    assert video.get_config()["pexels_key"] == "abc"


@pytest.mark.skipif(not HAS_TOOLS, reason="cần pillow + imageio-ffmpeg")
def test_render_download_publish_delete(client, monkeypatch, tmp_path):
    vid = db.video_add("T", "mô tả", video.clean_scenes(SCRIPT["scenes"]))

    def fake_tts(text, voice, rate, dest):          # không gọi Internet: tạo tiếng bíp 1 giây
        video._ffmpeg(["-f", "lavfi", "-i", "sine=duration=1", "-c:a", "libmp3lame", str(dest)], dest.parent)
    monkeypatch.setattr(video, "tts", fake_tts)
    monkeypatch.setattr(video, "missing_tools", lambda: [])
    monkeypatch.setattr(video, "_run_bg", lambda fn, *a: fn(*a))     # dựng ngay, không chạy nền

    r = client.post(f"/api/videos/{vid}/render").json()
    assert r["status"] == "done" and r["has_file"] and 3 < r["duration"] < 4
    f = client.get(f"/api/videos/{vid}/file?download=1")
    assert f.status_code == 200 and f.headers["content-type"] == "video/mp4" and len(f.content) > 1000
    assert sorted(p.name for p in (tmp_path / "videos" / str(vid)).iterdir()) == ["clip.mp4"]

    sent = []
    monkeypatch.setattr(facebook, "publish_video", lambda path, d="", t="": sent.append((path, d, t)) or "v1")
    assert client.post(f"/api/videos/{vid}/publish").json()["fb_video_id"] == "v1"
    assert sent[0][1] == "mô tả"

    assert client.delete(f"/api/videos/{vid}").json() == {"ok": True}
    assert not (tmp_path / "videos" / str(vid)).exists() and db.video_get(vid) is None


def test_stuck_rendering_is_reset_on_startup(client):
    vid = db.video_add("T", "", [{"headline": "", "narration": "x", "keyword": ""}])
    db.video_update(vid, status="rendering")
    db.init()
    v = db.video_get(vid)
    assert v["status"] == "failed" and "tắt" in v["error"]


def test_render_refused_without_tools(client, monkeypatch):
    vid = db.video_add("T", "", [{"headline": "", "narration": "x", "keyword": ""}])
    monkeypatch.setattr(video, "missing_tools", lambda: ["edge-tts"])
    r = client.post(f"/api/videos/{vid}/render")
    assert r.status_code == 409 and "Cài công cụ" in r.json()["detail"]
    assert db.video_get(vid)["status"] == "draft"
