import logging
import logging.handlers
import os
from datetime import datetime


LOG_DIR = "logs"
PROXY_LOG_PATH = os.path.join(LOG_DIR, "proxy.log")
TRAFFIC_LOG_PATH = os.path.join(LOG_DIR, "traffic.log")
_TRAFFIC_HEADER = "时间,客户端,协议,目标地址,目标端口,状态,上行字节,下行字节,耗时(ms)\n"


os.makedirs(LOG_DIR, exist_ok=True)


log = logging.getLogger("proxy")
if not log.handlers:
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

    file_handler = logging.handlers.TimedRotatingFileHandler(
        PROXY_LOG_PATH,
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

    log.setLevel(logging.INFO)
    log.addHandler(console_handler)
    log.addHandler(file_handler)
    log.propagate = False


traffic_logger = logging.getLogger("traffic")
if not traffic_logger.handlers:
    traffic_handler = logging.handlers.TimedRotatingFileHandler(
        TRAFFIC_LOG_PATH,
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8",
    )
    traffic_handler.setFormatter(logging.Formatter("%(message)s"))
    traffic_logger.addHandler(traffic_handler)
    traffic_logger.propagate = False
    traffic_logger.setLevel(logging.INFO)


if not os.path.exists(TRAFFIC_LOG_PATH) or os.path.getsize(TRAFFIC_LOG_PATH) == 0:
    with open(TRAFFIC_LOG_PATH, "w", encoding="utf-8") as f:
        f.write(_TRAFFIC_HEADER)


def log_traffic(client_addr, protocol, target_host, target_port, status, bytes_up=0, bytes_down=0, elapsed_ms=0):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    client_str = f"{client_addr[0]}:{client_addr[1]}" if isinstance(client_addr, tuple) else str(client_addr)
    traffic_logger.info(
        f"{now},{client_str},{protocol},{target_host},{target_port},{status},{bytes_up},{bytes_down},{elapsed_ms}"
    )
