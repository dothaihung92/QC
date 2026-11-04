import json

from fastapi.testclient import TestClient

from app import newsagent, server, wordpress


class R:
    def __init__(self, status=200, body=None, ctype="application/json", url="https://site.vn/wp-json/wp/v2/users/me", text=None):
        self.status_code, self.url = status, url
        self.headers = {"Content-Type": ctype}
        self.content = (text if text is not None else json.dumps(body or {})).encode()
        self.text = self.content.decode()

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


class FakeSession:
    """Website WordPress giả: hosting bỏ header Authorization; đăng nhập wp-login.php bằng mật khẩu thường."""
    logins = []

    def __init__(self):
        import requests
        self.cookies = requests.cookies.RequestsCookieJar()
        self.headers = {}

    def get(self, url, params=None, **k):
        if url.endswith("/wp-login.php"):
            return R(200, text="<form id=loginform></form>", ctype="text/html", url=url)
        if "admin-ajax.php" in url:
            ok = any(c.name.startswith("wordpress_logged_in") for c in self.cookies)
            return R(200, text="a1b2c3d4e5" if ok else "0", ctype="text/html", url=url)
        raise AssertionError(url)

    def post(self, url, data=None, **k):
        FakeSession.logins.append(data["log"])
        if data["pwd"] == "MatKhau$Dang!Nhap":
            self.cookies.set("wordpress_logged_in_abc", "1")
            return R(200, text="<html>dashboard</html>", ctype="text/html", url=url)
        return R(200, text='<div id="login_error"><strong>Lỗi:</strong> Mật khẩu không đúng.</div>', ctype="text/html", url=url)

    def request(self, method, url, headers=None, data=None, **k):
        if headers.get("X-WP-Nonce") == "a1b2c3d4e5" and any(c.name.startswith("wordpress_logged_in") for c in self.cookies):
            return R(201 if method == "POST" else 200, {"id": 7, "name": "Đỗ Hưng", "link": "https://x.vn/bai"})
        return R(401, {"code": "rest_cookie_invalid_nonce", "message": "nonce"})


def test_falls_back_to_browser_style_login_when_auth_header_is_stripped(monkeypatch):
    monkeypatch.setattr(wordpress.requests, "request",
                        lambda *a, **k: R(401, {"code": "rest_not_logged_in", "message": "Bạn hiện chưa đăng nhập."}))
    monkeypatch.setattr(wordpress.requests, "Session", FakeSession)
    wordpress._sessions.clear()
    import base64
    auth = "Basic " + base64.b64encode("DOHUNG:MatKhau$Dang!Nhap".encode()).decode()
    c = TestClient(server.app)
    r = c.get("/api/wp-proxy", params={"url": "https://x.vn/wp-json/wp/v2/users/me"}, headers={"X-WP-Authorization": auth})
    assert r.status_code == 200 and r.json()["name"] == "Đỗ Hưng"
    n = len(FakeSession.logins)
    c.get("/api/wp-proxy", params={"url": "https://x.vn/wp-json/wp/v2/users/me"}, headers={"X-WP-Authorization": auth})
    assert len(FakeSession.logins) == n                                   # dùng lại phiên đã đăng nhập
    bad = "Basic " + base64.b64encode(b"DOHUNG:abcdABCDefgh1234ijkl5678").decode()     # trông như Mật khẩu ứng dụng
    r = c.get("/api/wp-proxy", params={"url": "https://x.vn/wp-json/wp/v2/users/me"}, headers={"X-WP-Authorization": bad})
    msg = r.json()["message"]
    assert r.status_code == 401 and ".htaccess" in msg and "MẬT KHẨU ĐĂNG NHẬP" in msg and "Mật khẩu không đúng" in msg
    # Tin tức AI đăng WordPress cũng dùng cơ chế này
    item = {"title": "T", "summary": "s", "body": "b", "image_url": "", "url": "", "source": ""}
    cfg = {"wp_url": "https://x.vn/wp-admin/", "wp_user": "DOHUNG", "wp_app_password": "MatKhau$Dang!Nhap"}
    assert newsagent.post_to_wordpress(item, cfg) == "https://x.vn/bai"


def test_post_without_auth_401_cannot_create_falls_back_but_real_403_does_not(monkeypatch):
    calls = []

    def req(method, url, headers=None, data=None, **k):
        calls.append(url)
        if url.endswith("/posts"):        # hosting bỏ header → WordPress coi như khách: 401 rest_cannot_create
            return R(401, {"code": "rest_cannot_create", "message": "Bạn không được phép tạo bài viết bằng tài khoản này."})
        if url.endswith("/pages"):        # đã đăng nhập nhưng thiếu quyền thật
            return R(403, {"code": "rest_cannot_create", "message": "no"})
        return R(401, {"code": "rest_not_logged_in", "message": "x"})
    monkeypatch.setattr(wordpress.requests, "request", req)
    monkeypatch.setattr(wordpress.requests, "Session", FakeSession)
    wordpress._sessions.clear()
    wordpress._cookie_sites.clear()
    import base64
    auth = {"X-WP-Authorization": "Basic " + base64.b64encode("hungphuc:MatKhau$Dang!Nhap".encode()).decode(),
            "Content-Type": "application/json"}
    st, _, body = wordpress.forward("POST", "https://y.vn/wp-json/wp/v2/posts", auth, b'{"title":"T"}')
    assert st == 201 and json.loads(body)["link"] == "https://x.vn/bai"
    n = len(calls)
    st, _, _ = wordpress.forward("POST", "https://y.vn/wp-json/wp/v2/posts", auth, b'{"title":"T2"}')
    assert st == 201 and len(calls) == n          # lần sau đi thẳng đăng nhập kiểu trình duyệt
    wordpress._cookie_sites.clear()
    st, _, body = wordpress.forward("POST", "https://z.vn/wp-json/wp/v2/pages",
                                    {"Content-Type": "application/json"}, b"{}")
    assert st == 403 and "Biên tập viên" in json.loads(body)["message"]
