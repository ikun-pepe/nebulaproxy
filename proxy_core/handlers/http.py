import time

from ..logging_setup import log, log_traffic
from ..relay import RelayCounter
from ..runtime_stats import update_connection
from ..state import state
from ..upstream import connect_via_upstream


def handle_http(client, addr, connection_id=None, first_data=b""):
    start_ts = time.time()
    target_host = target_port = "?"
    status = "ERROR"
    counter = RelayCounter(connection_id)
    is_https = False

    update_connection(connection_id, protocol="HTTP", status="HANDSHAKE")
    try:
        buf = first_data
        while b"\r\n\r\n" not in buf:
            chunk = client.recv(state.buffer_size)
            if not chunk:
                raise ConnectionError("读取 HTTP 头部时连接关闭")
            buf += chunk
            if len(buf) > 65536:
                raise ValueError("HTTP 头部超限")

        header_raw, _, body_rest = buf.partition(b"\r\n\r\n")
        lines = header_raw.split(b"\r\n")
        request_line = lines[0].decode(errors="replace")
        parts = request_line.split()
        if len(parts) < 2:
            raise ValueError(f"HTTP 请求行格式错误: {request_line}")

        method = parts[0].upper()
        target = parts[1]

        if method == "CONNECT":
            is_https = True
            update_connection(connection_id, protocol="HTTPS")
            if ":" in target:
                target_host, port_str = target.rsplit(":", 1)
                target_port = int(port_str)
            else:
                target_host = target
                target_port = 443

            update_connection(connection_id, target_host=target_host, target_port=target_port, status="CONNECTING")
            log.info(f"[handle_http] {addr} CONNECT {target_host}:{target_port}")
            remote = connect_via_upstream(target_host, target_port)
            client.settimeout(None)
            client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            status = "OK"
            update_connection(connection_id, status="ACTIVE")
            counter.run(client, remote)
            remote.close()
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

            update_connection(connection_id, protocol="HTTP", target_host=target_host, target_port=target_port, status="CONNECTING")
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
            update_connection(connection_id, status="ACTIVE")
            counter.run(client, remote)
            remote.close()

    except TimeoutError as e:
        log.error(f"[handle_http] {addr} 超时 -> {target_host}:{target_port} | {e}")
        status = "TIMEOUT"
        try:
            client.sendall(b"HTTP/1.1 504 Gateway Timeout\r\n\r\n")
        except Exception:
            pass
    except PermissionError as e:
        log.warning(f"[handle_http] {addr} 认证错误: {e}")
        status = "AUTH_FAIL"
        try:
            client.sendall(b"HTTP/1.1 407 Proxy Authentication Required\r\n\r\n")
        except Exception:
            pass
    except ConnectionError as e:
        log.error(f"[handle_http] {addr} 连接错误 -> {target_host}:{target_port} | {e}")
        status = "CONN_FAIL"
        try:
            client.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
        except Exception:
            pass
    except NotImplementedError as e:
        log.warning(f"[handle_http] {addr} 不支持的操作: {e}")
        status = "UNSUPPORTED"
    except ValueError as e:
        log.warning(f"[handle_http] {addr} 协议解析错误: {e}")
        status = "PROTO_ERR"
        try:
            client.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\n")
        except Exception:
            pass
    except Exception as e:
        log.exception(f"[handle_http] {addr} 未知异常: {e}")
        status = "ERROR"
        try:
            client.sendall(b"HTTP/1.1 500 Internal Server Error\r\n\r\n")
        except Exception:
            pass
    finally:
        proto = "HTTPS" if is_https else "HTTP"
        update_connection(connection_id, protocol=proto, target_host=target_host, target_port=target_port, status=status)
        elapsed = int((time.time() - start_ts) * 1000)
        log_traffic(addr, proto, target_host, target_port, status, counter.bytes_sent, counter.bytes_recv, elapsed)
        client.close()
