from app import bot, db
from app.content import DEFAULT_SCRIPT


def comment_event(comment_id="c1", text="quan tâm", from_id="u1", name="Nguyễn Văn An"):
    return {"object": "page", "entry": [{"changes": [{"field": "feed", "value": {
        "item": "comment", "verb": "add", "comment_id": comment_id, "post_id": "p1",
        "message": text, "from": {"id": from_id, "name": name}}}]}]}


def msg_event(text="", psid="PSID1", mid="m1", payload=None, echo=False):
    message = {"mid": mid, "text": text}
    if payload:
        message["quick_reply"] = {"payload": payload}
    if echo:
        message["is_echo"] = True
    return {"object": "page", "entry": [{"messaging": [
        {"sender": {"id": psid}, "recipient": {"id": "PAGE1"}, "timestamp": 1, "message": message}]}]}


def sent_texts(calls):
    return [args[1] for name, args in calls if name == "send_message"]


# ---------------------------------------------------------------- tiện ích

def test_normalize_strips_vietnamese_marks():
    assert bot.normalize("  Tờ KHAI  Đã nộp!! ") == "to khai da nop"


def test_keyword_uses_word_boundaries():
    assert bot.has_keyword("check ib nhe", ["ib"])
    assert not bot.has_keyword("ibm server", ["ib"])
    assert bot.has_keyword(bot.normalize("Quan Tâm ạ"), ["quan tâm"])


def test_find_phone_formats():
    assert bot.find_phone("sđt 0912 345 678 nhé") == "0912345678"
    assert bot.find_phone("+84 912.345.678") == "0912345678"
    assert bot.find_phone("MST 0101234567890") == ""
    assert bot.find_phone("năm 2024") == ""


# ---------------------------------------------------------------- bình luận

def test_comment_with_keyword_gets_private_and_public_reply(fb_calls):
    bot.handle_webhook(comment_event(text="Quan tâm, ib mình"))
    names = [n for n, _ in fb_calls]
    assert names == ["private_reply", "reply_comment"]
    assert "An" in fb_calls[0][1][1]            # gọi bằng tên
    lead = db.get_lead("c:u1")
    assert lead["source"] == "comment" and lead["name"] == "Nguyễn Văn An"


def test_comment_without_keyword_is_only_recorded(fb_calls):
    bot.handle_webhook(comment_event(text="bài viết hay"))
    assert fb_calls == []
    assert db.get_lead("c:u1") is not None


def test_comment_with_phone_is_replied_and_saved(fb_calls):
    bot.handle_webhook(comment_event(text="0987654321"))
    assert [n for n, _ in fb_calls][0] == "private_reply"
    lead = db.get_lead("c:u1")
    assert lead["phone"] == "0987654321" and lead["status"] == "can_goi_lai"


def test_page_own_comment_and_duplicates_ignored(fb_calls):
    bot.handle_webhook(comment_event(from_id="PAGE1"))
    assert fb_calls == []
    bot.handle_webhook(comment_event(comment_id="c9"))
    bot.handle_webhook(comment_event(comment_id="c9"))   # Facebook gửi lại
    assert [n for n, _ in fb_calls].count("private_reply") == 1


def test_reply_all_comments_setting(fb_calls):
    db.set_setting("script", {"reply_all_comments": True, "comment_public_reply": ""})
    bot.handle_webhook(comment_event(text="👍"))
    assert [n for n, _ in fb_calls] == ["private_reply"]


# ---------------------------------------------------------------- Messenger

def test_new_user_gets_welcome_menu(fb_calls):
    bot.handle_webhook(msg_event("xin chào"))
    (name, (psid, text, qr)), = fb_calls
    assert psid == "PSID1" and "NHIỀU công ty" in text
    assert {q["payload"] for q in qr} >= {"FEATURE:hoa_don", "PRICING", "DEMO", "HUMAN"}
    assert all(len(q["title"]) <= 20 for q in qr)


def test_feature_keyword_sends_detail_and_records_interest(fb_calls):
    bot.handle_webhook(msg_event("tải hóa đơn điện tử thế nào?"))
    assert "TẢI HÓA ĐƠN" in sent_texts(fb_calls)[0]
    assert "hoa_don" in db.get_lead("PSID1")["interests"]


def test_quick_reply_payload(fb_calls):
    bot.handle_webhook(msg_event("Nhập liệu MISA", payload="FEATURE:misa"))
    assert "MISA" in sent_texts(fb_calls)[0]


def test_phone_is_saved(fb_calls):
    bot.handle_webhook(msg_event("số mình 0912345678"))
    lead = db.get_lead("PSID1")
    assert lead["phone"] == "0912345678" and lead["status"] == "can_goi_lai"
    assert "0912345678" in sent_texts(fb_calls)[0]


def test_dung_thu_is_demo_not_opt_out(fb_calls):
    bot.handle_webhook(msg_event("cho dùng thử"))
    assert "DÙNG THỬ" in sent_texts(fb_calls)[0]
    assert db.get_lead("PSID1")["opted_out"] == 0


def test_opt_out_then_silent_until_menu(fb_calls):
    bot.handle_webhook(msg_event("Dừng", mid="a"))
    assert db.get_lead("PSID1")["opted_out"] == 1
    bot.handle_webhook(msg_event("tờ khai", mid="b"))
    assert len(sent_texts(fb_calls)) == 1              # chỉ tin xác nhận hủy
    bot.handle_webhook(msg_event("menu", mid="c"))
    assert db.get_lead("PSID1")["opted_out"] == 0
    assert len(sent_texts(fb_calls)) == 2


def test_human_handover_pauses_bot(fb_calls):
    bot.handle_webhook(msg_event("Gặp tư vấn viên", payload="HUMAN", mid="a"))
    lead = db.get_lead("PSID1")
    assert lead["status"] == "can_goi_lai" and lead["paused_until"] > db.now()
    bot.handle_webhook(msg_event("alo", mid="b"))
    assert len(sent_texts(fb_calls)) == 1


def test_echo_and_duplicate_messages_ignored(fb_calls):
    bot.handle_webhook(msg_event("hi", echo=True))
    assert fb_calls == []
    bot.handle_webhook(msg_event("hi", mid="same"))
    bot.handle_webhook(msg_event("hi", mid="same"))
    assert len(fb_calls) == 1


def test_default_quick_reply_titles_fit_messenger_limit():
    assert all(len(f["short"]) <= 20 for f in DEFAULT_SCRIPT["features"])
