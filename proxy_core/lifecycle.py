import signal
import socket
import threading

from .config import DEFAULT_CONFIG_PATH, ProxySettings
from .handlers import handle_client
from .logging_setup import log
from .runtime_stats import runtime_stats
from .state import apply_settings, configure_from_file, state
from .upstream import UpstreamPool
from .verify import verify_remote


def shutdown(sig=None, frame=None):
    log.info("正在关闭代理服务...")
    state.stop_event.set()
    if state.server_socket:
        try:
            state.server_socket.close()
        except Exception:
            pass


def start(settings: ProxySettings | None = None, config_path=DEFAULT_CONFIG_PATH, install_signal_handlers=True):
    log.info("[start] entering start()")
    state.stop_event.clear()
    runtime_stats.reset()
    if settings is not None:
        log.info("[start] applying settings from GUI")
        apply_settings(settings)
    else:
        log.info(f"[start] loading config from file: {config_path}")
        configure_from_file(config_path)

    if install_signal_handlers:
        log.info("[start] installing signal handlers")
        signal.signal(signal.SIGINT, shutdown)
        signal.signal(signal.SIGTERM, shutdown)

    log.info("[start] verify_remote begin")
    verify_remote()
    log.info("[start] verify_remote success")

    if state.remote_enabled:
        log.info("[start] creating upstream pool")
        state.upstream_pool = UpstreamPool(state.remote_host, state.remote_port, max_idle=50)
        log.info("上游连接池已初始化，最大空闲连接: 50")
    else:
        state.upstream_pool = None
        log.info("直连模式，不使用上游连接池")

    log.info(f"[start] binding local server -> {state.local_host}:{state.local_port}")
    state.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    state.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    state.server_socket.bind((state.local_host, state.local_port))
    state.server_socket.listen(128)
    state.server_socket.settimeout(1)
    log.info("[start] local server bind/listen success")

    log.info("=" * 55)
    log.info(f"  多协议代理已启动  {state.local_host}:{state.local_port}")
    log.info("  支持协议: SOCKS5 / SOCKS4(a) / HTTP / HTTPS")
    log.info(f"  上游代理: {state.remote_host}:{state.remote_port}")
    log.info(f"  最大连接: {state.max_conn}")
    log.info(f"  SOCKS5认证: {'启用' if state.socks5_auth else '禁用'}")
    log.info("  流量日志: logs/traffic.log")
    log.info("=" * 55)

    while not state.stop_event.is_set():
        try:
            client, addr = state.server_socket.accept()
            threading.Thread(target=handle_client, args=(client, addr), daemon=True).start()
        except socket.timeout:
            continue
        except OSError as e:
            if state.stop_event.is_set():
                break
            log.error(f"Accept 错误: {e}")

    if state.server_socket:
        try:
            state.server_socket.close()
        except Exception:
            pass
        state.server_socket = None


def stop():
    shutdown()
