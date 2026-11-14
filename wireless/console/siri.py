"""Narrow, authenticated LAN ingress for Siri. No frames or configuration exposed."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread, Lock
import json
import os
import secrets
import time

CONFIG = Path(__file__).resolve().parents[1] / '.runtime' / 'siri.json'


def settings():
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    if not CONFIG.exists():
        fd = os.open(CONFIG, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as f:
            json.dump({'token': secrets.token_urlsafe(32)}, f)
    return json.loads(CONFIG.read_text())


class SiriHandler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def reply(self, status, message, **extra):
        data = json.dumps(dict(message=message, **extra), ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        self.reply(405, '请使用快捷指令提交任务')

    def do_POST(self):
        self.connection.settimeout(3)
        if self.headers.get('Origin') or not secrets.compare_digest(
                self.headers.get('Authorization', ''), 'Bearer ' + self.server.token):
            return self.reply(403, '快捷指令认证失败')
        if self.path != '/task':
            return self.reply(404, '接口不存在')
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 1 <= size <= 4096 or self.headers.get_content_type() != 'application/json':
                raise ValueError('请求格式错误')
            payload = json.loads(self.rfile.read(size))
            task = payload.get('task') if isinstance(payload, dict) else None
            if not isinstance(task, str) or not 1 <= len(task.strip()) <= 500:
                raise ValueError('请说出 1 到 500 字的任务')
            task = task.strip()
            with self.server.gate:
                if task in ('停止', '停止任务', '取消任务'):
                    self.server.console.stop()
                    return self.reply(200, '已停止任务')
                if task in ('连接测试', '测试连接'):
                    return self.reply(200, '已连接科技阁控制服务，语音入口正常')
                if time.monotonic() - self.server.last_submit < 2:
                    return self.reply(429, '任务刚刚收到，请勿重复提交')
                # Return before inference; allow Siri to dismiss before touching the phone.
                job_id = self.server.console.submit(task, defer=4)
                self.server.last_submit = time.monotonic()
            self.reply(202, '好，交给我。', id=job_id)
        except (ValueError, TypeError, OSError, RuntimeError) as exc:
            self.reply(400, str(exc))


def start_gateway(console, host, port=8769):
    server = ThreadingHTTPServer((host, port), SiriHandler)
    server.token = settings()['token']
    server.console = console
    server.gate = Lock()
    server.last_submit = float('-inf')
    Thread(target=server.serve_forever, daemon=True, name='siri-ingress').start()
    return server
