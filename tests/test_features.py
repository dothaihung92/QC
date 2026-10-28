import pytest
from fastapi.testclient import TestClient

from app import bot, config, db, facebook, server
from app.facebook import FacebookError
from tests.test_bot import comment_event


@pytest.fixture
def client():
    return TestClient(server.app)


# ---------------------------------------------------------------- bình luận

def test_webhook_comment_lands_in_inbox_and_bot_marks_it_answered(fb_calls):
    bot.handle_webhook(comment_event(comment_id="c1", text="quan tâm nhé", name="Lan Anh"))
    c = db.get_comment("c1")
    assert c["from_name"] == "Lan Anh" and c["message"] == "quan tâm nhé"
    assert c["status"] == "replied"                     # bot đã nhắn riêng + trả lời công khai


def test_comment_without_keyword_waits_for_human(fb_calls):
    bot.handle_webhook(comment_event(comment_id="c2", text="bài hay quá"))
    assert fb_calls == [] and db.get_comment("c2")["status"] == "new"
    assert db.count_new_comments() == 1


def test_reply_from_dashboard(client, monkeypatch):
    sent = []
    monkeypatch.setattr(facebook, "reply_comment", lambda cid, text: sent.append((cid, text)) or {"id": "x"})
    db.save_comment("c3", from_name="Minh", message="giá bao nhiêu?")
    r = client.post("/api/comments/c3/reply", json={"text": "Dạ em báo giá qua tin nhắn ạ"})
    assert r.status_code == 200 and r.json()["status"] == "replied"
    assert sent == [("c3", "Dạ em báo giá qua tin nhắn ạ")]
    assert client.get("/api/comments").json() == []             # hết ở mục "cần xử lý"
    assert [c["id"] for c in client.get("/api/comments?status=all").json()] == ["c3"]


def test_reply_permission_error_has_hint_and_keeps_comment_open(client, monkeypatch):
    def boom(cid, text):
        raise FacebookError("(#200) Requires pages_manage_engagement permission (code 200)")
    monkeypatch.setattr(facebook, "reply_comment", boom)
    db.save_comment("c4", message="hi")
    r = client.post("/api/comments/c4/reply", json={"text": "chào"})
    assert r.status_code == 502 and "pages_manage_engagement" in r.json()["detail"]
    assert db.get_comment("c4")["status"] == "new"


def test_private_reply_ignore_and_validation(client, monkeypatch):
    monkeypatch.setattr(facebook, "private_reply", lambda cid, text: {"id": "m"})
    db.save_comment("c5", message="a"); db.save_comment("c6", message="b")
    assert client.post("/api/comments/c5/private", json={"text": "Chào bạn"}).json()["status"] == "private_replied"
    assert client.post("/api/comments/c6/status", json={"status": "ignored"}).json()["status"] == "ignored"
    assert client.post("/api/comments/c6/status", json={"status": "hack"}).status_code == 400
    assert client.post("/api/comments/nope/reply", json={"text": "x"}).status_code == 404
    assert client.post("/api/comments/c5/reply", json={"text": "  "}).status_code == 400


def test_sync_comments_adds_new_keeps_status_and_skips_page(client, monkeypatch):
    monkeypatch.setattr(config, "PAGE_ID", "PAGE1")
    monkeypatch.setattr(facebook, "list_published_posts", lambda limit=8, with_views=False: [{"id": "P_1"}])
    monkeypatch.setattr(facebook, "list_post_comments", lambda pid, limit=25: [
        {"id": "s1", "post_id": pid, "from_id": "u1", "from_name": "An", "message": "hay", "created_time": 5, "page_replied": False},
        {"id": "s2", "post_id": pid, "from_id": "u2", "from_name": "Bình", "message": "ok", "created_time": 6, "page_replied": True},
        {"id": "s3", "post_id": pid, "from_id": "PAGE1", "from_name": "Page", "message": "cảm ơn", "created_time": 7, "page_replied": False},
    ])
    db.save_comment("s1", message="", status="new"); db.update_comment("s1", status="ignored")
    r = client.post("/api/comments/sync").json()
    assert r["added"] == 1                                   # chỉ s2 là mới; s3 là của Page
    assert db.get_comment("s1")["status"] == "ignored" and db.get_comment("s1")["message"] == "hay"
    assert db.get_comment("s2")["status"] == "replied" and db.get_comment("s3") is None


def test_sync_needs_connection_in_dry_run(client):
    r = client.post("/api/comments/sync")
    assert r.status_code == 502 and ".env" in r.json()["detail"]


# ---------------------------------------------------------------- thống kê

def test_stats_sync_and_totals(client, monkeypatch):
    monkeypatch.setattr(facebook, "list_published_posts", lambda limit=20, with_views=True: [
        {"id": "P_1", "message": "Bài 1", "permalink": "https://fb/1", "created_time": 200, "likes": 10, "comments": 2, "shares": 1, "views": 500},
        {"id": "P_2", "message": "Bài 2", "permalink": "https://fb/2", "created_time": 100, "likes": 5, "comments": 0, "shares": 0, "views": None},
    ])
    d = client.post("/api/stats/sync").json()
    assert d["totals"] == {"likes": 15, "comments": 2, "shares": 1, "views": 500, "posts": 2}
    assert [p["fb_post_id"] for p in d["posts"]] == ["P_1", "P_2"]          # mới nhất trước
    # đồng bộ lại mà Facebook không trả views → giữ số cũ
    monkeypatch.setattr(facebook, "list_published_posts", lambda limit=20, with_views=True: [
        {"id": "P_1", "message": "Bài 1", "permalink": "", "created_time": 200, "likes": 12, "comments": 2, "shares": 1, "views": None}])
    d = client.post("/api/stats/sync").json()
    p1 = [p for p in d["posts"] if p["fb_post_id"] == "P_1"][0]
    assert p1["likes"] == 12 and p1["views"] == 500


def test_stats_empty(client):
    d = client.get("/api/stats").json()
    assert d["posts"] == [] and d["totals"]["views"] is None and d["synced_at"] is None


def test_facebook_parsers(monkeypatch):
    monkeypatch.setattr(config, "DRY_RUN", False)
    monkeypatch.setattr(config, "PAGE_ID", "PAGE1")

    def fake(method, path, params=None, json=None):
        if path.endswith("/published_posts"):
            return {"data": [{"id": "P_1", "message": "m", "created_time": "2026-09-28T16:00:00+0000",
                              "permalink_url": "https://fb/p", "shares": {"count": 3},
                              "reactions": {"summary": {"total_count": 9}}, "comments": {"summary": {"total_count": 4}}}]}
        if path.endswith("/insights"):
            if params["metric"] == "post_media_view":
                return {"data": [{"values": [{"value": 321}]}]}
            raise FacebookError("(#100) metric deprecated")
        if path.endswith("/comments"):
            return {"data": [{"id": "c9", "message": "hi", "created_time": "2026-09-28T17:00:00+0000",
                              "from": {"id": "u1", "name": "Hà"}, "comments": {"data": [{"id": "r", "from": {"id": "PAGE1"}}]}}]}
        raise AssertionError(path)
    monkeypatch.setattr(facebook, "_call", fake)
    p = facebook.list_published_posts()[0]
    assert (p["likes"], p["comments"], p["shares"], p["views"]) == (9, 4, 3, 321)
    assert p["created_time"] == 1790611200
    c = facebook.list_post_comments("P_1")[0]
    assert c["from_name"] == "Hà" and c["page_replied"] is True


def test_views_unavailable_returns_none(monkeypatch):
    def boom(*a, **k):
        raise FacebookError("(#100) no")
    monkeypatch.setattr(facebook, "_call", boom)
    assert facebook.post_views("P_1") is None


# ---------------------------------------------------------------- đăng nhóm

def test_group_urls_and_duplicates(client):
    a = client.post("/api/groups", json={"name": "Kế toán HCM", "url": "https://www.facebook.com/groups/12345/?ref=share"}).json()
    assert a["url"] == "https://www.facebook.com/groups/12345"
    assert client.post("/api/groups", json={"url": "12345"}).status_code == 400          # trùng
    assert client.post("/api/groups", json={"url": "not a group!"}).status_code == 400
    b = client.post("/api/groups", json={"url": "ketoanvietnam"}).json()
    assert b["name"] == "ketoanvietnam"
    assert len(client.get("/api/groups").json()) == 2


def test_group_job_lifecycle(client):
    g1 = client.post("/api/groups", json={"name": "A", "url": "111"}).json()["id"]
    g2 = client.post("/api/groups", json={"name": "B", "url": "222"}).json()["id"]
    assert client.post("/api/group-jobs", json={"message": "x", "group_ids": [999]}).status_code == 400
    assert client.post("/api/group-jobs", json={"message": " ", "group_ids": [g1]}).status_code == 400
    future = client.post("/api/group-jobs", json={"message": "Sau", "group_ids": [g1], "scheduled_at": db.now() + 3600}).json()["id"]
    due = client.post("/api/group-jobs", json={"message": "Ngay", "link": "https://x", "group_ids": [g1, g2]}).json()["id"]
    jobs = {j["id"]: j for j in client.get("/api/group-jobs").json()}
    assert jobs[future]["status"] == "scheduled" and jobs[due]["status"] == "due"
    assert client.get("/api/badges").json()["group_due"] == 1
    client.post(f"/api/group-jobs/{due}/toggle", json={"group_id": g1})
    assert {j["id"]: j for j in client.get("/api/group-jobs").json()}[due]["status"] == "due"     # còn group B
    client.post(f"/api/group-jobs/{due}/toggle", json={"group_id": g2})
    assert {j["id"]: j for j in client.get("/api/group-jobs").json()}[due]["status"] == "done"
    assert client.get("/api/badges").json()["group_due"] == 0
    client.post(f"/api/group-jobs/{due}/toggle", json={"group_id": g2})                          # bỏ đánh dấu
    assert {j["id"]: j for j in client.get("/api/group-jobs").json()}[due]["status"] == "due"
    assert client.post("/api/group-jobs/999/toggle", json={"group_id": g1}).status_code == 404
    client.delete(f"/api/group-jobs/{future}")
    assert future not in {j["id"] for j in client.get("/api/group-jobs").json()}


def test_deleted_group_disappears_from_jobs(client):
    g1 = client.post("/api/groups", json={"url": "111"}).json()["id"]
    g2 = client.post("/api/groups", json={"url": "222"}).json()["id"]
    jid = client.post("/api/group-jobs", json={"message": "x", "group_ids": [g1, g2]}).json()["id"]
    client.delete(f"/api/groups/{g2}")
    job = client.get("/api/group-jobs").json()[0]
    assert job["id"] == jid and [g["id"] for g in job["groups"]] == [g1]
