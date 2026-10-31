"""Bộ hình phác thảo vẽ tay bằng nét mực (không cần AI) — dùng khi không có Gemini key hoặc AI vẽ lỗi.
Mỗi hình là một biểu tượng kế toán / thuế quen thuộc, chọn theo từ khóa trong nhãn và mô tả của hình."""
import math
import random
import re

from PIL import Image, ImageDraw

INK = (52, 38, 30)
ORANGE = (255, 196, 120)
TEAL = (150, 218, 206)
YELLOW = (255, 234, 150)
PINK = (250, 190, 180)
BLUE = (170, 205, 240)
RED = (222, 104, 52)


class Pen:
    def __init__(self, d, rng, w):
        self.d, self.rng, self.w = d, rng, max(3, int(w))

    def line(self, pts, w=None, color=INK):
        out = []
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            n = max(2, int(math.hypot(x1 - x0, y1 - y0) / 18))
            for k in range(n):
                t = k / n
                out.append((x0 + (x1 - x0) * t + self.rng.uniform(-1.5, 1.5), y0 + (y1 - y0) * t + self.rng.uniform(-1.5, 1.5)))
        out.append(pts[-1])
        self.d.line(out, fill=color, width=w or self.w, joint="curve")

    def rect(self, box, fill=None, r=0, w=None):
        x0, y0, x1, y1 = box
        if fill:
            self.d.rounded_rectangle(box, radius=r, fill=fill)
        self.line([(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)], w)

    def circle(self, cx, cy, r, fill=None, w=None):
        if fill:
            self.d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=fill)
        pts = [(cx + r * math.cos(a / 20 * 2 * math.pi), cy + r * math.sin(a / 20 * 2 * math.pi)) for a in range(21)]
        self.line(pts, w)

    def poly(self, pts, fill=None, w=None):
        if fill:
            self.d.polygon(pts, fill=fill)
        self.line(list(pts) + [pts[0]], w)


def person(p, x, y, s, hold=None):
    cx = x + s * 0.5
    p.circle(cx, y + s * 0.2, s * 0.14, fill=(255, 224, 196))
    p.d.ellipse((cx - s * 0.05 - 4, y + s * 0.17, cx - s * 0.05 + 4, y + s * 0.17 + 8), fill=INK)
    p.d.ellipse((cx + s * 0.05 - 4, y + s * 0.17, cx + s * 0.05 + 4, y + s * 0.17 + 8), fill=INK)
    p.line([(cx - s * 0.06, y + s * 0.26), (cx, y + s * 0.285), (cx + s * 0.06, y + s * 0.26)])
    p.poly([(cx - s * 0.2, y + s * 0.38), (cx + s * 0.2, y + s * 0.38), (cx + s * 0.24, y + s * 0.78), (cx - s * 0.24, y + s * 0.78)], fill=TEAL)
    p.line([(cx - s * 0.2, y + s * 0.42), (cx - s * 0.38, y + s * 0.62)])
    p.line([(cx + s * 0.2, y + s * 0.42), (cx + s * 0.38, y + s * 0.6)])
    p.line([(cx - s * 0.1, y + s * 0.78), (cx - s * 0.1, y + s * 0.98)])
    p.line([(cx + s * 0.1, y + s * 0.78), (cx + s * 0.1, y + s * 0.98)])
    p.line([(cx - s * 0.14, y + s * 0.07), (cx - s * 0.02, y + s * 0.02), (cx + s * 0.12, y + s * 0.06)], w=p.w * 2)


def shop(p, x, y, s):
    p.rect((x + s * 0.12, y + s * 0.42, x + s * 0.88, y + s * 0.92), fill=YELLOW)
    for k in range(5):                                           # mái che sọc
        x0 = x + s * (0.08 + k * 0.168)
        p.poly([(x0, y + s * 0.2), (x0 + s * 0.168, y + s * 0.2), (x0 + s * 0.168, y + s * 0.42), (x0, y + s * 0.42)],
               fill=ORANGE if k % 2 == 0 else (255, 250, 240))
    p.rect((x + s * 0.4, y + s * 0.6, x + s * 0.62, y + s * 0.92), fill=BLUE)
    p.rect((x + s * 0.18, y + s * 0.58, x + s * 0.34, y + s * 0.74), fill=(255, 250, 240))
    p.line([(x + s * 0.05, y + s * 0.92), (x + s * 0.95, y + s * 0.92)])


def coins(p, x, y, s):
    for k, (dx, dy) in enumerate(((0.3, 0.7), (0.62, 0.74), (0.46, 0.5))):
        p.circle(x + s * dx, y + s * dy, s * 0.2, fill=YELLOW)
        p.circle(x + s * dx, y + s * dy, s * 0.13)
    p.line([(x + s * 0.46, y + s * 0.42), (x + s * 0.46, y + s * 0.58)])
    p.line([(x + s * 0.4, y + s * 0.46), (x + s * 0.52, y + s * 0.46)])
    for a in (-0.7, 0, 0.7):                                     # tia sáng
        p.line([(x + s * (0.5 + 0.32 * math.sin(a)), y + s * (0.2 - 0.0 * a)), (x + s * (0.5 + 0.4 * math.sin(a)), y + s * 0.1)])


def banknote(p, x, y, s):
    p.rect((x + s * 0.06, y + s * 0.28, x + s * 0.94, y + s * 0.76), fill=(190, 230, 190), r=8)
    p.circle(x + s * 0.5, y + s * 0.52, s * 0.14, fill=(255, 250, 235))
    p.circle(x + s * 0.18, y + s * 0.4, s * 0.04)
    p.circle(x + s * 0.82, y + s * 0.64, s * 0.04)


def document(p, x, y, s):
    p.poly([(x + s * 0.2, y + s * 0.06), (x + s * 0.7, y + s * 0.06), (x + s * 0.84, y + s * 0.22), (x + s * 0.84, y + s * 0.94), (x + s * 0.2, y + s * 0.94)],
           fill=(255, 252, 242))
    p.line([(x + s * 0.7, y + s * 0.06), (x + s * 0.7, y + s * 0.22), (x + s * 0.84, y + s * 0.22)])
    for k in range(4):
        p.line([(x + s * 0.3, y + s * (0.34 + k * 0.1)), (x + s * (0.74 - (k % 2) * 0.12), y + s * (0.34 + k * 0.1))], w=max(2, p.w - 1))
    p.circle(x + s * 0.66, y + s * 0.78, s * 0.1, fill=(250, 200, 190))
    p.line([(x + s * 0.61, y + s * 0.78), (x + s * 0.65, y + s * 0.82), (x + s * 0.72, y + s * 0.73)], color=RED)


def calculator(p, x, y, s):
    p.rect((x + s * 0.2, y + s * 0.08, x + s * 0.8, y + s * 0.94), fill=BLUE, r=14)
    p.rect((x + s * 0.28, y + s * 0.16, x + s * 0.72, y + s * 0.34), fill=(235, 250, 240))
    for r_ in range(4):
        for c in range(3):
            p.circle(x + s * (0.32 + c * 0.18), y + s * (0.47 + r_ * 0.13), s * 0.04, fill=ORANGE if c == 2 else (255, 250, 240), w=max(2, p.w - 1))


def calendar(p, x, y, s):
    p.rect((x + s * 0.1, y + s * 0.18, x + s * 0.9, y + s * 0.9), fill=(255, 252, 242), r=10)
    p.rect((x + s * 0.1, y + s * 0.18, x + s * 0.9, y + s * 0.38), fill=ORANGE, r=10)
    for c in (0.28, 0.72):
        p.line([(x + s * c, y + s * 0.08), (x + s * c, y + s * 0.26)], w=p.w * 2)
    for r_ in range(3):
        for c in range(4):
            p.circle(x + s * (0.24 + c * 0.17), y + s * (0.5 + r_ * 0.12), s * 0.025, fill=INK, w=2)
    p.circle(x + s * 0.58, y + s * 0.74, s * 0.07, w=p.w + 1)


def percent(p, x, y, s):
    p.circle(x + s * 0.5, y + s * 0.5, s * 0.4, fill=ORANGE)
    p.circle(x + s * 0.36, y + s * 0.36, s * 0.07, fill=(255, 250, 240))
    p.circle(x + s * 0.64, y + s * 0.64, s * 0.07, fill=(255, 250, 240))
    p.line([(x + s * 0.66, y + s * 0.3), (x + s * 0.34, y + s * 0.7)], w=p.w + 2)


def clock(p, x, y, s):
    p.circle(x + s * 0.5, y + s * 0.5, s * 0.4, fill=(255, 252, 242))
    for k in range(12):
        a = k / 12 * 2 * math.pi
        p.line([(x + s * (0.5 + 0.33 * math.sin(a)), y + s * (0.5 - 0.33 * math.cos(a))), (x + s * (0.5 + 0.37 * math.sin(a)), y + s * (0.5 - 0.37 * math.cos(a)))], w=2)
    p.line([(x + s * 0.5, y + s * 0.5), (x + s * 0.5, y + s * 0.26)])
    p.line([(x + s * 0.5, y + s * 0.5), (x + s * 0.66, y + s * 0.56)])


def chart(p, x, y, s):
    p.line([(x + s * 0.12, y + s * 0.1), (x + s * 0.12, y + s * 0.88), (x + s * 0.92, y + s * 0.88)])
    for k, (h, col) in enumerate(((0.25, YELLOW), (0.4, TEAL), (0.55, ORANGE), (0.72, PINK))):
        x0 = x + s * (0.2 + k * 0.19)
        p.rect((x0, y + s * (0.88 - h), x0 + s * 0.13, y + s * 0.88), fill=col)
    p.line([(x + s * 0.2, y + s * 0.5), (x + s * 0.45, y + s * 0.4), (x + s * 0.62, y + s * 0.3), (x + s * 0.88, y + s * 0.14)], color=RED)
    p.line([(x + s * 0.78, y + s * 0.14), (x + s * 0.88, y + s * 0.14), (x + s * 0.88, y + s * 0.26)], color=RED)


def building(p, x, y, s):
    p.rect((x + s * 0.2, y + s * 0.1, x + s * 0.8, y + s * 0.92), fill=BLUE)
    for r_ in range(4):
        for c in range(3):
            p.rect((x + s * (0.3 + c * 0.18), y + s * (0.2 + r_ * 0.15), x + s * (0.4 + c * 0.18), y + s * (0.29 + r_ * 0.15)),
                   fill=(255, 245, 190), w=2)
    p.rect((x + s * 0.44, y + s * 0.78, x + s * 0.56, y + s * 0.92), fill=ORANGE)
    p.line([(x + s * 0.08, y + s * 0.92), (x + s * 0.92, y + s * 0.92)])


def chat(p, x, y, s):
    p.poly([(x + s * 0.1, y + s * 0.15), (x + s * 0.9, y + s * 0.15), (x + s * 0.9, y + s * 0.62), (x + s * 0.5, y + s * 0.62),
            (x + s * 0.3, y + s * 0.84), (x + s * 0.3, y + s * 0.62), (x + s * 0.1, y + s * 0.62)], fill=TEAL)
    for k in range(3):
        p.circle(x + s * (0.34 + k * 0.16), y + s * 0.39, s * 0.04, fill=INK, w=2)


def check(p, x, y, s):
    p.circle(x + s * 0.5, y + s * 0.5, s * 0.4, fill=(190, 235, 190))
    p.line([(x + s * 0.3, y + s * 0.52), (x + s * 0.45, y + s * 0.68), (x + s * 0.72, y + s * 0.34)], w=p.w * 2, color=INK)


def laptop(p, x, y, s):
    p.rect((x + s * 0.18, y + s * 0.2, x + s * 0.82, y + s * 0.64), fill=BLUE, r=6)
    p.rect((x + s * 0.24, y + s * 0.26, x + s * 0.76, y + s * 0.58), fill=(235, 250, 240))
    p.poly([(x + s * 0.08, y + s * 0.8), (x + s * 0.92, y + s * 0.8), (x + s * 0.82, y + s * 0.64), (x + s * 0.18, y + s * 0.64)], fill=(225, 225, 225))
    p.line([(x + s * 0.3, y + s * 0.4), (x + s * 0.44, y + s * 0.34), (x + s * 0.56, y + s * 0.46), (x + s * 0.7, y + s * 0.3)], color=RED)


def magnifier(p, x, y, s):
    p.circle(x + s * 0.42, y + s * 0.42, s * 0.26, fill=(225, 245, 250))
    p.line([(x + s * 0.61, y + s * 0.61), (x + s * 0.88, y + s * 0.88)], w=p.w * 2)


def arrow_down(p, x, y, s):
    p.poly([(x + s * 0.38, y + s * 0.1), (x + s * 0.62, y + s * 0.1), (x + s * 0.62, y + s * 0.5), (x + s * 0.8, y + s * 0.5),
            (x + s * 0.5, y + s * 0.9), (x + s * 0.2, y + s * 0.5), (x + s * 0.38, y + s * 0.5)], fill=PINK)


ICONS = {"person": person, "shop": shop, "coins": coins, "banknote": banknote, "document": document, "calculator": calculator,
         "calendar": calendar, "percent": percent, "clock": clock, "chart": chart, "building": building, "chat": chat,
         "check": check, "laptop": laptop, "magnifier": magnifier, "arrow_down": arrow_down}

KEYWORDS = [
    ("percent", r"%|phần trăm|percent|discount|ưu đãi|giảm thuế|tax cut"),
    ("calculator", r"tính|máy tính|calculator|calculat|cách tính|công thức"),
    ("calendar", r"lịch|năm|ngày|tháng|calendar|date|deadline|hạn|thời gian|hiệu lực|quý"),
    ("document", r"thuế|hóa đơn|invoice|document|hồ sơ|nghị định|thông tư|decree|form|kê khai|tờ khai|mẫu|văn bản|luật|law|paper"),
    ("shop", r"cửa hàng|shop|store|hộ kinh doanh|kinh doanh|bán|market|quán"),
    ("building", r"công ty|doanh nghiệp|company|office|building|enterprise"),
    ("coins", r"tiền|money|coin|doanh thu|revenue|tiết kiệm|save|lợi|nộp|đồng|tỷ|triệu"),
    ("chart", r"biểu đồ|chart|growth|tăng|lợi nhuận|profit|số liệu"),
    ("chat", r"tư vấn|nhắn|chat|phone|liên hệ|support|inbox|fanpage|hỗ trợ|hỏi"),
    ("check", r"điều kiện|kiểm tra|check|đủ|đạt|đúng|hợp lệ|condition|đối tượng"),
    ("laptop", r"phần mềm|software|computer|laptop|online|điện tử|nộp mạng"),
    ("magnifier", r"tìm|soát|magnif|search|rà|xem xét"),
    ("clock", r"giờ|clock|nhanh|time|sớm|trễ|hạn chót"),
    ("person", r"chủ|người|chị|anh|owner|person|man|woman|kế toán|accountant|khách|nhân viên|cá nhân"),
    ("banknote", r"banknote|cash|lương|salary"),
    ("arrow_down", r"giảm|decrease|reduce|còn lại|thấp"),
]
ORDER = ["person", "document", "coins", "calculator", "calendar", "chart", "shop", "percent", "check", "chat", "laptop", "building"]


def pick(label: str, visual: str, seed: int, count: int = 2) -> list:
    text = f"{label} {visual}".lower()
    found = []
    for name, rx in KEYWORDS:
        if re.search(rx, text) and name not in found:
            found.append(name)
    for name in ORDER[seed % len(ORDER):] + ORDER[:seed % len(ORDER)]:
        if len(found) >= count:
            break
        if name not in found:
            found.append(name)
    return found[:count]


def draw_scene(size: int, label: str, visual: str, seed: int, bg=(247, 243, 226)) -> Image.Image:
    """Ảnh vuông size×size: 1 biểu tượng chính + 1-2 biểu tượng phụ + nét trang trí, vẽ tay bằng nét mực."""
    S = 3
    n = size * S
    img = Image.new("RGB", (n, n), bg)
    d = ImageDraw.Draw(img)
    rng = random.Random(seed * 7 + len(label))
    pen = Pen(d, rng, n * 0.012)
    names = pick(label, visual, seed, 3)
    main = n * 0.62
    ICONS[names[0]](pen, (n - main) / 2, n * 0.14, main)
    small = n * 0.34
    ICONS[names[1]](pen, n * 0.04, n * 0.56, small)
    if len(names) > 2:
        ICONS[names[2]](pen, n * 0.64, n * 0.04, small * 0.85)
    for _ in range(5):                                           # nét trang trí: tia, chấm, sao nhỏ
        cx, cy = rng.uniform(0.05, 0.95) * n, rng.uniform(0.05, 0.95) * n
        if abs(cx - n / 2) < n * 0.3 and abs(cy - n / 2) < n * 0.3:
            continue
        r = n * rng.uniform(0.012, 0.025)
        if rng.random() < 0.5:
            pen.line([(cx - r, cy), (cx + r, cy)], w=3 * S // 2)
            pen.line([(cx, cy - r), (cx, cy + r)], w=3 * S // 2)
        else:
            d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=RED)
    return img.resize((size, size), Image.LANCZOS)
