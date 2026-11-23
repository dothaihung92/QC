"""Tìm ảnh minh họa trên web cùng chủ đề với từng cảnh của clip (khác ảnh trong bài).

Nguồn, thử lần lượt:
  1. Google (API chính thức "Custom Search", cần Google API key + Search engine ID — miễn phí 100 lượt/ngày)
  2. Bing Hình ảnh (không cần key)
  3. DuckDuckGo Hình ảnh (không cần key)
Chỉ nhận kết quả do công cụ tìm kiếm trả về và tải được thật; bỏ ảnh có hình mờ của ngân hàng ảnh (Shutterstock, Getty...),
ảnh quá nhỏ và ảnh giống ảnh đã dùng trong clip (so sánh bằng dấu vân hình ảnh).
Ảnh trên web thuộc bản quyền của chủ sở hữu — nên xin phép / ghi nguồn khi đăng công khai.
"""
import html as htmllib
import json
import re
from pathlib import Path
from urllib.parse import quote_plus, urlparse

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")
STOCK = ("shutterstock", "gettyimages", "istockphoto", "alamy", "dreamstime", "depositphotos", "123rf", "adobestock", "stock.adobe",
         "bigstockphoto", "stockphoto", "vectorstock", "freepik", "pinterest", "pinimg", "fbsbx", "lookaside.", "tiktok", "gstatic.com",
         "encrypted-tbn", "ytimg", "licdn", "twimg", "media-amazon", "aliexpress", "alicdn", "shopee", "lazada")
BAD_PATH = re.compile(r"logo|icon|avatar|sprite|banner|thumb(?:nail)?[-_/]|favicon|emoji|placeholder|qr[-_]|\.svg|\.gif", re.I)


def _ok(url: str) -> bool:
    u = urlparse(url)
    host = (u.hostname or "").lower()
    return u.scheme in ("http", "https") and bool(host) and not any(s in host for s in STOCK) and not BAD_PATH.search(u.path or "")


def google_cse(q: str, key: str, cx: str, n: int = 10) -> list:
    """API Custom Search (tìm ảnh) — nguồn chính thức của Google."""
    r = requests.get("https://www.googleapis.com/customsearch/v1", timeout=20,
                     params={"key": key, "cx": cx, "q": q, "searchType": "image", "num": min(10, n), "safe": "active", "lr": "lang_vi", "imgSize": "large"})
    if r.status_code >= 400:
        raise RuntimeError(f"Google API lỗi {r.status_code}: " + ((r.json().get("error") or {}).get("message", "")[:120] if "json" in r.headers.get("content-type", "") else ""))
    return [{"url": it.get("link", ""), "page": (it.get("image") or {}).get("contextLink", ""), "title": it.get("title", ""),
             "w": (it.get("image") or {}).get("width", 0), "h": (it.get("image") or {}).get("height", 0), "src": "google"}
            for it in r.json().get("items") or []]


def bing_images(q: str, n: int = 12) -> list:
    r = requests.get(f"https://www.bing.com/images/search?q={quote_plus(q)}&form=HDRSC2&first=1&setlang=vi&cc=VN&qft=%2Bfilterui%3Aimagesize-large",
                     headers={"User-Agent": UA, "Accept-Language": "vi,en;q=0.7"}, timeout=20)
    r.raise_for_status()
    out = []
    for m in re.findall(r'class="iusc"[^>]*?\sm="([^"]+)"', r.text):
        try:
            d = json.loads(htmllib.unescape(m))
        except ValueError:
            continue
        if d.get("murl"):
            out.append({"url": d["murl"], "page": d.get("purl", ""), "title": d.get("t", ""), "w": 0, "h": 0, "src": "bing"})
    return out[:n * 2]


def ddg_images(q: str, n: int = 12) -> list:
    h = {"User-Agent": UA, "Accept-Language": "vi,en;q=0.7"}
    page = requests.get(f"https://duckduckgo.com/?q={quote_plus(q)}&iax=images&ia=images", headers=h, timeout=20).text
    m = re.search(r'vqd=["\']?([\d-]+)', page)
    if not m:
        return []
    r = requests.get(f"https://duckduckgo.com/i.js?l=vi-vn&o=json&q={quote_plus(q)}&vqd={m[1]}&f=,,,,,&p=1", headers={**h, "Referer": "https://duckduckgo.com/"}, timeout=20)
    r.raise_for_status()
    return [{"url": it.get("image", ""), "page": it.get("url", ""), "title": it.get("title", ""), "w": it.get("width", 0), "h": it.get("height", 0), "src": "ddg"}
            for it in (r.json().get("results") or [])][:n * 2]


def search(q: str, cfg: dict = None, n: int = 10) -> list:
    """Danh sách ảnh ứng viên [{url, page, title, w, h, src}] — lọc ảnh ngân hàng ảnh / ảnh nhỏ; lỗi nguồn này thì thử nguồn sau."""
    cfg = cfg or {}
    sources = []
    if cfg.get("google_cse_key") and cfg.get("google_cse_cx"):
        sources.append(lambda: google_cse(q, cfg["google_cse_key"], cfg["google_cse_cx"], n))
    sources += [lambda: bing_images(q, n), lambda: ddg_images(q, n)]
    for fn in sources:
        try:
            res = fn()
        except Exception:  # noqa: BLE001 — bị chặn / hết lượt: thử nguồn kế tiếp
            continue
        seen, out = set(), []
        for it in res:
            u = it.get("url", "")
            if not _ok(u) or u in seen or (it.get("w") and it["w"] < 480) or (it.get("h") and it["h"] < 300):
                continue
            seen.add(u)
            out.append(it)
        if out:
            return out[:n]
    return []


# ---------------------------------------------------------------- dấu vân hình ảnh: nhận ra ảnh giống nhau

def ahash(path: Path) -> int:
    """Hash trung bình 8x8 — hai ảnh giống nhau (dù khác kích thước / nén lại) có hash gần nhau."""
    from PIL import Image
    with Image.open(path) as im:
        g = im.convert("L").resize((8, 8))
        px = list(g.getdata())
    avg = sum(px) / 64
    return sum(1 << i for i, v in enumerate(px) if v >= avg)


def similar(a: int, b: int, tol: int = 8) -> bool:
    return bin(a ^ b).count("1") <= tol


# ---------------------------------------------------------------- từ khóa tìm ảnh theo cảnh

_STOP = set("và của là có cho các một những được trong với này để khi đã sẽ bị cũng như từ đến tại về theo năm tháng ngày không còn hơn nhiều rất đang vì nên thì mà".split())


def norm(t: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFD", (t or "").lower().replace("đ", "d"))
    return re.sub(r"\s+", " ", "".join(c for c in t if unicodedata.category(c) != "Mn")).strip()


def topic_from_title(title: str) -> list:
    """Không có từ khóa chủ đề từ AI: lấy các từ có nghĩa trong tiêu đề clip."""
    return list(dict.fromkeys(w for w in re.findall(r"[\w]+", title or "") if w.lower() not in _STOP and len(w) > 2 and not re.search(r"\d", w)))[:5]


def anchor_query(q: str, topic: list) -> str:
    """Cụm tìm ảnh luôn phải chứa từ khóa chủ đề của bài (vd "thuế", "bảo hiểm xã hội") — nếu không tìm kiếm sẽ ra ảnh lạc đề (bàn phím, sách, người nước ngoài...)."""
    nq = norm(q)
    if topic and not any(norm(t) in nq for t in topic):
        return f"{topic[0]} {q}".strip()[:100]
    return q


def relevant_meta(item: dict, topic: list) -> bool:
    """Tiêu đề / địa chỉ của kết quả có nhắc tới chủ đề bài không? (lọc nhanh trước khi tải ảnh)"""
    if not topic:
        return True
    blob = norm(f"{item.get('title', '')} {urlparse(item.get('page') or '').path} {urlparse(item.get('url') or '').path}".replace("-", " ").replace("_", " "))
    return any(norm(t) in blob for t in topic)


def scene_query(sc: dict, title: str = "", topic: list = None) -> str:
    """Cụm tìm ảnh tiếng Việt: AI viết sẵn ("query") hoặc rút từ lời đọc (bỏ số và từ nối) + chủ đề; luôn gắn từ khóa chủ đề của bài."""
    q = (sc.get("query") or "").strip()
    if not q:
        words = [w for w in re.findall(r"[\w]+", sc.get("narration", "")) if not re.search(r"\d", w) and w.lower() not in _STOP and len(w) > 2]
        tw = [w for w in re.findall(r"[\w]+", title or "") if w.lower() not in _STOP and len(w) > 2][:3]
        q = " ".join(dict.fromkeys([*words[:4], *tw]))
    return anchor_query(q, topic if topic is not None else topic_from_title(title))[:100]
