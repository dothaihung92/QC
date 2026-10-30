"""Máy chủ: bảng điều khiển + webhook Facebook + lịch đăng bài."""
import csv
import io
import logging
import re
import secrets
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import (APIRouter, BackgroundTasks, Depends, FastAPI, HTTPException,
                     Request)
from fastapi.responses import (FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse,
                               Response)
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel

from . import autoreply, bot, config, content, db, facebook, newsagent, replies, video
from .facebook import FacebookError

try:
    from . import groupbot
except ImportError:      # file mới chưa được tự cập nhật về: đừng làm sập cả phần mềm
    groupbot = None

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
            newsagent.tick()
            if groupbot:
                groupbot.run_due_auto_jobs()
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

def _fb_error(e: FacebookError, what: str = "") -> HTTPException:
    msg = str(e)
    if what == "stats" and ("(#10)" in msg or "(#200)" in msg):
        return HTTPException(502, msg.split(" Refer to")[0] + " — Facebook chưa cho đọc bài đăng của Fanpage. "
                             "Vào developers.facebook.com → ứng dụng → Xét duyệt → Quyền và tính năng, "
                             "bấm \"Thêm\" cho pages_read_engagement và pages_read_user_content "
                             "(hoặc tính năng Page Public Content Access), rồi lấy lại Page Access Token.")
    if "(#200)" in msg or "(#10)" in msg or "ermission" in msg:
        msg += " — thiếu quyền: thêm pages_manage_engagement (trả lời bình luận) / pages_read_user_content (đọc nội dung) trong Xét duyệt → Quyền và tính năng, rồi lấy lại token."
    return HTTPException(502, msg)


@admin.get("/api/badges")
def badges():
    # comments_new = bình luận mới CHƯA MỞ XEM (số đỏ trên menu); comments_open = cần trả lời
    return {"comments_new": db.count_unseen_comments(), "comments_open": db.count_new_comments(),
            "group_due": db.count_due_group_jobs()}


_page_cache = {"at": 0, "name": ""}


def _page_name() -> str:
    """Tên Fanpage đang kết nối (hỏi Facebook 1 lần mỗi giờ)."""
    if config.DRY_RUN:
        return "Fanpage (chạy thử)"
    if not _page_cache["name"] or time.time() - _page_cache["at"] > 3600:
        try:
            _page_cache.update(name=facebook.page_info().get("name") or "", at=time.time())
        except FacebookError:
            _page_cache["at"] = time.time() - 3000          # thử lại sau ~10 phút
    return _page_cache["name"] or f"Trang {config.PAGE_ID}"


def _where(post_id: str) -> dict:
    """Bài này nằm ở Fanpage nào, là bài nào (id bài có dạng <id Trang>_<id bài>)."""
    page_id = post_id.split("_")[0] if "_" in post_id else config.PAGE_ID
    name = _page_name() if page_id == config.PAGE_ID else f"Trang {page_id}"
    snippet = " ".join(db.post_message(post_id).split())
    return {"page_id": page_id, "page_name": name,
            "post_snippet": snippet[:90] + ("…" if len(snippet) > 90 else ""),
            "post_url": f"https://www.facebook.com/{post_id}" if post_id else ""}


@admin.get("/api/comments")
def list_comments(status: str = "open"):
    return [{**c, **_where(c["post_id"])} for c in db.list_comments(None if status == "all" else status)]


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
        c = replies.public_reply(cid, body.text, by="manual")
    except FacebookError as e:
        db.log("error", f"reply_comment {cid}: {e}")
        raise _fb_error(e)
    db.update_comment(cid, seen=1)
    db.log("reply", body.text.strip(), "")
    return c


@admin.post("/api/comments/{cid}/private")
def private_reply(cid: str, body: ReplyIn):
    _comment_or_404(cid)
    if not body.text.strip():
        raise HTTPException(400, "Nội dung tin nhắn trống")
    try:
        c = replies.private_reply(cid, body.text, by="manual")
    except FacebookError as e:
        db.log("error", f"private_reply {cid}: {e}")
        raise _fb_error(e)
    db.update_comment(cid, seen=1)
    db.log("private_reply", f"comment {cid}")
    return c


class StatusIn(BaseModel):
    status: str


@admin.post("/api/comments/{cid}/status")
def set_comment_status(cid: str, body: StatusIn):
    _comment_or_404(cid)
    if body.status not in ("new", "ignored", "replied"):
        raise HTTPException(400, "Trạng thái không hợp lệ")
    db.update_comment(cid, status=body.status)
    return db.get_comment(cid)


@admin.post("/api/comments/seen-all")
def seen_all():
    db.mark_all_seen()
    return {"ok": True}


@admin.post("/api/comments/{cid}/seen")
def mark_seen(cid: str):
    _comment_or_404(cid)
    db.update_comment(cid, seen=1)
    return {"ok": True}


def _ingest_thread(post_id: str):
    """Kéo cả cuộc hội thoại của bài từ Facebook, bổ sung những gì webhook/phần mềm chưa có
    (bình luận bị lỡ, trả lời bạn đã gõ thẳng trên Facebook). Không đụng trạng thái bình luận đã có."""
    items = facebook.fetch_thread(post_id)
    answered = {i["parent_id"] for i in items if i["is_page"] and i["parent_id"]}
    have = db.list_thread(post_id)
    for it in items:
        if it["is_page"]:
            if any(r["status"] == "page" and r["parent_id"] == it["parent_id"] and r["message"] == it["message"] for r in have):
                continue
            db.save_comment(it["id"], post_id, it["from_id"], "Fanpage (bạn)", it["message"], it["created_time"],
                            it["parent_id"], status="page", seen=1)
        else:
            db.save_comment(it["id"], post_id, it["from_id"], it["from_name"], it["message"], it["created_time"],
                            it["parent_id"], status="replied" if it["id"] in answered else "new", seen=1)


def _node(c: dict) -> dict:
    return {"id": c["id"], "from_id": c["from_id"], "from_name": c["from_name"], "message": c["message"],
            "created_at": c["created_at"], "is_page": c["status"] == "page", "status": c["status"],
            "seen": c["seen"], "reply_by": c["reply_by"], "reply_text": c["reply_text"], "replies": []}


@admin.get("/api/comments/{cid}/thread")
def comment_thread(cid: str, live: int = 0):
    """Khung xem bài: bài viết + mọi bình luận (kèm trả lời) như trên Facebook."""
    focus = _comment_or_404(cid)
    post_id, live_error = focus["post_id"], ""
    if live and post_id:
        try:
            _ingest_thread(post_id)
        except FacebookError as e:
            live_error = str(e)
    rows = db.list_thread(post_id) if post_id else [focus]
    nodes = {r["id"]: _node(r) for r in rows}
    top = []
    for r in rows:
        parent = nodes.get(r["parent_id"]) if r["parent_id"] and r["parent_id"] != post_id else None
        (parent["replies"] if parent else top).append(nodes[r["id"]])
    stat = db.get_post_stat(post_id) or {}
    return {
        "post": {"id": post_id, "message": stat.get("message") or db.post_message(post_id), "likes": stat.get("likes"),
                 "page_name": _where(post_id)["page_name"], "page_id": _where(post_id)["page_id"],
                 "comments": stat.get("comments"), "shares": stat.get("shares"),
                 "permalink": stat.get("permalink") or (f"https://www.facebook.com/{post_id}" if post_id else "")},
        "focus": cid, "comments": top, "live_error": live_error,
    }


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


# ----- trả lời bình luận tự động ------------------------------------------------

@admin.get("/api/auto-reply")
def get_auto_reply():
    return {**autoreply.get_config(), "sent_today": db.count_activity_today("auto_reply")}


@admin.put("/api/auto-reply")
def save_auto_reply(body: dict):
    try:
        cfg = autoreply.clean_config(body)
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.set_setting("auto_reply", cfg)
    return {**cfg, "sent_today": db.count_activity_today("auto_reply")}


class AutoTestIn(BaseModel):
    text: str
    rules: Optional[list] = None
    default_reply: Optional[str] = None
    default_private: Optional[str] = None


@admin.post("/api/auto-reply/test")
def test_auto_reply(body: AutoTestIn):
    """Thử một bình luận giả: quy tắc nào sẽ bắt và trả lời gì (không gửi gì lên Facebook)."""
    override = {"enabled": False}
    if body.rules is not None:
        override["rules"] = body.rules
    if body.default_reply is not None:
        override["default_reply"] = body.default_reply
    if body.default_private is not None:
        override["default_private"] = body.default_private
    try:
        cfg = autoreply.clean_config({**autoreply.get_config(), **override})
    except ValueError as e:
        raise HTTPException(400, str(e))
    hit = autoreply.match(body.text, cfg)
    if not hit:
        return {"match": False}
    return {"match": True, "label": hit["label"],
            "reply": content.render(hit["reply"], name="Lan") if hit["reply"] else "",
            "private": content.render(hit["private"], name="Lan") if hit["private"] else ""}


_scope_cache = {"at": 0, "data": None}
SCOPE_FEATURES = {
    "pages_manage_engagement": "Trả lời bình luận công khai (thủ công và tự động)",
    "read_insights": "Số lượt xem trong tab Thống kê",
    "pages_read_user_content": "Đọc nội dung bình luận khi bấm Đồng bộ / mở bài",
}


@admin.get("/api/token-scopes")
def token_scopes(refresh: int = 0):
    """Token đang có quyền gì, thiếu quyền nào thì tính năng nào chưa dùng được."""
    if not refresh and _scope_cache["data"] and time.time() - _scope_cache["at"] < 300:
        return _scope_cache["data"]
    out = {"connected": not config.DRY_RUN, "scopes": [], "missing": [], "error": ""}
    if out["connected"]:
        try:
            info = facebook.token_scopes()
            out["scopes"] = info["scopes"]
            out["missing"] = [{"scope": k, "feature": v} for k, v in SCOPE_FEATURES.items() if k not in info["scopes"]]
        except FacebookError as e:
            out["error"] = str(e)
    _scope_cache.update(at=time.time(), data=out)
    return out


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
        raise _fb_error(e, "stats")
    return _stats_payload()


# ----- AI agent tin tức -------------------------------------------------------

_news_lock = threading.Lock()


@admin.get("/api/news/config")
def news_config():
    return newsagent.public_config()


@admin.put("/api/news/config")
def news_save_config(body: dict):
    return newsagent.save_config(body)


@admin.get("/api/news")
def news_list(status: str = ""):
    return db.news_list(status or None)


@admin.post("/api/news/run")
def news_run(background: BackgroundTasks):
    cfg = newsagent.get_config()
    if not cfg["gemini_key"]:
        raise HTTPException(400, "Chưa nhập Gemini API key")
    if _news_lock.locked():
        raise HTTPException(409, "Agent đang chạy, đợi một lát")

    def job():
        with _news_lock:
            try:
                newsagent.run_once(cfg)
            except Exception as e:
                db.log("error", f"news agent: {e}")
    background.add_task(job)
    return {"started": True}


@admin.get("/api/news/running")
def news_running():
    return {"running": _news_lock.locked()}


class NewsEdit(BaseModel):
    title: Optional[str] = None
    summary: Optional[str] = None
    body: Optional[str] = None
    fb_text: Optional[str] = None


def _news_or_404(item_id: int) -> dict:
    item = db.news_get(item_id)
    if not item:
        raise HTTPException(404, "Không có bài này")
    return item


@admin.put("/api/news/{item_id}")
def news_edit(item_id: int, body: NewsEdit):
    _news_or_404(item_id)
    db.news_update(item_id, **body.model_dump(exclude_none=True))
    return db.news_get(item_id)


@admin.post("/api/news/{item_id}/publish")
def news_publish(item_id: int):
    _news_or_404(item_id)
    try:
        return newsagent.publish_item(item_id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@admin.post("/api/news/{item_id}/reject")
def news_reject(item_id: int):
    _news_or_404(item_id)
    db.news_update(item_id, status="rejected")
    return db.news_get(item_id)


@admin.delete("/api/news/{item_id}")
def news_delete(item_id: int):
    db.news_delete(item_id)
    return {"ok": True}


# Trang tin tức công khai (không cần đăng nhập) — để link từ bài Facebook trỏ về.
_BLOG_CSS = ("body{font:17px/1.7 system-ui,sans-serif;max-width:760px;margin:0 auto;padding:20px;color:#222}"
             "a{color:#1a5fb4}img{max-width:100%;height:auto}h1{line-height:1.25}.m{color:#777;font-size:14px}")


def _blog_page(title: str, inner: str) -> HTMLResponse:
    import html as _h
    return HTMLResponse(f'<!doctype html><html lang="vi"><head><meta charset="utf-8">'
                        f'<meta name="viewport" content="width=device-width,initial-scale=1">'
                        f'<title>{_h.escape(title)}</title><style>{_BLOG_CSS}</style></head>'
                        f'<body>{inner}</body></html>')


@app.get("/tin-tuc", response_class=HTMLResponse)
def blog_index():
    import html as _h
    rows = "".join(
        f'<li><a href="/tin-tuc/{_h.escape(n["slug"])}">{_h.escape(n["title"])}</a>'
        f'<div class="m">{_h.escape(n["summary"])}</div></li>'
        for n in db.news_list("published", 100) if n["slug"])
    return _blog_page("Tin tức kế toán - thuế", f"<h1>Tin tức kế toán - thuế</h1><ul>{rows}</ul>")


@app.get("/tin-tuc/{slug}", response_class=HTMLResponse)
def blog_article(slug: str):
    import html as _h
    n = db.news_get_by_slug(slug)
    if not n:
        raise HTTPException(404, "Không tìm thấy bài viết")
    return _blog_page(n["title"], f'<p><a href="/tin-tuc">← Tin tức</a></p><h1>{_h.escape(n["title"])}</h1>'
                                  f'<div class="m">{time.strftime("%d/%m/%Y", time.localtime(n["published_at"] or n["created_at"]))}</div>'
                                  f'{newsagent.article_html(n)}')


# ----- tạo clip từ bài viết -----------------------------------------------------

@admin.get("/api/video/config")
def video_config():
    return video.public_config()


@admin.put("/api/video/config")
def video_save_config(body: dict):
    return video.save_config(body)


@admin.post("/api/video/install")
def video_install():
    try:
        video.start_install()
    except video.VideoError as e:
        raise HTTPException(409, str(e))
    return video.public_config()


class ScriptIn(BaseModel):
    text: str
    seconds: int = 45
    image_url: str = ""


@admin.post("/api/videos")
def video_create(body: ScriptIn):
    """AI viết kịch bản từ nội dung bài → lưu thành clip nháp để sửa trước khi dựng."""
    try:
        sc = video.make_script(body.text, body.seconds)
    except video.VideoError as e:
        raise HTTPException(400, str(e))
    vid = db.video_add(sc["title"], sc["description"], sc["scenes"], body.image_url.strip())
    return video.to_json(db.video_get(vid))


@admin.get("/api/videos")
def video_list():
    return [video.to_json(v) for v in db.video_list()]


def _video_or_404(vid: int) -> dict:
    v = db.video_get(vid)
    if not v:
        raise HTTPException(404, "Không có clip này")
    return v


class VideoEdit(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    scenes: Optional[list] = None


@admin.put("/api/videos/{vid}")
def video_edit(vid: int, body: VideoEdit):
    v = _video_or_404(vid)
    if v["status"] == "rendering":
        raise HTTPException(409, "Clip đang dựng, đợi xong rồi sửa")
    fields = body.model_dump(exclude_none=True)
    if "scenes" in fields:
        fields["scenes"] = video.clean_scenes(fields["scenes"])
    db.video_update(vid, **fields)
    return video.to_json(db.video_get(vid))


@admin.post("/api/videos/{vid}/render")
def video_render(vid: int):
    _video_or_404(vid)
    try:
        video.start_render(vid)
    except video.VideoError as e:
        raise HTTPException(409, str(e))
    return video.to_json(db.video_get(vid))


@admin.get("/api/videos/{vid}/file")
def video_file(vid: int, download: int = 0):
    v = _video_or_404(vid)
    if not v["path"] or not Path(v["path"]).exists():
        raise HTTPException(404, "Clip chưa dựng xong")
    name = f"clip-{vid}.mp4"
    return FileResponse(v["path"], media_type="video/mp4", filename=name if download else None)


@admin.post("/api/videos/{vid}/publish")
def video_publish(vid: int):
    v = _video_or_404(vid)
    if not v["path"] or not Path(v["path"]).exists():
        raise HTTPException(400, "Clip chưa dựng xong")
    try:
        fb_id = facebook.publish_video(v["path"], v["description"], v["title"])
    except FacebookError as e:
        raise _fb_error(e)
    db.video_update(vid, fb_video_id=fb_id)
    db.log("video", f"Đăng clip #{vid} lên Fanpage → {fb_id}")
    return video.to_json(db.video_get(vid))


@admin.delete("/api/videos/{vid}")
def video_delete(vid: int):
    v = _video_or_404(vid)
    if v["status"] == "rendering":
        raise HTTPException(409, "Clip đang dựng, đợi xong rồi xóa")
    video.delete(vid)
    return {"ok": True}


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
    auto: bool = False                    # đến giờ tự đăng bằng trình duyệt (thử nghiệm)
    accept_risk: bool = False


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
    if body.auto and not body.accept_risk:
        raise HTTPException(400, RISK_MSG)
    jid = db.add_group_job(body.message.strip(), body.link.strip(), body.scheduled_at or db.now(), ids, auto=body.auto)
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


# ----- tự đăng nhóm bằng trình duyệt (thử nghiệm) ------------------------------

RISK_MSG = "Cần xác nhận đã hiểu rủi ro: tự động đăng nhóm trái điều khoản Facebook, có thể bị khóa tài khoản."


def _bot():
    if groupbot is None:
        raise HTTPException(503, "Thiếu app/groupbot.py — đóng hết cửa sổ đen rồi chạy lại start.bat để tự cập nhật")
    return groupbot


def _bot_call(fn_name, *args):
    bot_module = _bot()
    try:
        getattr(bot_module, fn_name)(*args)
    except bot_module.GroupBotError as e:
        raise HTTPException(400, str(e))
    return bot_module.status()


@admin.get("/api/groupbot/status")
def groupbot_status():
    return _bot().status()


@admin.post("/api/groupbot/install")
def groupbot_install():
    return _bot_call("start_install")


@admin.post("/api/groupbot/login")
def groupbot_login():
    return _bot_call("start_login")


class BotSettingsIn(BaseModel):
    visible: bool


@admin.post("/api/groupbot/settings")
def groupbot_settings(body: BotSettingsIn):
    db.set_setting("groupbot_visible", body.visible)
    return _bot().status()


class RunIn(BaseModel):
    job_id: int
    accept_risk: bool = False


@admin.post("/api/groupbot/run")
def groupbot_run(body: RunIn):
    if not body.accept_risk:
        raise HTTPException(400, RISK_MSG)
    return _bot_call("start_run", body.job_id)


@admin.post("/api/groupbot/stop")
def groupbot_stop():
    _bot().stop()
    return _bot().status()


app.include_router(admin)


def main():
    import uvicorn
    uvicorn.run(app, host=config.HOST, port=config.PORT)


if __name__ == "__main__":
    main()
