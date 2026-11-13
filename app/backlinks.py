"""Hệ thống đi backlink CHẤT LƯỢNG (white-hat) cho website dịch vụ kế toán.

Không spam, không mua bán link, không đăng hàng loạt tự động. Phần mềm làm các việc nặng nhọc & dễ sai:
  1. Hồ sơ website (thương hiệu, NAP, từ khóa ↔ trang đích, đối thủ).
  2. Danh mục cơ hội backlink phù hợp ngành kế toán/thuế + tự tìm trang tiềm năng (Bing/DuckDuckGo) rồi chấm điểm chất lượng:
     đúng chủ đề, có spam không, có noindex không, nhiều link ra ngoài không, có nhận guest post không, có email liên hệ không.
  3. Sổ theo dõi backlink: ý tưởng → liên hệ → phản hồi → đã đăng → LIVE / mất link, hẹn ngày follow-up.
  4. Kiểm tra link thật: trang có còn link về website không, anchor gì, dofollow/nofollow/sponsored/ugc, trang có noindex không.
     Tự kiểm tra lại hằng ngày, báo khi mất link.
  5. Quản lý anchor text: tỉ lệ thương hiệu / URL / một phần / chung chung / chính xác — cảnh báo khi quá tay, gợi ý anchor tiếp theo.
  6. Công cụ tìm cơ hội: quét link chết (broken link building), trang nhắc thương hiệu nhưng chưa gắn link.
  7. AI soạn email chào hàng, bài guest post, mô tả danh bạ, bình luận chuyên gia cho báo chí... (chỉ dùng thông tin trong hồ sơ).
  8. Kế hoạch tuần: nhịp độ an toàn (không tăng link đột biến), việc cần làm hôm nay.

Mọi đường link đều do trang thật trả về và được kiểm tra bằng cách mở trang — không có link do AI tự bịa.
"""
import csv
import html as htmllib
import io
import ipaddress
import json
import re
import socket
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from urllib.parse import quote_plus, urljoin, urlparse

import requests

from . import db

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36")
MAX_PAGE = 2 * 1024 * 1024                    # chỉ đọc tối đa 2 MB mỗi trang
DAY = 86400

STATUSES = {"idea": "Ý tưởng", "contacted": "Đã liên hệ", "replied": "Đã phản hồi", "negotiating": "Đang trao đổi",
            "published": "Đã đăng (chờ kiểm tra)", "live": "Đang sống ✓", "lost": "Mất link", "rejected": "Từ chối / bỏ"}
ACTIVE = ("idea", "contacted", "replied", "negotiating")
RELS = ("", "dofollow", "nofollow", "sponsored", "ugc")
ANCHOR_TYPES = {"brand": "Thương hiệu", "naked": "URL trần", "partial": "Một phần từ khóa", "generic": "Chung chung",
                "exact": "Từ khóa chính xác", "image": "Link ảnh"}
# Tỉ lệ anchor tự nhiên (%): [thấp, cao]. Từ khóa chính xác nhiều là dấu hiệu đi link thao túng → Google phạt.
ANCHOR_TARGET = {"brand": (35, 50), "naked": (15, 25), "partial": (15, 25), "generic": (8, 15), "exact": (0, 6), "image": (0, 8)}
GENERIC_ANCHORS = ["xem thêm", "tại đây", "tìm hiểu thêm", "click vào đây", "truy cập", "website", "trang web", "đọc thêm",
                   "nhấn vào đây", "link", "nguồn", "theo dõi", "xem chi tiết", "here", "read more", "click here", "source"]

TOPIC_WORDS = ["kế toán", "thuế", "hóa đơn", "doanh nghiệp", "tài chính", "báo cáo tài chính", "kiểm toán", "quyết toán",
               "bảo hiểm xã hội", "tiền lương", "khởi nghiệp", "kinh doanh", "đăng ký kinh doanh", "chứng từ", "sổ sách",
               "ngân hàng", "đầu tư", "luật", "pháp lý", "nhân sự", "tờ khai", "vat", "gtgt", "tncn", "tndn"]
SPAM_WORDS = r"cá độ|casino|nhà cái|sòng bạc|xóc đĩa|tài xỉu|slot game|nổ hũ|viagra|cialis|sex|18\+|vay tiền nhanh|vay nóng|" \
             r"bắn cá|đá gà|lô đề|soi cầu|xổ số|thuốc tăng|bet365|w88|fb88|link đen|bán backlink|mua backlink|buy backlinks"
GUEST_WORDS = r"guest\s*post|viết bài cho chúng tôi|write for us|gửi bài|nhận đăng bài|đăng bài cộng tác|cộng tác viên|" \
              r"cộng tác bài viết|đóng góp bài viết|liên kết website|trao đổi link|submit (?:a )?(?:post|article)|đăng ký đăng bài|" \
              r"đăng tin miễn phí|thêm website|đăng ký doanh nghiệp|danh bạ"
SOCIAL_SKIP = ("facebook.com", "youtube.com", "tiktok.com", "instagram.com", "twitter.com", "x.com", "pinterest.com", "linkedin.com",
               "shopee.vn", "lazada.vn", "tiki.vn", "google.com", "bing.com", "wikipedia.org", "zalo.me", "t.me", "reddit.com")

# ------------------------------------------------------------------ danh mục cơ hội backlink

OPPORTUNITIES = [
    {"id": "profiles", "name": "Hồ sơ doanh nghiệp chuẩn NAP (làm đầu tiên)", "tier": "A", "effort": "Thấp", "link": "Phần lớn nofollow — nhưng xây độ tin cậy thương hiệu",
     "desc": "Tên – địa chỉ – điện thoại (NAP) GIỐNG NHAU ở mọi nơi. Google dùng để xác nhận doanh nghiệp là thật.",
     "how": "Tự đăng ký (miễn phí): Google Business Profile, Bing Places, Apple Business Connect, Fanpage Facebook, LinkedIn Company, kênh YouTube, "
            "Zalo Official Account, Pinterest, X (Twitter). Điền website + mô tả (dùng nút AI 'Mô tả danh bạ'). Sau đó thêm từng nơi vào sổ theo dõi.",
     "queries": [], "ai": "directory_desc", "checklist": ["Google Business Profile", "Bing Places", "Apple Business Connect", "Facebook Page", "LinkedIn Company",
                                                          "YouTube", "Zalo OA", "Pinterest", "X (Twitter)"]},
    {"id": "directory", "name": "Danh bạ doanh nghiệp Việt Nam uy tín", "tier": "B", "effort": "Thấp", "link": "Dofollow / nofollow tùy trang",
     "desc": "Chỉ chọn danh bạ có kiểm duyệt, có thông tin thật, cùng ngành. Tránh danh bạ rác đăng tràn lan.",
     "how": "Chạy 'Tự tìm trang tiềm năng' → ưu tiên trang điểm A/B, không spam. Mỗi tuần đăng 2–3 nơi, không đăng hàng loạt.",
     "queries": ['danh bạ doanh nghiệp dịch vụ kế toán đăng ký miễn phí', '"danh bạ doanh nghiệp" "kế toán" thêm website', 'danh bạ công ty dịch vụ kế toán thuế {city}'], "ai": "directory_desc"},
    {"id": "guest", "name": "Guest post: blog / tạp chí kế toán – tài chính – doanh nghiệp", "tier": "A", "effort": "Cao", "link": "Dofollow trong bài (nếu trang cho phép)",
     "desc": "Bài viết chuyên môn có giá trị thật, đăng trên trang cùng chủ đề. Link nằm trong thân bài, anchor tự nhiên. Chất lượng cao nhất.",
     "how": "Tìm trang nhận bài → chấm điểm → AI soạn email chào hàng + bài viết (1 link duy nhất, anchor tự nhiên) → gửi → theo dõi.",
     "queries": ['"viết bài cho chúng tôi" kế toán thuế', '"nhận đăng bài" kế toán doanh nghiệp', '"guest post" kế toán thuế doanh nghiệp', '"gửi bài" "cộng tác viên" tài chính kế toán',
                 'intitle:"viết bài cho" tài chính doanh nghiệp'], "ai": "guest_article"},
    {"id": "pr", "name": "Báo chí & chuyên gia bình luận (Digital PR)", "tier": "A", "effort": "Trung bình", "link": "Dofollow hoặc nhắc tên (giá trị rất cao)",
     "desc": "Phóng viên mảng kinh tế – thuế cần ý kiến chuyên gia khi có chính sách mới. Gửi nhận định ngắn, đúng luật, có số liệu thật.",
     "how": "Mỗi khi có thay đổi chính sách thuế/hóa đơn: AI soạn nhận định chuyên gia + email gửi phóng viên/biên tập. Chỉ gửi khi có điều gì đáng nói.",
     "queries": ['báo kinh tế thuế chính sách mới chuyên gia kế toán nhận định', 'chuyên mục thuế kế toán "liên hệ" "tòa soạn" doanh nghiệp', 'podcast tài chính doanh nghiệp khách mời kế toán'], "ai": "expert_comment"},
    {"id": "resource", "name": "Trang tài nguyên / liên kết hữu ích", "tier": "A", "effort": "Trung bình", "link": "Dofollow",
     "desc": "Các trang tổng hợp tài liệu, công cụ, liên kết hữu ích cho kế toán, doanh nghiệp nhỏ, startup. Xin được thêm tài nguyên của bạn (biểu mẫu, công cụ, hướng dẫn).",
     "how": "Cần có 'tài sản liên kết' đáng chia sẻ (xem mục Tài sản liên kết). Chào hàng ngắn gọn, nêu rõ trang đó được lợi gì.",
     "queries": ['intitle:"tài nguyên" kế toán thuế doanh nghiệp', 'intitle:"liên kết hữu ích" kế toán thuế', 'inurl:resources kế toán thuế doanh nghiệp', '"website hữu ích" cho kế toán', 'tổng hợp biểu mẫu kế toán thuế tải miễn phí'], "ai": "pitch_resource"},
    {"id": "broken", "name": "Link chết (Broken link building)", "tier": "A", "effort": "Trung bình", "link": "Dofollow",
     "desc": "Tìm trang có link hỏng về chủ đề thuế/kế toán, báo cho chủ trang và đề xuất bài của bạn thay thế. Họ được lợi (sửa lỗi) nên tỉ lệ đồng ý cao.",
     "how": "Dùng công cụ 'Quét link chết' bên dưới với trang tài nguyên/bài tổng hợp → chọn link hỏng khớp với bài của bạn → AI soạn email.",
     "queries": ['bài tổng hợp văn bản thuế kế toán nguồn tham khảo', 'danh sách website kế toán thuế hữu ích', 'hướng dẫn kê khai thuế tổng hợp liên kết'], "ai": "pitch_broken"},
    {"id": "mention", "name": "Nhắc thương hiệu nhưng chưa gắn link", "tier": "A", "effort": "Thấp", "link": "Dofollow",
     "desc": "Trang đã nhắc tên công ty bạn nhưng chưa có link — chỉ cần nhờ họ thêm link, tỉ lệ thành công cao nhất.",
     "how": "Chạy tìm với tên thương hiệu → phần mềm mở từng trang, báo 'có nhắc tên – chưa link' → AI soạn email nhờ thêm link.",
     "queries": ['"{brand}" -site:{domain}', '"{brand}" kế toán -site:{domain}', '"{brand}" dịch vụ kế toán {city}'], "ai": "pitch_mention"},
    {"id": "competitor", "name": "Học từ đối thủ", "tier": "B", "effort": "Trung bình", "link": "Tùy trang",
     "desc": "Trang nào đã nhắc/liên kết tới đối thủ thì có khả năng nhắc/liên kết tới bạn nếu bạn có giá trị tương đương hoặc tốt hơn.",
     "how": "Nhập tên/tên miền đối thủ ở Hồ sơ → tìm các trang nhắc họ → lọc trang chất lượng rồi liên hệ bằng nội dung riêng của bạn (không sao chép).",
     "queries": ['"{competitor}" -site:{competitor}', '"{competitor}" review đánh giá dịch vụ kế toán'], "ai": "pitch_guest"},
    {"id": "partners", "name": "Đối tác – khách hàng – hiệp hội – trường học", "tier": "A", "effort": "Trung bình", "link": "Dofollow (link thương hiệu thật)",
     "desc": "Link từ khách hàng (case study/cảm nhận), nhà cung cấp phần mềm bạn đang dùng (testimonial), hiệp hội ngành, câu lạc bộ doanh nghiệp, trường đại học (hợp tác thực tập, tài trợ).",
     "how": "Lập danh sách đối tác thật, đề nghị: viết cảm nhận/case study (có xin phép), tham gia hiệp hội, tài trợ học bổng/sự kiện, mời nói chuyện chuyên đề.",
     "queries": ['hiệp hội doanh nghiệp danh sách hội viên {city}', 'site:edu.vn kế toán đối tác doanh nghiệp tuyển thực tập', 'câu lạc bộ doanh nghiệp nhỏ và vừa hội viên {city}'], "ai": "pitch_partner"},
    {"id": "community", "name": "Diễn đàn / hỏi đáp: trả lời hữu ích", "tier": "C", "effort": "Thấp", "link": "Thường nofollow — giá trị là uy tín & khách hàng",
     "desc": "Trả lời CÂU HỎI THẬT về thuế, kế toán một cách chi tiết. Chỉ nhắc link khi thật sự giúp người hỏi. Không chèn link hàng loạt (bị cấm & bị phạt).",
     "how": "Chọn câu hỏi chưa có đáp án tốt → AI soạn nháp đáp án chi tiết → bạn đọc, sửa → đăng bằng tài khoản thật, ghi tên người thật.",
     "queries": ['diễn đàn kế toán hỏi đáp thuế', 'hỏi đáp thuế tncn hóa đơn diễn đàn chuyên gia trả lời', 'cộng đồng kế toán thảo luận quyết toán'], "ai": "qa_answer"},
    {"id": "assets", "name": "Tài sản liên kết (nội dung người ta muốn dẫn về)", "tier": "A", "effort": "Cao", "link": "Dofollow tự nhiên, bền vững nhất",
     "desc": "Công cụ/biểu mẫu/bảng tra hữu ích: máy tính thuế TNCN, lịch nộp tờ khai, checklist quyết toán cuối năm, bảng mức phạt chậm nộp, mẫu hợp đồng dịch vụ kế toán...",
     "how": "Làm 1–2 tài sản thật tốt trên website → rồi chào hàng ở các mục Tài nguyên, Báo chí, Hiệp hội. Dùng nút AI 'Ý tưởng tài sản liên kết'.",
     "queries": [], "ai": "asset_ideas"},
]

OPP = {o["id"]: o for o in OPPORTUNITIES}

AVOID = [
    "Mua/bán backlink, gói 'đi 500 link giá rẻ', mạng lưới PBN → Google phạt thủ công, mất thứ hạng.",
    "Spam bình luận blog, spam diễn đàn, đăng tài khoản ảo hàng loạt bằng tool → link bị xóa, có thể bị cấm.",
    "Quá nhiều anchor là từ khóa chính xác (vd 'dịch vụ kế toán') → tín hiệu thao túng. Giữ ≤ 6%.",
    "Trao đổi link chéo (A↔B) tràn lan hoặc link từ trang cờ bạc, đen, nội dung không liên quan.",
    "Tăng link đột biến (vd 0 → 100 link/tuần). Giữ nhịp 3–6 link chất lượng mỗi tuần.",
]


# ------------------------------------------------------------------ hồ sơ website

SITE_DEFAULT = {"url": "", "brand": "", "phone": "", "address": "", "email": "", "city": "", "services": "",
                "description": "", "keywords": "", "competitors": "", "socials": "", "weekly_target": 4, "auto_check": True}


def get_site() -> dict:
    s = dict(SITE_DEFAULT)
    s.update(db.get_setting("backlink_site", {}) or {})
    return s


def save_site(body: dict) -> dict:
    s = get_site()
    for k, d in SITE_DEFAULT.items():
        if k not in body:
            continue
        v = body[k]
        if isinstance(d, bool):
            v = bool(v)
        elif isinstance(d, int):
            try:
                v = max(1, min(50, int(v)))
            except (TypeError, ValueError):
                v = d
        else:
            v = str(v or "").strip()
        s[k] = v
    if s["url"] and not s["url"].startswith(("http://", "https://")):
        s["url"] = "https://" + s["url"]
    db.set_setting("backlink_site", s)
    return s


def domain_of(url: str) -> str:
    h = (urlparse(url if "//" in (url or "") else "//" + (url or "")).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def site_domain(site: dict = None) -> str:
    return domain_of((site or get_site())["url"])


def keywords(site: dict = None) -> list:
    """[(từ khóa, trang đích)] — dòng 'từ khóa | https://trang-đích' (trang đích bỏ trống = trang chủ)."""
    site = site or get_site()
    out = []
    for line in re.split(r"[\n;]+", site.get("keywords", "")):
        kw, _, url = (x.strip() for x in line.partition("|"))
        if kw:
            out.append((kw, url if url.startswith("http") else site.get("url", "")))
    return out


def _lines(s: str) -> list:
    return [x.strip() for x in re.split(r"[\n,;]+", s or "") if x.strip()]


# ------------------------------------------------------------------ tải trang an toàn

class FetchError(Exception):
    pass


def _public_host(host: str):
    """Chặn địa chỉ nội bộ (không để phần mềm bị lợi dụng quét mạng LAN của người dùng)."""
    try:
        for _f, _t, _p, _c, addr in socket.getaddrinfo(host, None):
            ip = ipaddress.ip_address(addr[0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                raise FetchError("Địa chỉ nội bộ — không được phép")
    except socket.gaierror:
        raise FetchError("Không phân giải được tên miền")


def fetch_page(url: str, timeout: int = 15, limit: int = MAX_PAGE) -> tuple:
    """(mã trạng thái, địa chỉ cuối cùng, nội dung html) — theo dõi chuyển hướng thủ công, mỗi chặng đều kiểm tra địa chỉ."""
    cur = url
    for _ in range(6):
        p = urlparse(cur)
        if p.scheme not in ("http", "https") or not p.hostname:
            raise FetchError("Địa chỉ không hợp lệ")
        _public_host(p.hostname)
        try:
            r = requests.get(cur, headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml",
                                           "Accept-Language": "vi,en;q=0.8"},
                             timeout=timeout, allow_redirects=False, stream=True)
        except requests.RequestException as e:
            raise FetchError(f"Không mở được trang ({type(e).__name__})")
        if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("Location"):
            cur = urljoin(cur, r.headers["Location"])
            r.close()
            continue
        data = b""
        try:
            for chunk in r.iter_content(65536):
                data += chunk
                if len(data) > limit:
                    break
        except requests.RequestException:
            pass
        enc = r.encoding if r.encoding and "iso-8859" not in r.encoding.lower() else None
        if not enc:
            m = re.search(rb'charset=["\']?([\w-]+)', data[:4096])
            enc = (m[1].decode("ascii", "ignore") if m else "utf-8")
        r.close()
        try:
            text = data.decode(enc, errors="replace")
        except LookupError:
            text = data.decode("utf-8", errors="replace")
        return r.status_code, cur, text
    raise FetchError("Chuyển hướng quá nhiều lần")


# ------------------------------------------------------------------ phân tích trang

class _Page(HTMLParser):
    def __init__(self, base: str):
        super().__init__(convert_charrefs=True)
        self.base, self.title, self.desc, self.robots, self.lang = base, "", "", "", ""
        self.links, self.text, self.emails = [], [], []
        self._in_title = False
        self._skip = 0
        self._a = None

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        if tag == "html":
            self.lang = a.get("lang", "").lower()
        elif tag == "title":
            self._in_title = True
        elif tag in ("script", "style", "noscript", "svg"):
            self._skip += 1
        elif tag == "meta":
            n = a.get("name", "").lower()
            if n == "robots":
                self.robots = a.get("content", "").lower()
            elif n == "description":
                self.desc = a.get("content", "")
        elif tag == "a" and a.get("href"):
            href = a["href"].strip()
            if href.lower().startswith("mailto:"):
                self.emails.append(href[7:].split("?")[0].strip())
            elif not href.startswith(("#", "javascript:", "tel:")):
                self._a = {"href": urljoin(self.base, href), "rel": a.get("rel", "").lower(), "text": [], "img": False,
                           "alt": ""}
        elif tag == "img" and self._a is not None:
            self._a["img"] = True
            self._a["alt"] = a.get("alt", "")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag in ("script", "style", "noscript", "svg") and self._skip:
            self._skip -= 1
        elif tag == "a" and self._a is not None:
            self._a["text"] = re.sub(r"\s+", " ", " ".join(self._a["text"])).strip()
            self.links.append(self._a)
            self._a = None

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.text.append(data)
            if self._a is not None:
                self._a["text"].append(data)


def parse_page(page_html: str, url: str, site: dict = None) -> dict:
    """Đọc 1 trang: tiêu đề, link về website của bạn (anchor, rel), có nhắc thương hiệu không, điểm chủ đề, dấu hiệu spam..."""
    site = site or get_site()
    p = _Page(url)
    try:
        p.feed(page_html)
        p.close()
    except Exception:  # noqa: BLE001 — html lỗi vẫn lấy được phần đã đọc
        pass
    mine = site_domain(site)
    text = re.sub(r"\s+", " ", " ".join(p.text)).strip()
    low = (p.title + " " + p.desc + " " + text).lower()
    own = domain_of(url)
    to_me, outbound = [], set()
    for a in p.links:
        d = domain_of(a["href"])
        if mine and (d == mine or d.endswith("." + mine)):
            rel = a["rel"]
            kind = ("sponsored" if "sponsored" in rel else "ugc" if "ugc" in rel else "nofollow" if "nofollow" in rel else "dofollow")
            anchor = a["text"] or (f"[ảnh] {a['alt']}".strip() if a["img"] else "")
            to_me.append({"href": a["href"], "anchor": anchor, "rel": kind, "image": bool(a["img"] and not a["text"])})
        elif d and d != own and not d.endswith("." + own):
            outbound.add(d)
    brand = (site.get("brand") or "").strip().lower()
    topic_hits = sum(1 for w in TOPIC_WORDS if w in low)
    words = len(text.split())
    noindex = "noindex" in p.robots
    spam = re.findall(SPAM_WORDS, low)
    emails = [e for e in dict.fromkeys(p.emails) if "@" in e][:3]
    if not emails:
        emails = [e for e in dict.fromkeys(re.findall(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)) if not e.endswith((".png", ".jpg"))][:3]
    return {"title": htmllib.unescape(p.title).strip()[:160], "description": p.desc[:200], "lang": p.lang, "words": words,
            "noindex": noindex, "robots": p.robots, "https": url.startswith("https://"), "outbound": len(outbound),
            "topic_hits": topic_hits, "spam": sorted(set(spam))[:4], "guest": bool(re.search(GUEST_WORDS, low)),
            "emails": emails, "links_to_me": to_me, "mentions_brand": bool(brand and brand in low),
            "domain": own}


def quality(a: dict, final_url: str = "") -> dict:
    """Điểm 0–100 + hạng A/B/C + lý do. Trang spam / noindex / lạc chủ đề bị loại hoặc trừ nặng."""
    s, why, flags = 0, [], []
    d = a.get("domain", "")
    s += min(35, a["topic_hits"] * 5)
    if a["topic_hits"] >= 4:
        why.append("đúng chủ đề kế toán/thuế")
    elif a["topic_hits"] <= 1:
        flags.append("ít liên quan chủ đề")
    if a["https"]:
        s += 5
    else:
        flags.append("không HTTPS")
    if a["noindex"]:
        s -= 30
        flags.append("trang noindex (Google không lập chỉ mục)")
    else:
        s += 10
    if a["outbound"] > 150:
        s -= 15
        flags.append(f"quá nhiều link ra ngoài ({a['outbound']})")
    elif a["outbound"] <= 80:
        s += 10
    if a["words"] >= 600:
        s += 10
        why.append("nội dung dài")
    elif a["words"] < 150:
        flags.append("nội dung mỏng")
    if a["spam"]:
        s -= 60
        flags.append("dấu hiệu spam: " + ", ".join(a["spam"]))
    if a["emails"]:
        s += 5
        why.append("có email liên hệ")
    if a["guest"]:
        s += 10
        why.append("có dấu hiệu nhận bài / thêm website")
    if d.endswith((".edu.vn", ".gov.vn", ".edu", ".gov")) or ".edu." in d or ".gov." in d:
        s += 12
        why.append("tên miền giáo dục/nhà nước")
    if a["lang"].startswith("vi") or re.search(r"[ăâđêôơưạảấầẩẫậắằẳẵặẹẻẽếềểễệ]", a["title"].lower()):
        s += 5
    if a["title"]:
        s += 5
    s = max(0, min(100, s))
    tier = "A" if s >= 70 else "B" if s >= 50 else "C"
    return {"score": s, "tier": tier, "why": why, "flags": flags, "reject": bool(a["spam"]) or a["noindex"] or a["topic_hits"] == 0}


def analyze(url: str, site: dict = None) -> dict:
    """Mở trang → thông tin + điểm chất lượng. Lỗi mở trang trả {"ok": False, "error": ...}."""
    try:
        status, final, body = fetch_page(url)
    except FetchError as e:
        return {"ok": False, "url": url, "error": str(e)}
    if status >= 400:
        return {"ok": False, "url": url, "error": f"Trang trả mã {status}", "status": status}
    a = parse_page(body, final, site)
    q = quality(a, final)
    return {"ok": True, "url": final, "status": status, **a, **q}


def _norm_url(u: str) -> str:
    """So sánh địa chỉ không phân biệt http/https, www, dấu / cuối, #."""
    return re.sub(r"^https?://(?:www\.)?", "", (u or "").strip().lower().split("#")[0]).rstrip("/")


def check_link(page_url: str, target_url: str = "", site: dict = None) -> dict:
    """Trang có còn link về website không? {"state": ok|not_found|noindex|error, "links": [...], "rel", "anchor"}"""
    site = site or get_site()
    try:
        status, final, body = fetch_page(page_url)
    except FetchError as e:
        return {"state": "error", "error": str(e), "links": []}
    if status >= 400:
        return {"state": "error", "error": f"Trang trả mã {status}", "status": status, "links": []}
    a = parse_page(body, final, site)
    links = a["links_to_me"]
    if target_url:                                     # có chỉ định trang đích → ưu tiên link khớp trang đó
        t = _norm_url(target_url)
        match = [x for x in links if _norm_url(x["href"]) == t]
        links = match or links
    if not links:
        return {"state": "not_found", "status": status, "links": [], "noindex": a["noindex"], "mentions_brand": a["mentions_brand"]}
    best = next((x for x in links if x["rel"] == "dofollow"), links[0])
    return {"state": "noindex" if a["noindex"] else "ok", "status": status, "links": links[:10], "rel": best["rel"],
            "anchor": best["anchor"], "href": best["href"], "noindex": a["noindex"], "image": best["image"]}


# ------------------------------------------------------------------ quét link chết

def _alive(url: str) -> str:
    """ok | dead | unknown — 403/429 coi là 'unknown' (trang chặn robot, chưa chắc hỏng)."""
    try:
        p = urlparse(url)
        _public_host(p.hostname or "")
        r = requests.head(url, headers={"User-Agent": UA}, timeout=10, allow_redirects=True)
        if r.status_code in (403, 405, 429, 501, 999) or r.status_code >= 500:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=10, allow_redirects=True, stream=True)
            r.close()
        if r.status_code in (404, 410):
            return "dead"
        return "ok" if r.status_code < 400 else "unknown"
    except FetchError:
        return "unknown"
    except requests.exceptions.ConnectionError:
        return "dead"                                  # tên miền không còn / không kết nối được
    except requests.RequestException:
        return "unknown"


def broken_links(page_url: str, limit: int = 80) -> dict:
    """Quét một trang tài nguyên/bài tổng hợp, liệt kê link ra ngoài đã chết → cơ hội đề xuất link thay thế."""
    try:
        status, final, body = fetch_page(page_url)
    except FetchError as e:
        return {"ok": False, "error": str(e)}
    if status >= 400:
        return {"ok": False, "error": f"Trang trả mã {status}"}
    p = _Page(final)
    p.feed(body)
    own = domain_of(final)
    seen, todo = set(), []
    for a in p.links:
        u = a["href"].split("#")[0]
        d = domain_of(u)
        if u in seen or not d or d == own or d.endswith("." + own) or urlparse(u).scheme not in ("http", "https"):
            continue
        if any(d == s or d.endswith("." + s) for s in SOCIAL_SKIP):
            continue
        seen.add(u)
        todo.append((u, a["text"]))
    todo = todo[:limit]
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(lambda t: _alive(t[0]), todo))
    dead = [{"url": u, "anchor": t} for (u, t), r in zip(todo, res) if r == "dead"]
    return {"ok": True, "url": final, "title": htmllib.unescape(p.title).strip()[:120], "checked": len(todo), "dead": dead}


# ------------------------------------------------------------------ tìm trang tiềm năng

def search(query: str) -> list:
    """[(url, tiêu đề)] từ Bing rồi DuckDuckGo — kết quả thật của công cụ tìm kiếm."""
    from . import legallinks
    for fn in (legallinks._bing, legallinks._ddg):
        try:
            res = fn(query)
            if res:
                return res
        except Exception:  # noqa: BLE001
            continue
    return []


def fill_query(q: str, site: dict) -> str:
    comp = (_lines(site.get("competitors", "")) or [""])[0]
    return (q.replace("{brand}", site.get("brand") or "").replace("{domain}", site_domain(site))
            .replace("{city}", site.get("city") or "Việt Nam").replace("{competitor}", comp)).strip()


def opportunities(site: dict = None) -> list:
    site = site or get_site()
    out = []
    for o in OPPORTUNITIES:
        qs = []
        for q in o["queries"]:
            if "{competitor}" in q and not _lines(site.get("competitors", "")):
                continue
            if ("{brand}" in q and not site.get("brand")) or ("{domain}" in q and not site_domain(site)):
                continue
            fq = fill_query(q, site)
            qs.append({"q": fq, "google": "https://www.google.com/search?q=" + quote_plus(fq),
                       "bing": "https://www.bing.com/search?q=" + quote_plus(fq)})
        out.append({**{k: v for k, v in o.items() if k != "queries"}, "queries": qs})
    return out


def discover(kind: str, query: str = "", site: dict = None, limit: int = 12) -> dict:
    """Chạy các câu tìm của một loại cơ hội → mở từng trang → chấm điểm. Chỉ trả trang thật, đã mở được."""
    site = site or get_site()
    opp = OPP.get(kind)
    if not opp and not query:
        raise ValueError("Chưa chọn loại cơ hội")
    qs = [query] if query else [fill_query(q, site) for q in opp["queries"][:3]]
    if not qs:
        raise ValueError("Loại cơ hội này không có câu tìm tự động — làm theo hướng dẫn trong thẻ")
    mine = site_domain(site)
    known = {r["domain"] for r in list_rows()}
    seen, found = set(), []
    for q in qs:
        for url, title in search(q):
            d = domain_of(url)
            if not d or d in seen or d == mine or any(d == s or d.endswith("." + s) for s in SOCIAL_SKIP):
                continue
            seen.add(d)
            found.append((url, title, d))
    found = found[:limit * 2]
    with ThreadPoolExecutor(5) as ex:
        res = list(ex.map(lambda t: analyze(t[0], site), found))
    cands = []
    for (url, title, d), a in zip(found, res):
        if not a.get("ok"):
            continue
        item = {"url": a["url"], "title": a["title"] or title, "domain": d, "score": a["score"], "tier": a["tier"], "why": a["why"],
                "flags": a["flags"], "emails": a["emails"], "guest": a["guest"], "reject": a["reject"],
                "mentions_brand": a["mentions_brand"], "has_link": bool(a["links_to_me"]), "known": d in known}
        cands.append(item)
    cands.sort(key=lambda c: (c["reject"], -c["score"]))
    return {"queries": qs, "candidates": cands[:limit], "scanned": len(found)}


# ------------------------------------------------------------------ sổ theo dõi

COLS = ("id", "domain", "page_url", "kind", "status", "target_url", "anchor", "anchor_type", "rel", "found_url", "contact",
        "notes", "score", "tier", "cost", "followup_at", "last_checked", "last_result", "live_since", "created_at",
        "updated_at", "history")


def _row(r) -> dict:
    d = dict(r)
    try:
        d["history"] = json.loads(d.get("history") or "[]")
    except ValueError:
        d["history"] = []
    return d


def list_rows(status: str = "", kind: str = "") -> list:
    q, args = "SELECT * FROM backlinks", []
    cond = []
    if status:
        cond.append("status=?")
        args.append(status)
    if kind:
        cond.append("kind=?")
        args.append(kind)
    if cond:
        q += " WHERE " + " AND ".join(cond)
    with db.conn() as c:
        return [_row(r) for r in c.execute(q + " ORDER BY updated_at DESC, id DESC", args)]


def get_row(bid: int):
    with db.conn() as c:
        r = c.execute("SELECT * FROM backlinks WHERE id=?", (bid,)).fetchone()
    return _row(r) if r else None


def _hist(row_hist: list, text: str) -> list:
    return ([*row_hist, {"t": db.now(), "text": text}])[-40:]


def classify_anchor(anchor: str, site: dict = None, image: bool = False) -> str:
    site = site or get_site()
    a = _plain(anchor)
    if image or not a or a.startswith("[anh]"):
        return "image"
    brand = _plain(site.get("brand", ""))
    dom = site_domain(site)
    if re.search(r"https?://|www\.|\.(?:com|vn|net|org|info)\b", anchor.lower()) or (dom and dom in anchor.lower()):
        return "naked"
    if brand and brand in a:
        return "brand"
    if a in [_plain(g) for g in GENERIC_ANCHORS]:
        return "generic"
    for kw, _u in keywords(site):
        k = _plain(kw)
        if a == k:
            return "exact"
        kw_words = [w for w in k.split() if len(w) > 2]
        if k in a or (kw_words and sum(1 for w in kw_words if w in a.split()) / len(kw_words) >= 0.6):
            return "partial"
    return "generic"


def _plain(s: str) -> str:
    s = unicodedata.normalize("NFD", (s or "").lower().replace("đ", "d"))
    return re.sub(r"\s+", " ", "".join(c for c in s if unicodedata.category(c) != "Mn")).strip()


def add_row(data: dict) -> dict:
    site = get_site()
    page = str(data.get("page_url", "")).strip()
    domain = domain_of(page) or str(data.get("domain", "")).strip().lower()
    if not domain:
        raise ValueError("Cần địa chỉ trang (URL) hoặc tên miền")
    mine = site_domain(site)
    if mine and (domain == mine or domain.endswith("." + mine)):
        raise ValueError("Đây là chính website của bạn — backlink phải đến từ trang khác")
    status = data.get("status") if data.get("status") in STATUSES else "idea"
    target = str(data.get("target_url") or site.get("url") or "").strip()
    anchor = str(data.get("anchor", "")).strip()
    now = db.now()
    with db.conn() as c:
        dup = c.execute("SELECT id FROM backlinks WHERE page_url=? AND target_url=? AND page_url!=''", (page, target)).fetchone()
        if dup:
            raise ValueError(f"Trang này đã có trong sổ (#{dup['id']})")
        cur = c.execute(
            "INSERT INTO backlinks(domain,page_url,kind,status,target_url,anchor,anchor_type,rel,found_url,contact,notes,score,tier,cost,"
            "followup_at,last_checked,last_result,live_since,created_at,updated_at,history) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (domain, page, str(data.get("kind", "")), status, target, anchor,
             data.get("anchor_type") if data.get("anchor_type") in ANCHOR_TYPES else (classify_anchor(anchor, site) if anchor else ""),
             data.get("rel") if data.get("rel") in RELS else "", str(data.get("found_url", "")).strip(),
             str(data.get("contact", "")).strip(), str(data.get("notes", "")).strip(), int(data.get("score") or 0),
             str(data.get("tier", "")), int(data.get("cost") or 0), data.get("followup_at"), None, "", None, now, now,
             json.dumps([{"t": now, "text": "Thêm vào sổ"}], ensure_ascii=False)))
    return get_row(cur.lastrowid)


def update_row(bid: int, data: dict) -> dict:
    r = get_row(bid)
    if not r:
        raise KeyError(bid)
    site = get_site()
    f, note = {}, []
    for k in ("page_url", "kind", "target_url", "anchor", "found_url", "contact", "notes", "tier"):
        if k in data and data[k] is not None:
            f[k] = str(data[k]).strip()
    for k in ("score", "cost"):
        if k in data and data[k] is not None:
            f[k] = int(data[k] or 0)
    if "rel" in data and data["rel"] in RELS:
        f["rel"] = data["rel"]
    if "followup_at" in data:
        f["followup_at"] = int(data["followup_at"]) if data["followup_at"] else None
    if "anchor" in f or data.get("anchor_type") in ANCHOR_TYPES:
        f["anchor_type"] = data["anchor_type"] if data.get("anchor_type") in ANCHOR_TYPES else (classify_anchor(f.get("anchor", r["anchor"]), site) if f.get("anchor", r["anchor"]) else "")
    if "page_url" in f and f["page_url"]:
        f["domain"] = domain_of(f["page_url"]) or r["domain"]
    st = data.get("status")
    if st in STATUSES and st != r["status"]:
        f["status"] = st
        note.append(f"Trạng thái: {STATUSES[r['status']]} → {STATUSES[st]}")
        if st == "contacted" and "followup_at" not in f and not r["followup_at"]:
            f["followup_at"] = db.now() + 5 * DAY              # nhắc follow-up sau 5 ngày
        if st in ("live", "rejected", "lost"):
            f["followup_at"] = None
        if st == "live" and not r["live_since"]:
            f["live_since"] = db.now()
    if not f:
        return r
    f["updated_at"] = db.now()
    f["history"] = json.dumps(_hist(r["history"], "; ".join(note) or "Cập nhật thông tin"), ensure_ascii=False)
    with db.conn() as c:
        c.execute("UPDATE backlinks SET " + ", ".join(f"{k}=?" for k in f) + " WHERE id=?", [*f.values(), bid])
    return get_row(bid)


def delete_row(bid: int) -> bool:
    with db.conn() as c:
        return c.execute("DELETE FROM backlinks WHERE id=?", (bid,)).rowcount > 0


def verify_row(bid: int, site: dict = None) -> dict:
    """Mở trang chứa link, ghi kết quả: còn link (LIVE) / mất link / trang noindex / lỗi mở trang."""
    r = get_row(bid)
    if not r:
        raise KeyError(bid)
    site = site or get_site()
    where = r["found_url"] or r["page_url"]
    if not where:
        raise ValueError("Chưa có địa chỉ trang chứa link — nhập 'Trang chứa link' rồi kiểm tra")
    res = check_link(where, r["target_url"], site)
    f, text = {"last_checked": db.now(), "last_result": res["state"], "updated_at": db.now()}, ""
    if res["state"] in ("ok", "noindex"):
        f.update(rel=res["rel"], anchor=res["anchor"], anchor_type=classify_anchor(res["anchor"], site, res.get("image", False)))
        if r["status"] != "live":
            f.update(status="live", live_since=r["live_since"] or db.now(), followup_at=None)
            text = f"Kiểm tra: link ĐÃ LÊN ({res['rel']}, anchor “{res['anchor'][:60]}”)"
        if res["state"] == "noindex":
            text = (text + " — ") + "cảnh báo: trang đặt noindex"
    elif res["state"] == "not_found":
        if r["status"] == "live":
            f["status"] = "lost"
            text = "Kiểm tra: MẤT LINK (trang vẫn mở được nhưng không còn link về website)"
            db.log("backlink", f"Mất link từ {r['domain']} — {where}")
        else:
            text = "Kiểm tra: chưa thấy link về website" + (" (trang có nhắc thương hiệu)" if res.get("mentions_brand") else "")
    else:
        text = "Kiểm tra: " + res.get("error", "lỗi mở trang")
        if r["status"] == "live" and r["last_result"] == "error":
            f["status"] = "lost"                       # lỗi 2 lần liên tiếp mới coi là mất, tránh báo nhầm do mạng
            text += " (2 lần liên tiếp)"
            db.log("backlink", f"Không mở được trang {r['domain']} 2 lần liên tiếp — {where}")
    if text:
        f["history"] = json.dumps(_hist(r["history"], text), ensure_ascii=False)
    with db.conn() as c:
        c.execute("UPDATE backlinks SET " + ", ".join(f"{k}=?" for k in f) + " WHERE id=?", [*f.values(), bid])
    return {"row": get_row(bid), "result": res}


def recheck_all(max_links: int = 80) -> dict:
    """Kiểm tra lại mọi link đang LIVE / đã đăng — cũ nhất trước. Trả số liệu + danh sách mất link."""
    rows = [r for r in list_rows() if r["status"] in ("live", "published") and (r["found_url"] or r["page_url"])]
    rows.sort(key=lambda r: r["last_checked"] or 0)
    rows = rows[:max_links]
    site = get_site()
    out = {"checked": 0, "ok": 0, "lost": [], "errors": 0}

    def one(r):
        try:
            return verify_row(r["id"], site)
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)}
    with ThreadPoolExecutor(4) as ex:
        for r, res in zip(rows, ex.map(one, rows)):
            out["checked"] += 1
            row = res.get("row")
            if not row:
                out["errors"] += 1
            elif row["status"] == "lost":
                out["lost"].append({"id": row["id"], "domain": row["domain"]})
            elif row["last_result"] in ("ok", "noindex"):
                out["ok"] += 1
            else:
                out["errors"] += 1
    db.set_setting("backlink_last_recheck", db.now())
    db.set_setting("backlink_try_at", db.now())
    return out


def due() -> bool:
    """Đã quá 24 giờ kể từ lần kiểm tra lại gần nhất (và người dùng bật tự kiểm tra)?"""
    return db.now() - (db.get_setting("backlink_try_at", 0) or 0) >= DAY and bool(get_site().get("auto_check"))


def tick():
    """Chạy trong luồng riêng (việc này có thể mất vài phút): kiểm tra lại link rồi ghi nhật ký."""
    if not due():
        return
    db.set_setting("backlink_try_at", db.now())                # đặt trước để lần lỗi không lặp liên tục
    if any(r["status"] in ("live", "published") for r in list_rows()):
        res = recheck_all()
        db.log("backlink", f"Kiểm tra lại {res['checked']} link: {res['ok']} còn, {len(res['lost'])} mất, {res['errors']} lỗi")


# ------------------------------------------------------------------ anchor & kế hoạch

def anchor_report(rows: list = None, site: dict = None) -> dict:
    """Tỉ lệ các loại anchor của link đã lên (LIVE + đã đăng) so với tỉ lệ tự nhiên."""
    rows = list_rows() if rows is None else rows
    site = site or get_site()
    live = [r for r in rows if r["status"] in ("live", "published") and r["anchor_type"]]
    n = len(live)
    cnt = {k: sum(1 for r in live if r["anchor_type"] == k) for k in ANCHOR_TYPES}
    pct = {k: (round(cnt[k] * 100 / n) if n else 0) for k in ANCHOR_TYPES}
    warn = []
    if n >= 5:
        for k, (lo, hi) in ANCHOR_TARGET.items():
            if pct[k] > hi + 5:
                warn.append(f"Anchor '{ANCHOR_TYPES[k]}' đang {pct[k]}% (nên ≤ {hi}%)" + (" — rất nguy hiểm, dừng dùng từ khóa chính xác." if k == "exact" else ""))
    return {"total": n, "count": cnt, "percent": pct, "target": ANCHOR_TARGET, "warnings": warn}


def next_anchor(site: dict = None, rows: list = None) -> dict:
    """Gợi ý loại anchor + ví dụ cho link kế tiếp (loại đang thiếu nhiều nhất so với mức giữa của khoảng tự nhiên)."""
    site = site or get_site()
    rep = anchor_report(rows, site)
    n = max(1, rep["total"])
    best, gap = "brand", -999
    for k, (lo, hi) in ANCHOR_TARGET.items():
        if k in ("image", "exact"):
            continue
        g = (lo + hi) / 2 - rep["percent"][k] if rep["total"] else (hi if k == "brand" else 0)
        if g > gap:
            best, gap = k, g
    if rep["total"] >= 5 and rep["percent"]["exact"] < 3 and gap < 5:
        best = "exact"
    kws = keywords(site)
    samples = {"brand": [site.get("brand")] if site.get("brand") else [], "naked": [site.get("url", "")],
               "partial": [f"dịch vụ {kw}" if not kw.lower().startswith("dịch vụ") else f"tìm hiểu về {kw}" for kw, _u in kws[:3]] + [f"{kw} tại {site.get('city')}" for kw, _u in kws[:1] if site.get("city")],
               "generic": GENERIC_ANCHORS[:3], "exact": [kw for kw, _u in kws[:3]]}
    return {"type": best, "label": ANCHOR_TYPES[best], "examples": [s for s in samples[best] if s][:4], "report": rep, "n": n}


def report() -> dict:
    rows = list_rows()
    now = db.now()
    live = [r for r in rows if r["status"] == "live"]
    by = {s: sum(1 for r in rows if r["status"] == s) for s in STATUSES}
    dom = {r["domain"] for r in live}
    rels = {k: sum(1 for r in live if r["rel"] == k) for k in ("dofollow", "nofollow", "sponsored", "ugc")}
    week = [r for r in rows if r["live_since"] and r["live_since"] >= now - 7 * DAY]
    month = [r for r in rows if r["live_since"] and r["live_since"] >= now - 30 * DAY]
    site = get_site()
    return {"counts": by, "total": len(rows), "live": len(live), "domains": len(dom), "rel": rels,
            "dofollow_pct": round(rels["dofollow"] * 100 / len(live)) if live else 0,
            "tierA": sum(1 for r in live if r["tier"] == "A"), "week": len(week), "month": len(month),
            "target": int(site.get("weekly_target") or 4), "anchors": anchor_report(rows, site),
            "next_anchor": next_anchor(site, rows), "plan": plan(rows, site),
            "last_recheck": db.get_setting("backlink_last_recheck", 0), "avoid": AVOID}


def plan(rows: list = None, site: dict = None) -> list:
    """Việc cần làm hôm nay: follow-up đến hạn, link cần kiểm tra, link mất cần xử lý, số liên hệ mới để đạt nhịp tuần."""
    rows = list_rows() if rows is None else rows
    site = site or get_site()
    now = db.now()
    tasks = []
    if not site.get("url") or not site.get("brand"):
        tasks.append({"kind": "setup", "text": "Điền Hồ sơ website (địa chỉ website, tên thương hiệu, từ khóa chính) để các công cụ chấm điểm & gợi ý chính xác."})
    for r in rows:
        if r["status"] in ("contacted", "replied", "negotiating") and r["followup_at"] and r["followup_at"] <= now:
            tasks.append({"kind": "followup", "id": r["id"], "text": f"Follow-up {r['domain']} (đã đến hạn) — gửi nhắc lịch sự 1 lần, không spam."})
        if r["status"] == "published" and (not r["last_checked"] or now - r["last_checked"] > 3 * DAY):
            tasks.append({"kind": "verify", "id": r["id"], "text": f"Kiểm tra link đã đăng ở {r['domain']} — xem đã lên đúng chưa."})
        if r["status"] == "lost":
            tasks.append({"kind": "recover", "id": r["id"], "text": f"Mất link ở {r['domain']} — liên hệ hỏi nguyên nhân / xin gắn lại."})
    contacted_week = sum(1 for r in rows if any(h["t"] >= now - 7 * DAY and "→ Đã liên hệ" in h["text"] for h in r["history"]))
    target = int(site.get("weekly_target") or 4)
    need = max(0, target * 3 - contacted_week)             # trung bình ~1/3 liên hệ thành link → liên hệ gấp 3 mục tiêu
    if need:
        ideas = sum(1 for r in rows if r["status"] == "idea")
        tasks.append({"kind": "outreach", "text": f"Tuần này còn nên liên hệ ~{need} trang nữa (mục tiêu {target} link/tuần). Trong sổ có {ideas} ý tưởng chờ liên hệ."
                      + (" Hãy chạy 'Tự tìm trang tiềm năng' để có thêm." if ideas < need else "")})
    if not any(r["kind"] == "profiles" for r in rows):
        tasks.append({"kind": "profiles", "text": "Làm bộ hồ sơ doanh nghiệp (Google Business, Bing Places, Facebook, LinkedIn, YouTube...) — nền tảng của mọi chiến dịch."})
    live = [r for r in rows if r["status"] == "live"]
    if len(live) >= 10 and sum(1 for r in live if r["tier"] == "A") * 100 / len(live) < 20:
        tasks.append({"kind": "quality", "text": "Tỉ lệ link hạng A còn thấp (<20%) — ưu tiên guest post / báo chí / tài nguyên thay vì danh bạ."})
    return tasks


def export_csv() -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["ID", "Tên miền", "Trang chứa link", "Loại cơ hội", "Trạng thái", "Trang đích", "Anchor", "Loại anchor", "Rel", "Điểm", "Hạng",
                "Chi phí", "Liên hệ", "Live từ", "Kiểm tra lần cuối", "Ghi chú"])
    for r in list_rows():
        f = lambda t: time.strftime("%Y-%m-%d", time.localtime(t)) if t else ""  # noqa: E731
        w.writerow([r["id"], r["domain"], r["found_url"] or r["page_url"], OPP.get(r["kind"], {}).get("name", r["kind"]), STATUSES.get(r["status"], r["status"]),
                    r["target_url"], r["anchor"], ANCHOR_TYPES.get(r["anchor_type"], ""), r["rel"], r["score"], r["tier"], r["cost"], r["contact"],
                    f(r["live_since"]), f(r["last_checked"]), r["notes"]])
    return "﻿" + buf.getvalue()


# ------------------------------------------------------------------ AI soạn nội dung

AI_KINDS = {
    "pitch_guest": "Email chào hàng viết guest post",
    "pitch_resource": "Email xin thêm vào trang tài nguyên",
    "pitch_broken": "Email báo link chết + đề xuất link thay thế",
    "pitch_mention": "Email nhờ gắn link cho nhắc thương hiệu",
    "pitch_partner": "Email đề nghị hợp tác / đối tác / hiệp hội",
    "followup": "Email nhắc lại (follow-up)",
    "expert_comment": "Nhận định chuyên gia gửi báo chí",
    "guest_article": "Bài guest post hoàn chỉnh (1 link tự nhiên)",
    "directory_desc": "Mô tả cho danh bạ / hồ sơ doanh nghiệp (3 độ dài)",
    "qa_answer": "Nháp trả lời câu hỏi diễn đàn",
    "asset_ideas": "Ý tưởng tài sản liên kết",
}

_RULES = """QUY TẮC BẮT BUỘC:
- Viết tiếng Việt tự nhiên, lịch sự, như người thật gửi 1-1 (không văn mẫu hàng loạt, không khoa trương).
- CHỈ dùng thông tin có trong HỒ SƠ bên dưới. KHÔNG bịa giải thưởng, số khách hàng, số năm kinh nghiệm, chứng chỉ, số liệu, tên người.
- KHÔNG nêu điều khoản pháp luật/mức phạt cụ thể trừ khi người dùng cung cấp trong 'GHI CHÚ THÊM'.
- KHÔNG hứa hẹn trả tiền, KHÔNG xin link "dofollow", KHÔNG nhắc SEO/backlink một cách lộ liễu. Nói về GIÁ TRỊ cho độc giả của họ.
- Không chèn link nào khác ngoài link được chỉ định."""


def _profile(site: dict) -> str:
    kws = "; ".join(f"{k} → {u}" for k, u in keywords(site)) or "(chưa có)"
    return (f"HỒ SƠ: thương hiệu = {site.get('brand') or '(chưa có)'}; website = {site.get('url') or '(chưa có)'}; thành phố = {site.get('city') or ''}; "
            f"dịch vụ = {site.get('services') or ''}; điện thoại = {site.get('phone') or ''}; email = {site.get('email') or ''}; địa chỉ = {site.get('address') or ''}; "
            f"mô tả = {site.get('description') or ''}; từ khóa → trang đích: {kws}")


def build_prompt(kind: str, site: dict, row: dict = None, extra: dict = None) -> str:
    extra = extra or {}
    row = row or {}
    nxt = next_anchor(site)
    anchor = (extra.get("anchor") or row.get("anchor") or (nxt["examples"][0] if nxt["examples"] else site.get("brand", ""))).strip()
    target = extra.get("target_url") or row.get("target_url") or site.get("url", "")
    ctx = (f"TRANG NHẬN: {row.get('page_url') or extra.get('page_url') or ''} (tên miền {row.get('domain') or ''}); ghi chú về trang: {row.get('notes') or ''}\n"
           f"GHI CHÚ THÊM: {extra.get('notes') or ''}\nCHỦ ĐỀ/TIÊU ĐỀ MONG MUỐN: {extra.get('topic') or ''}\n"
           f"LINK DUY NHẤT ĐƯỢC GẮN: {target} — anchor: \"{anchor}\"\n")
    base = f"{_RULES}\n{_profile(site)}\n{ctx}\n"
    if kind in ("pitch_guest", "pitch_resource", "pitch_broken", "pitch_mention", "pitch_partner", "followup"):
        goal = {"pitch_guest": "Đề xuất viết 1 bài chuyên môn miễn phí cho trang họ; nêu 2–3 chủ đề cụ thể phù hợp độc giả của họ và vì sao bạn viết được (dựa trên hồ sơ).",
                "pitch_resource": "Giới thiệu 1 tài nguyên hữu ích của bạn (nêu rõ giúp độc giả của trang như thế nào) và nhờ cân nhắc thêm vào trang tài nguyên của họ.",
                "pitch_broken": f"Báo lịch sự rằng trang họ có link chết: {extra.get('dead_url') or '(link hỏng)'} ; đề xuất bài của bạn tại {target} làm nội dung thay thế nếu phù hợp.",
                "pitch_mention": "Cảm ơn vì đã nhắc tới thương hiệu; nhờ thêm đường link tới website để độc giả tiện truy cập (nêu đúng trang đã nhắc).",
                "pitch_partner": "Đề nghị hợp tác cùng có lợi (vd: bài giới thiệu đối tác, cảm nhận khách hàng, chuyên đề chia sẻ); nêu lợi ích cho họ.",
                "followup": "Nhắc lại nhẹ nhàng email trước (khoảng 5 ngày), 2–3 câu, không áp lực, cho họ lối thoát lịch sự."}[kind]
        return base + (f"NHIỆM VỤ: viết email 1-1 ngắn (≤ 150 từ). Mục tiêu: {goal}\n"
                       'Trả về JSON: {"subject": "tiêu đề email", "body": "nội dung email thuần văn bản, có lời chào và chữ ký bằng tên thương hiệu/điện thoại trong hồ sơ"}')
    if kind == "expert_comment":
        return base + ('NHIỆM VỤ: viết nhận định chuyên gia ngắn (120–180 từ) để gửi phóng viên/biên tập mảng kinh tế – thuế, về chủ đề đã cho. '
                       'Nêu quan điểm thực tế từ góc nhìn dịch vụ kế toán, lời khuyên cho doanh nghiệp nhỏ. Không bịa số liệu/điều luật. Kèm 1 câu giới thiệu người phát biểu (chỉ dùng thông tin hồ sơ).\n'
                       'Trả về JSON: {"subject": "tiêu đề email gửi báo", "body": "email + nhận định"}')
    if kind == "guest_article":
        return base + ('NHIỆM VỤ: viết 1 bài guest post chuyên sâu 700–900 từ, có giá trị thật cho độc giả của trang nhận, về chủ đề đã cho (nếu trống, chọn chủ đề kế toán/thuế thiết thực cho doanh nghiệp nhỏ). '
                       'Cấu trúc: mở bài, 3–5 mục có tiêu đề <h2>, ví dụ thực tế, kết luận. KHÔNG quảng cáo lộ liễu. KHÔNG bịa điều luật/mức phạt/số liệu — nếu cần nói tới quy định, nói chung chung "theo quy định hiện hành" và khuyên kiểm tra văn bản gốc. '
                       f'Đặt ĐÚNG MỘT link <a href="{target}">{anchor}</a> trong thân bài ở chỗ liên quan tự nhiên (không phải đầu hoặc cuối bài), phần giới thiệu tác giả không chứa link.\n'
                       'Trả về JSON: {"title": "tiêu đề hấp dẫn đầy đủ câu", "body": "HTML chỉ dùng <h2>,<p>,<ul>,<li>,<strong>,<a>", "author_bio": "2 câu giới thiệu tác giả (văn bản thuần)"}')
    if kind == "directory_desc":
        return base + ('NHIỆM VỤ: viết mô tả doanh nghiệp để điền vào danh bạ / hồ sơ. Giọng trung thực, nêu dịch vụ chính, khu vực phục vụ, cách liên hệ. Không bịa thành tích.\n'
                       'Trả về JSON: {"short": "~50 từ", "medium": "~150 từ", "long": "~300 từ", "tagline": "1 câu ≤ 15 từ", "categories": ["3–5 danh mục ngành phù hợp"]}')
    if kind == "qa_answer":
        return base + ('NHIỆM VỤ: soạn NHÁP trả lời cho câu hỏi người dùng nêu ở "CHỦ ĐỀ/TIÊU ĐỀ MONG MUỐN" hoặc "GHI CHÚ THÊM" (đó là nội dung câu hỏi). '
                       'Trả lời chi tiết, từng bước, đúng trọng tâm, nói rõ phần nào cần kiểm tra văn bản pháp luật hiện hành hoặc hỏi cơ quan thuế. Giọng người thật giúp đỡ. '
                       'KHÔNG chèn link trừ khi thật cần; nếu có, chỉ ở cuối và nói rõ lý do. Cuối cùng nhắc đây là nháp để người dùng đọc, sửa trước khi đăng.\n'
                       'Trả về JSON: {"body": "nội dung trả lời", "note": "lưu ý cho người đăng"}')
    if kind == "asset_ideas":
        return base + ('NHIỆM VỤ: đề xuất 6 "tài sản liên kết" (công cụ, biểu mẫu, bảng tra, checklist, khảo sát nhỏ...) mà các trang kế toán/thuế/khởi nghiệp sẽ muốn dẫn link tới. '
                       'Mỗi ý: nêu rõ hữu ích gì, cách làm trong 1–2 tuần với nguồn lực nhỏ, ai sẽ muốn dẫn link (loại trang), độ khó 1–5.\n'
                       'Trả về JSON: {"ideas": [{"title": "", "what": "", "how": "", "who_links": "", "difficulty": 3}]}')
    raise ValueError("Loại nội dung không hỗ trợ")


def _strip_other_links(body: str, target: str) -> str:
    """Giữ đúng link tới trang đích, gỡ mọi link khác AI tự chèn (chỉ giữ chữ)."""
    t = (target or "").rstrip("/").lower()

    def fix(m):
        href = m.group(1).strip().rstrip("/").lower()
        return m.group(0) if href == t else m.group(2)
    return re.sub(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', fix, body or "", flags=re.S | re.I)


def generate(kind: str, row_id: int = 0, extra: dict = None) -> dict:
    from . import newsagent
    if kind not in AI_KINDS:
        raise ValueError("Loại nội dung không hỗ trợ")
    site = get_site()
    row = get_row(row_id) if row_id else None
    prompt = build_prompt(kind, site, row, extra)
    out = newsagent.gemini_json(prompt, newsagent.get_config())
    if kind == "guest_article":
        target = (extra or {}).get("target_url") or (row or {}).get("target_url") or site.get("url", "")
        out["body"] = _strip_other_links(str(out.get("body", "")), target)
        out["has_link"] = bool(target) and target.rstrip("/").lower() in out["body"].lower()
        out["author_bio"] = re.sub(r"<[^>]+>", "", str(out.get("author_bio", "")))
    if "body" in out and isinstance(out["body"], str) and kind != "guest_article":
        out["body"] = out["body"].strip()
    return out


def mailto(to: str, subject: str, body: str) -> str:
    return f"mailto:{to}?subject={quote_plus(subject).replace('+', '%20')}&body={quote_plus(body).replace('+', '%20')}"

