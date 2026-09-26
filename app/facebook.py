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

import requests

from . import config, db

log = logging.getLogger("qc.facebook")


class FacebookError(Exception):
    pass


def _url(path: str) -> str:
    return f"https://graph.facebook.com/{config.GRAPH_API_VERSION}/{path.lstrip('/')}"


def _call(method: str, path: str, *, params=None, json=None) -> dict:
    if config.DRY_RUN:
        db.log("dry_run", f"{method} {path} {json or params or ''}")
        return {"id": "dry-run", "dry_run": True}
    params = dict(params or {})
    params["access_token"] = config.PAGE_ACCESS_TOKEN
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
