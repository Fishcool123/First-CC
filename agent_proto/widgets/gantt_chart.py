# -*- coding: utf-8 -*-
"""甘特图 — QPainter 手绘周视图"""
from datetime import datetime, timedelta, date

from PyQt5.QtWidgets import QWidget, QSizePolicy
from PyQt5.QtCore import Qt, QRect, QPoint, QSize
from PyQt5.QtGui import QPainter, QColor, QBrush, QPen, QFont, QFontMetrics

from database import get_schedule

_WEEKDAYS = ["一", "二", "三", "四", "五", "六", "日"]
_PRIO = {
    1: (224, 85, 85), 2: (224, 160, 85),
    3: (85, 160, 224), 4: (136, 102, 204), 5: (85, 170, 136),
}
_DFLT = (85, 160, 224)


class GanttChart(QWidget):
    """周视图甘特图"""
    HOUR_H = 22
    LABEL_W = 48
    HEADER_H = 28

    def __init__(self):
        super().__init__()
        self._scheduled = []
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    def sizeHint(self):
        return QSize(600, self.HEADER_H + 24 * self.HOUR_H + 30)

    def load_week(self, start_date=None):
        if start_date is None:
            today = date.today()
            start_date = today - timedelta(days=today.weekday())
        self._scheduled = []
        try:
            for d_off in range(7):
                day = start_date + timedelta(days=d_off)
                ds = day.strftime("%Y-%m-%d")
                for r in get_schedule(ds):
                    self._scheduled.append({
                        "title": r.get("title", "?"),
                        "date_str": ds,
                        "start": r.get("start_time", ""),
                        "end": r.get("end_time", ""),
                        "priority": r.get("priority", 3),
                        "is_manual": r.get("is_manual", 0),
                    })
        except Exception:
            pass
        self.update()

    def clear(self):
        self._scheduled = []
        self.update()

    def paintEvent(self, event):
        w = self.width()
        h = self.height()
        if w < self.LABEL_W + 80 or h < 50:
            return

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(0, 0, w, h, QColor(245, 247, 250))

        today = date.today()
        ox = self.LABEL_W
        oy = self.HEADER_H
        col_w = max(80, (w - ox - 8) // 7)
        now = datetime.now()

        # 周标题
        p.setFont(QFont("Microsoft YaHei", 10))
        for i in range(7):
            x = ox + i * col_w
            d = today - timedelta(days=today.weekday() - i)
            if i == today.weekday():
                p.fillRect(x, 0, col_w, self.HEADER_H, QColor(230, 240, 250))
                p.setPen(QColor(90, 158, 191))
            else:
                p.setPen(QColor(136, 136, 136))
            p.drawText(x, 0, col_w, self.HEADER_H, Qt.AlignCenter,
                       f"{_WEEKDAYS[i]} {d.strftime('%m/%d')}")

        # 时间网格
        p.setFont(QFont("Consolas", 9))
        for hour in range(25):
            y = oy + hour * self.HOUR_H
            if hour % 3 == 0:
                p.setPen(QColor(224, 224, 224))
                p.drawLine(ox, y, ox + 7 * col_w, y)
                p.setPen(QColor(102, 102, 102))
                p.drawText(0, y - 9, ox - 4, 18,
                           Qt.AlignRight | Qt.AlignVCenter, f"{hour:02d}:00")
            else:
                p.setPen(QColor(240, 240, 240))
                p.drawLine(ox, y, ox + 7 * col_w, y)

        # 当前时间线
        if 0 <= now.weekday() < 7:
            now_h = now.hour + now.minute / 60
            now_y = int(oy + now_h * self.HOUR_H)
            now_x = ox + now.weekday() * col_w
            p.setPen(QPen(QColor(224, 85, 85), 1.5))
            p.drawLine(now_x, max(oy, now_y), now_x + col_w, now_y)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(224, 85, 85))
            p.drawEllipse(QPoint(now_x + col_w // 2, now_y), 3, 3)

        # 任务条
        fm8 = QFontMetrics(QFont("Microsoft YaHei", 8))
        p.setFont(QFont("Microsoft YaHei", 8))
        for item in self._scheduled:
            try:
                d = datetime.strptime(item["date_str"], "%Y-%m-%d").date()
                col = d.weekday()
                sh, sm = item["start"].split(":")
                eh, em = item["end"].split(":")
                s_h = int(sh) + int(sm) / 60
                e_h = int(eh) + int(em) / 60
            except Exception:
                continue
            x = ox + col * col_w + 2
            bw = col_w - 4
            by = int(oy + s_h * self.HOUR_H)
            bh = max(8, int((e_h - s_h) * self.HOUR_H))
            c = _PRIO.get(item.get("priority", 3), _DFLT)
            # 半透明背景
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(c[0], c[1], c[2], 35))
            p.drawRoundedRect(x, by, bw, bh, 4, 4)
            # 左侧色条
            if item.get("is_manual", 0):
                p.setPen(QPen(QColor(*c), 2))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(x, by, bw, bh, 4, 4)
            else:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(*c))
                p.drawRoundedRect(x, by, 3, bh, 1, 1)
            # 标题
            label = f"{item['title']} ({item['start'][:5]}-{item['end'][:5]})"
            p.setPen(QColor(51, 51, 51))
            el = fm8.elidedText(label, Qt.ElideRight, bw - 10)
            p.drawText(x + 6, by, bw - 10, bh, Qt.AlignLeft | Qt.AlignVCenter, el)

        # 图例
        ly = oy + 24 * self.HOUR_H + 6
        fm9 = QFontMetrics(QFont("Microsoft YaHei", 9))
        p.setFont(QFont("Microsoft YaHei", 9))
        lx = ox
        for prio, label in [(1, "P1紧急"), (2, "P2高"), (3, "P3中"), (4, "P4低"), (5, "P5闲")]:
            c = _PRIO.get(prio, _DFLT)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(*c))
            p.drawRoundedRect(lx, ly, 10, 10, 2, 2)
            p.setPen(QColor(136, 136, 136))
            tw = fm9.horizontalAdvance(label) + 4
            p.drawText(lx + 13, ly, tw, 10, Qt.AlignLeft | Qt.AlignVCenter, label)
            lx += tw + 22

        p.end()
