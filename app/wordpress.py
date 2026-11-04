"""Kết nối WordPress: chuẩn hóa địa chỉ web và chuyển tiếp REST API (tránh lỗi CORS "Failed to fetch")."""
import base64
import hashlib
import html
import json
import re
import time
from urllib.parse import urlparse

import requests

UA = "Mozilla/5.0 (compatible; QC-SEO-Writer/1.0)"
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def site_root(url: str) -> str:
    """"dailythuehungphuc.com/wp-admin/" → "https://dailythuehungphuc.com" (bỏ /wp-admin, /wp-login.php, dấu / cuối)."""
    u = (url or "").strip()
    if not u:
        return ""
    if not re.match(r"^https?://", u, re.I):
        u = "https://" + u
    u = re.split(r"/(?:wp-admin|wp-login\.php|wp-json)(?:[/?#]|$)", u, maxsplit=1, flags=re.I)[0]
    return u.split("#")[0].split("?")[0].rstrip("/")


def fix_rest_url(url: str) -> str:
    """Sửa địa chỉ REST do người dùng nhập kèm /wp-admin: ".../wp-admin//wp-json/wp/v2/posts" → ".../wp-json/wp/v2/posts"."""
    m = re.search(r"/wp-json/", url)
    if not m:
        return url
    return site_root(url[:m.start()]) + url[m.start():]


HINTS = {
    "rest_not_logged_in": "Website không nhận được thông tin đăng nhập. Thường do hosting chặn header Authorization "
                          "hoặc plugin bảo mật — xem hướng dẫn trong tab Viết bài SEO.",
    "login_failed": "Kiểm tra lại Username và mật khẩu.",
    "incorrect_password": "Sai Mật khẩu ứng dụng (Application Password). Tạo lại trong WordPress: Thành viên → Hồ sơ → Mật khẩu ứng dụng.",
    "invalid_username": "Sai Username — dùng đúng tên đăng nhập WordPress (không phải tên hiển thị).",
    "invalid_email": "Sai email/Username đăng nhập WordPress.",
    "rest_forbidden": "Tài khoản không đủ quyền — cần vai trò Biên tập viên (Editor) hoặc Quản trị viên.",
    "rest_cannot_create": "Tài khoản không có quyền đăng bài — cần vai trò Biên tập viên (Editor) hoặc Quản trị viên.",
    "application_passwords_disabled": "Website đang tắt Mật khẩu ứng dụng (thường do plugin bảo mật như Wordfence/iThemes) — bật lại trong plugin đó.",
    "rest_no_route": "Website chưa bật REST API hoặc đường dẫn sai — kiểm tra Cài đặt → Đường dẫn tĩnh (chọn 'Tên bài viết') rồi Lưu.",
}


class LoginError(Exception):
    pass


_sessions = {}            # đăng nhập bằng cookie: khóa → (session, nonce, thời điểm)
SESSION_TTL = 6 * 3600
FALLBACK_CODES = ("rest_not_logged_in", "incorrect_password", "application_passwords_disabled",
                  "rest_forbidden_context", "invalid_application_credentials")


def _creds(auth: str):
    """"Basic base64(user:pass)" → (user, pass)."""
    m = re.match(r"\s*Basic\s+(\S+)", auth or "", re.I)
    if not m:
        return None
    try:
        user, _, pwd = base64.b64decode(m.group(1)).decode("utf-8").partition(":")
    except (ValueError, UnicodeDecodeError):
        return None
    return (user, pwd) if user and pwd else None


def _strip_tags(t: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t or ""))).strip()


def cookie_login(root: str, user: str, pwd: str, fresh: bool = False):
    """Đăng nhập như trình duyệt (wp-login.php) → (session, REST nonce). Dùng khi hosting chặn header
    Authorization hoặc người dùng nhập mật khẩu đăng nhập thay vì Mật khẩu ứng dụng."""
    key = hashlib.sha256(f"{root}|{user}|{pwd}".encode()).hexdigest()
    hit = _sessions.get(key)
    if hit and not fresh and time.time() - hit[2] < SESSION_TTL:
        return hit[0], hit[1]
    s = requests.Session()
    s.headers["User-Agent"] = BROWSER_UA
    login = f"{root}/wp-login.php"
    try:
        g = s.get(login, timeout=30)
    except requests.RequestException as e:
        raise LoginError(f"không mở được trang đăng nhập ({type(e).__name__})")
    if g.status_code == 404:
        raise LoginError("không tìm thấy trang wp-login.php (website đã đổi đường dẫn đăng nhập, vd plugin WPS Hide Login)")
    captcha = bool(re.search(r"g-recaptcha|cf-turnstile|h-captcha|hcaptcha", g.text or "", re.I))
    s.cookies.set("wordpress_test_cookie", "WP Cookie check")
    try:
        r = s.post(login, timeout=30, data={"log": user, "pwd": pwd, "rememberme": "forever", "wp-submit": "Log In",
                                             "redirect_to": f"{root}/wp-admin/", "testcookie": "1"})
    except requests.RequestException as e:
        raise LoginError(f"lỗi khi đăng nhập ({type(e).__name__})")
    if not any(c.name.startswith("wordpress_logged_in") for c in s.cookies):
        m = re.search(r'id="login_error"[^>]*>(.*?)</div>', r.text or "", re.S)
        why = _strip_tags(m.group(1)) if m else ""
        if captcha and not why:
            why = "trang đăng nhập có mã captcha nên phần mềm không tự đăng nhập được"
        raise LoginError(why or "WordPress không chấp nhận đăng nhập")
    try:
        n = s.get(f"{root}/wp-admin/admin-ajax.php", params={"action": "rest-nonce"}, timeout=30)
        nonce = (n.text or "").strip()
    except requests.RequestException:
        nonce = ""
    if not re.fullmatch(r"[0-9a-f]{6,20}", nonce):
        raise LoginError("đăng nhập được nhưng không lấy được mã REST (nonce)")
    _sessions[key] = (s, nonce, time.time())
    return s, nonce


_cookie_sites = set()     # (website|user) mà header Authorization không tới được WordPress


class _fake_401:
    status_code = 401
    url = ""
    headers = {"Content-Type": "application/json"}
    content = b'{"code": "rest_not_logged_in"}'

    def json(self):
        return {"code": "rest_not_logged_in"}


def _json(r):
    try:
        return r.json()
    except ValueError:
        return {}


def forward(method: str, url: str, headers: dict, body: bytes):
    """Gửi yêu cầu REST tới WordPress thay cho trình duyệt. Trả về (status, content_type, nội dung).
    Thử Mật khẩu ứng dụng (header Authorization) trước; website không nhận → tự đăng nhập như trình duyệt."""
    url = fix_rest_url(url)
    p = urlparse(url)
    if p.scheme not in ("http", "https") or "/wp-json/" not in p.path:
        return 400, "application/json", _err("bad_url", "Chỉ chuyển tiếp địa chỉ REST API WordPress (/wp-json/).")
    # Bảng điều khiển gửi đăng nhập WordPress trong "X-WP-Authorization" (header Authorization là của QC)
    keep = {k: v for k, v in headers.items() if k.lower() in ("content-type", "content-disposition", "accept")}
    wp_auth = next((v for k, v in headers.items() if k.lower() == "x-wp-authorization"), "")
    send = dict(keep, **({"Authorization": wp_auth} if wp_auth else {}))
    send["User-Agent"] = UA
    creds = _creds(wp_auth)
    root = site_root(url[:url.index("/wp-json/")])
    ckey = f"{root}|{creds[0]}" if creds else ""
    try:
        if ckey in _cookie_sites:                        # website này đã biết bỏ qua header → đăng nhập kiểu trình duyệt luôn
            r = _fake_401()
        else:
            r = requests.request(method, url, headers=send, data=body or None, timeout=120, allow_redirects=True)
    except requests.exceptions.SSLError:
        return 502, "application/json", _err("ssl", "Lỗi chứng chỉ HTTPS của website — kiểm tra SSL hoặc thử http://")
    except requests.RequestException as e:
        return 502, "application/json", _err("connect", f"Không kết nối được tới {p.netloc}: kiểm tra tên miền / mạng ({type(e).__name__}).")

    code = str(_json(r).get("code", "")) if r.status_code in (401, 403) else ""
    # 401 = WordPress coi như CHƯA đăng nhập (kể cả mã rest_cannot_create khi đăng bài / tải ảnh);
    # 403 = đã đăng nhập nhưng thiếu quyền thật → không thử lại.
    if creds and (r.status_code == 401 or code in FALLBACK_CODES):
        try:
            for fresh in (False, True):
                sess, nonce = cookie_login(root, creds[0], creds[1], fresh=fresh)
                r2 = sess.request(method, url, headers=dict(keep, **{"X-WP-Nonce": nonce}), data=body or None, timeout=120)
                if not (r2.status_code in (401, 403) and "nonce" in str(_json(r2).get("code", ""))):
                    break
            r = r2
            if r.status_code < 400:
                _cookie_sites.add(ckey)
        except LoginError as e:
            looks_app = bool(re.fullmatch(r"[A-Za-z0-9]{24}", creds[1].replace(" ", "")))
            msg = ("Không đăng nhập được WordPress. "
                   + ("Bạn đang nhập Mật khẩu ứng dụng nhưng website không nhận (hosting chặn header Authorization) — "
                      "thêm dòng SetEnvIf vào .htaccess (xem hướng dẫn), HOẶC nhập MẬT KHẨU ĐĂNG NHẬP WordPress của tài khoản này. "
                      if looks_app else
                      "Phần mềm đã thử cả Mật khẩu ứng dụng lẫn đăng nhập thường. ")
                   + f"Chi tiết: {e}")
            return 401, "application/json", _err(code or "login_failed", msg)

    ctype = r.headers.get("Content-Type", "")
    if "json" not in ctype.lower():
        login = "wp-login" in getattr(r, "url", "") or "wp-admin" in getattr(r, "url", "")
        return (r.status_code if r.status_code >= 400 else 502), "application/json", _err(
            "not_json", "Website trả về trang HTML thay vì REST API"
            + (" (bị chuyển tới trang đăng nhập)" if login else "")
            + f" — mã {r.status_code}. Kiểm tra: URL chỉ nhập tên miền (https://ten-mien.com), REST API không bị plugin bảo mật/Cloudflare chặn.")
    content = r.content
    if r.status_code >= 400:
        data = _json(r)
        hint = HINTS.get(str(data.get("code", ""))) if isinstance(data, dict) else None
        if r.status_code == 401 and str(data.get("code", "")).startswith("rest_cannot"):
            hint = HINTS["rest_not_logged_in"]                    # 401 = chưa đăng nhập, không phải thiếu quyền
        if hint:
            data["message"] = f"{data.get('message', '')} — {hint}".strip(" —").rstrip(".")
            content = json.dumps(data, ensure_ascii=False).encode()
    return r.status_code, ctype, content


def request(method: str, root: str, path: str, user: str, pwd: str, payload=None):
    """Dùng ở máy chủ (Tin tức AI → WordPress): cùng cơ chế đăng nhập như trên. Trả về (status, dữ liệu JSON)."""
    auth = "Basic " + base64.b64encode(f"{user}:{pwd}".encode()).decode()
    status, _, content = forward(method, f"{site_root(root)}/wp-json/{path.lstrip('/')}",
                                 {"X-WP-Authorization": auth, "Content-Type": "application/json"},
                                 json.dumps(payload or {}).encode() if payload is not None else b"")
    try:
        return status, json.loads(content or b"{}")
    except ValueError:
        return status, {}


def _err(code, msg):
    return json.dumps({"code": code, "message": msg}, ensure_ascii=False).encode()
