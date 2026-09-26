"""SQLite: bài đăng, khách hàng tiềm năng, cài đặt kịch bản, nhật ký."""
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

def create_post(message, link="", image_url="", template_key="", scheduled_at=None):
    status = "scheduled" if scheduled_at else "draft"
    with conn() as c:
        cur = c.execute(
            "INSERT INTO posts(message, link, image_url, template_key, status, scheduled_at, created_at) "
            "VALUES(?, ?, ?, ?, ?, ?, ?)",
            (message, link, image_url, template_key, status, scheduled_at, now()),
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
               "fb_post_id", "error", "posted_at"}
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
