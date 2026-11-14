"""Observe an action's result before allowing the next action or inference."""
from io import BytesIO
import time
from PIL import Image, ImageChops, ImageStat

def view(frame):
    with Image.open(BytesIO(frame.jpeg)) as image:
        return image.convert('L').resize((96,72))

def delta(a, b):
    return ImageStat.Stat(ImageChops.difference(a,b)).mean[0]

def after_action(source, before, acknowledged, stopped=None, timeout=3):
    baseline = view(before) if before else None
    number = before.number if before else 0
    latest = previous_view = None
    stable_since = None
    changed = False
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if stopped is not None and stopped.is_set():
            return None, 'cancelled'
        frame = source.get_frame(number, timeout=.08)
        if frame is None:
            continue
        number = frame.number
        # Frames already in the decoder at acknowledgement aren't action feedback.
        if frame.time < acknowledged + .12:
            continue
        current = view(frame)
        latest = frame
        changed = changed or baseline is None or delta(baseline,current) > 1.0
        if previous_view is None or delta(previous_view,current) > .8:
            stable_since = frame.time
        previous_view = current
        quiet = stable_since is not None and frame.time - stable_since >= .14
        if quiet and changed:
            return frame, 'changed'
        if quiet and frame.time - acknowledged >= .8:
            return frame, 'unchanged'
    if latest is not None:
        # Reaching the deadline never proves a quiet frame, even if all changes
        # stayed below the baseline threshold. Callers must settle again.
        return latest, 'animating'
    raise RuntimeError('动作已发出，但未收到动作后的新画面；已停止后续操作，避免重复点击')
