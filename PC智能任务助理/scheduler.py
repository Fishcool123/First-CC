"""
scheduler.py — 简单排程算法（贪心填充）
依赖：无第三方库，纯 Python 标准库
"""
from datetime import datetime, date


def time_to_minutes(time_str):
    """将 HH:MM 字符串转为分钟数，如 '09:30' → 570"""
    parts = time_str.strip().split(":")
    return int(parts[0]) * 60 + int(parts[1])


def minutes_to_time(minutes):
    """将分钟数转为 HH:MM 字符串，如 570 → '09:30'"""
    h = minutes // 60
    m = minutes % 60
    return f"{h:02d}:{m:02d}"


def get_free_gaps(slot_start, slot_end, occupied_intervals):
    """
    在给定时段内，剔除已占用区间，返回所有空闲区间列表。
    occupied_intervals 为 [(start_min, end_min), ...]，无序。
    """
    # 按开始时间排序已占用区间
    sorted_occ = sorted(occupied_intervals, key=lambda x: x[0])
    gaps = []
    cursor = slot_start
    for occ_start, occ_end in sorted_occ:
        if occ_start > cursor:
            gaps.append((cursor, occ_start))
        cursor = max(cursor, occ_end)
    if cursor < slot_end:
        gaps.append((cursor, slot_end))
    return gaps


def schedule_tasks(tasks, availabilities):
    """
    贪心排程核心算法。

    参数：
        tasks         — 任务列表，每项含 id / title / priority / estimated_minutes / deadline
        availabilities — 可用时段列表，每项含 id / label / start_time / end_time

    返回：
        (scheduled, unscheduled)
        scheduled   — [{task: {...}, start: 'HH:MM', end: 'HH:MM', slot_label: str}, ...]
        unscheduled — [task_dict, ...]  未能排入的任务
    """
    # 1. 排序任务：优先级数字小的优先；同优先级截止时间早的优先
    def sort_key(t):
        prio = t.get("priority", 3)
        dl = t.get("deadline")
        # 无截止时间的任务排在同优先级末尾
        dl_sort = dl if dl else "9999-12-31"
        return (prio, dl_sort)

    sorted_tasks = sorted(tasks, key=sort_key)

    # 2. 按开始时间排序可用时段
    sorted_avail = sorted(availabilities, key=lambda a: a["start_time"])

    # 3. 每个可用时段维护已占用区间列表
    occupied = {a["id"]: [] for a in sorted_avail}

    scheduled = []
    unscheduled = []

    for task in sorted_tasks:
        placed = False
        task_min = task["estimated_minutes"]

        for avail in sorted_avail:
            avail_start = time_to_minutes(avail["start_time"])
            avail_end = time_to_minutes(avail["end_time"])

            gaps = get_free_gaps(avail_start, avail_end, occupied[avail["id"]])

            for gap_start, gap_end in gaps:
                if gap_end - gap_start >= task_min:
                    task_start = gap_start
                    task_end = task_start + task_min
                    occupied[avail["id"]].append((task_start, task_end))
                    scheduled.append({
                        "task": task,
                        "start": minutes_to_time(task_start),
                        "end": minutes_to_time(task_end),
                        "slot_label": avail["label"]
                    })
                    placed = True
                    break
            if placed:
                break

        if not placed:
            unscheduled.append(task)

    return scheduled, unscheduled
