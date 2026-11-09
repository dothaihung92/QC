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

    def fake_post(page, text, timeout=0, images=None):
        if page.url.endswith("333"):
            raise groupbot.NoComposer("không có ô viết bài")
        posted.append((page.url.rsplit("/", 1)[-1], text))
        return "pending" if page.url.endswith("111") else "ok"

    mod = types.ModuleType("playwright.sync_api")
    mod.sync_playwright = lambda: contextlib.nullcontext(object())
    monkeypatch.setitem(sys.modules, "playwright.sync_api", mod)
    monkeypatch.setattr(groupbot, "_launch", lambda p, visible: Ctx())
    cm = []
    monkeypatch.setattr(groupbot, "post_to_open_group", fake_post)
    monkeypatch.setattr(groupbot, "comment_under_post", lambda page, url, text, link, timeout=0: cm.append((url.rsplit("/", 1)[-1], text, link)))
    monkeypatch.setattr(groupbot, "MARKER", tmp_path / "logged")
    (tmp_path / "logged").write_text("1")
    monkeypatch.setattr(groupbot, "_sleep", lambda s: None)
    groupbot._run_job(jid)
    assert posted == [("222", "bài cho Lớn"), ("111", "bài cho Nhỏ")]                 # bài gọn, KHÔNG kèm link
    assert cm == [("222", "bài cho Lớn", "https://x.vn/bai/")]                          # link bình luận dưới bài (nhóm chờ duyệt để sau)
    st = {g["name"]: g["state"] for g in client.get("/api/group-jobs").json()[0]["groups"]}
    assert st == {"Lớn": "ok", "Cấm": "blocked", "Nhỏ": "pending"}


def test_uses_google_chrome_and_imports_facebook_login(client, monkeypatch, tmp_path):
    import sqlite3
    ud = tmp_path / "Chrome" / "User Data"
    (ud / "Default" / "Network").mkdir(parents=True)
    (ud / "Profile 2" / "Network").mkdir(parents=True)
    (ud / "Local State").write_text('{"os_crypt": {}}')
    for prof, fb in (("Default", False), ("Profile 2", True)):
        with sqlite3.connect(ud / prof / "Network" / "Cookies") as c:
            c.execute("CREATE TABLE cookies (host_key TEXT, name TEXT, encrypted_value BLOB)")
            c.execute("INSERT INTO cookies VALUES ('.google.com', 'SID', x'00')")
            if fb:
                c.execute("INSERT INTO cookies VALUES ('.facebook.com', 'c_user', x'01')")
    monkeypatch.setattr(groupbot, "chrome_user_data", lambda: ud)
    monkeypatch.setattr(groupbot, "PROFILE_DIR", tmp_path / "profile")
    monkeypatch.setattr(groupbot, "MARKER", tmp_path / "profile" / ".da_dang_nhap")
    assert [p.name for p in groupbot.chrome_facebook_profiles()] == ["Profile 2"]
    st = client.get("/api/groupbot/status").json()
    assert st["browser"] == "chrome" and st["chrome_found"] is True               # mặc định Google Chrome

    channels = []

    class Chromium:
        def launch_persistent_context(self, **kw):
            channels.append(kw.get("channel"))
            raise RuntimeError("không có")
    import types
    with __import__("pytest").raises(groupbot.GroupBotError):
        groupbot._launch(types.SimpleNamespace(chromium=Chromium()))
    assert channels[:2] == ["chrome", "msedge"]                                   # Chrome trước, Edge dự phòng
    groupbot.MARKER.parent.mkdir(parents=True, exist_ok=True)
    groupbot.MARKER.write_text("1")
    client.post("/api/groupbot/settings", json={"browser": "msedge"})
    assert groupbot.browser() == "msedge" and not groupbot.MARKER.exists()          # đổi trình duyệt → đăng nhập lại
    channels.clear()
    with __import__("pytest").raises(groupbot.GroupBotError):
        groupbot._launch(types.SimpleNamespace(chromium=Chromium()))
    assert channels[:2] == ["msedge", "chrome"]

    # nhập đăng nhập từ Chrome: chép Local State + Cookies của hồ sơ có Facebook rồi mở thử
    import contextlib
    import sys
    mod = types.ModuleType("playwright.sync_api")
    mod.sync_playwright = lambda: contextlib.nullcontext(object())
    monkeypatch.setitem(sys.modules, "playwright.sync_api", mod)

    class Page:
        def goto(self, *a, **k): pass
        def wait_for_timeout(self, ms): pass
        def locator(self, sel): return types.SimpleNamespace(count=lambda: 0)

    class Ctx:
        pages = [Page()]
        def cookies(self, url): return [{"name": "c_user"}]
        def close(self): pass
    monkeypatch.setattr(groupbot, "_launch", lambda p, visible=True: Ctx())
    groupbot._import_chrome()
    assert (tmp_path / "profile" / "Local State").exists()
    assert (tmp_path / "profile" / "Default" / "Network" / "Cookies").exists()
    assert groupbot.MARKER.exists() and groupbot.browser() == "chrome"


def test_group_posts_are_short_and_link_is_left_for_comments(client, monkeypatch):
    _groups(client, ("A", "111", 100), ("B", "222", 50))
    newsagent.save_config({"gemini_key": "k"})
    long = "Dòng nội dung dài dòng về thuế để thử rút gọn bài đăng nhóm cho gọn lại. " * 3
    seen = []

    def fake(prompt, cfg):
        seen.append(prompt)
        return {"posts": [{"n": k, "text": f"Mở bài số {k * 3} rất riêng biệt\n" + "\n".join(f"{long} ý {k}{i}" for i in range(6)) +
                                           "\nLink bài viết em để ở bình luận nhé.\n#thue https://x.vn/bai/"} for k in range(2)]}
    monkeypatch.setattr(newsagent, "gemini_json", fake)
    client.post("/api/group-jobs/from-article", json={"title": "T", "url": "https://x.vn/bai/", "content": "c"})
    job = client.get("/api/group-jobs").json()[0]
    assert "tối đa 4 dòng ngắn" in seen[0] and "BÌNH LUẬN" in seen[0]
    for g in job["groups"]:
        assert len(g["text"]) <= groupwriter.MAX_CHARS * 1.25 and "https://" not in g["text"]
        assert g["commented"] is False
    client.post(f"/api/group-jobs/{job['id']}/commented", json={"group_id": job["groups"][0]["id"], "state": "1"})
    assert client.get("/api/group-jobs").json()[0]["groups"][0]["commented"] is True


def test_ai_writes_distinct_posts_from_user_text_with_images_and_can_post(client, monkeypatch):
    import base64
    a, b, c = _groups(client, ("Nhỏ", "111", 1000), ("Lớn", "222", 90000), ("Vừa", "333", 20000))
    newsagent.save_config({"gemini_key": "k"})
    png = base64.b64encode(b"\x89PNG\r\n\x1a\n").decode()
    img = client.post("/api/media", json={"data": "data:image/png;base64," + png}).json()["url"]
    seen = []

    def fake(prompt, cfg):
        seen.append(prompt)
        return {"posts": [{"n": k, "text": f"Bản {k}: dịch vụ kế toán trọn gói chỉ 1 triệu mỗi tháng, liên hệ 0986883137 để được tư vấn. "
                                           f"Cách nói khác biệt số {k * 11} dành cho nhóm này nhé anh chị."} for k in range(3)]}
    monkeypatch.setattr(newsagent, "gemini_json", fake)
    assert client.post("/api/group-jobs/ai", json={"message": "ngắn", "group_ids": [a]}).status_code == 400           # nội dung quá ngắn
    assert client.post("/api/group-jobs/ai", json={"message": "Dịch vụ kế toán trọn gói 1 triệu/tháng, liên hệ 0986883137.", "group_ids": []}).status_code == 400
    r = client.post("/api/group-jobs/ai", json={"message": "Dịch vụ kế toán trọn gói 1 triệu/tháng, liên hệ 0986883137.",
                                                "group_ids": [a, b, c], "images": [img, "/media/khong-co.png", "https://x.vn/a.jpg"]})
    assert r.status_code == 200 and r.json()["groups"] == 3 and r.json()["posting"] is False
    p = seen[0]
    assert "NỘI DUNG GỐC do người dùng soạn" in p and "bình luận / trao đổi" not in p and "BÌNH LUẬN" not in p      # không có link → không nhắc bình luận
    job = client.get("/api/group-jobs").json()[0]
    assert job["images"] == [img] and job["source"] == "ai"                              # chỉ giữ ảnh đã tải lên phần mềm
    assert [g["name"] for g in job["groups"]] == ["Lớn", "Vừa", "Nhỏ"]                     # nhóm đông trước
    texts = [g["text"] for g in job["groups"]]
    assert len(set(texts)) == 3 and all(g["custom"] for g in job["groups"])
    # đăng luôn: cần xác nhận rủi ro; chưa đăng nhập Facebook thì vẫn giữ lịch và báo lý do
    assert client.post("/api/group-jobs/ai", json={"message": "Nội dung đủ dài để AI viết lại nhé", "group_ids": [a], "post_now": True}).status_code == 400
    r = client.post("/api/group-jobs/ai", json={"message": "Nội dung đủ dài để AI viết lại nhé", "group_ids": [a], "post_now": True, "accept_risk": True}).json()
    assert r["posting"] is False and r["note"]
    started = []
    import tempfile
    from pathlib import Path
    marker = Path(tempfile.mkdtemp()) / "logged"
    marker.write_text("1")
    monkeypatch.setattr(groupbot, "MARKER", marker)
    monkeypatch.setattr(groupbot, "start_run", lambda jid, visible=None: started.append(jid))
    r = client.post("/api/group-jobs/ai", json={"message": "Nội dung đủ dài để AI viết lại nhé", "group_ids": [a, b], "post_now": True, "accept_risk": True,
                                                "link": "https://x.vn/bai/", "link_mode": "comment"}).json()
    assert r["posting"] is True and started == [r["id"]] and "BÌNH LUẬN" in seen[-1]       # chế độ bình luận: AI mời xem link ở bình luận


def test_ai_needs_gemini_key(client, monkeypatch):
    a = _groups(client, ("A", "111", 0))[0]
    newsagent.save_config({"gemini_key": ""})
    cfg = newsagent.get_config()
    monkeypatch.setattr(newsagent, "get_config", lambda: dict(cfg, gemini_key=""))
    r = client.post("/api/group-jobs/ai", json={"message": "Nội dung đủ dài để AI viết lại nhé", "group_ids": [a]})
    assert r.status_code == 400 and "Gemini key" in r.json()["detail"]


def test_group_tab_has_ai_button_and_image_upload():
    html = TestClient(server.app).get("/").text
    assert "gjAi(true)" in html and "✨ AI viết bài &amp; đăng lên nhóm" in html and "gjUpload(this)" in html
    assert "/api/group-jobs/ai" in html


def test_link_goes_into_the_post_and_ai_calls_to_download_and_try(client, monkeypatch):
    a, b = _groups(client, ("A", "111", 5000), ("B", "222", 100))
    newsagent.save_config({"gemini_key": "k"})
    seen = []

    def fake(prompt, cfg):
        seen.append(prompt)
        return {"posts": [{"n": k, "text": f"Phiên bản {k}: phần mềm giúp kế toán xuất hóa đơn nhanh gấp 5 lần, đỡ sai sót. "
                                           f"Lời kêu gọi khác số {k * 13}: tải về dùng thử ngay tại link bên dưới nhé!"} for k in range(2)]}
    monkeypatch.setattr(newsagent, "gemini_json", fake)
    r = client.post("/api/group-jobs/ai", json={"message": "Phần mềm quản lý hóa đơn điện tử đa công ty, tải hóa đơn hàng loạt, miễn phí dùng thử 30 ngày.",
                                                "link": "https://dailythuehungphuc.com/phan-mem/", "group_ids": [a, b]})
    assert r.status_code == 200
    p = seen[0]
    assert "MỤC TIÊU CỦA BÀI: KÊU GỌI NGƯỜI XEM TẢI VÀ DÙNG THỬ PHẦN MỀM" in p and "LINK BÊN DƯỚI" in p
    assert "BÌNH LUẬN" not in p                                                       # mặc định gắn link vào bài, không bình luận
    job = client.get("/api/group-jobs").json()[0]
    assert job["link_mode"] == "post" and job["link"] == "https://dailythuehungphuc.com/phan-mem/"
    seen.clear()
    client.post("/api/group-jobs/ai", json={"message": "Phần mềm quản lý hóa đơn điện tử đa công ty, miễn phí dùng thử.", "link": "https://x.vn/",
                                            "link_mode": "comment", "goal": "share", "group_ids": [a]})
    assert "BÌNH LUẬN" in seen[0] and "CHIA SẺ KIẾN THỨC" in seen[0]
    assert client.get("/api/group-jobs").json()[0]["link_mode"] == "comment"


def test_bot_appends_link_to_the_post_in_post_mode(client, monkeypatch, tmp_path):
    import contextlib
    import sys
    import types
    a = _groups(client, ("A", "111", 100))[0]
    jid = db.add_group_job("chung", "https://x.vn/tai/", db.now(), [a], variants={a: "bài riêng cho A"}, link_mode="post")
    posted, comments = [], []

    class Page:
        url = ""
        def goto(self, url, **k): self.url = url
        def wait_for_timeout(self, ms): pass
        def screenshot(self, **k): pass

    class Ctx:
        pages = [Page()]
        def close(self): pass
    mod = types.ModuleType("playwright.sync_api")
    mod.sync_playwright = lambda: contextlib.nullcontext(object())
    monkeypatch.setitem(sys.modules, "playwright.sync_api", mod)
    monkeypatch.setattr(groupbot, "_launch", lambda p, visible: Ctx())
    monkeypatch.setattr(groupbot, "post_to_open_group", lambda page, text, timeout=0, images=None: posted.append(text) or "ok")
    monkeypatch.setattr(groupbot, "comment_under_post", lambda *a, **k: comments.append(a))
    monkeypatch.setattr(groupbot, "MARKER", tmp_path / "logged")
    (tmp_path / "logged").write_text("1")
    monkeypatch.setattr(groupbot, "_sleep", lambda s: None)
    groupbot._run_job(jid)
    assert posted == ["bài riêng cho A\n\nhttps://x.vn/tai/"] and comments == []        # link ở cuối bài, không bình luận
    with __import__("pytest").raises(groupbot.GroupBotError, match="đã nằm trong bài"):
        groupbot._comment_job(jid)
