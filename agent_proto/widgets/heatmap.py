# -*- coding: utf-8 -*-
"""热力图 — QPainter 手绘年度热力图，Phase 2 填充"""
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt5.QtCore import Qt


class HeatMap(QWidget):
    """年度热力图 — QPainter 手绘 365 天方格"""

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        placeholder = QLabel(
        "🔥 年度活动热力图\n\n（Phase 2 填充）"
        )
        placeholder.setAlignment(Qt.AlignCenter)
        placeholder.setStyleSheet("color: #555; font-size: 16px; border: none;")
        layout.addWidget(placeholder)
