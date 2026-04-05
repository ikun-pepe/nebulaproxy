# NebulaProxy

一个基于 Python 的多协议本地代理工具，附带可选的 PySide6 桌面管理界面，用于配置管理、连通性验证和运行控制。

## 项目简介

NebulaProxy 提供一个本地代理入口，可接收多种代理协议的客户端请求，并根据配置选择：

- 直接连接目标主机
- 经由上游 HTTP 代理转发

仓库当前包含两个主要运行组件：

- `proxy.py`：核心多协议代理服务
- `NebulaGate.py`：PySide6 图形管理界面，用于配置、验证和控制代理服务

该项目适用于本地代理测试、上游代理验证以及轻量级流量转发场景。

## 功能特性

- 支持多种客户端代理协议
  - SOCKS5
  - SOCKS4 / SOCKS4a
  - HTTP
  - HTTPS CONNECT
- 支持两种出站模式
  - 直连目标地址
  - 通过上游 HTTP 代理转发
- 支持本地 SOCKS5 用户名/密码认证
- 支持上游代理 Basic 认证
- 支持最大连接数限制
- 支持配置中继超时与缓冲区大小
- 支持运行日志和流量日志
- 提供桌面 GUI，用于加载、保存、验证、启动、停止和观察代理服务

## 仓库结构

```text
.
├── proxy.py           # 核心代理服务实现
├── NebulaGate.py      # PySide6 桌面管理界面
├── proxy.conf         # 实际运行配置文件
├── proxy.example.conf # 脱敏示例配置文件
├── requirements.txt   # GUI 依赖清单
├── LICENSE            # 项目许可证
├── CHANGELOG.md       # 变更记录
└── logs/              # 运行时自动创建
```

## 环境要求

- Python 3.10 或更高版本
- 当前 GUI 使用体验更适合 Windows 环境
- `PySide6` 仅在使用桌面界面时需要安装

## 安装

### 仅使用命令行代理服务

如果只运行命令行代理服务，当前代码库不依赖额外第三方包。

```bash
python -m pip install --upgrade pip
```

### 使用桌面管理界面

如需使用 GUI，请安装依赖：

```bash
python -m pip install -r requirements.txt
```

或直接安装：

```bash
python -m pip install PySide6
```

## 配置说明

默认配置文件为 `proxy.conf`。如需快速开始，建议先复制 `proxy.example.conf` 并根据实际环境修改。

### `[remote]` —— 上游代理配置

```ini
[remote]
enabled = false
host = 127.0.0.1
port = 3128
username = your_user
password = your_pass
```

字段说明：

- `enabled`：是否启用上游代理模式
- `host`：上游 HTTP 代理地址
- `port`：上游 HTTP 代理端口
- `username`：上游代理用户名
- `password`：上游代理密码

当 `enabled = false` 时，服务将直接连接目标地址。

### `[local]` —— 本地监听配置

```ini
[local]
host = 127.0.0.1
port = 7463
max_connections = 200
```

字段说明：

- `host`：本地绑定地址
- `port`：本地监听端口
- `max_connections`：最大并发连接数

### `[socks5_auth]` —— 本地 SOCKS5 认证配置

```ini
[socks5_auth]
enabled = false
username = local_user
password = local_pass
```

字段说明：

- `enabled`：是否启用 SOCKS5 用户名/密码认证
- `username`：SOCKS5 用户名
- `password`：SOCKS5 密码

### `[relay]` —— 数据中继配置

```ini
[relay]
timeout = 60
buffer_size = 4096
```

字段说明：

- `timeout`：中继超时时间，单位为秒
- `buffer_size`：中继缓冲区大小，单位为字节

## 使用方式

### 启动命令行代理服务

```bash
python proxy.py
```

程序启动时会：

- 读取 `proxy.conf`
- 在启用上游代理时执行连通性验证
- 绑定本地监听地址和端口
- 在需要时创建 `logs/` 目录
- 写入运行日志和流量日志

### 启动桌面管理界面

```bash
python NebulaGate.py
```

GUI 提供以下能力：

- 加载配置
- 保存配置
- 验证上游代理
- 启动代理服务
- 停止代理服务
- 查看运行日志
- 快速打开日志目录

## 日志说明

程序会自动创建 `logs/` 目录，并写入以下文件：

- `logs/proxy.log`：运行事件、启动信息和错误日志
- `logs/traffic.log`：已处理连接的流量统计信息

流量日志记录字段包括：

- 时间戳
- 客户端地址
- 协议类型
- 目标主机
- 目标端口
- 状态
- 上行字节数
- 下行字节数
- 耗时（毫秒）

## 典型使用场景

### 本地统一代理入口

将浏览器、脚本或其他客户端指向本地监听地址，例如：

- `127.0.0.1:7463`

NebulaProxy 会根据配置决定是直连还是通过上游代理转发。

### 上游代理连通性验证

如果你维护一个上游 HTTP 代理，可通过 GUI 先验证连通性和认证状态，再让真实流量经过该代理。

### 本地 SOCKS5 访问控制

启用 `[socks5_auth]` 后，SOCKS5 客户端必须先通过认证，代理才会接受连接。

## 注意事项与限制

- `NebulaGate.py` 使用 `os.startfile` 打开日志目录，该行为依赖 Windows。
- 当前上游验证默认以 `www.baidu.com:80` 作为测试目标，因此在受限网络环境中可能验证失败。
- 仓库已提供脱敏示例配置 `proxy.example.conf`，可作为新环境初始化模板。
- 仓库目前未提供打包元数据或发布流程。

## 安全说明

- 不要将真实代理凭据提交到版本控制系统。
- 当 `proxy.conf` 包含真实用户名或密码时，应将其视为敏感文件。
- 在真实环境中运行前，请先将示例占位值替换为实际配置。

## 快速开始

1. 编辑 `proxy.conf`
2. 选择一种启动方式：
   - `python proxy.py`
   - `python NebulaGate.py`
3. 将客户端指向配置好的本地监听地址
4. 检查 `logs/proxy.log` 和 `logs/traffic.log`

## 项目元信息

- 依赖清单：`requirements.txt`
- 示例配置：`proxy.example.conf`
- 许可证：`LICENSE`（MIT）
- 变更记录：`CHANGELOG.md`

## English Documentation

For an English version of the documentation, see [README_EN.md](README_EN.md).
