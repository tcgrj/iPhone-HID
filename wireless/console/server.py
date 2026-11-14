"""Local AirPlay preview and task console. Run from the project root."""

import argparse
from collections import deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import subprocess
from pathlib import Path
import secrets
import shutil
import time
from threading import Condition, Event, Thread
from urllib.parse import parse_qs, urlsplit

from .agent import Cancelled, run_task
from .device import Device
from .local_planner import settings as planner_settings


STATIC = Path(__file__).with_name("static")
ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
}


class Console:
    def __init__(self, device, codex):
        self.device = device
        self.codex = codex
        self.token = secrets.token_urlsafe(24)
        self.changed = Condition()
        self.jobs = deque(maxlen=25)
        self.pending = deque()
        self.events = deque(maxlen=80)
        self.next_id = 0
        self.revision = 0
        self.active = None
        self.stop_signal = None
        self.refresh_during_plan = False
        self.keep_awake_last = None
        self.keep_awake_error = ""
        if planner_settings().get("keep_awake"):
            Thread(target=self.keep_awake, name="recording-keep-awake", daemon=True).start()
        Thread(target=self.worker, name="tasks", daemon=True).start()

    def keep_awake_tick(self):
        # Serialise with job transitions: never move during aiming/clicking/typing.
        with self.changed:
            if (self.active and not self.refresh_during_plan) or self.pending:
                return
            status = self.device.snapshot()
            if not status.get("paired"):
                return
            try:
                self.device.command("move 1 0")
                self.device.command("move -1 0")
                self.keep_awake_last = time.monotonic()
                self.keep_awake_error = ""
            except (OSError, RuntimeError) as exc:
                self.keep_awake_error = str(exc)[:150]

    def keep_awake(self):
        while True:
            time.sleep(15)
            self.keep_awake_tick()

    def event(self, kind, title, detail, job=None):
        # The caller holds the condition lock.
        self.revision += 1
        self.events.append({
            "id": self.revision, "kind": kind, "title": title, "detail": detail,
            "time": datetime.now().strftime("%H:%M:%S"), "job": job and job["id"],
        })

    def state(self):
        with self.changed:
            return {
                "token": self.token, "device": self.device.snapshot(), "model": bool(self.codex),
                "planner": planner_settings(),
                "keep_awake": {"enabled":bool(planner_settings().get("keep_awake")), "last":self.keep_awake_last,"error":self.keep_awake_error},
                "active": dict(self.active) if self.active else None,
                "jobs": [dict(job) for job in reversed(self.jobs)],
                "events": list(reversed(self.events)),
            }

    def submit(self, task, defer=0):
        if not self.codex:
            raise RuntimeError("Mac 上找不到 Codex CLI")
        with self.changed:
            if len(self.pending) >= 5:
                raise RuntimeError("队列已满")
            self.next_id += 1
            job = {"id": self.next_id, "task": task, "state": "queued", "result": "", "defer": defer}
            self.jobs.append(job)
            self.pending.append(job)
            self.event("task", "收到任务", task, job)
            self.changed.notify()
            return job["id"]

    def worker(self):
        while True:
            with self.changed:
                self.changed.wait_for(lambda: self.pending)
                job = self.pending.popleft()
                self.active = job
                self.refresh_during_plan = False
                self.stop_signal = Event()
                job["state"] = "running"
                self.event("task", "开始执行", job["task"], job)

            def report(kind, title, detail):
                with self.changed:
                    if title.startswith("识别第"):
                        self.refresh_during_plan = True
                    elif title == "识别完成":
                        self.refresh_during_plan = False
                    self.event(kind, title, detail, job)

            try:
                if self.stop_signal.wait(job.get("defer", 0)):
                    raise Cancelled()
                if not self.device.snapshot()["live"]:
                    job["phase"] = "waiting_screen"
                    report("vision", "等待手机画面", "任务已收到，正在尝试唤醒投屏；尚未开始点击")
                    deadline = time.monotonic() + 180
                    try:
                        self.device.fresh_frame()
                    except RuntimeError:
                        if self.stop_signal.is_set():
                            raise Cancelled()
                        try:
                            recovered = self.device.recover_receiver()
                        except (OSError, RuntimeError, TimeoutError):
                            recovered = False
                        report("vision", "正在恢复投屏" if recovered else "投屏恢复未成功",
                               "已重启接收端，等待手机恢复传图；收到新画面后继续任务" if recovered else
                               "没有收到新画面，等待投屏恢复，最多 3 分钟；不会按旧画面点击")
                        while not self.device.snapshot()["live"]:
                            if self.stop_signal.wait(.25):
                                raise Cancelled()
                            if time.monotonic() >= deadline:
                                raise RuntimeError("等待投屏超过 3 分钟。任务已停止，未执行点击。")
                    report("vision", "手机画面已恢复", "继续执行已收到的任务")
                job["phase"] = "executing"
                state, result = run_task(self.codex, self.device, job["task"], self.stop_signal, report)
            except Cancelled:
                state, result = "cancelled", "已停止执行"
            except (OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
                state, result = "blocked", str(exc)
            with self.changed:
                job.update(state=state, result=result)
                title = {"finish": "任务完成", "blocked": "任务暂停", "cancelled": "任务已停止"}[state]
                self.event(state, title, result, job)
                self.active = self.stop_signal = None

    def stop(self):
        with self.changed:
            if self.stop_signal:
                self.stop_signal.set()
            for job in self.pending:
                job.update(state="cancelled", result="已从队列取消")
            self.pending.clear()
            self.event("cancelled", "收到停止指令", "取消待执行的任务")

    def manual(self, key, dx=None, dy=None):
        commands = {"up": ("move 0 -28", "向上"), "down": ("move 0 28", "向下"),
                    "left": ("move -28 0", "向左"), "right": ("move 28 0", "向右"),
                    "click": ("click", "单击"), "swipe-up": ("drag 0 -155 220", "向上滑动"),
                    "swipe-down": ("drag 0 155 220", "向下滑动")}
        if key == "move":
            if any(type(delta) is not int or not -127 <= delta <= 127 for delta in (dx, dy)) or not (dx or dy):
                raise ValueError("移动量须为 -127 到 127 的整数")
            commands[key] = (f"move {dx} {dy}", f"移动指针 Δ {dx}, {dy}")
        if key not in commands:
            raise ValueError("未知指针操作")
        command, detail = commands[key]
        with self.changed:
            if self.active or self.pending:
                raise RuntimeError("请先停止当前任务")
            self.device.command(command)
            self.event("action", "手动操作", detail)

    def quality(self, mode):
        with self.changed:
            if self.active or self.pending:
                raise RuntimeError("请在当前任务结束后切换画质")
            self.device.set_mode(mode)

    def meter(self, region):
        with self.changed:
            if self.active or self.pending:
                raise RuntimeError("请在当前任务结束后调整曝光")
            self.device.set_meter(region)

    def network(self, payload):
        with self.changed:
            if self.active or self.pending:
                raise RuntimeError("请在当前任务结束后配置网络")
            self.device.network.start(payload)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def response(self, status, data=b"", content_type="application/json; charset=utf-8", **headers):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; img-src 'self' blob:; frame-ancestors 'none'")
        for key, value in headers.items():
            self.send_header(key.replace("_", "-"), value)
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def json(self, status, payload):
        self.response(status, json.dumps(payload, ensure_ascii=False).encode())

    def host_allowed(self):
        host = self.headers.get("Host", "")
        return host in (f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}")

    def do_GET(self):
        if not self.host_allowed():
            return self.json(403, {"error": "此页面仅接受本机访问"})
        url = urlsplit(self.path)
        console = self.server.console
        if url.path in ASSETS:
            name, content_type = ASSETS[url.path]
            return self.response(200, (STATIC / name).read_bytes(), content_type)
        if url.path == "/api/state":
            return self.json(200, console.state())
        if url.path == "/api/network":
            return self.json(200, console.device.network.snapshot())
        if url.path == "/api/frame":
            try:
                after = int(parse_qs(url.query).get("after", ["0"])[0])
            except ValueError:
                return self.json(400, {"error": "无效的帧号"})
            frame = console.device.get_frame(after, timeout=1.4)
            if frame is None:
                restarted = after > console.device.snapshot()["frames"]
                return self.response(204, X_Camera_Restarted="1" if restarted else "0")
            return self.response(200, frame.jpeg, "image/jpeg", X_Frame_Number=str(frame.number))
        return self.json(404, {"error": "页面不存在"})

    def do_POST(self):
        console = self.server.console
        origin = self.headers.get("Origin")
        if (not self.host_allowed() or (origin and origin != f"http://{self.headers.get('Host')}")
                or not secrets.compare_digest(self.headers.get("X-Console-Token", ""), console.token)):
            return self.json(403, {"error": "请从本机控制台提交"})
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 1 <= size <= 4096 or self.headers.get_content_type() != "application/json":
                raise ValueError("请求格式不正确")
            payload = json.loads(self.rfile.read(size))
            if not isinstance(payload, dict):
                raise ValueError("请求格式不正确")
            if self.path == "/api/tasks":
                task = payload.get("task")
                if not isinstance(task, str) or not 1 <= len(task.strip()) <= 500:
                    raise ValueError("请输入 1 到 500 字的任务")
                return self.json(202, {"id": console.submit(task.strip())})
            if self.path == "/api/network":
                console.network(payload)
                return self.json(202, {"ok": True})
            if self.path == "/api/stop":
                console.stop()
                return self.json(200, {"ok": True})
            if self.path == "/api/manual":
                console.manual(payload.get("key", ""), payload.get("dx"), payload.get("dy"))
                return self.json(200, {"ok": True})
            if self.path == "/api/quality":
                console.quality(payload.get("mode", ""))
                return self.json(200, {"ok": True})
            if self.path == "/api/meter":
                console.meter(payload.get("region"))
                return self.json(200, {"ok": True})
        except (ValueError, TypeError, OSError, RuntimeError) as exc:
            return self.json(400, {"error": str(exc)})
        return self.json(404, {"error": "操作不存在"})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", help="ESP32 的 Mac 串口")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--siri-host", help="启用 Siri 入口，绑定本机局域网地址")
    args = parser.parse_args()
    codex = os.environ.get("CODEX_BIN") or shutil.which("codex")
    if codex and not (Path(codex).is_file() and os.access(codex, os.X_OK)):
        raise SystemExit("CODEX_BIN must be an executable path")
    if planner_settings().get("keep_awake") and shutil.which("caffeinate"):
        subprocess.Popen(["caffeinate", "-di", "-w", str(os.getpid())], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        server.console = Console(Device(args.serial), codex)
        if args.siri_host:
            from .siri import start_gateway
            start_gateway(server.console, args.siri_host)
        print(f"Local console: http://127.0.0.1:{args.port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            server.console.stop()


if __name__ == "__main__":
    main()
