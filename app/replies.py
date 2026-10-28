"""Gửi trả lời bình luận (thủ công hoặc tự động) và ghi lại để hiện trong khung xem bài."""
import uuid

from . import config, db, facebook


def public_reply(comment_id: str, text: str, by: str = "manual") -> dict:
    """Trả lời công khai ngay dưới bình luận trên Facebook. Lỗi API → FacebookError."""
    text = text.strip()
    original = db.get_comment(comment_id) or {}
    result = facebook.reply_comment(comment_id, text)
    reply_id = result.get("id") or ""
    if reply_id in ("", "dry-run"):                       # chạy thử: không có id thật
        reply_id = f"dry-{uuid.uuid4().hex[:10]}"
    # Lưu thành 1 bình luận của Fanpage để khung xem bài hiện đủ cuộc hội thoại như trên Facebook.
    db.save_comment(reply_id, post_id=original.get("post_id", ""), parent_id=comment_id,
                    from_id=config.PAGE_ID or "page", from_name="Fanpage (bạn)", message=text,
                    created_at=db.now(), status="page", seen=1, reply_by=by)
    previous = original.get("reply_text", "")
    db.update_comment(comment_id, status="replied", reply_by=by, replied_at=db.now(),
                      reply_text=text if not previous or original.get("status") != "private_replied"
                      else f"{text}\n✉️ Nhắn riêng: {previous}")
    return db.get_comment(comment_id)


def private_reply(comment_id: str, text: str, by: str = "manual") -> dict:
    """Nhắn riêng cho người bình luận (Facebook: 1 tin/bình luận, trong 7 ngày)."""
    text = text.strip()
    original = db.get_comment(comment_id) or {}
    facebook.private_reply(comment_id, text)
    if original.get("status") == "replied" and original.get("reply_text"):
        db.update_comment(comment_id, reply_text=f"{original['reply_text']}\n✉️ Nhắn riêng: {text}", reply_by=by)
    else:
        db.update_comment(comment_id, status="private_replied", reply_text=text, reply_by=by, replied_at=db.now())
    return db.get_comment(comment_id)
