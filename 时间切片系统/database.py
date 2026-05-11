"""
database.py — slices.db 建表、CRUD、跨库读取 PC助理任务
依赖：Python 标准库 sqlite3
"""
import sqlite3
import os
import json

# slices.db 路径（独立于 PC助理的 data.db）
DB_PATH = os.path.join(os.path.dirname(__file__), "slices.db")

# PC助理数据库路径（用于 ATTACH 跨库查询）
ASSISTANT_DB = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "PC智能任务助理", "task_assistant.db")
)


def get_conn():
    """获取 slices.db 连接，启用 WAL + 外键"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """建表（幂等）并预置情绪标签"""
    conn = get_conn()
    conn.executescript("""
        -- 手动切片
        CREATE TABLE IF NOT EXISTS slices (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp       TEXT    NOT NULL,       -- 记录时间 ISO: YYYY-MM-DD HH:MM:SS
            activity_desc   TEXT    NOT NULL,       -- 活动描述
            mood_tags       TEXT    DEFAULT '[]',   -- JSON 数组，如 ["专注","平静"]
            mood_intensity  INTEGER DEFAULT 3,      -- 情绪强度 1-5
            energy_level    INTEGER DEFAULT 3,      -- 精力水平 1-5
            related_task_id INTEGER,                -- 关联 PC助理 tasks.id（可空）
            notes           TEXT    DEFAULT '',     -- 自由笔记
            created_at      TEXT    DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_slices_ts ON slices(timestamp);

        -- 自动窗口监控记录（按分钟聚合）
        CREATE TABLE IF NOT EXISTS device_usage_logs (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp        TEXT    NOT NULL,      -- YYYY-MM-DD HH:MM（精确到分钟）
            window_title     TEXT    DEFAULT '',    -- 活跃窗口标题
            process_name     TEXT    DEFAULT '',    -- 进程名（如 chrome.exe）
            duration_seconds INTEGER DEFAULT 0,     -- 该分钟内的活跃秒数
            created_at       TEXT    DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_device_ts ON device_usage_logs(timestamp);

        -- 情绪标签字典
        CREATE TABLE IF NOT EXISTS mood_tags (
            id    INTEGER PRIMARY KEY AUTOINCREMENT,
            name  TEXT    NOT NULL UNIQUE,
            color TEXT    DEFAULT '#6e6e73'
        );
    """)
    conn.commit()
    conn.close()


def seed_defaults():
    """首次使用：写入预置情绪标签"""
    conn = get_conn()
    cnt = conn.execute("SELECT COUNT(*) FROM mood_tags").fetchone()[0]
    if cnt == 0:
        tags = [
            ("焦虑", "#ff3b30"), ("平静", "#34c759"), ("兴奋", "#ff9500"),
            ("低落", "#8e8e93"), ("烦躁", "#ff2d55"), ("疲惫", "#af52de"),
            ("专注", "#007aff"), ("放松", "#5ac8fa"), ("其他", "#c7c7cc"),
        ]
        conn.executemany(
            "INSERT INTO mood_tags (name, color) VALUES (?, ?)", tags
        )
    conn.commit()
    conn.close()


# ══════════════════════════════════════════════════════════
# 切片 CRUD
# ══════════════════════════════════════════════════════════

def add_slice(timestamp, activity_desc, mood_tags=None, mood_intensity=3,
              energy_level=3, related_task_id=None, notes=""):
    """新增手动切片"""
    conn = get_conn()
    tags_json = json.dumps(mood_tags or [], ensure_ascii=False)
    cur = conn.execute(
        """INSERT INTO slices (timestamp, activity_desc, mood_tags,
           mood_intensity, energy_level, related_task_id, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (timestamp, activity_desc, tags_json, mood_intensity,
         energy_level, related_task_id, notes)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM slices WHERE id = ?", (cur.lastrowid,)).fetchone()
    conn.close()
    return dict(row)


def get_slices(date_str=None):
    """
    获取切片列表。指定 date_str 则只取当天（匹配 timestamp 前缀）。
    date_str 格式：YYYY-MM-DD
    """
    conn = get_conn()
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


def delete_slice(slice_id):
    """删除手动切片"""
    conn = get_conn()
    conn.execute("DELETE FROM slices WHERE id = ?", (slice_id,))
    conn.commit()
    conn.close()


# ══════════════════════════════════════════════════════════
# 设备使用日志 CRUD
# ══════════════════════════════════════════════════════════

def add_device_log(timestamp, window_title, process_name, duration_seconds):
    """插入一条分钟级设备记录"""
    conn = get_conn()
    conn.execute(
        """INSERT INTO device_usage_logs (timestamp, window_title, process_name, duration_seconds)
           VALUES (?, ?, ?, ?)""",
        (timestamp, window_title, process_name, duration_seconds)
    )
    conn.commit()
    conn.close()


def get_device_logs(date_str):
    """
    获取指定日期的设备使用记录，按时间排序。
    start: YYYY-MM-DD 00:00, end: YYYY-MM-DD 23:59
    """
    conn = get_conn()
    rows = conn.execute(
        """SELECT * FROM device_usage_logs
           WHERE timestamp LIKE ?
           ORDER BY timestamp ASC""",
        (f"{date_str}%",)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_device_logs_aggregated(date_str):
    """
    获取指定日期的设备使用记录，按进程名聚合当日总使用时长（分钟）。
    用于"今天设备使用概览"。
    """
    conn = get_conn()
    rows = conn.execute(
        """SELECT process_name,
                  COUNT(*) AS active_minutes,
                  SUM(duration_seconds) AS total_seconds
           FROM device_usage_logs
           WHERE timestamp LIKE ?
           GROUP BY process_name
           ORDER BY total_seconds DESC""",
        (f"{date_str}%",)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ══════════════════════════════════════════════════════════
# 日历热力图统计
# ══════════════════════════════════════════════════════════

def get_heatmap_data(start_date, end_date):
    """
    返回日期范围内每天的手动切片数 + 是否有设备日志。
    返回 [{date, slice_count, has_device_data}, ...]
    Bug #3 修复：只用手动切片数做热力色阶，设备日志用布尔标记。
    """
    conn = get_conn()
    # 手动切片计数
    rows1 = conn.execute(
        """SELECT substr(timestamp, 1, 10) AS day, COUNT(*) AS cnt
           FROM slices
           WHERE timestamp >= ? AND timestamp < ?
           GROUP BY day""",
        (start_date, f"{end_date} 23:59:59")
    ).fetchall()
    # 哪些天有设备日志
    rows2 = conn.execute(
        """SELECT DISTINCT substr(timestamp, 1, 10) AS day
           FROM device_usage_logs
           WHERE timestamp >= ? AND timestamp < ?
           GROUP BY day""",
        (start_date, f"{end_date} 23:59:59")
    ).fetchall()
    conn.close()

    device_days = {r["day"] for r in rows2}
    day_map = {}
    for r in rows1:
        day_map[r["day"]] = r["cnt"]

    result = []
    # 生成日期范围内所有天（含无数据的天）
    from datetime import date, timedelta
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
# 跨库读取 PC助理任务
# ══════════════════════════════════════════════════════════

def get_assistant_tasks():
    """
    通过 ATTACH 挂载 PC助理 data.db，读取待办任务列表。
    若 PC助理数据库不存在则返回空列表。
    """
    if not os.path.exists(ASSISTANT_DB):
        return []

    conn = get_conn()
    try:
        conn.execute("ATTACH DATABASE ? AS assistant", (ASSISTANT_DB,))
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
# 情绪标签字典
# ══════════════════════════════════════════════════════════

def get_mood_tags():
    """获取所有情绪标签"""
    conn = get_conn()
    rows = conn.execute("SELECT * FROM mood_tags ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]
