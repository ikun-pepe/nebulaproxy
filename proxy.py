"""
proxy.py — 多协议代理服务器
支持：SOCKS5 / SOCKS4(a) / HTTP / HTTPS CONNECT
功能：流量日志、启动验证、客户端认证、连接数限制、上游连接池
"""

from proxy_core import (
    ProxySettings,
    apply_settings,
    configure_from_file,
    get_active_connections,
    get_runtime_stats,
    load_config,
    log,
    log_traffic,
    save_config,
    settings_from_config,
    start,
    stop,
    verify_remote,
)
from proxy_core.state import state


def __getattr__(name):
    if name == "upstream_pool":
        return state.upstream_pool
    raise AttributeError(f"module 'proxy' has no attribute {name!r}")


if __name__ == "__main__":
    start()
