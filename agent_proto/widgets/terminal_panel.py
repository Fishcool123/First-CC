# -*- coding: utf-8 -*-
"""TerminalPanel：底部终端日志面板（QDockWidget，可折叠+可独立弹出+ANSI 清洗）"""
import re
from PyQt5.QtWidgets import QDockWidget, QPlainTextEdit
from PyQt5.QtCore import Qt


# ANSI 转义码正则（用于清洗终端日志中的颜色码）
_ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')


def _clean_ansi(text):
    return _ANSI_RE.sub('', text)


class TerminalPanel(QDockWidget):
    """底部终端日志 — Cherry 风格黑底绿字等宽"""

    def __init__(self, parent=None):
        super().__init__("终端日志", parent)
        self.setAllowedAreas(Qt.BottomDockWidgetArea)
        self.setFeatures(
            QDockWidget.DockWidgetClosable
            | QDockWidget.DockWidgetMovable
            | QDockWidget.DockWidgetFloatable
        )

        self._log_widget = QPlainTextEdit()
        self._log_widget.setObjectName("terminalLog")  # QSS 选择器
        self._log_widget.setReadOnly(True)
        self._log_widget.setMaximumBlockCount(2000)
        self.setWidget(self._log_widget)

        from agent_bridge import bridge
        bridge.log_line.connect(self._on_log_line)

    def _on_log_line(self, level, message):
        """追加日志行，清洗 ANSI 码，按级别着色"""
        message = _clean_ansi(message)
        color_map = {
            "ERROR": "#ff4444",
            "WARN": "#ffaa44",
            "STDOUT": "#00ff00",
            "INFO": "#00ff00",
        }
        c = color_map.get(level, "#00ff00")
        self._log_widget.appendHtml(
            f'<span style="color:#888">[{level}]</span> '
            f'<span style="color:{c}">{message}</span>'
        )
        sb = self._log_widget.verticalScrollBar()
        sb.setValue(sb.maximum())
