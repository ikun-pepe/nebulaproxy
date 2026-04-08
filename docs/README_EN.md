# NebulaProxy

A Python-based multi-protocol local proxy toolkit with an optional PySide6 desktop console for configuration, validation, and runtime control.

## Overview

NebulaProxy accepts local client traffic in multiple proxy protocols and forwards it either directly to the target host or through an upstream HTTP proxy.

The repository includes two primary runtime components:

- `proxy.py` — core multi-protocol proxy server
- `NebulaGate.py` — PySide6 desktop GUI for configuration management and service control

This project is suitable for local proxy testing, relay validation, and lightweight proxy gateway scenarios.

## Features

- Multi-protocol proxy support
  - SOCKS5
  - SOCKS4 / SOCKS4a
  - HTTP
  - HTTPS CONNECT
- Two outbound modes
  - Direct connection to the destination
  - Forwarding through an upstream HTTP proxy
- Optional SOCKS5 username/password authentication for local clients
- Optional upstream proxy Basic authentication
- Configurable maximum connection count
- Configurable relay timeout and buffer size
- Runtime logging and traffic logging
- Desktop GUI for configuration, validation, startup, shutdown, and log viewing

## Repository Layout

```text
.
├── proxy.py           # Core proxy server implementation
├── NebulaGate.py      # PySide6 desktop management console
├── proxy.conf         # Active runtime configuration
├── proxy.example.conf # Sanitized example configuration
├── requirements.txt   # GUI dependency list
├── LICENSE            # Project license
├── CHANGELOG.md       # Change history
└── logs/              # Created automatically at runtime
```

## Requirements

- Python 3.10+
- `PySide6` for the GUI application only
- Windows is recommended for the current GUI workflow

## Installation

### Core proxy only

If you only need the command-line proxy service, no third-party dependency is currently required.

```bash
python -m pip install --upgrade pip
```

### Proxy with desktop GUI

Install the GUI dependency with:

```bash
python -m pip install -r requirements.txt
```

Or directly:

```bash
python -m pip install PySide6
```

## Configuration

The default configuration file is `proxy.conf`. For new environments, you can start from `proxy.example.conf` and adjust the values for your setup.

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

- `enabled`: enables or disables upstream proxy mode
- `host`: upstream HTTP proxy host
- `port`: upstream HTTP proxy port
- `username`: upstream proxy username
- `password`: upstream proxy password

When `enabled = false`, the service connects directly to the destination.

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

- `enabled`: enables or disables SOCKS5 username/password authentication
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

### Start the command-line proxy service

```bash
python proxy.py
```

At startup, the service will:

- read `proxy.conf`
- validate the upstream proxy if enabled
- bind the local listening socket
- create the `logs/` directory if necessary
- write runtime and traffic logs

### Start the desktop GUI

```bash
python NebulaGate.py
```

The GUI provides:

- configuration loading
- configuration saving
- upstream proxy validation
- proxy startup
- proxy shutdown
- runtime log viewing
- quick access to the log directory

## Logging

The application creates a `logs/` directory automatically and writes:

- `logs/proxy.log` — runtime events, startup information, and errors
- `logs/traffic.log` — traffic statistics for handled sessions

Traffic records include:

- timestamp
- client address
- protocol
- target host
- target port
- status
- bytes sent upstream
- bytes received downstream
- elapsed time in milliseconds

## Typical Use Cases

### Local unified proxy endpoint

Point local clients to the configured listener, for example:

- `127.0.0.1:7463`

NebulaProxy will then relay traffic either directly or through the configured upstream proxy.

### Upstream proxy verification

Use the GUI to validate connectivity and authentication before routing real client traffic through an upstream proxy.

### Local SOCKS5 access control

When `[socks5_auth]` is enabled, SOCKS5 clients must provide valid credentials before the proxy accepts the session.

## Notes and Limitations

- `NebulaGate.py` uses `os.startfile` to open the log directory, which is Windows-specific.
- Upstream validation currently targets `www.baidu.com:80`, so validation can fail in restricted networks.
- The repository includes a sanitized example configuration file, `proxy.example.conf`, for bootstrapping new environments.
- The repository does not currently provide a packaged installer or release process.

## Security Notice

- Do not commit real proxy credentials to source control.
- Treat `proxy.conf` as sensitive when it contains live usernames or passwords.
- Replace example placeholder values before using the service in a real environment.

## Project Metadata

- Dependency list: `requirements.txt`
- Example configuration: `proxy.example.conf`
- License: `LICENSE` (MIT)
- Changelog: `CHANGELOG.md`

## Quick Start

1. Edit `proxy.conf`
2. Start one of the following:
   - `python proxy.py`
   - `python NebulaGate.py`
3. Point your client to the configured local listener
4. Check `logs/proxy.log` and `logs/traffic.log`
