"""Gọi Facebook Graph API chính thức (Fanpage + Messenger).

Chỉ dùng những gì Meta cho phép với Page access token:
- Đăng bài lên Fanpage của bạn              POST /{page-id}/feed, /{page-id}/photos
- Trả lời công khai bình luận trên Fanpage  POST /{comment-id}/comments
- Nhắn riêng cho người vừa bình luận        POST /{page-id}/messages  recipient.comment_id
  (Private Replies: 1 tin cho mỗi bình luận, trong vòng 7 ngày)
- Trả lời người đã nhắn tin cho Page        POST /{page-id}/messages  recipient.id
  (trong cửa sổ 24 giờ kể từ tin nhắn gần nhất của họ)
"""
import hashlib
import hmac
import logging
from datetime import datetime

import requests

from . import config, db

log = logging.getLogger("qc.facebook")


class FacebookError(Exception):
    pass


def _url(path: str) -> str:
    return f"https://graph.facebook.com/{config.GRAPH_API_VERSION}/{path.lstrip('/')}"


def _call(method: str, path: str, *, params=None, json=None, token=None) -> dict:
    if config.DRY_RUN:
        db.log("dry_run", f"{method} {path} {json or params or ''}")
        return {"id": "dry-run", "dry_run": True}
    params = dict(params or {})
    params["access_token"] = token or config.PAGE_ACCESS_TOKEN
    try:
        r = requests.request(method, _url(path), params=params, json=json, timeout=30)
        data = r.json()
    except (requests.RequestException, ValueError) as e:
        raise FacebookError(f"Lỗi kết nối Facebook: {e}") from e
    if r.status_code >= 400 or "error" in data:
        err = data.get("error", {})
        raise FacebookError(f"{err.get('message', r.text)} (code {err.get('code')})")
    return data


def verify_signature(raw_body: bytes, header_value: str) -> bool:
    """Kiểm tra X-Hub-Signature-256 để chắc webhook đến từ Meta."""
    if not config.APP_SECRET:
        # Chưa cấu hình App Secret: chỉ chấp nhận khi đang chạy thử.
        return config.DRY_RUN
    if not header_value or not header_value.startswith("sha256="):
        return False
    expected = hmac.new(config.APP_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header_value.split("=", 1)[1])


def page_info() -> dict:
    return _call("GET", config.PAGE_ID, params={"fields": "id,name,fan_count,link"})


def publish_post(message: str, link: str = "", image_url: str = "") -> str:
    if image_url:
        data = _call("POST", f"{config.PAGE_ID}/photos",
                     json={"url": image_url, "caption": _with_link(message, link)})
        return data.get("post_id") or data.get("id", "")
    body = {"message": message}
    if link:
        body["link"] = link
    return _call("POST", f"{config.PAGE_ID}/feed", json=body).get("id", "")


def _with_link(message: str, link: str) -> str:
    return f"{message}\n\n👉 {link}" if link and link not in message else message


def reply_comment(comment_id: str, text: str) -> dict:
    return _call("POST", f"{comment_id}/comments", json={"message": text})


def private_reply(comment_id: str, text: str) -> dict:
    return _call("POST", f"{config.PAGE_ID}/messages", json={
        "recipient": {"comment_id": comment_id},
        "message": {"text": text},
    })


def send_message(psid: str, text: str, quick_replies=None) -> dict:
    message = {"text": text}
    if quick_replies:
        message["quick_replies"] = [
            {"content_type": "text", "title": q["title"][:20], "payload": q["payload"]}
            for q in quick_replies[:13]
        ]
    return _call("POST", f"{config.PAGE_ID}/messages", json={
        "recipient": {"id": psid},
        "messaging_type": "RESPONSE",
        "message": message,
    })


# ---------------------------------------------------------------- đọc dữ liệu Fanpage
# Chỉ đọc được bài / bình luận của CHÍNH Fanpage mình quản lý. Facebook không cho
# ứng dụng đọc bài hay bình luận trong group.

def _need_connection():
    if config.DRY_RUN:
        raise FacebookError("Chưa kết nối Fanpage (đang chạy thử) — điền FB_PAGE_ID và FB_PAGE_ACCESS_TOKEN trong .env")


def _ts(value) -> int:
    """'2026-09-28T16:00:00+0000' → epoch giây."""
    try:
        return int(datetime.strptime(value, "%Y-%m-%dT%H:%M:%S%z").timestamp())
    except (TypeError, ValueError):
        return 0


# Facebook đổi tên số liệu "lượt xem" nhiều lần (post_impressions đã bị bỏ năm 2026),
# nên thử lần lượt; không có số nào dùng được thì trả None (giao diện hiện "—").
VIEW_METRICS = ("post_media_view", "post_impressions")


def post_views(post_id: str):
    for metric in VIEW_METRICS:
        try:
            data = _call("GET", f"{post_id}/insights", params={"metric": metric})
        except FacebookError:
            continue
        for item in data.get("data", []):
            values = item.get("values") or []
            if values and values[0].get("value") is not None:
                try:
                    return int(values[0]["value"])
                except (TypeError, ValueError):
                    pass
    return None


_POST_FIELDS = (
    "id,message,created_time,permalink_url,shares,"
    "reactions.summary(total_count).limit(0),comments.summary(total_count).limit(0)",
    "id,message,created_time,permalink_url,shares",
    "id,message,created_time,permalink_url",
)


def list_published_posts(limit=20, with_views=True) -> list:
    """Bài đã đăng của Fanpage. Thiếu quyền đọc tương tác thì thử lại với ít trường hơn
    (khi đó số thích/bình luận/chia sẻ chỉ là 0); cả 3 mức đều lỗi thì báo lỗi mức cuối."""
    _need_connection()
    data, last = None, None
    for fields in _POST_FIELDS:
        try:
            data = _call("GET", f"{config.PAGE_ID}/published_posts",
                         params={"fields": fields, "limit": limit})
            break
        except FacebookError as e:
            last = e
            if "code 10)" not in str(e) and "code 200)" not in str(e):
                raise
    if data is None:
        raise last
    posts = []
    for p in data.get("data", []):
        posts.append({
            "id": p["id"],
            "message": p.get("message", ""),
            "permalink": p.get("permalink_url", ""),
            "created_time": _ts(p.get("created_time")),
            "likes": ((p.get("reactions") or {}).get("summary") or {}).get("total_count", 0),
            "comments": ((p.get("comments") or {}).get("summary") or {}).get("total_count", 0),
            "shares": (p.get("shares") or {}).get("count", 0),
            "views": post_views(p["id"]) if with_views else None,
        })
    return posts


def list_post_comments(post_id: str, limit=25) -> list:
    """Bình luận cấp 1 của 1 bài. Cần quyền pages_read_user_content mới đọc được nội dung
    bình luận của người dùng; thiếu quyền thì message rỗng (webhook vẫn nhận đủ nội dung)."""
    _need_connection()
    fields = "id,message,created_time,from{id,name},comments.limit(5){id,from{id,name}}"
    data = _call("GET", f"{post_id}/comments", params={
        "fields": fields, "limit": limit, "filter": "toplevel", "order": "reverse_chronological"})
    out = []
    for c in data.get("data", []):
        author = c.get("from") or {}
        replies = (c.get("comments") or {}).get("data", [])
        out.append({
            "id": c["id"], "post_id": post_id,
            "from_id": author.get("id", ""), "from_name": author.get("name", ""),
            "message": c.get("message", ""), "created_time": _ts(c.get("created_time")),
            "page_replied": any((r.get("from") or {}).get("id") == config.PAGE_ID for r in replies),
        })
    return out


def token_scopes() -> dict:
    """Quyền mà Page Access Token đang có (để báo thiếu quyền trước khi người dùng gặp lỗi)."""
    _need_connection()
    if not config.APP_SECRET:
        raise FacebookError("Cần FB_APP_SECRET trong .env để kiểm tra quyền của token")
    app_id = _call("GET", "app", params={"fields": "id"}).get("id")
    data = _call("GET", "debug_token", params={"input_token": config.PAGE_ACCESS_TOKEN},
                 token=f"{app_id}|{config.APP_SECRET}").get("data", {})
    return {"scopes": data.get("scopes", []), "valid": bool(data.get("is_valid", True)),
            "expires_at": data.get("expires_at", 0)}


def _thread_item(c: dict, post_id: str, parent_id: str) -> dict:
    author = c.get("from") or {}
    return {"id": c["id"], "post_id": post_id, "parent_id": parent_id,
            "from_id": author.get("id", ""), "from_name": author.get("name", ""),
            "message": c.get("message", ""), "created_time": _ts(c.get("created_time")),
            "is_page": author.get("id") == config.PAGE_ID}


def fetch_thread(post_id: str, limit: int = 50) -> list:
    """Toàn bộ bình luận cấp 1 + trả lời trong từng bình luận của 1 bài (kể cả trả lời của Fanpage)."""
    _need_connection()
    fields = "id,message,created_time,from{id,name},comments.limit(50){id,message,created_time,from{id,name}}"
    data = _call("GET", f"{post_id}/comments", params={
        "fields": fields, "limit": limit, "filter": "toplevel", "order": "chronological"})
    items = []
    for c in data.get("data", []):
        items.append(_thread_item(c, post_id, ""))
        for r in (c.get("comments") or {}).get("data", []):
            items.append(_thread_item(r, post_id, c["id"]))
    return items
