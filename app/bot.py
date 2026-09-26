"""Xử lý webhook Fanpage: bình luận → nhắn riêng giới thiệu; Messenger → menu tính năng.

Bot CHỈ trả lời người đã chủ động tương tác với Fanpage (bình luận hoặc nhắn tin),
không bao giờ nhắn cho người lạ.
"""
import re
import unicodedata

from . import config, content, db, facebook
from .facebook import FacebookError

PHONE_RE = re.compile(r"(?<!\d)(?:\+?84|0)(?:[\s.\-]?\d){9}(?!\d)")
OPT_OUT = {"stop", "huy", "dung", "dung lai", "khong nhan", "huy dang ky", "unsubscribe"}
MENU_WORDS = ["menu", "bat dau", "start", "get started"]
GREETINGS = ["hi", "hello", "chao", "xin chao", "alo", "hey"]
PRICING_WORDS = ["bao gia", "gia bao nhieu", "gia ca", "gia sao", "gia the nao",
                 "chi phi", "bao nhieu tien", "phi bao nhieu"]
DEMO_WORDS = ["dung thu", "demo", "cai dat", "tai phan mem", "trial", "ban dung thu"]
HUMAN_WORDS = ["tu van vien", "nhan vien", "nguoi that", "gap admin", "goi cho toi", "goi lai"]


def normalize(text: str) -> str:
    """Chữ thường, bỏ dấu tiếng Việt, gộp khoảng trắng: 'Tờ Khai' → 'to khai'."""
    text = (text or "").lower().replace("đ", "d")
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def has_keyword(norm_text: str, keywords) -> bool:
    return any(
        re.search(rf"(?<!\w){re.escape(normalize(k))}(?!\w)", norm_text)
        for k in keywords if normalize(k)
    )


def find_phone(text: str) -> str:
    m = PHONE_RE.search(text or "")
    if not m:
        return ""
    digits = re.sub(r"\D", "", m.group(0))
    return "0" + digits[2:] if digits.startswith("84") else digits


def get_script() -> dict:
    script = dict(content.DEFAULT_SCRIPT)
    script.update(db.get_setting("script", {}) or {})
    return script


def first_name(full_name: str) -> str:
    parts = (full_name or "").split()
    return parts[-1] if parts else "bạn"


def menu_quick_replies(script, exclude_key=None):
    qr = [
        {"title": f["short"], "payload": f"FEATURE:{f['key']}"}
        for f in script["features"] if f["key"] != exclude_key
    ]
    qr += [
        {"title": "Báo giá", "payload": "PRICING"},
        {"title": "Dùng thử", "payload": "DEMO"},
        {"title": "Gặp tư vấn viên", "payload": "HUMAN"},
    ]
    return qr


# ---------------------------------------------------------------- webhook

def handle_webhook(payload: dict):
    if payload.get("object") != "page":
        return
    for entry in payload.get("entry", []):
        for event in entry.get("messaging", []):
            _safe(handle_messaging, event)
        for change in entry.get("changes", []):
            if change.get("field") == "feed":
                _safe(handle_comment, change.get("value", {}))


def _safe(fn, arg):
    try:
        fn(arg)
    except Exception as e:  # một sự kiện lỗi không được làm hỏng cả lô
        db.log("error", f"{fn.__name__}: {e!r}")


# ---------------------------------------------------------------- bình luận

def handle_comment(value: dict):
    if value.get("item") != "comment" or value.get("verb") != "add":
        return
    comment_id = value.get("comment_id")
    sender = value.get("from") or {}
    if not comment_id or not sender.get("id") or sender.get("id") == config.PAGE_ID:
        return
    if not db.mark_processed(f"comment:{comment_id}"):
        return

    text = value.get("message", "")
    lead_id = f"c:{sender['id']}"
    db.upsert_lead(lead_id, "comment", sender.get("name", ""), text)
    db.log("comment", text, lead_id)

    phone = find_phone(text)
    if phone:
        db.update_lead(lead_id, phone=phone, status="can_goi_lai")

    script = get_script()
    if not (script.get("reply_all_comments") or phone
            or has_keyword(normalize(text), script["comment_keywords"])):
        return

    name = first_name(sender.get("name", ""))
    try:
        facebook.private_reply(comment_id, content.render(script["comment_private_reply"], name=name))
        db.log("private_reply", f"comment {comment_id}", lead_id)
    except FacebookError as e:
        db.log("error", f"private_reply {comment_id}: {e}", lead_id)
        return
    if script.get("comment_public_reply"):
        try:
            facebook.reply_comment(comment_id, content.render(script["comment_public_reply"], name=name))
        except FacebookError as e:
            db.log("error", f"reply_comment {comment_id}: {e}", lead_id)


# ---------------------------------------------------------------- Messenger

def handle_messaging(event: dict):
    psid = (event.get("sender") or {}).get("id")
    if not psid or psid == config.PAGE_ID:
        return
    message = event.get("message") or {}
    postback = event.get("postback") or {}
    if message.get("is_echo"):
        return

    text = message.get("text", "")
    payload = (message.get("quick_reply") or {}).get("payload") or postback.get("payload") or ""
    ref = message.get("mid") or postback.get("mid") or f"{psid}:{event.get('timestamp')}"
    if not (text or payload) or not db.mark_processed(f"msg:{ref}"):
        return

    lead = db.upsert_lead(psid, "messenger", "", text or payload)
    is_new = lead["first_seen"] == lead["last_seen"] and lead["status"] == "moi"
    db.log("message_in", text or payload, psid)
    if lead["status"] == "moi":
        db.update_lead(psid, status="dang_tu_van")
        lead["status"] = "dang_tu_van"

    reply = decide_reply(lead, text, payload, is_new=is_new)
    if reply:
        send(psid, *reply)


def decide_reply(lead: dict, text: str, payload: str = "", is_new: bool = False):
    """Trả về (nội dung, quick_replies) hoặc None nếu bot nên im lặng."""
    script = get_script()
    name = first_name(lead.get("name", ""))
    norm = normalize(text)
    features = {f["key"]: f for f in script["features"]}
    lead_id = lead["id"]

    def welcome():
        return content.render(script["welcome"], name=name), menu_quick_replies(script)

    def feature_reply(key):
        db.add_interest(lead_id, key)
        return features[key]["detail"], menu_quick_replies(script, exclude_key=key)

    # Người dùng gọi lại menu: luôn trả lời, bật lại bot.
    if payload in ("MENU", "GET_STARTED") or has_keyword(norm, MENU_WORDS):
        db.update_lead(lead_id, opted_out=0, paused_until=0)
        return welcome()

    if lead.get("opted_out"):
        return None
    if lead.get("paused_until", 0) > db.now():
        return None  # nhân viên đang tư vấn trực tiếp

    if norm in OPT_OUT:
        db.update_lead(lead_id, opted_out=1)
        return content.render(script["opt_out"], name=name), None

    if payload == "HUMAN" or has_keyword(norm, HUMAN_WORDS):
        hours = float(script.get("human_pause_hours") or 12)
        db.update_lead(lead_id, status="can_goi_lai", paused_until=db.now() + int(hours * 3600))
        db.log("handover", text or payload, lead_id)
        return content.render(script["human_handover"], name=name), None

    phone = find_phone(text)
    if phone:
        db.update_lead(lead_id, phone=phone, status="can_goi_lai")
        db.log("phone", phone, lead_id)
        return content.render(script["phone_thanks"], name=name, phone=phone), None

    if payload.startswith("FEATURE:") and payload[8:] in features:
        return feature_reply(payload[8:])
    if payload == "PRICING" or has_keyword(norm, PRICING_WORDS):
        db.add_interest(lead_id, "bao_gia")
        return content.render(script["pricing"], name=name), menu_quick_replies(script)
    if payload == "DEMO" or has_keyword(norm, DEMO_WORDS):
        db.add_interest(lead_id, "dung_thu")
        return content.render(script["demo"], name=name), None

    for key, f in features.items():
        if has_keyword(norm, f.get("keywords", [])):
            return feature_reply(key)

    if is_new or has_keyword(norm, GREETINGS):
        return welcome()
    return content.render(script["fallback"], name=name), menu_quick_replies(script)


def send(psid: str, text: str, quick_replies=None):
    try:
        facebook.send_message(psid, text, quick_replies)
        db.log("send", text[:300], psid)
    except FacebookError as e:
        db.log("error", f"send {psid}: {e}", psid)
