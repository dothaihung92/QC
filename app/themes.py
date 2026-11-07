"""Giao diện clip (kiểu "công nghệ" và "giải thích"): mỗi clip một bộ màu + họa tiết nền + kiểu tiêu đề khác nhau
để các clip không cùng một khung mẫu. Chế độ "auto" xoay vòng theo số thứ tự clip (2 clip liền nhau luôn khác giao diện).
"""

# a1/a2: màu nhấn (dòng tiêu đề 2, số thứ tự, viền); key: nền từ đang đọc ở phụ đề; glass/gedge: thẻ nội dung
THEMES = {
    "dem": dict(name="Xanh đêm", bg=(6, 10, 24), glow=(16, 36, 84), a1=(78, 146, 255), a2=(70, 190, 255),
                key=(36, 104, 232), glass=(16, 24, 50, 228), gedge=(64, 90, 150, 200), dot=(90, 140, 255)),
    "ngoc": dict(name="Ngọc lục bảo", bg=(3, 18, 16), glow=(8, 74, 62), a1=(34, 206, 150), a2=(140, 240, 200),
                 key=(14, 150, 108), glass=(8, 36, 34, 228), gedge=(52, 150, 124, 200), dot=(60, 220, 170)),
    "tim": dict(name="Tím hoàng hôn", bg=(15, 8, 30), glow=(72, 30, 112), a1=(176, 124, 255), a2=(255, 130, 204),
                key=(128, 64, 220), glass=(30, 18, 54, 228), gedge=(130, 96, 200, 200), dot=(190, 130, 255)),
    "cam": dict(name="Cam năng lượng", bg=(22, 12, 6), glow=(104, 48, 10), a1=(255, 150, 56), a2=(255, 214, 96),
                key=(214, 96, 18), glass=(44, 26, 14, 228), gedge=(186, 112, 52, 200), dot=(255, 160, 80)),
    "do": dict(name="Đỏ cảnh báo", bg=(22, 6, 10), glow=(110, 18, 30), a1=(255, 96, 96), a2=(255, 176, 120),
               key=(196, 38, 52), glass=(44, 14, 22, 228), gedge=(190, 72, 84, 200), dot=(255, 110, 110)),
    "bien": dict(name="Xanh biển", bg=(3, 16, 30), glow=(0, 86, 120), a1=(30, 196, 255), a2=(120, 255, 228),
                 key=(0, 132, 196), glass=(8, 34, 56, 228), gedge=(48, 150, 196, 200), dot=(60, 200, 255)),
    "vang": dict(name="Than chì – vàng", bg=(14, 14, 17), glow=(54, 52, 60), a1=(255, 196, 56), a2=(255, 232, 140),
                 key=(196, 142, 16), glass=(30, 30, 36, 230), gedge=(150, 130, 80, 200), dot=(255, 210, 100)),
}
ORDER = ["dem", "ngoc", "tim", "cam", "bien", "do", "vang"]
PATTERNS = ["grid", "dots", "diagonal", "rings", "waves", "plus"]
HEADS = ["left", "center", "band"]


def pick(choice: str, video_id: int) -> dict:
    """Giao diện cho 1 clip. choice = "auto" (đổi mỗi clip) hoặc mã giao diện trong THEMES."""
    vid = max(0, int(video_id or 0))
    key = choice if choice in THEMES else ORDER[vid % len(ORDER)]
    t = dict(THEMES[key], id=key)
    # họa tiết + kiểu tiêu đề cũng xoay (bước khác nhau để tổ hợp lặp lại thật chậm)
    t["pattern"] = PATTERNS[(vid * 5 + 1) % len(PATTERNS)]
    t["head"] = HEADS[(vid * 2 + vid // len(ORDER)) % len(HEADS)]
    return t


def apply(t: dict):
    """Đặt màu cho các module vẽ (kiểu công nghệ + kiểu giải thích)."""
    from . import explainer as X
    from . import techlook as T
    T.BG, T.GLOW, T.DOTC = t["bg"], t["glow"], t["dot"]
    T.BLUE, T.BLUE2, T.KEYBOX = t["a1"], t["a2"], t["key"]
    T.CARD = t["glass"]
    T.CARD_EDGE = t["gedge"][:3] + (255,)
    T.PATTERN, T.HEAD = t.get("pattern", "grid"), t.get("head", "left")
    X.CYAN, X.MINT = t["a1"], t["a2"]
    X.GLASS, X.EDGE = t["glass"], t["gedge"]
    X.LINE = t["a1"] + (255,)
    X.PURPLE = t["key"]
    X.BG_BASE = t["bg"]
    X.SPOTS = (t["glow"], tuple(max(0, int(c * 0.7)) for c in t["glow"]))
