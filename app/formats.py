"""Kiểu nội dung (mạch kể) của clip — mỗi clip một kiểu để nội dung và bố cục không lặp lại:
cùng một bài nhưng có thể thành bản tin nóng, hỏi – đáp, top sai lầm, câu chuyện, so sánh cũ – mới, checklist,
hiểu lầm – sự thật, hoặc luật sư – kế toán giải trình. Chế độ "auto" xoay vòng (không trùng kiểu của clip trước).
"""
from . import db

SPECIAL_TYPES = (
    'CÁC KIỂU CẢNH ĐẶC BIỆT (dùng theo bố cục bên dưới; mỗi mục vẫn viết "tiêu đề | ý ngắn"):\n'
    '- "compare": so sánh 2 cột. items[0] = "Nhãn trái | Nhãn phải" (vd "Trước 2026 | Từ 2026" hoặc "Hiểu lầm | Sự thật"), '
    'các items sau = "nội dung trái | nội dung phải" (2-3 dòng, mỗi ô tối đa 8 từ).\n'
    '- "quote": trích dẫn lớn. items[0] = câu trích NGUYÊN VĂN ngắn (tối đa 30 từ) từ văn bản/nguồn, url_title = nguồn (vd "Điều 8, Thông tư 18/2026/TT-BTC"), '
    'items[1] = "Hiểu đơn giản | giải thích bằng lời thường".\n'
    '- "timeline": dòng thời gian. items = "Mốc thời gian | sự kiện" (3-5 mốc, đúng thứ tự thời gian).\n'
    '- "checklist": danh sách việc cần làm sẽ được tích dần. items = "Việc cần làm | chi tiết ngắn" (3-5 việc).\n'
    '- "qa": hỏi – đáp. items[0] = câu hỏi người xem hay hỏi, items[1] = câu trả lời ngắn (1-2 câu), items[2] (tùy chọn) = "ý bổ sung | chi tiết".\n'
    '- "rank": một mục trong danh sách xếp hạng. big = thứ hạng (vd "#3"), items[0] = "Tên sai lầm/điểm | mô tả", items[1] = "Cách tránh | mô tả".\n'
)

FORMATS = {
    "tin-nong": dict(
        name="Bản tin nóng",
        idea="giọng người dẫn bản tin: nhanh, rõ, tập trung vào ĐIỀU GÌ VỪA THAY ĐỔI và ẢNH HƯỞNG tới người xem.",
        skeleton='hero (tin chính + chip) → stat (con số quan trọng nhất) → compare ("Trước | Từ nay") → list (ai bị ảnh hưởng) → '
                 'timeline (mốc hiệu lực, hạn chót) → checklist (việc cần làm ngay) → cta',
        hook='mở bằng "Tin mới:" + con số / thay đổi gây chú ý',
        cta='kết bằng lời nhắc lưu video và hỏi "Doanh nghiệp bạn có bị ảnh hưởng không?"'),
    "hoi-dap": dict(
        name="Hỏi – Đáp",
        idea="trả lời lần lượt các câu hỏi người xem hay hỏi nhất về chủ đề; mỗi câu hỏi một cảnh, trả lời thẳng vào vấn đề.",
        skeleton='hero (chủ đề + "5 câu hỏi bạn hay gặp") → qa → qa → quote (căn cứ cho câu trả lời quan trọng) → qa → qa → calc (ví dụ nếu có số liệu) → cta',
        hook='mở bằng câu hỏi được hỏi nhiều nhất',
        cta='mời người xem bình luận câu hỏi tiếp theo của họ'),
    "top-sai-lam": dict(
        name="Top sai lầm",
        idea='đếm ngược "Top 3-5 sai lầm" doanh nghiệp hay mắc liên quan chủ đề, mỗi sai lầm một cảnh kèm cách tránh; sai lầm số 1 nghiêm trọng nhất để cuối.',
        skeleton='hero ("Top N sai lầm …") → rank (#N) → rank (#N-1) → … → rank (#1) → quote (căn cứ/mức phạt) → checklist (cách phòng tránh) → cta',
        hook='mở bằng "Đây là N sai lầm khiến doanh nghiệp bị phạt / mất tiền …"',
        cta='hỏi người xem đã từng mắc sai lầm nào'),
    "cau-chuyen": dict(
        name="Câu chuyện tình huống", story=True,
        idea="kể MỘT câu chuyện có nhân vật (tên, nghề, cửa hàng cụ thể) gặp đúng vấn đề của chủ đề: bối cảnh → rắc rối → tìm hiểu quy định → con số → cách giải quyết → bài học.",
        skeleton='hero (nhân vật + tình huống) → stat (thiệt hại / số tiền liên quan) → quote (quy định áp dụng) → calc (tính toán trường hợp của nhân vật) → '
                 'compare ("Nếu làm sai | Nếu làm đúng") → checklist (bài học) → cta',
        hook='mở bằng tình huống gây tò mò của nhân vật',
        cta='"Bạn có gặp trường hợp giống … không? Kể cho mình nghe nhé."'),
    "truoc-sau": dict(
        name="So sánh cũ – mới",
        idea="đặt quy định CŨ cạnh quy định MỚI để người xem thấy ngay khác biệt và tác động bằng tiền.",
        skeleton='hero → compare (điểm khác 1) → compare (điểm khác 2) → timeline (từ khi nào) → calc (ví dụ tính theo cách cũ và mới) → '
                 'bars (so sánh số tiền) → checklist (cần làm gì) → cta',
        hook='mở bằng "Cùng một cửa hàng, theo quy định mới nộp thuế khác bao nhiêu?"',
        cta='mời lưu lại để đối chiếu khi kê khai'),
    "checklist": dict(
        name="Hướng dẫn từng bước",
        idea="hướng dẫn thực hành: làm gì, theo thứ tự nào, hồ sơ gì, hạn chót khi nào — như đang cầm tay chỉ việc.",
        skeleton='hero → quote (căn cứ) → steps (các bước) → timeline (thời hạn) → checklist (hồ sơ cần chuẩn bị) → rank (#1 lỗi hay sai khi làm) → cta',
        hook='mở bằng "Chỉ cần N bước để …"',
        cta='mời bình luận "cần mẫu" / liên hệ hỗ trợ làm hồ sơ'),
    "hieu-lam": dict(
        name="Hiểu lầm – Sự thật",
        idea='lật lại những điều nhiều người tưởng đúng nhưng sai về chủ đề; mỗi cảnh một hiểu lầm đối chiếu sự thật có căn cứ.',
        skeleton='hero ("N hiểu lầm về …") → compare ("Hiểu lầm | Sự thật") → quote (căn cứ) → compare ("Hiểu lầm | Sự thật") → '
                 'calc (ví dụ hậu quả bằng tiền) → compare ("Hiểu lầm | Sự thật") → checklist (làm đúng thế nào) → cta',
        hook='mở bằng "Bạn có đang tin điều này không?"',
        cta='hỏi người xem từng hiểu lầm điều nào'),
    "chuyen-gia": dict(
        name="Luật sư – kế toán giải trình", expert_order=True, story=True,
        idea="giải trình đầy đủ như buổi tư vấn của luật sư kiêm kế toán.",
        skeleton='hero → browser/quote (căn cứ pháp lý) → list (đối tượng áp dụng) → compare (được / không được) → calc (ví dụ có lãi) → '
                 'calc (ví dụ bị lỗ) → bars → checklist (khuyến nghị) → cta',
        hook='mở bằng câu hỏi / con số gây tò mò',
        cta='mời liên hệ tư vấn'),
}
ORDER = ["tin-nong", "hoi-dap", "top-sai-lam", "cau-chuyen", "truoc-sau", "checklist", "hieu-lam", "chuyen-gia"]


def pick(choice: str = "auto") -> dict:
    """Kiểu nội dung cho clip mới. auto: xoay vòng theo bộ đếm, không trùng clip trước."""
    if choice in FORMATS:
        key = choice
    else:
        seq = int(db.get_setting("video_story_seq", 0) or 0)
        key = ORDER[seq % len(ORDER)]
        db.set_setting("video_story_seq", seq + 1)
    return dict(FORMATS[key], key=key)


def prompt_block(f: dict, n: int, rich_types: bool = True) -> str:
    """Đoạn chỉ dẫn thêm vào cuối prompt viết kịch bản."""
    out = (f'\n\nKIỂU NỘI DUNG CỦA CLIP NÀY: "{f["name"]}" — {f["idea"]}\n'
           'Kiểu nội dung này QUYẾT ĐỊNH mạch kể và bố cục: nó THAY THẾ mọi trình tự cố định nêu ở trên '
           '(vẫn giữ yêu cầu chính xác, nêu căn cứ pháp lý, giải thích thuật ngữ, ví dụ có số liệu đúng).\n'
           f'- Mở đầu: {f["hook"]}.\n- Kết: {f["cta"]}.\n')
    if rich_types:
        out += (f'- BỐ CỤC CẢNH theo thứ tự (co giãn cho đủ {n} cảnh, có thể lặp kiểu cảnh giữa): {f["skeleton"]}.\n'
                '- Dùng ĐA DẠNG kiểu cảnh, không để 2 cảnh liền nhau cùng kiểu (trừ rank/qa/compare trong chuỗi của kiểu nội dung).\n'
                + SPECIAL_TYPES)
    return out
