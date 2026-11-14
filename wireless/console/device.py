"""Independent Wi-Fi input link and in-memory AirPlay video source."""

from threading import Lock, Thread
import time
import os
import subprocess
import sys

from .airplay import AirPlaySource
from .network import NetworkLink
from .observation import after_action, delta, view


class Device:
    def __init__(self, serial_port=None):
        self.network = NetworkLink(serial_port)
        self.source = AirPlaySource()
        self.lock = Lock()
        self.paired = self.keyboard = self.connected = False
        self.input_error = "请配置开发板 Wi-Fi"
        self.command_ms = None
        self.observation = None
        self._observation_frame = None
        self._command_generation = 0
        Thread(target=self.poll, daemon=True, name="wireless-status").start()

    def poll(self):
        while True:
            try:
                state = self.network.status()
                with self.lock:
                    self.connected = True
                    self.paired = bool(state.get("paired") and state.get("mouse"))
                    self.keyboard = bool(state.get("keyboard"))
                    self.input_error = "" if self.paired else "请在 iPhone 配对 TechGe Wireless iPhone"
            except (OSError, RuntimeError, ValueError) as error:
                with self.lock:
                    self.connected = self.paired = self.keyboard = False
                    self.input_error = str(error)
            time.sleep(.6)

    def command(self, command, stopped=None):
        with self.lock:
            self._command_generation += 1
            generation = self._command_generation
            self._observation_frame = None
        if stopped is not None and stopped.is_set():
            return False
        started = time.monotonic()
        observes = command.split()[0] in ('click', 'drag', 'type')
        before = self.source.get_frame() if observes else None
        self.network.command(command)
        acknowledged = time.monotonic()
        with self.lock:
            self.command_ms = round((acknowledged - started) * 1000, 1)
        if observes:
            frame, result = after_action(self.source, before, acknowledged, stopped)
            if frame is None:
                return False
            with self.lock:
                self.observation = {'before': before.number if before else 0,
                                    'after': frame.number, 'result': result,
                                    'ms': round((time.monotonic()-acknowledged)*1000,1)}
                if (generation == self._command_generation and stopped is not None
                        and not stopped.is_set() and result in ('changed', 'unchanged')):
                    self._observation_frame = (stopped, frame, generation)
        return True

    def consume_observation_frame(self, stopped, max_age=.5):
        """Reuse a just-settled action result once, only within its owning task.

        A newer unchanged frame is preferable to the sampled result. If a later
        transition has started, the caller must take its normal fresh/settle path.
        This never reuses frames across tasks, commands, cancellation or outages.
        """
        with self.lock:
            pending, self._observation_frame = self._observation_frame, None
        if pending is None or stopped is None or stopped.is_set():
            return None
        owner, frame, generation = pending
        if owner is not stopped or time.monotonic() - frame.time > max_age:
            return None
        latest = self.source.get_frame()
        if (latest is None or latest.number < frame.number or latest.time < frame.time
                or (latest.width, latest.height) != (frame.width, frame.height)
                or time.monotonic() - latest.time > max_age):
            return None
        if latest.number != frame.number and delta(view(frame), view(latest)) > .8:
            return None
        with self.lock:
            if generation != self._command_generation or stopped.is_set():
                return None
        return latest

    def get_frame(self, after=0, timeout=0):
        return self.source.get_frame(after, timeout)

    def fresh_frame(self):
        previous = self.source.get_frame()
        frame = self.source.get_frame(previous.number if previous else 0, timeout=.35)
        if frame is None and self.paired:
            # AirPlay can stop producing frames for an unchanged screen. Request
            # visible feedback without clicking; only accept a newly decoded frame.
            self.command("move 2 0")
            frame = self.source.get_frame(previous.number if previous else 0, timeout=3)
            if frame is None:
                # At a screen edge, the first nudge may not change the image.
                self.command("move -2 0")
                frame = self.source.get_frame(previous.number if previous else 0, timeout=3)
        if frame is None:
            raise RuntimeError("自动恢复画面未成功：蓝牙唤醒后仍未收到新帧，任务已停止，尚未接通独立截图重连通道")
        return frame

    def recover_receiver(self):
        """One bounded restart after a failed fresh-frame probe, never per frame."""
        if sys.platform != "darwin":
            return False
        try:
            result = subprocess.run(
                ["/bin/launchctl", "kickstart", "-k", f"gui/{os.getuid()}/cn.techge.iphone.receiver"],
                capture_output=True, timeout=10)
            return result.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    def snapshot(self):
        screen = self.source.snapshot()
        frame = self.source.get_frame()
        with self.lock:
            return dict(screen, paired=self.paired, keyboard=self.keyboard,
                        input_connected=self.connected, input_error=self.input_error,
                        command_ms=self.command_ms, mode="fast", transport="wifi", exposure=0,
                        observation=self.observation,
                        bytes=len(frame.jpeg) if frame else 0)

    def set_mode(self, mode):
        if mode != "fast":
            raise ValueError("无线屏幕版本使用低延迟模式")

    def set_meter(self, region):
        raise ValueError("屏幕内容直接读取，无需相机测光")
