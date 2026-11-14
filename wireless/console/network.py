"""USB provisioning only; ordinary operation uses Wi-Fi and never opens a serial port."""

import json
import http.client
import os
import socket
from pathlib import Path
from threading import Lock, Thread
import time

import serial
from serial.tools import list_ports


CONFIG = Path(__file__).resolve().parents[1] / ".runtime" / "network.json"


class NetworkLink:
    def __init__(self, serial_port=None):
        self.serial_port = serial_port
        self.lock = Lock()
        self.io_lock = Lock()
        self.connection = None
        self.connection_host = ""
        self.tcp = None
        self.tcp_host = ""
        self.recv_buffer = b""
        self.ip = self.token = self.ssid = ""
        self.busy = False
        self.message = "首次使用请连接 USB，填写 2.4 GHz Wi-Fi。"
        try:
            config = json.loads(CONFIG.read_text())
            self.accept(config, save=False)
        except (OSError, ValueError, KeyError):
            pass

    def accept(self, config, save=True):
        import ipaddress
        ip = str(ipaddress.IPv4Address(config["ip"]))
        token = config["token"]
        if ip == "0.0.0.0" or not isinstance(token, str) or not 16 <= len(token) <= 128:
            raise ValueError("开发板尚未获得网络地址")
        value = dict(ip=ip, token=token, ssid=str(config.get("ssid", "")))
        if save:
            CONFIG.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            temporary = CONFIG.with_suffix(".tmp")
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as output:
                json.dump(value, output, ensure_ascii=False)
            os.replace(temporary, CONFIG)
            os.chmod(CONFIG, 0o600)
        with self.lock:
            self.ip, self.token, self.ssid = ip, token, value["ssid"]
            self.message = "已获取开发板地址，正在通过 Wi-Fi 连接。"

    def credentials(self):
        with self.lock:
            return self.ip, self.token

    def request(self, path, payload=None):
        if path != "/status" or payload is not None:
            raise ValueError("HTTP 仅用于读取开发板状态")
        ip, token = self.credentials()
        if not ip or not token:
            raise RuntimeError("请先为开发板配置 Wi-Fi")
        with self.io_lock:
            if self.connection is None or self.connection_host != ip:
                if self.connection is not None:
                    self.connection.close()
                self.connection = http.client.HTTPConnection(ip, timeout=2)
                self.connection_host = ip
            headers = {"X-Device-Token": token, "Content-Type": "application/json"}
            body = None if payload is None else json.dumps(payload).encode()
            try:
                self.connection.request("GET" if payload is None else "POST", path, body=body, headers=headers)
                response = self.connection.getresponse()
                raw = response.read(16385)
                if len(raw) > 16384:
                    raise ValueError("Oversized status reply")
                if response.status == 401:
                    raise RuntimeError("开发板认证信息已变化，请通过 USB 重新读取连接")
                result = json.loads(raw)
                if response.status != 200 or not isinstance(result, dict) or result.get("ok") is False or result.get("error"):
                    raise RuntimeError("开发板拒绝操作，请检查 iPhone 蓝牙连接和输入参数")
                return result
            except RuntimeError:
                self.connection.close()
                self.connection = None
                raise
            except (OSError, ValueError, http.client.HTTPException):
                self.connection.close()
                self.connection = None
                # A lost reply may follow an executed action; never retry automatically.
                raise RuntimeError("开发板 Wi-Fi 通信未确认，请检查连接后重新观察屏幕") from None

    def close_tcp(self):
        if self.tcp is not None:
            self.tcp.close()
        self.tcp = None
        self.tcp_host = ""
        self.recv_buffer = b""

    def tcp_request(self, command):
        ip, token = self.credentials()
        if not ip or not token:
            raise RuntimeError("请先为开发板配置 Wi-Fi")
        with self.io_lock:
            try:
                if self.tcp is None or self.tcp_host != ip:
                    self.close_tcp()
                    self.tcp = socket.create_connection((ip, 8768), timeout=2)
                    self.tcp.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    self.tcp_host = ip
                data = (json.dumps({"token": token, "command": command}, separators=(",", ":")) + "\n").encode()
                deadline = time.monotonic() + 2
                self.tcp.settimeout(2)
                self.tcp.sendall(data)
                while b"\n" not in self.recv_buffer:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("TCP reply timed out")
                    self.tcp.settimeout(remaining)
                    chunk = self.tcp.recv(4096)
                    if not chunk:
                        raise ConnectionError("Peer disconnected")
                    self.recv_buffer += chunk
                    if len(self.recv_buffer.split(b"\n", 1)[0]) > 16384:
                        raise ValueError("Oversized TCP reply")
                line, self.recv_buffer = self.recv_buffer.split(b"\n", 1)
                if len(line) > 16384:
                    raise ValueError("Oversized TCP reply")
                result = json.loads(line)
                if not isinstance(result, dict):
                    raise ValueError("Invalid TCP reply")
                if result.get("ok") is False or result.get("error"):
                    raise RuntimeError("开发板拒绝操作，请检查 iPhone 蓝牙连接和输入参数")
                if command != "status" and result.get("ok") is not True:
                    raise ValueError("Action acknowledgement missing")
                return result
            except RuntimeError:
                self.close_tcp()
                raise
            except (OSError, ValueError):
                self.close_tcp()
                # The input may have reached iOS before the connection failed.
                # Drop this connection and let the caller observe before acting again.
                raise RuntimeError("开发板 Wi-Fi 通信未确认，请检查连接后重新观察屏幕") from None

    def status(self):
        try:
            result = self.tcp_request("status")
        except RuntimeError:
            # A read-only status can use the old HTTP endpoint. Actions never fall back.
            result = self.request("/status")
        with self.lock:
            if not self.busy:
                self.message = "开发板已通过 Wi-Fi 连接"
        return result

    def command(self, command):
        return self.tcp_request(command)

    def snapshot(self):
        ports = [p.device for p in list_ports.comports() if p.vid in (0x303A, 0x1A86)]
        with self.lock:
            return dict(ip=self.ip, ssid=self.ssid, configured=bool(self.ip and self.token),
                        busy=self.busy, message=self.message, ports=ports)

    def start(self, payload):
        refresh = payload.get("refresh") is True
        ssid, password = payload.get("ssid"), payload.get("password")
        if not refresh:
            if not isinstance(ssid, str) or not 1 <= len(ssid.encode()) <= 32:
                raise ValueError("Wi-Fi 名称须为 1 到 32 字节")
            if not isinstance(password, str) or (password and not 8 <= len(password.encode()) <= 63):
                raise ValueError("Wi-Fi 密码须为 8 到 63 字节；开放网络可留空")
        ports = self.snapshot()["ports"]
        port = self.serial_port
        if port is None:
            if len(ports) != 1:
                raise RuntimeError("请只接入这一块 ESP32 开发板，或用 --serial 指定串口")
            port = ports[0]
        with self.lock:
            if self.busy:
                raise RuntimeError("正在配置网络，请稍候")
            self.busy = True
            self.message = "正在读取开发板网络" if refresh else "正在配置 Wi-Fi，请保持 USB 连接"
        Thread(target=self.provision, args=(port, None if refresh else dict(ssid=ssid, password=password)),
               daemon=True, name="wifi-setup").start()

    def provision(self, port, wifi):
        link = serial.Serial(port=None, baudrate=115200, timeout=.25, write_timeout=2)
        try:
            link.port = port
            link.dtr, link.rts = True, False
            link.exclusive = True
            link.open()
            time.sleep(.6)
            link.reset_input_buffer()
            if wifi is not None:
                link.write(("wifi " + json.dumps(wifi, ensure_ascii=False) + "\n").encode())
                wifi = None
                link.flush()
            deadline, next_query = time.monotonic() + 40, 0
            while time.monotonic() < deadline:
                now = time.monotonic()
                if now >= next_query:
                    link.write(b"network\n")
                    next_query = now + 1.5
                line = link.readline(4096)
                try:
                    reply = json.loads(line)
                except (ValueError, UnicodeError):
                    continue
                if isinstance(reply, dict) and reply.get("connected") and reply.get("ip"):
                    self.accept(reply)
                    return
                if isinstance(reply, dict) and reply.get("ok") is False:
                    raise RuntimeError("开发板未接受网络配置，请检查固件与 Wi-Fi 信息")
            raise RuntimeError("开发板尚未连上 Wi-Fi，请检查 2.4 GHz 网络名称和密码")
        except (OSError, RuntimeError, ValueError):
            with self.lock:
                self.message = "配网未完成，请检查 USB 连接、2.4 GHz 网络名称和密码后重试。"
        finally:
            wifi = None
            if link.is_open:
                link.close()
            with self.lock:
                self.busy = False
