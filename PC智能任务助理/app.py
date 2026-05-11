"""
app.py — Flask 主入口：路由定义、API 接口、服务启动
启动方式：python app.py  或  双击 start.bat
"""
import os
import webbrowser
from datetime import date
from flask import Flask, render_template, request, jsonify

import database as db
from scheduler import schedule_tasks, time_to_minutes, minutes_to_time, get_free_gaps

# ── Flask 应用初始化 ───────────────────────────────────────
app = Flask(__name__)


# ── 页面路由 ───────────────────────────────────────────────

@app.route("/")
def index():
    """主页面"""
    return render_template("index.html")


# ── 任务 API ──────────────────────────────────────────────

@app.route("/api/tasks", methods=["GET"])
def api_get_tasks():
    """获取任务列表：?status=pending|done|all"""
    status = request.args.get("status")
    if status == "all" or status is None:
        tasks = db.get_tasks()
    else:
        tasks = db.get_tasks(status_filter=status)
    return jsonify(tasks)


@app.route("/api/tasks", methods=["POST"])
def api_add_task():
    """新增任务"""
    data = request.get_json()
    if not data or "title" not in data or "estimated_minutes" not in data:
        return jsonify({"error": "缺少必填字段：title / estimated_minutes"}), 400
    task = db.add_task(
        title=data["title"].strip(),
        priority=int(data.get("priority", 3)),
        estimated_minutes=int(data["estimated_minutes"]),
        deadline=data.get("deadline") or None,
    )
    return jsonify(task), 201


@app.route("/api/tasks/<int:task_id>", methods=["PUT"])
def api_update_task(task_id):
    """更新任务（状态、排序、字段修改）"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "请求体为空"}), 400
    db.update_task(task_id, **data)
    return jsonify({"ok": True})


@app.route("/api/tasks/<int:task_id>", methods=["DELETE"])
def api_delete_task(task_id):
    """删除任务"""
    db.delete_task(task_id)
    return jsonify({"ok": True})


# ── 可用时段 API ──────────────────────────────────────────

@app.route("/api/availability", methods=["GET"])
def api_get_availability():
    """获取可用时段列表"""
    return jsonify(db.get_availability())


@app.route("/api/availability", methods=["POST"])
def api_add_availability():
    """新增可用时段"""
    data = request.get_json()
    if not data or "label" not in data or "start_time" not in data or "end_time" not in data:
        return jsonify({"error": "缺少必填字段"}), 400
    avail = db.save_availability(data["label"], data["start_time"], data["end_time"])
    return jsonify(avail), 201


@app.route("/api/availability/<int:avail_id>", methods=["PUT"])
def api_update_availability(avail_id):
    """更新可用时段"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "请求体为空"}), 400
    db.update_availability(avail_id, **data)
    return jsonify({"ok": True})


@app.route("/api/availability/<int:avail_id>", methods=["DELETE"])
def api_delete_availability(avail_id):
    """删除可用时段"""
    db.delete_availability(avail_id)
    return jsonify({"ok": True})


# ── 排程 API ──────────────────────────────────────────────

@app.route("/api/schedule", methods=["GET"])
def api_get_schedule():
    """
    读取今日排程（从 schedule_results 表，不重新计算）。
    同时计算未排程任务 = pending 任务 - 已排程任务。
    支持 ?date=YYYY-MM-DD 查询历史。
    """
    query_date = request.args.get("date") or date.today().isoformat()
    rows = db.get_schedule(query_date)

    # 组装排程列表（兼容前端旧格式：每项含 task 子对象）
    scheduled = []
    scheduled_ids = set()
    for r in rows:
        scheduled_ids.add(r["task_id"])
        scheduled.append({
            "id": r["id"],                    # schedule_results 的主键
            "task": {
                "id": r["task_id"],
                "title": r["title"],
                "priority": r["priority"],
                "estimated_minutes": r["estimated_minutes"],
                "deadline": r["deadline"],
                "status": r["status"],
            },
            "start": r["start_time"],
            "end": r["end_time"],
            "slot_label": r["slot_label"],
            "is_manual": bool(r["is_manual"]),
        })

    # 未排程 = 所有 pending 任务 - 已排程任务
    all_pending = db.get_tasks(status_filter="pending")
    unscheduled = [t for t in all_pending if t["id"] not in scheduled_ids]

    return jsonify({"scheduled": scheduled, "unscheduled": unscheduled})


@app.route("/api/schedule", methods=["POST"])
def api_run_schedule():
    """
    执行排程算法并持久化：
    1. 清空当天旧 schedule_results
    2. 运行贪心排程
    3. 写入 schedule_results 表
    4. 返回排程结果
    """
    today = date.today().isoformat()
    tasks = db.get_tasks(status_filter="pending")

    if not tasks:
        db.save_schedule(today, [])  # 清空当天
        return jsonify({"scheduled": [], "unscheduled": []})

    availabilities = db.get_availability()
    if not availabilities:
        db.save_schedule(today, [])
        return jsonify({"scheduled": [], "unscheduled": tasks})

    scheduled, unscheduled = schedule_tasks(tasks, availabilities)

    # 持久化排程结果
    schedule_items = []
    for item in scheduled:
        schedule_items.append({
            "task_id": item["task"]["id"],
            "start_time": item["start"],
            "end_time": item["end"],
            "slot_label": item["slot_label"],
            "is_manual": 0,
        })
    db.save_schedule(today, schedule_items)

    return jsonify({"scheduled": scheduled, "unscheduled": unscheduled})


@app.route("/api/schedule/gaps", methods=["GET"])
def api_schedule_gaps():
    """
    获取今日可用时段的空闲间隙，供手动分配使用。
    返回每个可用时段内未被占用的时间段列表。
    """
    today = date.today().isoformat()
    existing = db.get_schedule(today)          # 已排程项
    availabilities = db.get_availability()     # 可用时段

    gaps_by_slot = []
    for avail in availabilities:
        slot_start = time_to_minutes(avail["start_time"])
        slot_end = time_to_minutes(avail["end_time"])

        # 取出该时段内的已占用区间
        occupied = []
        for item in existing:
            if item["slot_label"] == avail["label"]:
                occ_start = time_to_minutes(item["start_time"])
                occ_end = time_to_minutes(item["end_time"])
                occupied.append((occ_start, occ_end))

        free = get_free_gaps(slot_start, slot_end, occupied)
        for gap_start, gap_end in free:
            if gap_end - gap_start >= 5:       # 过滤 <5 分钟的碎片
                gaps_by_slot.append({
                    "slot_id": avail["id"],
                    "slot_label": avail["label"],
                    "gap_start": minutes_to_time(gap_start),
                    "gap_end": minutes_to_time(gap_end),
                    "gap_minutes": gap_end - gap_start,
                })

    return jsonify(gaps_by_slot)


@app.route("/api/schedule/assign", methods=["POST"])
def api_schedule_assign():
    """
    手动分配任务到指定空闲位置。
    请求体：{ task_id, scheduled_date, start_time, end_time, slot_label }
    """
    data = request.get_json()
    required = ["task_id", "scheduled_date", "start_time", "end_time", "slot_label"]
    for field in required:
        if field not in data:
            return jsonify({"error": f"缺少字段：{field}"}), 400

    result = db.add_schedule_item(
        date_str=data["scheduled_date"],
        task_id=int(data["task_id"]),
        start_time=data["start_time"],
        end_time=data["end_time"],
        slot_label=data["slot_label"],
        is_manual=1,
    )
    return jsonify(result), 201


@app.route("/api/schedule/<int:item_id>", methods=["DELETE"])
def api_delete_schedule(item_id):
    """删除单条排程记录（手动分配后退回）"""
    db.delete_schedule_item(item_id)
    return jsonify({"ok": True})


# ── 启动入口 ──────────────────────────────────────────────

if __name__ == "__main__":
    # 初始化数据库 & 写入默认数据
    db.init_db()
    db.seed_defaults()

    # 自动打开浏览器
    port = 5000
    url = f"http://127.0.0.1:{port}"
    webbrowser.open(url)

    print(f" PC智能任务助理 已启动 → {url}")
    app.run(host="127.0.0.1", port=port, debug=False)
