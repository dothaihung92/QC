import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def upd(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("qc_update", ROOT / "update.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "BASE", str(tmp_path))
    monkeypatch.setattr(mod.sys, "argv", ["update.py"])
    return mod


def test_reruns_itself_when_update_py_changes(upd, monkeypatch):
    monkeypatch.setattr(upd, "FILES", ["update.py", "static/a.txt"])
    monkeypatch.setattr(upd, "_tai_raw", lambda path, timeout=20: b"new " + path.encode())
    calls = []
    monkeypatch.setattr(upd.subprocess, "call", lambda args: calls.append(args) or 0)
    assert upd.main() == 0
    assert len(calls) == 1 and calls[0][-1] == "--lan-2"
    assert (Path(upd.BASE) / "static" / "a.txt").read_bytes() == b"new static/a.txt"


def test_no_rerun_when_unchanged_or_second_pass(upd, monkeypatch):
    monkeypatch.setattr(upd, "FILES", ["update.py"])
    monkeypatch.setattr(upd, "_tai_raw", lambda path, timeout=20: b"same")
    (Path(upd.BASE) / "update.py").write_bytes(b"same")
    calls = []
    monkeypatch.setattr(upd.subprocess, "call", lambda args: calls.append(args) or 0)
    upd.main()
    monkeypatch.setattr(upd.sys, "argv", ["update.py", "--lan-2"])
    (Path(upd.BASE) / "update.py").write_bytes(b"old")
    upd.main()
    assert calls == []


def test_network_failure_never_raises(upd, monkeypatch):
    def boom(path, timeout=20):
        raise OSError("offline")
    monkeypatch.setattr(upd, "_tai_raw", boom)
    assert upd.main() == 0


def test_every_app_module_and_static_file_is_in_update_list():
    import os
    import update
    base = os.path.dirname(os.path.dirname(os.path.abspath(update.__file__))) if False else os.path.dirname(os.path.abspath(update.__file__))
    missing = []
    for folder in ("app", "static"):
        for name in os.listdir(os.path.join(base, folder)):
            if name.endswith((".py", ".html", ".js")) and f"{folder}/{name}" not in update.FILES and name != "__pycache__":
                missing.append(f"{folder}/{name}")
    assert not missing, f"thiếu trong update.FILES: {missing}"
