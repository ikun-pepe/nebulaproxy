import base64
import threading
from dataclasses import dataclass, field

from .config import DEFAULT_CONFIG_PATH, load_config, settings_from_config


@dataclass
class RuntimeState:
    cfg: object | None = None
    remote_host: str = ""
    remote_port: int = 0
    remote_auth_mode: str = "basic"
    remote_user: str = ""
    remote_pass: str = ""
    local_host: str = "127.0.0.1"
    local_port: int = 7463
    max_conn: int = 200
    remote_enabled: bool = True
    socks5_auth: bool = False
    socks5_user: str = ""
    socks5_pass: str = ""
    relay_timeout: int = 60
    buffer_size: int = 4096
    remote_auth: str | None = None
    semaphore: threading.Semaphore = field(default_factory=lambda: threading.Semaphore(200))
    upstream_pool = None
    server_socket = None
    stop_event: threading.Event = field(default_factory=threading.Event)


state = RuntimeState()


def apply_settings(settings):
    state.remote_host = settings.remote_host
    state.remote_port = settings.remote_port
    state.remote_auth_mode = settings.remote_auth_mode
    state.remote_user = settings.remote_user
    state.remote_pass = settings.remote_pass
    state.local_host = settings.local_host
    state.local_port = settings.local_port
    state.max_conn = settings.max_conn
    state.remote_enabled = settings.remote_enabled
    state.socks5_auth = settings.socks5_auth
    state.socks5_user = settings.socks5_user
    state.socks5_pass = settings.socks5_pass
    state.relay_timeout = settings.relay_timeout
    state.buffer_size = settings.buffer_size
    state.remote_auth = (
        base64.b64encode(f"{state.remote_user}:{state.remote_pass}".encode()).decode()
        if state.remote_auth_mode == "basic" and state.remote_user and state.remote_pass else None
    )
    state.semaphore = threading.Semaphore(state.max_conn)


def configure_from_file(path=DEFAULT_CONFIG_PATH):
    state.cfg = load_config(path)
    settings = settings_from_config(state.cfg)
    apply_settings(settings)
    return state.cfg


def get_upstream_pool():
    return state.upstream_pool
