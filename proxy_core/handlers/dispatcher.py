from ..logging_setup import log
from ..runtime_stats import register_connection, runtime_stats, unregister_connection, update_connection
from ..state import state
from .http import handle_http
from .socks4 import handle_socks4
from .socks5 import handle_socks5


def handle_client(client, addr):
    acquired = state.semaphore.acquire(blocking=False)
    if not acquired:
        log.warning(f"连接数已满，拒绝 {addr}")
        client.close()
        return

    connection_id = register_connection(addr)
    runtime_stats.connection_opened()
    try:
        client.settimeout(30)
        first = client.recv(1)
        if not first:
            return

        b = first[0]

        if b == 0x05:
            handle_socks5(client, addr, connection_id, first)
        elif b == 0x04:
            handle_socks4(client, addr, connection_id, first)
        elif first in (b"G", b"P", b"H", b"D", b"C", b"O", b"T"):
            handle_http(client, addr, connection_id, first)
        elif b == 0x16:
            update_connection(connection_id, status="TLS_PROXY_MISMATCH")
            log.warning(
                f"[TLS?] {addr} 检测到 TLS ClientHello (0x16)，"
                "客户端正在把当前端口当 HTTPS 代理使用；"
                "本程序仅支持 HTTP CONNECT / SOCKS4 / SOCKS5"
            )
        else:
            update_connection(connection_id, status="UNKNOWN")
            log.warning(f"[?] {addr} 未知协议首字节: {b:#x}，丢弃连接")

    except Exception as e:
        update_connection(connection_id, status="ERROR")
        log.debug(f"[入口] {addr} 异常: {e}")
    finally:
        unregister_connection(connection_id)
        runtime_stats.connection_closed()
        state.semaphore.release()
