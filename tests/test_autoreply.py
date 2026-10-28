import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import autoreply, bot, config, db, facebook, server
from app.facebook import FacebookError
from tests.test_bot import comment_event


@pytest.fixture
def client():
    return TestClient(server.app)


@pytest.fixture
def sent(monkeypatch):
    """Ghi lại mọi lệnh gửi lên Facebook; reply_comment trả id thật như Graph API."""
    calls = []
    monkeypatch.setattr(config, "PAGE_ID", "PAGE1")
    monkeypatch.setattr(facebook, "reply_comment", lambda cid, text: calls.append(("public", cid, text)) or {"id": f"R{len(calls)}"})
    monkeypatch.setattr(facebook, "private_reply", lambda cid, text: calls.append(("private", cid, text)) or {"id": "m"})
    monkeypatch.setattr(facebook, "send_message", lambda *a, **k: {"id": "x"})
    return calls


RULES = {"enabled": True, "rules": [
    {"keywords": ["giá", "báo giá"], "reply": "Chào {name}, mình báo giá qua tin nhắn nhé", "private": "Bảng giá: ..."},
    {"keywords": ["demo"], "reply": "Dạ {name}, bên em gửi bản dùng thử ạ", "private": ""},
]}


def save(client, **over):
    r = client.put("/api/auto-reply", json={**RULES, **over})
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------- cấu hình

def test_config_validation(client):
    assert client.put("/api/auto-reply", json={"enabled": True}).status_code == 400            # bật mà chưa có gì
    r = client.put("/api/auto-reply", json={"rules": [{"keywords": "", "reply": "x"}]})
    assert r.status_code == 400 and "từ khóa" in r.json()["detail"]
    r = client.put("/api/auto-reply", json={"rules": [{"keywords": "giá", "reply": ""}]})
    assert r.status_code == 400 and "nội dung" in r.json()["detail"]
    ok = save(client, rules=[{"keywords": "giá, báo giá ,", "reply": "ok"}, {"keywords": "", "reply": ""}])
    assert ok["rules"] == [{"keywords": ["giá", "báo giá"], "reply": "ok", "private": ""}]      # dòng trống bị bỏ
    assert client.get("/api/auto-reply").json()["enabled"] is True


def test_rule_tester_does_not_need_saving(client):
    save(client)
    r = client.post("/api/auto-reply/test", json={"text": "Cho mình xin BAO GIA với"}).json()
    assert r["match"] and "báo giá qua tin nhắn" in r["reply"] and r["private"] == "Bảng giá: ..."
    assert client.post("/api/auto-reply/test", json={"text": "bài hay quá"}).json() == {"match": False}
    r = client.post("/api/auto-reply/test", json={"text": "hello", "default_reply": "Cảm ơn {name}!"}).json()
    assert r["match"] and r["reply"] == "Cảm ơn Lan!"


# ---------------------------------------------------------------- tự trả lời

def test_matching_comment_gets_public_and_private_reply_and_thread_shows_it(client, sent):
    save(client)
    bot.handle_webhook(comment_event(comment_id="c1", text="Cho mình xin báo giá", name="Nguyễn Văn An"))
    assert [(k, t) for k, _, t in sent] == [("private", "Bảng giá: ..."), ("public", "Chào An, mình báo giá qua tin nhắn nhé")]
    c = db.get_comment("c1")
    assert c["status"] == "replied" and c["reply_by"] == "auto" and "Bảng giá" in c["reply_text"]
    page_rows = [r for r in db.list_thread("p1") if r["status"] == "page"]
    assert len(page_rows) == 1 and page_rows[0]["parent_id"] == "c1" and page_rows[0]["id"] == "R2"
    assert db.count_activity_today("auto_reply") == 1


def test_accent_insensitive_keyword_and_no_match_is_left_for_human(client, sent):
    save(client)
    bot.handle_webhook(comment_event(comment_id="c2", text="mình muốn DEMO thử", name="Bình"))
    assert sent[0][0] == "public" and "bản dùng thử" in sent[0][2]
    sent.clear()
    bot.handle_webhook(comment_event(comment_id="c3", text="bài viết hay quá", name="Cường"))
    assert sent == [] and db.get_comment("c3")["status"] == "new"


def test_default_reply_for_everything_else(client, sent):
    save(client, default_reply="Cảm ơn {name} đã quan tâm ❤️", rules=[])
    bot.handle_webhook(comment_event(comment_id="c4", text="hay quá", name="Dũng"))
    assert sent == [("public", "c4", "Cảm ơn Dũng đã quan tâm ❤️")]


def test_disabled_falls_back_to_old_keyword_flow(client, sent):
    save(client, enabled=False)
    bot.handle_webhook(comment_event(comment_id="c5", text="quan tâm", name="Em"))
    assert [k for k, *_ in sent] == ["private", "public"]                 # kịch bản cũ vẫn chạy
    assert db.get_comment("c5")["reply_by"] == "auto"


def test_auto_reply_takes_priority_and_does_not_double_reply(client, sent):
    save(client, rules=[{"keywords": ["quan tâm"], "reply": "Luật mới", "private": ""}])
    bot.handle_webhook(comment_event(comment_id="c6", text="quan tâm", name="Hà"))
    assert sent == [("public", "c6", "Luật mới")]                         # kịch bản cũ không chạy thêm


def test_once_per_person_per_post(client, sent):
    save(client)
    bot.handle_webhook(comment_event(comment_id="c7", text="giá?", from_id="u7", name="Khoa"))
    bot.handle_webhook(comment_event(comment_id="c8", text="giá bao nhiêu vậy", from_id="u7", name="Khoa"))
    assert len([s for s in sent if s[0] == "public"]) == 1
    assert db.get_comment("c8")["status"] == "new"                        # để người thật xem
    save(client, once_per_person=False)
    bot.handle_webhook(comment_event(comment_id="c9", text="giá", from_id="u7", name="Khoa"))
    assert len([s for s in sent if s[0] == "public"]) == 2


def test_replies_inside_a_thread_are_skipped_by_default(client, sent):
    save(client)
    ev = comment_event(comment_id="c10", text="giá", from_id="u10", name="Lâm")
    ev["entry"][0]["changes"][0]["value"]["parent_id"] = "c1"              # nằm trong bình luận khác
    bot.handle_webhook(ev)
    assert sent == []


def test_daily_limit(client, sent):
    save(client, daily_limit=1, once_per_person=False)
    bot.handle_webhook(comment_event(comment_id="d1", text="giá", from_id="a", name="A"))
    bot.handle_webhook(comment_event(comment_id="d2", text="giá", from_id="b", name="B"))
    assert len([s for s in sent if s[0] == "public"]) == 1
    assert any("giới hạn" in a["text"] for a in db.list_activity())


def test_send_error_is_logged_not_raised_and_not_retried_by_old_flow(client, sent, monkeypatch):
    def boom(cid, text):
        raise FacebookError("(#200) Requires pages_manage_engagement permission (code 200)")
    monkeypatch.setattr(facebook, "reply_comment", boom)
    save(client, rules=[{"keywords": ["quan tâm"], "reply": "x", "private": ""}])
    bot.handle_webhook(comment_event(comment_id="e1", text="quan tâm", name="Ngọc"))
    assert db.get_comment("e1")["status"] == "new" and sent == []
    assert any(a["kind"] == "error" and "pages_manage_engagement" in a["text"] for a in db.list_activity())


# ---------------------------------------------------------------- đã xem / mới

def test_new_comment_is_unseen_until_opened(client, sent):
    bot.handle_webhook(comment_event(comment_id="s1", text="hay quá", name="Oanh"))
    bot.handle_webhook(comment_event(comment_id="s2", text="tuyệt", name="Phúc"))
    assert client.get("/api/badges").json()["comments_new"] == 2
    assert [c["id"] for c in client.get("/api/comments?status=unseen").json()] == ["s2", "s1"]
    client.post("/api/comments/s1/seen")
    assert client.get("/api/badges").json()["comments_new"] == 1
    assert client.get("/api/badges").json()["comments_open"] == 2        # vẫn cần trả lời
    client.post("/api/comments/seen-all")
    assert client.get("/api/badges").json()["comments_new"] == 0
    assert client.post("/api/comments/nope/seen").status_code == 404


def test_replying_marks_seen(client, sent):
    bot.handle_webhook(comment_event(comment_id="s3", text="hay", name="Quân"))
    client.post("/api/comments/s3/reply", json={"text": "Cảm ơn bạn"})
    assert db.get_comment("s3")["seen"] == 1


def test_old_database_comments_become_seen_on_migration(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE comments (id TEXT PRIMARY KEY, post_id TEXT DEFAULT '', parent_id TEXT DEFAULT '', "
              "from_id TEXT DEFAULT '', from_name TEXT DEFAULT '', message TEXT DEFAULT '', created_at INTEGER NOT NULL, "
              "status TEXT NOT NULL DEFAULT 'new', reply_text TEXT DEFAULT '', replied_at INTEGER)")
    c.execute("INSERT INTO comments(id, created_at) VALUES('old', 1)"); c.commit(); c.close()
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init()
    assert db.get_comment("old")["seen"] == 1 and db.count_unseen_comments() == 0
    db.save_comment("new1", created_at=2)
    assert db.count_unseen_comments() == 1


# ---------------------------------------------------------------- khung xem bài

def seed_thread():
    db.save_comment("A", "P_1", "u1", "An", "Phần mềm này dùng cho 30 công ty được không?", 100)
    db.save_comment("B", "P_1", "u2", "Bình", "Giá bao nhiêu vậy?", 200)
    db.save_comment("A1", "P_1", "PAGE1", "Fanpage (bạn)", "Dạ được ạ", 150, parent_id="A", status="page", seen=1)
    db.save_comment("A2", "P_1", "u1", "An", "Cảm ơn shop", 160, parent_id="A")
    db.save_comment("X", "P_2", "u9", "Khác bài", "bài khác", 50)


def test_thread_shows_whole_post_like_facebook(client):
    seed_thread()
    t = client.get("/api/comments/B/thread").json()
    assert t["focus"] == "B" and t["post"]["permalink"] == "https://www.facebook.com/P_1"
    assert [c["id"] for c in t["comments"]] == ["A", "B"]                      # theo thời gian, không lẫn bài khác
    a = t["comments"][0]
    assert [r["id"] for r in a["replies"]] == ["A1", "A2"]
    assert a["replies"][0]["is_page"] is True and a["replies"][1]["is_page"] is False
    assert client.get("/api/comments/nope/thread").status_code == 404


def test_page_replies_are_not_in_the_inbox(client):
    seed_thread()
    ids = [c["id"] for c in client.get("/api/comments?status=all").json()]
    assert "A1" not in ids and {"A", "B", "A2", "X"} <= set(ids)


def test_thread_live_adds_missed_comments_and_replies_typed_on_facebook(client, monkeypatch):
    seed_thread()
    monkeypatch.setattr(facebook, "fetch_thread", lambda pid, limit=50: [
        {"id": "A", "post_id": pid, "parent_id": "", "from_id": "u1", "from_name": "An", "message": "Phần mềm này dùng cho 30 công ty được không? (đã sửa)", "created_time": 100, "is_page": False},
        {"id": "M", "post_id": pid, "parent_id": "", "from_id": "u5", "from_name": "Mai", "message": "bị lỡ webhook", "created_time": 300, "is_page": False},
        {"id": "MR", "post_id": pid, "parent_id": "M", "from_id": "PAGE1", "from_name": "Page", "message": "Mình trả lời trên FB", "created_time": 310, "is_page": True},
        {"id": "A1-real", "post_id": pid, "parent_id": "A", "from_id": "PAGE1", "from_name": "Page", "message": "Dạ được ạ", "created_time": 150, "is_page": True},
    ])
    t = client.get("/api/comments/A/thread?live=1").json()
    assert t["live_error"] == ""
    top = {c["id"]: c for c in t["comments"]}
    assert "M" in top and [r["message"] for r in top["M"]["replies"]] == ["Mình trả lời trên FB"]
    assert top["M"]["status"] == "replied" and top["M"]["seen"] == 1               # có Fanpage trả lời rồi
    assert [r["id"] for r in top["A"]["replies"]] == ["A1", "A2"]                    # trả lời trùng nội dung không bị nhân đôi
    assert db.get_comment("A")["message"].endswith("(đã sửa)")                       # nội dung theo Facebook (khi người dùng sửa bình luận)


def test_thread_live_failure_still_returns_local_thread(client, monkeypatch):
    seed_thread()
    def boom(pid, limit=50):
        raise FacebookError("(#10) Requires pages_read_user_content")
    monkeypatch.setattr(facebook, "fetch_thread", boom)
    t = client.get("/api/comments/A/thread?live=1").json()
    assert "pages_read_user_content" in t["live_error"] and len(t["comments"]) == 2


# ---------------------------------------------------------------- quyền của token

def test_token_scopes_reports_missing_permissions(client, monkeypatch):
    monkeypatch.setattr(server, "_scope_cache", {"at": 0, "data": None})
    assert client.get("/api/token-scopes").json()["connected"] is False                  # chạy thử
    monkeypatch.setattr(config, "DRY_RUN", False)
    monkeypatch.setattr(facebook, "token_scopes", lambda: {"scopes": ["pages_show_list", "pages_manage_posts"], "valid": True, "expires_at": 0})
    r = client.get("/api/token-scopes?refresh=1").json()
    assert r["connected"] and {m["scope"] for m in r["missing"]} == {"pages_manage_engagement", "read_insights", "pages_read_user_content"}
    monkeypatch.setattr(facebook, "token_scopes", lambda: {"scopes": ["pages_manage_engagement", "read_insights", "pages_read_user_content"], "valid": True, "expires_at": 0})
    assert client.get("/api/token-scopes?refresh=1").json()["missing"] == []


def test_token_scopes_parser(monkeypatch):
    monkeypatch.setattr(config, "DRY_RUN", False)
    monkeypatch.setattr(config, "APP_SECRET", "sec")
    seen = []
    def fake(method, path, params=None, json=None, token=None):
        seen.append((path, token))
        return {"id": "123"} if path == "app" else {"data": {"is_valid": True, "scopes": ["pages_show_list"], "expires_at": 0}}
    monkeypatch.setattr(facebook, "_call", fake)
    assert facebook.token_scopes()["scopes"] == ["pages_show_list"]
    assert seen[1] == ("debug_token", "123|sec")                                         # dùng app token, không dùng page token


# ---------------------------------------------------------------- bài này ở Fanpage nào

def test_comment_shows_which_page_and_post(client, monkeypatch):
    monkeypatch.setattr(server, "_page_cache", {"at": 0, "name": ""})
    monkeypatch.setattr(config, "PAGE_ID", "PAGE1")
    monkeypatch.setattr(config, "DRY_RUN", False)
    monkeypatch.setattr(facebook, "page_info", lambda: {"name": "Group Kế Toán HCM"})
    db.upsert_post_stats("PAGE1_77", "📢 Cuối tháng tải hóa đơn cho cả chục công ty mất cả buổi? " * 3, "https://fb/77")
    db.save_comment("w1", "PAGE1_77", "u1", "An", "hay quá", 10)
    db.save_comment("w2", "OTHER_5", "u2", "Bình", "ở trang khác", 20)
    rows = {c["id"]: c for c in client.get("/api/comments?status=all").json()}
    assert rows["w1"]["page_name"] == "Group Kế Toán HCM" and rows["w1"]["post_snippet"].startswith("📢 Cuối tháng")
    assert rows["w1"]["post_snippet"].endswith("…") and len(rows["w1"]["post_snippet"]) <= 91
    assert rows["w1"]["post_url"] == "https://www.facebook.com/PAGE1_77"
    assert rows["w2"]["page_name"] == "Trang OTHER"
    t = client.get("/api/comments/w1/thread").json()["post"]
    assert t["page_name"] == "Group Kế Toán HCM" and t["message"].startswith("📢")


def test_post_message_falls_back_to_posts_made_in_the_app(client):
    pid = db.create_post("Bài đăng từ phần mềm")
    db.update_post(pid, fb_post_id="PAGE1_88", status="posted")
    assert db.post_message("PAGE1_88") == "Bài đăng từ phần mềm" and db.post_message("") == ""


def test_page_name_lookup_failure_degrades_gracefully(client, monkeypatch):
    monkeypatch.setattr(server, "_page_cache", {"at": 0, "name": ""})
    monkeypatch.setattr(config, "PAGE_ID", "PAGE1")
    monkeypatch.setattr(config, "DRY_RUN", False)
    def boom():
        raise FacebookError("offline")
    monkeypatch.setattr(facebook, "page_info", boom)
    db.save_comment("w3", "PAGE1_9", "u", "A", "x", 1)
    assert client.get("/api/comments?status=all").json()[0]["page_name"] == "Trang PAGE1"
