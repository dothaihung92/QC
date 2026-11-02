"""Kết nối WordPress: chuẩn hóa địa chỉ web và chuyển tiếp REST API (tránh lỗi CORS "Failed to fetch")."""
import json
import re
from urllib.parse import urlparse

import requests

UA = "Mozilla/5.0 (compatible; QC-SEO-Writer/1.0)"


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
    "incorrect_password": "Sai Mật khẩu ứng dụng (Application Password). Tạo lại trong WordPress: Thành viên → Hồ sơ → Mật khẩu ứng dụng.",
    "invalid_username": "Sai Username — dùng đúng tên đăng nhập WordPress (không phải tên hiển thị).",
    "invalid_email": "Sai email/Username đăng nhập WordPress.",
    "rest_forbidden": "Tài khoản không đủ quyền — cần vai trò Biên tập viên (Editor) hoặc Quản trị viên.",
    "rest_cannot_create": "Tài khoản không có quyền đăng bài — cần vai trò Biên tập viên (Editor) hoặc Quản trị viên.",
    "application_passwords_disabled": "Website đang tắt Mật khẩu ứng dụng (thường do plugin bảo mật như Wordfence/iThemes) — bật lại trong plugin đó.",
    "rest_no_route": "Website chưa bật REST API hoặc đường dẫn sai — kiểm tra Cài đặt → Đường dẫn tĩnh (chọn 'Tên bài viết') rồi Lưu.",
}


def forward(method: str, url: str, headers: dict, body: bytes):
    """Gửi yêu cầu REST tới WordPress thay cho trình duyệt. Trả về (status, content_type, nội dung)."""
    url = fix_rest_url(url)
    p = urlparse(url)
    if p.scheme not in ("http", "https") or "/wp-json/" not in p.path:
        return 400, "application/json", json.dumps({"code": "bad_url", "message": "Chỉ chuyển tiếp địa chỉ REST API WordPress (/wp-json/)."}).encode()
    # Bảng điều khiển gửi đăng nhập WordPress trong "X-WP-Authorization" (header Authorization là của QC)
    keep = {k: v for k, v in headers.items() if k.lower() in ("content-type", "content-disposition", "accept")}
    wp_auth = next((v for k, v in headers.items() if k.lower() == "x-wp-authorization"), "")
    if wp_auth:
        keep["Authorization"] = wp_auth
    keep["User-Agent"] = UA
    try:
        r = requests.request(method, url, headers=keep, data=body or None, timeout=120, allow_redirects=True)
    except requests.exceptions.SSLError:
        return 502, "application/json", _err("ssl", "Lỗi chứng chỉ HTTPS của website — kiểm tra SSL hoặc thử http://")
    except requests.RequestException as e:
        return 502, "application/json", _err("connect", f"Không kết nối được tới {p.netloc}: kiểm tra tên miền / mạng ({type(e).__name__}).")
    ctype = r.headers.get("Content-Type", "")
    if "json" not in ctype.lower():
        login = "wp-login" in r.url or "wp-admin" in r.url
        return (r.status_code if r.status_code >= 400 else 502), "application/json", _err(
            "not_json", "Website trả về trang HTML thay vì REST API"
            + (" (bị chuyển tới trang đăng nhập)" if login else "")
            + f" — mã {r.status_code}. Kiểm tra: URL chỉ nhập tên miền (https://ten-mien.com), REST API không bị plugin bảo mật/Cloudflare chặn.")
    content = r.content
    if r.status_code >= 400:
        try:
            data = r.json()
            hint = HINTS.get(str(data.get("code", "")))
            if hint and isinstance(data, dict):
                data["message"] = f"{data.get('message', '')} — {hint}".strip(" —").rstrip(".")
                content = json.dumps(data, ensure_ascii=False).encode()
        except ValueError:
            pass
    return r.status_code, ctype, content


def _err(code, msg):
    return json.dumps({"code": code, "message": msg}, ensure_ascii=False).encode()
