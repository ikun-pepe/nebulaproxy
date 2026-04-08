import socket
import struct
import time

from ..logging_setup import log, log_traffic
from ..relay import RelayCounter, recv_exact
from ..runtime_stats import update_connection
from ..upstream import connect_via_upstream


def handle_socks4(client, addr, connection_id=None, first_byte=b""):
    start_ts = time.time()
    target_host = target_port = "?"
    status = "ERROR"
    counter = RelayCounter(connection_id)

    update_connection(connection_id, protocol="SOCKS4", status="HANDSHAKE")
    try:
        rest = recv_exact(client, 7)
        cmd = rest[0]
        target_port = struct.unpack("!H", rest[1:3])[0]
        ip_bytes = rest[3:7]

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

        update_connection(connection_id, target_host=target_host, target_port=target_port, status="CONNECTING")
        log.info(f"[handle_socks4] {addr} -> {target_host}:{target_port}")

        remote = connect_via_upstream(target_host, target_port)
        client.settimeout(None)
        remote.settimeout(None)
        client.sendall(b"\x00\x5A" + struct.pack("!H", target_port) + ip_bytes)

        status = "OK"
        update_connection(connection_id, status="ACTIVE")
        counter.run(client, remote)
        remote.close()

    except TimeoutError as e:
        log.error(f"[handle_socks4] {addr} 超时 -> {target_host}:{target_port} | {e}")
        status = "TIMEOUT"
        try:
            client.sendall(b"\x00\x5B" + b"\x00" * 6)
        except Exception:
            pass
    except ConnectionError as e:
        log.error(f"[handle_socks4] {addr} 连接错误 -> {target_host}:{target_port} | {e}")
        status = "CONN_FAIL"
        try:
            client.sendall(b"\x00\x5B" + b"\x00" * 6)
        except Exception:
            pass
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
        update_connection(connection_id, status=status)
        elapsed = int((time.time() - start_ts) * 1000)
        log_traffic(addr, "SOCKS4", target_host, target_port, status, counter.bytes_sent, counter.bytes_recv, elapsed)
        client.close()
