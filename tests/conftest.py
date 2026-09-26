import os
import sys
from pathlib import Path

# Cấu hình cố định cho test, không phụ thuộc file .env thật của máy.
os.environ.update({
    "FB_PAGE_ID": "", "FB_PAGE_ACCESS_TOKEN": "", "FB_APP_SECRET": "",
    "FB_VERIFY_TOKEN": "verify-me", "ADMIN_USER": "admin", "ADMIN_PASSWORD": "secret",
})
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from app import config, db, facebook  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init()


@pytest.fixture
def fb_calls(monkeypatch):
    """Thay các hàm gọi Facebook bằng hàm ghi lại lời gọi."""
    calls = []

    def rec(name):
        def f(*args, **kwargs):
            calls.append((name, args))
            return {"id": "fake"}
        return f

    for name in ("private_reply", "reply_comment", "send_message"):
        monkeypatch.setattr(facebook, name, rec(name))
    monkeypatch.setattr(config, "PAGE_ID", "PAGE1")
    return calls
