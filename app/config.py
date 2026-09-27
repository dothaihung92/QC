"""Đọc cấu hình từ file .env (không cần thư viện ngoài)."""
import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


_load_env_file(BASE_DIR / ".env")


def _admin_password() -> str:
    """Mật khẩu vào bảng điều khiển. Chưa đặt thì tự sinh và lưu lại."""
    pw = os.environ.get("ADMIN_PASSWORD", "").strip()
    if pw:
        return pw
    f = DATA_DIR / ".admin_password"
    if f.exists():
        return f.read_text(encoding="utf-8").strip()
    pw = secrets.token_urlsafe(12)
    f.write_text(pw, encoding="utf-8")
    return pw


PAGE_ID = os.environ.get("FB_PAGE_ID", "").strip()
PAGE_ACCESS_TOKEN = os.environ.get("FB_PAGE_ACCESS_TOKEN", "").strip()
APP_SECRET = os.environ.get("FB_APP_SECRET", "").strip()
VERIFY_TOKEN = os.environ.get("FB_VERIFY_TOKEN", "").strip()
GRAPH_API_VERSION = os.environ.get("GRAPH_API_VERSION", "v23.0").strip()

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8787"))

# Mặc định KHÔNG yêu cầu đăng nhập vào bảng điều khiển (chỉ chạy trên máy của
# bạn, ở 127.0.0.1 - không ai khác truy cập được). Chỉ bật khi phần mềm được
# mở ra ngoài Internet (vd qua cloudflared tunnel) để tránh người lạ vào được.
REQUIRE_LOGIN = os.environ.get("DASHBOARD_LOGIN", "").lower() in ("1", "true", "yes")
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = _admin_password() if REQUIRE_LOGIN else ""
DB_PATH = Path(os.environ.get("DB_PATH", str(DATA_DIR / "qc.db")))

# Chưa có token → chạy thử: ghi log thay vì gọi Facebook thật.
DRY_RUN = os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes") or not (
    PAGE_ID and PAGE_ACCESS_TOKEN
)
