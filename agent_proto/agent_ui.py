# -*- coding: utf-8 -*-
"""
agent_ui.py — 桌面悬浮窗 + 系统托盘 + 聊天窗（Phase 4A/B/C）
PyQt5 实现的 AI 陪伴智能体 UI，三种形态自适应切换。

入口：py agent_proto/agent_ui.py
- 主线程：PyQt5 窗口 + 托盘图标
- 后台线程：Agent 循环（Observer → Thinker → Actor）
"""
import sys
import math
import threading
import time
import webbrowser
from datetime import datetime

from PyQt5.QtWidgets import (
    QApplication, QWidget, QSystemTrayIcon, QMenu, QAction,
    QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton, QLabel,
    QScrollArea, QSizePolicy, QTabWidget,
)
from PyQt5.QtCore import Qt, QTimer, QPoint
from PyQt5.QtGui import (
    QPainter, QColor, QBrush, QPen, QFont, QPixmap, QIcon,
)

import os
import atexit
import urllib.request

# ── 单例锁：防止重复启动 ──
_LOCK_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".agent_ui.lock")


def _acquire_single_instance():
    """获取单例锁。已有实例运行时返回 False。注册退出时自动释放。"""
    try:
        if os.path.exists(_LOCK_FILE):
            with open(_LOCK_FILE, "r") as f:
                old_pid = f.read().strip()
            # 检查旧进程是否还活着
            try:
                import ctypes
                PROCESS_TERMINATE = 1
                h = ctypes.windll.kernel32.OpenProcess(PROCESS_TERMINATE, False, int(old_pid))
                if h:
                    ctypes.windll.kernel32.CloseHandle(h)
                    print(f"[UI] Agent 已在运行中（PID {old_pid}），退出。")
                    return False
            except Exception:
                pass  # 旧 PID 无效，覆盖
        with open(_LOCK_FILE, "w") as f:
            f.write(str(os.getpid()))
        atexit.register(_release_single_instance)
        return True
    except Exception:
        return True  # 锁文件不可写时不阻止启动


def _release_single_instance():
    try:
        if os.path.exists(_LOCK_FILE):
            os.remove(_LOCK_FILE)
    except Exception:
        pass


def _ping_url(url):
    """快速检测 URL 是否可达"""
    try:
        req = urllib.request.Request(url, method='HEAD')
        with urllib.request.urlopen(req, timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════
# 共享状态
# ═══════════════════════════════════════════════════════════

_state = {
    "color": "#4A9EFF",
    "breath": "slow",
    "text": "",
    "tooltip": "",
    "mode": "accompany",     # sleep / accompany / dialog
    "auto_mode": True,       # Fix 3: 是否允许自动模式切换
    "_mode_locked": False,   # Fix 3: 用户是否锁定模式
    "pending_auto_mode": None,  # Fix 3: Agent 线程请求的模式切换
}
_state_lock = threading.Lock()
_messages = []  # 消息历史，供聊天窗读取
_messages_lock = threading.Lock()


def update_status(color=None, breath=None, text=None):
    """Agent 线程调用，更新悬浮窗状态"""
    with _state_lock:
        if color:
            _state["color"] = {
                "blue": "#4A9EFF", "orange": "#FF9E4A",
                "red": "#FF4A4A", "green": "#4AFF4A",
            }.get(color, color)
        if breath:
            _state["breath"] = breath
        if text:
            _state["text"] = text[:20]
            _state["tooltip"] = text


def request_auto_mode(mode):
    """Agent 线程调用，请求自动模式切换（仅当未被锁定时生效）"""
    with _state_lock:
        _state["pending_auto_mode"] = mode


def add_message(persona, text):
    """Agent 线程调用，添加消息到聊天历史"""
    with _messages_lock:
        _messages.append({
            "time": datetime.now().strftime("%H:%M"),
            "persona": persona,
            "text": text,
        })
        if len(_messages) > 200:
            _messages.pop(0)


# ═══════════════════════════════════════════════════════════
# 托盘图标
# ═══════════════════════════════════════════════════════════

def _make_tray_icon(color_hex="#4A9EFF", size=16):
    """绘制精致的托盘图标：环 + 实心内圈"""
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    cx, cy = size / 2, size / 2
    color = QColor(color_hex)
    # 外环
    p.setPen(QPen(color, 1.2))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QPoint(int(cx), int(cy)), int(cx - 1.5), int(cy - 1.5))
    # 内实心点
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(color))
    p.drawEllipse(QPoint(int(cx), int(cy)), int(cx - 4), int(cy - 4))
    p.end()
    return QIcon(pix)


# ═══════════════════════════════════════════════════════════
# 聊天窗（Phase 4B）
# ═══════════════════════════════════════════════════════════

class ChatWindow(QWidget):
    """对话态窗口 — 聊天气泡 + 打字指示器 + Enter 发送"""

    BUBBLE_COLORS = {
        "user":      ("#2b5278", "#e8ecf1", "right"),
        "companion": ("transparent", "#c8ccd4", "left"),
        "recorder":  ("transparent", "#4A9EFF", "left"),
        "scheduler": ("transparent", "#FF9E4A", "left"),
    }

    def __init__(self, parent_dot, thinker=None):
        super().__init__()
        self._dot = parent_dot
        self._thinker = thinker
        self._history = []
        self._typing_label = None  # "正在输入..." 指示器

        self.setWindowTitle("小鱼")
        self.setMinimumSize(360, 480)
        self.resize(400, 560)

        self.setWindowFlags(
            Qt.Window | Qt.WindowStaysOnTopHint | Qt.WindowCloseButtonHint
        )
        self.setAttribute(Qt.WA_DeleteOnClose, False)

        dot_center = parent_dot.frameGeometry().center()
        self.move(dot_center.x() - 180, dot_center.y() - 480)

        self._setup_ui()
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_messages)
        self._refresh_timer.start(3000)

    def _setup_ui(self):
        self.setStyleSheet("""
            QWidget {
                background-color: #1e1e1e;
                color: #cccccc;
                font-family: "Microsoft YaHei";
                font-size: 13px;
            }
            QTextEdit {
                background-color: #2a2a2a;
                color: #e0e0e0;
                border: 1px solid #3c3c3c;
                border-radius: 8px;
                padding: 10px 14px;
                font-size: 13px;
                selection-background-color: #264f78;
            }
            QTextEdit:focus {
                border-color: #555;
            }
            QPushButton {
                background-color: #0e639c;
                color: #fff;
                border: none;
                border-radius: 6px;
                font-size: 12px;
                padding: 6px 14px;
            }
            QPushButton:hover {
                background-color: #1177bb;
            }
            QPushButton:pressed {
                background-color: #094771;
            }
            QScrollArea {
                border: none;
                background: transparent;
            }
            QScrollBar:vertical {
                background: transparent;
                width: 8px;
                margin: 0;
            }
            QScrollBar::handle:vertical {
                background: #424242;
                border-radius: 4px;
                min-height: 30px;
            }
            QScrollBar::handle:vertical:hover {
                background: #555;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── 顶部栏 ──
        top_bar = QWidget()
        top_bar.setFixedHeight(44)
        top_bar.setStyleSheet("background: #252525; border-bottom: 1px solid #333;")
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(14, 0, 14, 0)

        top_title = QLabel("小鱼")
        top_title.setStyleSheet("font-size: 13px; font-weight: bold; color: #ddd; border: none;")
        top_layout.addWidget(top_title)

        top_layout.addStretch()

        self._status_dot = QLabel("●")
        self._status_dot.setStyleSheet("color: #4A9EFF; font-size: 8px; border: none;")
        top_layout.addWidget(self._status_dot)
        status_text = QLabel("在线")
        status_text.setStyleSheet("color: #777; font-size: 11px; border: none; margin-right: 4px;")
        top_layout.addWidget(status_text)

        layout.addWidget(top_bar)

        # ── 消息区 ──
        self._msg_area = QScrollArea()
        self._msg_area.setWidgetResizable(True)
        self._msg_container = QWidget()
        self._msg_container.setStyleSheet("background: transparent;")
        self._msg_layout = QVBoxLayout(self._msg_container)
        self._msg_layout.setAlignment(Qt.AlignTop)
        self._msg_layout.setSpacing(10)
        self._msg_layout.setContentsMargins(12, 12, 12, 12)
        self._msg_area.setWidget(self._msg_container)
        layout.addWidget(self._msg_area, stretch=1)

        # ── 输入区 ──
        input_box = QWidget()
        input_box.setStyleSheet("background: #252525; border-top: 1px solid #333;")
        input_layout = QHBoxLayout(input_box)
        input_layout.setContentsMargins(12, 10, 12, 10)
        input_layout.setSpacing(8)

        self._input = QTextEdit()
        self._input.setFixedHeight(40)
        self._input.setPlaceholderText("输入消息...")
        self._input.installEventFilter(self)
        input_layout.addWidget(self._input)

        send_btn = QPushButton("发送")
        send_btn.setFixedSize(52, 40)
        send_btn.clicked.connect(self._on_send)
        input_layout.addWidget(send_btn)

        layout.addWidget(input_box)
        self._shown_ids = set()

    def eventFilter(self, obj, event):
        """Enter 发送，Shift+Enter 换行"""
        from PyQt5.QtCore import QEvent
        if obj == self._input and event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Return and not (event.modifiers() & Qt.ShiftModifier):
                self._on_send()
                return True
        return super().eventFilter(obj, event)

    def _refresh_messages(self):
        with _messages_lock:
            msgs = list(_messages)
        for i, m in enumerate(msgs):
            msg_id = f"{m['time']}-{i}"
            if msg_id not in self._shown_ids:
                self._shown_ids.add(msg_id)
                self._add_bubble(m)
        if msgs:
            QTimer.singleShot(50, self._scroll_bottom)

    def _add_bubble(self, msg):
        persona = msg.get("persona", "companion")
        bg, fg, align = self.BUBBLE_COLORS.get(persona,
                          ("transparent", "#ccc", "left"))
        is_user = (align == "right")

        row = QWidget()
        row.setStyleSheet("background: transparent;")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)

        # 头像小圆点（非用户消息）
        if not is_user:
            avatar = QLabel("●")
            avatar.setFixedSize(18, 18)
            dot_color = "#6a9955" if persona == "companion" else "#4A9EFF"
            avatar.setStyleSheet(f"color: {dot_color}; font-size: 14px; "
                                 "background: transparent; border: none;")
            avatar.setAlignment(Qt.AlignTop)
            row_layout.addWidget(avatar)

        if is_user:
            row_layout.addStretch()

        # 气泡
        bubble = QLabel(msg["text"])
        bubble.setWordWrap(True)
        bubble.setMaximumWidth(280)
        if is_user:
            bubble.setStyleSheet(f"""
                background-color: {bg};
                color: {fg};
                border-radius: 8px;
                padding: 8px 14px;
                font-size: 13px;
            """)
        else:
            bubble.setStyleSheet(f"""
                background-color: transparent;
                color: {fg};
                padding: 6px 0px 6px 0px;
                font-size: 13px;
            """)
        bubble.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        row_layout.addWidget(bubble)

        if not is_user:
            row_layout.addStretch()

        # 时间戳
        ts = QLabel(msg.get("time", ""))
        ts.setStyleSheet("color: #555; font-size: 10px; background: transparent; border: none;")
        ts.setAlignment(Qt.AlignBottom)
        if is_user:
            row_layout.insertWidget(row_layout.count() - 1, ts)
        else:
            row_layout.addWidget(ts)

        self._msg_layout.addWidget(row)

    def _add_typing_indicator(self):
        """显示「小鱼正在打字...」"""
        if self._typing_label:
            return
        row = QWidget()
        row.setStyleSheet("background: transparent;")
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(QLabel("●"))
        label = QLabel("  小鱼正在打字...")
        label.setStyleSheet("color: #666; font-size: 12px; background: transparent; border: none;")
        rl.addWidget(label)
        rl.addStretch()
        self._typing_label = row
        self._msg_layout.addWidget(row)
        self._scroll_bottom()

    def _remove_typing_indicator(self):
        if self._typing_label:
            self._typing_label.deleteLater()
            self._typing_label = None

    def _scroll_bottom(self):
        sb = self._msg_area.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_send(self):
        text = self._input.toPlainText().strip()
        if not text:
            return

        # 用户气泡
        self._add_bubble({"time": datetime.now().strftime("%H:%M"),
                          "persona": "user", "text": text})
        self._input.clear()
        self._input.setEnabled(False)
        self._add_typing_indicator()
        self._scroll_bottom()

        def do_chat():
            try:
                reply = self._thinker.chat(text, "companion", self._history) if self._thinker else "(未连接)"
            except Exception as e:
                reply = f"(回复失败: {e})"
            self._history.append({"role": "user", "content": text})
            self._history.append({"role": "assistant", "content": reply})
            if len(self._history) > 40:
                self._history = self._history[-40:]
            self._remove_typing_indicator()
            self._add_bubble({"time": datetime.now().strftime("%H:%M"),
                             "persona": "companion", "text": reply})
            self._input.setEnabled(True)
            self._input.setFocus()
            self._scroll_bottom()

        QTimer.singleShot(100, do_chat)

    def closeEvent(self, event):
        self._dot.set_mode("accompany")
        event.ignore()
        self.hide()

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_messages()


# ═══════════════════════════════════════════════════════════
# 统一主窗口 — 三标签页（小鱼 + 任务 + 切片）
# ═══════════════════════════════════════════════════════════

class MainWindow(QWidget):
    """三标签主窗口：对话 / 任务管理 / 时间切片"""

    def __init__(self, parent_dot, thinker=None):
        super().__init__()
        self._dot = parent_dot
        self.setWindowTitle("认知增强系统")
        self.setMinimumSize(420, 520)
        self.resize(440, 580)

        self.setWindowFlags(
            Qt.Window | Qt.WindowCloseButtonHint
        )
        self.setAttribute(Qt.WA_DeleteOnClose, False)

        dot_center = parent_dot.frameGeometry().center()
        self.move(max(0, dot_center.x() - 480), max(0, dot_center.y() - 600))

        self.setStyleSheet("""
            QWidget {
                background-color: #1e1e1e;
                color: #cccccc;
                font-family: "Microsoft YaHei";
                font-size: 13px;
            }
            QTabWidget::pane {
                border: none;
                background: #1e1e1e;
            }
            QTabBar::tab {
                background: #252525;
                color: #999;
                border: none;
                padding: 10px 24px;
                font-size: 13px;
                min-width: 80px;
            }
            QTabBar::tab:selected {
                background: #1e1e1e;
                color: #e0e0e0;
                border-bottom: 2px solid #4A9EFF;
            }
            QTabBar::tab:hover:!selected {
                color: #ccc;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._tabs = QTabWidget()
        layout.addWidget(self._tabs)

        # Tab 0: 小鱼对话
        self._chat = ChatWindow(parent_dot, thinker)
        self._chat.setParent(None)
        # 移除 ChatWindow 的窗口标志，改为普通 widget
        self._chat.setWindowFlags(Qt.Widget)
        self._tabs.addTab(self._chat, "💬 小鱼")

        # Tab 1: 任务管理
        self._tabs.addTab(self._make_launcher_tab(
            "📋 任务管理助手",
            "任务 CRUD · 贪心排程 · 拖拽排序 · 手动分配",
            "http://127.0.0.1:5000"
        ), "📋 任务")

        # Tab 2: 时间切片
        self._tabs.addTab(self._make_launcher_tab(
            "⏱ 时间切片系统",
            "手动切片 · 日历热力图 · 设备日志 · 情绪标签",
            "http://127.0.0.1:5001"
        ), "⏱ 切片")

    def _make_launcher_tab(self, title, desc, url):
        """启动面板：服务状态指示灯 + 标题描述 + 浏览器按钮"""
        w = QWidget()
        w.setStyleSheet("background: #1e1e1e;")
        layout = QVBoxLayout(w)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(14)

        # 服务状态（初始显示检测中，100ms 后异步更新）
        status_row = QHBoxLayout()
        status_row.setAlignment(Qt.AlignCenter)
        dot = QLabel("●")
        dot.setStyleSheet("color: #888; font-size: 10px; border: none;")
        status_row.addWidget(dot)
        status_lbl = QLabel("检测中...")
        status_lbl.setStyleSheet("color: #888; font-size: 12px; border: none; margin-left: 4px;")
        status_row.addWidget(status_lbl)
        layout.addLayout(status_row)

        icon = QLabel(title.split(" ")[0])
        icon.setStyleSheet("font-size: 42px; border: none; background: transparent;")
        icon.setAlignment(Qt.AlignCenter)
        layout.addWidget(icon)

        name = QLabel(title)
        name.setStyleSheet("font-size: 18px; font-weight: bold; color: #ddd; border: none;")
        name.setAlignment(Qt.AlignCenter)
        layout.addWidget(name)

        info = QLabel(desc)
        info.setStyleSheet("font-size: 12px; color: #777; border: none;")
        info.setAlignment(Qt.AlignCenter)
        layout.addWidget(info)

        btn = QPushButton("打开")
        btn.setStyleSheet("""
            QPushButton {
                background-color: #0e639c; color: #fff; border: none;
                border-radius: 6px; padding: 8px 24px; font-size: 13px;
            }
            QPushButton:hover { background-color: #1177bb; }
            QPushButton:disabled { background-color: #333; color: #666; }
        """)
        btn.setFixedWidth(120)
        btn.setEnabled(False)  # 初始禁用，检测通过后启用
        btn.clicked.connect(lambda: webbrowser.open(url))
        layout.addWidget(btn, alignment=Qt.AlignCenter)

        # 异步检测服务状态
        def check():
            online = _ping_url(url)
            c = "#4d4" if online else "#e44"
            t = "服务在线" if online else "服务离线"
            dot.setStyleSheet(f"color: {c}; font-size: 10px; border: none;")
            status_lbl.setStyleSheet(f"color: {c}; font-size: 12px; border: none; margin-left: 4px;")
            status_lbl.setText(t)
            btn.setEnabled(online)
        QTimer.singleShot(200, check)

        return w

    def closeEvent(self, event):
        """关闭窗口 = 缩回悬浮窗"""
        self._dot.set_mode("accompany")
        event.ignore()
        self.hide()

    def showEvent(self, event):
        super().showEvent(event)
        # 刷新聊天消息
        if hasattr(self, '_chat') and self._chat:
            self._chat._refresh_messages()


# ═══════════════════════════════════════════════════════════
# 悬浮圆点（Phase 4A + 模式管理）
# ═══════════════════════════════════════════════════════════

class CompanionDot(QWidget):
    DIAMETER = 72
    GLOW_EXTRA = 14
    WINDOW_SIZE = DIAMETER + GLOW_EXTRA * 2 + 4  # ≈ 104

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(self.WINDOW_SIZE, self.WINDOW_SIZE)

        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.width() - 140, screen.height() - 200)

        self._phase = 0.0
        self._float_phase = 0.0    # 浮动动画独立相位
        self._glow_phase = 0.0     # 光晕脉冲独立相位
        self._breath_speed = 0.04
        self._target_breath_speed = 0.04  # 平滑过渡
        self._color = QColor("#4A9EFF")
        self._target_color = QColor("#4A9EFF")
        self._start_time = time.time()
        self._display_text = ""
        self._dragging = False
        self._cx = self.WINDOW_SIZE / 2
        self._cy = self.WINDOW_SIZE / 2
        self._dot_r = self.DIAMETER / 2
        self._glow_alpha = 25
        self._cached_frame = None     # Pixmap 预渲染缓存
        self._drag_offset = QPoint()
        self._main_win = None  # 主窗口延迟创建
        self._thinker = None   # Thinker 实例引用

        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)  # 60 FPS

        self._mode_locked = False   # Fix 3/5: 用户锁定当前模式

        self.show()

    # ── 模式管理 ──────────────────────────────────────────

    def set_mode(self, mode, auto=False):
        """切换存在模式：sleep(休眠) / accompany(陪伴) / dialog(对话)

        auto=True 表示由 Agent 自动触发（IDE 检测），受 mode_locked 约束。
        auto=False 表示用户手动操作，会关闭自动模式并锁定。
        """
        # 自动切换时，如果用户锁定了模式，则不响应
        if auto and self._mode_locked:
            return

        # 手动操作时关闭自动模式
        if not auto:
            with _state_lock:
                _state["auto_mode"] = False
                _state["_mode_locked"] = False  # 手动操作重置锁定状态
                _state["pending_auto_mode"] = None

        with _state_lock:
            _state["mode"] = mode

        if mode == "sleep":
            self.hide()
            if self._main_win:
                self._main_win.hide()
        elif mode == "accompany":
            self.show()
            if self._main_win:
                self._main_win.hide()
        elif mode == "dialog":
            self.show()
            if not self._main_win:
                self._main_win = MainWindow(self, self._thinker)
            self._main_win.show()
            self._main_win.raise_()

        # 更新托盘文字
        if hasattr(self, '_tray'):
            labels = {"sleep": "休眠", "accompany": "陪伴", "dialog": "对话"}
            self._tray.setToolTip(f"Agent · {labels.get(mode, mode)}")

    def get_mode(self):
        with _state_lock:
            return _state["mode"]

    # ── 绘制 ──────────────────────────────────────────────

    def paintEvent(self, event):
        if self._cached_frame and not self._cached_frame.isNull():
            p = QPainter(self)
            p.drawPixmap(0, 0, self._cached_frame)
            p.end()

    def _lerp_color(self, c1, c2, t):
        r = int(c1.red() + (c2.red() - c1.red()) * t)
        g = int(c1.green() + (c2.green() - c1.green()) * t)
        b = int(c1.blue() + (c2.blue() - c1.blue()) * t)
        return QColor(r, g, b)

    def _tick(self):
        # ── 读取共享状态 ──
        with _state_lock:
            target_hex = _state["color"]
            breath_type = _state["breath"]
            text = _state["text"]
        self._target_color = QColor(target_hex)

        # ── 动画参数更新 ──
        self._color = self._lerp_color(self._color, self._target_color, 0.065)
        target_speed = {"slow": 0.017, "normal": 0.03, "fast": 0.055}.get(breath_type, 0.025)
        self._target_breath_speed += (target_speed - self._target_breath_speed) * 0.065
        self._breath_speed = self._target_breath_speed

        self._phase += self._breath_speed
        self._glow_phase += 0.027

        s = math.sin(self._phase)
        s2 = math.sin(self._phase * 2.17)
        breath = s * 3.8 + s2 * 1.0
        cx = self.WINDOW_SIZE / 2
        cy = self.WINDOW_SIZE / 2
        dot_r = self.DIAMETER / 2 + breath
        glow_pulse = math.sin(self._glow_phase) * 0.35 + 0.75
        glow_alpha = max(10, min(40, int(25 * glow_pulse)))

        # ── Pixmap 预渲染：所有绘制在此完成，paintEvent 只做一次 blit ──
        color = self._color
        glow_r = dot_r + 6
        pix = QPixmap(self.WINDOW_SIZE, self.WINDOW_SIZE)
        pix.fill(Qt.transparent)
        pp = QPainter(pix)
        pp.setRenderHint(QPainter.Antialiasing)

        # 光晕
        glow = QColor(color)
        glow.setAlpha(glow_alpha)
        pp.setBrush(QBrush(glow))
        pp.setPen(Qt.NoPen)
        pp.drawEllipse(QPoint(int(cx), int(cy)), int(glow_r), int(glow_r))
        # 中层柔光
        mid_glow = QColor(color)
        mid_glow.setAlpha(int(glow_alpha * 1.6))
        pp.setBrush(QBrush(mid_glow))
        pp.drawEllipse(QPoint(int(cx), int(cy)), int(dot_r + 3), int(dot_r + 3))
        # 主体
        pp.setBrush(QBrush(color))
        pp.drawEllipse(QPoint(int(cx), int(cy)), int(dot_r), int(dot_r))
        # 高光
        hl = QColor(255, 255, 255, 50)
        pp.setBrush(QBrush(hl))
        hl_x = cx - dot_r * 0.18
        hl_y = cy - dot_r * 0.25
        hl_r = dot_r * 0.4
        pp.drawEllipse(QPoint(int(hl_x), int(hl_y)), int(hl_r), int(hl_r))
        # 次高光
        hl2 = QColor(255, 255, 255, 70)
        pp.setBrush(QBrush(hl2))
        pp.drawEllipse(QPoint(int(hl_x - hl_r * 0.4), int(hl_y - hl_r * 0.3)),
                       int(hl_r * 0.45), int(hl_r * 0.45))

        # 文字（自动截断防溢出）
        elapsed = int((time.time() - self._start_time) / 60)
        display_text = text if text else (
            f"已陪伴 {elapsed} 分钟" if elapsed >= 1 else "刚刚苏醒..."
        )
        if display_text and self.get_mode() != "sleep":
            font = QFont("Microsoft YaHei", 8)
            pp.setFont(font)
            # 文本区域：球下方留 4px 左右边距
            text_rect = pix.rect().adjusted(6, int(dot_r + 18), -6, -2)
            fm = pp.fontMetrics()
            # 超长则省略号截断
            if fm.horizontalAdvance(display_text) > text_rect.width():
                display_text = fm.elidedText(display_text, Qt.ElideRight, text_rect.width())
            pp.setPen(QColor(255, 255, 255, 160))
            pp.drawText(text_rect, Qt.AlignHCenter | Qt.AlignTop, display_text)
        pp.end()

        self._cached_frame = pix

        # ── Fix 3: 自动模式切换 ──
        with _state_lock:
            pending = _state.get("pending_auto_mode")
        if pending and not self._mode_locked:
            self.set_mode(pending, auto=True)
            with _state_lock:
                _state["pending_auto_mode"] = None

        self.update()

    # ── 拖拽 ──────────────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._drag_offset = event.globalPos() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self._dragging:
            self.move(event.globalPos() - self._drag_offset)

    def mouseReleaseEvent(self, event):
        self._dragging = False

    # ── Fix 5: 右键菜单 ──────────────────────────────────

    def contextMenuEvent(self, event):
        menu = QMenu()

        mode_menu = menu.addMenu("切换模式")
        sleep_action = mode_menu.addAction("💤 休眠态")
        companion_action = mode_menu.addAction("🌙 陪伴态")
        chat_action = mode_menu.addAction("💬 对话态")

        menu.addSeparator()
        lock_text = "🔒 锁定当前模式" if not self._mode_locked else "🔓 解锁模式"
        lock_action = menu.addAction(lock_text)
        menu.addSeparator()
        exit_action = menu.addAction("❌ 退出")

        action = menu.exec_(event.globalPos())

        if action == sleep_action:
            self.set_mode("sleep")
        elif action == companion_action:
            self.set_mode("accompany")
        elif action == chat_action:
            self.set_mode("dialog")
        elif action == lock_action:
            self._mode_locked = not self._mode_locked
        elif action == exit_action:
            self.hide()
            if self._main_win:
                self._main_win.close()
            if hasattr(self, '_tray') and self._tray:
                self._tray.hide()
            QApplication.quit()

    # ── 交互 ──────────────────────────────────────────────

    def enterEvent(self, event):
        with _state_lock:
            tip = _state.get("tooltip", "")
            breath = _state["breath"]
        if tip:
            self.setToolTip(tip)
        else:
            breath_cn = {"slow": "静默观察中", "normal": "关注中", "fast": "有话要说"}
            self.setToolTip(f"Agent 运行中\n{breath_cn.get(breath, '')}\n双击打开对话窗")

    def mouseDoubleClickEvent(self, event):
        """双击：展开对话窗"""
        current = self.get_mode()
        if current == "dialog":
            self.set_mode("accompany")  # 缩回
        else:
            self.set_mode("dialog")     # 展开


# ═══════════════════════════════════════════════════════════
# 系统托盘（Phase 4C）
# ═══════════════════════════════════════════════════════════

class TrayManager:
    """系统托盘图标 + 右键菜单"""

    def __init__(self, dot):
        self._dot = dot
        self._tray = QSystemTrayIcon()
        self._tray.setIcon(_make_tray_icon("#4A9EFF"))
        self._tray.setToolTip("Agent · 陪伴")

        # 菜单
        menu = QMenu()

        mode_menu = QMenu("模式切换", menu)

        self._act_sleep = QAction("休眠 — 静默隐藏", mode_menu)
        self._act_sleep.triggered.connect(lambda: dot.set_mode("sleep"))
        mode_menu.addAction(self._act_sleep)

        self._act_accompany = QAction("陪伴 — 悬浮圆点", mode_menu)
        self._act_accompany.triggered.connect(lambda: dot.set_mode("accompany"))
        mode_menu.addAction(self._act_accompany)

        self._act_dialog = QAction("对话 — 聊天窗口", mode_menu)
        self._act_dialog.triggered.connect(lambda: dot.set_mode("dialog"))
        mode_menu.addAction(self._act_dialog)

        menu.addMenu(mode_menu)
        menu.addSeparator()

        act_quit = QAction("退出 Agent", menu)
        act_quit.triggered.connect(self._quit)
        menu.addAction(act_quit)

        self._tray.setContextMenu(menu)

        # 左键点击：切换 陪伴/对话
        self._tray.activated.connect(self._on_tray_click)

        self._tray.show()

        # 定时更新托盘图标颜色（每 2 秒）
        self._icon_timer = QTimer()
        self._icon_timer.timeout.connect(self._update_icon)
        self._icon_timer.start(2000)

    def _on_tray_click(self, reason):
        """左键点击托盘：陪伴↔对话切换"""
        if reason == QSystemTrayIcon.Trigger:  # 左键单击
            current = self._dot.get_mode()
            if current == "dialog":
                self._dot.set_mode("accompany")
            elif current == "accompany":
                self._dot.set_mode("dialog")
            else:
                self._dot.set_mode("accompany")

    def _update_icon(self):
        with _state_lock:
            color = _state["color"]
        self._tray.setIcon(_make_tray_icon(color))

    def _quit(self):
        self._dot.hide()
        if self._dot._main_win:
            self._dot._main_win.close()
        self._tray.hide()
        QApplication.quit()


# ═══════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════

def _start_agent(dot):
    """后台线程启动 Agent 循环，共享 Thinker 给聊天窗"""
    from agent_loop import run_agent
    from agent_thinker import Thinker

    # 在主线程外创建 Thinker（给 Agent 循环和聊天窗共享）
    try:
        thinker = Thinker()
        # 快速连通检查
        thinker.client.chat.completions.create(
            model=thinker.model,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=4, timeout=8,
        )
        dot._thinker = thinker  # 聊天窗可访问
    except Exception as e:
        print(f"[UI] Thinker 创建失败: {e}")
        thinker = None

    def status_cb(**kwargs):
        update_status(**kwargs)
        text = kwargs.get("text", "")
        persona = kwargs.get("persona", "recorder")
        if text:
            add_message(persona, text)

    run_agent(status_cb=status_cb, thinker=thinker, mode_cb=request_auto_mode)


def main():
    if not _acquire_single_instance():
        sys.exit(0)
    print("[UI] 启动悬浮窗 + 托盘...")
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("Agent Proto")

    # 悬浮窗 + 托盘
    dot = CompanionDot()
    tray_mgr = TrayManager(dot)
    dot._tray = tray_mgr._tray  # 供 set_mode 更新 tooltip

    # 后台线程启动 Agent（共享 Thinker 实例给聊天窗）
    agent_thread = threading.Thread(
        target=_start_agent, args=(dot,), daemon=True, name="AgentLoop"
    )
    agent_thread.start()
    print("[UI] Agent 后台线程已启动")

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
