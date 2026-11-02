import pytest
from fastapi.testclient import TestClient

from app import db, legallinks, newsagent, server

GOOD = "https://thuvienphapluat.vn/van-ban/Thue-Phi-Le-Phi/Nghi-dinh-398-2026-ND-CP-giam-thue-thu-nhap-612345.aspx"
WRONG_NO = "https://thuvienphapluat.vn/van-ban/Thue-Phi-Le-Phi/Nghi-dinh-1398-2026-ND-CP-khac-1.aspx"
DEAD = "https://luatvietnam.vn/thue/nghi-dinh-398-2026-nd-cp-404.html"
OTHER = "https://baomoi.com/nghi-dinh-398-2026-nd-cp.html"


class Resp:
    def __init__(self, status=200, text="", url=""):
        self.status_code, self.text, self.url, self.encoding = status, text, url, "utf-8"
        self.ok = status < 400


@pytest.fixture
def web(monkeypatch):
    """Giả lập công cụ tìm kiếm + các trang web (máy test không có Internet)."""
    calls = {"search": 0, "get": []}

    def bing(q):
        calls["search"] += 1
        if "398/2026" in q:
            return [(OTHER, "Báo"), (WRONG_NO, "Nghị định 1398/2026/NĐ-CP"), (DEAD, "Nghị định 398/2026/NĐ-CP"),
                    (GOOD, "Nghị định 398/2026/NĐ-CP giảm thuế")]
        return []

    def get(url, **k):
        calls["get"].append(url)
        if url == DEAD:
            return Resp(404, "", url)
        return Resp(200, "<title>Nghị định 398/2026/NĐ-CP giảm thuế</title>", url)

    monkeypatch.setattr(legallinks, "_tvpl", lambda q: [])
    monkeypatch.setattr(legallinks, "_ddg", lambda q: [])
    monkeypatch.setattr(legallinks, "_bing", bing)
    monkeypatch.setattr(legallinks.requests, "get", get)
    return calls


def test_find_refs_kinds_and_codes():
    text = ("Nghị định số 398/2026/NĐ-CP; khoản 2 Điều 8 Thông tư số 18/2026/TT-BTC ngày 05/3/2026; "
            "Luật Quản lý thuế số 108/2025/QH15; Công văn 3897/CT-CS; nhắc lại 398/2026/NĐ-CP; tỷ lệ 1/2.")
    refs = legallinks.find_refs(text)
    assert [r["code"] for r in refs] == ["398/2026/NĐ-CP", "18/2026/TT-BTC", "108/2025/QH15", "3897/CT-CS"]
    assert refs[0]["kind"] == "Nghị định" and refs[2]["kind"].startswith("Luật") and refs[3]["kind"] == "Công văn"
    assert legallinks.find_refs("Theo 40/2021/TT-BTC")[0]["kind"] == "Thông tư"       # suy ra từ số hiệu


def test_lookup_only_accepts_verified_trusted_link_and_caches(web):
    ref = legallinks.find_refs("Nghị định 398/2026/NĐ-CP")[0]
    res = legallinks.lookup(ref)
    assert res["url"] == GOOD                    # bỏ báo (không tin cậy), số hiệu khác (1398), link chết (404)
    assert OTHER not in web["get"] and WRONG_NO not in web["get"]
    n = web["search"]
    assert legallinks.lookup(ref)["url"] == GOOD and web["search"] == n          # lần sau lấy từ bộ nhớ
    miss = legallinks.lookup(legallinks.find_refs("Thông tư 99/2026/TT-BTC")[0])
    assert miss["url"] == "" and db.get_setting("legal:99/2026/TT-BTC")["url"] == ""


def test_verify_rejects_404_wrong_page_and_untrusted(monkeypatch):
    pages = {GOOD: Resp(200, "<title>Trang chủ</title>"), DEAD: Resp(404),
             "https://vanban.chinhphu.vn/?docid=1": Resp(200, "<title>Văn bản</title><p>Số: 398/2026/NĐ-CP</p>"),
             "https://vanban.chinhphu.vn/?docid=2": Resp(200, "<title>Văn bản</title><p>Số: 12/2026/NĐ-CP</p>"),
             "https://thuvienphapluat.vn/van-ban/x-1.aspx": Resp(403)}
    monkeypatch.setattr(legallinks.requests, "get", lambda u, **k: pages[u])
    code = "398/2026/NĐ-CP"
    assert legallinks.verify(GOOD, code)                                  # đúng số hiệu trong địa chỉ
    assert not legallinks.verify(DEAD, code)
    assert legallinks.verify("https://vanban.chinhphu.vn/?docid=1", code)
    assert not legallinks.verify("https://vanban.chinhphu.vn/?docid=2", code)
    assert not legallinks.verify("https://thuvienphapluat.vn/van-ban/x-1.aspx", code)   # bị chặn + địa chỉ không khớp
    assert not legallinks.verify(OTHER, code)


def test_link_markdown_and_html_first_mention_only():
    refs = [{"text": "Nghị định số 398/2026/NĐ-CP", "code": "398/2026/NĐ-CP", "kind": "Nghị định", "url": GOOD},
            {"text": "Thông tư 18/2026/TT-BTC", "code": "18/2026/TT-BTC", "kind": "Thông tư", "url": ""}]
    body = "## Nghị định 398/2026/NĐ-CP là gì\n\nChính phủ ban hành Nghị định số 398/2026/NĐ-CP.\n\nNhắc lại 398/2026/NĐ-CP."
    out = legallinks.link_markdown(body, refs)
    assert out.count(f"]({GOOD})") == 2                                          # 1 lần trong bài + mục cuối
    assert "## Nghị định 398/2026/NĐ-CP là gì" in out                             # không gắn trong tiêu đề
    assert f"[Nghị định số 398/2026/NĐ-CP]({GOOD})" in out and "## Văn bản pháp luật liên quan" in out
    assert legallinks.link_markdown(out, refs) == out                             # chạy lại không gắn thêm
    parts = ["<h2>Nghị định 398/2026/NĐ-CP</h2><p>Theo <strong>Nghị định 398/2026/NĐ-CP</strong> thì…</p>",
             "<p>Lại nhắc Nghị định 398/2026/NĐ-CP.</p>"]
    res = legallinks.link_html(parts, refs)
    assert res[0].count("<a ") == 1 and f'<strong><a href="{GOOD}"' in res[0] and "<h2>Nghị định 398" in res[0]
    assert res[1] == parts[1]
    assert legallinks.link_html(res, refs) == res
    assert "📄 Xem văn bản gốc" in legallinks.fb_footer("Tin thuế", refs)


def test_news_article_gets_verified_links_on_web_and_facebook(web, monkeypatch):
    newsagent.save_config({"gemini_key": "k"})
    ai = {"relevant": True, "title": "Giảm 30% thuế", "summary": "s", "fb_text": "Tin vui 🎉",
          "body": "Chính phủ ban hành **Nghị định số 398/2026/NĐ-CP**.\n\n* Doanh thu dưới 10 tỷ\n* Áp dụng 2026"}
    monkeypatch.setattr(newsagent, "fetch_article", lambda u: {"url": u, "title": "t", "image": "", "text": "x" * 400})
    monkeypatch.setattr(newsagent, "gemini_json", lambda p, c: ai)
    item_id = newsagent.process_url({"title": "t", "url": "https://bao.vn/a"}, newsagent.get_config())
    item = db.news_get(item_id)
    assert f"]({GOOD})" in item["body"] and GOOD in item["fb_text"]
    page = newsagent.body_to_html(item["body"])
    assert f'<a href="{GOOD}" target="_blank" rel="noopener">' in page
    assert "<ul><li>Doanh thu dưới 10 tỷ</li>" in page and "<strong>" in page
    newsagent.save_config({"legal_links": False})
    assert newsagent.add_legal_links(item, newsagent.get_config()) == {}


def test_legal_links_endpoint(web):
    c = TestClient(server.app)
    r = c.post("/api/legal/links", json={"parts": ["<p>Theo Nghị định 398/2026/NĐ-CP.</p>", "<p>Hết.</p>"]})
    d = r.json()
    assert r.status_code == 200 and GOOD in d["parts"][0] and d["parts"][1] == "<p>Hết.</p>"
    assert d["refs"][0]["code"] == "398/2026/NĐ-CP"
    assert "qcLinkLegalDocs" in c.get("/qc-bridge.js").text
