import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from app import config, db, facebook, server
from app.facebook import FacebookError

AUTH = ("admin", "secret")


@pytest.fixture
def client():
    return TestClient(server.app)


def test_dashboard_requires_password(client):
    assert client.get("/").status_code == 401
    assert client.get("/api/status").status_code == 401
    assert client.get("/", auth=("admin", "wrong")).status_code == 401
    r = client.get("/", auth=AUTH)
    assert r.status_code == 200 and "Quảng cáo Fanpage" in r.text


def test_webhook_verification(client):
    ok = client.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "verify-me",
                                        "hub.challenge": "12345"})
    assert ok.status_code == 200 and ok.text == "12345"
    bad = client.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "x",
                                         "hub.challenge": "1"})
    assert bad.status_code == 403


def test_webhook_signature_checked(client, monkeypatch, fb_calls):
    monkeypatch.setattr(config, "APP_SECRET", "app-secret")
    body = json.dumps({"object": "page", "entry": [{"messaging": [
        {"sender": {"id": "U1"}, "timestamp": 1, "message": {"mid": "m1", "text": "hi"}}]}]}).encode()
    bad = client.post("/webhook", content=body, headers={"X-Hub-Signature-256": "sha256=00"})
    assert bad.status_code == 403
    sig = "sha256=" + hmac.new(b"app-secret", body, hashlib.sha256).hexdigest()
    ok = client.post("/webhook", content=body, headers={"X-Hub-Signature-256": sig,
                                                        "Content-Type": "application/json"})
    assert ok.status_code == 200
    assert [n for n, _ in fb_calls] == ["send_message"]


def test_publish_now_in_dry_run(client):
    r = client.post("/api/posts", auth=AUTH, json={"message": "Xin chào", "publish_now": True})
    assert r.json()["status"] == "posted"


def test_scheduled_post_published_by_scheduler(monkeypatch):
    published = []
    monkeypatch.setattr(facebook, "publish_post", lambda m, l="", i="": published.append(m) or "123_456")
    pid = db.create_post("Bài hẹn giờ", scheduled_at=db.now() - 1)
    future = db.create_post("Chưa tới giờ", scheduled_at=db.now() + 3600)
    for post in db.claim_due_posts():
        server.publish(post)
    assert published == ["Bài hẹn giờ"]
    assert db.get_post(pid)["status"] == "posted" and db.get_post(pid)["fb_post_id"] == "123_456"
    assert db.get_post(future)["status"] == "scheduled"
    assert db.claim_due_posts() == []          # không đăng lại


def test_failed_publish_is_recorded(monkeypatch):
    def boom(*a):
        raise FacebookError("Token hết hạn (code 190)")
    monkeypatch.setattr(facebook, "publish_post", boom)
    pid = db.create_post("x")
    post = server.publish(db.get_post(pid))
    assert post["status"] == "failed" and "190" in post["error"]


def test_script_validation(client):
    script = client.get("/api/script", auth=AUTH).json()
    script["features"][0]["short"] = "Tên nút quá dài vượt hai mươi ký tự"
    assert client.put("/api/script", auth=AUTH, json=script).status_code == 400
    assert client.put("/api/script", auth=AUTH, json={"hack": 1}).status_code == 400
    assert client.put("/api/script", auth=AUTH, json={"pricing": "Giá 1 triệu"}).json()["pricing"] == "Giá 1 triệu"


def test_simulator_does_not_create_visible_lead(client):
    r = client.post("/api/simulate", auth=AUTH, json={"text": "tờ khai GTGT"}).json()
    assert "TỜ KHAI" in r["text"]
    assert client.get("/api/leads", auth=AUTH).json() == []
    c = client.post("/api/simulate", auth=AUTH, json={"kind": "comment", "text": "xin báo giá"}).json()
    assert c["will_reply"] is True


def test_leads_csv(client):
    db.upsert_lead("PSID9", "messenger", "Lan", "hello")
    r = client.get("/api/leads.csv", auth=AUTH)
    assert r.status_code == 200 and "PSID9" in r.text and "Lan" in r.text
