# -*- coding: utf-8 -*-
"""
agent_memory.py — 只读连接 v2 SQLite，提供回溯上下文给 Thinker
Phase 3: 今日切片数 / 上次记录时间 / 最近设备活动摘要

依赖: sqlite3（标准库）
"""
import os
import sqlite3
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
V2_DATA = os.path.normpath(os.path.join(BASE_DIR, "..", "认知增强系统", "data"))

SLICES_DB = os.path.join(V2_DATA, "slices.db")
TASKS_DB = os.path.join(V2_DATA, "task_assistant.db")


def _ro_connect(db_path):
    """WAL 兼容的只读连接"""
    uri = f"file:{db_path}?mode=ro"
    return sqlite3.connect(uri, uri=True)


# ═══════════════════════════════════════════════════════════
# 切片相关查询
# ═══════════════════════════════════════════════════════════

def get_today_slice_count():
    """今日手动切片数，失败返回 -1"""
    try:
        conn = _ro_connect(SLICES_DB)
        cnt = conn.execute(
            "SELECT COUNT(*) FROM slices WHERE date(timestamp) = date('now', 'localtime')"
        ).fetchone()[0]
        conn.close()
        return cnt
    except Exception:
        return -1


def get_last_manual_record():
    """最近一次手动记录的切片时间与描述。

    返回: (timestamp_iso, activity_desc) 或 (None, None)
    """
    try:
        conn = _ro_connect(SLICES_DB)
        row = conn.execute(
            "SELECT timestamp, activity_desc FROM slices "
            "ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        conn.close()
        if row:
            return row[0], row[1] or "(无描述)"
    except Exception:
        pass
    return None, None


def get_time_since_last_record():
    """距离上次手动记录的时间（分钟），无记录时返回 -1"""
    ts, _ = get_last_manual_record()
    if ts is None:
        return -1
    try:
        last = datetime.fromisoformat(ts)
        delta = datetime.now() - last
        return int(delta.total_seconds() / 60)
    except Exception:
        return -1


# ═══════════════════════════════════════════════════════════
# 设备活动摘要
# ═══════════════════════════════════════════════════════════

def get_recent_activity(hours=2):
    """最近 N 小时的设备使用摘要。

    返回: 格式化的中文字符串，如 "Cursor.exe 45min, chrome.exe 30min"
           无数据时返回 "(暂无)"
    """
    try:
        since = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M")
        conn = _ro_connect(SLICES_DB)
        rows = conn.execute(
            "SELECT process_name, SUM(duration_seconds) as total "
            "FROM device_usage_logs "
            "WHERE timestamp >= ? "
            "GROUP BY process_name "
            "ORDER BY total DESC "
            "LIMIT 5",
            (since,)
        ).fetchall()
        conn.close()

        if not rows:
            return "(暂无)"

        parts = []
        for proc, total_sec in rows:
            minutes = int(total_sec / 60)
            if minutes >= 1:
                parts.append(f"{proc} {minutes}min")
            else:
                parts.append(f"{proc} <1min")
        return ", ".join(parts)
    except Exception:
        return "(暂无)"


# ═══════════════════════════════════════════════════════════
# 任务相关查询
# ═══════════════════════════════════════════════════════════

def get_pending_task_count():
    """待处理任务数"""
    try:
        conn = _ro_connect(TASKS_DB)
        cnt = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE status = 'pending'"
        ).fetchone()[0]
        conn.close()
        return cnt
    except Exception:
        return -1


def get_scheduled_task_count():
    """已排程但未完成的任务数"""
    try:
        conn = _ro_connect(TASKS_DB)
        cnt = conn.execute(
            "SELECT COUNT(*) FROM schedule_results "
            "WHERE scheduled_date >= date('now', 'localtime')"
        ).fetchone()[0]
        conn.close()
        return cnt
    except Exception:
        return -1


def get_upcoming_deadlines():
    """即将截止的任务摘要（48h 内），返回中文字符串"""
    try:
        conn = _ro_connect(TASKS_DB)
        rows = conn.execute(
            "SELECT title, deadline FROM tasks "
            "WHERE status = 'pending' AND deadline IS NOT NULL "
            "AND deadline <= date('now', '+2 days', 'localtime') "
            "ORDER BY deadline LIMIT 3"
        ).fetchall()
        conn.close()
        if not rows:
            return "无"
        parts = [f"{r[0]}（{r[1]}）" for r in rows]
        return "、".join(parts)
    except Exception:
        return "?"


def get_free_slots_today():
    """今日空闲时段摘要"""
    try:
        conn = _ro_connect(TASKS_DB)
        rows = conn.execute(
            "SELECT start_time, end_time, label FROM availability ORDER BY start_time"
        ).fetchall()
        conn.close()
        if not rows:
            return "无"
        parts = [f"{r[2] or ''} {r[0]}-{r[1]}" for r in rows]
        return "、".join(parts)
    except Exception:
        return "?"


# ═══════════════════════════════════════════════════════════
# 上下文增强（供 agent_loop.py 调用）
# ═══════════════════════════════════════════════════════════

def enrich_context(ctx):
    """在 Observer 上下文基础上补充记忆数据（原地修改）。

    新增字段:
        today_slice_count, last_manual_record, time_ago,
        recent_activity_summary, pending_task_count
    """
    ctx["today_slice_count"] = get_today_slice_count()

    last_ts, last_desc = get_last_manual_record()
    if last_ts:
        ctx["last_manual_record"] = f"{last_ts}（{last_desc}）"
        minutes_ago = get_time_since_last_record()
        if minutes_ago >= 60:
            ctx["time_ago"] = f"{minutes_ago // 60} 小时"
        else:
            ctx["time_ago"] = f"{minutes_ago} 分钟"
    else:
        ctx["last_manual_record"] = "暂无"
        ctx["time_ago"] = "?"

    ctx["recent_activity_summary"] = get_recent_activity(hours=2)
    ctx["pending_task_count"] = get_pending_task_count()
    ctx["scheduled_task_count"] = get_scheduled_task_count()
    ctx["upcoming_deadlines"] = get_upcoming_deadlines()
    ctx["free_slots_today"] = get_free_slots_today()
    ctx["today_completed_count"] = 0  # v2 无完成追踪，预留
    return ctx


# ═══════════════════════════════════════════════════════════
# 独立测试
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    print("── Agent Memory 独立测试 ──\n")
    print(f"今日切片数: {get_today_slice_count()}")
    ts, desc = get_last_manual_record()
    print(f"上次记录: {ts} — {desc}")
    print(f"距上次: {get_time_since_last_record()} 分钟")
    print(f"最近2h活动: {get_recent_activity(2)}")
    print(f"待处理任务: {get_pending_task_count()}")

    print("\n── 上下文增强测试 ──")
    ctx = {"timestamp": datetime.now().isoformat(), "window": {}, "idle_seconds": 0,
           "time": {"period": "afternoon"}, "previous_window": "test"}
    enrich_context(ctx)
    for k, v in ctx.items():
        print(f"  {k}: {v}")
