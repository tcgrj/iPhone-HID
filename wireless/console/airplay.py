"""Read UxPlay multipart JPEG over loopback; retain only the newest frame in RAM."""

from collections import deque
from io import BytesIO
import math
import socket
from threading import Condition, Event, Thread
import time

from PIL import Image, UnidentifiedImageError

from .screen import ScreenFrame

MAX_FRAME = 8_000_000
MAX_HEADER = 4096


class MultipartReader:
    """Length-delimited GStreamer multipartmux output, including fragmented TCP reads."""
    def __init__(self, connection):
        self.connection = connection
        self.buffer = bytearray()

    def _more(self):
        # A static AirPlay screen may stop producing frames. Keep the same
        # multipart buffer and connection; timeout is not an EOF/disconnect.
        while True:
            try:
                data = self.connection.recv(65536)
                break
            except socket.timeout:
                continue
        if not data:
            raise EOFError('无线投屏连接已断开')
        self.buffer.extend(data)

    def next_jpeg(self):
        while True:
            end = self.buffer.find(b'\r\n\r\n')
            if end >= 0:
                if end > MAX_HEADER:
                    raise ValueError('投屏帧头过大')
                break
            if len(self.buffer) > MAX_HEADER:
                raise ValueError('投屏帧头过大')
            self._more()
        header = bytes(self.buffer[:end]).lstrip(b'\r\n')
        del self.buffer[:end + 4]
        lines = header.split(b'\r\n')
        if not lines or not lines[0].startswith(b'--'):
            raise ValueError('投屏数据不是 multipart JPEG')
        fields = {}
        for line in lines[1:]:
            name, separator, value = line.partition(b':')
            if not separator or name.lower() in fields:
                raise ValueError('投屏帧头无效')
            fields[name.lower()] = value.strip()
        length = fields.get(b'content-length', b'')
        if not length.isdigit():
            raise ValueError('投屏帧缺少有效长度')
        size = int(length)
        if not 4 <= size <= MAX_FRAME:
            raise ValueError('投屏帧长度超出限制')
        if fields.get(b'content-type', b'').split(b';')[0].strip().lower() != b'image/jpeg':
            raise ValueError('投屏帧不是 JPEG')
        while len(self.buffer) < size:
            self._more()
        jpeg = bytes(self.buffer[:size])
        del self.buffer[:size]
        if not jpeg.startswith(b'\xff\xd8') or not jpeg.endswith(b'\xff\xd9'):
            raise ValueError('投屏 JPEG 不完整')
        return jpeg


def pad_frame(jpeg):
    """Preserve scale on both axes, padding to the controller's 4:3 coordinate space."""
    with Image.open(BytesIO(jpeg)) as original:
        if original.format != 'JPEG' or original.width * original.height > 16_000_000:
            raise ValueError('投屏图像尺寸无效')
        image = original.convert('RGB')
    # Smallest 4:3 canvas containing the input, bounded by 1600 x 1200.
    unit = min(400, max(1, math.ceil(max(image.width / 4, image.height / 3))))
    width, height = unit * 4, unit * 3
    image.thumbnail((width, height), Image.Resampling.LANCZOS)
    left, top = (width - image.width) // 2, (height - image.height) // 2
    canvas = Image.new('RGB', (width, height), 'black')
    canvas.paste(image, (left, top))
    output = BytesIO()
    canvas.save(output, 'JPEG', quality=90)
    meter = (left / width, top / height,
             (left + image.width) / width, (top + image.height) / height)
    return output.getvalue(), width, height, meter


class AirPlaySource:
    def __init__(self, host='127.0.0.1', port=8767):
        if host not in ('127.0.0.1', '::1') or type(port) is not int or not 1 <= port <= 65535:
            raise ValueError('投屏帧来源必须是本机 TCP 端口')
        self.host, self.port = host, port
        self.changed = Condition()
        self.stopped = Event()
        self.latest = None
        self.number = 0
        self.pending = None
        self.epoch = 0
        self.connection = None
        self.meter = (0.0, 0.0, 1.0, 1.0)
        self.error = '等待 iPhone 连接无线投屏'
        self.times = deque(maxlen=30)
        self.receiver = Thread(target=self._receive, name='airplay-reader', daemon=True)
        self.encoder = Thread(target=self._encode, name='airplay-frame', daemon=True)
        self.receiver.start()
        self.encoder.start()

    def _receive(self):
        while not self.stopped.is_set():
            connection = None
            try:
                connection = socket.create_connection((self.host, self.port), timeout=2)
                connection.settimeout(3)
                with self.changed:
                    self.connection = connection
                    self.epoch += 1
                    epoch = self.epoch
                reader = MultipartReader(connection)
                while not self.stopped.is_set():
                    jpeg = reader.next_jpeg()
                    with self.changed:
                        self.pending = (epoch, time.monotonic(), jpeg)
                        self.changed.notify_all()
            except (OSError, EOFError, ValueError) as exc:
                with self.changed:
                    self.epoch += 1
                    self.pending = self.latest = None
                    self.times.clear()
                    self.error = ('等待 iPhone 连接无线投屏' if isinstance(exc, (ConnectionRefusedError, socket.timeout))
                                  else str(exc))
                    self.changed.notify_all()
            finally:
                if connection is not None:
                    connection.close()
                with self.changed:
                    self.connection = None
            self.stopped.wait(.5)

    def _encode(self):
        while not self.stopped.is_set():
            with self.changed:
                self.changed.wait_for(lambda: self.pending is not None or self.stopped.is_set())
                if self.stopped.is_set():
                    return
                epoch, received, jpeg = self.pending
                self.pending = None
            try:
                encoded, width, height, meter = pad_frame(jpeg)
            except (OSError, UnidentifiedImageError, ValueError, Image.DecompressionBombError):
                with self.changed:
                    if epoch == self.epoch:
                        self.error = '收到无效的投屏图像'
                continue
            with self.changed:
                if epoch != self.epoch or self.stopped.is_set():
                    continue
                self.number += 1
                self.latest = ScreenFrame(self.number, received, encoded, width, height)
                self.times.append(received)
                self.meter = meter
                self.error = ''
                self.changed.notify_all()

    def get_frame(self, after=0, timeout=0):
        with self.changed:
            self.changed.wait_for(lambda: self.stopped.is_set() or
                                  (self.latest is not None and self.latest.number > after), timeout)
            if self.latest is not None and self.latest.number > after:
                return self.latest
            return None

    def snapshot(self):
        with self.changed:
            age = time.monotonic() - self.latest.time if self.latest else None
            live = age is not None and age < 2 and not self.stopped.is_set()
            span = self.times[-1] - self.times[0] if len(self.times) > 1 else 0
            return dict(live=live, age=round(age, 2) if age is not None else None,
                        error='' if live else (self.error or '画面暂未更新，执行时将自动尝试恢复'),
                        fps=round((len(self.times) - 1) / span, 1) if span > 0 and live else 0,
                        width=self.latest.width if self.latest else 0,
                        height=self.latest.height if self.latest else 0,
                        frames=self.number, meter=self.meter)

    def close(self):
        self.stopped.set()
        with self.changed:
            connection = self.connection
            self.epoch += 1
            self.pending = self.latest = None
            self.times.clear()
            self.error = '无线投屏已停止'
            self.changed.notify_all()
        if connection is not None:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        self.receiver.join(timeout=3)
        self.encoder.join(timeout=3)
