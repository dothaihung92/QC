import pytest
from fastapi.testclient import TestClient

from app import db, facebook, newsagent, server

RSS = """<?xml version="1.0"?><rss><channel>
<item><title>Thuế mới từ 1/7</title>
<link>http://www.bing.com/news/apiclick.aspx?ref=x&amp;url=https%3a%2f%2fbao.vn%2fthue-moi&amp;c=1</link>
<source>Báo A</source><pubDate>Mon, 26 Oct 2026 10:00:00 GMT</pubDate></item>
<item><title>Tin cũ</title><link>https://bao.vn/cu</link><pubDate>Mon, 01 Jan 2024 10:00:00 GMT</pubDate></item>
</channel></rss>"""

HTML = ("<html><head><meta property='og:image' content='https://bao.vn/a.jpg'>"
        "<meta property='og:title' content='Thuế mới'></head><body><nav><p>" + "menu " * 30 + "</p></nav>"
        "<p>" + "Nội dung bài viết về thuế GTGT mới. " * 12 + "</p></body></html>")

AI = {"relevant": True, "title": "Thuế GTGT mới: DN cần biết", "summary": "tóm tắt",
      "body": "Đoạn 1\n\n## Cần làm gì\n\nĐoạn 2 <script>", "fb_text": "Tin thuế mới 📢 #thue"}


@pytest.fixture
def client():
    return TestClient(server.app)


def test_parse_feed_extracts_real_url_and_date():
    items = newsagent.parse_feed(RSS)
    assert items[0]["url"] == "https://bao.vn/thue-moi" and items[0]["source"] == "Báo A"
    assert items[0]["published"] > 0 and len(items) == 2


def test_fetch_article_extracts_text_and_image(monkeypatch):
    class R:
        text, url, encoding = HTML, "https://bao.vn/thue-moi", "utf-8"
        def raise_for_status(self): pass
    monkeypatch.setattr(newsagent.requests, "get", lambda *a, **k: R())
    art = newsagent.fetch_article("https://bao.vn/thue-moi")
    assert art["image"] == "https://bao.vn/a.jpg" and "menu" not in art["text"] and "thuế GTGT" in art["text"]


def test_run_publish_flow_and_blog_escapes_html(monkeypatch, client, fb_calls):
    newsagent.save_config({"gemini_key": "k", "public_url": "https://site.vn"})
    monkeypatch.setattr(newsagent, "search", lambda *a, **k: [
        {"title": "Thuế mới", "url": "https://bao.vn/thue-moi", "source": "Báo A", "published": 0}])
    monkeypatch.setattr(newsagent, "fetch_article", lambda u: {
        "url": u, "title": "t", "image": "https://bao.vn/a.jpg", "text": "x" * 400})
    monkeypatch.setattr(newsagent, "gemini_json", lambda p, cfg: AI)
    published = []
    monkeypatch.setattr(facebook, "publish_post", lambda m, l="", i="": published.append((m, l, i)) or "fb1")

    assert newsagent.run_once() == {"found": 1, "written": 1}
    item = db.news_list()[0]
    assert item["status"] == "pending" and item["image_url"] == "https://bao.vn/a.jpg"
    assert newsagent.run_once()["found"] == 0                      # không viết lại bài đã có

    r = client.post(f"/api/news/{item['id']}/publish").json()
    assert r["status"] == "published" and r["fb_post_id"] == "fb1"
    assert published[0][1].startswith("https://site.vn/tin-tuc/")
    page = client.get(f"/tin-tuc/{r['slug']}").text
    assert "<h2>Cần làm gì</h2>" in page and "<script>" not in page and "Nguồn tham khảo" in page
    assert r["slug"] in client.get("/tin-tuc").text


def test_irrelevant_article_is_skipped_and_key_is_masked(monkeypatch):
    cfg = newsagent.save_config({"gemini_key": "secret"})
    assert cfg["gemini_key"] == "" and cfg["has_gemini_key"]
    newsagent.save_config({"gemini_key": ""})                      # để trống = giữ cũ
    assert newsagent.get_config()["gemini_key"] == "secret"
    monkeypatch.setattr(newsagent, "fetch_article", lambda u: {"url": u, "title": "", "image": "", "text": "x" * 400})
    monkeypatch.setattr(newsagent, "gemini_json", lambda p, c: {**AI, "relevant": False})
    newsagent.process_url({"title": "Bóng đá", "url": "https://bao.vn/bd"}, newsagent.get_config())
    assert db.news_list()[0]["status"] == "skipped"


def test_page_links_fallback_for_pages_without_rss():
    page = ('<a href="/a/1">Thông tư mới hướng dẫn thuế thu nhập cá nhân 2026</a>'
            '<a href="/menu">Trang chủ</a><a href="https://other.vn/x">Một bài viết ở website khác rất dài</a>'
            '<a href="/a/1">Thông tư mới hướng dẫn thuế thu nhập cá nhân 2026</a>')
    items = newsagent.parse_page_links(page, "https://www.gdt.gov.vn/tin")
    assert [i["url"] for i in items] == ["https://www.gdt.gov.vn/a/1"]


def test_page_links_use_date_after_link_and_drop_undated_menu_items():
    page = ('<a href="/menu/ung-dung">Ứng dụng hỗ trợ người nộp thuế cho doanh nghiệp</a>'
            '<div><a href="/a/1">Nghị định mới về chi phí y tế được giảm trừ thuế</a><br>'
            '<span>Ngày 30/10/2026</span></div>')
    items = newsagent.parse_page_links(page, "https://www.gdt.gov.vn/tin")
    assert len(items) == 1 and items[0]["url"].endswith("/a/1") and items[0]["published"] > 0


def test_fetch_article_falls_back_to_div_text(monkeypatch):
    long = "Nội dung chi tiết của thông báo về chính sách thuế mới áp dụng cho hộ kinh doanh. " * 5
    class R:
        text, url, encoding = f"<html><body><div>{long}</div></body></html>", "https://x.vn/a", "utf-8"
        def raise_for_status(self): pass
    monkeypatch.setattr(newsagent.requests, "get", lambda *a, **k: R())
    assert "hộ kinh doanh" in newsagent.fetch_article("https://x.vn/a")["text"]


def test_search_returns_newest_first_and_drops_old(monkeypatch):
    import time as _t
    now = _t.time()
    def fake_get(url, timeout=20):
        class R:
            url = "https://x.vn/f"
            text = ""
        return R()
    items = [{"title": "cũ", "url": "u1", "source": "", "published": int(now - 10 * 86400)},
             {"title": "hôm qua", "url": "u2", "source": "", "published": int(now - 86400)},
             {"title": "nay", "url": "u3", "source": "", "published": int(now - 600)}]
    monkeypatch.setattr(newsagent, "_get", fake_get)
    monkeypatch.setattr(newsagent, "parse_feed", lambda t: list(items))
    out = newsagent.search(["k"], [], 2)
    assert [i["url"] for i in out] == ["u3", "u2"]
