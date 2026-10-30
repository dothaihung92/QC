"""SQLite: bài đăng, bình luận, thống kê, lịch đăng nhóm, khách hàng tiềm năng, nhật ký."""
import json
import sqlite3
import threading
import time
from contextlib import contextmanager

from . import config

DB_PATH = config.DB_PATH
_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS posts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    message      TEXT NOT NULL,
    link         TEXT DEFAULT '',
    image_url    TEXT DEFAULT '',
    template_key TEXT DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'draft',   -- draft|scheduled|posting|posted|failed
    scheduled_at INTEGER,                          -- epoch giây
    fb_post_id   TEXT DEFAULT '',
    error        TEXT DEFAULT '',
    created_at   INTEGER NOT NULL,
    posted_at    INTEGER
);
CREATE TABLE IF NOT EXISTS leads (
    id           TEXT PRIMARY KEY,                 -- PSID (Messenger) hoặc 'c:<id>' (bình luận)
    name         TEXT DEFAULT '',
    phone        TEXT DEFAULT '',
    source       TEXT DEFAULT '',                  -- messenger|comment
    interests    TEXT DEFAULT '[]',                -- JSON list key tính năng
    status       TEXT DEFAULT 'moi',               -- moi|dang_tu_van|can_goi_lai|da_mua|khong_quan_tam
    note         TEXT DEFAULT '',
    opted_out    INTEGER DEFAULT 0,
    paused_until INTEGER DEFAULT 0,                -- bot tạm dừng để nhân viên tư vấn
    last_text    TEXT DEFAULT '',
    first_seen   INTEGER NOT NULL,
    last_seen    INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS processed (
    ref_id     TEXT PRIMARY KEY,                   -- mid tin nhắn / comment_id, chống xử lý trùng
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS comments (
    id          TEXT PRIMARY KEY,                  -- comment_id của Facebook
    post_id     TEXT DEFAULT '',
    parent_id   TEXT DEFAULT '',                   -- khác post_id = trả lời trong 1 bình luận
    from_id     TEXT DEFAULT '',
    from_name   TEXT DEFAULT '',
    message     TEXT DEFAULT '',
    created_at  INTEGER NOT NULL,
    status      TEXT NOT NULL DEFAULT 'new',       -- new|replied|private_replied|ignored|page (trả lời của Fanpage)
    reply_text  TEXT DEFAULT '',
    replied_at  INTEGER,
    seen        INTEGER NOT NULL DEFAULT 0,        -- 0 = bình luận mới, người dùng chưa mở xem
    reply_by    TEXT NOT NULL DEFAULT ''           -- auto|manual: ai đã trả lời
);
CREATE TABLE IF NOT EXISTS post_stats (
    fb_post_id   TEXT PRIMARY KEY,
    message      TEXT DEFAULT '',
    permalink    TEXT DEFAULT '',
    created_time INTEGER,
    likes        INTEGER DEFAULT 0,
    comments     INTEGER DEFAULT 0,
    shares       INTEGER DEFAULT 0,
    views        INTEGER,                          -- NULL = Facebook không trả về
    synced_at    INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS group_targets (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    url  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS group_jobs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    message      TEXT NOT NULL,
    link         TEXT DEFAULT '',
    scheduled_at INTEGER NOT NULL,
    group_ids    TEXT NOT NULL DEFAULT '[]',       -- JSON list id group_targets
    done_ids     TEXT NOT NULL DEFAULT '[]',       -- JSON list group đã đăng xong
    created_at   INTEGER NOT NULL,
    auto         INTEGER NOT NULL DEFAULT 0        -- 1 = đến giờ tự đăng bằng trình duyệt
);
CREATE TABLE IF NOT EXISTS news_items (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    url          TEXT NOT NULL UNIQUE,
    source       TEXT DEFAULT '',
    orig_title   TEXT DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'new',  -- pending|published|rejected|skipped|failed
    title        TEXT DEFAULT '',
    summary      TEXT DEFAULT '',
    body         TEXT DEFAULT '',
    fb_text      TEXT DEFAULT '',
    image_url    TEXT DEFAULT '',
    slug         TEXT DEFAULT '',
    web_url      TEXT DEFAULT '',
    fb_post_id   TEXT DEFAULT '',
    error        TEXT DEFAULT '',
    created_at   INTEGER NOT NULL,
    published_at INTEGER
);
CREATE TABLE IF NOT EXISTS videos (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    title        TEXT DEFAULT '',
    description  TEXT DEFAULT '',
    scenes       TEXT NOT NULL DEFAULT '[]',   -- JSON [{headline, narration, keyword}]
    image_url    TEXT DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'draft', -- draft|rendering|done|failed
    progress     TEXT DEFAULT '',
    path         TEXT DEFAULT '',
    duration     REAL DEFAULT 0,
    fb_video_id  TEXT DEFAULT '',
    error        TEXT DEFAULT '',
    created_at   INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS activity (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at INTEGER NOT NULL,
    kind       TEXT NOT NULL,
    lead_id    TEXT DEFAULT '',
    text       TEXT DEFAULT ''
);
"""


@contextmanager
def conn():
    with _lock:
        c = sqlite3.connect(DB_PATH)
        c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        finally:
            c.close()


def init():
    with conn() as c:
        c.executescript(SCHEMA)
        cols = {r["name"] for r in c.execute("PRAGMA table_info(group_jobs)")}
        if "auto" not in cols:                       # CSDL cũ chưa có cột auto
            c.execute("ALTER TABLE group_jobs ADD COLUMN auto INTEGER NOT NULL DEFAULT 0")
        ccols = {r["name"] for r in c.execute("PRAGMA table_info(comments)")}
        if "seen" not in ccols:                      # bình luận cũ coi như đã xem, chỉ bình luận mới mới có chấm "Mới"
            c.execute("ALTER TABLE comments ADD COLUMN seen INTEGER NOT NULL DEFAULT 0")
            c.execute("UPDATE comments SET seen=1")
        if "reply_by" not in ccols:
            c.execute("ALTER TABLE comments ADD COLUMN reply_by TEXT NOT NULL DEFAULT ''")
        pcols = {r["name"] for r in c.execute("PRAGMA table_info(posts)")}
        for col, ddl in POST_EXTRA_COLS.items():           # tính năng thêm theo kiểu Postiz
            if col not in pcols:
                c.execute(f"ALTER TABLE posts ADD COLUMN {col} {ddl}")
        # phần mềm bị tắt giữa lúc dựng clip → đừng để clip kẹt mãi ở "đang dựng"
        c.execute("UPDATE videos SET status='failed', progress='', "
                  "error='Phần mềm bị tắt khi đang dựng — bấm Dựng clip lại' WHERE status='rendering'")


POST_EXTRA_COLS = {
    "first_comment": "TEXT NOT NULL DEFAULT ''",   # Fanpage tự bình luận ngay dưới bài vừa đăng
    "repeat_days":   "INTEGER NOT NULL DEFAULT 0",  # đăng lại sau N ngày (0 = không lặp)
    "plug_likes":    "INTEGER NOT NULL DEFAULT 0",  # đạt N lượt cảm xúc thì tự bình luận plug_text
    "plug_text":     "TEXT NOT NULL DEFAULT ''",
    "plug_done":     "INTEGER NOT NULL DEFAULT 0",
}


def now() -> int:
    return int(time.time())


# ---------- settings ----------

def get_setting(key, default=None):
    with conn() as c:
        row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def set_setting(key, value):
    with conn() as c:
        c.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value, ensure_ascii=False)),
        )


# ---------- chống trùng ----------

def mark_processed(ref_id: str) -> bool:
    """True nếu lần đầu thấy ref_id (Facebook có thể gửi lại webhook)."""
    with conn() as c:
        cur = c.execute(
            "INSERT OR IGNORE INTO processed(ref_id, created_at) VALUES(?, ?)",
            (ref_id, now()),
        )
        return cur.rowcount == 1


# ---------- nhật ký ----------

def log(kind: str, text: str = "", lead_id: str = ""):
    with conn() as c:
        c.execute(
            "INSERT INTO activity(created_at, kind, lead_id, text) VALUES(?, ?, ?, ?)",
            (now(), kind, lead_id, text[:2000]),
        )


def list_activity(limit=200):
    with conn() as c:
        rows = c.execute(
            "SELECT * FROM activity WHERE lead_id NOT LIKE 'test:%' ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


# ---------- leads ----------

def upsert_lead(lead_id: str, source: str, name: str = "", text: str = "") -> dict:
    t = now()
    with conn() as c:
        c.execute(
            "INSERT INTO leads(id, name, source, last_text, first_seen, last_seen) "
            "VALUES(?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET last_seen=excluded.last_seen, "
            "last_text=CASE WHEN excluded.last_text != '' THEN excluded.last_text ELSE last_text END, "
            "name=CASE WHEN name = '' THEN excluded.name ELSE name END",
            (lead_id, name, source, text[:500], t, t),
        )
        row = c.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
    return _lead_dict(row)


def get_lead(lead_id: str):
    with conn() as c:
        row = c.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
    return _lead_dict(row) if row else None


def update_lead(lead_id: str, **fields):
    allowed = {"name", "phone", "status", "note", "opted_out", "paused_until", "interests"}
    fields = {k: v for k, v in fields.items() if k in allowed}
    if not fields:
        return
    if "interests" in fields:
        fields["interests"] = json.dumps(fields["interests"], ensure_ascii=False)
    sets = ", ".join(f"{k}=?" for k in fields)
    with conn() as c:
        c.execute(f"UPDATE leads SET {sets} WHERE id=?", (*fields.values(), lead_id))


def add_interest(lead_id: str, feature_key: str):
    lead = get_lead(lead_id)
    if lead and feature_key not in lead["interests"]:
        update_lead(lead_id, interests=lead["interests"] + [feature_key])


def list_leads():
    with conn() as c:
        rows = c.execute("SELECT * FROM leads ORDER BY last_seen DESC").fetchall()
    return [_lead_dict(r) for r in rows]


def _lead_dict(row):
    d = dict(row)
    d["interests"] = json.loads(d.get("interests") or "[]")
    return d


# ---------- posts ----------

def create_post(message, link="", image_url="", template_key="", scheduled_at=None, **extra):
    status = "scheduled" if scheduled_at else "draft"
    extra = {k: v for k, v in extra.items() if k in POST_EXTRA_COLS and v is not None}
    cols = ["message", "link", "image_url", "template_key", "status", "scheduled_at", "created_at", *extra]
    with conn() as c:
        cur = c.execute(
            f"INSERT INTO posts({', '.join(cols)}) VALUES({', '.join('?' * len(cols))})",
            (message, link, image_url, template_key, status, scheduled_at, now(), *extra.values()),
        )
        return cur.lastrowid


def get_post(post_id: int):
    with conn() as c:
        row = c.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
    return dict(row) if row else None


def list_posts():
    with conn() as c:
        rows = c.execute("SELECT * FROM posts ORDER BY id DESC").fetchall()
    return [dict(r) for r in rows]


def update_post(post_id: int, **fields):
    allowed = {"message", "link", "image_url", "status", "scheduled_at",
               "fb_post_id", "error", "posted_at", *POST_EXTRA_COLS}
    fields = {k: v for k, v in fields.items() if k in allowed}
    if not fields:
        return
    sets = ", ".join(f"{k}=?" for k in fields)
    with conn() as c:
        c.execute(f"UPDATE posts SET {sets} WHERE id=?", (*fields.values(), post_id))


def delete_post(post_id: int):
    with conn() as c:
        c.execute("DELETE FROM posts WHERE id=?", (post_id,))


def claim_due_posts() -> list:
    """Lấy bài đến giờ đăng và chuyển sang 'posting' để không đăng hai lần."""
    with conn() as c:
        rows = c.execute(
            "SELECT * FROM posts WHERE status='scheduled' AND scheduled_at <= ?",
            (now(),),
        ).fetchall()
        ids = [r["id"] for r in rows]
        if ids:
            c.execute(
                f"UPDATE posts SET status='posting' WHERE id IN ({','.join('?' * len(ids))})",
                ids,
            )
    return [dict(r) for r in rows]


def stats():
    real = "id NOT LIKE 'test:%'"  # bỏ khách giả lập từ nút "Thử kịch bản"
    with conn() as c:
        q = lambda sql: c.execute(sql).fetchone()[0]  # noqa: E731
        return {
            "leads": q(f"SELECT COUNT(*) FROM leads WHERE {real}"),
            "leads_7d": q(f"SELECT COUNT(*) FROM leads WHERE {real} AND first_seen >= {now() - 7 * 86400}"),
            "can_goi_lai": q(f"SELECT COUNT(*) FROM leads WHERE {real} AND status='can_goi_lai'"),
            "co_sdt": q(f"SELECT COUNT(*) FROM leads WHERE {real} AND phone != ''"),
            "posts_posted": q("SELECT COUNT(*) FROM posts WHERE status='posted'"),
            "posts_scheduled": q("SELECT COUNT(*) FROM posts WHERE status='scheduled'"),
            "replies_sent": q("SELECT COUNT(*) FROM activity WHERE kind IN ('send','private_reply') "
                              "AND lead_id NOT LIKE 'test:%'"),
        }


# ---------- bình luận ----------

def save_comment(cid, post_id="", from_id="", from_name="", message="",
                 created_at=None, parent_id="", status="new", seen=0, reply_by=""):
    """Thêm bình luận; có rồi thì chỉ bổ sung nội dung/tên còn thiếu, KHÔNG đổi trạng thái / đã xem."""
    with conn() as c:
        c.execute(
            "INSERT INTO comments(id, post_id, parent_id, from_id, from_name, message, created_at, status, seen, reply_by) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET "
            "message=CASE WHEN excluded.message != '' THEN excluded.message ELSE message END, "
            "from_name=CASE WHEN excluded.from_name != '' THEN excluded.from_name ELSE from_name END",
            (cid, post_id, parent_id, from_id, from_name, message, created_at or now(), status, seen, reply_by),
        )


def get_comment(cid):
    with conn() as c:
        row = c.execute("SELECT * FROM comments WHERE id=?", (cid,)).fetchone()
    return dict(row) if row else None


def list_comments(status=None, limit=300):
    """Hộp thư bình luận. Trả lời của chính Fanpage (status='page') chỉ hiện trong khung xem bài."""
    sql, args = "SELECT * FROM comments WHERE status != 'page'", []
    if status == "open":                    # cần trả lời
        sql += " AND status='new'"
    elif status == "unseen":                # chưa mở xem
        sql += " AND seen=0"
    elif status and status != "all":
        sql += " AND status=?"; args.append(status)
    sql += " ORDER BY created_at DESC, rowid DESC LIMIT ?"
    with conn() as c:
        rows = c.execute(sql, (*args, limit)).fetchall()
    return [dict(r) for r in rows]


def update_comment(cid, **fields):
    allowed = {"status", "reply_text", "replied_at", "seen", "reply_by"}
    fields = {k: v for k, v in fields.items() if k in allowed}
    if not fields:
        return
    sets = ", ".join(f"{k}=?" for k in fields)
    with conn() as c:
        c.execute(f"UPDATE comments SET {sets} WHERE id=?", (*fields.values(), cid))


def count_new_comments() -> int:
    """Số bình luận cần trả lời."""
    with conn() as c:
        return c.execute("SELECT COUNT(*) FROM comments WHERE status='new'").fetchone()[0]


def count_unseen_comments() -> int:
    """Số bình luận mới chưa mở xem (số đỏ trên menu)."""
    with conn() as c:
        return c.execute("SELECT COUNT(*) FROM comments WHERE seen=0 AND status != 'page'").fetchone()[0]


def mark_all_seen():
    with conn() as c:
        c.execute("UPDATE comments SET seen=1 WHERE seen=0")


def list_thread(post_id):
    """Mọi bình luận của 1 bài (cả trả lời của Fanpage), theo thứ tự thời gian."""
    with conn() as c:
        rows = c.execute("SELECT * FROM comments WHERE post_id=? ORDER BY created_at, rowid", (post_id,)).fetchall()
    return [dict(r) for r in rows]


def has_auto_reply_to(post_id, from_id, except_id="") -> bool:
    """Người này đã được trả lời tự động ở bài này chưa (để không trả lời lặp)."""
    with conn() as c:
        return c.execute(
            "SELECT 1 FROM comments WHERE post_id=? AND from_id=? AND reply_by='auto' AND id != ? LIMIT 1",
            (post_id, from_id, except_id)).fetchone() is not None


def get_post_stat(fb_post_id):
    with conn() as c:
        row = c.execute("SELECT * FROM post_stats WHERE fb_post_id=?", (fb_post_id,)).fetchone()
    return dict(row) if row else None


# ---------- thống kê bài ----------

def upsert_post_stats(fb_post_id, message="", permalink="", created_time=None,
                      likes=0, comments=0, shares=0, views=None):
    with conn() as c:
        c.execute(
            "INSERT INTO post_stats(fb_post_id, message, permalink, created_time, likes, comments, shares, views, synced_at) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(fb_post_id) DO UPDATE SET message=excluded.message, permalink=excluded.permalink, "
            "created_time=excluded.created_time, likes=excluded.likes, comments=excluded.comments, "
            "shares=excluded.shares, views=COALESCE(excluded.views, views), synced_at=excluded.synced_at",
            (fb_post_id, message, permalink, created_time, likes, comments, shares, views, now()),
        )


def list_post_stats(limit=100):
    with conn() as c:
        rows = c.execute("SELECT * FROM post_stats ORDER BY created_time DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


# ---------- lịch đăng nhóm (nhắc, đăng tay) ----------

def add_group(name, url):
    with conn() as c:
        return c.execute("INSERT INTO group_targets(name, url) VALUES(?, ?)", (name, url)).lastrowid


def list_groups():
    with conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM group_targets ORDER BY id").fetchall()]


def delete_group(gid):
    with conn() as c:
        c.execute("DELETE FROM group_targets WHERE id=?", (gid,))


def add_group_job(message, link, scheduled_at, group_ids, auto=False):
    with conn() as c:
        return c.execute(
            "INSERT INTO group_jobs(message, link, scheduled_at, group_ids, created_at, auto) VALUES(?, ?, ?, ?, ?, ?)",
            (message, link, scheduled_at, json.dumps(group_ids), now(), int(bool(auto))),
        ).lastrowid


def set_group_job_auto(job_id, auto: bool):
    with conn() as c:
        c.execute("UPDATE group_jobs SET auto=? WHERE id=?", (int(bool(auto)), job_id))


def mark_group_done(job_id, group_id):
    """Đánh dấu 1 group đã đăng xong (khác toggle: gọi nhiều lần vẫn là 'đã đăng')."""
    with conn() as c:
        row = c.execute("SELECT done_ids FROM group_jobs WHERE id=?", (job_id,)).fetchone()
        if row:
            done = set(json.loads(row["done_ids"])) | {group_id}
            c.execute("UPDATE group_jobs SET done_ids=? WHERE id=?", (json.dumps(sorted(done)), job_id))


def count_activity_today(kind) -> int:
    t = time.localtime()
    midnight = int(time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1)))
    with conn() as c:
        return c.execute("SELECT COUNT(*) FROM activity WHERE kind=? AND created_at>=?", (kind, midnight)).fetchone()[0]


def _job_dict(row, groups_by_id):
    d = dict(row)
    ids = [g for g in json.loads(d.pop("group_ids")) if g in groups_by_id]   # bỏ group đã xóa
    done = set(json.loads(d.pop("done_ids")))
    d["groups"] = [{"id": g, "name": groups_by_id[g]["name"], "url": groups_by_id[g]["url"],
                    "done": g in done} for g in ids]
    if ids and all(g in done for g in ids):
        d["status"] = "done"
    elif d["scheduled_at"] <= now():
        d["status"] = "due"
    else:
        d["status"] = "scheduled"
    return d


def list_group_jobs():
    groups = {g["id"]: g for g in list_groups()}
    with conn() as c:
        rows = c.execute("SELECT * FROM group_jobs ORDER BY scheduled_at DESC, id DESC").fetchall()
    return [_job_dict(r, groups) for r in rows]


def toggle_group_done(job_id, group_id):
    """Đảo trạng thái 'đã đăng' của 1 group trong 1 lịch. Trả về True nếu lịch tồn tại."""
    with conn() as c:
        row = c.execute("SELECT done_ids FROM group_jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            return False
        done = set(json.loads(row["done_ids"]))
        done.symmetric_difference_update({group_id})
        c.execute("UPDATE group_jobs SET done_ids=? WHERE id=?", (json.dumps(sorted(done)), job_id))
    return True


def delete_group_job(job_id):
    with conn() as c:
        c.execute("DELETE FROM group_jobs WHERE id=?", (job_id,))


def count_due_group_jobs() -> int:
    return sum(1 for j in list_group_jobs() if j["status"] == "due")


def post_message(fb_post_id) -> str:
    """Nội dung bài Fanpage (để hiện 'Trên bài: ...' cạnh bình luận): số liệu đã đồng bộ, không có thì bài đăng từ phần mềm."""
    if not fb_post_id:
        return ""
    stat = get_post_stat(fb_post_id)
    if stat and stat["message"]:
        return stat["message"]
    with conn() as c:
        row = c.execute("SELECT message FROM posts WHERE fb_post_id=?", (fb_post_id,)).fetchone()
    return row["message"] if row else ""


# ---------- tin tức do AI agent tìm & viết lại ----------

def news_seen(url) -> bool:
    with conn() as c:
        return c.execute("SELECT 1 FROM news_items WHERE url=?", (url,)).fetchone() is not None


def news_add(url, source="", orig_title="", status="new", **fields) -> int:
    cols = ["url", "source", "orig_title", "status", "created_at"] + list(fields)
    vals = [url, source, orig_title, status, now()] + list(fields.values())
    with conn() as c:
        cur = c.execute(f"INSERT OR IGNORE INTO news_items({','.join(cols)}) "
                        f"VALUES({','.join('?' * len(cols))})", vals)
        return cur.lastrowid if cur.rowcount else 0


def news_update(item_id, **fields):
    if not fields:
        return
    with conn() as c:
        c.execute(f"UPDATE news_items SET {', '.join(k + '=?' for k in fields)} WHERE id=?",
                  list(fields.values()) + [item_id])


def news_get(item_id):
    with conn() as c:
        row = c.execute("SELECT * FROM news_items WHERE id=?", (item_id,)).fetchone()
    return dict(row) if row else None


def news_get_by_slug(slug):
    with conn() as c:
        row = c.execute("SELECT * FROM news_items WHERE slug=? AND status='published'", (slug,)).fetchone()
    return dict(row) if row else None


def news_list(status=None, limit=100):
    q, args = "SELECT * FROM news_items", []
    if status:
        q += " WHERE status=?"
        args.append(status)
    q += " ORDER BY created_at DESC, id DESC LIMIT ?"
    args.append(limit)
    with conn() as c:
        return [dict(r) for r in c.execute(q, args).fetchall()]


def news_delete(item_id):
    with conn() as c:
        c.execute("DELETE FROM news_items WHERE id=?", (item_id,))


# ---------- clip video tạo từ bài viết ----------

def _video_row(row):
    if not row:
        return None
    d = dict(row)
    d["scenes"] = json.loads(d["scenes"] or "[]")
    return d


def video_add(title, description, scenes, image_url="") -> int:
    with conn() as c:
        return c.execute(
            "INSERT INTO videos(title, description, scenes, image_url, created_at) VALUES(?, ?, ?, ?, ?)",
            (title, description, json.dumps(scenes, ensure_ascii=False), image_url, now())).lastrowid


def video_update(video_id, **fields):
    if "scenes" in fields:
        fields["scenes"] = json.dumps(fields["scenes"], ensure_ascii=False)
    if not fields:
        return
    with conn() as c:
        c.execute(f"UPDATE videos SET {', '.join(k + '=?' for k in fields)} WHERE id=?",
                  list(fields.values()) + [video_id])


def video_get(video_id):
    with conn() as c:
        return _video_row(c.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone())


def video_list(limit=50):
    with conn() as c:
        rows = c.execute("SELECT * FROM videos ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [_video_row(r) for r in rows]


def video_delete(video_id):
    with conn() as c:
        c.execute("DELETE FROM videos WHERE id=?", (video_id,))


# ---------- khung giờ vàng (giống "posting times" của Postiz) ----------

DEFAULT_SLOTS = ["07:30", "11:45", "20:00"]


def posting_slots() -> list:
    return get_setting("posting_slots", DEFAULT_SLOTS) or []


def next_free_slot(after=None, slots=None, gap=600):
    """Khung giờ vàng gần nhất còn trống (không có bài hẹn trong ±10 phút). Giờ theo máy tính."""
    from datetime import datetime, timedelta
    slots = slots if slots is not None else posting_slots()
    if not slots:
        return None
    after = (after or now()) + 60
    with conn() as c:
        taken = [r[0] for r in c.execute(
            "SELECT scheduled_at FROM posts WHERE status IN ('scheduled', 'posting') AND scheduled_at IS NOT NULL")]
    day = datetime.fromtimestamp(after).replace(hour=0, minute=0, second=0, microsecond=0)
    for d in range(60):
        base = day + timedelta(days=d)
        for hhmm in sorted(slots):
            h, m = map(int, hhmm.split(":"))
            ts = int((base + timedelta(hours=h, minutes=m)).timestamp())
            if ts >= after and all(abs(ts - t) >= gap for t in taken):
                return ts
    return None


def posts_to_plug(max_age=7 * 86400) -> list:
    with conn() as c:
        rows = c.execute(
            "SELECT * FROM posts WHERE status='posted' AND plug_likes > 0 AND plug_done=0 "
            "AND fb_post_id != '' AND posted_at >= ?", (now() - max_age,)).fetchall()
    return [dict(r) for r in rows]
