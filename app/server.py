"""Máy chủ: bảng điều khiển + webhook Facebook + lịch đăng bài."""
import csv
import io
import logging
import secrets
import threading
import time
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import (APIRouter, BackgroundTasks, Depends, FastAPI, HTTPException,
                     Request)
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
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


@admin.get("/", response_class=HTMLResponse)
def index():
    return (STATIC / "index.html").read_text(encoding="utf-8")


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


app.include_router(admin)


def main():
    import uvicorn
    uvicorn.run(app, host=config.HOST, port=config.PORT)


if __name__ == "__main__":
    main()
