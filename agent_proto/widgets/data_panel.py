# -*- coding: utf-8 -*-
"""
DataPanel：情绪数据可视化 — 7日折线图 + 标签云（可折叠）
Phase 3 C2-C4 实现
"""
import math
from datetime import datetime, timedelta

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
)
from PyQt5.QtCore import Qt, QRect, QPoint, QTimer
from PyQt5.QtGui import (
    QPainter, QColor, QBrush, QPen, QFont, QFontMetrics,
)

from database import get_conn


class DataPanel(QWidget):
    """情绪数据可视化面板 — 可折叠 + 7日折线图 + 标签云"""

    LINE_COLORS = {
        "专注": QColor("#4A9EFF"),
        "平静": QColor("#4aff9e"),
        "开心": QColor("#ffe84a"),
        "焦虑": QColor("#ff994a"),
        "兴奋": QColor("#ff4aff"),
        "沮丧": QColor("#8888cc"),
        "紧张": QColor("#ff6b6b"),
        "疲倦": QColor("#999999"),
        "满足": QColor("#4affcc"),
    }
    DEFAULT_COLOR = QColor("#4A9EFF")

    def __init__(self):
        super().__init__()
        self._collapsed = True  # 默认折叠
        self._chart_data = {}   # {date_str: {tag: count}}
        self._all_tags = []
        self._tag_counts = {}   # {tag: total_count} 用于标签云
        self._setup_ui()
        self._load_data()

        # 每 60 秒刷新
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._load_data)
        self._refresh_timer.start(60000)

    def _setup_ui(self):
        self.setStyleSheet("background: #f5f7fa;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 标题栏（可点击折叠）
        self._title_bar = QWidget()
        self._title_bar.setFixedHeight(28)
        self._title_bar.setStyleSheet("background: #ffffff; border-top: 1px solid #e8eaed;")
        self._title_bar.setCursor(Qt.PointingHandCursor)
        self._title_bar.mousePressEvent = lambda e: self._toggle()
        tb_layout = QHBoxLayout(self._title_bar)
        tb_layout.setContentsMargins(12, 0, 8, 0)
        self._title_label = QLabel(" 情绪数据 ▸")
        self._title_label.setStyleSheet("color: #666; font-size: 13px; border: none;")
        tb_layout.addWidget(self._title_label)
        tb_layout.addStretch()
        layout.addWidget(self._title_bar)

        # 内容区
        self._content = QWidget()
        self._content.hide()  # 默认折叠
        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        # 折线图
        self._chart = _LineChart()
        content_layout.addWidget(self._chart, stretch=1)

        # 标签云
        self._tag_cloud = _TagCloud()
        self._tag_cloud.setFixedHeight(100)
        content_layout.addWidget(self._tag_cloud)

        layout.addWidget(self._content)

    def _toggle(self):
        self._collapsed = not self._collapsed
        if self._collapsed:
            self._content.hide()
            self._title_label.setText("📊 情绪数据 ▸")
        else:
            self._load_data()
            self._content.show()
            self._title_label.setText("📊 情绪数据 ▾")

    def _load_data(self):
        """查询近 7 日情绪数据"""
        try:
            conn = get_conn("slices")
            since = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
            rows = conn.execute(
                """SELECT date(timestamp) as d, mood_tags
                   FROM slices
                   WHERE date(timestamp) >= ? AND mood_tags IS NOT NULL
                   AND mood_tags != '' AND mood_tags != '[]'""",
                (since,),
            ).fetchall()
            conn.close()

            import json
            chart_data = {}
            tag_counts = {}
            for r in rows:
                date_str = r["d"]
                try:
                    tags = json.loads(r["mood_tags"]) if isinstance(r["mood_tags"], str) else r["mood_tags"]
                except Exception:
                    continue
                if not tags:
                    continue
                if date_str not in chart_data:
                    chart_data[date_str] = {}
                for t in tags:
                    chart_data[date_str][t] = chart_data[date_str].get(t, 0) + 1
                    tag_counts[t] = tag_counts.get(t, 0) + 1

            # 确保最近 7 天都有数据点（即使为 0）
            today = datetime.now().date()
            full_data = {}
            for i in range(7):
                d = (today - timedelta(days=6 - i)).strftime("%Y-%m-%d")
                full_data[d] = chart_data.get(d, {})
            self._chart_data = full_data

            # 收集所有出现过的标签
            all_tags = set()
            for day_data in full_data.values():
                all_tags.update(day_data.keys())
            all_tags.update(tag_counts.keys())
            self._all_tags = sorted(all_tags, key=lambda t: tag_counts.get(t, 0), reverse=True)
            self._tag_counts = tag_counts

        except Exception as e:
            self._chart_data = {}
            self._all_tags = []
            self._tag_counts = {}

        self._chart.set_data(self._chart_data, self._all_tags, self.LINE_COLORS, self.DEFAULT_COLOR)
        self._tag_cloud.set_tags(self._tag_counts, self.LINE_COLORS, self.DEFAULT_COLOR)


# ═══════════════════════════════════════════════════════════
# 7 日情绪折线图（QPainter 手绘）
# ═══════════════════════════════════════════════════════════

class _LineChart(QWidget):
    def __init__(self):
        super().__init__()
        self._data = {}
        self._tags = []
        self._colors = {}
        self._default_color = QColor("#4A9EFF")
        self.setMinimumHeight(140)

    def set_data(self, data, tags, colors, default_color):
        self._data = data
        self._tags = tags[:6]  # 最多显示 6 条线
        self._colors = colors
        self._default_color = default_color
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#f5f7fa"))

        if not self._data or not self._tags:
            p.setPen(QColor("#bbb"))
            p.setFont(QFont("Microsoft YaHei", 12))
            p.drawText(self.rect(), Qt.AlignCenter, "暂无情绪数据")
            p.end()
            return

        w, h = self.width(), self.height()
        margin_l, margin_r, margin_t, margin_b = 36, 12, 16, 28
        chart_w = w - margin_l - margin_r
        chart_h = h - margin_t - margin_b

        if chart_w < 20 or chart_h < 20:
            p.end()
            return

        # 背景网格
        p.setPen(QPen(QColor("#e8e8e8"), 0.5))
        for i in range(5):
            y = int(margin_t + chart_h * i / 4)
            p.drawLine(margin_l, y, w - margin_r, y)

        # Y 轴刻度
        font = QFont("Microsoft YaHei", 9)
        p.setFont(font)
        max_val = 1
        for day_data in self._data.values():
            if day_data:
                max_val = max(max_val, max(day_data.values()))
        max_val = max(max_val, 4)  # 最少 4 格

        for i in range(5):
            val = int(max_val * (4 - i) / 4)
            y = int(margin_t + chart_h * i / 4)
            p.setPen(QColor("#999"))
            p.drawText(QRect(0, y - 8, margin_l - 4, 16),
                       Qt.AlignRight | Qt.AlignVCenter, str(val))

        # X 轴日期
        dates = list(self._data.keys())
        for i, date_str in enumerate(dates):
            if len(dates) <= 1:
                x = margin_l + chart_w // 2
            else:
                x = int(margin_l + chart_w * i / (len(dates) - 1))
            label = date_str[5:]  # "MM-DD"
            p.setPen(QColor("#999"))
            p.drawText(QRect(x - 20, h - margin_b + 4, 40, 16),
                       Qt.AlignCenter, label)

        # 折线
        for tag_idx, tag in enumerate(self._tags):
            color = self._colors.get(tag, self._default_color)
            pen = QPen(color, 2.0)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)

            points = []
            for i, (date_str, day_data) in enumerate(self._data.items()):
                val = day_data.get(tag, 0)
                if len(dates) <= 1:
                    x = margin_l + chart_w // 2
                else:
                    x = int(margin_l + chart_w * i / (len(dates) - 1))
                y = int(margin_t + chart_h * (1 - val / max(max_val, 1)))
                points.append(QPoint(x, y))

            # 画线
            for j in range(len(points) - 1):
                p.drawLine(points[j], points[j + 1])

            # 画点
            p.setBrush(QBrush(color))
            p.setPen(Qt.NoPen)
            for pt in points:
                p.drawEllipse(pt, 3, 3)

        # 图例
        legend_x = margin_l
        legend_y = 4
        legend_font = QFont("Microsoft YaHei", 9)
        p.setFont(legend_font)
        for tag in self._tags:
            color = self._colors.get(tag, self._default_color)
            tw = QFontMetrics(legend_font).horizontalAdvance(tag) + 16
            if legend_x + tw > w - margin_r:
                legend_x = margin_l
                legend_y += 16
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(color))
            p.drawEllipse(QPoint(legend_x + 4, legend_y + 7), 3, 3)
            p.setPen(QColor("#888"))
            p.drawText(QRect(legend_x + 10, legend_y, tw - 10, 14),
                       Qt.AlignLeft | Qt.AlignVCenter, tag)
            legend_x += tw + 4

        p.end()


# ═══════════════════════════════════════════════════════════
# 情绪标签云（QPainter 手绘）
# ═══════════════════════════════════════════════════════════

class _TagCloud(QWidget):
    def __init__(self):
        super().__init__()
        self._tags = {}    # {tag: count}
        self._colors = {}
        self._default_color = QColor("#4A9EFF")

    def set_tags(self, tag_counts, colors, default_color):
        self._tags = tag_counts
        self._colors = colors
        self._default_color = default_color
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#f5f7fa"))

        if not self._tags:
            p.end()
            return

        w, h = self.width(), self.height()
        total = sum(self._tags.values()) or 1

        # 按计数排序
        sorted_tags = sorted(self._tags.items(), key=lambda x: -x[1])

        # 逐个放置标签
        margin = 8
        x, row_y = margin, margin
        row_h = 0

        for tag, count in sorted_tags:
            ratio = count / total
            font_size = max(12, min(28, int(14 + ratio * 28)))
            font = QFont("Microsoft YaHei", font_size)
            p.setFont(font)
            fm = QFontMetrics(font)
            tw = fm.horizontalAdvance(tag) + 10
            th = fm.height() + 4

            if x + tw > w - margin:
                x = margin
                row_y += row_h + 6
                row_h = 0

            color = self._colors.get(tag, self._default_color)
            alpha = max(80, int(180 + ratio * 75))
            color.setAlpha(alpha)
            p.setPen(color)
            p.drawText(QRect(x, row_y, tw, th), Qt.AlignCenter, tag)

            x += tw + 4
            row_h = max(row_h, th)

        p.end()
