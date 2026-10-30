"""AI agent tin tức: dò bài về kế toán / thuế → AI viết lại → (duyệt) → đăng web + Fanpage.

Chỉ dùng thư viện chuẩn + requests. Mặc định bài viết lại nằm ở hàng chờ DUYỆT; chỉ
tự đăng khi bật "auto_publish". Mọi bài đều ghi nguồn gốc ở cuối.
"""
import html
import json
import logging
import re
import time
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import parse_qs, quote_plus, urljoin, urlparse

import requests

from . import config, db, facebook
from .facebook import FacebookError

log = logging.getLogger("qc.news")

DEFAULTS = {
    "enabled": False,
    "auto_publish": False,        # False = chờ bạn duyệt trước khi đăng
    "keywords": ["luật thuế mới", "kế toán thuế", "hóa đơn điện tử", "thuế TNCN", "thuế GTGT"],
    "feeds": [],                   # thêm RSS của báo/website bạn tin cậy
    "interval_hours": 6,
    "max_per_run": 3,
    "max_age_days": 2,            # chỉ lấy bài trong N ngày gần nhất (1 = hôm nay/hôm qua)
    "post_to_web": True,
    "post_to_fb": True,
    "use_images": True,
    "public_url": "",             # địa chỉ web của bạn, vd https://dailythuehungphuc.com
    "brand_note": "",             # câu giới thiệu dịch vụ/phần mềm chèn cuối bài
    "wp_url": "", "wp_user": "", "wp_app_password": "",
    "gemini_key": "",
    "model": "gemini-2.5-flash",
}
UA = "Mozilla/5.0 (compatible; QCNewsAgent/1.0)"


# ---------------------------------------------------------------- cấu hình

def get_config() -> dict:
    cfg = dict(DEFAULTS)
    cfg.update(db.get_setting("newsagent", {}) or {})
    return cfg


def public_config() -> dict:
    cfg = get_config()
    cfg["has_gemini_key"] = bool(cfg["gemini_key"])
    cfg["has_wp_password"] = bool(cfg["wp_app_password"])
    cfg["gemini_key"] = cfg["wp_app_password"] = ""
    cfg["last_run"] = db.get_setting("newsagent_last_run", 0)
    return cfg


def save_config(body: dict) -> dict:
    cur = get_config()
    for k, default in DEFAULTS.items():
        if k not in body:
            continue
        v = body[k]
        if k in ("gemini_key", "wp_app_password") and not str(v or "").strip():
            continue                                  # để trống = giữ giá trị cũ
        if isinstance(default, bool):
            v = bool(v)
        elif isinstance(default, int):
            try:
                v = max(1, int(v))
            except (TypeError, ValueError):
                v = default
        elif isinstance(default, list):
            if isinstance(v, str):
                v = v.splitlines()
            v = [str(x).strip() for x in v if str(x).strip()]
        else:
            v = str(v or "").strip()
        cur[k] = v
    cur["public_url"] = cur["public_url"].rstrip("/")
    cur["wp_url"] = cur["wp_url"].rstrip("/")
    db.set_setting("newsagent", cur)
    return public_config()


# ---------------------------------------------------------------- tìm bài

def _bing_url(link: str) -> str:
    """Link Bing News chứa địa chỉ thật trong tham số url=."""
    q = parse_qs(urlparse(link).query)
    return (q.get("url") or [link])[0]


def _parse_date(value: str) -> int:
    value = (value or "").strip()
    for parse in (parsedate_to_datetime, datetime.fromisoformat):
        try:
            return int(parse(value).timestamp())
        except (TypeError, ValueError, IndexError):
            continue
    return 0


def parse_feed(xml_text: str) -> list:
    """RSS/Atom → [{title, url, source, published(epoch)}]."""
    out = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return out
    strip = lambda t: t.split("}", 1)[-1]
    for el in root.iter():
        if strip(el.tag) not in ("item", "entry"):
            continue
        d = {strip(c.tag): (c.text or "", c) for c in el}
        title = html.unescape(d.get("title", ("",))[0]).strip()
        link = d.get("link", ("",))[0].strip()
        if not link and "link" in d:
            link = d["link"][1].attrib.get("href", "")
        src = d.get("source", ("",))[0].strip()
        pub = d.get("pubDate", d.get("published", d.get("updated", ("",))))[0]
        ts = _parse_date(pub)
        if title and link:
            out.append({"title": title, "url": _bing_url(link), "source": src, "published": ts})
    return out


class _Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links, self._href, self._buf = [], None, []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href, self._buf = dict(attrs).get("href"), []
            self.links.append(None)          # đánh dấu: các chữ sau đây thuộc link trước đó (chứa ngày đăng)

    def handle_endtag(self, tag):
        if tag == "a" and self._href:
            self.links[-1] = [self._href, re.sub(r"\s+", " ", "".join(self._buf)).strip(), ""]
            self._href = None

    def handle_data(self, data):
        if self._href:
            self._buf.append(data)
        elif self.links and self.links[-1]:
            self.links[-1][2] += data


_DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")


def parse_page_links(html_text: str, base_url: str) -> list:
    """Trang danh sách tin (không có RSS) → các link bài viết cùng website, tiêu đề dài >= 25 ký tự.
    Ngày đăng lấy từ chữ "Ngày dd/mm/yyyy" ngay sau link; trang có ghi ngày thì chỉ lấy link có ngày
    (bỏ menu, ứng dụng...)."""
    p = _Links()
    p.feed(html_text)
    host, out, seen = urlparse(base_url).netloc, [], set()
    for entry in p.links:
        if not entry:
            continue
        href, text, after = entry
        url = urljoin(base_url, html.unescape(href.strip()))
        if (len(text) < 25 or urlparse(url).scheme not in ("http", "https")
                or urlparse(url).netloc != host or url in seen or url.rstrip("/") == base_url.rstrip("/")):
            continue
        ts = 0
        m = _DATE_RE.search(after[:80])
        if m:
            try:
                ts = int(datetime(int(m[3]), int(m[2]), int(m[1])).timestamp())
            except ValueError:
                pass
        seen.add(url)
        out.append({"title": text, "url": url, "source": host, "published": ts})
    if any(i["published"] for i in out):
        out = [i for i in out if i["published"]]
    return out


def _get(url: str, timeout=20):
    r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "vi,en;q=0.8"}, timeout=timeout)
    r.raise_for_status()
    if not r.encoding or r.encoding.lower() == "iso-8859-1":
        r.encoding = r.apparent_encoding
    return r


def search(keywords, feeds, max_age_days=2) -> list:
    urls = [f"https://www.bing.com/news/search?q={quote_plus(k)}&format=rss&setlang=vi&cc=VN"
            for k in keywords] + list(feeds)
    found, seen = [], set()
    cutoff = time.time() - max_age_days * 86400
    for u in urls:
        try:
            r = _get(u)
            items = parse_feed(r.text) or parse_page_links(r.text, r.url)   # RSS, không phải thì coi là trang danh sách
        except (requests.RequestException, ValueError) as e:
            log.warning("feed lỗi %s: %s", u, e)
            continue
        for it in items:
            if it["url"] in seen or (it["published"] and it["published"] < cutoff):
                continue
            seen.add(it["url"])
            found.append(it)
    found.sort(key=lambda it: it["published"], reverse=True)      # bài mới nhất trước, bài không rõ ngày xuống cuối
    return found


# ---------------------------------------------------------------- đọc bài nguồn

class _Extract(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta, self.paras, self._buf, self._skip, self._p = {}, [], [], 0, False
        self.chunks = []                    # văn bản dài nằm ngoài thẻ <p> (website dùng div/span/td)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta":
            key = a.get("property") or a.get("name")
            if key and a.get("content"):
                self.meta.setdefault(key, a["content"])
        elif tag in ("script", "style", "nav", "footer", "header", "aside", "form", "noscript"):
            self._skip += 1
        elif tag == "p" and not self._skip:
            self._p, self._buf = True, []

    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav", "footer", "header", "aside", "form", "noscript"):
            self._skip = max(0, self._skip - 1)
        elif tag == "p" and self._p:
            text = re.sub(r"\s+", " ", "".join(self._buf)).strip()
            if len(text) >= 60:
                self.paras.append(text)
            self._p = False

    def handle_data(self, data):
        if self._p and not self._skip:
            self._buf.append(data)
        elif not self._skip:
            text = re.sub(r"\s+", " ", data).strip()
            if len(text) >= 80:
                self.chunks.append(text)


def fetch_article(url: str) -> dict:
    r = _get(url)
    ex = _Extract()
    ex.feed(r.text)
    image = ex.meta.get("og:image") or ex.meta.get("twitter:image") or ""
    text = "\n\n".join(ex.paras)
    if len(text) < 300:
        text = "\n\n".join(ex.paras + ex.chunks)
    return {"url": r.url, "title": ex.meta.get("og:title", ""), "image": image, "text": text[:7000]}


# ---------------------------------------------------------------- AI viết lại

PROMPT = """Bạn là biên tập viên của một công ty dịch vụ kế toán - thuế tại Việt Nam.
Dưới đây là bài báo nguồn. Hãy VIẾT LẠI hoàn toàn bằng lời văn của bạn cho khách hàng là chủ doanh nghiệp nhỏ và kế toán.

Quy tắc:
- Giữ ĐÚNG số liệu, mức thuế, ngày hiệu lực, số hiệu văn bản. Không bịa thêm thông tin không có trong bài nguồn.
- Không sao chép nguyên câu của bài nguồn. Cấu trúc lại, thêm phần "Doanh nghiệp cần làm gì".
- Nếu bài KHÔNG liên quan kế toán / thuế / hóa đơn / BHXH / quy định cho doanh nghiệp thì đặt "relevant": false.
- body: văn bản thường, đoạn cách nhau một dòng trống, tiêu đề phụ bắt đầu bằng "## ". Không dùng HTML.
- fb_text: bài đăng Facebook 4-8 dòng, mở bằng ý chính, có 1-2 emoji, kết bằng 3 hashtag. Không chèn link.
{brand}
Trả về DUY NHẤT một JSON: {{"relevant": true, "title": "...", "summary": "1-2 câu", "body": "...", "fb_text": "..."}}

TIÊU ĐỀ NGUỒN: {title}
NỘI DUNG NGUỒN:
{text}
"""


def gemini_json(prompt: str, cfg: dict) -> dict:
    if not cfg["gemini_key"]:
        raise RuntimeError("Chưa nhập Gemini API key (tab Tin tức AI)")
    last = None
    for model in (cfg["model"], "gemini-2.5-flash-lite"):
        try:
            r = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                headers={"x-goog-api-key": cfg["gemini_key"], "Content-Type": "application/json"},
                json={"contents": [{"parts": [{"text": prompt}]}],
                      "generationConfig": {"responseMimeType": "application/json", "temperature": 0.6}},
                timeout=90)
            data = r.json()
            if r.status_code >= 400:
                raise RuntimeError(data.get("error", {}).get("message", r.text)[:300])
            txt = data["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(re.sub(r"^```(?:json)?|```$", "", txt.strip()).strip())
        except (requests.RequestException, KeyError, IndexError, ValueError, RuntimeError) as e:
            last = e
    raise RuntimeError(f"Gemini lỗi: {last}")


def rewrite(art: dict, title: str, cfg: dict) -> dict:
    brand = (f'- Cuối body thêm 1 đoạn giới thiệu nhẹ nhàng: "{cfg["brand_note"]}"\n'
             if cfg["brand_note"] else "")
    out = gemini_json(PROMPT.format(brand=brand, title=art["title"] or title, text=art["text"]), cfg)
    return {k: str(out.get(k, "")).strip() for k in ("title", "summary", "body", "fb_text")} | \
        {"relevant": bool(out.get("relevant", True))}


# ---------------------------------------------------------------- hiển thị / đăng web

def slugify(title: str) -> str:
    s = unicodedata.normalize("NFD", title.lower().replace("đ", "d"))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:70] or "bai-viet"


def body_to_html(body: str) -> str:
    parts = []
    for block in re.split(r"\n\s*\n", body.strip()):
        block = block.strip()
        if block.startswith("## "):
            parts.append(f"<h2>{html.escape(block[3:])}</h2>")
        elif block:
            parts.append("<p>" + html.escape(block).replace("\n", "<br>") + "</p>")
    return "\n".join(parts)


def article_html(item: dict, with_source=True) -> str:
    out = ""
    if item["image_url"]:
        out += f'<p><img src="{html.escape(item["image_url"])}" alt="{html.escape(item["title"])}" style="max-width:100%"></p>\n'
    out += body_to_html(item["body"])
    if with_source and item["url"]:
        host = urlparse(item["url"]).netloc
        out += (f'\n<p><em>Nguồn tham khảo: <a href="{html.escape(item["url"])}" rel="nofollow noopener" '
                f'target="_blank">{html.escape(item["source"] or host)}</a></em></p>')
    return out


def _unique_slug(base: str, item_id: int) -> str:
    slug, n = base, 2
    while True:
        other = db.news_get_by_slug(slug)
        if not other or other["id"] == item_id:
            return slug
        slug, n = f"{base}-{n}", n + 1


def post_to_wordpress(item: dict, cfg: dict) -> str:
    r = requests.post(f"{cfg['wp_url']}/wp-json/wp/v2/posts",
                      auth=(cfg["wp_user"], cfg["wp_app_password"]), timeout=60,
                      json={"title": item["title"], "content": article_html(item),
                            "excerpt": item["summary"], "status": "publish"})
    try:
        data = r.json()
    except ValueError:
        data = {}
    if r.status_code >= 400:
        raise RuntimeError(f"WordPress: {data.get('message', r.text[:200])}")
    return data.get("link", "")


# ---------------------------------------------------------------- quy trình

def process_url(it: dict, cfg: dict) -> int:
    """Đọc + viết lại 1 bài nguồn → lưu thành 'pending' (hoặc 'skipped' / 'failed'). Trả về id."""
    item_id = db.news_add(it["url"], it.get("source", ""), it["title"])
    if not item_id:
        return 0
    try:
        art = fetch_article(it["url"])
        if len(art["text"]) < 300:
            db.news_update(item_id, status="skipped", error="Không đọc được nội dung bài nguồn")
            return item_id
        res = rewrite(art, it["title"], cfg)
        if not res["relevant"] or not res["body"]:
            db.news_update(item_id, status="skipped", error="AI: không liên quan kế toán/thuế")
            return item_id
        db.news_update(item_id, status="pending", title=res["title"] or it["title"],
                       summary=res["summary"], body=res["body"], fb_text=res["fb_text"],
                       image_url=art["image"] if cfg["use_images"] else "")
    except Exception as e:
        db.news_update(item_id, status="failed", error=str(e)[:300])
        db.log("error", f"news {it['url']}: {e}")
    return item_id


def run_once(cfg=None) -> dict:
    cfg = cfg or get_config()
    db.set_setting("newsagent_last_run", db.now())
    found = [it for it in search(cfg["keywords"], cfg["feeds"], cfg["max_age_days"])
             if not db.news_seen(it["url"])]
    made = []
    for it in found:
        if len(made) >= cfg["max_per_run"]:
            break
        item_id = process_url(it, cfg)
        item = db.news_get(item_id) if item_id else None
        if item and item["status"] == "pending":
            made.append(item_id)
            if cfg["auto_publish"]:
                publish_item(item_id, cfg)
    db.log("news", f"Tìm thấy {len(found)} bài mới, viết lại {len(made)} bài")
    return {"found": len(found), "written": len(made)}


def publish_item(item_id: int, cfg=None) -> dict:
    cfg = cfg or get_config()
    item = db.news_get(item_id)
    if not item or item["status"] not in ("pending", "failed"):
        raise ValueError("Bài không ở trạng thái chờ đăng")
    web_url, errors, web_ok = "", [], False
    slug = _unique_slug(slugify(item["title"]), item_id)
    db.news_update(item_id, slug=slug)
    item["slug"] = slug
    if cfg["post_to_web"]:
        web_ok = True                                  # trang /tin-tuc của phần mềm luôn có
        if cfg["wp_url"] and cfg["wp_user"] and cfg["wp_app_password"]:
            try:
                web_url = post_to_wordpress(item, cfg)
            except Exception as e:
                errors.append(str(e))
                web_ok = False
        if not web_url and cfg["public_url"]:
            web_url = f"{cfg['public_url']}/tin-tuc/{slug}"
    fb_id = ""
    if cfg["post_to_fb"]:
        try:
            fb_id = facebook.publish_post(item["fb_text"] or item["title"], web_url, item["image_url"])
        except FacebookError as e:
            errors.append(str(e))
    db.news_update(item_id, status="published" if (web_ok or fb_id) else "failed",
                   web_url=web_url, fb_post_id=fb_id, error="; ".join(errors)[:300],
                   published_at=db.now())
    db.log("news", f"Đăng '{item['title']}' → web: {web_url or '-'} / fb: {fb_id or '-'}")
    return db.news_get(item_id)


def tick():
    """Gọi từ vòng lặp lịch: đến giờ thì chạy 1 lượt."""
    cfg = get_config()
    if not cfg["enabled"] or not cfg["gemini_key"]:
        return
    if db.now() - (db.get_setting("newsagent_last_run", 0) or 0) < cfg["interval_hours"] * 3600:
        return
    try:
        run_once(cfg)
    except Exception as e:
        db.log("error", f"news agent: {e}")
