import socket
import time

from ..logging_setup import log, log_traffic
from ..relay import RelayCounter, recv_exact
from ..runtime_stats import update_connection
from ..state import state
from ..upstream import connect_via_upstream


def handle_socks5(client, addr, connection_id=None, first_byte=b""):
    start_ts = time.time()
    target_host = target_port = "?"
    status = "ERROR"
    counter = RelayCounter(connection_id)

    update_connection(connection_id, protocol="SOCKS5", status="HANDSHAKE")
    try:
        header = first_byte + recv_exact(client, 1)
        if header[0] != 0x05:
            raise ValueError(f"非 SOCKS5 协议，版本字节: {header[0]:#x}")

        nmethods = header[1]
        methods = recv_exact(client, nmethods)

        if state.socks5_auth:
            if 0x02 not in methods:
                client.sendall(b"\x05\xFF")
                raise PermissionError("客户端不支持用户名/密码认证")
            client.sendall(b"\x05\x02")
            sub = recv_exact(client, 2)
            uname = recv_exact(client, sub[1]).decode()
            plen = recv_exact(client, 1)[0]
            passwd = recv_exact(client, plen).decode()
            if uname == state.socks5_user and passwd == state.socks5_pass:
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
            length = recv_exact(client, 1)[0]
            target_host = recv_exact(client, length).decode()
        elif atyp == 0x04:
            target_host = socket.inet_ntop(socket.AF_INET6, recv_exact(client, 16))
        else:
            client.sendall(b"\x05\x08\x00\x01\x00\x00\x00\x00\x00\x00")
            raise ValueError(f"不支持的地址类型: {atyp:#x}")

        target_port = int.from_bytes(recv_exact(client, 2), "big")
        update_connection(connection_id, target_host=target_host, target_port=target_port, status="CONNECTING")
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
        update_connection(connection_id, status=status)
        elapsed = int((time.time() - start_ts) * 1000)
        log_traffic(addr, "SOCKS5", target_host, target_port, status, counter.bytes_sent, counter.bytes_recv, elapsed)
        client.close()
