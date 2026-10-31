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

    def fake_tts(text, voice, rate, dest, style=""):          # không gọi Internet: tạo tiếng bíp 1 giây
        video._ffmpeg(["-f", "lavfi", "-i", "sine=duration=1", "-c:a", "libmp3lame", str(dest)], dest.parent)
    monkeypatch.setattr(video, "tts", fake_tts)
    monkeypatch.setattr(video, "missing_tools", lambda: [])
    monkeypatch.setattr(video, "_run_bg", lambda fn, *a: fn(*a))     # dựng ngay, không chạy nền

    r = client.post(f"/api/videos/{vid}/render").json()
    assert r["status"] == "done" and r["has_file"] and 2 < r["duration"] < 3
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


def test_tts_cleans_text_and_falls_back_to_google(monkeypatch, tmp_path):
    assert video.clean_tts_text("## Giảm 30% thuế 🎉 **ngay**!") == "Giảm 30% thuế ngay !"
    tried = []

    def edge_fail(text, voice, rate, dest):
        tried.append((voice, rate))
        raise RuntimeError("No audio was received")
    monkeypatch.setattr(video, "_edge", edge_fail)
    monkeypatch.setattr(video, "_gtts", lambda text, dest: dest.write_bytes(b"mp3"))
    monkeypatch.setattr(video.time, "sleep", lambda s: None)
    assert video.tts("Xin chào 👋", "vi-VN-HoaiMyNeural", 5, tmp_path / "a.mp3") == "Google"
    assert tried == [("vi-VN-HoaiMyNeural", "+5%"), ("vi-VN-HoaiMyNeural", "+0%"), ("vi-VN-NamMinhNeural", "+0%")]

    monkeypatch.setattr(video, "_gtts", lambda text, dest: (_ for _ in ()).throw(RuntimeError("offline")))
    with pytest.raises(video.VideoError, match="Google: offline"):
        video.tts("Xin chào", "vi-VN-HoaiMyNeural", 0, tmp_path / "b.mp3")


def test_long_clip_script_retries_when_too_short(client, monkeypatch):
    video.save_config({"look": "explainer"})
    prompts = []
    short = [{"headline": "Ý", "narration": "Ngắn quá.", "items": ["a"]}] * 8
    long_ = [{"type": "stat", "headline": f"Ý {i}", "narration": "Lời đọc khá dài " * 7, "big": "30%",
              "items": "Ý một\nÝ hai\n\n• Ý ba"} for i in range(20)]
    replies = iter([{"scenes": short}, {"scenes": long_}])
    monkeypatch.setattr(newsagent, "gemini_json", lambda p, cfg: prompts.append(p) or next(replies))
    v = client.post("/api/videos", json={"text": "Nội dung bài viết về thuế. " * 10, "seconds": 180}).json()
    assert len(v["scenes"]) == 20 and v["scenes"][0]["items"] == ["Ý một", "Ý hai", "Ý ba"]
    assert "20 cảnh" in prompts[0] and "540 từ" in prompts[0] and "QUÁ NGẮN" in prompts[1]
    assert 150 < video.estimate_seconds(v["scenes"]) < 200


def test_caption_chunks_are_short():
    chunks = video.caption_chunks("Từ ngày 1 tháng 7, doanh nghiệp nhỏ được giảm 30% thuế thu nhập doanh nghiệp "
                                  "trong hai năm liên tiếp 2026 và 2027. Đặc biệt!")
    assert all(len(c.split()) <= 10 for c in chunks) and " ".join(chunks).endswith("Đặc biệt!")



@pytest.mark.skipif(not (HAS_TOOLS and importlib.util.find_spec("piper")), reason="cần piper-tts")
def test_piper_voice_makes_mp3_and_falls_back(monkeypatch, tmp_path):
    seen = {}

    class FakeVoice:
        def synthesize_wav(self, text, f, syn_config=None):
            seen["scale"] = syn_config.length_scale
            f.setnchannels(1); f.setsampwidth(2); f.setframerate(22050)
            f.writeframes(b"\x00\x00" * 22050)
    monkeypatch.setattr(video, "_piper_voice", lambda name: seen.setdefault("name", name) and FakeVoice())
    dest = tmp_path / "v.mp3"
    assert video.tts("Xin chào", "piper:vi_VN-vais1000-medium", 25, dest) == "VAIS1000 (nữ)"
    assert seen["name"] == "vi_VN-vais1000-medium" and abs(seen["scale"] - 0.8) < 1e-6
    assert 0.9 < video.media_duration(dest) < 1.2 and not dest.with_suffix(".wav").exists()

    def broken(name):
        raise video.VideoError("Chưa tải được giọng")
    monkeypatch.setattr(video, "_piper_voice", broken)
    monkeypatch.setattr(video, "_edge", lambda text, voice, rate, d: d.write_bytes(b"mp3"))
    monkeypatch.setattr(video.time, "sleep", lambda s: None)
    assert video.tts("Xin chào", "piper:vi_VN-vais1000-medium", 0, dest) == "Hoài My (nữ)"


def test_voice_test_endpoint(client, monkeypatch):
    monkeypatch.setattr(video, "missing_tools", lambda: [])
    monkeypatch.setattr(video, "tts", lambda text, voice, rate, dest, style="": (dest.write_bytes(b"ID3"), "Hoài My (nữ)")[1])
    r = client.post("/api/video/voice-test", json={"voice": "vi-VN-HoaiMyNeural"})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/mpeg" and r.content == b"ID3"
    assert client.post("/api/video/voice-test", json={"voice": "xx"}).status_code == 400
    monkeypatch.setattr(video, "tts", lambda text, voice, rate, dest, style="": (dest.write_bytes(b"x"), "Google")[1])
    r = client.post("/api/video/voice-test", json={"voice": "vi-VN-NamMinhNeural"})
    assert r.status_code == 400 and "Google" in r.json()["detail"]


def test_pexels_video_picks_smallest_sharp_file_and_skips_used(monkeypatch, tmp_path):
    vids = [{"id": 1, "duration": 10, "video_files": [{"file_type": "video/mp4", "width": 1080, "height": 1920, "link": "u1"}]},
            {"id": 2, "duration": 10, "video_files": [
                {"file_type": "video/mp4", "width": 2160, "height": 3840, "link": "big"},
                {"file_type": "video/mp4", "width": 720, "height": 1280, "link": "small"},
                {"file_type": "video/mp4", "width": 360, "height": 640, "link": "blurry"}]}]
    monkeypatch.setattr(video, "_pexels", lambda path, key, params: [dict(v) for v in vids])
    got = []
    monkeypatch.setattr(video, "_download", lambda url, dest, kind="image": got.append((url, kind)) or True)
    assert video.pexels_video("tax", "", (1080, 1920), tmp_path / "a.mp4", set()) is False     # chưa có key
    assert video.pexels_video("tax", "k", (1080, 1920), tmp_path / "a.mp4", {1}) is True
    assert got == [("small", "video")]


def test_gemini_voice_trims_and_falls_back_to_microsoft(monkeypatch, tmp_path):
    from app import aimedia
    newsagent.save_config({"gemini_key": "k"})
    seen = {}

    def fake_pcm(text, voice, style, key):
        seen.update(voice=voice, style=style, key=key, text=text)
        return b"\x00\x00" * 24000, 24000                   # 1 giây im lặng
    monkeypatch.setattr(aimedia, "tts_pcm", fake_pcm)
    dest = tmp_path / "g.mp3"
    if HAS_TOOLS:
        try:
            video._gemini_voice("Xin chào", "Leda", "Đọc vui vẻ", 8, dest)
        except video.VideoError:
            pytest.fail("ffmpeg không xử lý được âm thanh Gemini")
        assert dest.exists() and not dest.with_suffix(".wav").exists()
    assert seen["voice"] == "Leda" and seen["style"] == "Đọc vui vẻ" and seen["key"] == "k"

    def boom(*a):
        raise aimedia.AIError("quota (HTTP 429)")
    monkeypatch.setattr(aimedia, "tts_pcm", boom)
    monkeypatch.setattr(video, "_edge", lambda text, voice, rate, d: d.write_bytes(b"mp3"))
    monkeypatch.setattr(video.time, "sleep", lambda s: None)
    assert video.tts("Xin chào", "gemini:Leda", 8, tmp_path / "h.mp3", "style") == "Hoài My (nữ)"


def test_aimedia_parses_tts_image_and_retries(monkeypatch):
    import base64 as b64
    from app import aimedia
    monkeypatch.setattr(aimedia.time, "sleep", lambda s: None)
    calls = []

    class R:
        def __init__(self, status, body): self.status_code, self._b, self.text = status, body, str(body)
        def json(self): return self._b
    pcm = b64.b64encode(b"\x01\x00" * 10).decode()
    replies = iter([R(429, {"error": {"message": "Please retry in 2.5s"}}),
                    R(404, {"error": {"message": "model not found"}}),
                    R(200, {"candidates": [{"content": {"parts": [{"inlineData": {
                        "mimeType": "audio/L16;codec=pcm;rate=24000", "data": pcm}}]}}]})])
    monkeypatch.setattr(aimedia.requests, "post", lambda url, **kw: calls.append((url, kw["json"])) or next(replies))
    data, hz = aimedia.tts_pcm("Xin chào", "Leda", "Vui", "key")
    assert data == b"\x01\x00" * 10 and hz == 24000
    assert len(calls) == 3 and "preview-tts" in calls[0][0] and "flash-tts" in calls[2][0]        # 429 thử lại, 404 đổi model
    assert calls[0][1]["generationConfig"]["speechConfig"]["voiceConfig"]["prebuiltVoiceConfig"]["voiceName"] == "Leda"
    assert calls[0][1]["contents"][0]["parts"][0]["text"] == "Vui:\nXin chào"

    png = b64.b64encode(b"\x89PNGdata").decode()
    monkeypatch.setattr(aimedia.requests, "post", lambda url, **kw: R(200, {"candidates": [{"content": {"parts": [
        {"text": "ok"}, {"inlineData": {"mimeType": "image/png", "data": png}}]}}]}))
    assert aimedia.image("a shop", "9:16", "key") == b"\x89PNGdata"


def test_render_uses_ai_image_and_veo_with_fallbacks(client, monkeypatch, tmp_path):
    from app import aimedia
    newsagent.save_config({"gemini_key": "k"})
    video.save_config({"visual": "ai", "veo_scenes": 2, "voice": "vi-VN-HoaiMyNeural", "look": "classic"})
    sc = [{"type": "text", "headline": f"H{i}", "narration": "Lời đọc.", "visual": f"scene {i}"} for i in range(3)]
    vid = db.video_add("T", "", sc)
    monkeypatch.setattr(video, "tts", lambda text, voice, rate, dest, style="": (video._ffmpeg(
        ["-f", "lavfi", "-i", "sine=duration=1", "-c:a", "libmp3lame", str(dest)], dest.parent), "Hoài My (nữ)")[1])
    veo_calls, img_calls, rendered = [], [], []

    def fake_veo(prompt, aspect, key, dest, wait=0):
        veo_calls.append(prompt)
        if len(veo_calls) == 2:
            raise aimedia.AIError("Veo quá lâu")
        video._ffmpeg(["-f", "lavfi", "-i", "testsrc2=size=320x240:rate=25:duration=1", "-c:v", "libx264",
                       "-pix_fmt", "yuv420p", str(dest)], dest.parent)
    monkeypatch.setattr(aimedia, "veo", fake_veo)
    monkeypatch.setattr(aimedia, "image", lambda prompt, aspect, key: img_calls.append((prompt, aspect)) or (_ for _ in ()).throw(aimedia.AIError("blocked")))
    video.render(vid)
    v = db.video_get(vid)
    assert v["status"] == "done"
    assert len(veo_calls) == 2 and veo_calls[0].startswith("scene 0") and veo_calls[1].startswith("scene 2")   # cảnh đầu + cuối
    assert len(img_calls) == 2 and img_calls[0][0].startswith("scene 1") and img_calls[0][1] == "9:16"          # chỉ cảnh còn lại
    assert any("Veo lỗi" in l for l in video.state["log"]) and any("ảnh AI lỗi" in l for l in video.state["log"])


def test_explainer_heading_split_key_word_and_layers(tmp_path):
    from app import explainer
    assert explainer.split_heading("GIẢM 30% THUẾ|CHO HỘ KINH DOANH") == ["GIẢM 30% THUẾ", "CHO HỘ KINH DOANH"]
    assert explainer.split_heading("Bốn bước hưởng ưu đãi") == ["Bốn bước", "hưởng ưu đãi"]
    assert explainer._key_word("Từ ngày 1 tháng 7".split()) == "1"
    L = video.Layout((1080, 1920))
    sc = video.clean_scenes([{"type": "flow", "headline": "A B|C D", "narration": "Kiểm tra điều kiện doanh thu.",
                              "items": ["Gốc", "Nhánh một | mô tả", "Nhánh hai | mô tả hai"]}])[0]
    layers, caps = explainer.build(L, sc, 0, 1, tmp_path, "Brand", 3.0, 2.5)
    names = [n for n, *_ in layers]
    assert "xh0.png" in names and any(n.startswith("xl0_") for n in names) and caps
    assert all((tmp_path / n).exists() for n in names) and caps[-1][3] == 3.0
    for typ in ("stat", "steps", "list"):
        sc2 = dict(sc, type=typ, big="30%" if typ == "stat" else "")
        assert explainer.build(L, sc2, 1, 1, tmp_path, "", 3.0, 2.5)[0]


def test_explainer_is_default_and_classic_still_renders(client, monkeypatch):
    assert video.get_config()["look"] == "doodle"
    assert video.save_config({"look": "xx"})["look"] == "doodle"
    assert video.save_config({"look": "classic"})["look"] == "classic"


def test_doodle_script_prompt_and_panels(client, monkeypatch):
    prompts = []
    page = {"type": "doodle", "tag": "ví dụ thực tế", "headline": "Chị Lan bán quần áo", "hl": "một trăm triệu, 30%",
            "narration": "Ví dụ chị Lan nộp thuế hai trăm triệu, được giảm ba mươi phần trăm. " * 4,
            "panels": [{"label": "Doanh thu 8 tỷ", "visual": "A cute shop owner"}, "Giảm 30%", {"foo": 1}, {"label": "Còn 140 triệu"}]}
    monkeypatch.setattr(newsagent, "gemini_json", lambda p, cfg: prompts.append(p) or {"scenes": [page] * 8})
    v = client.post("/api/videos", json={"text": "Nội dung bài viết về thuế. " * 10, "seconds": 120}).json()
    assert len(v["scenes"]) == 8 and "8 TRANG" in prompts[0] and "VÍ DỤ CỤ THỂ" in prompts[0]
    sc = v["scenes"][0]
    assert sc["type"] == "doodle" and sc["hl"] == ["một trăm triệu", "30%"]
    assert [p["label"] for p in sc["panels"]] == ["Doanh thu 8 tỷ", "Giảm 30%", "Còn 140 triệu"] and sc["items"] == [p["label"] for p in sc["panels"]]


def test_doodle_layout_highlight_and_render(client, monkeypatch, tmp_path):
    from app import aimedia, doodle
    for n in (1, 2, 3, 4):
        boxes = doodle.layout((720, 1280), n)
        assert len(boxes) == n and all(0 <= x and x + w <= 720 and 0 <= y and y + h <= 1280 for x, y, w, h in boxes)
    w = "Được giảm ba mươi phần trăm, chị chỉ còn nộp một trăm bốn mươi triệu".split()
    hit = [x for x, f in zip(w, doodle.highlight_flags(w, ["ba mươi phần trăm", "140"])) if f]
    assert hit == ["ba", "mươi", "phần", "trăm,"]
    if not HAS_TOOLS:
        return
    video.save_config({"look": "doodle", "voice": "vi-VN-HoaiMyNeural"})
    newsagent.save_config({"gemini_key": "k"})
    scenes = [{"type": "doodle", "tag": "VÍ DỤ", "headline": "Chị Lan", "narration": "Chị Lan nộp thuế hai trăm triệu.",
               "panels": [{"label": "A", "visual": "a"}, {"label": "B", "visual": "b"}], "hl": ["hai trăm triệu"]}]
    vid = db.video_add("T", "", video.clean_scenes(scenes))
    monkeypatch.setattr(video, "tts", lambda text, voice, rate, dest, style="": (video._ffmpeg(
        ["-f", "lavfi", "-i", "sine=duration=2", "-c:a", "libmp3lame", str(dest)], dest.parent), "x")[1])
    calls = []

    def fake_image(prompt, aspect, key):
        calls.append(prompt)
        if len(calls) == 2:
            raise aimedia.AIError("blocked")
        import io
        from PIL import Image
        b = io.BytesIO()
        Image.new("RGB", (64, 64), "white").save(b, "PNG")
        return b.getvalue()
    monkeypatch.setattr(aimedia, "image", fake_image)
    video.render(vid)
    v = db.video_get(vid)
    assert v["status"] == "done" and 2 < v["duration"] < 4 and len(calls) == 2
    assert calls[0].startswith(doodle.IMG_STYLE) and any("vẽ AI lỗi" in l for l in video.state["log"])


def test_vieneu_voice_chain(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(video, "_vieneu", lambda text, voice, rate, dest: seen.append(voice) or (_ for _ in ()).throw(RuntimeError("chưa tải mô hình")))
    monkeypatch.setattr(video, "_edge", lambda text, voice, rate, d: d.write_bytes(b"mp3"))
    monkeypatch.setattr(video.time, "sleep", lambda s: None)
    assert video.tts("Xin chào", "vieneu:Mai Anh", 8, tmp_path / "v.mp3") == "Hoài My (nữ)"
    assert seen == ["Mai Anh", "Mai Anh"]
    assert video.get_config()["voice"] == "vieneu:Mai Anh" and "vieneu:Mai Anh" in video.VOICES


def test_doodle_ai_circuit_breaker_and_icon_fallback(tmp_path):
    from app import aimedia, doodle
    calls = []

    def hard_fail(prompt, aspect, key):
        calls.append(prompt)
        raise aimedia.AIError("Quota exceeded, limit: 0 (HTTP 429)")
    orig = aimedia.image
    aimedia.image = hard_fail
    try:
        st, logs = doodle.AIState(), []
        sc = video.clean_scenes([{"type": "doodle", "headline": "H", "narration": "Lời đọc dài.",
                                  "panels": [{"label": f"Hình {k}", "visual": "v"} for k in range(4)]}])[0]
        for page in range(3):
            panels = doodle.make_panels(sc, (720, 1280), tmp_path, page, "key", logs.append, True, st)
            assert len(panels) == 4 and all((tmp_path / n).exists() for n, *_ in panels)
        assert st.off and "limit: 0" in st.reason and len(calls) <= 3      # dừng thử sau lỗi cứng, không gọi 12 lần
        assert sum("không vẽ được hình" in l for l in logs) >= 1
    finally:
        aimedia.image = orig


def test_icons_pick_by_keyword_and_imagen_fallback(monkeypatch):
    from app import aimedia, doodle_icons
    assert doodle_icons.pick("Giảm 30% thuế", "", 0)[0] == "percent"
    assert doodle_icons.pick("Hồ sơ kê khai", "invoice", 1)[0] == "document"
    assert len(set(doodle_icons.pick("Tư vấn miễn phí", "", 3, 3))) == 3
    assert doodle_icons.draw_scene(120, "x", "y", 1).size == (120, 120)
    import base64 as b64
    seq = []

    def fake_post(path, key, body, **kw):
        seq.append(path)
        if ":predict" in path:
            return {"predictions": [{"bytesBase64Encoded": b64.b64encode(b"IMG").decode()}]}
        raise aimedia.AIError("no access (HTTP 403)")
    monkeypatch.setattr(aimedia, "_post", fake_post)
    assert aimedia.image("p", "1:1", "k") == b"IMG" and any("imagen" in p for p in seq)
