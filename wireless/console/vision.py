"""Shared camera crops and the optional macOS text recognizer."""

from io import BytesIO
import json
from pathlib import Path
import re
import subprocess
import unicodedata

from PIL import Image, ImageFilter, ImageOps


OCR = Path(__file__).resolve().parents[2] / ".console-runtime" / "ocr"
CLICK_LABEL = re.compile(r'点击(?:「([^」]+)」|“([^”]+)”|"([^"]+)")[。.]?')
READ_TEXT = {"读取屏幕文字", "识别屏幕文字", "读出屏幕文字"}


def screen_crop(frame, region, padding, size):
    x1, y1, x2, y2 = region
    px, py = padding
    with Image.open(BytesIO(frame.jpeg)) as image:
        width, height = image.size
        left, top = round(max(0, x1 - px) * width), round(max(0, y1 - py) * height)
        right, bottom = round(min(1, x2 + px) * width), round(min(1, y2 + py) * height)
        crop = image.crop((left, top, right, bottom))
    crop.thumbnail(size, Image.Resampling.LANCZOS)
    return crop, (left / width, top / height, right / width, bottom / height)


def camera_point(bounds, x, y):
    left, top, right, bottom = bounds
    return round(800 * (left + x * (right - left))), round(600 * (top + y * (bottom - top)))


def local_intent(task):
    if task.rstrip("。.") in READ_TEXT:
        return "read", ""
    match = CLICK_LABEL.fullmatch(task)
    if match:
        return "click", next(label for label in match.groups() if label is not None)
    return None


def normalize(text):
    return "".join(unicodedata.normalize("NFKC", text).casefold().split())


def read_regions(frame, region, timeout=2.5):
    if not OCR.is_file():
        return []
    image, bounds = screen_crop(frame, region, (.03, .025), (900, 1050))
    image = image.convert("RGB")
    jpeg = BytesIO()
    image.save(jpeg, "JPEG", quality=95)
    try:
        result = subprocess.run([OCR], input=jpeg.getvalue(), capture_output=True, timeout=timeout, check=True)
        return [(region["text"], region["confidence"], camera_point(bounds, region["x"], region["y"]))
                for region in json.loads(result.stdout)]
    except (OSError, subprocess.SubprocessError, ValueError):
        return []


def find_label(regions, label):
    expected = normalize(label)
    matches = [point for text, confidence, point in regions
               if confidence >= .65 and normalize(text) == expected]
    return matches[0] if len(matches) == 1 else None
