"""Locate the physical mouse pointer in consecutive camera frames."""

from io import BytesIO
import time

from PIL import Image, ImageChops, ImageFilter, ImageStat


def grayscale(frame):
    with Image.open(BytesIO(frame.jpeg)) as image:
        return image.convert("L").resize((800, 600), Image.Resampling.LANCZOS).filter(
            ImageFilter.GaussianBlur(1.4)
        )


def motion_matches(old, new, movement):
    """Reject reverse/sideways changes and implausible cursor acceleration."""
    dx, dy = movement
    norm = dx * dx + dy * dy
    if norm < 1:
        return False
    vx, vy = new[0] - old[0], new[1] - old[1]
    gain = (vx * dx + vy * dy) / norm
    sideways = abs(vx * dy - vy * dx) / norm ** .5
    return .4 <= gain <= 3 and sideways <= max(4, .15 * (vx * vx + vy * vy) ** .5)


def difference_components(delta, offset):
    width = delta.width
    points = {(i % width, i // width) for i, value in enumerate(delta.getdata()) if value >= 15}
    if len(points) > 12000:
        # Navigation/animation changed too much to attribute motion to the cursor.
        return None
    candidates = []
    while points:
        component = [points.pop()]
        for x, y in component:
            for p in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if p in points:
                    points.remove(p)
                    component.append(p)
        if not 20 <= len(component) <= 520:
            continue
        xs, ys = zip(*component)
        w, h = max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
        if min(w, h) < 4 or max(w, h) > 29 or not .45 <= w / h <= 2.2:
            continue
        point = (offset[0] + sum(xs) / len(xs), offset[1] + sum(ys) / len(ys))
        candidates.append((point, len(component), w, h))
    return candidates


def unique_position(points):
    # Light/dark edges of one pointer can produce two components at the same spot.
    groups = []
    for point in points:
        for group in groups:
            if all(distance(point, other) <= 5 ** 2 for other in group):
                group.append(point)
                break
        else:
            groups.append([point])
    if len(groups) != 1:
        return None
    return tuple(sum(p[axis] for p in groups[0]) / len(groups[0]) for axis in (0, 1))


def cursor_position(before, after, bounds, expected, previous=None, movement=None):
    left, top, right, bottom = bounds
    if expected is not None and previous is not None:
        x, y = map(round, expected)
        left, top = max(left, x - 64), max(top, y - 64)
        right, bottom = min(right, x + 65), min(bottom, y + 65)
    if right <= left or bottom <= top:
        return None
    crop = (left, top, right, bottom)
    dark = difference_components(ImageChops.subtract(before, after).crop(crop), (left, top))
    bright = difference_components(ImageChops.subtract(after, before).crop(crop), (left, top))
    if dark is None or bright is None:
        return None
    if previous is not None:
        candidates = []
        for point, _, _, _ in dark + bright:
            if distance(point, previous) <= 5 ** 2:
                continue
            if expected is not None and not follows_move(point, previous, expected):
                continue
            if movement is not None and not motion_matches(previous, point, movement):
                continue
            candidates.append(point)
        return unique_position(candidates)
    if movement is None:
        return None

    # Acquire from a matched erased/appearing pair. A lone changing icon is not a
    # pointer. Try both polarities because iOS changes pointer color with background.
    candidates = []
    for old_set, new_set in ((dark, bright), (bright, dark)):
        for old, old_area, old_w, old_h in old_set:
            if not .65 <= old_w / old_h <= 1.55:
                continue
            for new, new_area, new_w, new_h in new_set:
                if not .65 <= new_w / new_h <= 1.55:
                    continue
                if not .5 <= new_area / old_area <= 2:
                    continue
                if max(abs(old_w - new_w), abs(old_h - new_h)) > 6:
                    continue
                if motion_matches(old, new, movement):
                    candidates.append(new)
    return unique_position(candidates)


def distance(first, second):
    return (first[0] - second[0]) ** 2 + (first[1] - second[1]) ** 2


def follows_move(point, previous, expected):
    for actual, start, end in zip(point, previous, expected):
        intended = end - start
        observed = actual - start
        if abs(intended) >= 8:
            if observed * intended <= 0 or abs(observed) < min(5, abs(intended) * .3):
                return False
        elif abs(observed) > 15:
            return False
    return True


def stable_target(reference, latest, x, y, enables=False):
    box = (max(0, x - 15), max(0, y - 15), min(800, x + 16), min(600, y + 16))
    first, second = reference.crop(box), latest.crop(box)
    if ImageStat.Stat(ImageChops.difference(first, second)).mean[0] < 25:
        return True
    if enables:
        sides = (max(0, x - 35), max(0, y - 9), min(800, x + 36), min(600, y + 10))
        shift = ImageChops.subtract(latest.crop(sides), reference.crop(sides), offset=128)
        return ImageStat.Stat(shift).stddev[0] < 23
    return False


class Pointer:
    def __init__(self, device, stopped):
        self.device = device
        self.stopped = stopped
        self.position = None
        self.hint = None
        self.confirmed_at = 0.0
        self.gains = [1.35, 1.35]
        self.gain_samples = [0, 0]

    def learn_gains(self, previous, position, movement, bounds):
        if previous is None:
            return
        for axis, (start, end, delta) in enumerate(zip(previous, position, movement)):
            if abs(delta) < 25 or not bounds[axis] + 22 < end < bounds[axis + 2] - 22:
                continue
            observed = (end - start) / delta
            if .4 <= observed <= 3:
                self.gains[axis] = (observed if self.gain_samples[axis] == 0
                                    else .45 * self.gains[axis] + .55 * observed)
                self.gain_samples[axis] += 1

    def locate(self, dx, dy, bounds):
        if self.position is None:
            # iOS hides the idle cursor. Establish a visible baseline first;
            # otherwise every acquisition compares against a cursor-free frame.
            if not self.device.command("move 2 0", self.stopped):
                return
            if self.stopped.wait(.25):
                return
        previous = self.position or self.hint
        movement = (dx, dy)
        expected = (tuple(p + d * (gain if abs(d) >= 25 else 1.35)
                          for p, d, gain in zip(previous, movement, self.gains)) if previous else None)
        baseline = self.device.get_frame()
        if baseline is None:
            self.position = None
            return
        before = grayscale(baseline)
        previous_position = self.position
        self.position = None
        if not self.device.command(f"move {dx} {dy}", self.stopped):
            return
        deadline = time.monotonic() + 1.5
        frame_number = baseline.number
        last_match = None
        while not self.stopped.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            frame = self.device.get_frame(frame_number, timeout=min(.12, remaining))
            if frame is None:
                continue
            frame_number = frame.number
            position = cursor_position(before, grayscale(frame), bounds, expected, previous_position, movement)
            if position is not None and last_match is not None and distance(position, last_match) <= 3 ** 2:
                self.learn_gains(previous_position, position, movement, bounds)
                self.position = self.hint = position
                self.confirmed_at = time.monotonic()
                return
            last_match = position
        self.hint = expected

    def aim(self, target, bounds):
        for _ in range(6):
            if self.position is None:
                for dx, dy in ((-20, 14), (33, 10), (-14, -23)):
                    self.locate(dx, dy, bounds)
                    if self.position is not None or self.stopped.is_set():
                        break
                if self.position is None:
                    return False
            if distance(self.position, target) <= 8 ** 2:
                if time.monotonic() - self.confirmed_at <= .65:
                    return True
                self.locate(12 if target[0] < bounds[2] - 25 else -12, 0, bounds)
                continue
            dx, dy = (max(-limit, min(limit, round((wanted - actual) /
                       (gain if abs(wanted - actual) >= 40 else 1.35))))
                      for wanted, actual, gain, limit in zip(
                          target, self.position, self.gains,
                          (95 if count else 48 for count in self.gain_samples)))
            self.locate(dx, dy, bounds)
        return self.position is not None and distance(self.position, target) <= 8 ** 2
