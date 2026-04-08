# NebulaProxy

> 一个本地多协议代理入口，支持 SOCKS5、SOCKS4/4a、HTTP、HTTPS CONNECT，并提供可选的 PySide6 图形管理界面。

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![Protocols](https://img.shields.io/badge/Protocols-SOCKS5%20%7C%20SOCKS4a%20%7C%20HTTP%20%7C%20HTTPS-1F6FEB)
![GUI](https://img.shields.io/badge/GUI-PySide6-41CD52?logo=qt&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-2EA043)

## 功能概览

- 支持 SOCKS5、SOCKS4/4a、HTTP、HTTPS CONNECT 入站代理请求
- 支持直连目标地址，或经上游 HTTP 代理转发
- 支持本地 SOCKS5 用户名/密码认证
- 支持上游代理 Basic 认证
- 提供 GUI 用于配置读写、上游验证、代理启停、日志查看
- 提供运行日志、流量日志和 GUI 调试日志

## 快速开始

1. 参考 `config/proxy.example.conf` 准备本地配置文件 `config/proxy.conf`
2. 选择启动方式：
   - CLI：`python proxy.py`
   - GUI：`python NebulaGate.py`
3. 将客户端代理指向本地监听地址
4. 检查 `logs/proxy.log` 与 `logs/traffic.log`

## 入口文件

- `proxy.py`：CLI / 兼容入口
- `NebulaGate.py`：GUI / 兼容入口

核心实现已经拆分到 `proxy_core/` 中，根目录主要保留入口文件和项目元信息。

## 目录结构

```text
.
├── proxy.py
├── NebulaGate.py
├── proxy_core/
│   ├── handlers/
│   └── ...
├── config/
│   ├── proxy.conf
│   └── proxy.example.conf
├── docs/
│   ├── README_EN.md
│   └── CHANGELOG.md
├── logs/
├── README.md
├── LICENSE
└── requirements.txt
```

## 配置说明

默认配置文件位置：`config/proxy.conf`

示例配置文件位置：`config/proxy.example.conf`

配置主要分为四部分：

- `[remote]`：上游 HTTP 代理配置
- `[local]`：本地监听地址、端口、最大连接数
- `[socks5_auth]`：本地 SOCKS5 认证配置
- `[relay]`：中继超时与缓冲区大小

注意：`config/proxy.conf` 可能包含真实代理地址、用户名和密码，请不要直接提交到版本控制系统。

## 日志

运行后会在 `logs/` 下生成日志文件：

- `logs/proxy.log`：运行日志与错误日志
- `logs/traffic.log`：连接与流量日志
- `logs/nebulagate_debug.log`：GUI 调试日志

## 依赖与平台

- Python 3.10+
- 使用 GUI 时需要安装 `PySide6`
- GUI 在 Windows 下体验更完整

安装 GUI 依赖：

```bash
python -m pip install -r requirements.txt
```

## 更多文档

- 英文文档：`docs/README_EN.md`
- 变更记录：`docs/CHANGELOG.md`

## 安全提醒

- 不要提交真实的 `config/proxy.conf`
- 不要在截图、日志或文档中泄露上游代理凭据
- 建议使用 `config/proxy.example.conf` 初始化新环境

## License

MIT
