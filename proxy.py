"""
proxy.py — 多协议代理服务器
支持：SOCKS5 / SOCKS4(a) / HTTP / HTTPS CONNECT
功能：流量日志、启动验证、客户端认证、连接数限制、上游连接池
"""

import socket
import threading
import base64
import select
import logging
import logging.handlers
import configparser
import signal
import sys
import os
import time
import struct
import queue
from dataclasses import dataclass
from datetime import datetime

# ── 日志配置 ──────────────────────────────────────────────
os.makedirs("logs", exist_ok=True)

console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

file_handler = logging.handlers.TimedRotatingFileHandler(
    "logs/proxy.log", when="midnight", interval=1,
    backupCount=30, encoding="utf-8"
)
file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

logging.basicConfig(level=logging.INFO, handlers=[console_handler, file_handler])
log = logging.getLogger(__name__)

# 流量日志（独立 CSV 文件，按天滚动）
traffic_logger = logging.getLogger("traffic")
traffic_handler = logging.handlers.TimedRotatingFileHandler(
    "logs/traffic.log", when="midnight", interval=1,
    backupCount=30, encoding="utf-8"
)
traffic_handler.setFormatter(logging.Formatter("%(message)s"))
traffic_logger.addHandler(traffic_handler)
traffic_logger.propagate = False
traffic_logger.setLevel(logging.INFO)

traffic_log_path = "logs/traffic.log"
if not os.path.exists(traffic_log_path) or os.path.getsize(traffic_log_path) == 0:
    with open(traffic_log_path, "w", encoding="utf-8") as f:
        f.write("时间,客户端,协议,目标地址,目标端口,状态,上行字节,下行字节,耗时(ms)\n")


def log_traffic(client_addr, protocol, target_host, target_port,
                status, bytes_up=0, bytes_down=0, elapsed_ms=0):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    client_str = f"{client_addr[0]}:{client_addr[1]}" if isinstance(client_addr, tuple) else str(client_addr)
    traffic_logger.info(
        f"{now},{client_str},{protocol},{target_host},{target_port},"
        f"{status},{bytes_up},{bytes_down},{elapsed_ms}"
    )


# ── 读取配置 ──────────────────────────────────────────────

@dataclass
class ProxySettings:
    remote_host: str
    remote_port: int
    remote_user: str
    remote_pass: str
    local_host: str
    local_port: int
    max_conn: int
    remote_enabled: bool
    socks5_auth: bool
    socks5_user: str
    socks5_pass: str
    relay_timeout: int
    buffer_size: int


def settings_from_config(cfg: configparser.ConfigParser) -> ProxySettings:
    return ProxySettings(
        remote_host=cfg.get("remote", "host"),
        remote_port=cfg.getint("remote", "port"),
        remote_user=cfg.get("remote", "username", fallback="").strip(),
        remote_pass=cfg.get("remote", "password", fallback="").strip(),
        local_host=cfg.get("local", "host", fallback="127.0.0.1"),
        local_port=cfg.getint("local", "port", fallback=7463),
        max_conn=cfg.getint("local", "max_connections", fallback=200),
        remote_enabled=cfg.getboolean("remote", "enabled", fallback=True),
        socks5_auth=cfg.getboolean("socks5_auth", "enabled", fallback=False),
        socks5_user=cfg.get("socks5_auth", "username", fallback="").strip(),
        socks5_pass=cfg.get("socks5_auth", "password", fallback="").strip(),
        relay_timeout=cfg.getint("relay", "timeout", fallback=60),
        buffer_size=cfg.getint("relay", "buffer_size", fallback=4096),
    )


def load_config(path="proxy.conf"):
    if not os.path.exists(path):
        raise FileNotFoundError(f"配置文件不存在: {path}")
    cfg = configparser.ConfigParser()
    cfg.read(path, encoding="utf-8")

    log.info("=" * 40)
    log.info(f"配置文件: {os.path.abspath(path)}")
    for section in cfg.sections():
        log.info(f"[{section}]")
        for key, value in cfg.items(section):
            if "pass" in key or "password" in key:
                display = value[:2] + "***" if value.strip() else "(空)"
            else:
                display = value.strip() if value.strip() else "(空)"
            log.info(f"  {key} = {display}")
    log.info("=" * 40)

    return cfg


CFG = None
REMOTE_HOST = ""
REMOTE_PORT = 0
REMOTE_USER = ""
REMOTE_PASS = ""
LOCAL_HOST = "127.0.0.1"
LOCAL_PORT = 7463
MAX_CONN = 200
REMOTE_ENABLED = True
SOCKS5_AUTH = False
SOCKS5_USER = ""
SOCKS5_PASS = ""
RELAY_TIMEOUT = 60
BUFFER_SIZE = 4096
REMOTE_AUTH = None
_semaphore = threading.Semaphore(MAX_CONN)


def apply_settings(settings: ProxySettings):
    global REMOTE_HOST, REMOTE_PORT, REMOTE_USER, REMOTE_PASS
    global LOCAL_HOST, LOCAL_PORT, MAX_CONN, REMOTE_ENABLED
    global SOCKS5_AUTH, SOCKS5_USER, SOCKS5_PASS
    global RELAY_TIMEOUT, BUFFER_SIZE, REMOTE_AUTH, _semaphore

    REMOTE_HOST = settings.remote_host
    REMOTE_PORT = settings.remote_port
    REMOTE_USER = settings.remote_user
    REMOTE_PASS = settings.remote_pass
    LOCAL_HOST = settings.local_host
    LOCAL_PORT = settings.local_port
    MAX_CONN = settings.max_conn
    REMOTE_ENABLED = settings.remote_enabled
    SOCKS5_AUTH = settings.socks5_auth
    SOCKS5_USER = settings.socks5_user
    SOCKS5_PASS = settings.socks5_pass
    RELAY_TIMEOUT = settings.relay_timeout
    BUFFER_SIZE = settings.buffer_size
    REMOTE_AUTH = (
        base64.b64encode(f"{REMOTE_USER}:{REMOTE_PASS}".encode()).decode()
        if REMOTE_USER and REMOTE_PASS else None
    )
    _semaphore = threading.Semaphore(MAX_CONN)


def configure_from_file(path="proxy.conf"):
    global CFG
    CFG = load_config(path)
    settings = settings_from_config(CFG)
    apply_settings(settings)
    return CFG


class UpstreamPool:
    """
    维护一个到上游 Squid 的 TCP 空闲连接池。
    - 每条隧道建立后连接专属于该请求，用完即丢不归还
    - 连接池复用的是握手阶段的 TCP 连接，减少并发时三次握手开销
    """

    def __init__(self, host, port, max_idle=20):
        self.host     = host
        self.port     = port
        self.max_idle = max_idle
        self._pool    = queue.Queue()
        self._lock    = threading.Lock()
        self._total   = 0

    def _new_conn(self):
        sock = socket.create_connection((self.host, self.port), timeout=15)
        sock.settimeout(15)
        with self._lock:
            self._total += 1
        return sock

    def _is_alive(self, sock):
        """非阻塞探测连接是否还活着"""
        try:
            sock.settimeout(0)
            data = sock.recv(1, socket.MSG_PEEK)
            return data != b""
        except BlockingIOError:
            return True
        except OSError:
            return False

    def get(self):
        """取一个连接，优先复用空闲连接，没有就新建"""
        while not self._pool.empty():
            try:
                sock = self._pool.get_nowait()
                if self._is_alive(sock):
                    sock.settimeout(15)
                    return sock
                sock.close()
                with self._lock:
                    self._total = max(0, self._total - 1)
            except queue.Empty:
                break
        return self._new_conn()

    def discard(self, sock):
        """丢弃一个坏连接"""
        try:
            sock.close()
        except Exception:
            pass
        with self._lock:
            self._total = max(0, self._total - 1)

    @property
    def idle_count(self):
        return self._pool.qsize()

    @property
    def total_count(self):
        return self._total


upstream_pool: UpstreamPool | None = None

server_socket = None
stop_event = threading.Event()

def recv_exact(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("recv_exact: 连接提前关闭")
        buf += chunk
    return buf


class RelayCounter:
    """双向流量计数中继"""

    def __init__(self):
        self.bytes_sent = 0    # client → remote
        self.bytes_recv = 0    # remote → client
        self._lock = threading.Lock()

    def relay_one(self, src, dst, direction):
        try:
            while True:
                r, _, _ = select.select([src], [], [], RELAY_TIMEOUT)
                if not r:
                    break
                data = src.recv(BUFFER_SIZE)
                if not data:
                    break
                dst.sendall(data)
                with self._lock:
                    if direction == "up":
                        self.bytes_sent += len(data)
                    else:
                        self.bytes_recv += len(data)
        except OSError:
            pass
        except Exception as e:
            log.debug(f"中继异常 [{direction}]: {e}")

    def run(self, client, remote):
        t1 = threading.Thread(target=self.relay_one, args=(client, remote, "up"),   daemon=True)
        t2 = threading.Thread(target=self.relay_one, args=(remote, client, "down"), daemon=True)
        t1.start(); t2.start()
        t1.join();  t2.join()


# ── 连接上游代理 ──────────────────────────────────────────
def connect_via_upstream(target_host, target_port):
    if not REMOTE_ENABLED:
        try:
            sock = socket.create_connection((target_host, target_port), timeout=15)
            sock.settimeout(None)
            return sock
        except TimeoutError:
            raise TimeoutError(f"[connect_via_upstream] 直连超时 -> {target_host}:{target_port}")
        except ConnectionRefusedError:
            raise ConnectionError(f"[connect_via_upstream] 直连被拒绝 -> {target_host}:{target_port}")

    # 最多重试一次（应对连接池里的死连接）
    for attempt in range(2):
        sock = upstream_pool.get()
        try:
            lines = [
                f"CONNECT {target_host}:{target_port} HTTP/1.1",
                f"Host: {target_host}:{target_port}",
            ]
            if REMOTE_AUTH:
                lines.append(f"Proxy-Authorization: Basic {REMOTE_AUTH}")
            lines += ["", ""]
            sock.sendall("\r\n".join(lines).encode())

            resp = b""
            while b"\r\n\r\n" not in resp:
                try:
                    chunk = sock.recv(BUFFER_SIZE)
                except TimeoutError:
                    raise TimeoutError(
                        f"[connect_via_upstream] 等待上游响应超时 "
                        f"-> {target_host}:{target_port} "
                        f"(上游: {REMOTE_HOST}:{REMOTE_PORT})"
                    )
                if not chunk:
                    raise ConnectionError("上游代理意外关闭连接")
                resp += chunk

            first_line = resp.split(b"\r\n")[0].decode(errors="replace")
            try:
                status = int(first_line.split()[1])
            except (IndexError, ValueError):
                raise ConnectionError(f"上游代理返回异常响应：{first_line}")

            if status == 407:
                raise PermissionError("上游代理需要认证 (407)，请检查 proxy.conf 用户名/密码")
            if status != 200:
                raise ConnectionError(f"上游代理拒绝连接：{first_line}")

            sock.settimeout(None)
            return sock

        except ConnectionResetError:
            # 连接池里的死连接，丢掉后重新建一条
            upstream_pool.discard(sock)
            if attempt == 0:
                log.debug(f"[connect_via_upstream] 检测到死连接，自动重试 -> {target_host}:{target_port}")
                continue
            raise ConnectionError(
                f"[connect_via_upstream] 重试后仍然失败 -> {target_host}:{target_port}"
            )
        except Exception:
            upstream_pool.discard(sock)
            raise
# ════════════════════════════════════════════════════════════
#  协议处理器
# ════════════════════════════════════════════════════════════
# ── SOCKS5 ────────────────────────────────────────────────
def handle_socks5(client, addr, first_byte=b""):
    start_ts    = time.time()
    target_host = target_port = "?"
    status      = "ERROR"
    counter     = RelayCounter()

    try:
        header = first_byte + recv_exact(client, 1)
        if header[0] != 0x05:
            raise ValueError(f"非 SOCKS5 协议，版本字节: {header[0]:#x}")

        nmethods = header[1]
        methods  = recv_exact(client, nmethods)

        if SOCKS5_AUTH:
            if 0x02 not in methods:
                client.sendall(b"\x05\xFF")
                raise PermissionError("客户端不支持用户名/密码认证")
            client.sendall(b"\x05\x02")
            sub    = recv_exact(client, 2)
            uname  = recv_exact(client, sub[1]).decode()
            plen   = recv_exact(client, 1)[0]
            passwd = recv_exact(client, plen).decode()
            if uname == SOCKS5_USER and passwd == SOCKS5_PASS:
                client.sendall(b"\x01\x00")
                log.info(f"[handle_socks5] 客户端认证通过: {uname}")
            else:
                client.sendall(b"\x01\x01")
                raise PermissionError(f"客户端认证失败: {uname}")
        else:
            if 0x00 not in methods:
                client.sendall(b"\x05\xFF")
                raise PermissionError("客户端不支持无认证模式")
            client.sendall(b"\x05\x00")

        data = recv_exact(client, 4)
        ver, cmd, _, atyp = data
        if ver != 0x05:
            raise ValueError("SOCKS5 请求版本错误")
        if cmd != 0x01:
            client.sendall(b"\x05\x07\x00\x01\x00\x00\x00\x00\x00\x00")
            raise NotImplementedError(f"不支持的 CMD: {cmd:#x}")

        if atyp == 0x01:
            target_host = socket.inet_ntoa(recv_exact(client, 4))
        elif atyp == 0x03:
            length      = recv_exact(client, 1)[0]
            target_host = recv_exact(client, length).decode()
        elif atyp == 0x04:
            target_host = socket.inet_ntop(socket.AF_INET6, recv_exact(client, 16))
        else:
            client.sendall(b"\x05\x08\x00\x01\x00\x00\x00\x00\x00\x00")
            raise ValueError(f"不支持的地址类型: {atyp:#x}")

        target_port = int.from_bytes(recv_exact(client, 2), "big")
        log.info(f"[handle_socks5] {addr} -> {target_host}:{target_port}")

        remote = connect_via_upstream(target_host, target_port)
        client.settimeout(None)

        local_ip, local_port_num = remote.getsockname()
        client.sendall(
            b"\x05\x00\x00\x01"
            + socket.inet_aton(local_ip)
            + local_port_num.to_bytes(2, "big")
        )

        status = "OK"
        counter.run(client, remote)
        remote.close()

    except TimeoutError as e:
        log.error(f"[handle_socks5] {addr} 超时 -> {target_host}:{target_port} | {e}")
        status = "TIMEOUT"
    except PermissionError as e:
        log.warning(f"[handle_socks5] {addr} 认证错误: {e}")
        status = "AUTH_FAIL"
    except ConnectionError as e:
        log.error(f"[handle_socks5] {addr} 连接错误 -> {target_host}:{target_port} | {e}")
        status = "CONN_FAIL"
    except NotImplementedError as e:
        log.warning(f"[handle_socks5] {addr} 不支持的操作: {e}")
        status = "UNSUPPORTED"
    except ValueError as e:
        log.warning(f"[handle_socks5] {addr} 协议解析错误: {e}")
        status = "PROTO_ERR"
    except Exception as e:
        log.exception(f"[handle_socks5] {addr} 未知异常: {e}")
        status = "ERROR"
    finally:
        elapsed = int((time.time() - start_ts) * 1000)
        log_traffic(addr, "SOCKS5", target_host, target_port,
                    status, counter.bytes_sent, counter.bytes_recv, elapsed)
        client.close()


# ── SOCKS4 / SOCKS4a ──────────────────────────────────────
def handle_socks4(client, addr, first_byte=b""):
    start_ts    = time.time()
    target_host = target_port = "?"
    status      = "ERROR"
    counter     = RelayCounter()

    try:
        rest        = recv_exact(client, 7)
        cmd         = rest[0]
        target_port = struct.unpack("!H", rest[1:3])[0]
        ip_bytes    = rest[3:7]

        userid = b""
        while True:
            c = client.recv(1)
            if not c or c == b"\x00":
                break
            userid += c

        if ip_bytes[:3] == b"\x00\x00\x00" and ip_bytes[3] != 0:
            domain = b""
            while True:
                c = client.recv(1)
                if not c or c == b"\x00":
                    break
                domain += c
            target_host = domain.decode()
        else:
            target_host = socket.inet_ntoa(ip_bytes)

        if cmd != 0x01:
            client.sendall(b"\x00\x5B" + b"\x00" * 6)
            raise NotImplementedError(f"SOCKS4 不支持 CMD: {cmd:#x}")

        log.info(f"[handle_socks4] {addr} -> {target_host}:{target_port}")

        remote = connect_via_upstream(target_host, target_port)
        client.settimeout(None)
        remote.settimeout(None)

        client.sendall(b"\x00\x5A" + struct.pack("!H", target_port) + ip_bytes)

        status = "OK"
        counter.run(client, remote)
        remote.close()

    except TimeoutError as e:
        log.error(f"[handle_socks4] {addr} 超时 -> {target_host}:{target_port} | {e}")
        status = "TIMEOUT"
        try: client.sendall(b"\x00\x5B" + b"\x00" * 6)
        except: pass
    except ConnectionError as e:
        log.error(f"[handle_socks4] {addr} 连接错误 -> {target_host}:{target_port} | {e}")
        status = "CONN_FAIL"
        try: client.sendall(b"\x00\x5B" + b"\x00" * 6)
        except: pass
    except NotImplementedError as e:
        log.warning(f"[handle_socks4] {addr} 不支持的操作: {e}")
        status = "UNSUPPORTED"
    except ValueError as e:
        log.warning(f"[handle_socks4] {addr} 协议解析错误: {e}")
        status = "PROTO_ERR"
    except Exception as e:
        log.exception(f"[handle_socks4] {addr} 未知异常: {e}")
        status = "ERROR"
    finally:
        elapsed = int((time.time() - start_ts) * 1000)
        log_traffic(addr, "SOCKS4", target_host, target_port,
                    status, counter.bytes_sent, counter.bytes_recv, elapsed)
        client.close()


# ── HTTP / HTTPS CONNECT ──────────────────────────────────
def handle_http(client, addr, first_data=b""):
    start_ts    = time.time()
    target_host = target_port = "?"
    status      = "ERROR"
    counter     = RelayCounter()
    is_https    = False

    try:
        buf = first_data
        while b"\r\n\r\n" not in buf:
            chunk = client.recv(BUFFER_SIZE)
            if not chunk:
                raise ConnectionError("读取 HTTP 头部时连接关闭")
            buf += chunk
            if len(buf) > 65536:
                raise ValueError("HTTP 头部超限")

        header_raw, _, body_rest = buf.partition(b"\r\n\r\n")
        lines        = header_raw.split(b"\r\n")
        request_line = lines[0].decode(errors="replace")
        parts        = request_line.split()
        if len(parts) < 2:
            raise ValueError(f"HTTP 请求行格式错误: {request_line}")

        method = parts[0].upper()
        target = parts[1]

        # ── HTTPS CONNECT ──
        if method == "CONNECT":
            is_https = True
            if ":" in target:
                target_host, port_str = target.rsplit(":", 1)
                target_port = int(port_str)
            else:
                target_host = target
                target_port = 443

            log.info(f"[handle_http] {addr} CONNECT {target_host}:{target_port}")
            remote = connect_via_upstream(target_host, target_port)
            client.settimeout(None)
            client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            status = "OK"
            counter.run(client, remote)
            remote.close()

        # ── HTTP 明文代理 ──
        else:
            url = target
            if url.startswith("http://"):
                url = url[7:]
            slash_pos = url.find("/")
            host_part = url[:slash_pos] if slash_pos != -1 else url
            path_part = url[slash_pos:] if slash_pos != -1 else "/"

            if ":" in host_part:
                target_host, port_str = host_part.rsplit(":", 1)
                target_port = int(port_str)
            else:
                target_host = host_part
                target_port = 80

            log.info(f"[handle_http] {addr} {method} {target_host}:{target_port}{path_part}")

            new_first_line = f"{method} {path_part} HTTP/1.1".encode()
            filtered_lines = [new_first_line]
            for line in lines[1:]:
                if not line.lower().startswith(b"proxy-"):
                    filtered_lines.append(line)
            rebuilt = b"\r\n".join(filtered_lines) + b"\r\n\r\n" + body_rest

            remote = connect_via_upstream(target_host, target_port)
            client.settimeout(None)
            remote.sendall(rebuilt)
            status = "OK"
            counter.run(client, remote)
            remote.close()

    except TimeoutError as e:
        log.error(f"[handle_http] {addr} 超时 -> {target_host}:{target_port} | {e}")
        status = "TIMEOUT"
        try: client.sendall(b"HTTP/1.1 504 Gateway Timeout\r\n\r\n")
        except: pass
    except PermissionError as e:
        log.warning(f"[handle_http] {addr} 认证错误: {e}")
        status = "AUTH_FAIL"
        try: client.sendall(b"HTTP/1.1 407 Proxy Authentication Required\r\n\r\n")
        except: pass
    except ConnectionError as e:
        log.error(f"[handle_http] {addr} 连接错误 -> {target_host}:{target_port} | {e}")
        status = "CONN_FAIL"
        try: client.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
        except: pass
    except NotImplementedError as e:
        log.warning(f"[handle_http] {addr} 不支持的操作: {e}")
        status = "UNSUPPORTED"
    except ValueError as e:
        log.warning(f"[handle_http] {addr} 协议解析错误: {e}")
        status = "PROTO_ERR"
        try: client.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\n")
        except: pass
    except Exception as e:
        log.exception(f"[handle_http] {addr} 未知异常: {e}")
        status = "ERROR"
        try: client.sendall(b"HTTP/1.1 500 Internal Server Error\r\n\r\n")
        except: pass
    finally:
        elapsed = int((time.time() - start_ts) * 1000)
        proto   = "HTTPS" if is_https else "HTTP"
        log_traffic(addr, proto, target_host, target_port,
                    status, counter.bytes_sent, counter.bytes_recv, elapsed)
        client.close()

# ── 协议嗅探入口 ──────────────────────────────────────────
def handle_client(client, addr):
    acquired = _semaphore.acquire(blocking=False)
    if not acquired:
        log.warning(f"连接数已满，拒绝 {addr}")
        client.close()
        return

    try:
        client.settimeout(30)
        first = client.recv(1)
        if not first:
            return

        b = first[0]

        if b == 0x05:
            handle_socks5(client, addr, first)
        elif b == 0x04:
            handle_socks4(client, addr, first)
        elif first in (b"G", b"P", b"H", b"D", b"C", b"O", b"T"):
            handle_http(client, addr, first)
        else:
            log.warning(f"[?] {addr} 未知协议首字节: {b:#x}，丢弃连接")

    except Exception as e:
        log.debug(f"[入口] {addr} 异常: {e}")
    finally:
        _semaphore.release()


# ── 启动验证 ──────────────────────────────────────────────
def verify_remote(settings: ProxySettings | None = None):
    if settings is not None:
        apply_settings(settings)
    if not REMOTE_ENABLED:
        log.info("直连模式，跳过上游代理验证")
        return True
    
    test_host, test_port = "www.baidu.com", 80
    log.info("正在验证远端代理连通性...")
    log.info(f"上游: {REMOTE_HOST}:{REMOTE_PORT} | 认证: {'已配置' if REMOTE_AUTH else '未配置'}")

    try:
        remote = socket.create_connection((REMOTE_HOST, REMOTE_PORT), timeout=20)
        remote.settimeout(20)
        lines = [
            f"CONNECT {test_host}:{test_port} HTTP/1.1",
            f"Host: {test_host}:{test_port}",
        ]
        if REMOTE_AUTH:
            lines.append(f"Proxy-Authorization: Basic {REMOTE_AUTH}")
        lines += ["", ""]
        remote.sendall("\r\n".join(lines).encode())

        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = remote.recv(BUFFER_SIZE)
            if not chunk:
                raise ConnectionError("上游代理意外关闭连接")
            resp += chunk

        first_line = resp.split(b"\r\n")[0].decode()
        status     = int(first_line.split()[1])
        remote.close()

        if status == 200:
            log.info(f"验证通过 (200) -> {REMOTE_HOST}:{REMOTE_PORT}")
            return True
        elif status == 407:
            raise PermissionError("返回 407：用户名/密码错误或未配置，请检查 proxy.conf")
        else:
            raise ConnectionError(f"返回异常状态: {first_line}")

    except socket.timeout:
        raise TimeoutError(f"连接超时 ({REMOTE_HOST}:{REMOTE_PORT})，请检查网络或防火墙")
    except ConnectionRefusedError:
        raise ConnectionError(f"连接被拒绝 ({REMOTE_HOST}:{REMOTE_PORT})，Squid 服务是否在运行？")
    except Exception as e:
        raise RuntimeError(f"验证失败: {e}")


# ── 优雅退出 ──────────────────────────────────────────────
def _shutdown(sig=None, frame=None):
    global server_socket
    log.info("正在关闭代理服务...")
    stop_event.set()
    if server_socket:
        try:
            server_socket.close()
        except Exception:
            pass


# ── 启动 ──────────────────────────────────────────────────
def start(settings: ProxySettings | None = None, config_path="proxy.conf", install_signal_handlers=True):
    global upstream_pool, server_socket

    log.info("[start] entering start()")
    stop_event.clear()
    if settings is not None:
        log.info("[start] applying settings from GUI")
        apply_settings(settings)
    else:
        log.info(f"[start] loading config from file: {config_path}")
        configure_from_file(config_path)

    if install_signal_handlers:
        log.info("[start] installing signal handlers")
        signal.signal(signal.SIGINT, _shutdown)
        signal.signal(signal.SIGTERM, _shutdown)

    log.info("[start] verify_remote begin")
    verify_remote()
    log.info("[start] verify_remote success")

    if REMOTE_ENABLED:
        log.info("[start] creating upstream pool")
        upstream_pool = UpstreamPool(REMOTE_HOST, REMOTE_PORT, max_idle=50)
        log.info("上游连接池已初始化，最大空闲连接: 50")
    else:
        upstream_pool = None
        log.info("直连模式，不使用上游连接池")

    log.info(f"[start] binding local server -> {LOCAL_HOST}:{LOCAL_PORT}")
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((LOCAL_HOST, LOCAL_PORT))
    server_socket.listen(128)
    server_socket.settimeout(1)
    log.info("[start] local server bind/listen success")

    log.info("=" * 55)
    log.info(f"  多协议代理已启动  {LOCAL_HOST}:{LOCAL_PORT}")
    log.info(f"  支持协议: SOCKS5 / SOCKS4(a) / HTTP / HTTPS")
    log.info(f"  上游代理: {REMOTE_HOST}:{REMOTE_PORT}")
    log.info(f"  最大连接: {MAX_CONN}")
    log.info(f"  SOCKS5认证: {'启用' if SOCKS5_AUTH else '禁用'}")
    log.info(f"  流量日志: logs/traffic.log")
    log.info("=" * 55)

    while not stop_event.is_set():
        try:
            client, addr = server_socket.accept()
            threading.Thread(target=handle_client, args=(client, addr), daemon=True).start()
        except socket.timeout:
            continue
        except OSError as e:
            if stop_event.is_set():
                break
            log.error(f"Accept 错误: {e}")

    if server_socket:
        try:
            server_socket.close()
        except Exception:
            pass
        server_socket = None


def stop():
    _shutdown()


if __name__ == "__main__":
    start()