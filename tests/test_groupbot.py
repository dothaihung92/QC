"""Thử logic đăng nhóm trên trang GIẢ LẬP (không phải Facebook thật)."""
import glob
import http.server
import re
import threading

import pytest

pytest.importorskip("playwright")
from playwright.sync_api import sync_playwright  # noqa: E402

from app import config, db, groupbot  # noqa: E402

CHROME = (glob.glob("/opt/pw-browsers/chromium-*/chrome-linux*/chrome") or [None])[0]
pytestmark = pytest.mark.skipif(not CHROME, reason="không có Chromium để thử")

COMPOSER_PAGE = """<!doctype html><meta charset=utf-8>
<div role="button" id="openbtn">Bạn viết gì đi...</div><div id="posted" style="white-space:pre-wrap"></div>
<div role="dialog" id="dlg" style="display:none">
  <div role="textbox" contenteditable="true" id="box" aria-label="Tạo bài viết công khai..."></div>
  <div role="button" aria-label="Đăng" aria-disabled="true" id="post">Đăng</div></div>
<script>
openbtn.onclick = () => dlg.style.display = 'block';
box.oninput = () => post.setAttribute('aria-disabled', box.innerText.trim() ? 'false' : 'true');
post.onclick = () => { if (post.getAttribute('aria-disabled') === 'true') return;
  posted.innerText = box.innerText; dlg.style.display = 'none'; %s };
</script>"""
PAGES = {
    "/ok": COMPOSER_PAGE % "",
    "/pending": COMPOSER_PAGE % "document.body.append('Bài viết đang chờ phê duyệt');",
    "/nocomposer": "<!doctype html><meta charset=utf-8><p>Bạn chưa tham gia nhóm</p>",
    "/login": "<!doctype html><input name='email'><input name='pass' type='password'>",
}


@pytest.fixture(scope="module")
def site():
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = PAGES.get(self.path.split("?")[0], "").encode()
            self.send_response(200 if body else 404)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers(); self.wfile.write(body)
        def log_message(self, *a): pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.fixture
def page():
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        yield b.new_page()
        b.close()


@pytest.fixture(autouse=True)
def marker(tmp_path, monkeypatch):
    monkeypatch.setattr(groupbot, "PAUSE_AFTER_POST", 100)
    monkeypatch.setattr(groupbot, "STEP_TIMEOUT", 2000)
    monkeypatch.setattr(groupbot, "MARKER", tmp_path / "logged_in")
    monkeypatch.setattr(groupbot, "SHOTS", tmp_path / "shots")
    groupbot.MARKER.write_text("1")
    groupbot.state.update(busy=False, stop=False, log=[])


def test_posts_text_with_line_breaks(page, site):
    page.goto(site + "/ok")
    assert groupbot.post_to_open_group(page, "Dòng 1\n\nDòng 3 https://x.vn", timeout=4000) == "ok"
    posted = re.sub(r"\n+", "\n", page.inner_text("#posted")).strip()
    assert posted == "Dòng 1\nDòng 3 https://x.vn"


def test_detects_pending_approval(page, site):
    page.goto(site + "/pending")
    assert groupbot.post_to_open_group(page, "Chào", timeout=4000) == "pending"


def test_no_composer_is_clear_error(page, site):
    page.goto(site + "/nocomposer")
    with pytest.raises(groupbot.GroupBotError, match="ô viết bài"):
        groupbot.post_to_open_group(page, "x", timeout=2000)


def test_login_wall_stops_and_forgets_session(page, site):
    page.goto(site + "/login")
    with pytest.raises(groupbot.GroupBotError, match="đăng nhập"):
        groupbot.post_to_open_group(page, "x", timeout=2000)
    assert not groupbot.MARKER.exists()


def _setup_job(site, paths):
    gids = [db.add_group(f"G{i}", site + p) for i, p in enumerate(paths)]
    return db.add_group_job("Nội dung thử", "https://x.vn/bai", db.now() - 5, gids, auto=True), gids


@pytest.fixture
def headless(monkeypatch):
    def launch(p, visible=True):
        launch.visible_args.append(visible)
        return p.chromium.launch_persistent_context(str(groupbot.PROFILE_DIR.parent / "pw-test"), headless=True,
                                                    executable_path=CHROME, args=["--no-sandbox"])
    launch.visible_args = []
    monkeypatch.setattr(groupbot, "_launch", launch)
    monkeypatch.setattr(groupbot, "_wait_calls", [], raising=False)
    monkeypatch.setattr(config, "GROUPBOT_DELAY_MIN", 0)
    monkeypatch.setattr(config, "GROUPBOT_DELAY_MAX", 0)
    monkeypatch.setattr(groupbot, "_wait_until_closed", lambda ctx, s: groupbot._wait_calls.append(s))
    monkeypatch.setattr(groupbot, "PAUSE_AFTER_LOAD", (0, 0))
    return launch


def test_run_job_posts_all_groups_and_counts_today(site, headless):
    jid, gids = _setup_job(site, ["/ok", "/pending"])
    groupbot._run_job(jid)
    job = db.list_group_jobs()[0]
    assert job["status"] == "done" and all(g["done"] for g in job["groups"])
    assert db.count_activity_today("group_post") == 2
    assert "Xong lượt đăng" in "\n".join(groupbot.state["log"])


def test_run_job_stops_at_first_failure_and_keeps_progress(site, headless):
    jid, gids = _setup_job(site, ["/ok", "/nocomposer", "/ok"])
    groupbot._run_job(jid)
    done = [g["done"] for g in db.list_group_jobs()[0]["groups"]]
    assert done == [True, False, False]                      # dừng ở nhóm lỗi, không đăng tiếp
    assert any("Dừng ở «G1»" in l for l in groupbot.state["log"])
    assert list(groupbot.SHOTS.glob("*.png"))                # có ảnh chụp lỗi


def test_run_job_respects_daily_limit(site, headless, monkeypatch):
    monkeypatch.setattr(config, "GROUPBOT_DAILY_LIMIT", 1)
    jid, gids = _setup_job(site, ["/ok", "/ok"])
    groupbot._run_job(jid)
    assert [g["done"] for g in db.list_group_jobs()[0]["groups"]] == [True, False]
    with pytest.raises(groupbot.GroupBotError, match="giới hạn"):
        groupbot._run_job(jid)


def test_run_job_requires_login_marker(site, headless):
    groupbot.MARKER.unlink()
    jid, _ = _setup_job(site, ["/ok"])
    with pytest.raises(groupbot.GroupBotError, match="Đăng nhập Facebook"):
        groupbot._run_job(jid)


def test_auto_jobs_run_once_when_due(site, monkeypatch):
    started = []
    monkeypatch.setattr(groupbot, "start_run", lambda jid: started.append(jid))
    jid, _ = _setup_job(site, ["/ok"])
    future = db.add_group_job("Sau", "", db.now() + 3600, [db.list_groups()[0]["id"]], auto=True)
    groupbot.run_due_auto_jobs()
    groupbot.run_due_auto_jobs()
    assert started == [jid]                                  # lịch chưa đến giờ không chạy, chạy 1 lần thôi
    assert [j["auto"] for j in db.list_group_jobs() if j["id"] == jid] == [0]


def test_runs_hidden_by_default_and_does_not_wait_on_failure(site, headless):
    assert groupbot.is_visible() is False
    jid, _ = _setup_job(site, ["/nocomposer"])
    groupbot._run_job(jid)                                   # mặc định visible=False
    assert headless.visible_args == [False] and groupbot._wait_calls == []
    log = "\n".join(groupbot.state["log"])
    assert "ẩn" in log and "Hiện cửa sổ khi đăng" in log


def test_visible_run_keeps_window_open_on_failure(site, headless):
    jid, _ = _setup_job(site, ["/nocomposer"])
    groupbot._run_job(jid, True)
    assert headless.visible_args == [True] and groupbot._wait_calls == [900]


def test_visible_setting_and_start_run_default(site, monkeypatch):
    seen = []
    monkeypatch.setattr(groupbot, "_start", lambda kind, fn, *a: seen.append(a))
    db.set_setting("groupbot_visible", True)
    groupbot.start_run(7)
    db.set_setting("groupbot_visible", False)
    groupbot.start_run(8)
    groupbot.start_run(9, True)
    assert seen == [(7, True), (8, False), (9, True)]
