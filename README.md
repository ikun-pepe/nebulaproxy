# NebulaProxy

A Python-based multi-protocol local proxy toolkit with an optional PySide6 desktop console for configuration, validation, and runtime control.

## Overview

NebulaProxy provides a local proxy entrypoint that can accept client traffic in multiple proxy protocols and forward requests either directly to the destination or through an upstream HTTP proxy.

The repository contains two main runtime components:

- `proxy.py`: the core multi-protocol proxy server
- `NebulaGate.py`: a PySide6 desktop GUI for managing configuration and controlling the proxy service

This project is suitable for local proxy testing, upstream proxy validation, and lightweight traffic relay scenarios.

## Features

- Supports multiple client-facing proxy protocols
  - SOCKS5
  - SOCKS4 / SOCKS4a
  - HTTP proxy
  - HTTPS via CONNECT
- Supports two relay modes
  - Direct outbound connection
  - Forwarding through an upstream HTTP proxy
- Optional SOCKS5 username/password authentication for local clients
- Optional Basic authentication for the upstream proxy
- Configurable connection limit
- Configurable relay timeout and buffer size
- Rotating runtime log and traffic log output
- Desktop GUI for loading, saving, validating, starting, stopping, and observing the proxy service

## Repository Layout

```text
.
├── proxy.py         # Core proxy server implementation
├── NebulaGate.py    # PySide6 desktop management console
├── proxy.conf       # Runtime configuration file
└── logs/            # Created automatically at runtime
```

## Requirements

- Python 3.10 or later
- Windows is recommended for the current GUI experience
- `PySide6` is required only for the desktop GUI

## Installation

### Option 1: Core proxy server only

If you only want to run the proxy service from the command line, Python itself is enough for the current codebase.

```bash
python -m pip install --upgrade pip
```

### Option 2: Proxy server with GUI

To use the desktop management console, install the GUI dependency:

```bash
python -m pip install -r requirements.txt
```

Or install it directly:

```bash
python -m pip install PySide6
```

## Configuration

The default configuration file is `proxy.conf`.

### `[remote]` — upstream proxy settings

```ini
[remote]
enabled = false
host = 127.0.0.1
port = 3128
username = your_user
password = your_pass
```

Fields:

- `enabled`: enable or disable upstream proxy mode
- `host`: upstream HTTP proxy host
- `port`: upstream HTTP proxy port
- `username`: upstream proxy username
- `password`: upstream proxy password

When `enabled = false`, the proxy connects directly to the destination host.

### `[local]` — local listener settings

```ini
[local]
host = 127.0.0.1
port = 7463
max_connections = 200
```

Fields:

- `host`: local bind address
- `port`: local listening port
- `max_connections`: maximum concurrent connection count

### `[socks5_auth]` — local SOCKS5 authentication

```ini
[socks5_auth]
enabled = false
username = local_user
password = local_pass
```

Fields:

- `enabled`: enable or disable SOCKS5 username/password authentication
- `username`: SOCKS5 username
- `password`: SOCKS5 password

### `[relay]` — relay settings

```ini
[relay]
timeout = 60
buffer_size = 4096
```

Fields:

- `timeout`: relay timeout in seconds
- `buffer_size`: relay buffer size in bytes

## Usage

### Start the proxy service from the command line

```bash
python proxy.py
```

At startup, the service will:

- read `proxy.conf`
- validate the upstream proxy when enabled
- bind the local listening socket
- create the `logs/` directory if needed
- write runtime and traffic logs

### Start the desktop GUI

```bash
python NebulaGate.py
```

The GUI supports:

- loading configuration
- saving configuration
- validating the upstream proxy
- starting the proxy service
- stopping the proxy service
- viewing runtime logs
- opening the log directory

## Logging

The application creates a `logs/` directory automatically and writes the following files:

- `logs/proxy.log`: runtime events, startup details, and error messages
- `logs/traffic.log`: traffic statistics for handled sessions

The traffic log records:

- timestamp
- client address
- protocol
- target host
- target port
- status
- upstream byte count
- downstream byte count
- elapsed time in milliseconds

## Typical Use Cases

### Local unified proxy endpoint

Configure your browser, script, or client software to use the local listener, for example:

- `127.0.0.1:7463`

NebulaProxy then decides whether to connect directly or route through the configured upstream proxy.

### Upstream proxy validation

If you operate an upstream HTTP proxy, the GUI can be used to verify connectivity and authentication before traffic is relayed through it.

### Access control for SOCKS5 clients

When `[socks5_auth]` is enabled, SOCKS5 clients must authenticate before a connection is established.

## Notes and Limitations

- `NebulaGate.py` uses `os.startfile` to open the log directory, which is Windows-specific behavior.
- Upstream validation currently tests connectivity against `www.baidu.com:80`, so validation may fail in restricted network environments.
- The repository does not currently include a sample config template such as `proxy.example.conf`.
- The repository does not currently include packaging metadata or a release workflow.

## Security Notice

- Do not commit real proxy credentials to source control.
- Keep `proxy.conf` out of public distribution when it contains live usernames or passwords.
- Replace example placeholders with environment-appropriate values before running the service.

## Quick Start

1. Edit `proxy.conf`
2. Choose one startup mode:
   - `python proxy.py`
   - `python NebulaGate.py`
3. Point your client to the configured local listener
4. Check `logs/proxy.log` and `logs/traffic.log`

## English Documentation

For an English version of the documentation, see [README_EN.md](README_EN.md).
