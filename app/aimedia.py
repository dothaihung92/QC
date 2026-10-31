"""Giọng đọc, ảnh và video do AI của Google tạo — dùng chung Gemini API key đã nhập ở tab Tin tức AI.

- Gemini TTS: giọng đọc tự nhiên, có "phong cách đọc" (năng động, ấm áp...) — khác hẳn giọng máy
- Ảnh AI (Gemini Flash Image): mỗi cảnh một ảnh minh họa riêng theo nội dung
- Veo (cùng nền tảng với Google Flow): video AI 8 giây, TRẢ PHÍ theo giây nên chỉ dùng cho vài cảnh chọn lọc
Tên model Google đổi khá thường xuyên nên mỗi loại thử lần lượt vài tên.
"""
import base64
import re
import time

import requests

API = "https://generativelanguage.googleapis.com/v1beta"
TTS_MODELS = ["gemini-2.5-flash-preview-tts", "gemini-2.5-flash-tts", "gemini-2.5-pro-preview-tts"]
IMAGE_MODELS = ["gemini-2.5-flash-image", "gemini-2.5-flash-image-preview"]
VEO_MODELS = ["veo-3.1-fast-generate-preview", "veo-3.0-fast-generate-001"]
VEO_PRICE_PER_SEC = 0.10            # USD, Veo 3.1 Fast 720p (giá tham khảo, kiểm tra lại trên trang giá của Google)
VEO_SECONDS = 8


class AIError(Exception):
    pass


def _headers(key: str) -> dict:
    return {"x-goog-api-key": key, "Content-Type": "application/json"}


def _post(path: str, key: str, body: dict, timeout=120, retries=3):
    """POST có thử lại khi Google báo quá tải / hết lượt tạm thời (429, 503)."""
    last = None
    for attempt in range(retries + 1):
        try:
            r = requests.post(f"{API}/{path}", headers=_headers(key), json=body, timeout=timeout)
        except requests.RequestException as e:
            raise AIError(f"Lỗi kết nối Google: {e}") from e
        try:
            data = r.json()
        except ValueError:
            data = {}
        if r.status_code < 400:
            return data
        msg = (data.get("error") or {}).get("message") or r.text[:200]
        last = AIError(f"{msg[:220]} (HTTP {r.status_code})")
        last.status = r.status_code
        if r.status_code in (429, 503) and attempt < retries:
            m = re.search(r"retry in ([\d.]+)s", msg)
            time.sleep(min(70, float(m[1]) + 1) if m else 12 * (attempt + 1))
            continue
        raise last
    raise last


def _inline(data: dict):
    for cand in data.get("candidates") or []:
        for part in (cand.get("content") or {}).get("parts") or []:
            blob = part.get("inlineData") or part.get("inline_data")
            if blob and blob.get("data"):
                return base64.b64decode(blob["data"]), blob.get("mimeType") or blob.get("mime_type") or ""
    return None, ""


def _first_working(models, call):
    errors = []
    for m in models:
        try:
            return call(m)
        except AIError as e:
            errors.append(f"{m}: {e}")
            if getattr(e, "status", 0) not in (400, 404):      # lỗi khác tên model: thử model khác cũng vô ích
                break
    raise AIError(" | ".join(errors))


def tts_pcm(text: str, voice: str, style: str, key: str):
    """Trả về (bytes PCM 16-bit mono, sample_rate)."""
    prompt = f"{style}:\n{text}" if style else text
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseModalities": ["AUDIO"],
                                 "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}}}

    def call(model):
        pcm, mime = _inline(_post(f"models/{model}:generateContent", key, body))
        if not pcm:
            raise AIError("Google không trả âm thanh")
        m = re.search(r"rate=(\d+)", mime)
        return pcm, int(m[1]) if m else 24000
    return _first_working(TTS_MODELS, call)


def image(prompt: str, aspect: str, key: str):
    """Trả về bytes ảnh (PNG/JPEG)."""
    def call(model):
        body = {"contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": aspect}}}
        try:
            data = _post(f"models/{model}:generateContent", key, body)
        except AIError as e:
            if getattr(e, "status", 0) != 400 or "aspect" not in str(e).lower() and "imageconfig" not in str(e).lower():
                raise
            body["generationConfig"].pop("imageConfig")             # model không hỗ trợ chọn tỷ lệ
            data = _post(f"models/{model}:generateContent", key, body)
        img, _ = _inline(data)
        if not img:
            raise AIError("Google không trả ảnh (có thể bị chặn nội dung)")
        return img
    return _first_working(IMAGE_MODELS, call)


def veo(prompt: str, aspect: str, key: str, dest, wait=420) -> None:
    """Tạo video ~8 giây bằng Veo rồi tải về dest. Mất 1-3 phút, tốn phí theo giây."""
    def start(model):
        data = _post(f"models/{model}:predictLongRunning", key,
                     {"instances": [{"prompt": prompt}], "parameters": {"aspectRatio": aspect}})
        if not data.get("name"):
            raise AIError("Veo không trả mã tác vụ")
        return data["name"]
    op = _first_working(VEO_MODELS, start)
    deadline = time.time() + wait
    while time.time() < deadline:
        time.sleep(10)
        try:
            r = requests.get(f"{API}/{op}", headers=_headers(key), timeout=60)
            data = r.json()
        except (requests.RequestException, ValueError) as e:
            raise AIError(f"Lỗi kết nối Google: {e}") from e
        if data.get("error"):
            raise AIError(str(data["error"].get("message", data["error"]))[:200])
        if data.get("done"):
            resp = data.get("response") or {}
            samples = (resp.get("generateVideoResponse") or resp).get("generatedSamples") or []
            if not samples:
                raise AIError("Veo không tạo được video (có thể bị chặn nội dung)")
            uri = samples[0]["video"]["uri"]
            try:
                with requests.get(uri, headers={"x-goog-api-key": key}, timeout=300, stream=True) as v:
                    v.raise_for_status()
                    with open(dest, "wb") as f:
                        for chunk in v.iter_content(1 << 16):
                            f.write(chunk)
            except (requests.RequestException, OSError) as e:
                raise AIError(f"Không tải được video Veo: {e}") from e
            return
    raise AIError("Veo quá lâu (hơn 7 phút), bỏ qua cảnh này")
