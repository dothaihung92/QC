# -*- coding: utf-8 -*-
"""
Tu dong cap nhat phan mem tu GitHub (repo Public) - chay moi khi bam start.bat.

- Tai TUNG FILE trong danh sach FILES ben duoi qua raw.githubusercontent.com,
  so byte voi file dang co tren may -> KHAC thi ghi de, GIONG thi bo qua.
- Danh sach FILES la co dinh (khong tu doi ten file goc). Them file moi vao
  du an thi phai them duong dan file do vao FILES ben duoi.
- CHI dung raw.githubusercontent.com (khong dung api.github.com) vi
  raw.githubusercontent.com la CDN phuc vu file tinh, KHONG bi gioi han
  "60 request/gio" ma api.github.com ap dung cho may khong dang nhap - tranh
  loi "403 rate limit exceeded" khi khoi dong nhieu lan lien tuc.
- Khong bao gio lam treo phan mem: moi loi mang deu bo qua va chay tiep.
- KHONG dong den .env, data/ hay bat ky du lieu nao cua nguoi dung.

Tra ve exit code 10 neu start.bat hoac run_server.bat bi thay doi (de
start.bat tu khoi dong lai voi ban moi).
"""
import os, sys, ssl, urllib.request

OWNER  = "dothaihung92"
REPO   = "QC"
BRANCH = "claude/facebook-auto-advertising-tool-ireuil"

BASE = os.path.dirname(os.path.abspath(__file__))
RAW  = "https://raw.githubusercontent.com"

# Cac file cua phan mem lay tu repo (KHONG gom .env, data/, *.db...).
FILES = [
    "update.py",
    "requirements.txt",
    "requirements-dev.txt",
    "start.bat",
    "start.sh",
    "run_server.bat",
    "app/__init__.py",
    "app/config.py",
    "app/db.py",
    "app/facebook.py",
    "app/content.py",
    "app/bot.py",
    "app/server.py",
    "static/index.html",
]

# File nao thay doi thi bat cho khoi dong lai (start.bat doc lai chinh no,
# run_server.bat duoc mo o cua so rieng - deu can khoi dong lai moi ap dung).
RESTART_TRIGGERS = {"start.bat", "run_server.bat"}


def _tai_raw(path, timeout=20):
    url = f"{RAW}/{OWNER}/{REPO}/{BRANCH}/{path}"
    req = urllib.request.Request(url, headers={"User-Agent": "qc-updater"})
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        return r.read()


def main():
    n = 0
    loi = 0
    can_khoi_dong_lai = False
    for path in FILES:
        try:
            content = _tai_raw(path)
        except Exception as e:
            print(f"[update]  (bo qua {path}: {e})")
            loi += 1
            continue
        dest = os.path.join(BASE, path.replace("/", os.sep))
        # chi ghi khi noi dung khac (tranh ghi de vo ich)
        try:
            if os.path.exists(dest):
                with open(dest, "rb") as f:
                    if f.read() == content:
                        continue
        except Exception:
            pass
        try:
            d = os.path.dirname(dest)
            if d and not os.path.isdir(d):
                os.makedirs(d, exist_ok=True)
            with open(dest, "wb") as f:
                f.write(content)
            n += 1
            print(f"[update]  + {path}")
            if path.lower() in RESTART_TRIGGERS:
                can_khoi_dong_lai = True
        except Exception as e:
            print(f"[update]  (khong ghi duoc {path}: {e})")

    if n == 0 and loi == 0:
        print("[update] Phan mem da la ban moi nhat.")
    elif n == 0 and loi > 0:
        print(f"[update] Khong ket noi duoc GitHub ({loi} file) - chay tiep voi ban dang co san.")
    else:
        print(f"[update] Xong: da cap nhat {n} file.")
    return 10 if can_khoi_dong_lai else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"[update] Loi khong mong doi (chay tiep): {e}")
        sys.exit(0)
