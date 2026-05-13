# -*- coding: utf-8 -*-
"""
Tab2：PC智能任务助理 — 任务CRUD + 贪心排程 + 甘特图 + 精力匹配
Phase 4 完整实现
"""
import math
from datetime import datetime, timedelta, date

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableView, QHeaderView, QLineEdit, QDialog, QComboBox,
    QTextEdit, QSlider, QAbstractItemView, QFrame, QButtonGroup,
    QMessageBox, QFormLayout, QSplitter,
)
from PyQt5.QtCore import Qt, QAbstractTableModel, QModelIndex, QRect, QTimer
from PyQt5.QtGui import (
    QPainter, QColor, QBrush, QPen, QFont, QFontMetrics,
)

from database import get_conn
from widgets.gantt_chart import GanttChart

_PRIORITY_LABELS = {1: "P1 紧急", 2: "P2 高", 3: "P3 中", 4: "P4 低", 5: "P5 闲"}
_STATUS_LABELS = {"pending": "待处理", "done": "已完成"}


# ═══════════════════════════════════════════════════════════
# 任务编辑弹窗
# ═══════════════════════════════════════════════════════════

class TaskDialog(QDialog):
    """新增/编辑任务弹窗"""

    def __init__(self, parent=None, task=None):
        super().__init__(parent)
        self._task = task  # None=新增, dict=编辑
        self._result = None
        self.setWindowTitle("新建任务" if task is None else "编辑任务")
        self.setMinimumWidth(400)
        self.setStyleSheet("""
            QDialog { background: #ffffff; }
            QLabel { color: #333; font-size: 14px; border: none; }
            QLineEdit, QTextEdit, QComboBox {
                background: #ffffff; color: #333;
                border: 1px solid #d9d9d9; border-radius: 4px;
                padding: 6px 10px; font-size: 14px;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background: #ffffff; color: #333; selection-background-color: #e6f7ff;
            }
            QSlider::groove:horizontal {
                height: 6px; background: #e0e0e0; border-radius: 3px;
            }
            QSlider::handle:horizontal {
                width: 14px; height: 14px; margin: -5px 0;
                background: #5A9EBF; border-radius: 7px;
            }
            QPushButton {
                background: #5A9EBF; color: #fff; border: none;
                border-radius: 4px; padding: 8px 20px; font-size: 14px;
            }
            QPushButton:hover { background: #6bb0d1; }
            QPushButton#cancelBtn { background: #f0f2f5; color: #666; }
            QPushButton#cancelBtn:hover { background: #e0e2e5; }
        """)

        layout = QFormLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        # 标题
        self._title_input = QLineEdit()
        self._title_input.setPlaceholderText("任务标题")
        layout.addRow("标题", self._title_input)

        # 优先级
        prio_row = QHBoxLayout()
        self._priority_slider = QSlider(Qt.Horizontal)
        self._priority_slider.setRange(1, 5)
        self._priority_slider.setValue(3)
        self._priority_slider.setFixedWidth(200)
        prio_row.addWidget(self._priority_slider)
        self._priority_label = QLabel("P3 中")
        self._priority_label.setStyleSheet("color: #4A9EFF; font-weight: bold;")
        self._priority_slider.valueChanged.connect(
            lambda v: self._priority_label.setText(_PRIORITY_LABELS.get(v, str(v))))
        prio_row.addWidget(self._priority_label)
        prio_row.addStretch()
        layout.addRow("优先级", prio_row)

        # 预估时间
        time_row = QHBoxLayout()
        self._est_input = QLineEdit("30")
        self._est_input.setFixedWidth(80)
        self._est_input.setPlaceholderText("分钟")
        time_row.addWidget(self._est_input)
        time_row.addWidget(QLabel("分钟"))
        time_row.addStretch()
        layout.addRow("预估耗时", time_row)

        # 截止日期
        self._deadline_input = QLineEdit()
        self._deadline_input.setPlaceholderText("YYYY-MM-DD HH:MM（可留空）")
        layout.addRow("截止日期", self._deadline_input)

        # 状态
        self._status_combo = QComboBox()
        self._status_combo.addItems(["待处理", "已完成"])
        layout.addRow("状态", self._status_combo)

        # 重复
        self._recurrence_combo = QComboBox()
        self._recurrence_combo.addItems(["不重复", "每天", "每周"])
        layout.addRow("重复", self._recurrence_combo)

        # 按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("取消")
        cancel_btn.setObjectName("cancelBtn")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(save_btn)
        layout.addRow(btn_row)

        # 编辑模式：填充现有数据
        if task:
            self._title_input.setText(task.get("title", ""))
            self._priority_slider.setValue(task.get("priority", 3))
            self._est_input.setText(str(task.get("estimated_minutes", 30)))
            self._deadline_input.setText(task.get("deadline") or "")
            self._status_combo.setCurrentIndex(0 if task.get("status") == "pending" else 1)
            rec_map = {"none": 0, "daily": 1, "weekly": 2}
            self._recurrence_combo.setCurrentIndex(rec_map.get(task.get("recurrence", "none"), 0))

    def _save(self):
        title = self._title_input.text().strip()
        if not title:
            return
        try:
            est = int(self._est_input.text().strip())
        except ValueError:
            est = 30
        deadline = self._deadline_input.text().strip() or None
        status = "pending" if self._status_combo.currentIndex() == 0 else "done"
        rec_map = {0: "none", 1: "daily", 2: "weekly"}
        recurrence = rec_map[self._recurrence_combo.currentIndex()]

        try:
            conn = get_conn("tasks")
            if self._task:  # 编辑
                conn.execute(
                    """UPDATE tasks SET title=?, priority=?, estimated_minutes=?,
                       deadline=?, status=?, recurrence=?
                       WHERE id=?""",
                    (title, self._priority_slider.value(), est,
                     deadline, status, recurrence, self._task["id"]),
                )
            else:  # 新增
                conn.execute(
                    """INSERT INTO tasks (title, priority, estimated_minutes,
                       deadline, status, recurrence)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (title, self._priority_slider.value(), est,
                     deadline, status, recurrence),
                )
            conn.commit()
            conn.close()
            self.accept()
        except Exception as e:
            print(f"[Task] 保存失败: {e}")
            self.reject()


# ═══════════════════════════════════════════════════════════
# 任务表格模型
# ═══════════════════════════════════════════════════════════

_TASK_COLS = ["标题", "优先级", "预估", "截止", "状态", "重复"]


class _TaskTableModel(QAbstractTableModel):
    def __init__(self):
        super().__init__()
        self._rows = []
        self._filter = "all"  # all / pending / done

    def set_filter(self, status):
        self._filter = status
        self._reload()

    def _reload(self):
        rows = []
        try:
            conn = get_conn("tasks")
            if self._filter == "pending":
                rows = conn.execute(
                    "SELECT * FROM tasks WHERE status='pending' ORDER BY priority, deadline"
                ).fetchall()
            elif self._filter == "done":
                rows = conn.execute(
                    "SELECT * FROM tasks WHERE status='done' ORDER BY created_at DESC LIMIT 50"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM tasks ORDER BY status, priority, deadline"
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
        return len(_TASK_COLS)

    def headerData(self, section, orientation, role):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return _TASK_COLS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        col = index.column()
        keys = ["title", "priority", "estimated_minutes", "deadline", "status", "recurrence"]

        if role == Qt.DisplayRole:
            val = row.get(keys[col], "")
            if col == 1:
                return f"P{val}"
            if col == 2:
                return f"{val}min"
            if col == 4:
                return _STATUS_LABELS.get(val, val)
            if col == 5:
                rec_map = {"none": "不重复", "daily": "每天", "weekly": "每周"}
                return rec_map.get(val, val)
            return str(val) if val else ""

        if role == Qt.ForegroundRole:
            if col == 1:
                p = row.get("priority", 3)
                if p <= 1:
                    return QColor("#ff4444")
                elif p <= 2:
                    return QColor("#ff9944")
            if col == 4:
                if row.get("status") == "done":
                    return QColor("#4aff4a")
            if col == 3 and row.get("deadline"):
                try:
                    dl = datetime.fromisoformat(row["deadline"])
                    if dl < datetime.now():
                        return QColor("#ff4444")
                except Exception:
                    pass

        if role == Qt.DecorationRole and col == 0:
            if row.get("status") == "done":
                return QColor("#4aff4a")

        return None

    def get_row(self, row_idx):
        if 0 <= row_idx < len(self._rows):
            return self._rows[row_idx]
        return None


# ═══════════════════════════════════════════════════════════
# 简易甘特图（周视图）
# ═══════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════
# 贪心排程器（精简版，复用原 scheduler 逻辑）
# ═══════════════════════════════════════════════════════════

def _time_to_min(time_str):
    parts = time_str.strip().split(":")
    return int(parts[0]) * 60 + int(parts[1])


def _min_to_time(m):
    return f"{m // 60:02d}:{m % 60:02d}"


def _effective_priority(task, now=None):
    if now is None:
        now = datetime.now()
    base = task.get("priority", 3)
    dl_str = task.get("deadline")
    if not dl_str:
        return base
    try:
        dl = datetime.fromisoformat(dl_str)
    except Exception:
        return base
    delta = dl - now
    if delta.total_seconds() < 0:
        return 0
    elif delta < timedelta(hours=2):
        return 0
    elif delta < timedelta(hours=24):
        return 1
    elif delta < timedelta(days=3):
        return max(0, base - 1)
    return base


def run_scheduler():
    """贪心排程：从 tasks + availability 生成 schedule_results，写入数据库。
    返回 (scheduled_count, unscheduled_count)
    """
    conn = get_conn("tasks")
    tasks = [dict(r) for r in conn.execute(
        "SELECT * FROM tasks WHERE status='pending'").fetchall()]
    avails = [dict(r) for r in conn.execute(
        "SELECT * FROM availability ORDER BY start_time").fetchall()]
    conn.close()

    if not tasks or not avails:
        return 0, 0

    # 按优先级排序
    sorted_tasks = sorted(tasks, key=lambda t: (_effective_priority(t), t.get("deadline") or "9999"))
    occupied = {a["id"]: [] for a in avails}

    scheduled, unscheduled = [], []

    for task in sorted_tasks:
        placed = False
        task_min = task["estimated_minutes"]
        for avail in avails:
            av_start = _time_to_min(avail["start_time"])
            av_end = _time_to_min(avail["end_time"])

            # 找空闲区间
            slots = sorted(occupied[avail["id"]], key=lambda x: x[0])
            cursor = av_start
            gaps = []
            for s, e in slots:
                if s > cursor:
                    gaps.append((cursor, s))
                cursor = max(cursor, e)
            if cursor < av_end:
                gaps.append((cursor, av_end))

            for gs, ge in gaps:
                if ge - gs >= task_min:
                    scheduled.append({
                        "task": task,
                        "start": _min_to_time(gs),
                        "end": _min_to_time(gs + task_min),
                        "slot_label": avail["label"],
                        "avail_id": avail["id"],
                    })
                    occupied[avail["id"]].append((gs, gs + task_min))
                    placed = True
                    break
            if placed:
                break
        if not placed:
            unscheduled.append(task)

    # 写入 schedule_results
    conn = get_conn("tasks")
    # 清除旧排程
    conn.execute("DELETE FROM schedule_results WHERE is_manual=0")
    today_str = date.today().strftime("%Y-%m-%d")
    for s in scheduled:
        conn.execute(
            """INSERT INTO schedule_results
               (task_id, scheduled_date, start_time, end_time, slot_label, is_manual)
               VALUES (?, ?, ?, ?, ?, 0)""",
            (s["task"]["id"], today_str, s["start"], s["end"], s["slot_label"]),
        )
    conn.commit()
    conn.close()
    return len(scheduled), len(unscheduled)


# ═══════════════════════════════════════════════════════════
# 任务助理 Tab 主组件
# ═══════════════════════════════════════════════════════════

class TaskTab(QWidget):
    """Tab2：任务助理 — CRUD + 贪心排程 + 甘特图"""

    def __init__(self):
        super().__init__()
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── 工具栏 ──
        toolbar = QWidget()
        toolbar.setFixedHeight(48)
        toolbar.setStyleSheet("background: #ffffff; border-bottom: 1px solid #e8eaed;")
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(12, 6, 12, 6)
        tb_layout.setSpacing(8)

        add_btn = QPushButton("✚ 新建")
        add_btn.setFixedHeight(34)
        add_btn.setStyleSheet("""
            QPushButton {
                background: #5A9EBF; color: #fff; border: none;
                border-radius: 4px; padding: 6px 14px; font-size: 14px;
            }
            QPushButton:hover { background: #6bb0d1; }
        """)
        add_btn.clicked.connect(self._add_task)
        tb_layout.addWidget(add_btn)

        self._edit_btn = QPushButton("✎ 编辑")
        self._edit_btn.setFixedHeight(34)
        self._edit_btn.setEnabled(False)
        self._edit_btn.setStyleSheet("""
            QPushButton {
                background: #f0f2f5; color: #666; border: none;
                border-radius: 4px; padding: 6px 14px; font-size: 14px;
            }
            QPushButton:hover { background: #e0e2e5; }
            QPushButton:disabled { color: #bbb; }
        """)
        self._edit_btn.clicked.connect(self._edit_task)
        tb_layout.addWidget(self._edit_btn)

        self._delete_btn = QPushButton("✕ 删除")
        self._delete_btn.setFixedHeight(34)
        self._delete_btn.setEnabled(False)
        self._delete_btn.setStyleSheet("""
            QPushButton {
                background: #f0f2f5; color: #666; border: none;
                border-radius: 4px; padding: 6px 14px; font-size: 14px;
            }
            QPushButton:hover { background: #ffe0e0; color: #ff4d4f; }
            QPushButton:disabled { color: #bbb; }
        """)
        self._delete_btn.clicked.connect(self._delete_task)
        tb_layout.addWidget(self._delete_btn)

        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet("background: #e0e0e0; border: none;")
        sep.setFixedWidth(1)
        tb_layout.addWidget(sep)

        schedule_btn = QPushButton("⚡ 贪心排程")
        schedule_btn.setFixedHeight(34)
        schedule_btn.setStyleSheet("""
            QPushButton {
                background: #2d5a2d; color: #4aff4a; border: none;
                border-radius: 4px; padding: 6px 14px; font-size: 14px;
            }
            QPushButton:hover { background: #3a6a3a; }
        """)
        schedule_btn.clicked.connect(self._run_scheduler)
        tb_layout.addWidget(schedule_btn)

        tb_layout.addStretch()

        # 状态筛选
        filter_label = QLabel("筛选")
        filter_label.setStyleSheet("color: #888; font-size: 14px; border: none;")
        tb_layout.addWidget(filter_label)
        self._filter_combo = QComboBox()
        self._filter_combo.addItems(["全部", "待处理", "已完成"])
        self._filter_combo.setFixedWidth(90)
        self._filter_combo.setStyleSheet("""
            QComboBox {
                background: #ffffff; color: #333;
                border: 1px solid #d9d9d9; border-radius: 4px;
                padding: 4px 8px; font-size: 14px;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background: #ffffff; color: #333; selection-background-color: #e6f7ff;
            }
        """)
        self._filter_combo.currentIndexChanged.connect(self._on_filter)
        tb_layout.addWidget(self._filter_combo)

        layout.addWidget(toolbar)

        # ── QSplitter：上表格 / 下甘特图 ──
        self._splitter = QSplitter(Qt.Vertical)

        # 任务表格
        self._task_model = _TaskTableModel()
        self._task_table = self._make_table()
        self._task_table.selectionModel().selectionChanged.connect(self._on_selection)
        self._splitter.addWidget(self._task_table)

        # 甘特图
        self._gantt = GanttChart()
        self._splitter.addWidget(self._gantt)
        self._splitter.setSizes([320, 200])

        layout.addWidget(self._splitter)

        # ── 状态栏 ──
        self._status_label = QLabel("")
        self._status_label.setFixedHeight(24)
        self._status_label.setStyleSheet(
            "color: #888; font-size: 13px; background: #ffffff; "
            "border-top: 1px solid #e8eaed; padding: 2px 12px;")
        layout.addWidget(self._status_label)

        self._task_model._reload()
        self._update_status()
        self._gantt.load_week()

    def _make_table(self):
        table = QTableView()
        table.setModel(self._task_model)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(38)
        header = table.horizontalHeader()
        widths = [220, 60, 60, 160, 70, 60]
        for i, w in enumerate(widths):
            header.setSectionResizeMode(i, QHeaderView.Interactive)
            table.setColumnWidth(i, w)
        header.setStretchLastSection(True)
        return table

    # ── CRUD ──

    def _add_task(self):
        dlg = TaskDialog(self)
        if dlg.exec_() == QDialog.Accepted:
            self._task_model._reload()
            self._update_status()

    def _edit_task(self):
        row = self._task_table.currentIndex().row()
        task = self._task_model.get_row(row)
        if not task:
            return
        dlg = TaskDialog(self, task)
        if dlg.exec_() == QDialog.Accepted:
            self._task_model._reload()
            self._load_gantt()
            self._update_status()

    def _delete_task(self):
        row = self._task_table.currentIndex().row()
        task = self._task_model.get_row(row)
        if not task:
            return
        reply = QMessageBox.question(
            self, "确认删除", f"确定删除「{task['title']}」？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        try:
            conn = get_conn("tasks")
            conn.execute("DELETE FROM tasks WHERE id=?", (task["id"],))
            conn.execute("DELETE FROM schedule_results WHERE task_id=?", (task["id"],))
            conn.commit()
            conn.close()
            self._task_model._reload()
            self._load_gantt()
            self._update_status()
        except Exception as e:
            print(f"[Task] 删除失败: {e}")

    def _on_selection(self):
        has_selection = self._task_table.selectionModel().hasSelection()
        self._edit_btn.setEnabled(has_selection)
        self._delete_btn.setEnabled(has_selection)

    def _on_filter(self, idx):
        filter_map = {0: "all", 1: "pending", 2: "done"}
        self._task_model.set_filter(filter_map.get(idx, "all"))
        self._update_status()

    def _run_scheduler(self):
        cnt, un = run_scheduler()
        self._gantt.load_week()
        self._update_status()
        msg = f"排程完成：{cnt} 个任务已安排"
        if un:
            msg += f"，{un} 个未排入"
        self._status_label.setText(f"  {msg}")

    def _load_gantt(self):
        self._gantt.load_week()

    def _update_status(self):
        total = self._task_model.rowCount()
        filt = self._filter_combo.currentText()
        self._status_label.setText(
            f"  共 {total} 个任务" + (f"（{filt}）" if filt != "全部" else ""))
