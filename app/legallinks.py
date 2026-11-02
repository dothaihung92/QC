"""Tự tìm văn bản pháp luật được nhắc trong bài (Nghị định, Thông tư, Luật, Công văn...) và gắn link THẬT.

Cách làm để không gắn link sai / link 404:
1. Tách số hiệu văn bản trong bài (vd "Nghị định 398/2026/NĐ-CP").
2. Tìm trên công cụ tìm kiếm (Bing, DuckDuckGo; có Gemini key thì thêm Google qua Gemini)
   — chỉ nhận kết quả thuộc trang văn bản pháp luật tin cậy.
3. Mở thử từng link: trang phải tồn tại và đúng số hiệu (trong địa chỉ hoặc tiêu đề trang).
4. Ghi nhớ kết quả (tìm được: 30 ngày, chưa tìm được: 12 giờ) để lần sau nhanh.
Không tìm được link chắc chắn thì giữ nguyên tên văn bản, không gắn gì.
"""
import html
import logging
import re
import time
import unicodedata
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import requests

from . import db

log = logging.getLogger("qc.legal")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
# Trang tin cậy, xếp theo thứ tự ưu tiên. (tên miền, đoạn đường dẫn bắt buộc)
TRUSTED = [
    ("thuvienphapluat.vn", "/van-ban/"),
    ("vanban.chinhphu.vn", ""),
    ("luatvietnam.vn", ""),
    ("congbao.chinhphu.vn", ""),
    ("mof.gov.vn", ""),
    ("gdt.gov.vn", ""),
    ("moj.gov.vn", ""),
]
OK_TTL = 30 * 86400
MISS_TTL = 12 * 3600
MAX_REFS = 8

KINDS = (r"Thông tư liên tịch|Thông tư|Nghị định|Nghị quyết|Quyết định|Công văn|Pháp lệnh|Chỉ thị|"
         r"Văn bản hợp nhất|Luật(?:\s+[A-ZÀ-Ỹa-zà-ỹđĐ]+){0,8}?")
# 398/2026/NĐ-CP · 18/2026/TT-BTC · 108/2025/QH15 · 01/2026/NQ-HĐND
FULL = r"\d{1,4}/\d{4}/[A-ZĐ]{1,8}\d{0,2}(?:-[A-ZĐ0-9]{1,10}){0,3}"
# Công văn 3897/CT-CS · 1234/TCT-CS (không có năm → bắt buộc có chữ "Công văn" phía trước)
SHORT = r"\d{1,6}/[A-ZĐ]{1,8}(?:-[A-ZĐ0-9]{1,10}){1,3}"
REF_RE = re.compile(
    rf"(?:(?P<kind>{KINDS})\s+(?:số\s+)?)?(?P<code>{FULL})"
    rf"|(?P<kind2>Công văn|Văn bản)\s+(?:số\s+)?(?P<code2>{SHORT})")
SUFFIX_KIND = [("NĐ-CP", "Nghị định"), ("TTLT", "Thông tư liên tịch"), ("TT-", "Thông tư"), ("/QH", "Luật"),
               ("NQ-", "Nghị quyết"), ("QĐ-", "Quyết định"), ("CT-TTG", "Chỉ thị")]


def _plain(s: str) -> str:
    s = unicodedata.normalize("NFD", (s or "").replace("đ", "d").replace("Đ", "D"))
    return "".join(c for c in s if unicodedata.category(c) != "Mn").upper()


def _slug(s: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "-", _plain(s)).strip("-")


def _has(want: str, text: str) -> bool:
    """Số hiệu (dạng slug) có trong chuỗi, đúng ranh giới — "18-2026-TT-BTC" không khớp "118-2026-TT-BTC"."""
    return f"-{want}-" in f"-{_slug(text)}-"


def find_refs(text: str) -> list:
    """Các văn bản được nhắc trong bài: [{"text", "code", "kind"}] — mỗi số hiệu một lần, theo thứ tự xuất hiện."""
    out, seen = [], set()
    for m in REF_RE.finditer(text or ""):
        code = (m.group("code") or m.group("code2") or "").upper()
        if not code or code in seen:
            continue
        kind = (m.group("kind") or m.group("kind2") or "").strip()
        if not kind:
            kind = next((k for suf, k in SUFFIX_KIND if suf in code), "Văn bản")
        if kind.lower().startswith("luật") and not m.group("kind"):
            kind = "Luật"
        seen.add(code)
        out.append({"text": m.group(0).strip(), "code": code, "kind": kind})
    return out


# ---------------------------------------------------------------- tìm kiếm

def _rank(url: str) -> int:
    host = urlparse(url).netloc.lower()
    for i, (dom, path) in enumerate(TRUSTED):
        if host == dom or host.endswith("." + dom):
            return i if (not path or path in urlparse(url).path) else -1
    return -1


def _bing(query: str) -> list:
    r = requests.get(f"https://www.bing.com/search?format=rss&setlang=vi&cc=VN&q={quote_plus(query)}",
                     headers={"User-Agent": UA}, timeout=15)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    return [((it.findtext("link") or "").strip(), (it.findtext("title") or "").strip())
            for it in root.iter("item")]


def _ddg(query: str) -> list:
    r = requests.get(f"https://html.duckduckgo.com/html/?q={quote_plus(query)}",
                     headers={"User-Agent": UA}, timeout=15)
    r.raise_for_status()
    out = []
    for href, title in re.findall(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', r.text, re.S):
        href = html.unescape(href)
        if "uddg=" in href:
            href = unquote(parse_qs(urlparse(href).query).get("uddg", [""])[0])
        out.append((href, html.unescape(re.sub(r"<[^>]+>", "", title))))
    return out


def _tvpl(query: str) -> list:
    """Ô tìm kiếm của chính thuvienphapluat.vn (có thể bị chặn máy — khi đó dùng nguồn khác)."""
    r = requests.get(f"https://thuvienphapluat.vn/page/tim-van-ban.aspx?keyword={quote_plus(query)}&sort=1",
                     headers={"User-Agent": UA, "Accept-Language": "vi"}, timeout=15)
    r.raise_for_status()
    out = []
    for href, title in re.findall(r'<a[^>]+href="((?:https://thuvienphapluat\.vn)?/van-ban/[^"]+?\.aspx)"[^>]*>(.*?)</a>',
                                  r.text, re.S):
        url = href if href.startswith("http") else "https://thuvienphapluat.vn" + href
        out.append((html.unescape(url), html.unescape(re.sub(r"<[^>]+>", "", title)).strip()))
    return out


def _gemini(ref: dict, key: str, model: str = "gemini-2.5-flash") -> list:
    """Hỏi Google (qua Gemini + Google Search) — lấy link từ nguồn Google trả về, không tin URL AI tự viết."""
    prompt = (f'Tìm trang văn bản gốc của "{ref["kind"]} {ref["code"]}" (Việt Nam) trên thuvienphapluat.vn, '
              "vanban.chinhphu.vn hoặc luatvietnam.vn. Chỉ trả lời các đường link tìm được.")
    r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                      headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                      json={"contents": [{"parts": [{"text": prompt}]}], "tools": [{"google_search": {}}],
                            "generationConfig": {"temperature": 0}}, timeout=60)
    r.raise_for_status()
    cand = (r.json().get("candidates") or [{}])[0]
    out = []
    for ch in (cand.get("groundingMetadata") or {}).get("groundingChunks") or []:
        uri = (ch.get("web") or {}).get("uri", "")
        if "grounding-api-redirect" in uri:          # link chuyển hướng của Google → lấy địa chỉ thật
            try:
                uri = requests.head(uri, allow_redirects=False, timeout=10).headers.get("Location", "")
            except requests.RequestException:
                uri = ""
        if uri:
            out.append((uri, (ch.get("web") or {}).get("title", "")))
    text = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts") or [])
    out += [(u.rstrip(").,;"), "") for u in re.findall(r"https?://[^\s<>\"')\]]+", text)]
    return out


def verify(url: str, code: str, title: str = "") -> bool:
    """Link phải tồn tại và đúng văn bản: số hiệu nằm trong địa chỉ, hoặc trong tiêu đề trang."""
    if _rank(url) < 0:
        return False
    want = _slug(code)
    in_url = _has(want, unquote(url))
    try:
        r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "vi"}, timeout=15)
    except requests.RequestException:
        return in_url                                  # mạng chập chờn: tin địa chỉ do công cụ tìm kiếm trả về
    if r.status_code in (404, 410) or (r.ok and "404" in urlparse(r.url).path):
        return False
    if not r.ok:                                       # trang chặn máy (403/429...) → dựa vào địa chỉ
        return in_url
    if not r.encoding or r.encoding.lower() == "iso-8859-1":
        r.encoding = r.apparent_encoding
    page = r.text[:400000]
    m = re.search(r"<title[^>]*>(.*?)</title>", page, re.S | re.I)
    if in_url or (m and _has(want, html.unescape(m.group(1)))):
        return True
    # vanban.chinhphu.vn: tiêu đề trang chung chung → xem số hiệu trong nội dung
    return urlparse(url).netloc.endswith("vanban.chinhphu.vn") and _has(want, html.unescape(re.sub(r"<[^>]+>", " ", page)))


def lookup(ref: dict, gemini_key: str = "", fresh: bool = False) -> dict:
    """Trả về {"url", "title"} (url rỗng nếu không tìm được link chắc chắn)."""
    code = ref["code"]
    ck = f"legal:{code}"
    hit = None if fresh else db.get_setting(ck)
    if hit and time.time() - hit.get("t", 0) < (OK_TTL if hit.get("url") else MISS_TTL):
        return {"url": hit.get("url", ""), "title": hit.get("title", "")}
    kind = ref["kind"] if ref["kind"] != "Văn bản" else ""
    searches = [(_tvpl, code),
                (_bing, f'"{code}" {kind} site:thuvienphapluat.vn OR site:vanban.chinhphu.vn OR site:luatvietnam.vn'),
                (_ddg, f'"{code}" {kind} thuvienphapluat'),
                (_bing, f"{kind} {code}")]
    found, tried = [], set()
    want = _slug(code)
    for src, q in searches:
        try:
            found += [(u, t) for u, t in src(q) if _rank(u) >= 0]
        except Exception as e:                        # noqa: BLE001 — một nguồn lỗi thì thử nguồn khác
            log.info("legal search %s %s: %s", src.__name__, q, e)
        if any(_has(want, unquote(u)) or _has(want, t) for u, t in found):
            break                                     # đã có kết quả đúng số hiệu → khỏi tìm thêm
    if not found and gemini_key:
        try:
            found += [(u, t) for u, t in _gemini(ref, gemini_key) if _rank(u) >= 0]
        except Exception as e:                        # noqa: BLE001
            log.info("legal gemini %s: %s", code, e)
    # ưu tiên: địa chỉ/tiêu đề có đúng số hiệu, rồi trang tin cậy hơn
    found.sort(key=lambda x: (not (_has(want, unquote(x[0])) or _has(want, x[1])), _rank(x[0])))
    res = {"url": "", "title": ""}
    for url, title in found:
        url = url.split("#")[0]
        if url in tried:
            continue
        tried.add(url)
        if verify(url, code, title):
            res = {"url": url, "title": title}
            break
        if len(tried) >= 6:
            break
    db.set_setting(ck, res | {"t": int(time.time())})
    return res


def resolve(text: str, gemini_key: str = "") -> list:
    """Tìm link cho mọi văn bản trong bài (song song). Trả về [{"text","code","kind","url","title"}]."""
    refs = find_refs(text)[:MAX_REFS]
    if not refs:
        return []
    with ThreadPoolExecutor(max_workers=4) as ex:
        links = list(ex.map(lambda r: lookup(r, gemini_key), refs))
    return [r | l for r, l in zip(refs, links)]


# ---------------------------------------------------------------- gắn link vào bài

def _ref_pattern(ref: dict):
    """Khớp cả cụm "Nghị định (số) 398/2026/NĐ-CP" hoặc chỉ số hiệu."""
    return re.compile(rf"(?:(?:{KINDS}|Công văn|Văn bản)\s+(?:số\s+)?)?{re.escape(ref['code'])}", re.I)


def link_markdown(body: str, refs: list) -> str:
    """Bài web dạng markdown: gắn [tên văn bản](link) ở lần nhắc đầu tiên (không gắn trong tiêu đề ##),
    thêm mục "Văn bản pháp luật liên quan" ở cuối."""
    linked = []
    for ref in refs:
        if not ref.get("url") or ref["url"] in body:
            if ref.get("url"):
                linked.append(ref)
            continue
        pat = _ref_pattern(ref)
        out, done = [], False
        for line in body.split("\n"):
            if not done and not line.lstrip().startswith("#"):
                spans = [(m.start(), m.end()) for m in re.finditer(r"\[[^\]]*\]\([^)]*\)", line)]
                for m in pat.finditer(line):
                    if any(a <= m.start() < b for a, b in spans):
                        continue
                    txt = m.group(0)
                    line = f"{line[:m.start()]}[{txt}]({ref['url']}){line[m.end():]}"
                    done = True
                    break
            out.append(line)
        body = "\n".join(out)
        if done:
            linked.append(ref)
    if linked and "## Văn bản pháp luật liên quan" not in body:
        body = body.rstrip() + "\n\n## Văn bản pháp luật liên quan\n\n" + "\n".join(
            f"- [{r['kind']} {r['code']}]({r['url']})" for r in linked)
    return body


def link_html(parts: list, refs: list) -> list:
    """Bài HTML (tab Viết bài SEO): gắn <a> ở lần nhắc đầu tiên trên toàn bài, không đụng thẻ/link có sẵn."""
    joined = "".join(parts)
    todo = [r for r in refs if r.get("url") and html.escape(r["url"]) not in joined and r["url"] not in joined]
    out = []
    for part in parts:
        tokens = re.split(r"(<[^>]+>)", part or "")
        in_a = in_head = 0
        for i, tok in enumerate(tokens):
            if tok.startswith("<"):
                t = tok.lower()
                if re.match(r"<a[\s>]", t):
                    in_a += 1
                elif t.startswith("</a"):
                    in_a = max(0, in_a - 1)
                elif re.match(r"<h[1-6][\s>]", t):
                    in_head += 1
                elif re.match(r"</h[1-6]", t):
                    in_head = max(0, in_head - 1)
                continue
            if in_a or in_head or not tok.strip():
                continue
            for ref in list(todo):
                m = _ref_pattern(ref).search(tok)
                if m:
                    a = (f'<a href="{html.escape(ref["url"])}" target="_blank" rel="noopener nofollow" '
                         f'title="Xem văn bản gốc">{m.group(0)}</a>')
                    tok = tok[:m.start()] + a + tok[m.end():]
                    todo.remove(ref)
                    break                                  # mỗi đoạn chữ gắn tối đa 1 link
            tokens[i] = tok
        out.append("".join(tokens))
    return out


def fb_footer(fb_text: str, refs: list) -> str:
    """Bài Facebook: thêm dòng "📄 Văn bản gốc" (link bấm được) nếu chưa có."""
    rows = [f"• {r['kind']} {r['code']}: {r['url']}" for r in refs if r.get("url") and r["url"] not in fb_text][:3]
    if not rows:
        return fb_text
    return fb_text.rstrip() + "\n\n📄 Xem văn bản gốc:\n" + "\n".join(rows)
