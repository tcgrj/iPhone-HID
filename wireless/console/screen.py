"""Bounded in-memory frames from one explicitly selected iPhone mirror window."""

from collections import deque
from dataclasses import dataclass
from io import BytesIO
import json
from pathlib import Path
import struct
import subprocess
from threading import Condition, Thread
import time

from PIL import Image

BINARY = Path(__file__).resolve().parents[1] / '.runtime' / 'screen-stream'


@dataclass(frozen=True)
class ScreenFrame:
    number: int
    time: float
    jpeg: bytes
    width: int
    height: int


def list_windows():
    if not BINARY.is_file():
        raise RuntimeError('投屏读取程序尚未编译')
    try:
        result = subprocess.run([str(BINARY), '--list'], capture_output=True, timeout=8)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError('读取投屏窗口超时，请检查系统屏幕录制权限') from exc
    if result.returncode:
        raise RuntimeError(result.stderr.decode('utf-8', errors='replace').strip() or '无法枚举投屏窗口')
    return json.loads(result.stdout)


class ScreenSource:
    def __init__(self):
        self.changed = Condition()
        self.latest = None
        self.number = 0
        self.window_id = None
        self.process = None
        self.generation = 0
        self.error = '请打开 iPhone 镜像并选择投屏窗口'
        self.times = deque(maxlen=30)
        self.diagnostic = ''

    def list_windows(self):
        return list_windows()

    def select(self, window_id):
        # Enumerate only eligible phone surfaces; a caller cannot select arbitrary apps.
        if window_id is not None:
            if type(window_id) is not int or window_id not in {w['windowId'] for w in list_windows()}:
                raise ValueError('请选择当前可用的 iPhone 镜像窗口')
        self.close()
        if window_id is None:
            return
        process = subprocess.Popen([str(BINARY), '--window', str(window_id)],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
        with self.changed:
            self.process = process
            self.window_id = window_id
            self.error = '等待投屏画面'
            self.diagnostic = ''
            generation = self.generation
        Thread(target=self._diagnostics, args=(process, generation), daemon=True).start()
        Thread(target=self._reader, args=(process, generation), daemon=True).start()

    @staticmethod
    def _exact(stream, size):
        chunks = bytearray()
        while len(chunks) < size:
            data = stream.read(size - len(chunks))
            if not data:
                raise EOFError('投屏读取程序已退出')
            chunks.extend(data)
        return bytes(chunks)

    def _diagnostics(self, process, generation):
        for line in iter(process.stderr.readline, b''):
            with self.changed:
                if generation != self.generation:
                    return
                self.diagnostic = line.decode('utf-8', errors='replace').strip()[:700]

    def _reader(self, process, generation):
        try:
            while True:
                size = struct.unpack('>I', self._exact(process.stdout, 4))[0]
                if not 4 <= size <= 8_000_000:
                    raise ValueError('无效的投屏帧长度')
                jpeg = self._exact(process.stdout, size)
                if not jpeg.startswith(b'\xff\xd8') or not jpeg.endswith(b'\xff\xd9'):
                    raise ValueError('投屏帧数据损坏')
                with Image.open(BytesIO(jpeg)) as image:
                    width, height = image.size
                with self.changed:
                    if generation != self.generation:
                        return
                    self.number += 1
                    now = time.monotonic()
                    self.latest = ScreenFrame(self.number, now, jpeg, width, height)
                    self.times.append(now)
                    self.error = ''
                    self.changed.notify_all()
        except (OSError, EOFError, ValueError) as exc:
            with self.changed:
                if generation == self.generation:
                    self.error = self.diagnostic or str(exc)
                    self.latest = None
                    self.times.clear()
                    self.changed.notify_all()
            if process.poll() is None:
                process.terminate()

    def get_frame(self, after=0, timeout=0):
        with self.changed:
            self.changed.wait_for(lambda: self.latest is not None and self.latest.number > after, timeout)
            if self.latest is not None and self.latest.number > after:
                return self.latest
            return None

    def snapshot(self):
        with self.changed:
            age = time.monotonic() - self.latest.time if self.latest else None
            live = age is not None and age < 2
            span = self.times[-1] - self.times[0] if len(self.times) > 1 else 0
            return dict(live=live, error=self.error if not live else '', window_id=self.window_id,
                        frames=self.number, fps=round((len(self.times)-1)/span, 1) if span and live else 0,
                        width=self.latest.width if self.latest else 0,
                        height=self.latest.height if self.latest else 0,
                        age=round(age, 2) if age is not None else None)

    def close(self):
        with self.changed:
            self.generation += 1
            process = self.process
            self.process = None
            self.window_id = None
            self.latest = None
            self.times.clear()
            self.error = '未选择投屏窗口'
            self.changed.notify_all()
        if process is not None:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
            process.stdout.close()
            process.stderr.close()
