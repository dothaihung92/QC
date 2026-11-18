import importlib.util

import pytest
from fastapi.testclient import TestClient

from app import db, newsagent, newslook, server, video

HAS_TOOLS = all(importlib.util.find_spec(m) for m in ("PIL", "imageio_ffmpeg")) and not video.missing_tools()

ARTICLE = ("10 tháng đầu năm 2026, cơ quan thuế từ chối hoàn hơn 10.000 tỷ đồng vì hồ sơ thiếu. Bộ trưởng Tài chính cho biết "
           "doanh nghiệp cần rà soát hóa đơn đầu vào trước khi xin hoàn. Thời gian giải quyết giảm từ 50 ngày xuống 40 ngày. ") * 2
AI = {"title": "Hoàn thuế bị từ chối", "headline": "10 tháng đầu năm 2026, cơ quan thuế từ chối hoàn hơn 10.000 tỷ đồng vì hồ sơ thiếu: doanh nghiệp nên rà soát hóa đơn trước khi xin hoàn",
      "hashtags": ["#HoanThue", "hoadondauvao"],
      "scenes": [{"narration": "10 tháng đầu năm nay, cơ quan thuế đã từ chối hoàn hơn 10.000 tỷ đồng tiền thuế.", "keyword": "tax office", "hl": ["từ chối hoàn", "10.000 tỷ đồng"]},
                 {"narration": "Nhiều hồ sơ bị trả vì thiếu hóa đơn đầu vào hợp lệ.", "keyword": "invoice", "hl": ["hóa đơn đầu vào"]},
                 {"narration": "Hồ sơ đầy đủ thì giải quyết từ 50 ngày xuống khoảng 40 ngày.", "keyword": "calendar", "hl": ["50 ngày", "40 ngày"]},
                 {"narration": ""}, "rác"]}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(video, "VIDEO_DIR", tmp_path / "videos")
    monkeypatch.setattr(video, "MUSIC_DIR", tmp_path / "music")
    return TestClient(server.app)


def test_bold_unicode_and_caption_layout_like_the_sample_post():
    assert newslook.bold_unicode("ĐẠI LÝ Thuế 24") == "𝗗𝗔𝗜 𝗟𝗬 𝗧𝗵𝘂𝗲 𝟮𝟰"
    cfg = {**video.DEFAULTS, "sig_address": "", "sig_tags": "#DaiLyThueHungPhuc #hoanthue"}
    cap = newslook.compose_caption("Tiêu đề tin.", ["#HoanThue", "HoaDon"], cfg)
    lines = cap.split("\n")
    assert lines[0] == "Tiêu đề tin." and lines[1] == "" and lines[2] == "______________________"       # câu tiêu đề → đường kẻ → chữ ký
    assert lines[3] == "𝗗𝗔𝗜 𝗟𝗬 𝗧𝗛𝗨𝗘 𝗛𝗨𝗡𝗚 𝗣𝗛𝗨𝗖" and "📞 Hotline: 0986883137" in lines and not any("📍" in l for l in lines)
    assert lines[-1] == "#HoanThue #HoaDon #DaiLyThueHungPhuc"                                          # hashtag AI + cố định, không trùng (HoanThue/hoanthue)
    cfg2 = {**cfg, "sig_bold": False, "sig_address": "Hà Nội"}
    assert "ĐẠI LÝ THUẾ HƯNG PHÚC" in newslook.compose_caption("X", [], cfg2) and "📍 Hà Nội" in newslook.compose_caption("X", [], cfg2)
    assert newslook.compose_caption("Chỉ tiêu đề", [], {"sig_tags": ""}) == "Chỉ tiêu đề"


def test_color_words_and_chunks_keep_key_phrases_together():
    words = "đã từ chối hoàn hơn 10.000 tỷ đồng tiền thuế".split()
    cols = newslook.color_words(words, ["từ chối hoàn"])
    assert [cols[i] for i in (1, 2, 3)] == [newslook.ORANGE] * 3 and cols[5] == cols[6] == cols[7] == newslook.YELLOW
    assert cols[0] == cols[8] == (255, 255, 255)
    for text, hl in (("10 tháng đầu năm nay, cơ quan thuế đã từ chối hoàn hơn 10.000 tỷ đồng tiền thuế.", ["từ chối hoàn", "10.000 tỷ đồng"]),
                     ("Hồ sơ đầy đủ, thời gian giải quyết giảm từ 50 ngày xuống khoảng 40 ngày.", ["50 ngày", "40 ngày"])):
        chunks = newslook.news_chunks(text, hl)
        joined = " | ".join(chunks)
        assert all(ph in joined for ph in hl) and " ".join(chunks).split() == " ".join(text.split()).split()     # không cắt đôi cụm, không mất chữ


def test_news_script_keeps_key_points_and_builds_facebook_caption(client, monkeypatch):
    seen = []
    monkeypatch.setattr(newsagent, "gemini_json", lambda p, cfg: seen.append(p) or AI)
    v = client.post("/api/videos", json={"text": ARTICLE, "seconds": 30, "look": "news"}).json()
    assert v["options"] == {"look": "news", "images": [], "article_url": ""} and len(v["scenes"]) == 3 and all(s["type"] == "news" for s in v["scenes"])
    assert v["scenes"][0]["hl"] == ["từ chối hoàn", "10.000 tỷ đồng"] and v["scenes"][0]["keyword"] == "tax office"
    assert "CHỈ GHI NHỮNG NỘI DUNG QUAN TRỌNG" in seen[0] and "TRUNG THỰC" in seen[0] and "đúng 7 cảnh" in seen[0] and "không dùng dấu /" in seen[0]
    d = v["description"]
    assert d.startswith("10 tháng đầu năm 2026") and "\n______________________\n" in d and "📞 Hotline: 0986883137" in d and d.rstrip().endswith("#HoanThue #hoadondauvao #DaiLyThueHungPhuc")
    assert video.get_config()["look"] == video.DEFAULTS["look"]                       # chỉ clip này dùng kiểu Tin nhanh, cài đặt chung không đổi
    v2 = client.post("/api/videos", json={"text": ARTICLE, "seconds": 30}).json()     # không chọn → kiểu mặc định
    assert v2["options"] == {}


def test_signature_settings_are_saved(client):
    c = client.put("/api/video/config", json={"sig_name": "CÔNG TY A", "sig_phone": "0900000000", "sig_bold": False, "cta_text": "Gọi ngay", "logo_text": "A"}).json()
    assert c["sig_name"] == "CÔNG TY A" and c["sig_bold"] is False and c["cta_text"] == "Gọi ngay"
    assert video.get_config()["sig_phone"] == "0900000000" and video.DEFAULTS["sig_phone"] == "0986883137"


def _fake_tts(monkeypatch):
    def tts(text, voice, rate, dest, style=""):
        n = max(1, len(text.split())) * 0.25
        video._ffmpeg(["-f", "lavfi", "-i", f"sine=frequency=440:duration={n:.2f}", "-c:a", "libmp3lame", str(dest)], dest.parent)
        return video.VOICES.get(voice, "x").split(" — ")[0]
    monkeypatch.setattr(video, "tts", tts)
    monkeypatch.setattr(video, "_run_bg", lambda fn, *a: fn(*a))
    monkeypatch.setattr(video, "missing_tools", lambda: [])


def _frame(path, t, tmp_path):
    from PIL import Image
    png = tmp_path / f"f{int(t * 10)}.png"
    video._ffmpeg(["-ss", f"{t:.2f}", "-i", str(path), "-frames:v", "1", str(png)], tmp_path)
    return Image.open(png).convert("RGB")


@pytest.mark.skipif(not HAS_TOOLS, reason="cần pillow + imageio-ffmpeg")
def test_news_clip_renders_photo_top_blue_text_bottom_and_contact_card(client, monkeypatch, tmp_path):
    from PIL import Image
    _fake_tts(monkeypatch)
    monkeypatch.setattr(newsagent, "gemini_json", lambda p, cfg: AI)
    video.save_config({"pexels_key": "k"})
    colors = iter([(200, 40, 40), (40, 160, 60), (230, 200, 40), (120, 40, 200)])

    def pex(kw, key, vertical, dest):
        Image.new("RGB", (900, 1400), next(colors)).save(dest, "JPEG")
        return True
    monkeypatch.setattr(video, "pexels_photo", pex)
    v = client.post("/api/videos", json={"text": ARTICLE, "seconds": 30, "look": "news"}).json()
    r = client.post(f"/api/videos/{v['id']}/render").json()
    d = db.video_get(v["id"])
    assert d["status"] == "done", d["error"]
    assert d["error"] == "" and d["duration"] > 12                                        # 3 cảnh + cảnh liên hệ cuối
    img = _frame(d["path"], 0.8, tmp_path)
    assert img.size == (720, 1280)
    top, bottom = img.getpixel((360, 300)), img.getpixel((60, 1200))
    assert top[0] > 150 and top[2] < 90                                                   # nửa trên: ảnh minh họa (đỏ)
    assert bottom[2] > 150 and bottom[0] < 80                                             # nửa dưới: nền xanh dương
    assert all(abs(a - b) < 6 for a, b in zip(img.getpixel((4, 600)), newslook.STRIP))                                      # dải cam bên trái
    last = _frame(d["path"], d["duration"] - 0.4, tmp_path)
    assert sum(last.getpixel((360, 1000))) > 600 or sum(last.getpixel((30, 30))) > 600       # cảnh cuối nền sáng
    last.save(tmp_path / "last.png")
    blue = [(x, y) for y in range(200, 700, 6) for x in range(100, 620, 6) if last.getpixel((x, y))[0] < 60 and last.getpixel((x, y))[2] > 200]
    assert len(blue) > 40                                                                      # nút hotline xanh trên thẻ liên hệ


@pytest.mark.skipif(not HAS_TOOLS, reason="cần pillow + imageio-ffmpeg")
def test_news_clip_without_photos_shows_stat_panel_and_explains(client, monkeypatch, tmp_path):
    _fake_tts(monkeypatch)
    monkeypatch.setattr(newsagent, "gemini_json", lambda p, cfg: AI)
    monkeypatch.setattr(video, "pexels_photo", lambda *a: False)
    video.save_config({"cta_text": "", "sig_phone": ""})                                   # không có thẻ liên hệ cuối
    v = client.post("/api/videos", json={"text": ARTICLE, "seconds": 30, "look": "news"}).json()
    client.post(f"/api/videos/{v['id']}/render")
    d = db.video_get(v["id"])
    assert d["status"] == "done" and "Pexels" in d["error"]
    assert 8 < d["duration"] < 14                                                         # chỉ 3 cảnh nội dung


def test_ui_has_news_look_controls():
    html = TestClient(server.app).get("/").text
    assert "vdCreate('news')" in html and 'value="news"' in html and 'id="vdSigName"' in html and "function vdLogoUp" in html


ARTICLE_HTML = """<html><head><meta property="og:image" content="https://cdn.baochi.vn/cover.jpg"></head><body>
<header><img src="/img/logo.png"></header>
<article>
  <img src="https://cdn.baochi.vn/a1-800x600.jpg" width="800" height="600" alt="Họp quốc hội">
  <img data-src="/uploads/a2.jpg" alt="Cơ quan thuế">
  <img src="https://cdn.baochi.vn/a1-400x300.jpg">
  <img src="/uploads/icon-share.png"><img src="x.svg"><img src="data:image/gif;base64,AAA">
  <img srcset="/u/small.jpg 300w, /u/big.jpg 1200w" src="/u/small.jpg">
  <img src="/tiny.jpg" width="40" height="40">
</article>
<aside><img src="https://ads.example.com/ads/banner1.jpg"><img src="/sidebar/other.jpg"></aside></body></html>"""


def test_article_images_picks_content_photos_and_skips_junk(monkeypatch):
    from app import backlinks
    monkeypatch.setattr(backlinks, "fetch_page", lambda url, **k: (200, "https://baochi.vn/bai-1", ARTICLE_HTML))
    imgs = newslook.article_images("https://baochi.vn/bai-1")
    assert imgs[0] == "https://cdn.baochi.vn/cover.jpg"                                          # ảnh đại diện trước
    assert imgs[1:4] == ["https://cdn.baochi.vn/a1-800x600.jpg", "https://baochi.vn/uploads/a2.jpg", "https://baochi.vn/u/big.jpg"]
    assert not any("logo" in u or "icon" in u or "banner" in u or u.endswith(".svg") or "tiny" in u or "a1-400x300" in u for u in imgs)      # bỏ logo, icon, quảng cáo, ảnh nhỏ, bản trùng
    monkeypatch.setattr(backlinks, "fetch_page", lambda url, **k: (404, url, ""))
    assert newslook.article_images("https://baochi.vn/x") == []
    assert newslook.article_images("http://127.0.0.1/x") == []                                     # địa chỉ nội bộ bị chặn


def test_news_clip_stores_article_images_and_allows_editing(client, monkeypatch):
    monkeypatch.setattr(newsagent, "gemini_json", lambda p, cfg: AI)
    monkeypatch.setattr(newslook, "article_images", lambda url, limit=12: ["https://cdn.baochi.vn/1.jpg", "https://cdn.baochi.vn/2.jpg"] if url else [])
    v = client.post("/api/videos", json={"text": ARTICLE, "seconds": 30, "look": "news", "article_url": "https://baochi.vn/bai-1", "image_url": "https://x.vn/cover.jpg"}).json()
    assert v["options"] == {"look": "news", "images": ["https://x.vn/cover.jpg", "https://cdn.baochi.vn/1.jpg", "https://cdn.baochi.vn/2.jpg"], "article_url": "https://baochi.vn/bai-1"}
    e = client.put(f"/api/videos/{v['id']}", json={"images": ["https://a.vn/1.jpg", "", "ftp://bad", "https://a.vn/2.jpg"]}).json()
    assert e["options"]["images"] == ["https://a.vn/1.jpg", "https://a.vn/2.jpg"] and e["options"]["look"] == "news" and e["options"]["article_url"] == "https://baochi.vn/bai-1"


@pytest.mark.skipif(not HAS_TOOLS, reason="cần pillow + imageio-ffmpeg")
def test_news_clip_uses_article_photos_first_then_pexels(client, monkeypatch, tmp_path):
    from PIL import Image
    _fake_tts(monkeypatch)
    monkeypatch.setattr(newsagent, "gemini_json", lambda p, cfg: AI)
    monkeypatch.setattr(newslook, "article_images", lambda url, limit=12: ["https://cdn.baochi.vn/1.jpg", "https://cdn.baochi.vn/bad.jpg"])
    video.save_config({"pexels_key": "k"})
    fetched, pex_calls = [], []

    def fetch(url, referer, dest):
        fetched.append((url, referer))
        if "bad" in url:
            return False                                                                      # ảnh hỏng/nhỏ bị bỏ
        Image.new("RGB", (900, 1400), (200, 40, 40)).save(dest, "JPEG")
        return True
    monkeypatch.setattr(newslook, "_fetch_image", fetch)

    def pex(kw, key, vertical, dest):
        pex_calls.append(kw)
        Image.new("RGB", (900, 1400), (40, 160, 60)).save(dest, "JPEG")
        return True
    monkeypatch.setattr(video, "pexels_photo", pex)
    v = client.post("/api/videos", json={"text": ARTICLE, "seconds": 30, "look": "news", "article_url": "https://baochi.vn/bai-1"}).json()
    client.post(f"/api/videos/{v['id']}/render")
    d = db.video_get(v["id"])
    assert d["status"] == "done", d["error"]
    assert fetched[0] == ("https://cdn.baochi.vn/1.jpg", "https://baochi.vn/bai-1")           # tải kèm Referer của bài
    a, b = _frame(d["path"], 0.8, tmp_path), _frame(d["path"], 5.0, tmp_path)
    assert a.getpixel((360, 300))[0] > 150 and a.getpixel((360, 300))[1] < 90                  # cảnh 1: ảnh trong bài (đỏ)
    assert pex_calls and b.getpixel((360, 300))[1] > 120 and b.getpixel((360, 300))[0] < 90    # hết ảnh trong bài → Pexels (xanh lá)


@pytest.mark.skipif(not HAS_TOOLS, reason="cần pillow + imageio-ffmpeg")
def test_news_clip_cycles_article_photos_without_pexels_and_credits_source(client, monkeypatch, tmp_path):
    from PIL import Image
    _fake_tts(monkeypatch)
    monkeypatch.setattr(newsagent, "gemini_json", lambda p, cfg: AI)
    monkeypatch.setattr(newslook, "article_images", lambda url, limit=12: ["https://cdn.baochi.vn/1.jpg"])
    monkeypatch.setattr(newslook, "_fetch_image", lambda url, ref, dest: Image.new("RGB", (900, 1400), (200, 40, 40)).save(dest, "JPEG") or True)
    seen_labels = []
    real = newslook.scene_background
    monkeypatch.setattr(newslook, "scene_background", lambda cfg, photo, stat, dest, label="": seen_labels.append(label) or real(cfg, photo, stat, dest, label))
    v = client.post("/api/videos", json={"text": ARTICLE, "seconds": 30, "look": "news", "article_url": "https://www.baochi.vn/bai-1"}).json()
    client.post(f"/api/videos/{v['id']}/render")
    d = db.video_get(v["id"])
    assert d["status"] == "done" and d["error"] == ""                                       # có ảnh trong bài → không cần Pexels, không báo thiếu
    assert seen_labels == ["ẢNH: BAOCHI.VN"] * 3                                            # ghi nguồn ảnh; 1 ảnh được dùng lại cho cả 3 cảnh
