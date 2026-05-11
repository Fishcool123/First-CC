"""
database.py — SQLite 数据库初始化、建表、CRUD 封装
依赖：Python 标准库 sqlite3
"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "data.db")


def get_conn():
    """获取数据库连接，启用 WAL 模式提升并发读性能"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row       # 查询结果可用 dict 方式访问
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    """建表（幂等：IF NOT EXISTS），首次运行时创建表结构"""
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS tasks (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            title            TEXT    NOT NULL,
            priority         INTEGER DEFAULT 3,          -- 1最高 ~ 5最低
            estimated_minutes INTEGER NOT NULL,           -- 预估耗时（分钟）
            deadline         TEXT,                        -- ISO格式，可为空
            status           TEXT    DEFAULT 'pending',   -- pending | done
            sort_order       REAL    DEFAULT 0,           -- 手动拖拽排序权重
            created_at       TEXT    DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS availability (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            label      TEXT    NOT NULL,                  -- 时段名称，如"上午"
            start_time TEXT    NOT NULL,                  -- HH:MM
            end_time   TEXT    NOT NULL                   -- HH:MM
        );

        CREATE TABLE IF NOT EXISTS schedule_results (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id         INTEGER NOT NULL,              -- 关联 tasks.id
            scheduled_date  TEXT    NOT NULL,               -- 排程日期 YYYY-MM-DD
            start_time      TEXT    NOT NULL,               -- HH:MM
            end_time        TEXT    NOT NULL,               -- HH:MM
            slot_label      TEXT,                           -- 所属时段名称
            is_manual       INTEGER DEFAULT 0,              -- 0=算法排程, 1=手动分配
            created_at      TEXT    DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_schedule_date
            ON schedule_results(scheduled_date);
    """)
    conn.commit()
    conn.close()


# ── 任务 CRUD ─────────────────────────────────────────────

def get_tasks(status_filter=None):
    """获取任务列表，可按状态过滤，默认按 sort_order 排序"""
    conn = get_conn()
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


def add_task(title, priority, estimated_minutes, deadline=None):
    """新增任务，返回新建任务的完整字典"""
    conn = get_conn()
    # sort_order 默认 = id（保证新任务排在最后）
    cur = conn.execute(
        """INSERT INTO tasks (title, priority, estimated_minutes, deadline)
           VALUES (?, ?, ?, ?)""",
        (title, priority, estimated_minutes, deadline)
    )
    task_id = cur.lastrowid
    conn.execute("UPDATE tasks SET sort_order = ? WHERE id = ?", (float(task_id), task_id))
    conn.commit()
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    conn.close()
    return dict(row)


def update_task(task_id, **kwargs):
    """更新任务字段（title / priority / estimated_minutes / deadline / status / sort_order）"""
    allowed = {"title", "priority", "estimated_minutes", "deadline", "status", "sort_order"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return
    conn = get_conn()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [task_id]
    conn.execute(f"UPDATE tasks SET {set_clause} WHERE id = ?", values)
    conn.commit()
    conn.close()


def delete_task(task_id):
    """删除任务"""
    conn = get_conn()
    conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    conn.commit()
    conn.close()


# ── 可用时段 CRUD ─────────────────────────────────────────

def get_availability():
    """获取所有可用时段，按开始时间排序"""
    conn = get_conn()
    rows = conn.execute("SELECT * FROM availability ORDER BY start_time").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def save_availability(label, start_time, end_time):
    """新增一条可用时段"""
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO availability (label, start_time, end_time) VALUES (?, ?, ?)",
        (label, start_time, end_time)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM availability WHERE id = ?", (cur.lastrowid,)).fetchone()
    conn.close()
    return dict(row)


def update_availability(avail_id, **kwargs):
    """更新可用时段"""
    allowed = {"label", "start_time", "end_time"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return
    conn = get_conn()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [avail_id]
    conn.execute(f"UPDATE availability SET {set_clause} WHERE id = ?", values)
    conn.commit()
    conn.close()


def delete_availability(avail_id):
    """删除可用时段"""
    conn = get_conn()
    conn.execute("DELETE FROM availability WHERE id = ?", (avail_id,))
    conn.commit()
    conn.close()


# ── 预设默认数据 ──────────────────────────────────────────

# ── 排程结果 CRUD ─────────────────────────────────────────

def get_schedule(date_str):
    """获取指定日期的排程结果，联表查询任务详情"""
    conn = get_conn()
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
    """
    保存排程结果：先清空当天旧结果，再批量写入新结果。
    scheduled_items: [{task_id, start_time, end_time, slot_label, is_manual}, ...]
    """
    conn = get_conn()
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
    """手动插入一条排程记录"""
    conn = get_conn()
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
    """删除单条排程记录（手动分配后支持撤销）"""
    conn = get_conn()
    conn.execute("DELETE FROM schedule_results WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()


def seed_defaults():
    """首次使用：写入默认可用时段 + 一条示例任务"""
    conn = get_conn()
    cnt = conn.execute("SELECT COUNT(*) FROM availability").fetchone()[0]
    if cnt == 0:
        conn.execute(
            "INSERT INTO availability (label, start_time, end_time) VALUES (?, ?, ?)",
            ("上午", "09:00", "12:00")
        )
        conn.execute(
            "INSERT INTO availability (label, start_time, end_time) VALUES (?, ?, ?)",
            ("下午", "14:00", "18:00")
        )
        conn.execute(
            "INSERT INTO availability (label, start_time, end_time) VALUES (?, ?, ?)",
            ("晚上", "20:00", "22:00")
        )
    task_cnt = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    if task_cnt == 0:
        conn.execute(
            """INSERT INTO tasks (title, priority, estimated_minutes, deadline)
               VALUES (?, ?, ?, ?)""",
            ("示例任务：熟悉 PC智能任务助理", 1, 30, None)
        )
        conn.execute("UPDATE tasks SET sort_order = 1 WHERE id = 1")
    conn.commit()
    conn.close()
