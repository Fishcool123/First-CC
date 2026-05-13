"""
database.py — 统一 SQLite 连接管理
管理两个独立数据库：task_assistant.db（任务）+ slices.db（切片）
跨库用 ATTACH，首次启动自动从旧目录迁移数据
依赖：Python 标准库 sqlite3 / json / shutil / os
"""
import json, os, shutil, sqlite3
from datetime import date, timedelta
from pathlib import Path

# 数据库路径（相对于本文件）
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
TASKS_DB = DATA_DIR / "task_assistant.db"
SLICES_DB = DATA_DIR / "slices.db"

# 旧项目路径（用于首次迁移）
OLD_TASKS_DIR = BASE_DIR.parent / "PC智能任务助理"
OLD_SLICES_DIR = BASE_DIR.parent / "时间切片系统"


# ══════════════════════════════════════════════════════════
# 初始化 & 迁移
# ══════════════════════════════════════════════════════════

def _migrate_db(src_paths, dst_path, label):
    """尝试从多个候选源路径复制数据库到目标路径。返回是否成功。"""
    if dst_path.exists():
        return False  # 已存在，无需迁移
    for src in src_paths:
        if src.exists():
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst_path)
            print(f"[迁移] {label}: {src.name} → {dst_path.name}")
            return True
    return False


def init_db():
    """初始化两个数据库：建表 + 尝试从旧目录迁移 + 预置默认数据"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # 从旧目录迁移（兼容 data.db 和 task_assistant.db 两个文件名）
    _migrate_db(
        [OLD_TASKS_DIR / "data.db", OLD_TASKS_DIR / "task_assistant.db"],
        TASKS_DB, "任务数据库"
    )
    _migrate_db(
        [OLD_SLICES_DIR / "slices.db"],
        SLICES_DB, "切片数据库"
    )

    # 建表（幂等）
    _create_tasks_tables()
    _create_slices_tables()

    # 预置默认数据
    _seed_tasks_defaults()
    _seed_slices_defaults()


# ══════════════════════════════════════════════════════════
# 连接工厂
# ══════════════════════════════════════════════════════════

def get_conn(db_name="tasks"):
    """获取数据库连接，启用 WAL 模式。db_name: 'tasks' | 'slices'"""
    path = TASKS_DB if db_name == "tasks" else SLICES_DB
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    if db_name == "slices":
        conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ══════════════════════════════════════════════════════════
# 建表：任务侧（tasks / availability / schedule_results）
# ══════════════════════════════════════════════════════════

def _create_tasks_tables():
    conn = get_conn("tasks")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS tasks (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            title            TEXT    NOT NULL,
            priority         INTEGER DEFAULT 3,
            estimated_minutes INTEGER NOT NULL,
            deadline         TEXT,
            status           TEXT    DEFAULT 'pending',
            sort_order       REAL    DEFAULT 0,
            created_at       TEXT    DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS availability (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            label      TEXT    NOT NULL,
            start_time TEXT    NOT NULL,
            end_time   TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS schedule_results (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id         INTEGER NOT NULL,
            scheduled_date  TEXT    NOT NULL,
            start_time      TEXT    NOT NULL,
            end_time        TEXT    NOT NULL,
            slot_label      TEXT,
            is_manual       INTEGER DEFAULT 0,
            created_at      TEXT    DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_schedule_date
            ON schedule_results(scheduled_date);
    """)
    conn.commit()
    # 兼容：添加重复任务字段
    try:
        conn.execute("ALTER TABLE tasks ADD COLUMN recurrence TEXT DEFAULT 'none'")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE tasks ADD COLUMN last_generated_date TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE tasks ADD COLUMN parent_recurring_id INTEGER")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()


def _create_slices_tables():
    conn = get_conn("slices")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS slices (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp       TEXT    NOT NULL,
            activity_desc   TEXT    NOT NULL,
            mood_tags       TEXT    DEFAULT '[]',
            mood_intensity  INTEGER DEFAULT 3,
            energy_level    INTEGER DEFAULT 3,
            related_task_id INTEGER,
            notes           TEXT    DEFAULT '',
            created_at      TEXT    DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_slices_ts ON slices(timestamp);

        CREATE TABLE IF NOT EXISTS device_usage_logs (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp        TEXT    NOT NULL,
            window_title     TEXT    DEFAULT '',
            process_name     TEXT    DEFAULT '',
            duration_seconds INTEGER DEFAULT 0,
            created_at       TEXT    DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_device_ts ON device_usage_logs(timestamp);

        CREATE TABLE IF NOT EXISTS mood_tags (
            id    INTEGER PRIMARY KEY AUTOINCREMENT,
            name  TEXT    NOT NULL UNIQUE,
            color TEXT    DEFAULT '#6e6e73'
        );

        CREATE TABLE IF NOT EXISTS rules (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT    NOT NULL,
            description     TEXT    DEFAULT '',
            trigger_type    TEXT    NOT NULL,
            trigger_params  TEXT    NOT NULL DEFAULT '{}',
            action_type     TEXT    NOT NULL,
            action_params   TEXT    NOT NULL DEFAULT '{}',
            enabled         INTEGER DEFAULT 1,
            is_preset       INTEGER DEFAULT 0,
            created_at      TEXT    DEFAULT (datetime('now','localtime')),
            updated_at      TEXT    DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS energy_profile (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            period          TEXT    NOT NULL UNIQUE,
            avg_energy      REAL,
            sample_count    INTEGER DEFAULT 0,
            updated_at      TEXT    DEFAULT (datetime('now','localtime'))
        );
    """)
    # 兼容旧表：尝试添加 granularity 字段（第三阶段 #11 使用）
    try:
        conn.execute("ALTER TABLE slices ADD COLUMN granularity TEXT DEFAULT 'manual'")
    except sqlite3.OperationalError:
        pass  # 字段已存在
    # 兼容旧值：fine → manual
    try:
        conn.execute("UPDATE slices SET granularity = 'manual' WHERE granularity = 'fine'")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()


# ══════════════════════════════════════════════════════════
# 预置默认数据
# ══════════════════════════════════════════════════════════

def _seed_tasks_defaults():
    conn = get_conn("tasks")
    cnt = conn.execute("SELECT COUNT(*) FROM availability").fetchone()[0]
    if cnt == 0:
        conn.execute("INSERT INTO availability (label, start_time, end_time) VALUES (?, ?, ?)",
                     ("上午", "09:00", "12:00"))
        conn.execute("INSERT INTO availability (label, start_time, end_time) VALUES (?, ?, ?)",
                     ("下午", "14:00", "18:00"))
        conn.execute("INSERT INTO availability (label, start_time, end_time) VALUES (?, ?, ?)",
                     ("晚上", "20:00", "22:00"))
    task_cnt = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    if task_cnt == 0:
        conn.execute(
            "INSERT INTO tasks (title, priority, estimated_minutes, deadline) VALUES (?, ?, ?, ?)",
            ("示例任务：熟悉 PC智能任务助理", 1, 30, None)
        )
        conn.execute("UPDATE tasks SET sort_order = 1 WHERE id = 1")
    conn.commit()
    conn.close()


def _seed_slices_defaults():
    conn = get_conn("slices")
    cnt = conn.execute("SELECT COUNT(*) FROM mood_tags").fetchone()[0]
    if cnt == 0:
        tags = [
            ("焦虑", "#ff3b30"), ("平静", "#34c759"), ("兴奋", "#ff9500"),
            ("低落", "#8e8e93"), ("烦躁", "#ff2d55"), ("疲惫", "#af52de"),
            ("专注", "#007aff"), ("放松", "#5ac8fa"), ("其他", "#c7c7cc"),
        ]
        conn.executemany("INSERT INTO mood_tags (name, color) VALUES (?, ?)", tags)

    # 预设规则种子
    rule_cnt = conn.execute("SELECT COUNT(*) FROM rules").fetchone()[0]
    if rule_cnt == 0:
        preset_rules = [
            ("长时间未记录切片提醒", "slice_gap",
             json.dumps({"hours": 4}),
             "notify", json.dumps({"title": "该切一片了", "message": "你已经{hours}小时没记录切片了"})),
            ("设备连续使用超时提醒", "device_usage_duration",
             json.dumps({"process": "*", "minutes": 90}),
             "notify", json.dumps({"title": "休息提醒", "message": "你已连续使用{process}{minutes}分钟"})),
            ("每日屏幕时间超限", "device_usage_daily",
             json.dumps({"hours": 8}),
             "notify", json.dumps({"title": "屏幕时间提醒", "message": "今日屏幕使用已超过{hours}小时"})),
            ("任务即将截止提醒", "task_deadline_approaching",
             json.dumps({"hours": 1}),
             "notify", json.dumps({"title": "任务即将截止", "message": "「{task_name}」将在{time}后截止"})),
            ("任务多日未推进提醒", "task_stale",
             json.dumps({"days": 3}),
             "notify", json.dumps({"title": "任务提醒", "message": "「{task_name}」已经{days}天没有推进了"})),
            ("连续低精力提醒", "energy_drop",
             json.dumps({"count": 2, "threshold": 2}),
             "notify", json.dumps({"title": "精力提醒", "message": "你已连续{count}次标记低精力，建议休息"})),
            ("焦虑情绪上升提醒", "slice_mood_spike",
             json.dumps({"tag": "焦虑", "count": 3, "days": 7}),
             "prompt_slice", json.dumps({"title": "情绪关怀", "message": "最近{days}天内你标记了{count}次焦虑，要聊聊吗？"})),
            ("排程冲突检测", "schedule_conflict",
             json.dumps({}),
             "notify", json.dumps({"title": "排程冲突", "message": "同一时段手动分配已覆盖自动排程"})),
        ]
        conn.executemany(
            "INSERT INTO rules (name, trigger_type, trigger_params, action_type, action_params, is_preset) VALUES (?, ?, ?, ?, ?, 1)",
            preset_rules,
        )
    conn.commit()
    conn.close()


# ══════════════════════════════════════════════════════════
# 任务 CRUD（tasks 库）
# ══════════════════════════════════════════════════════════

def get_tasks(status_filter=None):
    conn = get_conn("tasks")
    if status_filter:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE status = ? ORDER BY sort_order, created_at",
            (status_filter,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM tasks ORDER BY sort_order, created_at"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_task(title, priority, estimated_minutes, deadline=None, recurrence=None, parent_recurring_id=None):
    conn = get_conn("tasks")
    cur = conn.execute(
        "INSERT INTO tasks (title, priority, estimated_minutes, deadline, recurrence, parent_recurring_id) VALUES (?, ?, ?, ?, ?, ?)",
        (title, priority, estimated_minutes, deadline, recurrence or "none", parent_recurring_id)
    )
    task_id = cur.lastrowid
    conn.execute("UPDATE tasks SET sort_order = ? WHERE id = ?", (float(task_id), task_id))
    conn.commit()
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    conn.close()
    return dict(row)


def update_task(task_id, **kwargs):
    allowed = {"title", "priority", "estimated_minutes", "deadline", "status", "sort_order"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return
    conn = get_conn("tasks")
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [task_id]
    conn.execute(f"UPDATE tasks SET {set_clause} WHERE id = ?", values)
    conn.commit()
    conn.close()


def delete_task(task_id):
    conn = get_conn("tasks")
    conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    conn.commit()
    conn.close()


# ══════════════════════════════════════════════════════════
# 可用时段 CRUD（tasks 库）
# ══════════════════════════════════════════════════════════

def get_availability():
    conn = get_conn("tasks")
    rows = conn.execute("SELECT * FROM availability ORDER BY start_time").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def save_availability(label, start_time, end_time):
    conn = get_conn("tasks")
    cur = conn.execute(
        "INSERT INTO availability (label, start_time, end_time) VALUES (?, ?, ?)",
        (label, start_time, end_time)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM availability WHERE id = ?", (cur.lastrowid,)).fetchone()
    conn.close()
    return dict(row)


def update_availability(avail_id, **kwargs):
    allowed = {"label", "start_time", "end_time"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return
    conn = get_conn("tasks")
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [avail_id]
    conn.execute(f"UPDATE availability SET {set_clause} WHERE id = ?", values)
    conn.commit()
    conn.close()


def delete_availability(avail_id):
    conn = get_conn("tasks")
    conn.execute("DELETE FROM availability WHERE id = ?", (avail_id,))
    conn.commit()
    conn.close()


# ══════════════════════════════════════════════════════════
# 排程 CRUD（tasks 库）
# ══════════════════════════════════════════════════════════

def get_schedule(date_str):
    conn = get_conn("tasks")
    rows = conn.execute("""
        SELECT sr.id, sr.task_id, sr.scheduled_date, sr.start_time, sr.end_time,
               sr.slot_label, sr.is_manual, sr.created_at,
               t.title, t.priority, t.estimated_minutes, t.deadline, t.status
        FROM schedule_results sr
        JOIN tasks t ON t.id = sr.task_id
        WHERE sr.scheduled_date = ?
        ORDER BY sr.start_time
    """, (date_str,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def save_schedule(date_str, scheduled_items):
    conn = get_conn("tasks")
    conn.execute("DELETE FROM schedule_results WHERE scheduled_date = ?", (date_str,))
    for item in scheduled_items:
        conn.execute(
            """INSERT INTO schedule_results
               (task_id, scheduled_date, start_time, end_time, slot_label, is_manual)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (item["task_id"], date_str, item["start_time"], item["end_time"],
             item.get("slot_label", ""), item.get("is_manual", 0))
        )
    conn.commit()
    conn.close()


def add_schedule_item(date_str, task_id, start_time, end_time, slot_label, is_manual=1):
    conn = get_conn("tasks")
    cur = conn.execute(
        """INSERT INTO schedule_results
           (task_id, scheduled_date, start_time, end_time, slot_label, is_manual)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (task_id, date_str, start_time, end_time, slot_label, is_manual)
    )
    conn.commit()
    rid = cur.lastrowid
    row = conn.execute("""
        SELECT sr.*, t.title, t.priority, t.estimated_minutes, t.deadline, t.status
        FROM schedule_results sr
        JOIN tasks t ON t.id = sr.task_id
        WHERE sr.id = ?
    """, (rid,)).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_schedule_item(item_id):
    conn = get_conn("tasks")
    conn.execute("DELETE FROM schedule_results WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()


# ══════════════════════════════════════════════════════════
# 切片 CRUD（slices 库）
# ══════════════════════════════════════════════════════════

def add_slice(timestamp, activity_desc, mood_tags=None, mood_intensity=3,
              energy_level=3, related_task_id=None, notes="", granularity="fine"):
    conn = get_conn("slices")
    tags_json = json.dumps(mood_tags or [], ensure_ascii=False)
    cur = conn.execute(
        """INSERT INTO slices (timestamp, activity_desc, mood_tags,
           mood_intensity, energy_level, related_task_id, notes, granularity)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (timestamp, activity_desc, tags_json, mood_intensity,
         energy_level, related_task_id, notes, granularity)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM slices WHERE id = ?", (cur.lastrowid,)).fetchone()
    conn.close()
    return dict(row)


def get_slices(date_str=None):
    conn = get_conn("slices")
    if date_str:
        rows = conn.execute(
            "SELECT * FROM slices WHERE timestamp LIKE ? ORDER BY timestamp DESC",
            (f"{date_str}%",)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM slices ORDER BY timestamp DESC LIMIT 200"
        ).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        d["mood_tags"] = json.loads(d["mood_tags"])
        result.append(d)
    return result


def update_slice(slice_id, **kwargs):
    """更新切片字段（第三阶段 #9 切片编辑）"""
    allowed = {"timestamp", "activity_desc", "mood_tags", "mood_intensity",
               "energy_level", "related_task_id", "notes", "granularity"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return
    # mood_tags 需要 JSON 序列化
    if "mood_tags" in updates:
        updates["mood_tags"] = json.dumps(updates["mood_tags"], ensure_ascii=False)
    conn = get_conn("slices")
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [slice_id]
    conn.execute(f"UPDATE slices SET {set_clause} WHERE id = ?", values)
    conn.commit()
    conn.close()


def delete_slice(slice_id):
    conn = get_conn("slices")
    conn.execute("DELETE FROM slices WHERE id = ?", (slice_id,))
    conn.commit()
    conn.close()


# ══════════════════════════════════════════════════════════
# 设备使用日志 CRUD（slices 库）
# ══════════════════════════════════════════════════════════

def add_device_log(timestamp, window_title, process_name, duration_seconds):
    conn = get_conn("slices")
    conn.execute(
        """INSERT INTO device_usage_logs (timestamp, window_title, process_name, duration_seconds)
           VALUES (?, ?, ?, ?)""",
        (timestamp, window_title, process_name, duration_seconds)
    )
    conn.commit()
    conn.close()


def get_device_logs(date_str):
    conn = get_conn("slices")
    rows = conn.execute(
        "SELECT * FROM device_usage_logs WHERE timestamp LIKE ? ORDER BY timestamp ASC",
        (f"{date_str}%",)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_device_logs_aggregated(date_str):
    conn = get_conn("slices")
    rows = conn.execute(
        """SELECT process_name, COUNT(*) AS active_minutes,
                  SUM(duration_seconds) AS total_seconds
           FROM device_usage_logs
           WHERE timestamp LIKE ?
           GROUP BY process_name
           ORDER BY total_seconds DESC""",
        (f"{date_str}%",)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_device_log_count():
    """设备日志总条数（第三阶段 #12 设置页展示）"""
    conn = get_conn("slices")
    row = conn.execute("SELECT COUNT(*) AS cnt FROM device_usage_logs").fetchone()
    conn.close()
    return row["cnt"]


def cleanup_old_device_logs(days=30):
    """清理 N 天前的设备日志（第三阶段 #12）"""
    conn = get_conn("slices")
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    cur = conn.execute(
        "DELETE FROM device_usage_logs WHERE timestamp < ?", (cutoff,)
    )
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    return deleted


# ══════════════════════════════════════════════════════════
# 热力图统计（slices 库）
# ══════════════════════════════════════════════════════════

def get_heatmap_data(start_date, end_date):
    conn = get_conn("slices")
    rows1 = conn.execute(
        """SELECT substr(timestamp, 1, 10) AS day, COUNT(*) AS cnt
           FROM slices
           WHERE timestamp >= ? AND timestamp < ?
           GROUP BY day""",
        (start_date, f"{end_date} 23:59:59")
    ).fetchall()
    rows2 = conn.execute(
        """SELECT DISTINCT substr(timestamp, 1, 10) AS day
           FROM device_usage_logs
           WHERE timestamp >= ? AND timestamp < ?
           GROUP BY day""",
        (start_date, f"{end_date} 23:59:59")
    ).fetchall()
    conn.close()

    device_days = {r["day"] for r in rows2}
    day_map = {r["day"]: r["cnt"] for r in rows1}

    result = []
    d = date.fromisoformat(start_date)
    ed = date.fromisoformat(end_date)
    while d <= ed:
        ds = d.isoformat()
        result.append({
            "date": ds,
            "slice_count": day_map.get(ds, 0),
            "has_device_data": ds in device_days,
        })
        d += timedelta(days=1)
    return result


# ══════════════════════════════════════════════════════════
# 跨库读取 PC助理任务（slices 侧 ATTACH tasks）
# ══════════════════════════════════════════════════════════

def get_assistant_tasks():
    if not TASKS_DB.exists():
        return []
    conn = get_conn("slices")
    try:
        conn.execute("ATTACH DATABASE ? AS assistant", (str(TASKS_DB),))
        rows = conn.execute(
            """SELECT id, title, priority, estimated_minutes, deadline, status
               FROM assistant.tasks
               WHERE status = 'pending'
               ORDER BY priority, created_at"""
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        try:
            conn.execute("DETACH assistant")
        except sqlite3.Error:
            pass
        conn.close()
    return [dict(r) for r in rows]


# ══════════════════════════════════════════════════════════
# 情绪标签（slices 库）
# ══════════════════════════════════════════════════════════

def get_mood_tags():
    conn = get_conn("slices")
    rows = conn.execute("SELECT * FROM mood_tags ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ══════════════════════════════════════════════════════════
# 精力曲线（slices 库）
# ══════════════════════════════════════════════════════════

def get_energy_profile():
    """返回三个时段的精力画像"""
    conn = get_conn("slices")
    rows = conn.execute("SELECT * FROM energy_profile ORDER BY id").fetchall()
    conn.close()
    profile = {r["period"]: dict(r) for r in rows}
    # 确保三个时段都存在
    for period in ("morning", "afternoon", "evening"):
        if period not in profile:
            profile[period] = {"period": period, "avg_energy": None, "sample_count": 0}
    return [profile[p] for p in ("morning", "afternoon", "evening")]


def refresh_energy_profile(days=30):
    """根据 slices 表中最近 N 天的数据重新计算精力画像"""
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    conn = get_conn("slices")
    for period, h_start, h_end in [
        ("morning", 5, 11),
        ("afternoon", 12, 17),
        ("evening", 18, 23),
    ]:
        # evening 包含 18-23 和 0-4
        if period == "evening":
            row = conn.execute(
                """SELECT AVG(energy_level) AS avg_e, COUNT(*) AS cnt
                   FROM slices
                   WHERE timestamp >= ? AND granularity != 'auto'
                   AND (CAST(substr(timestamp, 12, 2) AS INTEGER) >= 18
                        OR CAST(substr(timestamp, 12, 2) AS INTEGER) < 5)""",
                (cutoff,)
            ).fetchone()
        else:
            row = conn.execute(
                """SELECT AVG(energy_level) AS avg_e, COUNT(*) AS cnt
                   FROM slices
                   WHERE timestamp >= ? AND granularity != 'auto'
                   AND CAST(substr(timestamp, 12, 2) AS INTEGER) BETWEEN ? AND ?""",
                (cutoff, h_start, h_end)
            ).fetchone()
        avg = round(row["avg_e"], 2) if row["avg_e"] else None
        cnt = row["cnt"] or 0
        conn.execute(
            """INSERT INTO energy_profile (period, avg_energy, sample_count)
               VALUES (?, ?, ?)
               ON CONFLICT(period) DO UPDATE SET
                   avg_energy=excluded.avg_energy,
                   sample_count=excluded.sample_count,
                   updated_at=datetime('now','localtime')""",
            (period, avg, cnt)
        )
    conn.commit()
    conn.close()


def get_energy_trend(days=14):
    """返回最近 N 天每天的精力趋势"""
    conn = get_conn("slices")
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    # 按日期+时段分组
    rows = conn.execute(
        """SELECT substr(timestamp, 1, 10) AS day,
                  CASE
                    WHEN CAST(substr(timestamp, 12, 2) AS INTEGER) BETWEEN 5 AND 11 THEN 'morning'
                    WHEN CAST(substr(timestamp, 12, 2) AS INTEGER) BETWEEN 12 AND 17 THEN 'afternoon'
                    ELSE 'evening'
                  END AS period,
                  AVG(energy_level) AS avg_e
           FROM slices
           WHERE timestamp >= ? AND granularity != 'auto' AND energy_level IS NOT NULL
           GROUP BY day, period
           ORDER BY day""",
        (cutoff,)
    ).fetchall()
    conn.close()
    # 重组为按日期的 dict
    by_day = {}
    for r in rows:
        day = r["day"]
        if day not in by_day:
            by_day[day] = {"date": day}
        by_day[day][r["period"]] = round(r["avg_e"], 2)
    # 填充缺失日期
    result = []
    d = date.fromisoformat(cutoff)
    today = date.today()
    while d <= today:
        ds = d.isoformat()
        entry = by_day.get(ds, {"date": ds})
        result.append(entry)
        d += timedelta(days=1)
    return result


# ══════════════════════════════════════════════════════════
# 规则引擎 CRUD（slices 库）
# ══════════════════════════════════════════════════════════

def get_rules(enabled_only=False):
    conn = get_conn("slices")
    if enabled_only:
        rows = conn.execute("SELECT * FROM rules WHERE enabled = 1 ORDER BY id").fetchall()
    else:
        rows = conn.execute("SELECT * FROM rules ORDER BY id").fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        d["trigger_params"] = json.loads(d["trigger_params"])
        d["action_params"] = json.loads(d["action_params"])
        result.append(d)
    return result


def get_enabled_rules_by_trigger(trigger_type):
    conn = get_conn("slices")
    rows = conn.execute(
        "SELECT * FROM rules WHERE trigger_type = ? AND enabled = 1 ORDER BY id",
        (trigger_type,)
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        d["trigger_params"] = json.loads(d["trigger_params"])
        d["action_params"] = json.loads(d["action_params"])
        result.append(d)
    return result


def create_rule(name, trigger_type, trigger_params, action_type, action_params, is_preset=0):
    conn = get_conn("slices")
    cur = conn.execute(
        """INSERT INTO rules (name, trigger_type, trigger_params, action_type, action_params, is_preset)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (name, trigger_type, json.dumps(trigger_params, ensure_ascii=False),
         action_type, json.dumps(action_params, ensure_ascii=False), is_preset)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM rules WHERE id = ?", (cur.lastrowid,)).fetchone()
    conn.close()
    d = dict(row)
    d["trigger_params"] = json.loads(d["trigger_params"])
    d["action_params"] = json.loads(d["action_params"])
    return d


def update_rule(rule_id, **kwargs):
    allowed = {"name", "description", "trigger_type", "trigger_params",
               "action_type", "action_params", "enabled"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return
    # JSON 字段序列化
    if "trigger_params" in updates:
        updates["trigger_params"] = json.dumps(updates["trigger_params"], ensure_ascii=False)
    if "action_params" in updates:
        updates["action_params"] = json.dumps(updates["action_params"], ensure_ascii=False)
    conn = get_conn("slices")
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [rule_id]
    conn.execute(f"UPDATE rules SET {set_clause}, updated_at = datetime('now','localtime') WHERE id = ?", values)
    conn.commit()
    conn.close()


def toggle_rule(rule_id, enabled):
    conn = get_conn("slices")
    conn.execute(
        "UPDATE rules SET enabled = ?, updated_at = datetime('now','localtime') WHERE id = ?",
        (1 if enabled else 0, rule_id)
    )
    conn.commit()
    conn.close()


def delete_rule(rule_id):
    conn = get_conn("slices")
    row = conn.execute("SELECT is_preset FROM rules WHERE id = ?", (rule_id,)).fetchone()
    if row and row["is_preset"]:
        conn.close()
        return False  # 预设规则不可删除
    conn.execute("DELETE FROM rules WHERE id = ?", (rule_id,))
    conn.commit()
    conn.close()
    return True


# ══════════════════════════════════════════════════════════
# 自动切片生成（slices 库）
# ══════════════════════════════════════════════════════════

def get_device_logs_by_date(target_date):
    """获取指定日期的所有设备日志"""
    date_str = target_date.isoformat() if hasattr(target_date, 'isoformat') else str(target_date)
    conn = get_conn("slices")
    rows = conn.execute(
        "SELECT * FROM device_usage_logs WHERE timestamp LIKE ? ORDER BY timestamp ASC",
        (f"{date_str}%",)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_auto_slices_for_date(target_date):
    """删除指定日期的所有自动切片（幂等性）"""
    date_str = target_date.isoformat() if hasattr(target_date, 'isoformat') else str(target_date)
    conn = get_conn("slices")
    conn.execute("DELETE FROM slices WHERE timestamp LIKE ? AND granularity = 'auto'", (f"{date_str}%",))
    conn.commit()
    conn.close()


def get_auto_slices_count_for_date(target_date):
    """获取指定日期的自动切片数量"""
    date_str = target_date.isoformat() if hasattr(target_date, 'isoformat') else str(target_date)
    conn = get_conn("slices")
    row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM slices WHERE timestamp LIKE ? AND granularity = 'auto'",
        (f"{date_str}%",)
    ).fetchone()
    conn.close()
    return row["cnt"] if row else 0


# ══════════════════════════════════════════════════════════
# 重复任务（tasks 库）
# ══════════════════════════════════════════════════════════

def get_tasks_by_recurrence(recurrence_types):
    """获取指定重复类型的任务"""
    conn = get_conn("tasks")
    placeholders = ",".join("?" for _ in recurrence_types)
    rows = conn.execute(
        f"SELECT * FROM tasks WHERE recurrence IN ({placeholders}) AND status = 'pending'",
        recurrence_types
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def generate_recurring_tasks_today():
    """每日凌晨检查重复任务，生成今日实例"""
    today = date.today().isoformat()
    recurring_tasks = get_tasks_by_recurrence(["daily", "weekly", "weekday"])
    generated = 0

    for task in recurring_tasks:
        # 检查今天是否已生成
        if task.get("last_generated_date") == today:
            continue

        now = datetime.now()
        # 工作日检查
        if task["recurrence"] == "weekday" and now.weekday() >= 5:
            continue

        # 周任务检查（仅周一生成）
        if task["recurrence"] == "weekly" and now.weekday() != 0:
            continue

        # 生成今日实例
        conn = get_conn("tasks")
        cur = conn.execute(
            """INSERT INTO tasks (title, priority, estimated_minutes, deadline, recurrence, parent_recurring_id, sort_order)
               VALUES (?, ?, ?, ?, 'none', ?, ?)""",
            (task["title"], task["priority"], task["estimated_minutes"],
             None, task["id"], float(task["id"]))
        )
        new_id = cur.lastrowid
        conn.execute(
            "UPDATE tasks SET last_generated_date = ? WHERE id = ?",
            (today, task["id"])
        )
        conn.commit()
        conn.close()
        generated += 1

    return generated
