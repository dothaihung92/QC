import pytest
from fastapi.testclient import TestClient

from app import backlinks as B
from app import db, server

SITE = {"url": "https://ketoanhp.vn", "brand": "Kế toán Hưng Phúc", "city": "Hà Nội", "weekly_target": 4,
        "keywords": "dịch vụ kế toán trọn gói | https://ketoanhp.vn/dich-vu-ke-toan\nquyết toán thuế",
        "competitors": "ketoandoithu.vn", "email": "a@ketoanhp.vn"}

GOOD = """<html lang="vi"><head><title>Tổng hợp hướng dẫn kế toán thuế cho doanh nghiệp</title>
<meta name="description" content="kế toán thuế"></head><body>
<h1>Kế toán thuế hóa đơn doanh nghiệp</h1><p>""" + "Hướng dẫn quyết toán thuế, báo cáo tài chính, hóa đơn cho doanh nghiệp nhỏ. " * 60 + """</p>
<a href="https://www.ketoanhp.vn/dich-vu-ke-toan" rel="nofollow">Kế toán Hưng Phúc</a>
<a href="/lien-he">Liên hệ</a> <a href="mailto:ban-bien-tap@blog.vn">email</a>
<a href="https://ketoanhp.vn/"><img src="x.png" alt="logo"></a>
<p>Bạn có thể viết bài cho chúng tôi (guest post).</p></body></html>"""


@pytest.fixture(autouse=True)
def site():
    B.save_site(SITE)


@pytest.fixture
def client():
    return TestClient(server.app)


def fake_fetch(pages):
    def f(url, timeout=15, limit=0):
        if url not in pages:
            raise B.FetchError("Không mở được trang")
        st, body = pages[url] if isinstance(pages[url], tuple) else (200, pages[url])
        return st, url, body
    return f


def test_parse_page_finds_my_links_with_rel_and_anchor():
    a = B.parse_page(GOOD, "https://blog.vn/bai", B.get_site())
    links = a["links_to_me"]
    assert [(x["rel"], x["anchor"]) for x in links] == [("nofollow", "Kế toán Hưng Phúc"), ("dofollow", "[ảnh] logo")]
    assert links[1]["image"] and a["emails"] == ["ban-bien-tap@blog.vn"] and a["guest"] and a["mentions_brand"]
    assert not a["noindex"] and a["topic_hits"] >= 6


def test_quality_rejects_spam_noindex_and_offtopic_but_likes_relevant_pages():
    q = B.quality(B.parse_page(GOOD, "https://blog.vn/bai", B.get_site()))
    assert q["tier"] == "A" and q["score"] >= 70 and not q["reject"]
    spam = B.quality(B.parse_page("<title>Nhà cái cá độ casino</title><p>kế toán</p>", "http://x.vn/", B.get_site()))
    assert spam["reject"] and spam["tier"] == "C" and any("spam" in f for f in spam["flags"])
    noidx = B.quality(B.parse_page('<meta name="robots" content="noindex,follow"><title>Kế toán thuế</title>', "https://x.vn/", B.get_site()))
    assert noidx["reject"] and any("noindex" in f for f in noidx["flags"])
    assert B.quality(B.parse_page("<title>Du lịch Đà Lạt</title><p>cà phê</p>", "https://x.vn/", B.get_site()))["reject"]


def test_fetch_page_refuses_internal_addresses():
    for u in ("http://127.0.0.1:8787/", "http://localhost/admin", "http://192.168.1.1/", "ftp://x.vn/a", "http://169.254.169.254/"):
        with pytest.raises(B.FetchError):
            B.fetch_page(u)


def test_check_link_states(monkeypatch):
    pages = {"https://blog.vn/a": GOOD, "https://blog.vn/b": "<title>Kế toán</title><p>Kế toán Hưng Phúc nhưng chưa có link</p>",
             "https://blog.vn/c": (404, "x"), "https://blog.vn/d": '<meta name="robots" content="noindex"><a href="https://ketoanhp.vn/">x</a>'}
    monkeypatch.setattr(B, "fetch_page", fake_fetch(pages))
    ok = B.check_link("https://blog.vn/a", "https://ketoanhp.vn/dich-vu-ke-toan")
    assert ok["state"] == "ok" and ok["rel"] == "nofollow" and ok["anchor"] == "Kế toán Hưng Phúc"        # ưu tiên link khớp trang đích
    nf = B.check_link("https://blog.vn/b")
    assert nf["state"] == "not_found" and nf["mentions_brand"]
    assert B.check_link("https://blog.vn/c")["state"] == "error"
    assert B.check_link("https://blog.vn/zzz")["state"] == "error"
    assert B.check_link("https://blog.vn/d")["state"] == "noindex"


def test_classify_anchor_types():
    s = B.get_site()
    c = lambda a, **k: B.classify_anchor(a, s, **k)  # noqa: E731
    assert c("Kế toán Hưng Phúc") == "brand" and c("ketoanhp.vn") == "naked" and c("https://ketoanhp.vn/") == "naked"
    assert c("dịch vụ kế toán trọn gói") == "exact" and c("dịch vụ kế toán trọn gói giá rẻ cho công ty") == "partial"
    assert c("xem thêm") == "generic" and c("", image=True) == "image" and c("quyết toán thuế cuối năm") == "partial"


def test_add_update_flow_followups_and_validation():
    with pytest.raises(ValueError):
        B.add_row({"page_url": "https://www.ketoanhp.vn/blog"})                       # chính website của mình
    with pytest.raises(ValueError):
        B.add_row({})
    r = B.add_row({"page_url": "https://blog.vn/viet-bai", "kind": "guest", "score": 80, "tier": "A", "contact": "x@blog.vn"})
    assert r["status"] == "idea" and r["domain"] == "blog.vn" and r["target_url"] == "https://ketoanhp.vn"
    with pytest.raises(ValueError):
        B.add_row({"page_url": "https://blog.vn/viet-bai"})                           # trùng
    r = B.update_row(r["id"], {"status": "contacted"})
    assert r["followup_at"] and abs(r["followup_at"] - db.now() - 5 * 86400) < 5 and "→ Đã liên hệ" in r["history"][-1]["text"]
    r = B.update_row(r["id"], {"status": "live", "anchor": "Kế toán Hưng Phúc", "rel": "dofollow"})
    assert r["live_since"] and r["followup_at"] is None and r["anchor_type"] == "brand"
    assert B.delete_row(r["id"]) and not B.delete_row(r["id"])


def test_verify_row_goes_live_then_lost_then_error_needs_twice(monkeypatch):
    pages = {"https://blog.vn/a": GOOD}
    monkeypatch.setattr(B, "fetch_page", fake_fetch(pages))
    r = B.add_row({"page_url": "https://blog.vn/a", "kind": "guest", "status": "published"})
    out = B.verify_row(r["id"])["row"]
    assert out["status"] == "live" and out["last_result"] == "ok" and out["rel"] == "dofollow" and out["anchor"] == "[ảnh] logo"
    pages["https://blog.vn/a"] = "<p>đã xóa link</p>"
    out = B.verify_row(r["id"])["row"]
    assert out["status"] == "lost" and "MẤT LINK" in out["history"][-1]["text"]
    assert any(a["kind"] == "backlink" for a in db.recent_activity(5)) if hasattr(db, "recent_activity") else True
    r2 = B.add_row({"page_url": "https://blog.vn/e", "status": "live"})
    del pages["https://blog.vn/a"]
    assert B.verify_row(r2["id"])["row"]["status"] == "live"                          # lỗi 1 lần → chưa kết luận mất
    assert B.verify_row(r2["id"])["row"]["status"] == "lost"                          # lỗi 2 lần liên tiếp → mất


def test_recheck_all_and_due(monkeypatch):
    monkeypatch.setattr(B, "fetch_page", fake_fetch({"https://blog.vn/a": GOOD, "https://blog.vn/b": "<p>hết link</p>"}))
    a = B.add_row({"page_url": "https://blog.vn/a", "status": "live"})
    b = B.add_row({"page_url": "https://blog.vn/b", "status": "live"})
    B.add_row({"page_url": "https://blog.vn/c", "status": "idea"})
    assert B.due()
    res = B.recheck_all()
    assert res["checked"] == 2 and res["ok"] == 1 and res["lost"] == [{"id": b["id"], "domain": "blog.vn"}]
    assert B.get_row(a["id"])["last_result"] == "ok" and not B.due()
    B.save_site({"auto_check": False})
    db.set_setting("backlink_try_at", 0)
    assert not B.due()


def test_anchor_report_warns_on_exact_match_and_suggests_next():
    rows = [{"status": "live", "anchor_type": "exact"}] * 4 + [{"status": "live", "anchor_type": "brand"}] * 2 + [{"status": "idea", "anchor_type": "exact"}]
    rep = B.anchor_report(rows)
    assert rep["total"] == 6 and rep["percent"]["exact"] == 67 and any("Từ khóa chính xác" in w for w in rep["warnings"])
    nxt = B.next_anchor(rows=rows)
    assert nxt["type"] in ("naked", "partial", "generic", "brand") and nxt["type"] != "exact" and nxt["examples"]
    assert B.next_anchor(rows=[])["type"] == "brand" and B.next_anchor(rows=[])["examples"] == ["Kế toán Hưng Phúc"]


def test_plan_lists_due_followups_unverified_and_lost():
    now = db.now()
    r1 = B.add_row({"page_url": "https://a.vn/1", "status": "contacted", "followup_at": now - 10})
    r2 = B.add_row({"page_url": "https://b.vn/1", "status": "published"})
    r3 = B.add_row({"page_url": "https://c.vn/1", "status": "lost"})
    kinds = {(t["kind"], t.get("id")) for t in B.plan()}
    assert ("followup", r1["id"]) in kinds and ("verify", r2["id"]) in kinds and ("recover", r3["id"]) in kinds
    assert any(t["kind"] == "outreach" for t in B.plan()) and any(t["kind"] == "profiles" for t in B.plan())
    B.save_site({"brand": ""})
    assert B.plan()[0]["kind"] == "setup"


def test_opportunities_fill_queries_and_skip_unusable():
    items = {o["id"]: o for o in B.opportunities()}
    mention = [q["q"] for q in items["mention"]["queries"]]
    assert '"Kế toán Hưng Phúc" -site:ketoanhp.vn' in mention and all("google.com/search?q=" in q["google"] for q in items["mention"]["queries"])
    assert '"ketoandoithu.vn" -site:ketoandoithu.vn' in [q["q"] for q in items["competitor"]["queries"]]
    B.save_site({"competitors": "", "brand": ""})
    items = {o["id"]: o for o in B.opportunities()}
    assert items["competitor"]["queries"] == [] and items["mention"]["queries"] == []
    assert not any("{" in q["q"] for o in items.values() for q in o["queries"])


def test_discover_scores_filters_and_skips_own_social_and_dead(monkeypatch):
    monkeypatch.setattr(B, "search", lambda q: [("https://blog.vn/viet-bai", "Viết bài"), ("https://ketoanhp.vn/x", "mình"),
                                                ("https://facebook.com/y", "fb"), ("https://spam.vn/", "spam"), ("https://dead.vn/", "chết"),
                                                ("https://blog.vn/trang-khac", "cùng miền")])
    monkeypatch.setattr(B, "fetch_page", fake_fetch({"https://blog.vn/viet-bai": GOOD, "https://spam.vn/": "<title>Nhà cái casino kế toán</title>"}))
    B.add_row({"page_url": "https://old.vn/a"})
    res = B.discover("guest")
    assert [c["domain"] for c in res["candidates"]] == ["blog.vn", "spam.vn"]       # tên miền trùng chỉ giữ 1, link của mình/fb/trang chết bị bỏ
    assert res["candidates"][0]["tier"] == "A" and res["candidates"][0]["emails"] and res["candidates"][1]["reject"]
    with pytest.raises(ValueError):
        B.discover("profiles")                                                         # không có câu tìm tự động
    with pytest.raises(ValueError):
        B.discover("")


def test_broken_links_reports_only_dead_external_links(monkeypatch):
    page = '<title>Tài nguyên</title><a href="https://dead.vn/a">Bài cũ</a><a href="https://ok.vn/a">Ổn</a><a href="https://blog.vn/noi-bo">nội bộ</a>' \
           '<a href="https://facebook.com/x">fb</a><a href="https://blocked.vn/">chặn robot</a>'
    monkeypatch.setattr(B, "fetch_page", fake_fetch({"https://blog.vn/tai-nguyen": page}))
    monkeypatch.setattr(B, "_alive", lambda u: {"https://dead.vn/a": "dead", "https://blocked.vn/": "unknown"}.get(u, "ok"))
    r = B.broken_links("https://blog.vn/tai-nguyen")
    assert r["ok"] and r["checked"] == 3 and r["dead"] == [{"url": "https://dead.vn/a", "anchor": "Bài cũ"}]
    assert not B.broken_links("https://blog.vn/none")["ok"]


def test_generate_guest_article_keeps_only_target_link(monkeypatch):
    from app import newsagent
    seen = {}
    monkeypatch.setattr(newsagent, "gemini_json", lambda prompt, cfg: seen.update(p=prompt) or {
        "title": "T", "body": '<p>a <a href="https://ketoanhp.vn/dich-vu-ke-toan">dịch vụ kế toán trọn gói</a> và <a href="https://spam.vn/x">link lạ</a></p>',
        "author_bio": "<b>Tác giả</b> A"})
    r = B.add_row({"page_url": "https://blog.vn/a", "target_url": "https://ketoanhp.vn/dich-vu-ke-toan", "anchor": "dịch vụ kế toán trọn gói"})
    out = B.generate("guest_article", r["id"], {"topic": "Quyết toán cuối năm"})
    assert "spam.vn" not in out["body"] and "link lạ" in out["body"] and out["has_link"] and out["author_bio"] == "Tác giả A"
    assert "KHÔNG bịa" in seen["p"] and "Quyết toán cuối năm" in seen["p"] and "https://ketoanhp.vn/dich-vu-ke-toan" in seen["p"]
    with pytest.raises(ValueError):
        B.generate("xyz")
    monkeypatch.setattr(newsagent, "gemini_json", lambda p, c: {"subject": "S", "body": "B"})
    assert B.generate("pitch_guest", r["id"])["subject"] == "S"


def test_api_end_to_end(client, monkeypatch):
    from app import newsagent
    assert client.put("/api/backlinks/site", json={"brand": "HP", "weekly_target": 99, "url": "hp.vn"}).json()["url"] == "https://hp.vn"
    assert client.get("/api/backlinks/site").json()["weekly_target"] == 50
    items = client.get("/api/backlinks/opportunities").json()
    assert len(items["items"]) >= 10 and items["avoid"] and "guest_article" in items["ai"]
    monkeypatch.setattr(B, "fetch_page", fake_fetch({"https://blog.vn/a": GOOD}))
    r = client.post("/api/backlinks", json={"page_url": "https://blog.vn/a", "kind": "guest", "contact": "e@blog.vn"})
    assert r.status_code == 200
    bid = r.json()["id"]
    assert client.post("/api/backlinks", json={"page_url": "https://hp.vn/x"}).status_code == 400
    assert client.put(f"/api/backlinks/{bid}", json={"status": "published", "target_url": "https://hp.vn"}).json()["status"] == "published"
    assert client.post(f"/api/backlinks/{bid}/check").json()["row"]["last_result"] == "not_found"          # GOOD chỉ link về ketoanhp.vn
    assert client.post("/api/backlinks/9999/check").status_code == 404
    rep = client.get("/api/backlinks-report").json()
    assert rep["total"] == 1 and rep["counts"]["published"] == 1 and rep["plan"]
    assert client.get("/api/backlinks?status=published").json()["items"][0]["id"] == bid
    assert client.get("/api/backlinks?status=live").json()["items"] == []
    csv = client.get("/api/backlinks-export.csv")
    assert csv.status_code == 200 and "blog.vn" in csv.text and "attachment" in csv.headers["content-disposition"]
    a = client.post("/api/backlinks/analyze", json={"url": "blog.vn/a"}).json()
    assert a["ok"] and a["tier"] in "ABC"
    monkeypatch.setattr(newsagent, "gemini_json", lambda p, c: {"subject": "Chào bạn", "body": "Nội dung"})
    ai = client.post("/api/backlinks-ai", json={"kind": "pitch_guest", "id": bid}).json()
    assert ai["subject"] == "Chào bạn" and ai["mailto"].startswith("mailto:e@blog.vn?subject=")
    assert client.post("/api/backlinks-ai", json={"kind": "bogus"}).status_code == 400
    assert client.delete(f"/api/backlinks/{bid}").json() == {"ok": True} and client.delete(f"/api/backlinks/{bid}").status_code == 404


def test_ui_has_backlink_tab(client):
    html = client.get("/").text
    assert 'data-s="backlink"' in html and "function loadBacklink" in html and "/api/backlinks-report" in html
