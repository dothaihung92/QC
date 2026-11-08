"""Các kiểu cảnh bổ sung cho clip Công nghệ / Giải thích — để mỗi clip có bố cục khác nhau tùy kiểu nội dung:
compare (so sánh 2 cột), quote (trích dẫn lớn), timeline (dòng thời gian), checklist (tích dần từng việc),
qa (hỏi – đáp), rank (xếp hạng "Top"). Màu lấy từ giao diện của clip (themes.apply) lúc vẽ.
Mọi chữ đều xuống dòng / thu nhỏ để không tràn khỏi khung.
"""
from PIL import Image, ImageDraw, ImageFilter

from . import explainer as X
from . import techlook as T
from . import video as V

RED, GREEN = (244, 112, 104), (84, 206, 128)


def _fonts(L, title=0.046, body=0.036):
    ts = getattr(L, "ts", 1.0)
    return V._font(int(L.base * title * ts), bold=True), V._font(int(L.base * body * ts))


def _fit_block(meas, texts, width, sizes, limits, avail_h, gap_lines=1.3):
    """Chọn cỡ chữ lớn nhất cho tới khi tổng chiều cao vừa avail_h. texts: [(text, kind)] kind 0 = đậm, 1 = thường."""
    big, small = sizes
    while True:
        fb, fs = V._font(big, bold=True), V._font(small)
        lines = [V.fit_lines(meas, t, fb if k == 0 else fs, width, limits[k]) for t, k in texts]
        h = sum(len(ls) * int((fb if k == 0 else fs).size * gap_lines) for ls, (_, k) in zip(lines, texts))
        if h <= avail_h or small <= 14:
            return fb, fs, lines, h
        big, small = max(16, int(big * 0.92)), max(14, int(small * 0.92))


def _rows(items):
    return [X._split_item(t) for t in items]


# ---------------------------------------------------------------- so sánh 2 cột

def compare(c, L, sc, top, bottom):
    """items[0] = "Nhãn trái | Nhãn phải" (vd "Trước 2026 | Từ 2026", "Hiểu lầm | Sự thật"); các dòng sau "trái | phải"."""
    items = sc["items"][:5]
    head = items[0].split("|", 1) if items and "|" in items[0] else ["Trước", "Sau"]
    rows = [r.split("|", 1) for r in items[1:] if "|" in r][:4] or [[a, b] for a, b in _rows(items)]
    myth = sc.get("tone") == "bad" or any(w in (head[0] or "").lower() for w in ("hiểu lầm", "sai", "lầm tưởng"))
    lcol, rcol = (RED, GREEN) if myth else ((150, 162, 186), T.BLUE)
    gap = int(L.pad * 0.4)
    cw = (L.W - 2 * L.pad - gap) // 2
    meas = ImageDraw.Draw(c.new())
    hh = int(L.base * 0.085)
    fh = V._font(int(L.base * 0.04 * getattr(L, "ts", 1.0)), bold=True)
    # cỡ chữ chung cho mọi ô, đủ chỗ cho tất cả các dòng
    size = int(L.base * 0.038 * getattr(L, "ts", 1.0))
    while True:
        f = V._font(size, bold=False)
        cells = [[V.fit_lines(meas, (t or "").strip(), f, cw - L.pad, 4) for t in r] for r in rows]
        rh = [max(len(a), len(b)) * int(f.size * 1.32) + int(L.pad * 0.7) for a, b in cells]
        total = hh + gap + sum(rh) + gap * len(rh)
        if total <= bottom - top or size <= 16:
            break
        size -= 2
    ov = c.new()
    d = ImageDraw.Draw(ov)
    for k, (lab, col) in enumerate(((head[0], lcol), (head[1] if len(head) > 1 else "", rcol))):
        x0 = L.pad + k * (cw + gap)
        d.rounded_rectangle((x0, top, x0 + cw, top + hh), radius=hh // 2, fill=col + (255,))
        lab = V.fit_lines(meas, (lab or "").strip().upper(), fh, cw - L.pad, 1)[0] if lab.strip() else ""
        d.text((x0 + cw / 2, top + hh / 2), lab, font=fh, fill=(255, 255, 255, 255), anchor="mm")
    c.add(ov, 0.35, "pop")
    y = top + hh + gap
    for k, ((a, b), h) in enumerate(zip(cells, rh)):
        ov = c.new()
        d = ImageDraw.Draw(ov)
        for side, (lines, col) in enumerate(((a, lcol), (b, rcol))):
            x0 = L.pad + side * (cw + gap)
            X._glass(ov, (x0, y, x0 + cw, y + h), radius=16, edge=col + (200,))
            ty = y + (h - len(lines) * int(f.size * 1.32)) // 2
            for ln in lines:
                d.text((x0 + cw / 2, ty), ln, font=f, fill=(255, 255, 255, 255) if side else (222, 228, 240, 255), anchor="mt")
                ty += int(f.size * 1.32)
        ar = int(gap * 0.9)                                  # mũi tên giữa 2 cột
        cx, cy = L.W // 2, y + h // 2
        d.ellipse((cx - ar, cy - ar, cx + ar, cy + ar), fill=rcol + (255,))
        d.polygon([(cx - ar * 0.35, cy - ar * 0.5), (cx + ar * 0.5, cy), (cx - ar * 0.35, cy + ar * 0.5)], fill=(255, 255, 255, 255))
        c.add(ov, c.when(k, len(cells), 0.6), "rise")
        y += h + gap


# ---------------------------------------------------------------- trích dẫn lớn

def quote(c, L, sc, top, bottom):
    """items[0] = câu trích (văn bản / điều khoản), url_title = nguồn, items[1] (tùy chọn) = "Hiểu đơn giản | ..."."""
    items = sc["items"]
    text = (items[0] if items else sc["narration"]).replace("|", ":")
    src = sc.get("url_title") or ""
    expl = X._split_item(items[1]) if len(items) > 1 else ("", "")
    meas = ImageDraw.Draw(c.new())
    w = L.W - 2 * L.pad - int(L.pad * 1.6)
    avail = int((bottom - top) * (0.62 if expl[1] or expl[0] else 0.9))
    fq, fs, (ql, sl), qh = _fit_block(meas, [(f"“{text}”", 0), (("— " + src) if src else "", 1)], w,
                                      (int(L.base * 0.052 * getattr(L, "ts", 1.0)), int(L.base * 0.032)), (7, 2), avail - L.pad)
    h = qh + int(L.pad * 1.6)
    ov = c.new()
    X._glass(ov, (L.pad, top, L.W - L.pad, top + h), radius=24)
    d = ImageDraw.Draw(ov)
    d.rounded_rectangle((L.pad, top, L.pad + int(L.base * 0.014), top + h), radius=6, fill=T.BLUE + (255,))
    big = V._font(int(L.base * 0.2), bold=True)
    d.text((L.W - L.pad * 1.6, top - int(L.base * 0.02)), "”", font=big, fill=T.BLUE + (90,), anchor="rt")
    y = top + int(L.pad * 0.8)
    for ln in ql:
        d.text((L.pad * 1.8, y), ln, font=fq, fill=(255, 255, 255, 255), anchor="lt")
        y += int(fq.size * 1.3)
    for ln in sl:
        d.text((L.pad * 1.8, y), ln, font=fs, fill=T.BLUE2 + (255,), anchor="lt")
        y += int(fs.size * 1.3)
    c.add(ov, 0.4, "rise")
    if expl[0] or expl[1]:
        y = top + h + int(L.pad * 0.5)
        ft, fd = _fonts(L, 0.04, 0.034)
        t1, t2 = (expl[0] or "Hiểu đơn giản"), (expl[1] or expl[0])
        dl = V.fit_lines(meas, t2, fd, w, 4)
        hh = int(ft.size * 1.4) + len(dl) * int(fd.size * 1.32) + int(L.pad * 0.9)
        if y + hh <= bottom:
            ov = c.new()
            X._glass(ov, (L.pad, y, L.W - L.pad, y + hh), radius=20, edge=T.BLUE2 + (220,))
            d = ImageDraw.Draw(ov)
            T.icon(d, "check", L.pad * 1.7, y + L.pad * 0.45 + ft.size * 0.5, ft.size * 0.45)
            d.text((L.pad * 2.4, y + int(L.pad * 0.45)), t1, font=ft, fill=T.BLUE2 + (255,), anchor="lt")
            ty = y + int(L.pad * 0.45) + int(ft.size * 1.4)
            for ln in dl:
                d.text((L.pad * 1.6, ty), ln, font=fd, fill=(230, 236, 246, 255), anchor="lt")
                ty += int(fd.size * 1.32)
            c.add(ov, max(1.2, c.span * 0.45), "rise")


# ---------------------------------------------------------------- dòng thời gian

def timeline(c, L, sc, top, bottom):
    """items: "Mốc thời gian | sự kiện" (vd "01/01/2026 | Bắt đầu áp dụng")."""
    rows = _rows(sc["items"][:5])
    meas = ImageDraw.Draw(c.new())
    x_line = L.pad + int(L.base * 0.05)
    w = L.W - x_line - L.pad * 2
    gap = int(L.pad * 0.45)
    size = int(L.base * 0.04 * getattr(L, "ts", 1.0))
    while True:
        fd, fe = V._font(size, bold=True), V._font(int(size * 0.92))
        cells = [(V.fit_lines(meas, a or b, fd, w, 1), V.fit_lines(meas, b if a else "", fe, w, 3)) for a, b in rows]
        hs = [int(fd.size * 1.35) + len(e) * int(fe.size * 1.3) + int(L.pad * 0.3) for _, e in cells]
        if sum(hs) + gap * (len(hs) - 1) <= bottom - top or size <= 16:
            break
        size -= 2
    total = sum(hs) + gap * (len(hs) - 1)
    ov = c.new()
    ImageDraw.Draw(ov).rounded_rectangle((x_line - 3, top, x_line + 3, top + total), radius=3, fill=T.BLUE + (150,))
    c.add(ov, 0.3, "none")
    y = top
    for k, ((dl, el), h) in enumerate(zip(cells, hs)):
        ov = c.new()
        d = ImageDraw.Draw(ov)
        r = int(L.base * 0.022)
        d.ellipse((x_line - r, y + fd.size * 0.15, x_line + r, y + fd.size * 0.15 + 2 * r), fill=T.BLUE2 + (255,),
                  outline=(255, 255, 255, 255), width=3)
        tx = x_line + int(L.pad * 0.9)
        ty = y
        for ln in dl:
            d.text((tx, ty), ln, font=fd, fill=T.BLUE2 + (255,), anchor="lt")
            ty += int(fd.size * 1.35)
        for ln in el:
            d.text((tx, ty), ln, font=fe, fill=(236, 240, 248, 255), anchor="lt")
            ty += int(fe.size * 1.3)
        c.add(ov, c.when(k, len(cells), 0.5), "rise")
        y += h + gap


# ---------------------------------------------------------------- checklist tích dần

def checklist(c, L, sc, top, bottom):
    rows = _rows(sc["items"][:5])
    meas = ImageDraw.Draw(c.new())
    box = int(L.base * 0.06)
    w = L.W - 2 * L.pad - box - int(L.pad * 1.4)
    gap = int(L.pad * 0.3)
    size = int(L.base * 0.042 * getattr(L, "ts", 1.0))
    while True:
        ft, fd = V._font(size, bold=True), V._font(int(size * 0.85))
        cells = [(V.fit_lines(meas, a or b, ft, w, 2), V.fit_lines(meas, b if a else "", fd, w, 2)) for a, b in rows]
        hs = [max(box, len(t) * int(ft.size * 1.25) + len(e) * int(fd.size * 1.3)) + int(L.pad * 0.6) for t, e in cells]
        if sum(hs) + gap * (len(hs) - 1) <= bottom - top or size <= 16:
            break
        size -= 2
    y = top
    n = len(cells)
    for k, ((tl, el), h) in enumerate(zip(cells, hs)):
        ov = c.new()
        X._glass(ov, (L.pad, y, L.W - L.pad, y + h), radius=16)
        d = ImageDraw.Draw(ov)
        bx, by = L.pad + int(L.pad * 0.5), y + (h - box) // 2
        d.rounded_rectangle((bx, by, bx + box, by + box), radius=8, outline=T.BLUE2 + (255,), width=4)
        tx, ty = bx + box + int(L.pad * 0.5), y + (h - len(tl) * int(ft.size * 1.25) - len(el) * int(fd.size * 1.3)) // 2
        for ln in tl:
            d.text((tx, ty), ln, font=ft, fill=(255, 255, 255, 255), anchor="lt")
            ty += int(ft.size * 1.25)
        for ln in el:
            d.text((tx, ty), ln, font=fd, fill=(214, 222, 236, 255), anchor="lt")
            ty += int(fd.size * 1.3)
        t0 = c.when(k, n, 0.4)
        c.add(ov, t0, "rise")
        ov = c.new()                                          # dấu tích hiện sau khi đọc tới việc đó
        d = ImageDraw.Draw(ov)
        d.rounded_rectangle((bx, by, bx + box, by + box), radius=8, fill=GREEN + (255,))
        d.line([(bx + box * 0.22, by + box * 0.52), (bx + box * 0.42, by + box * 0.72), (bx + box * 0.8, by + box * 0.3)],
               fill=(255, 255, 255, 255), width=max(4, box // 9), joint="curve")
        c.add(ov, t0 + 0.9, "pop")
        y += h + gap


# ---------------------------------------------------------------- hỏi – đáp

def qa(c, L, sc, top, bottom):
    """items[0] = câu hỏi, items[1] = trả lời ngắn, items[2:] = ý bổ sung ("tiêu đề | ý")."""
    items = sc["items"]
    q = (items[0] if items else sc["headline"].replace("|", " ")).replace("|", " ").strip()
    a = items[1].replace("|", ":").strip() if len(items) > 1 else ""
    extra = _rows(items[2:4])
    meas = ImageDraw.Draw(c.new())
    fq, fa = _fonts(L, 0.046, 0.04)
    av = int(L.base * 0.07)
    qw = L.W - 2 * L.pad - av - int(L.pad * 1.6)
    ql = V.fit_lines(meas, q, fq, qw, 4)
    qh = len(ql) * int(fq.size * 1.3) + int(L.pad * 0.9)
    ov = c.new()
    d = ImageDraw.Draw(ov)
    d.ellipse((L.pad, top, L.pad + av, top + av), fill=T.BLUE + (255,))
    d.text((L.pad + av / 2, top + av / 2), "?", font=V._font(int(av * 0.62), bold=True), fill=(255, 255, 255, 255), anchor="mm")
    bx = L.pad + av + int(L.pad * 0.4)
    d.rounded_rectangle((bx, top, L.W - L.pad, top + qh), radius=22, fill=(246, 248, 252, 255))
    d.polygon([(bx, top + av * 0.35), (bx - int(L.pad * 0.35), top + av * 0.5), (bx, top + av * 0.65)], fill=(246, 248, 252, 255))
    ty = top + int(L.pad * 0.45)
    for ln in ql:
        d.text((bx + int(L.pad * 0.5), ty), ln, font=fq, fill=(24, 30, 46, 255), anchor="lt")
        ty += int(fq.size * 1.3)
    c.add(ov, 0.3, "pop")
    y = top + qh + int(L.pad * 0.6)
    if a:
        aw = L.W - 2 * L.pad - int(L.pad * 1.2)
        al = V.fit_lines(meas, a, fa, aw, max(2, min(6, (bottom - y - L.pad) // max(1, int(fa.size * 1.32)) - 1)))
        ah = int(fa.size * 1.5) + len(al) * int(fa.size * 1.32) + int(L.pad * 0.8)
        ov = c.new()
        X._glass(ov, (L.pad, y, L.W - L.pad, y + ah), radius=20, edge=GREEN + (220,))
        d = ImageDraw.Draw(ov)
        lab = V._font(int(fa.size * 0.85), bold=True)
        d.text((L.pad + int(L.pad * 0.6), y + int(L.pad * 0.4)), "✓ TRẢ LỜI", font=lab, fill=GREEN + (255,), anchor="lt")
        ty = y + int(L.pad * 0.4) + int(fa.size * 1.5)
        for ln in al:
            d.text((L.pad + int(L.pad * 0.6), ty), ln, font=fa, fill=(255, 255, 255, 255), anchor="lt")
            ty += int(fa.size * 1.32)
        c.add(ov, max(1.0, c.span * 0.25), "rise")
        y += ah + int(L.pad * 0.4)
    if extra and bottom - y > L.base * 0.25:                  # ý bổ sung dạng thẻ nhỏ
        X._list(c, dict(sc, items=[f"{t} | {e}" if t else e for t, e in extra]), y, bottom)


# ---------------------------------------------------------------- xếp hạng "Top"

def rank(c, L, sc, top, bottom):
    """big = thứ hạng (vd "#3" / "3"); items[0] = "Sai lầm | mô tả", items[1] = "Cách tránh | mô tả"."""
    num = (sc.get("big") or "").strip().lstrip("#") or "1"
    big = X._fit("#" + num[:3], int(L.base * 0.26), int(L.W * 0.45), grad=(T.BLUE, T.BLUE2), scale=1.0)
    ov = c.new()
    halo = Image.new("RGBA", ov.size, (0, 0, 0, 0))
    ImageDraw.Draw(halo).ellipse((L.pad - big.height * 0.2, top - big.height * 0.1, L.pad + big.width + big.height * 0.2,
                                  top + big.height * 1.1), fill=T.BLUE + (60,))
    ov.alpha_composite(halo.filter(ImageFilter.GaussianBlur(big.height * 0.25)))
    ov.alpha_composite(big, (L.pad, top))
    rows = _rows(sc["items"][:2])
    meas = ImageDraw.Draw(c.new())
    if rows and rows[0][0]:                                   # tên lỗi lớn bên phải số hạng
        ft = V._font(int(L.base * 0.05 * getattr(L, "ts", 1.0)), bold=True)
        tx = L.pad + big.width + int(L.pad * 0.6)
        lines = V.fit_lines(meas, rows[0][0], ft, L.W - L.pad - tx, 3)
        ty = top + (big.height - len(lines) * int(ft.size * 1.25)) // 2
        for ln in lines:
            ImageDraw.Draw(ov).text((tx, ty), ln, font=ft, fill=(255, 255, 255, 255), anchor="lt")
            ty += int(ft.size * 1.25)
    c.add(ov, 0.3, "pop")
    y = top + big.height + int(L.pad * 0.6)
    ft, fd = _fonts(L, 0.04, 0.036)
    for k, (t, e) in enumerate(rows):
        col, ic, lab = ((RED, "warn", "SAI LẦM") if k == 0 else (GREEN, "check", "CÁCH TRÁNH"))
        text = e or t
        lines = V.fit_lines(meas, text, fd, L.W - 2 * L.pad - int(L.pad * 1.6), 4)
        h = int(ft.size * 1.45) + len(lines) * int(fd.size * 1.32) + int(L.pad * 0.8)
        if y + h > bottom:
            break
        ov = c.new()
        X._glass(ov, (L.pad, y, L.W - L.pad, y + h), radius=18, edge=col + (230,))
        d = ImageDraw.Draw(ov)
        T.icon(d, ic, L.pad + int(L.pad * 0.9), y + int(L.pad * 0.45) + ft.size * 0.55, ft.size * 0.5)
        d.text((L.pad + int(L.pad * 1.6), y + int(L.pad * 0.45)), lab, font=ft, fill=col + (255,), anchor="lt")
        ty = y + int(L.pad * 0.45) + int(ft.size * 1.45)
        for ln in lines:
            d.text((L.pad + int(L.pad * 0.7), ty), ln, font=fd, fill=(240, 244, 250, 255), anchor="lt")
            ty += int(fd.size * 1.32)
        c.add(ov, c.when(k + 1, 3, 0.5), "rise")
        y += h + int(L.pad * 0.4)


RENDERERS = {"compare": compare, "quote": quote, "timeline": timeline, "checklist": checklist, "qa": qa, "rank": rank}
