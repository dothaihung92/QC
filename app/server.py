"""Máy chủ: bảng điều khiển + webhook Facebook + lịch đăng bài."""
import csv
import io
import logging
import re
import secrets
import threading
import time
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import (APIRouter, BackgroundTasks, Depends, FastAPI, HTTPException,
                     Request)
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel

from . import bot, config, content, db, facebook
from .facebook import FacebookError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("qc")

STATIC = config.BASE_DIR / "static"
_stop = threading.Event()


# ---------------------------------------------------------------- lịch đăng bài

def publish(post: dict) -> dict:
    try:
        fb_id = facebook.publish_post(post["message"], post.get("link", ""), post.get("image_url", ""))
        db.update_post(post["id"], status="posted", fb_post_id=fb_id, error="", posted_at=db.now())
        db.log("post", f"#{post['id']} → {fb_id}")
    except FacebookError as e:
        db.update_post(post["id"], status="failed", error=str(e))
        db.log("error", f"post #{post['id']}: {e}")
    return db.get_post(post["id"])


def scheduler_loop(interval=20):
    while not _stop.is_set():
        try:
            for post in db.claim_due_posts():
                publish(post)
        except Exception as e:
            log.exception("scheduler: %s", e)
        _stop.wait(interval)


@asynccontextmanager
async def lifespan(_app):
    db.init()
    _stop.clear()
    threading.Thread(target=scheduler_loop, daemon=True).start()
    mode = "CHẠY THỬ (chưa gửi thật lên Facebook)" if config.DRY_RUN else f"Page {config.PAGE_ID}"
    if config.REQUIRE_LOGIN:
        log.info("Bảng điều khiển: http://%s:%s  — đăng nhập: %s / %s",
                 config.HOST, config.PORT, config.ADMIN_USER, config.ADMIN_PASSWORD)
    else:
        log.info("Bảng điều khiển: http://%s:%s  (không yêu cầu đăng nhập)",
                 config.HOST, config.PORT)
    log.info("Chế độ: %s", mode)
    yield
    _stop.set()


app = FastAPI(title="Quảng cáo Fanpage", lifespan=lifespan)


# ---------------------------------------------------------------- webhook (công khai)

@app.get("/webhook", response_class=PlainTextResponse)
def webhook_verify(request: Request):
    q = request.query_params
    if (q.get("hub.mode") == "subscribe" and config.VERIFY_TOKEN
            and secrets.compare_digest(q.get("hub.verify_token", ""), config.VERIFY_TOKEN)):
        return q.get("hub.challenge", "")
    raise HTTPException(403, "Verify token không đúng")


@app.post("/webhook")
async def webhook_receive(request: Request, background: BackgroundTasks):
    raw = await request.body()
    if not facebook.verify_signature(raw, request.headers.get("X-Hub-Signature-256", "")):
        raise HTTPException(403, "Sai chữ ký")
    try:
        payload = await request.json()
    except ValueError:
        raise HTTPException(400, "JSON không hợp lệ")
    background.add_task(bot.handle_webhook, payload)
    return PlainTextResponse("EVENT_RECEIVED")


# ---------------------------------------------------------------- bảng điều khiển
# Mặc định không yêu cầu đăng nhập (chỉ chạy trên máy của bạn). Đặt
# DASHBOARD_LOGIN=true trong .env để bật lại mật khẩu - cần thiết nếu đưa
# phần mềm ra ngoài Internet (vd qua cloudflared tunnel để cấu hình webhook).

security = HTTPBasic(auto_error=False)


def require_admin(cred: HTTPBasicCredentials = Depends(security)):
    if not config.REQUIRE_LOGIN:
        return
    ok = (cred is not None
          and secrets.compare_digest(cred.username.encode(), config.ADMIN_USER.encode())
          and secrets.compare_digest(cred.password.encode(), config.ADMIN_PASSWORD.encode()))
    if not ok:
        raise HTTPException(401, "Sai tài khoản", headers={"WWW-Authenticate": "Basic"})


admin = APIRouter(dependencies=[Depends(require_admin)])


NO_STORE = {"Cache-Control": "no-store"}  # luôn lấy bản mới sau khi tự cập nhật


@admin.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse((STATIC / "index.html").read_text(encoding="utf-8"), headers=NO_STORE)


@admin.get("/seo-writer", response_class=HTMLResponse)
def seo_writer(request: Request):
    """Công cụ SEO Article Writer (Gemini) — cùng địa chỉ với bảng điều khiển nên
    dùng chung Gemini key (localStorage 'gkey') và gọi được /api/posts."""
    # Mở thẳng (dấu trang / liên kết cũ) thì đưa về tab "Viết bài SEO" trong bảng điều khiển;
    # tab đó nhúng chính trang này dưới dạng iframe nên không bị lặp.
    if request.headers.get("sec-fetch-dest") == "document":
        return RedirectResponse("/#seo", status_code=302, headers=NO_STORE)
    path = STATIC / "seo-writer.html"
    if not path.exists():
        return HTMLResponse(
            "<meta charset='utf-8'><div style='font:16px system-ui;padding:40px;line-height:1.6'>"
            "<h2>Chưa có công cụ Viết bài SEO</h2>"
            "<p>Thiếu file <code>static/seo-writer.html</code>. Đóng hết cửa sổ đen của phần mềm "
            "rồi chạy lại <b>start.bat</b> để phần mềm tự tải về.</p></div>")
    html = path.read_text(encoding="utf-8")
    # Tự chèn nút "Đăng lên Fanpage" — thay seo-writer.html bằng bản mới vẫn giữ được.
    tag = '<script src="/qc-bridge.js"></script>'
    html = html.replace("</body>", tag + "</body>", 1) if "</body>" in html else html + tag
    return HTMLResponse(html, headers=NO_STORE)


@admin.get("/qc-bridge.js")
def qc_bridge():
    path = STATIC / "qc-bridge.js"
    js = path.read_text(encoding="utf-8") if path.exists() else ""
    return Response(js, media_type="application/javascript; charset=utf-8")


@admin.get("/api/status")
def status():
    return {
        "dry_run": config.DRY_RUN,
        "page_id": config.PAGE_ID,
        "has_token": bool(config.PAGE_ACCESS_TOKEN),
        "has_app_secret": bool(config.APP_SECRET),
        "has_verify_token": bool(config.VERIFY_TOKEN),
        "graph_version": config.GRAPH_API_VERSION,
        "stats": db.stats(),
    }


@admin.post("/api/check-connection")
def check_connection():
    if config.DRY_RUN:
        raise HTTPException(400, "Chưa khai báo FB_PAGE_ID / FB_PAGE_ACCESS_TOKEN trong file .env")
    try:
        return facebook.page_info()
    except FacebookError as e:
        raise HTTPException(502, str(e))


# ----- mẫu bài & kịch bản

@admin.get("/api/templates")
def templates():
    return [
        {"key": t["key"], "title": t["title"], "text": content.render(t["text"])}
        for t in content.POST_TEMPLATES
    ]


@admin.get("/api/script")
def get_script():
    return bot.get_script()


@admin.put("/api/script")
def save_script(script: dict):
    unknown = set(script) - set(content.DEFAULT_SCRIPT)
    if unknown:
        raise HTTPException(400, f"Khóa không hợp lệ: {', '.join(sorted(unknown))}")
    for f in script.get("features", []):
        if not {"key", "short", "title", "detail"} <= set(f):
            raise HTTPException(400, "Mỗi tính năng cần key, short, title, detail")
        if len(f["short"]) > 20:
            raise HTTPException(400, f"Tên nút '{f['short']}' dài quá 20 ký tự (giới hạn của Messenger)")
    db.set_setting("script", script)
    return bot.get_script()


@admin.post("/api/script/reset")
def reset_script():
    db.set_setting("script", {})
    return bot.get_script()


class SimulateIn(BaseModel):
    kind: str = "message"   # message | comment
    text: str = ""
    payload: str = ""


@admin.post("/api/simulate")
def simulate(body: SimulateIn):
    """Thử kịch bản ngay trên giao diện — không gửi gì lên Facebook."""
    script = bot.get_script()
    if body.kind == "comment":
        norm = bot.normalize(body.text)
        hit = (script.get("reply_all_comments") or bool(bot.find_phone(body.text))
               or bot.has_keyword(norm, script["comment_keywords"]))
        return {
            "will_reply": hit,
            "private_reply": content.render(script["comment_private_reply"], name="bạn") if hit else "",
            "public_reply": content.render(script.get("comment_public_reply") or "", name="bạn") if hit else "",
        }
    lead_id = "test:simulator"
    db.upsert_lead(lead_id, "test", "", body.text)
    db.update_lead(lead_id, opted_out=0, paused_until=0)  # mỗi lần thử bắt đầu sạch
    lead = db.get_lead(lead_id)
    reply = bot.decide_reply(lead, body.text, body.payload)
    if reply is None:
        return {"text": None, "quick_replies": []}
    text, qr = reply
    return {"text": text, "quick_replies": qr or []}


# ----- bài đăng

class PostIn(BaseModel):
    message: str
    link: str = ""
    image_url: str = ""
    template_key: str = ""
    scheduled_at: Optional[int] = None   # epoch giây; None = lưu nháp
    publish_now: bool = False


@admin.get("/api/posts")
def list_posts():
    return db.list_posts()


@admin.post("/api/posts")
def create_post(body: PostIn):
    if not body.message.strip():
        raise HTTPException(400, "Nội dung trống")
    pid = db.create_post(body.message, body.link, body.image_url, body.template_key,
                         None if body.publish_now else body.scheduled_at)
    if body.publish_now:
        return publish(db.get_post(pid))
    return db.get_post(pid)


class PostUpdate(BaseModel):
    message: Optional[str] = None
    link: Optional[str] = None
    image_url: Optional[str] = None
    scheduled_at: Optional[int] = None
    unschedule: bool = False


@admin.put("/api/posts/{post_id}")
def update_post(post_id: int, body: PostUpdate):
    post = db.get_post(post_id)
    if not post:
        raise HTTPException(404, "Không có bài này")
    if post["status"] in ("posted", "posting"):
        raise HTTPException(400, "Bài đã đăng, không sửa được")
    fields = {k: v for k, v in body.model_dump().items()
              if v is not None and k in ("message", "link", "image_url", "scheduled_at")}
    if body.scheduled_at:
        fields["status"] = "scheduled"
        fields["error"] = ""
    if body.unschedule:
        fields.update(status="draft", scheduled_at=None)
    db.update_post(post_id, **fields)
    return db.get_post(post_id)


@admin.post("/api/posts/{post_id}/publish")
def publish_now(post_id: int):
    post = db.get_post(post_id)
    if not post:
        raise HTTPException(404, "Không có bài này")
    if post["status"] in ("posted", "posting"):
        raise HTTPException(400, "Bài đã đăng rồi")
    db.update_post(post_id, status="posting")
    return publish(post)


@admin.delete("/api/posts/{post_id}")
def delete_post(post_id: int):
    db.delete_post(post_id)
    return {"ok": True}


# ----- khách hàng tiềm năng

class LeadUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    status: Optional[str] = None
    note: Optional[str] = None
    opted_out: Optional[int] = None
    resume_bot: bool = False


@admin.get("/api/leads")
def list_leads():
    return [l for l in db.list_leads() if not l["id"].startswith("test:")]


@admin.put("/api/leads/{lead_id}")
def update_lead(lead_id: str, body: LeadUpdate):
    if not db.get_lead(lead_id):
        raise HTTPException(404, "Không có khách này")
    fields = {k: v for k, v in body.model_dump().items() if v is not None and k != "resume_bot"}
    if body.resume_bot:
        fields["paused_until"] = 0
    db.update_lead(lead_id, **fields)
    return db.get_lead(lead_id)


@admin.get("/api/leads.csv")
def leads_csv():
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "ten", "sdt", "nguon", "quan_tam", "trang_thai", "ghi_chu",
                "tu_choi_nhan", "tin_cuoi", "lan_dau", "lan_cuoi"])
    fmt = lambda t: time.strftime("%Y-%m-%d %H:%M", time.localtime(t))  # noqa: E731
    for l in list_leads():
        w.writerow([l["id"], l["name"], l["phone"], l["source"], ", ".join(l["interests"]),
                    l["status"], l["note"], l["opted_out"], l["last_text"],
                    fmt(l["first_seen"]), fmt(l["last_seen"])])
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename=khach-hang-tiem-nang.csv"})


@admin.get("/api/activity")
def activity():
    return db.list_activity()


# ----- bình luận (hộp thư) ----------------------------------------------------

def _fb_error(e: FacebookError) -> HTTPException:
    msg = str(e)
    if "(#200)" in msg or "(#10)" in msg or "ermission" in msg:
        msg += " — thiếu quyền: thêm pages_manage_engagement (trả lời bình luận) / pages_read_user_content (đọc nội dung) trong Xét duyệt → Quyền và tính năng, rồi lấy lại token."
    return HTTPException(502, msg)


@admin.get("/api/badges")
def badges():
    return {"comments_new": db.count_new_comments(), "group_due": db.count_due_group_jobs()}


@admin.get("/api/comments")
def list_comments(status: str = "open"):
    return db.list_comments(None if status == "all" else status)


class ReplyIn(BaseModel):
    text: str


def _comment_or_404(cid: str) -> dict:
    c = db.get_comment(cid)
    if not c:
        raise HTTPException(404, "Không có bình luận này")
    return c


@admin.post("/api/comments/{cid}/reply")
def reply_comment(cid: str, body: ReplyIn):
    _comment_or_404(cid)
    if not body.text.strip():
        raise HTTPException(400, "Nội dung trả lời trống")
    try:
        facebook.reply_comment(cid, body.text.strip())
    except FacebookError as e:
        db.log("error", f"reply_comment {cid}: {e}")
        raise _fb_error(e)
    db.update_comment(cid, status="replied", reply_text=body.text.strip(), replied_at=db.now())
    db.log("reply", body.text.strip(), "")
    return db.get_comment(cid)


@admin.post("/api/comments/{cid}/private")
def private_reply(cid: str, body: ReplyIn):
    _comment_or_404(cid)
    if not body.text.strip():
        raise HTTPException(400, "Nội dung tin nhắn trống")
    try:
        facebook.private_reply(cid, body.text.strip())
    except FacebookError as e:
        db.log("error", f"private_reply {cid}: {e}")
        raise _fb_error(e)
    db.update_comment(cid, status="private_replied", reply_text=body.text.strip(), replied_at=db.now())
    db.log("private_reply", f"comment {cid}")
    return db.get_comment(cid)


class StatusIn(BaseModel):
    status: str


@admin.post("/api/comments/{cid}/status")
def set_comment_status(cid: str, body: StatusIn):
    _comment_or_404(cid)
    if body.status not in ("new", "ignored", "replied"):
        raise HTTPException(400, "Trạng thái không hợp lệ")
    db.update_comment(cid, status=body.status)
    return db.get_comment(cid)


@admin.post("/api/comments/sync")
def sync_comments(posts: int = 8):
    """Kéo bình luận gần đây từ Facebook — bù cho lúc webhook/tunnel bị tắt."""
    try:
        recent = facebook.list_published_posts(limit=posts, with_views=False)
        added = 0
        for post in recent:
            for c in facebook.list_post_comments(post["id"]):
                if c["from_id"] == config.PAGE_ID:
                    continue
                is_new = db.get_comment(c["id"]) is None
                db.save_comment(c["id"], post_id=post["id"], from_id=c["from_id"], from_name=c["from_name"],
                                message=c["message"], created_at=c["created_time"],
                                status="replied" if c["page_replied"] else "new")
                added += is_new
    except FacebookError as e:
        raise _fb_error(e)
    return {"added": added, "new_total": db.count_new_comments()}


# ----- thống kê ----------------------------------------------------------------

def _stats_payload():
    posts = db.list_post_stats()
    tot = {k: sum((p[k] or 0) for p in posts) for k in ("likes", "comments", "shares")}
    views = [p["views"] for p in posts if p["views"] is not None]
    tot["views"] = sum(views) if views else None
    tot["posts"] = len(posts)
    synced = max((p["synced_at"] for p in posts), default=None)
    return {"posts": posts, "totals": tot, "synced_at": synced}


@admin.get("/api/stats")
def get_stats():
    return _stats_payload()


@admin.post("/api/stats/sync")
def sync_stats(limit: int = 20):
    try:
        for p in facebook.list_published_posts(limit=min(max(limit, 1), 50)):
            db.upsert_post_stats(p["id"], p["message"], p["permalink"], p["created_time"],
                                 p["likes"], p["comments"], p["shares"], p["views"])
    except FacebookError as e:
        raise _fb_error(e)
    return _stats_payload()


# ----- lịch đăng nhóm (nhắc đăng tay) -------------------------------------------
# Facebook không cho ứng dụng tự đăng vào group → đến giờ phần mềm nhắc, mở sẵn nhóm
# và chép sẵn nội dung; người dùng dán và bấm đăng rồi đánh dấu "đã đăng".

class GroupIn(BaseModel):
    name: str = ""
    url: str


def _group_url(raw: str) -> str:
    raw = raw.strip()
    m = re.search(r"facebook\.com/groups/([^/?#\s]+)", raw)
    ident = m.group(1) if m else raw
    if not re.fullmatch(r"[0-9A-Za-z._-]+", ident):
        raise HTTPException(400, "Dán đường dẫn group (facebook.com/groups/...) hoặc Group ID")
    return f"https://www.facebook.com/groups/{ident}"


@admin.get("/api/groups")
def list_groups():
    return db.list_groups()


@admin.post("/api/groups")
def add_group(body: GroupIn):
    url = _group_url(body.url)
    if any(g["url"] == url for g in db.list_groups()):
        raise HTTPException(400, "Group này đã có rồi")
    name = body.name.strip() or url.rsplit("/", 1)[-1]
    gid = db.add_group(name, url)
    return {"id": gid, "name": name, "url": url}


@admin.delete("/api/groups/{gid}")
def delete_group(gid: int):
    db.delete_group(gid)
    return {"ok": True}


class GroupJobIn(BaseModel):
    message: str
    link: str = ""
    scheduled_at: Optional[int] = None    # None = đăng ngay (nhắc luôn)
    group_ids: list[int]


@admin.get("/api/group-jobs")
def list_group_jobs():
    return db.list_group_jobs()


@admin.post("/api/group-jobs")
def add_group_job(body: GroupJobIn):
    if not body.message.strip():
        raise HTTPException(400, "Nội dung trống")
    valid = {g["id"] for g in db.list_groups()}
    ids = [g for g in body.group_ids if g in valid]
    if not ids:
        raise HTTPException(400, "Chọn ít nhất 1 group")
    jid = db.add_group_job(body.message.strip(), body.link.strip(), body.scheduled_at or db.now(), ids)
    return {"id": jid}


class ToggleIn(BaseModel):
    group_id: int


@admin.post("/api/group-jobs/{jid}/toggle")
def toggle_group_job(jid: int, body: ToggleIn):
    if not db.toggle_group_done(jid, body.group_id):
        raise HTTPException(404, "Không có lịch này")
    return {"ok": True}


@admin.delete("/api/group-jobs/{jid}")
def delete_group_job(jid: int):
    db.delete_group_job(jid)
    return {"ok": True}


app.include_router(admin)


def main():
    import uvicorn
    uvicorn.run(app, host=config.HOST, port=config.PORT)


if __name__ == "__main__":
    main()
