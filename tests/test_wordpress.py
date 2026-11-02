import json

from fastapi.testclient import TestClient

from app import newsagent, server, wordpress


class R:
    def __init__(self, status=200, body=None, ctype="application/json", url="https://site.vn/wp-json/wp/v2/users/me", text=None):
        self.status_code, self.url = status, url
        self.headers = {"Content-Type": ctype}
        self.content = (text if text is not None else json.dumps(body or {})).encode()

    def json(self):
        return json.loads(self.content)


def test_site_root_strips_admin_paths():
    assert wordpress.site_root("https://dailythuehungphuc.com/wp-admin/") == "https://dailythuehungphuc.com"
    assert wordpress.site_root("dailythuehungphuc.com") == "https://dailythuehungphuc.com"
    assert wordpress.site_root("https://x.vn/blog/wp-login.php?redirect=1") == "https://x.vn/blog"
    assert wordpress.fix_rest_url("https://x.vn/wp-admin//wp-json/wp/v2/posts") == "https://x.vn/wp-json/wp/v2/posts"
    assert newsagent.save_config({"wp_url": "https://x.vn/wp-admin/"}) and newsagent.get_config()["wp_url"] == "https://x.vn"


def test_proxy_forwards_auth_and_explains_errors(monkeypatch):
    seen = []

    def req(method, url, headers=None, data=None, **k):
        seen.append((method, url, headers, data))
        if url.endswith("/users/me"):
            if "Authorization" not in {h.title() for h in headers}:
                return R(401, {"code": "rest_not_logged_in", "message": "You are not currently logged in."})
            return R(200, {"id": 1, "name": "Hưng Phúc"})
        if url.endswith("/media"):
            return R(201, {"id": 9, "source_url": "https://x.vn/a.jpg"})
        return R(200, text="<html>login</html>", ctype="text/html", url="https://x.vn/wp-login.php")
    monkeypatch.setattr(wordpress.requests, "request", req)
    c = TestClient(server.app)
    r = c.get("/api/wp-proxy", params={"url": "https://x.vn/wp-admin//wp-json/wp/v2/users/me"},
              headers={"X-WP-Authorization": "Basic abc"})
    assert r.status_code == 200 and r.json()["id"] == 1
    assert seen[-1][1] == "https://x.vn/wp-json/wp/v2/users/me" and seen[-1][2]["Authorization"] == "Basic abc"
    r = c.get("/api/wp-proxy", params={"url": "https://x.vn/wp-json/wp/v2/users/me"})
    assert r.status_code == 401 and "Authorization" in r.json()["message"]                 # có gợi ý tiếng Việt
    r = c.post("/api/wp-proxy", params={"url": "https://x.vn/wp-json/wp/v2/media"}, content=b"\x89PNG-bytes",
               headers={"X-WP-Authorization": "Basic abc", "Content-Type": "image/png", "Content-Disposition": 'attachment; filename="a.png"'})
    assert r.status_code == 201 and seen[-1][3] == b"\x89PNG-bytes" and seen[-1][2]["content-disposition"]
    r = c.get("/api/wp-proxy", params={"url": "https://x.vn/wp-json/wp/v2/posts"})
    assert r.status_code == 502 and "trang đăng nhập" in r.json()["message"]
    assert c.get("/api/wp-proxy", params={"url": "https://x.vn/secret"}).status_code == 400   # chỉ chuyển tiếp REST API


def test_bridge_routes_wordpress_calls_through_qc():
    c = TestClient(server.app)
    js = c.get("/qc-bridge.js").text
    assert "/api/wp-proxy?url=" in js and "fixWpUrl" in js and "X-WP-Authorization" in js
    assert "Mật khẩu ứng dụng" in c.get("/seo-writer").text
