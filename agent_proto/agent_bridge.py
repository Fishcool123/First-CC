# -*- coding: utf-8 -*-
"""
agent_bridge.py — Agent ↔ UI 信号总线（Qt Signal）
全局单例，Agent 线程通过 bridge.signal.emit() 发信号，UI 线程通过 connect 接收。
"""
from PyQt5.QtCore import QObject, pyqtSignal


class AgentBridge(QObject):
    """Agent 后台线程 → UI 主线程 的信号桥"""

    # Agent 状态更新：color(hex), breath(slow/normal/fast), text
    status_updated = pyqtSignal(str, str, str)

    # 新消息：persona, text
    message_added = pyqtSignal(str, str)

    # 模式切换请求：mode (sleep/accompany/dialog)
    mode_requested = pyqtSignal(str)

    # 终端日志：level(INFO/WARN/ERROR/STDOUT), message
    log_line = pyqtSignal(str, str)

    # 数据库变更通知
    slice_recorded = pyqtSignal(int)   # slice_id
    task_updated = pyqtSignal(int)     # task_id


# 全局单例
bridge = AgentBridge()
