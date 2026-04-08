import configparser
import os
from dataclasses import dataclass

from .logging_setup import log


DEFAULT_CONFIG_PATH = os.path.join("config", "proxy.conf")
DEFAULT_EXAMPLE_CONFIG_PATH = os.path.join("config", "proxy.example.conf")


@dataclass
class ProxySettings:
    remote_host: str
    remote_port: int
    remote_auth_mode: str
    remote_user: str
    remote_pass: str
    local_host: str
    local_port: int
    max_conn: int
    remote_enabled: bool
    socks5_auth: bool
    socks5_user: str
    socks5_pass: str
    relay_timeout: int
    buffer_size: int


def settings_from_config(cfg: configparser.ConfigParser) -> ProxySettings:
    return ProxySettings(
        remote_host=cfg.get("remote", "host"),
        remote_port=cfg.getint("remote", "port"),
        remote_auth_mode=cfg.get("remote", "auth_mode", fallback="basic").strip().lower(),
        remote_user=cfg.get("remote", "username", fallback="").strip(),
        remote_pass=cfg.get("remote", "password", fallback="").strip(),
        local_host=cfg.get("local", "host", fallback="127.0.0.1"),
        local_port=cfg.getint("local", "port", fallback=7463),
        max_conn=cfg.getint("local", "max_connections", fallback=200),
        remote_enabled=cfg.getboolean("remote", "enabled", fallback=True),
        socks5_auth=cfg.getboolean("socks5_auth", "enabled", fallback=False),
        socks5_user=cfg.get("socks5_auth", "username", fallback="").strip(),
        socks5_pass=cfg.get("socks5_auth", "password", fallback="").strip(),
        relay_timeout=cfg.getint("relay", "timeout", fallback=60),
        buffer_size=cfg.getint("relay", "buffer_size", fallback=4096),
    )


def load_config(path=DEFAULT_CONFIG_PATH):
    if not os.path.exists(path):
        raise FileNotFoundError(f"配置文件不存在: {path}")
    cfg = configparser.ConfigParser()
    cfg.read(path, encoding="utf-8")

    log.info("=" * 40)
    log.info(f"配置文件: {os.path.abspath(path)}")
    for section in cfg.sections():
        log.info(f"[{section}]")
        for key, value in cfg.items(section):
            if "pass" in key or "password" in key:
                display = value[:2] + "***" if value.strip() else "(空)"
            else:
                display = value.strip() if value.strip() else "(空)"
            log.info(f"  {key} = {display}")
    log.info("=" * 40)

    return cfg


def save_config(settings: ProxySettings, path=DEFAULT_CONFIG_PATH):
    cfg = configparser.ConfigParser()
    cfg["remote"] = {
        "enabled": str(settings.remote_enabled).lower(),
        "auth_mode": settings.remote_auth_mode,
        "host": settings.remote_host,
        "port": str(settings.remote_port),
        "username": settings.remote_user,
        "password": settings.remote_pass,
    }
    cfg["local"] = {
        "host": settings.local_host,
        "port": str(settings.local_port),
        "max_connections": str(settings.max_conn),
    }
    cfg["socks5_auth"] = {
        "enabled": str(settings.socks5_auth).lower(),
        "username": settings.socks5_user,
        "password": settings.socks5_pass,
    }
    cfg["relay"] = {
        "timeout": str(settings.relay_timeout),
        "buffer_size": str(settings.buffer_size),
    }
    with open(path, "w", encoding="utf-8") as f:
        cfg.write(f)
