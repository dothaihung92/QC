import pytest
from fastapi.testclient import TestClient

from app import db, groupbot, groupwriter, newsagent, server


@pytest.fixture
def client():
    return TestClient(server.app)


def _groups(client, *spec):
    ids = []
    for name, url, members in spec:
        gid = client.post("/api/groups", json={"name": name, "url": url}).json()["id"]
        if members:
            client.put(f"/api/groups/{gid}", json={"members": members})
        ids.append(gid)
    return ids


def test_groups_sorted_by_members_and_member_parsing(client):
    a, b, c = _groups(client, ("Nhỏ", "111", 900), ("Lớn", "222", 52000), ("Vừa", "333", 12300))
    assert [g["name"] for g in client.get("/api/groups").json()] == ["Lớn", "Vừa", "Nhỏ"]
    assert groupbot.parse_members("Nhóm Công khai · 12,3K thành viên") == 12300
    assert groupbot.parse_members("45.678 thành viên") == 45678
    assert groupbot.parse_members("1,2 triệu thành viên") == 1200000
    assert groupbot.parse_members("3.4K members") == 3400 and groupbot.parse_members("không có") == 0


def test_seo_article_becomes_distinct_post_per_group(client, monkeypatch):
    a, b, c = _groups(client, ("Diễn đàn thuế", "111", 5000), ("Thư viện kế toán", "222", 20000), ("Kế toán HCM", "333", 0))
    newsagent.save_config({"gemini_key": "k"})
    calls = []

    def fake(prompt, cfg):
        calls.append(prompt)
        if len(calls) == 1:          # lần đầu AI trả 2 bài giống hệt nhau + thiếu 1 bài → phải viết lại
            same = "Doanh nghiệp VOSA bị phạt hơn 2 tỷ đồng vì sai phạm hóa đơn và kê khai thuế TNDN. " * 2
            return {"posts": [{"n": 0, "text": same}, {"n": 1, "text": same + " https://x.vn/bai"}]}
        return {"posts": [{"n": k, "text": f"Câu chuyện số {k}: một kế toán phát hiện chi phí không có hóa đơn hợp lệ nên bị loại khi tính thuế TNDN, "
                                           f"bài học rút ra là rà soát chứng từ mỗi quý. Góc nhìn {k * 7} khác hẳn."} for k in range(3)]}
    monkeypatch.setattr(newsagent, "gemini_json", fake)
    r = client.post("/api/group-jobs/from-article", json={"title": "Sai phạm hóa đơn thuế TNDN", "url": "https://x.vn/bai/",
                                                          "keyword": "sai phạm hóa đơn", "content": "Nội dung bài SEO."}).json()
    assert r["groups"] == 3 and len(calls) == 2
    job = client.get("/api/group-jobs").json()[0]
    assert job["title"] == "Sai phạm hóa đơn thuế TNDN" and job["link"] == "https://x.vn/bai/"
    assert [g["name"] for g in job["groups"]] == ["Thư viện kế toán", "Diễn đàn thuế", "Kế toán HCM"]     # đông trước
    texts = [g["text"] for g in job["groups"]]
    assert all("https://" not in t for t in texts)                                         # link do phần mềm gắn cuối
    assert all(groupwriter.similarity(x, y) <= groupwriter.SIMILAR for i, x in enumerate(texts) for y in texts[i + 1:])
    assert all(g["state"] == "" for g in job["groups"])


def test_group_states_and_policy(client):
    a, b = _groups(client, ("A", "111", 0), ("B", "222", 0))
    jid = db.add_group_job("x", "", db.now(), [a, b], variants={a: "riêng A"})
    client.post(f"/api/group-jobs/{jid}/state", json={"group_id": a, "state": "pending"})
    client.post(f"/api/group-jobs/{jid}/state", json={"group_id": b, "state": "blocked"})
    job = client.get("/api/group-jobs").json()[0]
    st = {g["name"]: (g["state"], g["done"], g["text"]) for g in job["groups"]}
    assert st == {"A": ("pending", True, "riêng A"), "B": ("blocked", False, "x")}
    pol = {g["name"]: g["policy"] for g in client.get("/api/groups").json()}
    assert pol == {"A": "review", "B": "blocked"}
    client.post(f"/api/group-jobs/{jid}/state", json={"group_id": a, "state": "approved"})
    assert client.get("/api/group-jobs").json()[0]["groups"][0]["state"] == "approved"
    assert client.post(f"/api/group-jobs/{jid}/state", json={"group_id": a, "state": "xyz"}).status_code == 400
    client.put(f"/api/group-jobs/{jid}/variant", json={"group_id": b, "text": "nội dung sửa tay"})
    assert {g["name"]: g["text"] for g in client.get("/api/group-jobs").json()[0]["groups"]}["B"] == "nội dung sửa tay"
    # nhóm "không cho đăng" không được đưa vào lịch tạo từ bài SEO
    r = client.post("/api/group-jobs/from-article", json={"title": "T", "content": "c"}).json()
    assert r["groups"] == 1


def test_seo_tab_creates_group_job_after_publishing():
    js = TestClient(server.app).get("/qc-bridge.js").text
    assert "/api/group-jobs/from-article" in js and "qcMakeGroupJob" in js and "createGroupJob(a, a._publishedUrl)" in js


def test_bot_posts_each_group_its_own_text_biggest_first_and_skips_blocked(client, monkeypatch, tmp_path):
    import contextlib
    import sys
    import types
    a, b, c = _groups(client, ("Nhỏ", "111", 100), ("Lớn", "222", 9000), ("Cấm", "333", 5000))
    jid = db.add_group_job("chung", "https://x.vn/bai/", db.now(), [a, b, c], variants={a: "bài cho Nhỏ", b: "bài cho Lớn", c: "bài cho Cấm"})
    posted = []

    class Page:
        url = ""
        def goto(self, url, **k): self.url = url
        def wait_for_timeout(self, ms): pass
        def screenshot(self, **k): pass

    class Ctx:
        pages = [Page()]
        def close(self): pass

    def fake_post(page, text, timeout=0):
        if page.url.endswith("333"):
            raise groupbot.NoComposer("không có ô viết bài")
        posted.append((page.url.rsplit("/", 1)[-1], text))
        return "pending" if page.url.endswith("111") else "ok"

    mod = types.ModuleType("playwright.sync_api")
    mod.sync_playwright = lambda: contextlib.nullcontext(object())
    monkeypatch.setitem(sys.modules, "playwright.sync_api", mod)
    monkeypatch.setattr(groupbot, "_launch", lambda p, visible: Ctx())
    monkeypatch.setattr(groupbot, "post_to_open_group", fake_post)
    monkeypatch.setattr(groupbot, "MARKER", tmp_path / "logged")
    (tmp_path / "logged").write_text("1")
    monkeypatch.setattr(groupbot, "_sleep", lambda s: None)
    groupbot._run_job(jid)
    assert posted == [("222", "bài cho Lớn\n\nhttps://x.vn/bai/"), ("111", "bài cho Nhỏ\n\nhttps://x.vn/bai/")]
    st = {g["name"]: g["state"] for g in client.get("/api/group-jobs").json()[0]["groups"]}
    assert st == {"Lớn": "ok", "Cấm": "blocked", "Nhỏ": "pending"}
