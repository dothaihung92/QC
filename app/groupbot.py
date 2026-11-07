"""Tự đăng bài vào group bằng trình duyệt thật (Microsoft Edge / Chrome) — THỬ NGHIỆM.

Facebook không có API đăng vào group, nên phần này điều khiển trình duyệt như người dùng:
- KHÔNG lưu mật khẩu: bạn đăng nhập tay 1 lần trong cửa sổ do phần mềm mở, phiên đăng nhập được
  giữ trong data/browser-profile để các lần sau dùng lại.
- Có giới hạn số bài/ngày và nghỉ giữa các nhóm để bảo vệ tài khoản.
- Chỉ cửa sổ ĐĂNG NHẬP là hiện ra; khi đăng bài trình duyệt chạy ẩn (trừ khi bật "hiện cửa sổ").
- Gặp bất kỳ chỗ nào không chắc (đòi đăng nhập lại, đổi giao diện...) thì DỪNG, chụp màn hình vào
  data/groupbot-errors (chạy hiện thì còn giữ cửa sổ mở để bạn tự hoàn tất) — không đoán mò.
Hành vi này trái điều khoản Facebook, có thể bị khóa tài khoản: người dùng tự chịu rủi ro.
"""
import importlib.util
import random
import re
import subprocess
import sys
import threading
import time

from . import config, db

PROFILE_DIR = config.DATA_DIR / "browser-profile"
MARKER = PROFILE_DIR / ".da_dang_nhap"
SHOTS = config.DATA_DIR / "groupbot-errors"

PAUSE_AFTER_LOAD = (3000, 5000)   # ms, chờ trang group tải xong
PAUSE_AFTER_POST = 3000           # ms, chờ Facebook xử lý sau khi bấm Đăng
STEP_TIMEOUT = 30000              # ms, chờ mỗi bước trên trang (ô viết bài, hộp soạn, nút Đăng)

_lock = threading.Lock()
state = {"busy": False, "kind": "", "log": [], "stop": False}


class GroupBotError(Exception):
    pass


class NoComposer(GroupBotError):
    """Trang nhóm không có ô viết bài: chưa tham gia / nhóm tắt quyền đăng của thành viên."""


def _log(msg: str):
    state["log"] = (state["log"] + [f"{time.strftime('%H:%M:%S')}  {msg}"])[-200:]


def playwright_available() -> bool:
    return importlib.util.find_spec("playwright") is not None


def is_visible() -> bool:
    """Có hiện cửa sổ khi đăng không (mặc định: ẩn)."""
    return bool(db.get_setting("groupbot_visible", False)) and not config.GROUPBOT_FORCE_HEADLESS


def status() -> dict:
    return {
        "visible": is_visible(),
        "playwright": playwright_available(),
        "logged_in": MARKER.exists(),
        "busy": state["busy"], "kind": state["kind"], "log": state["log"],
        "daily_used": db.count_activity_today("group_post"),
        "daily_limit": config.GROUPBOT_DAILY_LIMIT,
    }


def stop():
    state["stop"] = True


def _start(kind: str, fn, *args):
    with _lock:
        if state["busy"]:
            raise GroupBotError("Đang có một tác vụ khác chạy — đợi xong hoặc bấm Dừng")
        state.update(busy=True, kind=kind, stop=False, log=[])

    def target():
        try:
            fn(*args)
        except GroupBotError as e:
            _log(f"⚠ {e}")
        except Exception as e:  # noqa: BLE001
            _log(f"⚠ Lỗi không mong đợi: {e!r}")
        finally:
            state["busy"] = False

    threading.Thread(target=target, daemon=True).start()


# ---------------------------------------------------------------- cài đặt

def start_install():
    _start("install", _install)


def _install():
    _log("Đang cài trình điều khiển trình duyệt (playwright), khoảng 1 phút...")
    r = subprocess.run([sys.executable, "-m", "pip", "install", "playwright"],
                       capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise GroupBotError("Cài thất bại: " + (r.stderr or r.stdout)[-400:])
    importlib.invalidate_caches()
    _log("✅ Đã cài xong. Giờ bấm 'Đăng nhập Facebook'.")


# ---------------------------------------------------------------- trình duyệt

def _launch(p, visible=True):
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    kw = dict(user_data_dir=str(PROFILE_DIR), headless=(not visible) or config.GROUPBOT_FORCE_HEADLESS,
              viewport={"width": 1280, "height": 900}, locale="vi-VN")
    attempts = ([{"executable_path": config.GROUPBOT_BROWSER_PATH}] if config.GROUPBOT_BROWSER_PATH
                else [{"channel": "msedge"}, {"channel": "chrome"}, {}])
    last = None
    for extra in attempts:
        try:
            return p.chromium.launch_persistent_context(**kw, **extra)
        except Exception as e:  # noqa: BLE001
            last = e
    raise GroupBotError(f"Không mở được trình duyệt (cần Microsoft Edge hoặc Chrome, và không mở sẵn "
                        f"cùng hồ sơ này ở cửa sổ khác): {str(last)[:200]}")


def _logged_in(ctx) -> bool:
    return any(c["name"] == "c_user" for c in ctx.cookies("https://www.facebook.com"))


def start_login():
    _need_playwright()
    _start("login", _login_flow)


def _need_playwright():
    if not playwright_available():
        raise GroupBotError("Chưa cài trình điều khiển — bấm 'Cài đặt' trước")


def _login_flow():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        ctx = _launch(p, visible=True)          # đăng nhập luôn hiện cửa sổ để bạn nhập
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto("https://www.facebook.com/", wait_until="domcontentloaded")
            _log("Đã mở Facebook — hãy đăng nhập trong cửa sổ vừa hiện (chờ tối đa 10 phút).")
            end = time.time() + 600
            while not _logged_in(ctx):
                if state["stop"] or time.time() > end:
                    raise GroupBotError("Chưa đăng nhập xong — đã hủy")
                time.sleep(2)
            time.sleep(3)  # để Facebook ghi nốt cookie
            MARKER.write_text(str(int(time.time())))
            _log("✅ Đã đăng nhập. Các lần sau phần mềm tự dùng lại phiên này.")
        finally:
            _close(ctx)


def _close(ctx):
    try:
        ctx.close()
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------- đăng 1 bài

COMPOSER = re.compile(r"Bạn viết gì|Viết gì đó|Viết bài|Write something|What's on your mind|"
                      r"Create a public post|Tạo bài viết", re.I)
POST_BTN = re.compile(r"^(Đăng|Post)$", re.I)
PENDING = re.compile(r"đang chờ|chờ phê duyệt|chờ duyệt|pending|awaiting", re.I)


def _check_session(page):
    path = page.url.split("?")[0]
    if "checkpoint" in path or path.rstrip("/").endswith("/login") or page.locator("input[name='pass']").count():
        MARKER.unlink(missing_ok=True)
        raise GroupBotError("Facebook đang đòi đăng nhập/xác minh — bấm 'Đăng nhập Facebook' làm lại")


def post_to_open_group(page, text: str, timeout: int = 0) -> str:
    """Trang group đang mở → đăng `text`. Trả 'ok' hoặc 'pending' (chờ quản trị viên duyệt)."""
    timeout = timeout or STEP_TIMEOUT
    _check_session(page)
    opener = None
    for loc in (page.get_by_role("button", name=COMPOSER), page.get_by_text(COMPOSER)):
        try:
            loc.first.wait_for(state="visible", timeout=timeout // 2)
            opener = loc.first
            break
        except Exception:  # noqa: BLE001
            continue
    if opener is None:
        raise NoComposer("Không thấy ô viết bài (chưa tham gia nhóm / nhóm không cho thành viên đăng / Facebook đổi giao diện)")
    opener.click()

    dialog = page.get_by_role("dialog").last
    box = dialog.get_by_role("textbox").first
    box.wait_for(state="visible", timeout=timeout)
    box.click()
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line:
            page.keyboard.insert_text(line)
        if i < len(lines) - 1:
            page.keyboard.press("Enter")
    page.wait_for_timeout(800)

    btn = dialog.get_by_role("button", name=POST_BTN).last
    btn.wait_for(state="visible", timeout=timeout)
    for _ in range(20):                       # nút Đăng sáng lên sau vài giây
        if btn.get_attribute("aria-disabled") != "true":
            break
        page.wait_for_timeout(500)
    btn.click()
    try:
        dialog.wait_for(state="hidden", timeout=60000)
    except Exception:  # noqa: BLE001
        raise GroupBotError("Đã bấm Đăng nhưng hộp soạn bài vẫn còn — chưa chắc bài đã lên")
    page.wait_for_timeout(PAUSE_AFTER_POST)
    return "pending" if page.get_by_text(PENDING).count() else "ok"


# ---------------------------------------------------------------- chạy cả lịch

def start_run(job_id: int, visible=None):
    _need_playwright()
    _start("run", _run_job, job_id, is_visible() if visible is None else visible)


def _sleep(seconds: float):
    end = time.time() + seconds
    while time.time() < end and not state["stop"]:
        time.sleep(1)


def _run_job(job_id: int, visible: bool = False):
    from playwright.sync_api import sync_playwright
    job = next((j for j in db.list_group_jobs() if j["id"] == job_id), None)
    if not job:
        raise GroupBotError("Không có lịch này")
    todo = [g for g in job["groups"] if not g["done"] and g["state"] != "blocked"]     # đã xếp nhóm đông thành viên trước
    if not todo:
        _log("Lịch này đã đăng hết các nhóm.")
        return
    if not MARKER.exists():
        raise GroupBotError("Chưa đăng nhập Facebook trong phần mềm — bấm 'Đăng nhập Facebook' trước")
    room = config.GROUPBOT_DAILY_LIMIT - db.count_activity_today("group_post")
    if room <= 0:
        raise GroupBotError(f"Hôm nay đã đăng đủ {config.GROUPBOT_DAILY_LIMIT} bài (giới hạn bảo vệ tài khoản) — mai tiếp tục")
    if len(todo) > room:
        _log(f"Chỉ còn {room} lượt hôm nay, sẽ đăng {room}/{len(todo)} nhóm.")
        todo = todo[:room]
    link = ("\n\n" + job["link"]) if job["link"] else ""

    _log("Chạy " + ("có hiện cửa sổ trình duyệt." if visible else "ẩn (không hiện cửa sổ)."))
    with sync_playwright() as p:
        ctx = _launch(p, visible)
        failure = None
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            for i, g in enumerate(todo):
                if state["stop"]:
                    _log("Đã dừng theo yêu cầu.")
                    break
                _log(f"({i + 1}/{len(todo)}) Đang đăng vào «{g['name']}»...")
                try:
                    page.goto(g["url"], wait_until="domcontentloaded", timeout=60000)
                    page.wait_for_timeout(random.randint(*PAUSE_AFTER_LOAD))
                    result = post_to_open_group(page, (g.get("text") or job["message"]) + link)   # mỗi nhóm 1 nội dung riêng
                except NoComposer as e:                    # nhóm không cho mình đăng → ghi nhận rồi sang nhóm khác
                    db.set_group_state(job_id, g["id"], "blocked")
                    _log(f"⛔ «{g['name']}»: {e} — bỏ qua nhóm này")
                    continue
                except Exception as e:  # noqa: BLE001
                    failure = e if isinstance(e, GroupBotError) else GroupBotError(f"{type(e).__name__}: {str(e)[:200]}")
                    failure.group = g["name"]
                    _screenshot(page)
                    break
                db.set_group_state(job_id, g["id"], result)          # ok = lên bài ngay; pending = chờ quản trị viên duyệt
                db.log("group_post", f"lịch {job_id} → {g['name']} ({result})")
                _log(f"✅ «{g['name']}»" + (" — đang chờ quản trị viên duyệt" if result == "pending" else ""))
                if i < len(todo) - 1 and not state["stop"]:
                    wait = random.randint(config.GROUPBOT_DELAY_MIN, max(config.GROUPBOT_DELAY_MIN, config.GROUPBOT_DELAY_MAX))
                    _log(f"Nghỉ {wait} giây trước nhóm kế tiếp...")
                    _sleep(wait)
            else:
                _log("Xong lượt đăng.")
            if failure:
                _log(f"⚠ Dừng ở «{getattr(failure, 'group', '?')}»: {failure}")
                if visible:
                    _log("Cửa sổ trình duyệt được giữ mở để bạn tự đăng nốt; đóng cửa sổ khi xong, "
                         "rồi bấm '✓ Đã đăng' ở nhóm đó. Ảnh chụp lỗi lưu ở data/groupbot-errors.")
                    _wait_until_closed(ctx, 900)
                else:
                    _log("Ảnh chụp lỗi lưu ở data/groupbot-errors. Muốn xem trực tiếp: bật 'Hiện cửa sổ khi đăng' "
                         "rồi chạy lại; nếu Facebook đòi xác minh thì bấm 'Đăng nhập lại Facebook'.")
        finally:
            _close(ctx)


def _screenshot(page):
    try:
        SHOTS.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(SHOTS / f"{time.strftime('%Y%m%d-%H%M%S')}.png"))
    except Exception:  # noqa: BLE001
        pass


def _wait_until_closed(ctx, seconds):
    end = time.time() + seconds
    while time.time() < end and not state["stop"]:
        try:
            if not ctx.pages:
                return
        except Exception:  # noqa: BLE001
            return
        time.sleep(2)


# ---------------------------------------------------------------- kiểm tra bài đã được duyệt chưa

def _norm(t: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", (t or "").lower())).strip()


def snippet(text: str) -> str:
    """Đoạn chữ đặc trưng (khoảng 8 từ đầu của dòng dài nhất) để tìm lại bài trên trang nhóm."""
    lines = [l for l in (text or "").split("\n") if len(_norm(l)) > 15]
    best = max(lines, key=lambda l: len(l)) if lines else (text or "")
    return " ".join(_norm(best).split()[:8])


def start_check(job_id: int):
    _need_playwright()
    _start("check", _check_job, job_id)


def _page_text(page, url):
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(random.randint(*PAUSE_AFTER_LOAD))
    _check_session(page)
    for _ in range(3):                                          # cuộn để tải thêm bài
        page.mouse.wheel(0, 2500)
        page.wait_for_timeout(1200)
    return _norm(page.inner_text("body"))


def _check_job(job_id: int):
    """Bài đang 'chờ duyệt' ở nhóm nào → xem trang 'Nội dung của bạn' của nhóm: đã lên / còn chờ / bị từ chối."""
    from playwright.sync_api import sync_playwright
    job = next((j for j in db.list_group_jobs() if j["id"] == job_id), None)
    if not job:
        raise GroupBotError("Không có lịch này")
    todo = [g for g in job["groups"] if g["state"] == "pending"]
    if not todo:
        _log("Không có nhóm nào đang chờ duyệt.")
        return
    if not MARKER.exists():
        raise GroupBotError("Chưa đăng nhập Facebook trong phần mềm — bấm 'Đăng nhập Facebook' trước")
    with sync_playwright() as p:
        ctx = _launch(p, is_visible())
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            for g in todo:
                if state["stop"]:
                    break
                key = snippet(g["text"])
                base = g["url"].rstrip("/")
                try:
                    if key and key in _page_text(page, base + "/my_posted_content"):
                        db.set_group_state(job_id, g["id"], "approved")
                        _log(f"✔ «{g['name']}»: bài ĐÃ ĐƯỢC DUYỆT và đang hiển thị")
                    elif key and key in _page_text(page, base + "/my_pending_content"):
                        _log(f"⏳ «{g['name']}»: vẫn đang chờ quản trị viên duyệt")
                    else:
                        db.set_group_state(job_id, g["id"], "declined")
                        _log(f"⛔ «{g['name']}»: không thấy bài ở mục đã đăng lẫn chờ duyệt — có thể đã bị từ chối / xóa")
                except GroupBotError:
                    raise
                except Exception as e:  # noqa: BLE001
                    _log(f"⚠ «{g['name']}»: không kiểm tra được ({type(e).__name__})")
                _sleep(random.randint(4, 9))
            _log("Xong kiểm tra duyệt bài.")
        finally:
            _close(ctx)


# ---------------------------------------------------------------- số thành viên của nhóm

_MULT = {"k": 1e3, "n": 1e3, "nghìn": 1e3, "ngàn": 1e3, "tr": 1e6, "triệu": 1e6, "m": 1e6}


def parse_members(text: str) -> int:
    """'12,3K thành viên' / '45.678 thành viên' / '1,2 triệu thành viên' / '3.4K members' → số nguyên."""
    m = re.search(r"(\d[\d.,]*)\s*(k|n|nghìn|ngàn|triệu|tr|m)?\s*(?:thành viên|members?)\b", text or "", re.I)
    if not m:
        return 0
    num, unit = m.group(1), (m.group(2) or "").lower()
    if unit:
        val = float(num.replace(",", ".")) if num.count(",") + num.count(".") <= 1 else float(num.replace(".", "").replace(",", "."))
        return int(round(val * _MULT[unit]))
    return int(re.sub(r"[.,\s]", "", num) or 0)


def start_members():
    _need_playwright()
    _start("members", _update_members)


def _update_members():
    from playwright.sync_api import sync_playwright
    groups = db.list_groups()
    if not groups:
        _log("Chưa có nhóm nào.")
        return
    if not MARKER.exists():
        raise GroupBotError("Chưa đăng nhập Facebook trong phần mềm — bấm 'Đăng nhập Facebook' trước")
    with sync_playwright() as p:
        ctx = _launch(p, is_visible())
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            for g in groups:
                if state["stop"]:
                    break
                try:
                    page.goto(g["url"], wait_until="domcontentloaded", timeout=60000)
                    page.wait_for_timeout(random.randint(*PAUSE_AFTER_LOAD))
                    _check_session(page)
                    n = parse_members(page.inner_text("body"))
                except GroupBotError:
                    raise
                except Exception as e:  # noqa: BLE001
                    _log(f"⚠ «{g['name']}»: không đọc được ({type(e).__name__})")
                    continue
                if n:
                    db.update_group(g["id"], members=n, members_at=db.now())
                    _log(f"👥 «{g['name']}»: {n:,} thành viên".replace(",", "."))
                else:
                    _log(f"⚠ «{g['name']}»: không thấy số thành viên — nhập tay trong danh sách nhóm")
                _sleep(random.randint(3, 7))
            _log("Xong cập nhật số thành viên — danh sách đã xếp nhóm đông nhất lên đầu.")
        finally:
            _close(ctx)


# ---------------------------------------------------------------- lịch hẹn tự đăng

def run_due_auto_jobs():
    """Gọi định kỳ từ bộ lập lịch: lịch đã đến giờ và bật 'tự đăng' thì chạy (mỗi lần 1 lịch)."""
    if state["busy"] or not playwright_available() or not MARKER.exists():
        return
    for job in db.list_group_jobs():
        if job["auto"] and job["status"] == "due":
            try:
                start_run(job["id"])
            except GroupBotError:
                return
            db.set_group_job_auto(job["id"], False)     # chỉ thử 1 lần, tránh lặp khi lỗi
            return
