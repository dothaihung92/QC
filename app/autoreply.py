"""Trả lời bình luận tự động theo quy tắc (từ khóa → nội dung trả lời công khai / nhắn riêng)."""
from . import bot, content, db, replies
from .facebook import FacebookError

DEFAULTS = {
    "enabled": False,
    "rules": [],               # [{"keywords": ["giá", "báo giá"], "reply": "...", "private": "..."}]
    "default_reply": "",       # trả lời cho MỌI bình luận không khớp quy tắc nào (để trống = không trả lời)
    "default_private": "",
    "once_per_person": True,   # mỗi người chỉ trả lời tự động 1 lần ở mỗi bài (tránh spam)
    "only_top_level": True,    # bỏ qua bình luận nằm trong phần trả lời của một bình luận khác
    "daily_limit": 200,        # tối đa số lượt trả lời tự động mỗi ngày
}


def get_config() -> dict:
    cfg = dict(DEFAULTS)
    cfg.update(db.get_setting("auto_reply", {}) or {})
    return cfg


def clean_config(raw: dict) -> dict:
    """Kiểm tra dữ liệu người dùng gửi lên; sai thì ValueError với thông báo tiếng Việt."""
    cfg = dict(DEFAULTS)
    cfg["enabled"] = bool(raw.get("enabled"))
    cfg["once_per_person"] = bool(raw.get("once_per_person", True))
    cfg["only_top_level"] = bool(raw.get("only_top_level", True))
    try:
        cfg["daily_limit"] = max(1, min(int(raw.get("daily_limit", 200)), 2000))
    except (TypeError, ValueError):
        raise ValueError("Giới hạn mỗi ngày phải là số")
    for key in ("default_reply", "default_private"):
        cfg[key] = str(raw.get(key, "")).strip()
    rules = []
    for i, r in enumerate(raw.get("rules", []), 1):
        kws = r.get("keywords", [])
        if isinstance(kws, str):
            kws = kws.split(",")
        kws = [k.strip() for k in kws if k.strip()]
        reply, private = str(r.get("reply", "")).strip(), str(r.get("private", "")).strip()
        if not kws and not reply and not private:
            continue                                    # dòng trống: bỏ qua
        if not kws:
            raise ValueError(f"Quy tắc {i}: chưa có từ khóa")
        if not (reply or private):
            raise ValueError(f"Quy tắc {i}: chưa có nội dung trả lời")
        rules.append({"keywords": kws, "reply": reply, "private": private})
    cfg["rules"] = rules
    if cfg["enabled"] and not (rules or cfg["default_reply"] or cfg["default_private"]):
        raise ValueError("Bật trả lời tự động thì cần ít nhất 1 quy tắc hoặc 1 câu trả lời mặc định")
    return cfg


def match(text: str, cfg: dict):
    """Quy tắc đầu tiên khớp từ khóa (không phân biệt hoa thường / dấu), không có thì câu mặc định."""
    norm = bot.normalize(text)
    for i, rule in enumerate(cfg["rules"], 1):
        if bot.has_keyword(norm, rule["keywords"]):
            return {"label": f"quy tắc {i} ({', '.join(rule['keywords'][:3])})", "reply": rule["reply"], "private": rule["private"]}
    if cfg["default_reply"] or cfg["default_private"]:
        return {"label": "câu trả lời mặc định", "reply": cfg["default_reply"], "private": cfg["default_private"]}
    return None


def try_auto_reply(comment_id: str, value: dict, sender: dict, text: str) -> bool:
    """True = bình luận đã được xử lý bởi trả lời tự động (kể cả khi bỏ qua có chủ đích / gửi lỗi),
    để các luồng cũ không trả lời chồng lên."""
    cfg = get_config()
    if not cfg["enabled"]:
        return False
    post_id, parent_id = value.get("post_id", ""), value.get("parent_id", "")
    if cfg["only_top_level"] and parent_id and parent_id != post_id:
        return False
    if cfg["once_per_person"] and db.has_auto_reply_to(post_id, sender["id"], comment_id):
        return True
    if db.count_activity_today("auto_reply") >= cfg["daily_limit"]:
        db.log("error", f"Đã chạm giới hạn {cfg['daily_limit']} lượt trả lời tự động hôm nay", f"c:{sender['id']}")
        return True
    hit = match(text, cfg)
    if not hit:
        return False
    name = bot.first_name(sender.get("name", ""))
    lead = f"c:{sender['id']}"
    sent = False
    try:
        if hit["private"]:
            replies.private_reply(comment_id, content.render(hit["private"], name=name), by="auto")
            sent = True
        if hit["reply"]:
            replies.public_reply(comment_id, content.render(hit["reply"], name=name), by="auto")
            sent = True
    except FacebookError as e:
        db.log("error", f"trả lời tự động {comment_id}: {e}", lead)
    if sent:
        db.log("auto_reply", f"{comment_id} → {hit['label']}", lead)
    return True
