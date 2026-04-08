import queue
import socket
import threading

from .logging_setup import log
from .state import state


class UpstreamPool:
    """
    维护一个到上游 Squid 的 TCP 空闲连接池。
    - 每条隧道建立后连接专属于该请求，用完即丢不归还
    - 连接池复用的是握手阶段的 TCP 连接，减少并发时三次握手开销
    """

    def __init__(self, host, port, max_idle=20):
        self.host = host
        self.port = port
        self.max_idle = max_idle
        self._pool = queue.Queue()
        self._lock = threading.Lock()
        self._total = 0

    def _new_conn(self):
        sock = socket.create_connection((self.host, self.port), timeout=15)
        sock.settimeout(15)
        with self._lock:
            self._total += 1
        return sock

    def _is_alive(self, sock):
        try:
            sock.settimeout(0)
            data = sock.recv(1, socket.MSG_PEEK)
            return data != b""
        except BlockingIOError:
            return True
        except OSError:
            return False

    def get(self):
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


def _build_connect_lines(target_host, target_port):
    lines = [
        f"CONNECT {target_host}:{target_port} HTTP/1.1",
        f"Host: {target_host}:{target_port}",
    ]
    if state.remote_auth:
        lines.append(f"Proxy-Authorization: Basic {state.remote_auth}")
    lines += ["", ""]
    return lines


def connect_via_upstream(target_host, target_port):
    if not state.remote_enabled:
        try:
            sock = socket.create_connection((target_host, target_port), timeout=15)
            sock.settimeout(None)
            return sock
        except TimeoutError:
            raise TimeoutError(f"[connect_via_upstream] 直连超时 -> {target_host}:{target_port}")
        except ConnectionRefusedError:
            raise ConnectionError(f"[connect_via_upstream] 直连被拒绝 -> {target_host}:{target_port}")

    for attempt in range(2):
        sock = state.upstream_pool.get()
        try:
            sock.sendall("\r\n".join(_build_connect_lines(target_host, target_port)).encode())

            resp = b""
            while b"\r\n\r\n" not in resp:
                try:
                    chunk = sock.recv(state.buffer_size)
                except TimeoutError:
                    raise TimeoutError(
                        f"[connect_via_upstream] 等待上游响应超时 -> {target_host}:{target_port} "
                        f"(上游: {state.remote_host}:{state.remote_port})"
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
            state.upstream_pool.discard(sock)
            if attempt == 0:
                log.debug(f"[connect_via_upstream] 检测到死连接，自动重试 -> {target_host}:{target_port}")
                continue
            raise ConnectionError(f"[connect_via_upstream] 重试后仍然失败 -> {target_host}:{target_port}")
        except Exception:
            state.upstream_pool.discard(sock)
            raise


def verify_remote_connectivity(test_host, test_port):
    remote = socket.create_connection((state.remote_host, state.remote_port), timeout=20)
    remote.settimeout(20)
    remote.sendall("\r\n".join(_build_connect_lines(test_host, test_port)).encode())

    resp = b""
    while b"\r\n\r\n" not in resp:
        chunk = remote.recv(state.buffer_size)
        if not chunk:
            raise ConnectionError("上游代理意外关闭连接")
        resp += chunk

    first_line = resp.split(b"\r\n")[0].decode()
    status = int(first_line.split()[1])
    remote.close()
    return status, first_line
