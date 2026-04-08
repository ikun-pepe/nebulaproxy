from __future__ import annotations

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
from proxy_core.config import DEFAULT_CONFIG_PATH
from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QComboBox,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


CONFIG_PATH = Path(DEFAULT_CONFIG_PATH)


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
        self.stats_timer = QTimer(self)
        self.stats_timer.setInterval(1000)
        self.stats_timer.timeout.connect(self._refresh_runtime_stats)
        self.connections_timer = QTimer(self)
        self.connections_timer.setInterval(1000)
        self.connections_timer.timeout.connect(self._refresh_connections)
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

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_config_tab(), "配置")
        self.tabs.addTab(self._build_log_tab(), "日志")
        self.tabs.addTab(self._build_connections_tab(), "连接状态")
        root.addWidget(self.tabs, 1)

    def _build_config_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(12)
        layout.addWidget(self._build_config_group())
        layout.addWidget(self._build_control_group())
        layout.addWidget(self._build_status_group())
        layout.addStretch(1)
        return tab

    def _build_log_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(12)
        layout.addWidget(self._build_log_group(), 1)
        return tab

    def _build_connections_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(12)

        filter_group = QGroupBox("筛选")
        filter_layout = QHBoxLayout(filter_group)
        self.conn_filter_edit = QLineEdit()
        self.conn_filter_edit.setPlaceholderText("输入客户端/IP/目标地址/协议/状态关键字筛选")
        self.conn_filter_edit.textChanged.connect(self._refresh_connections)
        filter_layout.addWidget(QLabel("关键字："))
        filter_layout.addWidget(self.conn_filter_edit)

        table_group = QGroupBox("当前连接")
        table_layout = QVBoxLayout(table_group)
        self.conn_table = QTableWidget(0, 9)
        self.conn_table.setHorizontalHeaderLabels([
            "客户端",
            "协议",
            "目标地址",
            "端口",
            "状态",
            "开始时间",
            "上行",
            "下行",
            "持续(ms)",
        ])
        self.conn_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.conn_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.conn_table.setAlternatingRowColors(True)
        self.conn_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.conn_table.customContextMenuRequested.connect(self._show_connection_context_menu)
        self.conn_table.verticalHeader().setVisible(False)
        self.conn_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table_layout.addWidget(self.conn_table)

        layout.addWidget(filter_group)
        layout.addWidget(table_group, 1)
        return tab

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
        self.remote_auth_mode_combo = QComboBox()
        self.remote_auth_mode_combo.addItems(["无认证", "Basic", "用户名/密码"])
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
        layout.addWidget(QLabel("    认证方式："), 5, 0)
        layout.addWidget(self.remote_auth_mode_combo, 5, 1)
        layout.addWidget(QLabel("    上游主机："), 6, 0)
        layout.addWidget(self.remote_host_edit, 6, 1)
        layout.addWidget(QLabel("    上游端口："), 7, 0)
        layout.addWidget(self.remote_port_spin, 7, 1)
        layout.addWidget(QLabel("    上游用户名："), 8, 0)
        layout.addWidget(self.remote_user_edit, 8, 1)
        layout.addWidget(QLabel("    上游密码："), 9, 0)
        layout.addWidget(self.remote_pass_edit, 9, 1)
        layout.addWidget(self.socks5_auth_check, 10, 0, 1, 2)
        layout.addWidget(QLabel("    SOCKS5 用户名："), 11, 0)
        layout.addWidget(self.socks5_user_edit, 11, 1)
        layout.addWidget(QLabel("    SOCKS5 密码："), 12, 0)
        layout.addWidget(self.socks5_pass_edit, 12, 1)
        layout.addWidget(QLabel("中继超时："), 13, 0)
        layout.addWidget(self.timeout_spin, 13, 1)
        layout.addWidget(QLabel("缓冲区大小："), 14, 0)
        layout.addWidget(self.buffer_spin, 14, 1)
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
        self.active_conn_value = QLabel("0")
        self.up_speed_value = QLabel("0 B/s")
        self.down_speed_value = QLabel("0 B/s")
        self.total_up_value = QLabel("0 B")
        self.total_down_value = QLabel("0 B")
        form.addRow("运行状态：", self.status_value)
        form.addRow("本地监听：", self.listen_value)
        form.addRow("上游模式：", self.upstream_value)
        form.addRow("连接池：", self.pool_value)
        form.addRow("活跃连接：", self.active_conn_value)
        form.addRow("实时上行：", self.up_speed_value)
        form.addRow("实时下行：", self.down_speed_value)
        form.addRow("累计上行：", self.total_up_value)
        form.addRow("累计下行：", self.total_down_value)
        return group

    def _build_log_group(self):
        group = QGroupBox("运行日志")
        layout = QVBoxLayout(group)
        self.log_path_value = QLabel(str(Path("logs/proxy.log").resolve()))
        layout.addWidget(QLabel("日志文件："))
        layout.addWidget(self.log_path_value)
        self.log_edit = QPlainTextEdit()
        self.log_edit.setReadOnly(True)
        layout.addWidget(self.log_edit)
        return group

    def append_log(self, text: str):
        self.log_edit.appendPlainText(text)

    @staticmethod
    def _format_bytes(value: float) -> str:
        units = ["B", "KB", "MB", "GB", "TB"]
        size = float(value)
        for unit in units:
            if size < 1024 or unit == units[-1]:
                if unit == "B":
                    return f"{int(size)} {unit}"
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    @staticmethod
    def _status_color(status: str):
        if status == "ACTIVE":
            return QColor("#1b8a3b")
        if status == "CONNECTING":
            return QColor("#c27c0e")
        if status in {"ERROR", "CONN_FAIL", "TIMEOUT", "AUTH_FAIL", "PROTO_ERR", "UNSUPPORTED", "UNKNOWN"}:
            return QColor("#c0392b")
        return None

    def _show_connection_context_menu(self, pos):
        item = self.conn_table.itemAt(pos)
        if item is None:
            return
        self.conn_table.selectRow(item.row())
        menu = QMenu(self)
        copy_action = menu.addAction("复制连接信息")
        action = menu.exec(self.conn_table.viewport().mapToGlobal(pos))
        if action == copy_action:
            self._copy_selected_connection_info()

    def _copy_selected_connection_info(self):
        row = self.conn_table.currentRow()
        if row < 0:
            return
        headers = [self.conn_table.horizontalHeaderItem(i).text() for i in range(self.conn_table.columnCount())]
        values = []
        for col in range(self.conn_table.columnCount()):
            item = self.conn_table.item(row, col)
            values.append(item.text() if item is not None else "")
        text = "\n".join(f"{header}: {value}" for header, value in zip(headers, values))
        QApplication.clipboard().setText(text)

    def _refresh_runtime_stats(self):
        stats = proxy.get_runtime_stats()
        self.active_conn_value.setText(str(stats["active_connections"]))
        self.up_speed_value.setText(f"{self._format_bytes(stats['up_bps'])}/s")
        self.down_speed_value.setText(f"{self._format_bytes(stats['down_bps'])}/s")
        self.total_up_value.setText(self._format_bytes(stats["total_up_bytes"]))
        self.total_down_value.setText(self._format_bytes(stats["total_down_bytes"]))
        if proxy.upstream_pool is None:
            self.pool_value.setText("直连模式")
        else:
            self.pool_value.setText(f"空闲 {proxy.upstream_pool.idle_count} / 总计 {proxy.upstream_pool.total_count}")

    def _refresh_connections(self):
        keyword = self.conn_filter_edit.text().strip().lower()
        rows = []
        for item in proxy.get_active_connections():
            searchable = " ".join([
                str(item["client_addr"]),
                str(item["protocol"]),
                str(item["target_host"]),
                str(item["target_port"]),
                str(item["status"]),
            ]).lower()
            if keyword and keyword not in searchable:
                continue
            rows.append(item)

        self.conn_table.setRowCount(len(rows))
        for row_index, item in enumerate(rows):
            values = [
                item["client_addr"],
                item["protocol"],
                item["target_host"],
                str(item["target_port"]),
                item["status"],
                item["started_at_text"],
                self._format_bytes(item["bytes_up"]),
                self._format_bytes(item["bytes_down"]),
                str(item["duration_ms"]),
            ]
            for col_index, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if col_index == 4:
                    color = self._status_color(item["status"])
                    if color is not None:
                        cell.setForeground(color)
                self.conn_table.setItem(row_index, col_index, cell)

    def load_config_to_ui(self, silent=False):
        try:
            cfg = proxy.load_config(self.config_path_edit.text().strip())
            settings = proxy.settings_from_config(cfg)
            self.local_host_edit.setText(settings.local_host)
            self.local_port_spin.setValue(settings.local_port)
            self.max_conn_spin.setValue(settings.max_conn)
            self.remote_enabled_check.setChecked(settings.remote_enabled)
            self.remote_auth_mode_combo.setCurrentText({
                "none": "无认证",
                "basic": "Basic",
                "username_password": "用户名/密码",
            }.get(settings.remote_auth_mode, "Basic"))
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
            remote_auth_mode={
                "无认证": "none",
                "Basic": "basic",
                "用户名/密码": "username_password",
            }[self.remote_auth_mode_combo.currentText()],
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
            proxy.save_config(settings, self.config_path_edit.text().strip())
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
        self._refresh_runtime_stats()
        self._refresh_connections()
        self.stats_timer.start()
        self.connections_timer.start()

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
        self.stats_timer.stop()
        self.connections_timer.stop()
        self.status_value.setText("启动失败")
        self.active_conn_value.setText("0")
        self.up_speed_value.setText("0 B/s")
        self.down_speed_value.setText("0 B/s")
        self.conn_table.setRowCount(0)
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.proxy_thread = None
        QMessageBox.critical(self, "代理异常", message)

    def on_proxy_stopped(self):
        self.debug_log("on_proxy_stopped signal received")
        self.proxy_running = False
        self.stats_timer.stop()
        self.connections_timer.stop()
        self.status_value.setText("已停止")
        self.active_conn_value.setText("0")
        self.up_speed_value.setText("0 B/s")
        self.down_speed_value.setText("0 B/s")
        self.conn_table.setRowCount(0)
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
