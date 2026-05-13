# -*- coding: utf-8 -*-
"""
Tab0：时间切片系统 — 快速记录 + 切片历史 + 设备日志 + 年度热力图
Phase 2 完整实现
"""
import math
from datetime import datetime, timedelta

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QStackedWidget, QTableView, QHeaderView, QLineEdit,
    QDialog, QSlider, QTextEdit, QCheckBox, QGridLayout,
    QAbstractItemView, QFrame, QButtonGroup,
)
from PyQt5.QtCore import Qt, QAbstractTableModel, QModelIndex, QRect
from PyQt5.QtGui import (
    QPainter, QColor, QBrush, QPen, QFont, QFontMetrics,
)

from database import get_conn


# ═══════════════════════════════════════════════════════════
# 快速记录弹窗
# ═══════════════════════════════════════════════════════════

class QuickRecordDialog(QDialog):
    """快速情绪切片记录弹窗"""

    MOOD_PRESETS = ["专注", "平静", "开心", "焦虑", "兴奋", "沮丧", "紧张", "疲倦", "满足"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("快速记录")
        self.setMinimumSize(360, 420)
        self.resize(380, 460)
        self.setWindowFlags(Qt.Dialog | Qt.WindowCloseButtonHint)
        self.setStyleSheet("""
            QDialog { background: #ffffff; }
            QLabel { color: #333; font-size: 14px; border: none; }
            QCheckBox {
                color: #333; font-size: 14px; spacing: 4px;
                background: #f5f7fa; border: 1px solid #d9d9d9;
                border-radius: 4px; padding: 4px 10px;
            }
            QCheckBox:checked {
                background: #e6f0fa; border-color: #5A9EBF; color: #5A9EBF;
            }
            QCheckBox:hover { border-color: #bfbfbf; }
            QSlider::groove:horizontal {
                height: 6px; background: #e0e0e0; border-radius: 3px;
            }
            QSlider::handle:horizontal {
                width: 14px; height: 14px; margin: -5px 0;
                background: #5A9EBF; border-radius: 7px;
            }
            QTextEdit, QLineEdit {
                background: #ffffff; color: #333;
                border: 1px solid #d9d9d9; border-radius: 4px;
                padding: 6px 10px; font-size: 14px;
            }
            QPushButton {
                background: #5A9EBF; color: #fff; border: none;
                border-radius: 4px; padding: 8px 20px; font-size: 15px;
            }
            QPushButton:hover { background: #6bb0d1; }
            QPushButton#cancelBtn { background: #f0f2f5; color: #666; }
            QPushButton#cancelBtn:hover { background: #e0e2e5; }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # 情绪标签
        layout.addWidget(QLabel("情绪标签（可多选）"))
        self._mood_checkboxes = []
        mood_grid = QGridLayout()
        mood_grid.setSpacing(6)
        for i, tag in enumerate(self.MOOD_PRESETS):
            cb = QCheckBox(tag)
            self._mood_checkboxes.append(cb)
            mood_grid.addWidget(cb, i // 3, i % 3)
        layout.addLayout(mood_grid)

        # 情绪强度
        intensity_row = QHBoxLayout()
        intensity_row.addWidget(QLabel("情绪强度"))
        self._intensity_slider = QSlider(Qt.Horizontal)
        self._intensity_slider.setRange(1, 5)
        self._intensity_slider.setValue(3)
        self._intensity_slider.setFixedWidth(160)
        intensity_row.addWidget(self._intensity_slider)
        self._intensity_label = QLabel("3")
        self._intensity_label.setFixedWidth(20)
        self._intensity_label.setStyleSheet("color: #4A9EFF; font-weight: bold;")
        self._intensity_slider.valueChanged.connect(
            lambda v: self._intensity_label.setText(str(v)))
        intensity_row.addWidget(self._intensity_label)
        intensity_row.addStretch()
        layout.addLayout(intensity_row)

        # 精力水平
        energy_row = QHBoxLayout()
        energy_row.addWidget(QLabel("精力水平"))
        self._energy_slider = QSlider(Qt.Horizontal)
        self._energy_slider.setRange(1, 5)
        self._energy_slider.setValue(3)
        self._energy_slider.setFixedWidth(160)
        energy_row.addWidget(self._energy_slider)
        self._energy_label = QLabel("3")
        self._energy_label.setFixedWidth(20)
        self._energy_label.setStyleSheet("color: #4A9EFF; font-weight: bold;")
        self._energy_slider.valueChanged.connect(
            lambda v: self._energy_label.setText(str(v)))
        energy_row.addWidget(self._energy_label)
        energy_row.addStretch()
        layout.addLayout(energy_row)

        # 活动描述
        layout.addWidget(QLabel("活动描述"))
        self._activity_input = QLineEdit()
        self._activity_input.setPlaceholderText("正在做什么...")
        layout.addWidget(self._activity_input)

        # 备注
        layout.addWidget(QLabel("备注"))
        self._notes_input = QTextEdit()
        self._notes_input.setFixedHeight(56)
        self._notes_input.setPlaceholderText("补充说明...")
        layout.addWidget(self._notes_input)

        # 按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("取消")
        cancel_btn.setObjectName("cancelBtn")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        save_btn = QPushButton("记录")
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

    def _save(self):
        moods = [cb.text() for cb in self._mood_checkboxes if cb.isChecked()]
        mood_str = str(moods) if moods else "[]"
        activity = self._activity_input.text().strip() or "手动记录"
        notes = self._notes_input.toPlainText().strip()
        try:
            conn = get_conn("slices")
            conn.execute(
                """INSERT INTO slices
                   (timestamp, activity_desc, mood_tags, mood_intensity,
                    energy_level, notes)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                 activity, mood_str,
                 self._intensity_slider.value(),
                 self._energy_slider.value(), notes),
            )
            conn.commit()
            conn.close()
            self.accept()
        except Exception as e:
            print(f"[Slice] 记录失败: {e}")
            self.reject()


# ═══════════════════════════════════════════════════════════
# 切片历史表格模型
# ═══════════════════════════════════════════════════════════

_SLICE_COLS = ["时间", "活动", "情绪", "强度", "精力", "备注"]


class _SliceTableModel(QAbstractTableModel):
    def __init__(self):
        super().__init__()
        self._rows = []
        self._search = ""

    def set_search(self, keyword):
        self._search = keyword.strip().lower()
        self._reload()

    def _reload(self):
        rows = []
        try:
            conn = get_conn("slices")
            if self._search:
                rows = conn.execute(
                    """SELECT timestamp, activity_desc, mood_tags,
                       mood_intensity, energy_level, notes
                       FROM slices
                       WHERE activity_desc LIKE ? OR notes LIKE ?
                          OR mood_tags LIKE ?
                       ORDER BY timestamp DESC LIMIT 200""",
                    (f"%{self._search}%",) * 3,
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT timestamp, activity_desc, mood_tags,
                       mood_intensity, energy_level, notes
                       FROM slices ORDER BY timestamp DESC LIMIT 100"""
                ).fetchall()
            conn.close()
            rows = [dict(r) for r in rows]
        except Exception:
            rows = []
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return len(_SLICE_COLS)

    def headerData(self, section, orientation, role):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return _SLICE_COLS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        col = index.column()
        keys = ["timestamp", "activity_desc", "mood_tags",
                "mood_intensity", "energy_level", "notes"]
        if role == Qt.DisplayRole:
            val = row.get(keys[col], "")
            if col == 2:
                try:
                    import json
                    tags = json.loads(val) if isinstance(val, str) else val
                    return "、".join(tags) if tags else ""
                except Exception:
                    return str(val)
            return str(val) if val is not None else ""
        if role == Qt.ForegroundRole and col in (3, 4):
            try:
                v = int(row.get(keys[col], 0))
                if v >= 4:
                    return QColor("#ff9944")
                elif v <= 2:
                    return QColor("#888")
            except Exception:
                pass
        return None


# ═══════════════════════════════════════════════════════════
# 设备日志表格模型
# ═══════════════════════════════════════════════════════════

_DEVICE_COLS = ["时间", "进程", "窗口标题", "活跃时长"]


class _DeviceLogModel(QAbstractTableModel):
    def __init__(self):
        super().__init__()
        self._rows = []
        self._search = ""

    def set_search(self, keyword):
        self._search = keyword.strip().lower()
        self._reload()

    def _reload(self):
        rows = []
        try:
            conn = get_conn("slices")
            if self._search:
                rows = conn.execute(
                    """SELECT timestamp, process_name, window_title, duration_seconds
                       FROM device_usage_logs
                       WHERE process_name LIKE ? OR window_title LIKE ?
                       ORDER BY timestamp DESC LIMIT 200""",
                    (f"%{self._search}%", f"%{self._search}%"),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT timestamp, process_name, window_title, duration_seconds
                       FROM device_usage_logs
                       ORDER BY timestamp DESC LIMIT 200"""
                ).fetchall()
            conn.close()
            rows = [dict(r) for r in rows]
        except Exception:
            rows = []
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return len(_DEVICE_COLS)

    def headerData(self, section, orientation, role):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return _DEVICE_COLS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        col = index.column()
        keys = ["timestamp", "process_name", "window_title", "duration_seconds"]
        if role == Qt.DisplayRole:
            val = row.get(keys[col], "")
            if col == 3:
                sec = int(val or 0)
                if sec >= 3600:
                    return f"{sec // 3600}h{sec % 3600 // 60}m"
                elif sec >= 60:
                    return f"{sec // 60}min"
                else:
                    return f"{sec}s"
            return str(val)[:80] if val else ""
        return None


# ═══════════════════════════════════════════════════════════
# 年度热力图（GitHub 风格）
# ═══════════════════════════════════════════════════════════

class YearHeatMap(QWidget):
    """QPainter 手绘年度热力图 — GitHub 风格，窗口缩放自适应"""

    MIN_CELL = 10
    MAX_CELL = 22
    LABEL_W = 36

    def __init__(self):
        super().__init__()
        self._data = {}
        self._max_count = 1
        self._today = None
        self._cells = []            # [(date_str, count, col, row), ...]
        self._month_labels = []     # [(col, "M月"), ...]
        self._cell = 14             # 当前单元格像素
        self._gap = 3
        self._header_h = 22
        self.setMouseTracking(True)
        self._load_data()
        self._precompute()

    # ── 数据 ──

    def _load_data(self):
        try:
            conn = get_conn("slices")
            year = datetime.now().year
            rows = conn.execute(
                """SELECT date(timestamp) as d, COUNT(*) as cnt
                   FROM slices WHERE date(timestamp) >= ? AND date(timestamp) <= ?
                   GROUP BY d""",
                (f"{year}-01-01", f"{year}-12-31"),
            ).fetchall()
            conn.close()
            self._data = {r["d"]: r["cnt"] for r in rows}
            self._max_count = max(self._data.values()) if self._data else 1
        except Exception:
            self._data = {}
            self._max_count = 1
        self._precompute()
        self.update()

    def _cell_color(self, count):
        if count == 0:
            return QColor("#ebedf0")
        ratio = min(count / max(self._max_count, 1), 1.0)
        if ratio < 0.25:
            return QColor("#0e4429")
        elif ratio < 0.5:
            return QColor("#006d32")
        elif ratio < 0.75:
            return QColor("#26a641")
        else:
            return QColor("#39d353")

    def _precompute(self):
        """预计算所有日期的网格坐标（col/row 而非像素）"""
        self._today = datetime.now().date()
        year = self._today.year
        year_start = datetime(year, 1, 1).date()
        offset = (year_start.weekday() + 1) % 7
        grid_start = year_start - timedelta(days=offset)

        self._cells = []
        for day_offset in range(371):
            d = grid_start + timedelta(days=day_offset)
            if d.year > year:
                break
            if d.year < year:
                continue
            delta_days = (d - grid_start).days
            col = delta_days // 7
            row = delta_days % 7
            date_str = d.strftime("%Y-%m-%d")
            cnt = self._data.get(date_str, 0)
            self._cells.append((date_str, cnt, col, row))

        self._month_labels = []
        for m in range(1, 13):
            d = datetime(year, m, 1).date()
            delta_days = (d - grid_start).days
            self._month_labels.append((delta_days // 7, f"{m}月"))

    # ── 自适应尺寸 ──

    def _calc_cell(self):
        """根据当前宽度计算单元格大小"""
        if not self._cells:
            return
        max_col = max(c[2] for c in self._cells)  # 列坐标，约 52
        avail = self.width() - self.LABEL_W - 8
        self._cell = max(self.MIN_CELL, min(self.MAX_CELL,
                         (avail - max_col * 3) // (max_col + 1)))
        self._gap = max(2, self._cell // 5)
        self._header_h = int(self._cell * 1.55)

    # ── 绘制 ──

    def paintEvent(self, event):
        w, h = self.width(), self.height()
        if w < 10 or h < 10 or not self._cells:
            return

        self._calc_cell()
        cell, gap = self._cell, self._gap
        ox = self.LABEL_W
        oy = self._header_h + 4

        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#f5f7fa"))

        font_size = max(9, int(cell * 0.68))
        font = QFont("Microsoft YaHei", font_size)
        p.setFont(font)

        # 月份标签
        p.setPen(QColor("#888"))
        last_col = -100
        for col, mlabel in self._month_labels:
            if col - last_col >= 3:
                x = ox + col * (cell + gap)
                p.drawText(QRect(x, 0, cell * 4, self._header_h),
                           Qt.AlignLeft | Qt.AlignBottom, mlabel)
                last_col = col

        # 周标签
        small_font = QFont("Microsoft YaHei", max(8, font_size - 1))
        p.setFont(small_font)
        for i, label in enumerate(["", "一", "", "三", "", "五", ""]):
            if label:
                y = oy + i * (cell + gap)
                p.drawText(QRect(0, y, self.LABEL_W - 4, cell),
                           Qt.AlignRight | Qt.AlignVCenter, label)

        # 方格矩阵
        p.setRenderHint(QPainter.Antialiasing)
        today_str = self._today.strftime("%Y-%m-%d")
        for date_str, cnt, col, row in self._cells:
            x = ox + col * (cell + gap)
            y = oy + row * (cell + gap)
            if x + cell > w:
                continue

            color = self._cell_color(cnt)
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(color))
            radius = max(1, cell // 6)
            p.drawRoundedRect(QRect(x, y, cell, cell), radius, radius)

            if date_str == today_str:
                p.setPen(QPen(QColor("#4A9EFF"), max(1.2, cell / 10)))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(QRect(x, y, cell, cell), radius, radius)

        # 图例
        ly = oy + 7 * (cell + gap) + gap * 4
        legend_font = QFont("Microsoft YaHei", max(8, font_size - 1))
        p.setFont(legend_font)
        lr = max(8, cell * 4 // 5)  # 图例方格大小
        p.setPen(QColor("#888"))
        p.drawText(QRect(ox, ly, 22, lr), Qt.AlignVCenter, "少")
        lx = ox + 22
        for level in range(5):
            dc = 0 if level == 0 else int(self._max_count * level / 4)
            cc = self._cell_color(dc)
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(cc))
            p.drawRoundedRect(QRect(lx, ly, lr, lr), 2, 2)
            lx += lr + 2
        p.setPen(QColor("#888"))
        p.drawText(QRect(lx + 3, ly, 22, lr), Qt.AlignVCenter, "多")

        p.end()

    # ── 悬停 ──

    def mouseMoveEvent(self, event):
        if not self._cells:
            return
        ox = self.LABEL_W
        oy = self._header_h + 4
        cell, gap = self._cell, self._gap
        mx, my = event.x(), event.y()
        col = int((mx - ox) / (cell + gap))
        row = int((my - oy) / (cell + gap))
        if col < 0 or row < 0 or row > 6:
            self.setToolTip("")
            return
        for date_str, cnt, cc, rr in self._cells:
            if cc == col and rr == row:
                self.setToolTip(f"{date_str} - {cnt} 次记录")
                return
        self.setToolTip("")


# ═══════════════════════════════════════════════════════════
# Tab0：时间切片主组件
# ═══════════════════════════════════════════════════════════

class TimeSliceTab(QWidget):
    """Tab0：时间切片 — 快速记录 + 历史 + 设备日志 + 热力图"""

    def __init__(self):
        super().__init__()
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 顶部工具栏
        toolbar = QWidget()
        toolbar.setFixedHeight(48)
        toolbar.setStyleSheet("background: #ffffff; border-bottom: 1px solid #e8eaed;")
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(12, 6, 12, 6)
        tb_layout.setSpacing(8)

        record_btn = QPushButton("✚ 快速记录")
        record_btn.setToolTip("记录当前的情绪、精力和活动状态")
        record_btn.setFixedHeight(36)
        record_btn.setStyleSheet("""
            QPushButton {
                background: #5A9EBF; color: #fff; border: none;
                border-radius: 4px; padding: 6px 16px; font-size: 15px;
            }
            QPushButton:hover { background: #1177bb; }
        """)
        record_btn.clicked.connect(self._open_quick_record)
        tb_layout.addWidget(record_btn)

        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet("background: #3c3c3c; border: none;")
        sep.setFixedWidth(1)
        tb_layout.addWidget(sep)

        # 视图切换按钮组
        self._btn_group = QButtonGroup(self)
        self._btn_group.setExclusive(True)
        for i, label in enumerate(["切片历史", "设备日志", "热力图"]):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setFixedHeight(30)
            btn.setStyleSheet("""
                QPushButton {
                    background: transparent; color: #666; border: none;
                    border-radius: 4px; padding: 4px 14px; font-size: 14px;
                }
                QPushButton:hover { color: #333; }
                QPushButton:checked { background: #e6f0fa; color: #5A9EBF; }
            """)
            btn.clicked.connect(lambda checked, idx=i: self._stack.setCurrentIndex(idx))
            btn.setChecked(i == 0)
            self._btn_group.addButton(btn, i)
            tb_layout.addWidget(btn)

        tb_layout.addStretch()

        self._search_input = QLineEdit()
        self._search_input.setFixedWidth(180)
        self._search_input.setFixedHeight(28)
        self._search_input.setPlaceholderText("搜索...")
        self._search_input.setStyleSheet("""
            QLineEdit {
                background: #ffffff; color: #333;
                border: 1px solid #d9d9d9; border-radius: 4px;
                padding: 2px 8px; font-size: 14px;
            }
            QLineEdit:focus { border-color: #5A9EBF; }
        """)
        self._search_input.textChanged.connect(self._on_search)
        tb_layout.addWidget(self._search_input)

        layout.addWidget(toolbar)

        # QStackedWidget
        self._stack = QStackedWidget()

        self._slice_model = _SliceTableModel()
        self._slice_table = self._make_table(
            self._slice_model, [140, 160, 140, 50, 50, 200])
        self._stack.addWidget(self._slice_table)

        self._device_model = _DeviceLogModel()
        self._device_table = self._make_table(
            self._device_model, [140, 120, 280, 80])
        self._stack.addWidget(self._device_table)

        self._heatmap = YearHeatMap()
        self._stack.addWidget(self._heatmap)

        layout.addWidget(self._stack)

        # 状态栏
        self._status_label = QLabel("")
        self._status_label.setFixedHeight(24)
        self._status_label.setStyleSheet(
            "color: #888; font-size: 13px; background: #ffffff; "
            "border-top: 1px solid #e8eaed; padding: 2px 12px;")
        layout.addWidget(self._status_label)

        self._slice_model._reload()
        self._device_model._reload()
        self._update_status()

    def _make_table(self, model, widths):
        table = QTableView()
        table.setModel(model)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(38)  # Cherry 风格行高
        header = table.horizontalHeader()
        for i, w in enumerate(widths):
            header.setSectionResizeMode(i, QHeaderView.Interactive)
            table.setColumnWidth(i, w)
        header.setStretchLastSection(True)
        return table

    def _open_quick_record(self):
        dlg = QuickRecordDialog(self)
        if dlg.exec_() == QDialog.Accepted:
            self._slice_model._reload()
            self._heatmap._load_data()
            self._update_status()

    def _on_search(self, keyword):
        idx = self._stack.currentIndex()
        if idx == 0:
            self._slice_model.set_search(keyword)
        elif idx == 1:
            self._device_model.set_search(keyword)
        self._update_status()

    def _update_status(self):
        idx = self._stack.currentIndex()
        kw = self._search_input.text().strip()
        if idx == 0:
            cnt = self._slice_model.rowCount()
            self._status_label.setText(
                f"  共 {cnt} 条" + (f"（搜索: {kw}）" if kw else ""))
        elif idx == 1:
            cnt = self._device_model.rowCount()
            self._status_label.setText(
                f"  共 {cnt} 条" + (f"（搜索: {kw}）" if kw else ""))
        elif idx == 2:
            year = (self._heatmap._today or datetime.now().date()).year
            total = sum(self._heatmap._data.values())
            today_str = (self._heatmap._today or datetime.now().date()).strftime("%Y-%m-%d")
            today_cnt = self._heatmap._data.get(today_str, 0)
            self._status_label.setText(
                f"  {year}年 · {total} 次记录 · 今日 {today_cnt} 次")
