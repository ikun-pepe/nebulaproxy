import threading
import time
from datetime import datetime


class RuntimeTrafficStats:
    def __init__(self):
        self._lock = threading.Lock()
        self.reset()

    def reset(self):
        with self._lock:
            self.active_connections = 0
            self.total_up_bytes = 0
            self.total_down_bytes = 0
            self._last_up_bytes = 0
            self._last_down_bytes = 0
            self._last_sample_ts = time.time()
            self.current_up_bps = 0.0
            self.current_down_bps = 0.0

    def connection_opened(self):
        with self._lock:
            self.active_connections += 1

    def connection_closed(self):
        with self._lock:
            if self.active_connections > 0:
                self.active_connections -= 1

    def add_bytes(self, direction, count):
        with self._lock:
            if direction == "up":
                self.total_up_bytes += count
            else:
                self.total_down_bytes += count

    def snapshot(self):
        with self._lock:
            now = time.time()
            elapsed = max(now - self._last_sample_ts, 1e-6)
            up_delta = self.total_up_bytes - self._last_up_bytes
            down_delta = self.total_down_bytes - self._last_down_bytes
            self.current_up_bps = up_delta / elapsed
            self.current_down_bps = down_delta / elapsed
            self._last_up_bytes = self.total_up_bytes
            self._last_down_bytes = self.total_down_bytes
            self._last_sample_ts = now
            return {
                "active_connections": self.active_connections,
                "total_up_bytes": self.total_up_bytes,
                "total_down_bytes": self.total_down_bytes,
                "up_bps": self.current_up_bps,
                "down_bps": self.current_down_bps,
            }


runtime_stats = RuntimeTrafficStats()
_active_connections_lock = threading.Lock()
_active_connections = {}
_next_connection_id = 1


def _new_connection_id():
    global _next_connection_id
    with _active_connections_lock:
        conn_id = _next_connection_id
        _next_connection_id += 1
        return conn_id


def register_connection(client_addr):
    conn_id = _new_connection_id()
    started_at = time.time()
    record = {
        "id": conn_id,
        "client_addr": f"{client_addr[0]}:{client_addr[1]}",
        "protocol": "-",
        "target_host": "-",
        "target_port": "-",
        "status": "CONNECTED",
        "started_at": started_at,
        "started_at_text": datetime.fromtimestamp(started_at).strftime("%H:%M:%S"),
        "bytes_up": 0,
        "bytes_down": 0,
    }
    with _active_connections_lock:
        _active_connections[conn_id] = record
    return conn_id


def update_connection(conn_id, **fields):
    with _active_connections_lock:
        record = _active_connections.get(conn_id)
        if not record:
            return
        record.update(fields)


def add_connection_bytes(conn_id, direction, count):
    with _active_connections_lock:
        record = _active_connections.get(conn_id)
        if not record:
            return
        if direction == "up":
            record["bytes_up"] += count
        else:
            record["bytes_down"] += count


def unregister_connection(conn_id):
    with _active_connections_lock:
        _active_connections.pop(conn_id, None)


def get_active_connections():
    with _active_connections_lock:
        snapshot = []
        now = time.time()
        for record in _active_connections.values():
            item = dict(record)
            item["duration_ms"] = int((now - item["started_at"]) * 1000)
            snapshot.append(item)
        snapshot.sort(key=lambda item: item["started_at"], reverse=True)
        return snapshot


def get_runtime_stats():
    return runtime_stats.snapshot()
