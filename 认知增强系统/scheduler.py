"""
scheduler.py — 简单排程算法（贪心填充）
依赖：无第三方库，纯 Python 标准库
"""
from datetime import datetime, date, timedelta


def _effective_priority(task, now=None):
    """根据距截止时间动态调整优先级。
    - deadline < 2小时  → 强制 P0
    - deadline < 24小时 → 强制 P1
    - deadline < 3天    → 原优先级 +1（不超过 P0）
    - 否则保持原优先级
    """
    if now is None:
        now = datetime.now()

    base_priority = task.get('priority', 3)

    if not task.get('deadline'):
        return base_priority

    try:
        dl = datetime.fromisoformat(task['deadline'])
    except (ValueError, TypeError):
        return base_priority

    delta = dl - now

    if delta.total_seconds() < 0:
        return 0  # 已过期，强制 P0
    elif delta < timedelta(hours=2):
        return 0
    elif delta < timedelta(hours=24):
        return 1
    elif delta < timedelta(days=3):
        return max(0, base_priority - 1)
    else:
        return base_priority


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


def _hour_to_period(hour):
    """将小时数映射为时段"""
    if 5 <= hour <= 11:
        return "morning"
    elif 12 <= hour <= 17:
        return "afternoon"
    else:
        return "evening"


def _get_period_for_block(block, energy_profile):
    """根据时段的 start_time 推断精力画像中的时段"""
    start = time_to_minutes(block["start_time"])
    hour = start // 60
    return _hour_to_period(hour)


def _get_avg_energy(energy_profile, period):
    """从精力画像中获取时段的平均精力"""
    for p in energy_profile:
        if p["period"] == period:
            return p.get("avg_energy")
    return None


def _total_samples(energy_profile):
    return sum(p.get("sample_count", 0) for p in energy_profile)


def schedule_tasks(tasks, availabilities, energy_profile=None):
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
        prio = _effective_priority(t)
        dl = t.get("deadline")
        # 无截止时间的任务排在同优先级末尾
        dl_sort = dl if dl else "9999-12-31"
        return (prio, dl_sort)

    sorted_tasks = sorted(tasks, key=sort_key)

    # 2. 按开始时间排序可用时段
    sorted_avail = sorted(availabilities, key=lambda a: a["start_time"])

    # 2.5 精力匹配：时段分类
    high_energy_blocks = []
    low_energy_blocks = []
    normal_blocks = []
    use_energy = energy_profile and _total_samples(energy_profile) >= 7

    if use_energy:
        for block in sorted_avail:
            period = _get_period_for_block(block, energy_profile)
            avg = _get_avg_energy(energy_profile, period)
            if avg and avg >= 3.5:
                high_energy_blocks.append(block)
            elif avg and avg < 2.5:
                low_energy_blocks.append(block)
            else:
                normal_blocks.append(block)
    else:
        normal_blocks = sorted_avail  # 降级为传统贪心

    # 3. 每个可用时段维护已占用区间列表
    occupied = {a["id"]: [] for a in sorted_avail}

    scheduled = []
    unscheduled = []

    for task in sorted_tasks:
        placed = False
        task_min = task["estimated_minutes"]
        task_prio = _effective_priority(task)

        # 精力匹配：高优先级 → 高精力时段优先；低优先级 → 低精力时段可排
        if use_energy:
            if task_prio <= 1:
                # P0/P1：优先高精力，然后正常，最后低精力
                block_order = high_energy_blocks + normal_blocks + low_energy_blocks
            elif task_prio >= 4:
                # P4/P5：优先低精力和正常时段
                block_order = low_energy_blocks + normal_blocks + high_energy_blocks
            else:
                # P2/P3：正常优先，然后高精力
                block_order = normal_blocks + high_energy_blocks + low_energy_blocks
        else:
            block_order = normal_blocks

        for avail in block_order:
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
