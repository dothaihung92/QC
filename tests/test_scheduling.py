"""Tính năng lấy ý tưởng từ Postiz: khung giờ vàng, bình luận đầu tiên, đăng lặp lại,
tự bình luận khi đạt lượt cảm xúc, nhiều ảnh / ảnh từ máy, chữ ký."""
import base64
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import config, db, facebook, server

PNG = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(facebook, "MEDIA_DIR", tmp_path / "media")
    return TestClient(server.app)


def _ts(day_offset, hh, mm):
    d = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=day_offset)
    return int((d + timedelta(hours=hh, minutes=mm)).timestamp())


def test_next_free_slot_skips_past_and_taken_slots():
    after = _ts(0, 12, 0)
    assert db.next_free_slot(after=after, slots=["07:30", "20:00"]) == _ts(0, 20, 0)
    db.create_post("x", scheduled_at=_ts(0, 20, 0))
    assert db.next_free_slot(after=after, slots=["07:30", "20:00"]) == _ts(1, 7, 30)
    assert db.next_free_slot(slots=[]) is None


def test_queue_posts_fill_slots_in_order(client):
    assert client.put("/api/posting-slots", json={"slots": ["7h30", "25:00"]}).status_code == 400
    r = client.put("/api/posting-slots", json={"slots": ["20:00", "7h30", "07:30"]}).json()
    assert r["slots"] == ["07:30", "20:00"]
    a = client.post("/api/posts", json={"message": "A", "queue": True}).json()
    b = client.post("/api/posts", json={"message": "B", "queue": True}).json()
    assert a["status"] == b["status"] == "scheduled" and b["scheduled_at"] > a["scheduled_at"] > db.now()
    client.put("/api/posting-slots", json={"slots": []})
    assert client.post("/api/posts", json={"message": "C", "queue": True}).status_code == 400


def test_publish_adds_first_comment_and_schedules_repeat(client, monkeypatch):
    calls = []
    monkeypatch.setattr(facebook, "publish_post", lambda m, l="", i="": calls.append(("post", m)) or "P_1")
    monkeypatch.setattr(facebook, "reply_comment", lambda pid, t: calls.append(("comment", pid, t)) or {})
    p = client.post("/api/posts", json={"message": "Bài", "publish_now": True, "first_comment": " 👉 link ",
                                        "repeat_days": 7}).json()
    assert p["status"] == "posted" and p["error"] == ""
    assert calls == [("post", "Bài"), ("comment", "P_1", "👉 link")]
    nxt = [x for x in db.list_posts() if x["status"] == "scheduled"]
    assert len(nxt) == 1 and nxt[0]["repeat_days"] == 7 and nxt[0]["first_comment"] == "👉 link"
    assert abs(nxt[0]["scheduled_at"] - (db.now() + 7 * 86400)) < 5


def test_first_comment_error_keeps_post_posted(client, monkeypatch):
    monkeypatch.setattr(facebook, "publish_post", lambda *a: "P_2")

    def boom(*a):
        raise facebook.FacebookError("(#200) thiếu quyền")
    monkeypatch.setattr(facebook, "reply_comment", boom)
    p = client.post("/api/posts", json={"message": "x", "publish_now": True, "first_comment": "c"}).json()
    assert p["status"] == "posted" and "bình luận đầu tiên lỗi" in p["error"]


def test_auto_plug_comments_once_when_reactions_reached(client, monkeypatch):
    monkeypatch.setattr(config, "DRY_RUN", False)
    pid = db.create_post("x", plug_likes=10, plug_text="Inbox để nhận ưu đãi!")
    db.update_post(pid, status="posted", fb_post_id="P_9", posted_at=db.now())
    likes, sent = {"n": 3}, []
    monkeypatch.setattr(facebook, "post_reactions", lambda post_id: likes["n"])
    monkeypatch.setattr(facebook, "reply_comment", lambda post_id, t: sent.append((post_id, t)) or {})
    server.run_plugs(force=True)
    assert sent == []
    likes["n"] = 12
    server.run_plugs(force=True)
    server.run_plugs(force=True)
    assert sent == [("P_9", "Inbox để nhận ưu đãi!")] and db.get_post(pid)["plug_done"] == 1
    assert client.post("/api/posts", json={"message": "y", "plug_likes": 5}).status_code == 400


def test_multi_image_post_uses_attached_media(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DRY_RUN", False)
    monkeypatch.setattr(config, "PAGE_ID", "PG")
    monkeypatch.setattr(facebook, "MEDIA_DIR", tmp_path)
    (tmp_path / "a.png").write_bytes(b"img")
    calls, n = [], iter(range(1, 10))

    def fake_call(method, path, params=None, json=None, token=None):
        calls.append((path, json))
        return {"id": f"m{next(n)}"}

    class R:
        status_code = 200
        def json(self): return {"id": "file1"}
    uploads = []
    monkeypatch.setattr(facebook, "_call", fake_call)
    monkeypatch.setattr(facebook.requests, "post",
                        lambda url, data=None, files=None, timeout=0: uploads.append(data) or R())
    fid = facebook.publish_post("Nội dung", "https://x.vn", "https://img/1.jpg\n/media/a.png\n")
    assert uploads[0]["published"] == "false"
    assert calls[0] == ("PG/photos", {"url": "https://img/1.jpg", "published": False})
    path, body = calls[-1]
    assert path == "PG/feed" and body["attached_media"] == [{"media_fbid": "m1"}, {"media_fbid": "file1"}]
    assert "https://x.vn" in body["message"] and fid == "m2"


def test_media_upload_list_serve_delete(client):
    assert client.post("/api/media", json={"data": "data:text/html;base64,PGI+"}).status_code == 400
    url = client.post("/api/media", json={"data": PNG}).json()["url"]
    assert url.startswith("/media/") and url.endswith(".png")
    assert [m["url"] for m in client.get("/api/media").json()] == [url]
    assert client.get(url).content.startswith(b"\x89PNG")
    assert client.get("/media/..%2Fqc.db").status_code == 404
    client.delete("/api/media/" + url.rsplit("/", 1)[-1])
    assert client.get("/api/media").json() == []


def test_signatures_keep_only_one_auto(client):
    r = client.put("/api/signatures", json={"items": [
        {"name": "Hotline", "text": "📞 0909", "auto": True}, {"text": "#ketoan", "auto": True}, {"text": " "}]}).json()
    assert [x["auto"] for x in r] == [True, False] and r[1]["name"] == "#ketoan"
    assert client.get("/api/signatures").json() == r
