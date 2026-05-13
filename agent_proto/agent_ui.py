# -*- coding: utf-8 -*-
"""
agent_ui.py — 认知增强系统 PyQt5 桌面应用
三 tab（时间切片 / 情感辅助 / 任务助理）+ 悬浮窗 + 托盘 + 终端日志

入口：py agent_proto/agent_ui.py
- 主线程：PyQt5 MainWindow + CompanionDot + TrayManager
- 后台线程：Agent 循环（Observer → Thinker → Actor）
"""
import sys
import math
import threading
import time
import os
import atexit
from datetime import datetime

from PyQt5.QtWidgets import (
    QApplication, QWidget, QSystemTrayIcon, QMenu, QAction,
    QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton, QLabel,
    QScrollArea, QSizePolicy, QTabWidget, QMainWindow, QDockWidget,
    QStackedWidget, QFrame,
)
from PyQt5.QtCore import Qt, QTimer, QPoint
from PyQt5.QtGui import (
    QPainter, QColor, QBrush, QPen, QFont, QPixmap, QIcon, QFontMetrics,
    QPainterPath,
)

# ── 单例锁 ──
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_LOCK_FILE = os.path.join(BASE_DIR, ".agent_ui.lock")


def _acquire_single_instance():
    """PID 文件单例锁，防止重复启动"""
    try:
        if os.path.exists(_LOCK_FILE):
            with open(_LOCK_FILE, "r") as f:
                old_pid = f.read().strip()
            try:
                import ctypes
                PROCESS_TERMINATE = 1
                h = ctypes.windll.kernel32.OpenProcess(PROCESS_TERMINATE, False, int(old_pid))
                if h:
                    ctypes.windll.kernel32.CloseHandle(h)
                    print(f"[UI] Agent 已在运行中（PID {old_pid}），退出。")
                    return False
            except Exception:
                pass
        with open(_LOCK_FILE, "w") as f:
            f.write(str(os.getpid()))
        atexit.register(_release_single_instance)
        return True
    except Exception:
        return True


def _release_single_instance():
    try:
        if os.path.exists(_LOCK_FILE):
            os.remove(_LOCK_FILE)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════
# 共享状态（Agent 线程写，UI 线程读）
# ═══════════════════════════════════════════════════════════

_state = {
    "color": "#4A9EFF",
    "breath": "slow",
    "text": "",
    "tooltip": "",
    "mode": "accompany",
    "auto_mode": True,
    "_mode_locked": False,
    "pending_auto_mode": None,
}
_state_lock = threading.Lock()
_messages = []
_messages_lock = threading.Lock()


def update_status(color=None, breath=None, text=None):
    """更新悬浮窗状态（由 bridge 信号触发）"""
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
    """请求自动模式切换（由 bridge 信号触发）"""
    with _state_lock:
        _state["pending_auto_mode"] = mode


def add_message(persona, text):
    """添加消息到聊天历史（由 bridge 信号触发）"""
    with _messages_lock:
        _messages.append({
            "time": datetime.now().strftime("%H:%M"),
            "persona": persona,
            "text": text,
        })
        if len(_messages) > 200:
            _messages.pop(0)


# ═══════════════════════════════════════════════════════════
# 托盘图标绘制
# ═══════════════════════════════════════════════════════════

def _make_tray_icon(color_hex="#4A9EFF", size=16):
    """Lucide 风格托盘图标 — 六边形（神经节点）+ 中心高光"""
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    cx, cy = size / 2, size / 2
    color = QColor(color_hex)

    pen = QPen(color, 1.1)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)

    # 六边形外框（Lucide Hexagon 风格）
    r = 5.8
    path = QPainterPath()
    for i in range(6):
        angle = math.pi / 6 + i * math.pi / 3
        x = cx + r * math.cos(angle)
        y = cy + r * math.sin(angle)
        if i == 0:
            path.moveTo(x, y)
        else:
            path.lineTo(x, y)
    path.closeSubpath()
    p.drawPath(path)

    # 中心点
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(color))
    p.drawEllipse(QPoint(int(cx), int(cy)), 1.5, 1.5)

    p.end()
    return QIcon(pix)


# ═══════════════════════════════════════════════════════════
# 聊天窗
# ═══════════════════════════════════════════════════════════

class ChatWindow(QWidget):
    """对话态窗口 — 聊天气泡 + 打字指示器 + Enter 发送
    支持嵌入模式（Qt.Widget，嵌入 EmotionalTab）和弹出模式（Qt.Window）。
    """

    # Persona 三色统一为蓝色系微妙差异（浅色适配）
    BUBBLE_COLORS = {
        "user":      ("#5A9EBF", "#ffffff", "right"),
        "companion": ("transparent", "#333333", "left"),
        "recorder":  ("transparent", "#5A9EBF", "left"),
        "scheduler": ("transparent", "#4a8eaf", "left"),
    }

    def __init__(self, thinker=None):
        super().__init__()
        self._thinker = thinker
        self._history = []
        self._typing_label = None
        self._embed_mode = False
        self._embed_callback = None
        self._shown_ids = set()

        self.setMinimumSize(360, 480)
        self.resize(400, 560)

        self.setWindowFlags(
            Qt.Window | Qt.WindowStaysOnTopHint | Qt.WindowCloseButtonHint
        )
        self.setAttribute(Qt.WA_DeleteOnClose, False)

        self._setup_ui()
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_messages)
        self._refresh_timer.start(3000)

        # 5 分钟无交互自动收起
        self._idle_timeout_ms = 5 * 60 * 1000
        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.timeout.connect(self._on_idle_timeout)

    def set_embed_mode(self, enabled, callback=None):
        """切换嵌入/弹出模式"""
        self._embed_mode = enabled
        self._embed_callback = callback
        self.hide()
        if enabled:
            self.setWindowFlags(Qt.Widget)
            self.setAttribute(Qt.WA_DeleteOnClose, False)
        else:
            self.setWindowFlags(
                Qt.Tool | Qt.WindowStaysOnTopHint | Qt.WindowCloseButtonHint
            )
        self.show()

    def _setup_ui(self):
        # 仅气泡/特殊样式保留内联，其他由 cherry_style_light.qss 接管
        self.setStyleSheet("""
            QScrollArea { border: none; background: #f5f7fa; }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 顶部栏
        top_bar = QWidget()
        top_bar.setObjectName("chatTopBar")
        top_bar.setFixedHeight(44)
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(14, 0, 14, 0)

        top_title = QLabel("小鱼")
        top_title.setObjectName("titleLabel")
        top_layout.addWidget(top_title)
        top_layout.addStretch()

        self._status_dot = QLabel("●")
        self._status_dot.setStyleSheet("color: #5A9EBF; font-size: 10px; border: none;")
        top_layout.addWidget(self._status_dot)
        status_text = QLabel("在线")
        status_text.setObjectName("subtitleLabel")
        top_layout.addWidget(status_text)
        layout.addWidget(top_bar)

        # 消息区
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

        # 输入区
        input_box = QWidget()
        input_box.setObjectName("chatInputBar")
        input_layout = QHBoxLayout(input_box)
        input_layout.setContentsMargins(12, 10, 12, 10)
        input_layout.setSpacing(8)

        self._input = QTextEdit()
        self._input.setFixedHeight(56)
        self._input.setPlaceholderText("输入消息...")
        self._input.installEventFilter(self)
        input_layout.addWidget(self._input)

        send_btn = QPushButton("发送")
        send_btn.setObjectName("primaryBtn")
        send_btn.setFixedSize(56, 56)
        send_btn.clicked.connect(self._on_send)
        input_layout.addWidget(send_btn)

        layout.addWidget(input_box)

    def eventFilter(self, obj, event):
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
        bg, fg, align = self.BUBBLE_COLORS.get(persona, ("transparent", "#ccc", "left"))
        is_user = (align == "right")

        row = QWidget()
        row.setStyleSheet("background: transparent;")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)

        if not is_user:
            avatar = QLabel("●")
            avatar.setFixedSize(20, 20)
            dot_color = "#5A9EBF" if persona == "companion" else "#4a8eaf"
            avatar.setStyleSheet(f"color: {dot_color}; font-size: 16px; "
                                 "background: transparent; border: none;")
            avatar.setAlignment(Qt.AlignTop)
            row_layout.addWidget(avatar)

        if is_user:
            row_layout.addStretch()

        bubble = QLabel(msg["text"])
        bubble.setWordWrap(True)
        bubble.setMaximumWidth(280)
        if is_user:
            bubble.setStyleSheet(f"""
                background-color: {bg}; color: {fg};
                border-radius: 8px; padding: 8px 14px; font-size: 15px;
            """)
        else:
            bubble.setStyleSheet(f"""
                background-color: transparent; color: {fg};
                padding: 6px 0px 6px 0px; font-size: 15px;
            """)
        bubble.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        row_layout.addWidget(bubble)

        if not is_user:
            row_layout.addStretch()

        ts = QLabel(msg.get("time", ""))
        ts.setStyleSheet("color: #999; font-size: 12px; background: transparent; border: none;")
        ts.setAlignment(Qt.AlignBottom)
        if is_user:
            row_layout.insertWidget(row_layout.count() - 1, ts)
        else:
            row_layout.addWidget(ts)

        self._msg_layout.addWidget(row)

    def _add_typing_indicator(self):
        if self._typing_label:
            return
        row = QWidget()
        row.setStyleSheet("background: transparent;")
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)

        dot = QLabel("●")
        dot.setStyleSheet("color: #5A9EBF; font-size: 14px; background: transparent; border: none;")
        rl.addWidget(dot)

        label = QLabel("  小鱼正在打字")
        label.setStyleSheet("color: #888; font-size: 14px; background: transparent; border: none;")
        rl.addWidget(label)

        self._typing_dots = QLabel("...")
        self._typing_dots.setStyleSheet("color: #888; font-size: 14px; background: transparent; border: none;")
        rl.addWidget(self._typing_dots)
        rl.addStretch()

        self._dot_phase = 0
        self._dot_timer = QTimer(self)
        def _anim_dots():
            self._dot_phase = (self._dot_phase + 1) % 4
            self._typing_dots.setText("." * self._dot_phase if self._dot_phase else "...")
        self._dot_timer.timeout.connect(_anim_dots)
        self._dot_timer.start(400)

        self._typing_label = row
        self._msg_layout.addWidget(row)
        self._scroll_bottom()

    def _remove_typing_indicator(self):
        if self._typing_label:
            if hasattr(self, '_dot_timer'):
                self._dot_timer.stop()
            self._typing_label.deleteLater()
            self._typing_label = None

    def _scroll_bottom(self):
        sb = self._msg_area.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _reset_idle_timer(self):
        if self._embed_mode:
            return
        self._idle_timer.stop()
        self._idle_timer.start(self._idle_timeout_ms)

    def _on_idle_timeout(self):
        if self._embed_callback:
            self._embed_callback()
        else:
            self.hide()

    def _on_send(self):
        text = self._input.toPlainText().strip()
        if not text:
            return

        self._reset_idle_timer()

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
        if self._embed_mode and self._embed_callback:
            self._embed_callback()
            event.ignore()
        else:
            self.hide()
            event.ignore()

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_messages()
        self._reset_idle_timer()


# ═══════════════════════════════════════════════════════════
# 悬浮圆点
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
        self._float_phase = 0.0
        self._glow_phase = 0.0
        self._breath_speed = 0.04
        self._target_breath_speed = 0.04
        self._color = QColor("#4A9EFF")
        self._target_color = QColor("#4A9EFF")
        self._start_time = time.time()
        self._display_text = ""
        self._dragging = False
        self._cx = self.WINDOW_SIZE / 2
        self._cy = self.WINDOW_SIZE / 2
        self._dot_r = self.DIAMETER / 2
        self._glow_alpha = 25
        self._cached_frame = None
        self._drag_offset = QPoint()
        self._main_win = None
        self._thinker = None
        self._tray = None

        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)

        self._mode_locked = False

        self.show()

    # ── 模式管理 ──

    def set_mode(self, mode, auto=False):
        if auto and self._mode_locked:
            return
        if not auto:
            with _state_lock:
                _state["auto_mode"] = False
                _state["_mode_locked"] = False
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
            if self._main_win:
                self._main_win.show()
                self._main_win.raise_()

        if hasattr(self, '_tray') and self._tray:
            labels = {"sleep": "休眠", "accompany": "陪伴", "dialog": "对话"}
            self._tray.setToolTip(f"Agent · {labels.get(mode, mode)}")

    def get_mode(self):
        with _state_lock:
            return _state["mode"]

    # ── 绘制 ──

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
        with _state_lock:
            target_hex = _state["color"]
            breath_type = _state["breath"]
            text = _state["text"]
        self._target_color = QColor(target_hex)

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

        # 文字
        elapsed = int((time.time() - self._start_time) / 60)
        display_text = text if text else (
            f"已陪伴 {elapsed} 分钟" if elapsed >= 1 else "刚刚苏醒..."
        )
        if display_text and self.get_mode() != "sleep":
            font = QFont("Microsoft YaHei", 10)
            pp.setFont(font)
            text_rect = pix.rect().adjusted(6, int(dot_r + 18), -6, -2)
            fm = QFontMetrics(font)
            if fm.horizontalAdvance(display_text) > text_rect.width():
                display_text = fm.elidedText(display_text, Qt.ElideRight, text_rect.width())
            pp.setPen(QColor(255, 255, 255, 160))
            pp.drawText(text_rect, Qt.AlignHCenter | Qt.AlignTop, display_text)
        pp.end()

        self._cached_frame = pix

        # 自动模式切换
        with _state_lock:
            pending = _state.get("pending_auto_mode")
        if pending and not self._mode_locked:
            self.set_mode(pending, auto=True)
            with _state_lock:
                _state["pending_auto_mode"] = None

        self.update()

    # ── 拖拽 ──

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._drag_offset = event.globalPos() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self._dragging:
            self.move(event.globalPos() - self._drag_offset)

    def mouseReleaseEvent(self, event):
        self._dragging = False

    # ── 右键菜单 ──

    def contextMenuEvent(self, event):
        menu = QMenu()

        mode_menu = menu.addMenu("切换模式")
        sleep_action = mode_menu.addAction("💤 休眠态")
        companion_action = mode_menu.addAction("🌙 陪伴态")
        chat_action = mode_menu.addAction("💬 对话态")

        menu.addSeparator()

        # 打开主面板
        panel_action = menu.addAction("📋 打开主面板")

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
        elif action == panel_action:
            if self._main_win:
                self._main_win.show()
                self._main_win.raise_()
        elif action == lock_action:
            self._mode_locked = not self._mode_locked
        elif action == exit_action:
            self.hide()
            if self._main_win:
                self._main_win.close()
            if hasattr(self, '_tray') and self._tray:
                self._tray.hide()
            QApplication.quit()

    # ── 交互 ──

    def enterEvent(self, event):
        with _state_lock:
            tip = _state.get("tooltip", "")
            breath = _state["breath"]
        if tip:
            self.setToolTip(tip)
        else:
            breath_cn = {"slow": "静默观察中", "normal": "关注中", "fast": "有话要说"}
            self.setToolTip(f"Agent 运行中\n{breath_cn.get(breath, '')}\n双击打开主面板")

    def mouseDoubleClickEvent(self, event):
        """双击：显示/隐藏主面板"""
        if self._main_win:
            if self._main_win.isVisible():
                self._main_win.hide()
            else:
                self._main_win.show()
                self._main_win.raise_()
        else:
            self.set_mode("dialog")


# ═══════════════════════════════════════════════════════════
# 系统托盘
# ═══════════════════════════════════════════════════════════

class TrayManager:
    """系统托盘图标 + 右键菜单"""

    def __init__(self, dot, main_win=None):
        self._dot = dot
        self._main_win = main_win
        self._tray = QSystemTrayIcon()
        self._tray.setIcon(_make_tray_icon("#4A9EFF"))
        self._tray.setToolTip("Agent · 陪伴")

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

        act_panel = QAction("显示主面板", menu)
        act_panel.triggered.connect(self._show_panel)
        menu.addAction(act_panel)
        menu.addSeparator()

        act_quit = QAction("退出 Agent", menu)
        act_quit.triggered.connect(self._quit)
        menu.addAction(act_quit)

        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_tray_click)
        self._tray.show()

        self._icon_timer = QTimer()
        self._icon_timer.timeout.connect(self._update_icon)
        self._icon_timer.start(2000)

    def _on_tray_click(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            current = self._dot.get_mode()
            if current == "dialog":
                self._dot.set_mode("accompany")
            elif current == "accompany":
                self._dot.set_mode("dialog")
            else:
                self._dot.set_mode("accompany")

    def _show_panel(self):
        if self._main_win:
            self._main_win.show()
            self._main_win.raise_()

    def _update_icon(self):
        with _state_lock:
            color = _state["color"]
        self._tray.setIcon(_make_tray_icon(color))

    def _quit(self):
        self._dot.hide()
        if self._main_win:
            self._main_win.close()
        self._tray.hide()
        QApplication.quit()


# ═══════════════════════════════════════════════════════════
# stdout/stderr 重定向到终端日志
# ═══════════════════════════════════════════════════════════

class _LogRedirector:
    """将 print() / sys.stderr 输出重定向到 bridge.log_line"""
    def __init__(self, original):
        self._original = original

    def write(self, text):
        if text and text.strip():
            from agent_bridge import bridge
            bridge.log_line.emit("STDOUT", text.rstrip())
        if self._original:
            self._original.write(text)

    def flush(self):
        if self._original:
            self._original.flush()


# ═══════════════════════════════════════════════════════════
# 主窗口（QMainWindow：三 tab + 终端日志面板）
# ═══════════════════════════════════════════════════════════

class MainWindow(QMainWindow):
    """Cherry Studio 风格主窗口 — 左侧 sidebar + 右侧内容区"""

    # Sidebar 图标映射（qtawesome icon name, label）
    NAV_ITEMS = [
        ("fa5s.clock", " 时间切片"),
        ("fa5s.brain", " 情感辅助"),
        ("fa5s.tasks", " 任务助理"),
    ]

    def __init__(self, parent_dot, chat_window, thinker=None):
        super().__init__()
        self._dot = parent_dot
        self._chat = chat_window
        self._thinker = thinker

        self.setWindowTitle("认知增强系统")
        self.setMinimumSize(1000, 700)
        self.resize(1100, 750)

        # 加载浅色 QSS 样式
        qss_path = os.path.join(BASE_DIR, "cherry_style_light.qss")
        if os.path.exists(qss_path):
            try:
                with open(qss_path, "r", encoding="utf-8") as f:
                    self.setStyleSheet(f.read())
            except Exception:
                pass

        # 全局字体
        self.setFont(QFont("Microsoft YaHei UI", 10))

        # ── 中央布局：水平分割（sidebar | 内容区）──
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ─ 左侧 Sidebar ──
        self._sidebar = self._build_sidebar()
        main_layout.addWidget(self._sidebar)

        # ── 右侧内容区（QStackedWidget）──
        self._stack = QStackedWidget()
        self._stack.setStyleSheet("background: #f5f7fa;")

        from widgets.time_slice_tab import TimeSliceTab
        self._time_slice_tab = TimeSliceTab()
        self._stack.addWidget(self._time_slice_tab)

        from widgets.emotional_tab import EmotionalTab
        self._emotional_tab = EmotionalTab(thinker)
        self._emotional_tab.set_chat(self._chat)
        self._stack.addWidget(self._emotional_tab)

        from widgets.task_tab import TaskTab
        self._task_tab = TaskTab()
        self._stack.addWidget(self._task_tab)

        main_layout.addWidget(self._stack, stretch=1)

        # 默认选中「时间切片」
        self._stack.setCurrentIndex(0)

        # ── 终端日志面板（QDockWidget，底部）──
        from widgets.terminal_panel import TerminalPanel
        self._terminal = TerminalPanel(self)
        self.addDockWidget(Qt.BottomDockWidgetArea, self._terminal)

        # View 菜单
        menubar = self.menuBar()
        view_menu = menubar.addMenu("视图")
        view_menu.addAction(self._terminal.toggleViewAction())

        # 连接 bridge 信号
        self._connect_bridge()

    def _build_sidebar(self):
        """构建左侧导航栏"""
        try:
            import qtawesome as qta
        except Exception:
            qta = None

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(180)

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(12, 16, 12, 12)
        layout.setSpacing(6)

        # 标题
        title = QLabel("认知增强系统")
        title.setObjectName("titleLabel")
        title.setAlignment(Qt.AlignCenter)
        title.setFixedHeight(36)
        layout.addWidget(title)
        layout.addSpacing(12)

        # 分隔线
        sep = QFrame()
        sep.setObjectName("separator")
        sep.setFixedHeight(1)
        layout.addWidget(sep)
        layout.addSpacing(8)

        # 导航项
        self._nav_buttons = []
        self._nav_labels = []
        self._nav_icons = []

        for idx, (icon_name, label_text) in enumerate(self.NAV_ITEMS):
            # 图标
            icon_label = QLabel()
            icon_label.setFixedSize(24, 24)
            icon_label.setAlignment(Qt.AlignCenter)
            if qta:
                try:
                    color = "#888" if idx != 0 else "#5A9EBF"
                    icon = qta.icon(icon_name, color=color, scale_factor=1.2)
                    icon_label.setPixmap(icon.pixmap(20, 20))
                except Exception:
                    pass
            self._nav_icons.append(icon_label)

            # 文字
            text_label = QLabel(label_text.strip())
            text_label.setObjectName("sidebarLabelSelected" if idx == 0 else "sidebarLabelInactive")
            text_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            self._nav_labels.append(text_label)

            # 容器（整行可点击）
            row = QFrame()
            row.setObjectName("sidebarItemSelected" if idx == 0 else "sidebarItem")
            row.setFixedHeight(40)
            row.setCursor(Qt.PointingHandCursor)
            row.setProperty("navIndex", idx)

            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(10, 0, 10, 0)
            row_layout.setSpacing(10)
            row_layout.addWidget(icon_label)
            row_layout.addWidget(text_label, stretch=1)

            self._nav_buttons.append(row)
            layout.addWidget(row)

            # 点击事件
            row.mousePressEvent = lambda ev, i=idx: self._on_nav_click(i)

        layout.addStretch()

        # 底部悬浮窗状态
        self._sidebar_status = QLabel("● 陪伴中")
        self._sidebar_status.setStyleSheet(
            "color: #5A9EBF; font-size: 12px; background: transparent; border: none;"
        )
        self._sidebar_status.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._sidebar_status)

        return sidebar

    def _on_nav_click(self, index):
        """切换导航项"""
        self._stack.setCurrentIndex(index)

        for i, btn in enumerate(self._nav_buttons):
            if i == index:
                btn.setObjectName("sidebarItemSelected")
                self._nav_labels[i].setObjectName("sidebarLabelSelected")
                # 更新图标颜色
                if self._nav_icons[i]:
                    try:
                        import qtawesome as qta
                        icon = qta.icon(self.NAV_ITEMS[i][0], color="#5A9EBF", scale_factor=1.2)
                        self._nav_icons[i].setPixmap(icon.pixmap(20, 20))
                    except Exception:
                        pass
            else:
                btn.setObjectName("sidebarItem")
                self._nav_labels[i].setObjectName("sidebarLabelInactive")
                if self._nav_icons[i]:
                    try:
                        import qtawesome as qta
                        icon = qta.icon(self.NAV_ITEMS[i][0], color="#888", scale_factor=1.2)
                        self._nav_icons[i].setPixmap(icon.pixmap(20, 20))
                    except Exception:
                        pass
            # 强制刷新样式
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            self._nav_labels[i].style().unpolish(self._nav_labels[i])
            self._nav_labels[i].style().polish(self._nav_labels[i])

    def _connect_bridge(self):
        from agent_bridge import bridge
        bridge.status_updated.connect(self._on_status_updated)
        bridge.message_added.connect(self._on_message_added)
        bridge.mode_requested.connect(self._on_mode_requested)

    def _on_status_updated(self, color, breath, text):
        update_status(color=color, breath=breath, text=text)

    def _on_message_added(self, persona, text):
        add_message(persona, text)

    def _on_mode_requested(self, mode):
        request_auto_mode(mode)

    def closeEvent(self, event):
        """关闭窗口 = 缩回悬浮窗，不退出程序"""
        self._dot.set_mode("accompany")
        event.ignore()
        self.hide()


# ═══════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════

def main():
    if not _acquire_single_instance():
        sys.exit(0)

    # QApplication 必须在 stdout 重定向前创建（bridge 信号需要 Qt 环境）
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("认知增强系统")

    # stdout/stderr 重定向到终端日志
    _original_stdout = sys.stdout
    _original_stderr = sys.stderr
    sys.stdout = _LogRedirector(_original_stdout)
    sys.stderr = _LogRedirector(_original_stderr)

    print("[UI] 启动认知增强系统...")

    # 悬浮窗
    dot = CompanionDot()

    # 聊天窗（嵌入模式，thinker 由 Agent 线程稍后设置）
    chat = ChatWindow(thinker=None)

    # 主窗口
    main_win = MainWindow(dot, chat, thinker=None)
    dot._main_win = main_win

    # 托盘
    tray_mgr = TrayManager(dot, main_win)
    dot._tray = tray_mgr._tray

    # 后台线程：启动 Agent
    agent_thread = threading.Thread(
        target=_start_agent, args=(dot, chat), daemon=True, name="AgentLoop"
    )
    agent_thread.start()
    print("[UI] Agent 后台线程已启动")

    sys.exit(app.exec_())


def _start_agent(dot, chat):
    """后台线程：创建 Thinker → 启动 Agent 循环"""
    from agent_loop import run_agent
    from agent_thinker import Thinker

    try:
        thinker = Thinker()
        thinker.client.chat.completions.create(
            model=thinker.model,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=4, timeout=8,
        )
        dot._thinker = thinker
        chat._thinker = thinker
        print("[UI] Thinker 连接成功")
    except Exception as e:
        print(f"[UI] Thinker 创建失败: {e}")
        thinker = None

    run_agent(thinker=thinker)


if __name__ == "__main__":
    main()
