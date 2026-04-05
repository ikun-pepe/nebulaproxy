from __future__ import annotations

import configparser
import logging
import os
import sys
import threading
import traceback
from pathlib import Path

DEBUG_MODE = True
DEBUG_LOG_PATH = Path(__file__).with_name("logs") / "nebulagate_debug.log"
DEBUG_LOG_PATH.parent.mkdir(exist_ok=True)

import proxy
from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


CONFIG_PATH = Path(__file__).with_name("proxy.conf")


class QtLogHandler(logging.Handler, QObject):
    log_signal = Signal(str)

    def __init__(self):
        QObject.__init__(self)
        logging.Handler.__init__(self)
        self.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

    def emit(self, record):
        self.log_signal.emit(self.format(record))


class ProxyWorker(QObject):
    started = Signal()
    stopped = Signal()
    failed = Signal(str)

    def __init__(self, settings: proxy.ProxySettings, debug_callback=None):
        super().__init__()
        self.settings = settings
        self.debug_callback = debug_callback

    def _debug(self, message: str):
        if self.debug_callback:
            self.debug_callback(message)

    def run(self):
        try:
            self._debug("worker.run entered")
            self._debug(f"worker settings: remote_enabled={self.settings.remote_enabled}, local={self.settings.local_host}:{self.settings.local_port}, remote={self.settings.remote_host}:{self.settings.remote_port}")
            self.started.emit()
            self._debug("proxy.start about to run")
            proxy.start(settings=self.settings, install_signal_handlers=False)
            self._debug("proxy.start returned normally")
            self.stopped.emit()
        except Exception as exc:
            tb = traceback.format_exc()
            self._debug(f"worker.run failed: {exc}\n{tb}")
            self.failed.emit(f"{exc}\n\n{tb}")


class GuiSignals(QObject):
    started = Signal()
    stopped = Signal()
    failed = Signal(str)


class NebulaGateWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("NebulaGate 多协议代理管理台")
        self.resize(1220, 860)
        self.proxy_thread: threading.Thread | None = None
        self.proxy_running = False
        self.signals = GuiSignals()
        self.signals.started.connect(self._on_backend_started)
        self.signals.stopped.connect(self.on_proxy_stopped)
        self.signals.failed.connect(self.on_proxy_failed)
        self.log_handler = QtLogHandler()
        self.log_handler.log_signal.connect(self.append_log)
        proxy.log.addHandler(self.log_handler)
        self.stop_poll_timer = QTimer(self)
        self.stop_poll_timer.setInterval(300)
        self.stop_poll_timer.timeout.connect(self._check_worker_stopped)
        self._build_ui()
        self.load_config_to_ui(silent=True)

    def debug_log(self, message: str):
        if not DEBUG_MODE:
            return
        line = f"[NebulaGate Debug] {message}"
        with open(DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        self.append_log(line)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        title = QLabel("NebulaGate 多协议代理管理台")
        title.setStyleSheet("font-size:24px;font-weight:700;color:#1d3557;")
        desc = QLabel("用于加载配置、验证上游、启动/停止代理，并实时查看运行日志。")
        desc.setStyleSheet("color:#5b6b84;font-size:13px;")
        root.addWidget(title)
        root.addWidget(desc)

        top = QHBoxLayout()
        top.setSpacing(14)
        root.addLayout(top, 1)

        left = QVBoxLayout()
        left.setSpacing(12)
        top.addLayout(left, 2)

        right = QVBoxLayout()
        right.setSpacing(12)
        top.addLayout(right, 3)

        left.addWidget(self._build_config_group())
        left.addWidget(self._build_control_group())
        left.addWidget(self._build_status_group())
        left.addStretch(1)

        right.addWidget(self._build_log_group(), 1)

    def _build_config_group(self):
        group = QGroupBox("基础配置")
        layout = QGridLayout(group)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(8)

        self.config_path_edit = QLineEdit(str(CONFIG_PATH))
        self.local_host_edit = QLineEdit()
        self.local_port_spin = QSpinBox(); self.local_port_spin.setMaximum(65535)
        self.max_conn_spin = QSpinBox(); self.max_conn_spin.setMaximum(100000)
        self.remote_enabled_check = QCheckBox("启用上游代理")
        self.remote_enabled_check.setStyleSheet("margin-top: 8px; margin-bottom: 4px;")
        self.remote_host_edit = QLineEdit()
        self.remote_port_spin = QSpinBox(); self.remote_port_spin.setMaximum(65535)
        self.remote_user_edit = QLineEdit()
        self.remote_pass_edit = QLineEdit(); self.remote_pass_edit.setEchoMode(QLineEdit.Password)
        self.socks5_auth_check = QCheckBox("启用 SOCKS5 认证")
        self.socks5_auth_check.setStyleSheet("margin-top: 10px; margin-bottom: 4px;")
        self.socks5_user_edit = QLineEdit()
        self.socks5_pass_edit = QLineEdit(); self.socks5_pass_edit.setEchoMode(QLineEdit.Password)
        self.timeout_spin = QSpinBox(); self.timeout_spin.setMaximum(3600)
        self.buffer_spin = QSpinBox(); self.buffer_spin.setMaximum(1024 * 1024)

        layout.addWidget(QLabel("配置文件："), 0, 0)
        layout.addWidget(self.config_path_edit, 0, 1)
        layout.addWidget(QLabel("本地监听地址："), 1, 0)
        layout.addWidget(self.local_host_edit, 1, 1)
        layout.addWidget(QLabel("本地监听端口："), 2, 0)
        layout.addWidget(self.local_port_spin, 2, 1)
        layout.addWidget(QLabel("最大连接数："), 3, 0)
        layout.addWidget(self.max_conn_spin, 3, 1)
        layout.addWidget(self.remote_enabled_check, 4, 0, 1, 2)
        layout.addWidget(QLabel("    上游主机："), 5, 0)
        layout.addWidget(self.remote_host_edit, 5, 1)
        layout.addWidget(QLabel("    上游端口："), 6, 0)
        layout.addWidget(self.remote_port_spin, 6, 1)
        layout.addWidget(QLabel("    上游用户名："), 7, 0)
        layout.addWidget(self.remote_user_edit, 7, 1)
        layout.addWidget(QLabel("    上游密码："), 8, 0)
        layout.addWidget(self.remote_pass_edit, 8, 1)
        layout.addWidget(self.socks5_auth_check, 9, 0, 1, 2)
        layout.addWidget(QLabel("    SOCKS5 用户名："), 10, 0)
        layout.addWidget(self.socks5_user_edit, 10, 1)
        layout.addWidget(QLabel("    SOCKS5 密码："), 11, 0)
        layout.addWidget(self.socks5_pass_edit, 11, 1)
        layout.addWidget(QLabel("中继超时："), 12, 0)
        layout.addWidget(self.timeout_spin, 12, 1)
        layout.addWidget(QLabel("缓冲区大小："), 13, 0)
        layout.addWidget(self.buffer_spin, 13, 1)
        return group

    def _build_control_group(self):
        group = QGroupBox("控制区")
        layout = QHBoxLayout(group)
        self.load_btn = QPushButton("加载配置")
        self.save_btn = QPushButton("保存配置")
        self.verify_btn = QPushButton("验证上游")
        self.start_btn = QPushButton("启动代理")
        self.stop_btn = QPushButton("停止代理")
        self.stop_btn.setEnabled(False)
        self.open_logs_btn = QPushButton("打开日志目录")

        self.load_btn.clicked.connect(self.load_config_to_ui)
        self.save_btn.clicked.connect(self.save_config_from_ui)
        self.verify_btn.clicked.connect(self.verify_remote)
        self.start_btn.clicked.connect(self.start_proxy)
        self.stop_btn.clicked.connect(self.stop_proxy)
        self.open_logs_btn.clicked.connect(self.open_logs_dir)

        for btn in [self.load_btn, self.save_btn, self.verify_btn, self.start_btn, self.stop_btn, self.open_logs_btn]:
            layout.addWidget(btn)
        return group

    def _build_status_group(self):
        group = QGroupBox("状态区")
        form = QFormLayout(group)
        self.status_value = QLabel("未启动")
        self.listen_value = QLabel("-")
        self.upstream_value = QLabel("-")
        self.pool_value = QLabel("-")
        self.log_value = QLabel(str(Path("logs/proxy.log").resolve()))
        form.addRow("运行状态：", self.status_value)
        form.addRow("本地监听：", self.listen_value)
        form.addRow("上游模式：", self.upstream_value)
        form.addRow("连接池：", self.pool_value)
        form.addRow("日志文件：", self.log_value)
        return group

    def _build_log_group(self):
        group = QGroupBox("运行日志")
        layout = QVBoxLayout(group)
        self.log_edit = QPlainTextEdit()
        self.log_edit.setReadOnly(True)
        layout.addWidget(self.log_edit)
        return group

    def append_log(self, text: str):
        self.log_edit.appendPlainText(text)

    def load_config_to_ui(self, silent=False):
        try:
            cfg = proxy.load_config(self.config_path_edit.text().strip())
            settings = proxy.settings_from_config(cfg)
            self.local_host_edit.setText(settings.local_host)
            self.local_port_spin.setValue(settings.local_port)
            self.max_conn_spin.setValue(settings.max_conn)
            self.remote_enabled_check.setChecked(settings.remote_enabled)
            self.remote_host_edit.setText(settings.remote_host)
            self.remote_port_spin.setValue(settings.remote_port)
            self.remote_user_edit.setText(settings.remote_user)
            self.remote_pass_edit.setText(settings.remote_pass)
            self.socks5_auth_check.setChecked(settings.socks5_auth)
            self.socks5_user_edit.setText(settings.socks5_user)
            self.socks5_pass_edit.setText(settings.socks5_pass)
            self.timeout_spin.setValue(settings.relay_timeout)
            self.buffer_spin.setValue(settings.buffer_size)
            self.listen_value.setText(f"{settings.local_host}:{settings.local_port}")
            self.upstream_value.setText("上游代理" if settings.remote_enabled else "直连")
            if not silent:
                QMessageBox.information(self, "加载成功", "配置已加载。")
        except Exception as exc:
            if not silent:
                QMessageBox.critical(self, "加载失败", str(exc))

    def collect_settings(self) -> proxy.ProxySettings:
        return proxy.ProxySettings(
            remote_host=self.remote_host_edit.text().strip(),
            remote_port=self.remote_port_spin.value(),
            remote_user=self.remote_user_edit.text().strip(),
            remote_pass=self.remote_pass_edit.text().strip(),
            local_host=self.local_host_edit.text().strip(),
            local_port=self.local_port_spin.value(),
            max_conn=self.max_conn_spin.value(),
            remote_enabled=self.remote_enabled_check.isChecked(),
            socks5_auth=self.socks5_auth_check.isChecked(),
            socks5_user=self.socks5_user_edit.text().strip(),
            socks5_pass=self.socks5_pass_edit.text().strip(),
            relay_timeout=self.timeout_spin.value(),
            buffer_size=self.buffer_spin.value(),
        )

    def save_config_from_ui(self):
        try:
            settings = self.collect_settings()
            cfg = configparser.ConfigParser()
            cfg["remote"] = {
                "enabled": str(settings.remote_enabled).lower(),
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
            with open(self.config_path_edit.text().strip(), "w", encoding="utf-8") as f:
                cfg.write(f)
            QMessageBox.information(self, "保存成功", "配置已保存。")
        except Exception as exc:
            QMessageBox.critical(self, "保存失败", str(exc))

    def verify_remote(self):
        try:
            proxy.verify_remote(self.collect_settings())
            QMessageBox.information(self, "验证成功", "上游验证通过。")
        except Exception as exc:
            QMessageBox.critical(self, "验证失败", str(exc))

    def start_proxy(self):
        try:
            if self.proxy_thread is not None and self.proxy_thread.is_alive():
                self.debug_log("start_proxy ignored because proxy thread is already running")
                return
            settings = self.collect_settings()
            self.debug_log("start_proxy clicked")
            self.proxy_thread = threading.Thread(target=self._run_proxy_backend, args=(settings,), daemon=True)
            self.proxy_thread.start()
            self.listen_value.setText(f"{settings.local_host}:{settings.local_port}")
            self.upstream_value.setText("上游代理" if settings.remote_enabled else "直连")
            self.debug_log("proxy threading.Thread started")
        except Exception as exc:
            self.debug_log(f"start_proxy exception: {exc}")
            QMessageBox.critical(self, "启动失败", str(exc))

    def _run_proxy_backend(self, settings: proxy.ProxySettings):
        try:
            self.debug_log("backend thread entered")
            self.signals.started.emit()
            proxy.start(settings=settings, install_signal_handlers=False)
            self.debug_log("backend thread returned normally")
            self.signals.stopped.emit()
        except Exception as exc:
            tb = traceback.format_exc()
            self.debug_log(f"backend thread failed: {exc}\n{tb}")
            self.signals.failed.emit(f"{exc}\n\n{tb}")

    def _on_backend_started(self):
        self.proxy_running = True
        self.status_value.setText("运行中")
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

    def stop_proxy(self):
        self.debug_log("stop_proxy clicked")
        self.status_value.setText("正在停止")
        self.stop_btn.setEnabled(False)
        proxy.stop()
        self.stop_poll_timer.start()

    def _check_worker_stopped(self):
        if self.proxy_thread is None:
            self.debug_log("poll detected proxy_thread is None")
            self.stop_poll_timer.stop()
            return
        if not self.proxy_thread.is_alive():
            self.debug_log("poll detected proxy_thread finished")
            self.stop_poll_timer.stop()
            self.on_proxy_stopped()
            return
        self.status_value.setText("正在停止（等待线程退出）")
        self.debug_log("poll waiting for proxy_thread to finish")

    def on_proxy_failed(self, message: str):
        self.debug_log(f"on_proxy_failed: {message}")
        self.proxy_running = False
        self.status_value.setText("启动失败")
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.proxy_thread = None
        QMessageBox.critical(self, "代理异常", message)

    def on_proxy_stopped(self):
        self.debug_log("on_proxy_stopped signal received")
        self.proxy_running = False
        self.status_value.setText("已停止")
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.stop_poll_timer.stop()
        self.proxy_thread = None

    def closeEvent(self, event):
        if self.proxy_thread is not None and self.proxy_thread.is_alive():
            self.debug_log("closeEvent intercepted while proxy_thread running")
            proxy.stop()
            self.stop_poll_timer.start()
            event.ignore()
            return
        event.accept()

    def open_logs_dir(self):
        logs_dir = Path(__file__).with_name("logs")
        os.startfile(logs_dir)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = NebulaGateWindow()
    window.show()
    sys.exit(app.exec())
