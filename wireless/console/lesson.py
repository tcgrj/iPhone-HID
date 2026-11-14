"""Recognize the routine correct-answer screen in an active Duolingo lesson."""

from .vision import camera_point, normalize, read_regions, screen_crop
import re
from io import BytesIO
from PIL import Image


def enabled_check(frame, meter, target, verify_label=True):
    """Confirm the planned Check button became enabled after selecting words."""
    if frame is None:
        return False
    matches = [target] if not verify_label else [point for label, confidence, point in read_regions(frame, meter)
               if confidence >= .25 and normalize(label) in {'检查', '检査', 'check'}
               and sum((a-b)**2 for a,b in zip(point,target)) <= 15**2]
    if len(matches) != 1:
        return False
    with Image.open(BytesIO(frame.jpeg)) as image:
        image = image.convert('RGB').resize((800,600))
        x,y = matches[0]
        pixels = list(image.crop((max(0,x-45),max(0,y-10),min(800,x+46),min(600,y+11))).getdata())
    return bool(pixels) and sum(g-r>=30 and g-b>=38 and g>=105 for r,g,b in pixels)/len(pixels) >= .6


POSITIVE_FEEDBACK = {"不错哦", "太棒了", "非常好", "真厉害", "好棒", "你太棒了", "真棒", "答对了", "回答正确", "正确", "完全正确", "做得好", "太出色了", "很好", "correct", "excellent", "greatjob", "nicelydone"}


def continue_button(frame, meter):
    left, top, right, bottom = meter
    lower = left, top + .50 * (bottom - top), right, min(1, bottom + .07)
    image, bounds = screen_crop(frame, lower, (.035, 0), (220, 140))
    image = image.convert("RGB")
    width, height = image.size
    pixels = iter(image.getdata())
    # A broad saturated green button differs from the pale green feedback panel.
    rows = []
    for y in range(height):
        green = sum(g - r >= 30 and g - b >= 38 and b <= .60 * g and g >= 105
                    for r, g, b in (next(pixels) for _ in range(width)))
        if y >= .52 * height and green >= .55 * width:
            rows.append(y)
    if (len(rows) < .05 * height or not rows
            or rows[-1] - rows[0] + 1 > .26 * height
            or len(rows) / (rows[-1] - rows[0] + 1) < .8):
        return None
    center_y = (rows[0] + rows[-1]) / (2 * height)
    _, button_y = camera_point(bounds, .5, center_y)
    regions = read_regions(frame, lower)
    if not any(confidence >= .25 and re.sub(r"[^a-z\u4e00-\u9fff]", "", normalize(label)) in POSITIVE_FEEDBACK
               and y < button_y - 18 for label, confidence, (_, y) in regions):
        return None
    matches = [point for text, confidence, point in regions
               if confidence >= .25 and normalize(text) in {"继续", "continue"} and abs(point[1] - button_y) <= 15]
    return matches[0] if len(matches) == 1 else None
