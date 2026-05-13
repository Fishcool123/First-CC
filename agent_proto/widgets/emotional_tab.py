# -*- coding: utf-8 -*-
"""
EmotionalTab：情感辅助 tab（方案C上下铺）
上半区：ChatWindow 嵌入 + "⤢ 弹出"按钮
下半区：DataPanel 可折叠（QSplitter 分隔）+ 底部情绪状态条
Phase 3 C1-C4 实现
"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QPushButton, QLabel,
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QMouseEvent

from widgets.data_panel import DataPanel


class _ClickableLabel(QLabel):
    """可点击的占位标签：弹出后点击收回聊天窗"""
    clicked = None

    def mousePressEvent(self, event: QMouseEvent):
        if self.clicked:
            self.clicked()


class EmotionalTab(QWidget):
    """Tab1：情感辅助 = ChatWindow(上) + QSplitter + DataPanel(下) + 状态条"""

    def __init__(self, thinker=None):
        super().__init__()
        self._thinker = thinker
        self._chat = None
        self._pop_out_btn = None
        self._chat_popped = False
        self._mood_label = None
        self._last_record_label = None

        self._setup_ui()
        self._refresh_status()

        # 每 30 秒刷新状态
        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._refresh_status)
        self._status_timer.start(30000)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._splitter = QSplitter(Qt.Vertical)
        layout.addWidget(self._splitter)

        # 上半区：ChatWindow 容器
        self._chat_container = QWidget()
        self._chat_container.setStyleSheet("background: #f5f7fa;")
        chat_layout = QVBoxLayout(self._chat_container)
        chat_layout.setContentsMargins(0, 0, 0, 0)
        chat_layout.setSpacing(0)

        # 顶部条：弹出/收回按钮
        top_bar = QWidget()
        top_bar.setFixedHeight(28)
        top_bar.setStyleSheet("background: #ffffff; border-bottom: 1px solid #e8eaed;")
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(8, 0, 8, 0)
        top_layout.addStretch()
        self._pop_out_btn = QPushButton("⤢ 弹出")
        self._pop_out_btn.setFixedSize(56, 22)
        self._pop_out_btn.setStyleSheet("""
            QPushButton {
                background: #f0f2f5; color: #666; border: none;
                border-radius: 3px; font-size: 13px;
            }
            QPushButton:hover { background: #e0e2e5; color: #333; }
        """)
        self._pop_out_btn.clicked.connect(self._toggle_chat)
        self._pop_out_btn.hide()
        top_layout.addWidget(self._pop_out_btn)
        chat_layout.addWidget(top_bar)

        # ChatWindow 占位（弹出后可点击收回）
        self._chat_placeholder = _ClickableLabel("💬 聊天窗加载中...")
        self._chat_placeholder.setAlignment(Qt.AlignCenter)
        self._chat_placeholder.setStyleSheet("color: #999; font-size: 16px; border: none;")
        self._chat_placeholder.clicked = self._embed_chat
        chat_layout.addWidget(self._chat_placeholder, stretch=1)

        self._splitter.addWidget(self._chat_container)

        # 下半区：DataPanel
        self._data_panel = DataPanel()
        self._splitter.addWidget(self._data_panel)

        self._splitter.setSizes([400, 200])

        # ── 底部状态条（C1：今日情绪摘要）──
        self._status_bar = QWidget()
        self._status_bar.setObjectName("emotionalStatusBar")
        self._status_bar.setFixedHeight(36)
        status_layout = QHBoxLayout(self._status_bar)
        status_layout.setContentsMargins(12, 0, 12, 0)
        status_layout.setSpacing(16)

        self._mood_label = QLabel("今日情绪：--")
        self._mood_label.setStyleSheet("color: #5A9EBF; font-size: 13px; border: none;")
        status_layout.addWidget(self._mood_label)

        status_layout.addStretch()

        self._last_record_label = QLabel("上次记录：--")
        self._last_record_label.setStyleSheet("color: #888888; font-size: 12px; border: none;")
        status_layout.addWidget(self._last_record_label)

        layout.addWidget(self._status_bar)

    def _refresh_status(self):
        """从数据库拉取今日情绪摘要"""
        try:
            from agent_memory import get_today_mood_summary, get_last_manual_record
            summary = get_today_mood_summary()
            if "暂无" in summary:
                self._mood_label.setText("今日情绪：暂无记录")
                self._mood_label.setStyleSheet("color: #999; font-size: 13px; border: none;")
            else:
                self._mood_label.setText(f"今日情绪：{summary.replace('记录', '').replace('次：', ' — ')}")
                self._mood_label.setStyleSheet("color: #5A9EBF; font-size: 13px; border: none;")

            ts, desc = get_last_manual_record()
            if ts:
                # 取时间部分
                time_part = ts.split()[-1] if " " in ts else ts
                self._last_record_label.setText(f"上次记录：{time_part} · {desc[:12]}")
            else:
                self._last_record_label.setText("上次记录：--")
        except Exception:
            pass

    def set_chat(self, chat_window):
        """将外部创建的 ChatWindow 嵌入本 tab 的上半区"""
        self._chat = chat_window
        self._chat_placeholder.hide()
        self._chat_container.layout().addWidget(chat_window, stretch=1)
        chat_window.set_embed_mode(True, self._embed_chat)
        self._pop_out_btn.show()

    def _toggle_chat(self):
        """切换弹出/嵌入"""
        if self._chat_popped:
            self._embed_chat()
        else:
            self._pop_out_chat()

    def _pop_out_chat(self):
        """弹出 ChatWindow 为独立窗口"""
        if not self._chat:
            return
        self._chat_popped = True
        self._chat_container.layout().removeWidget(self._chat)
        self._chat.set_embed_mode(False)
        # set_embed_mode 内已 show()，但再确保一次位置
        if not self._chat.isVisible():
            self._chat.show()
        self._chat.raise_()
        self._chat.activateWindow()
        self._pop_out_btn.setText("⤡ 收回")
        self._chat_placeholder.setText(" 聊天窗已弹出\n点击此处收回")
        self._chat_placeholder.setStyleSheet(
            "color: #999; font-size: 16px; border: 2px dashed #d0d0d0;"
            "border-radius: 8px; background: #f0f2f5;"
        )
        self._chat_placeholder.setCursor(Qt.PointingHandCursor)
        self._chat_placeholder.show()

    def _embed_chat(self):
        """ChatWindow 回到上半区"""
        if not self._chat:
            return
        self._chat_popped = False
        self._chat.hide()
        self._chat.setParent(None)
        self._chat.set_embed_mode(True, self._embed_chat)
        self._chat_container.layout().addWidget(self._chat, stretch=1)
        self._chat.show()
        self._chat_placeholder.hide()
        self._chat_placeholder.setStyleSheet("color: #555; font-size: 16px; border: none;")
        self._chat_placeholder.setCursor(Qt.ArrowCursor)
        self._pop_out_btn.setText("⤢ 弹出")
        self._pop_out_btn.show()
