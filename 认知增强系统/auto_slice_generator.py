"""
auto_slice_generator.py — 根据设备日志自动生成粗粒度切片
触发：每天 23:55 自动 / 首次启动补生成 / 手动触发
"""
import database as db
from datetime import datetime, date

PERIOD_MAP = {
    "morning":   (5, 11),
    "afternoon": (12, 17),
    "evening":   (18, 4),  # 跨夜
}

PERIOD_TIMES = {
    "morning":   "08:00:00",
    "afternoon": "14:00:00",
    "evening":   "20:00:00",
}

PERIOD_LABELS_CN = {
    "morning": "上午",
    "afternoon": "下午",
    "evening": "晚上",
}


def _hour_to_period(hour):
    if 5 <= hour <= 11:
        return "morning"
    elif 12 <= hour <= 17:
        return "afternoon"
    else:
        return "evening"


def generate_auto_slices(target_date, db_module=None):
    """根据 device_usage_logs 为指定日期生成自动切片。
    target_date: datetime.date 对象
    """
    if db_module is None:
        db_module = db

    # 先删除该日期的旧自动切片（幂等性）
    db_module.delete_auto_slices_for_date(target_date)

    logs = db_module.get_device_logs_by_date(target_date)
    if not logs:
        return 0

    # 分组聚合：(period, process) → total_seconds
    groups = {}
    for log in logs:
        ts = log["timestamp"]
        try:
            hour = int(ts[11:13])
        except (ValueError, IndexError):
            continue
        period = _hour_to_period(hour)
        process = log.get("process_name", "Unknown")
        key = (period, process)
        if key not in groups:
            groups[key] = 0
        groups[key] += log.get("duration_seconds", 0)

    # 过滤 < 5min 的
    groups = {k: v for k, v in groups.items() if v >= 300}

    if not groups:
        return 0

    count = 0
    date_str = target_date.isoformat()
    for (period, process), total_seconds in groups.items():
        minutes = total_seconds // 60
        timestamp = f"{date_str} {PERIOD_TIMES[period]}"
        db_module.add_slice(
            timestamp=timestamp,
            activity_desc=f"{process} ({minutes}分钟)",
            mood_tags=[],
            mood_intensity=3,
            energy_level=None,
            related_task_id=None,
            notes="",
            granularity="auto",
        )
        count += 1

    return count
