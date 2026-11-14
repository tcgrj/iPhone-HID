"""Small, persistent official Codex app-server client for screen decisions.

The process/connection is reused, but each decision uses an ephemeral thread
with one image and bounded action history. No screenshots or chats are saved.
The model only returns JSON; the existing controller owns all phone actions.
"""
import atexit
import base64
from contextlib import contextmanager
import json
import queue
import subprocess
import tempfile
import threading
import time


class TransportCancelled(Exception):
    pass


DISABLED_FEATURES = (
    'shell_tool', 'apps', 'multi_agent', 'view_image', 'plugins',
    'browser_use', 'computer_use', 'image_generation', 'goals', 'skill_search',
)


class ScreenPlanner:
    def __init__(self, executable):
        self.executable = executable
        self.process = None
        self.lock = threading.Lock()
        self.serial = 0
        self.folder = None
        self.disabled_mcp = None
        atexit.register(self.close)

    @contextmanager
    def _decision_lock(self, stopped):
        # A queued request must remain cancellable without terminating another
        # request which currently owns this persistent process.
        while not stopped.is_set():
            if self.lock.acquire(timeout=.05):
                break
        else:
            raise TransportCancelled
        try:
            if stopped.is_set():
                raise TransportCancelled
            yield
        finally:
            self.lock.release()

    def close(self):
        process, self.process = self.process, None
        self.disabled_mcp = None
        if process is not None:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            for pipe in (process.stdin, process.stdout):
                if pipe:
                    pipe.close()
        if self.folder:
            self.folder.cleanup()
            self.folder = None

    def _send(self, method, params=None, notification=False):
        self.serial += 1
        message = {"method": method}
        if params is not None:
            message["params"] = params
        if not notification:
            message["id"] = self.serial
        self.process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
        self.process.stdin.flush()
        return self.serial

    def _next(self, deadline, stopped):
        while time.monotonic() < deadline:
            if stopped.is_set():
                raise TransportCancelled
            try:
                message = self.events.get(timeout=.05)
            except queue.Empty:
                continue
            if message is None:
                raise RuntimeError("模型连接已退出")
            # Never execute a model-requested external tool or approval.
            if "id" in message and "method" in message:
                self.process.stdin.write(json.dumps({"id": message["id"], "error": {
                    "code": -32601, "message": "Screen planner does not execute tools"}}) + "\n")
                self.process.stdin.flush()
                raise RuntimeError("识屏模型请求了不支持的工具，未执行手机动作")
            if message.get('method') in ('item/started', 'item/completed'):
                item = message.get('params', {}).get('item', {})
                if item.get('type') not in ('userMessage', 'agentMessage', 'reasoning'):
                    # Feature/config restrictions remove tools. This is also a
                    # fail-closed check for a changed server/tool registry; it
                    # cannot undo a tool that the server already executed.
                    raise RuntimeError('识屏模型调用了不支持的工具，已停止本轮')
            return message
        raise RuntimeError("模型识屏超时")

    def _request(self, method, params, stopped, timeout=15):
        request = self._send(method, params)
        deadline = time.monotonic() + timeout
        while True:
            message = self._next(deadline, stopped)
            if message.get("id") == request:
                if "error" in message:
                    raise RuntimeError("模型协议请求失败：" + str(message["error"].get("message", ""))[:250])
                return message["result"]

    def _load_mcp_restrictions(self, stopped):
        """Read only configured server names and disable each for model threads.

        Config tables merge recursively, so an empty mcp_servers table does not
        remove user-configured servers. Commit the cache only after all pages
        succeed; no model thread may run with a partially enumerated registry.
        """
        restrictions, cursors = {}, set()
        cursor = None
        self.disabled_mcp = None
        while True:
            params = {'detail': 'toolsAndAuthOnly', 'limit': 100}
            if cursor is not None:
                params['cursor'] = cursor
            page = self._request('mcpServerStatus/list', params, stopped)
            if not isinstance(page, dict) or not isinstance(page.get('data'), list):
                raise RuntimeError('未能确认外部工具已禁用，已停止识屏')
            for server in page['data']:
                name = server.get('name') if isinstance(server, dict) else None
                if not isinstance(name, str) or not name:
                    raise RuntimeError('外部工具列表无效，已停止识屏')
                restrictions[name] = {'enabled': False}
            cursor = page.get('nextCursor')
            if cursor is None:
                break
            if not isinstance(cursor, str) or not cursor or cursor in cursors or len(cursors) >= 100:
                raise RuntimeError('外部工具列表分页无效，已停止识屏')
            cursors.add(cursor)
        self.disabled_mcp = restrictions

    def _start(self, stopped):
        if (self.process is not None and self.process.poll() is None
                and self.disabled_mcp is not None):
            return
        self.close()
        self.folder = tempfile.TemporaryDirectory(prefix="iphone-planner-")
        self.events = queue.Queue()
        command = [self.executable, "app-server", "--stdio"]
        for feature in DISABLED_FEATURES:
            command.extend(['-c', 'features.' + feature + '=false'])
        command.extend(['-c', 'skills.include_instructions=false',
                        '-c', 'features.skip_host_skill_discovery=true',
                        '-c', 'project_doc_max_bytes=0',
                        '-c', 'tools.update_plan.enabled=false',
                        '-c', 'tools.experimental_request_user_input.enabled=false'])
        self.process = subprocess.Popen(command,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, cwd=self.folder.name, bufsize=1)
        process, events = self.process, self.events

        def reader():
            try:
                for line in process.stdout:
                    try:
                        events.put(json.loads(line))
                    except ValueError:
                        pass
            finally:
                events.put(None)

        threading.Thread(target=reader, daemon=True, name="screen-planner-rpc").start()
        self._request("initialize", {"clientInfo": {
            "name": "techge_iphone", "title": "TechGe iPhone", "version": "0.2"},
            "capabilities": {"experimentalApi": True}}, stopped)
        self._send("initialized", notification=True)
        self._load_mcp_restrictions(stopped)

    def decide(self, instructions, prompt, jpeg, schema, model, effort, stopped):
        """Return parsed JSON and measured timing; never retry a failed decision."""
        with self._decision_lock(stopped):
            started = time.monotonic()
            thread_id = None
            try:
                self._start(stopped)
                if self.disabled_mcp is None:
                    raise RuntimeError('未能确认外部工具已禁用，已停止识屏')
                ready = time.monotonic()
                thread = self._request("thread/start", {
                    "model": model, "ephemeral": True,
                    "cwd": self.folder.name, "approvalPolicy": "never", "sandbox": "read-only",
                    "environments": [], "dynamicTools": [],
                    "baseInstructions": instructions + "\nOnly interpret the attached screen and return JSON. Do not call tools.",
                    "config": {"mcp_servers": self.disabled_mcp, "web_search": "disabled",
                               "features": dict({name: False for name in DISABLED_FEATURES},
                                                skip_host_skill_discovery=True),
                               "skills": {"include_instructions": False, "max_context_tokens": 1},
                               "include_apps_instructions": False,
                               "include_collaboration_mode_instructions": False,
                               "project_doc_max_bytes": 0,
                               "tools": {"update_plan": {"enabled": False},
                                         "experimental_request_user_input": {"enabled": False}}},
                }, stopped)
                thread_id = thread["thread"]["id"]
                submitted = time.monotonic()
                # Data URL stays in memory; no temporary image file is needed.
                request = self._send("turn/start", {
                    "threadId": thread_id, "effort": effort, "summary": "none",
                    "environments": [], "outputSchema": schema,
                    "input": [{"type": "text", "text": prompt},
                              {"type": "image", "url": "data:image/jpeg;base64," +
                               base64.b64encode(jpeg).decode("ascii")}],
                })
                deadline = submitted + 90
                text_parts, final_text, first = [], None, None
                usage = None
                while True:
                    message = self._next(deadline, stopped)
                    if message.get("id") == request and "error" in message:
                        raise RuntimeError("模型拒绝识屏请求：" + str(message["error"].get("message", ""))[:250])
                    params = message.get("params", {})
                    if params.get("threadId") != thread_id:
                        continue
                    method = message.get("method")
                    if method == "item/agentMessage/delta":
                        first = first or time.monotonic()
                        text_parts.append(params.get("delta", ""))
                    elif method == "item/completed":
                        item = params.get("item", {})
                        if item.get("type") == "agentMessage":
                            first = first or time.monotonic()
                            final_text = item.get("text", "")
                    elif method == "thread/tokenUsage/updated":
                        usage = params.get("tokenUsage", {}).get("last")
                    elif method == "turn/completed":
                        turn = params["turn"]
                        if turn.get("status") != "completed":
                            raise RuntimeError("模型识屏未完成：" + str((turn.get("error") or {}).get("message", turn.get("status")))[:250])
                        break
                finished = time.monotonic()
                action = json.loads(final_text if final_text is not None else "".join(text_parts))
                metrics = {"startup_ms": round((ready-started)*1000),
                           "thread_ms": round((submitted-ready)*1000),
                           "first_text_s": round((first-submitted), 2) if first else None,
                           "request_s": round(finished-submitted, 2),
                           "total_s": round(finished-started, 2), "image_bytes": len(jpeg),
                           "usage": usage}
                self._request("thread/unsubscribe", {"threadId": thread_id}, stopped, timeout=3)
                return action, metrics
            except Exception:
                # Closing aborts in-flight work and removes its ephemeral image.
                self.close()
                raise


_planners = {}
_registry_lock = threading.Lock()


def planner(executable):
    with _registry_lock:
        if executable not in _planners:
            _planners[executable] = ScreenPlanner(executable)
        return _planners[executable]
