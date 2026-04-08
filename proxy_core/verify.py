import socket

from .config import ProxySettings
from .logging_setup import log
from .state import apply_settings, state
from .upstream import verify_remote_connectivity


def verify_remote(settings: ProxySettings | None = None):
    if settings is not None:
        apply_settings(settings)
    if not state.remote_enabled:
        log.info("直连模式，跳过上游代理验证")
        return True

    test_host, test_port = "www.baidu.com", 80
    log.info("正在验证远端代理连通性...")
    log.info(f"上游: {state.remote_host}:{state.remote_port} | 认证: {'已配置' if state.remote_auth else '未配置'}")

    try:
        status, first_line = verify_remote_connectivity(test_host, test_port)
        if status == 200:
            log.info(f"验证通过 (200) -> {state.remote_host}:{state.remote_port}")
            return True
        if status == 407:
            raise PermissionError("返回 407：用户名/密码错误或未配置，请检查 proxy.conf")
        raise ConnectionError(f"返回异常状态: {first_line}")
    except socket.timeout:
        raise TimeoutError(f"连接超时 ({state.remote_host}:{state.remote_port})，请检查网络或防火墙")
    except ConnectionRefusedError:
        raise ConnectionError(f"连接被拒绝 ({state.remote_host}:{state.remote_port})，Squid 服务是否在运行？")
    except Exception as e:
        raise RuntimeError(f"验证失败: {e}")
