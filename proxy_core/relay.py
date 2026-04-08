import select
import threading

from .logging_setup import log
from .runtime_stats import add_connection_bytes, runtime_stats
from .state import state


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

    def __init__(self, connection_id=None):
        self.connection_id = connection_id
        self.bytes_sent = 0
        self.bytes_recv = 0
        self._lock = threading.Lock()

    def relay_one(self, src, dst, direction):
        try:
            while True:
                r, _, _ = select.select([src], [], [], state.relay_timeout)
                if not r:
                    break
                data = src.recv(state.buffer_size)
                if not data:
                    break
                dst.sendall(data)
                with self._lock:
                    if direction == "up":
                        self.bytes_sent += len(data)
                    else:
                        self.bytes_recv += len(data)
                runtime_stats.add_bytes(direction, len(data))
                if self.connection_id is not None:
                    add_connection_bytes(self.connection_id, direction, len(data))
        except OSError:
            pass
        except Exception as e:
            log.debug(f"中继异常 [{direction}]: {e}")

    def run(self, client, remote):
        t1 = threading.Thread(target=self.relay_one, args=(client, remote, "up"), daemon=True)
        t2 = threading.Thread(target=self.relay_one, args=(remote, client, "down"), daemon=True)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
