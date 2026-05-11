"""
app.py — 统一 Flask 应用：任务管理 + 切片系统 + 系统设置
路由前缀：/api/tasks/*  /api/slices/*  /api/system/*
启动方式：python desktop.py（桌面应用） 或 python app.py（浏览器调试）
"""
from datetime import datetime, date, timedelta
import threading
from flask import Flask, render_template, request, jsonify

import database as db
from scheduler import schedule_tasks, time_to_minutes, minutes_to_time, get_free_gaps
from rule_engine import RuleEngine, get_pending_prompts
from auto_slice_generator import generate_auto_slices

app = Flask(__name__)

# 规则引擎实例（在 init_db 后初始化）
rule_engine = None


# ══════════════════════════════════════════════════════════
# 页面路由
# ══════════════════════════════════════════════════════════

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/quick-slice")
def quick_slice_page():
    return render_template("quick-slice.html")


# ══════════════════════════════════════════════════════════
# /api/tasks/* — 任务管理（原 PC智能任务助理）
# ══════════════════════════════════════════════════════════

@app.route("/api/tasks", methods=["GET"])
def api_get_tasks():
    status = request.args.get("status")
    if status == "all" or status is None:
        tasks = db.get_tasks()
    else:
        tasks = db.get_tasks(status_filter=status)
    return jsonify(tasks)


@app.route("/api/tasks", methods=["POST"])
def api_add_task():
    data = request.get_json()
    if not data or "title" not in data or "estimated_minutes" not in data:
        return jsonify({"error": "缺少必填字段：title / estimated_minutes"}), 400
    task = db.add_task(
        title=data["title"].strip(),
        priority=int(data.get("priority", 3)),
        estimated_minutes=int(data["estimated_minutes"]),
        deadline=data.get("deadline") or None,
        recurrence=data.get("recurrence", "none"),
    )
    return jsonify(task), 201


@app.route("/api/tasks/<int:task_id>", methods=["PUT"])
def api_update_task(task_id):
    data = request.get_json()
    if not data:
        return jsonify({"error": "请求体为空"}), 400
    db.update_task(task_id, **data)
    return jsonify({"ok": True})


@app.route("/api/tasks/<int:task_id>", methods=["DELETE"])
def api_delete_task(task_id):
    db.delete_task(task_id)
    return jsonify({"ok": True})


# ── 可用时段 ──────────────────────────────────────────

@app.route("/api/tasks/availability", methods=["GET"])
def api_get_availability():
    return jsonify(db.get_availability())


@app.route("/api/tasks/availability", methods=["POST"])
def api_add_availability():
    data = request.get_json()
    if not data or "label" not in data or "start_time" not in data or "end_time" not in data:
        return jsonify({"error": "缺少必填字段"}), 400
    avail = db.save_availability(data["label"], data["start_time"], data["end_time"])
    return jsonify(avail), 201


@app.route("/api/tasks/availability/<int:avail_id>", methods=["PUT"])
def api_update_availability(avail_id):
    data = request.get_json()
    if not data:
        return jsonify({"error": "请求体为空"}), 400
    db.update_availability(avail_id, **data)
    return jsonify({"ok": True})


@app.route("/api/tasks/availability/<int:avail_id>", methods=["DELETE"])
def api_delete_availability(avail_id):
    db.delete_availability(avail_id)
    return jsonify({"ok": True})


# ── 排程 ──────────────────────────────────────────────

@app.route("/api/tasks/schedule", methods=["GET"])
def api_get_schedule():
    query_date = request.args.get("date") or date.today().isoformat()
    rows = db.get_schedule(query_date)
    scheduled = []
    scheduled_ids = set()
    for r in rows:
        scheduled_ids.add(r["task_id"])
        scheduled.append({
            "id": r["id"],
            "task": {
                "id": r["task_id"], "title": r["title"],
                "priority": r["priority"], "estimated_minutes": r["estimated_minutes"],
                "deadline": r["deadline"], "status": r["status"],
            },
            "start": r["start_time"], "end": r["end_time"],
            "slot_label": r["slot_label"], "is_manual": bool(r["is_manual"]),
        })
    all_pending = db.get_tasks(status_filter="pending")
    unscheduled = [t for t in all_pending if t["id"] not in scheduled_ids]
    return jsonify({"scheduled": scheduled, "unscheduled": unscheduled})


@app.route("/api/tasks/schedule", methods=["POST"])
def api_run_schedule():
    today = date.today().isoformat()
    tasks = db.get_tasks(status_filter="pending")
    if not tasks:
        db.save_schedule(today, [])
        return jsonify({"scheduled": [], "unscheduled": []})
    availabilities = db.get_availability()
    if not availabilities:
        db.save_schedule(today, [])
        return jsonify({"scheduled": [], "unscheduled": tasks})
    scheduled, unscheduled = schedule_tasks(tasks, availabilities, db.get_energy_profile())
    schedule_items = []
    for item in scheduled:
        schedule_items.append({
            "task_id": item["task"]["id"],
            "start_time": item["start"], "end_time": item["end"],
            "slot_label": item["slot_label"], "is_manual": 0,
        })
    db.save_schedule(today, schedule_items)
    return jsonify({"scheduled": scheduled, "unscheduled": unscheduled})


@app.route("/api/tasks/schedule/gaps", methods=["GET"])
def api_schedule_gaps():
    today = date.today().isoformat()
    existing = db.get_schedule(today)
    availabilities = db.get_availability()
    gaps_by_slot = []
    for avail in availabilities:
        slot_start = time_to_minutes(avail["start_time"])
        slot_end = time_to_minutes(avail["end_time"])
        occupied = []
        for item in existing:
            if item["slot_label"] == avail["label"]:
                occupied.append((
                    time_to_minutes(item["start_time"]),
                    time_to_minutes(item["end_time"]),
                ))
        free = get_free_gaps(slot_start, slot_end, occupied)
        for gap_start, gap_end in free:
            if gap_end - gap_start >= 5:
                gaps_by_slot.append({
                    "slot_id": avail["id"],
                    "slot_label": avail["label"],
                    "gap_start": minutes_to_time(gap_start),
                    "gap_end": minutes_to_time(gap_end),
                    "gap_minutes": gap_end - gap_start,
                })
    return jsonify(gaps_by_slot)


@app.route("/api/tasks/schedule/assign", methods=["POST"])
def api_schedule_assign():
    data = request.get_json()
    required = ["task_id", "scheduled_date", "start_time", "end_time", "slot_label"]
    for field in required:
        if field not in data:
            return jsonify({"error": f"缺少字段：{field}"}), 400
    result = db.add_schedule_item(
        date_str=data["scheduled_date"], task_id=int(data["task_id"]),
        start_time=data["start_time"], end_time=data["end_time"],
        slot_label=data["slot_label"], is_manual=1,
    )
    return jsonify(result), 201


@app.route("/api/tasks/schedule/<int:item_id>", methods=["DELETE"])
def api_delete_schedule(item_id):
    db.delete_schedule_item(item_id)
    return jsonify({"ok": True})


# ══════════════════════════════════════════════════════════
# /api/slices/* — 切片系统（原 时间切片系统）
# ══════════════════════════════════════════════════════════

@app.route("/api/slices", methods=["GET"])
def api_get_slices():
    query_date = request.args.get("date") or date.today().isoformat()
    return jsonify(db.get_slices(date_str=query_date))


@app.route("/api/slices", methods=["POST"])
def api_add_slice():
    data = request.get_json()
    required = ["timestamp", "activity_desc"]
    for field in required:
        if field not in data:
            return jsonify({"error": f"缺少必填字段：{field}"}), 400
    slc = db.add_slice(
        timestamp=data["timestamp"],
        activity_desc=data["activity_desc"],
        mood_tags=data.get("mood_tags", []),
        mood_intensity=int(data.get("mood_intensity", 3)),
        energy_level=int(data.get("energy_level", 3)),
        related_task_id=data.get("related_task_id"),
        notes=data.get("notes", ""),
        granularity=data.get("granularity", "fine"),
    )
    # 规则引擎挂载点
    if rule_engine:
        mood_tags = data.get("mood_tags", [])
        if mood_tags:
            tag = mood_tags[0]
            recent_count = 0
            try:
                cutoff = (datetime.now() - timedelta(days=7)).isoformat()
                all_recent = db.get_slices()
                recent_count = sum(1 for r in all_recent if tag in r.get("mood_tags", []) and r["timestamp"] >= cutoff)
            except Exception:
                pass
            rule_engine.evaluate("slice_mood_spike", {"tag": tag, "recent_count": recent_count, "days": 7})
        energy_level = int(data.get("energy_level", 3))
        rule_engine.evaluate("energy_drop", {"energy_level": energy_level, "consecutive_low": 1 if energy_level <= 2 else 0})
    return jsonify(slc), 201


@app.route("/api/slices/<int:slice_id>", methods=["PUT"])
def api_update_slice(slice_id):
    """编辑切片（第三阶段 #9）"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "请求体为空"}), 400
    db.update_slice(slice_id, **data)
    return jsonify({"ok": True})


@app.route("/api/slices/<int:slice_id>", methods=["DELETE"])
def api_delete_slice(slice_id):
    db.delete_slice(slice_id)
    return jsonify({"ok": True})


@app.route("/api/slices/device-logs", methods=["GET"])
def api_get_device_logs():
    query_date = request.args.get("date") or date.today().isoformat()
    return jsonify(db.get_device_logs(query_date))


@app.route("/api/slices/device-logs/summary", methods=["GET"])
def api_get_device_summary():
    query_date = request.args.get("date") or date.today().isoformat()
    return jsonify(db.get_device_logs_aggregated(query_date))


@app.route("/api/slices/heatmap", methods=["GET"])
def api_heatmap():
    today = date.today()
    start = today - timedelta(days=90)
    return jsonify(db.get_heatmap_data(start.isoformat(), today.isoformat()))


@app.route("/api/slices/assistant-tasks", methods=["GET"])
def api_assistant_tasks():
    return jsonify(db.get_assistant_tasks())


@app.route("/api/slices/mood-tags", methods=["GET"])
def api_mood_tags():
    return jsonify(db.get_mood_tags())


# ══════════════════════════════════════════════════════════
# /api/system/* — 系统设置（第三阶段 #10/#12）
# ══════════════════════════════════════════════════════════

@app.route("/api/system/export", methods=["GET"])
def api_export():
    """数据导出：?format=json|csv&type=slices|tasks"""
    fmt = request.args.get("format", "json")
    etype = request.args.get("type", "slices")
    if etype == "slices":
        data = db.get_slices()
    else:
        data = db.get_tasks(status_filter="all")
    if fmt == "csv":
        import io, csv as csv_mod
        buf = io.StringIO()
        if data:
            writer = csv_mod.DictWriter(buf, fieldnames=data[0].keys())
            writer.writeheader()
            for row in data:
                writer.writerow({k: str(v) for k, v in row.items()})
        from flask import make_response
        resp = make_response(buf.getvalue())
        resp.headers["Content-Type"] = "text/csv; charset=utf-8-sig"
        resp.headers["Content-Disposition"] = f"attachment; filename={etype}_export.csv"
        return resp
    return jsonify(data)


@app.route("/api/system/device-log-count", methods=["GET"])
def api_device_log_count():
    return jsonify({"count": db.get_device_log_count()})


@app.route("/api/system/cleanup-device-logs", methods=["POST"])
def api_cleanup_device_logs():
    deleted = db.cleanup_old_device_logs()
    return jsonify({"deleted": deleted})


# ══════════════════════════════════════════════════════════
# /api/rules/* — 规则引擎
# ══════════════════════════════════════════════════════════

@app.route("/api/rules", methods=["GET"])
def api_get_rules():
    return jsonify(db.get_rules())


@app.route("/api/rules/<int:rule_id>/toggle", methods=["POST"])
def api_toggle_rule(rule_id):
    data = request.get_json()
    enabled = bool(data.get("enabled", True)) if data else True
    db.toggle_rule(rule_id, enabled)
    return jsonify({"ok": True})


@app.route("/api/rules/evaluate", methods=["POST"])
def api_evaluate_rules():
    """手动触发一次规则评估（调试用）"""
    data = request.get_json()
    if not data or "trigger_type" not in data:
        return jsonify({"error": "缺少 trigger_type"}), 400
    trigger_type = data["trigger_type"]
    context = data.get("context", {})
    if rule_engine:
        rule_engine.evaluate(trigger_type, context)
    return jsonify({"ok": True})


@app.route("/api/rules/prompts", methods=["GET"])
def api_get_prompts():
    """前端轮询：获取待处理弹窗"""
    return jsonify(get_pending_prompts())


# ══════════════════════════════════════════════════════════
# 精力曲线 API
# ══════════════════════════════════════════════════════════

@app.route("/api/slices/energy-profile", methods=["GET"])
def api_get_energy_profile():
    profile = db.get_energy_profile()
    trend = db.get_energy_trend(days=14)
    return jsonify({"profile": profile, "trend": trend})


@app.route("/api/slices/energy-profile/refresh", methods=["POST"])
def api_refresh_energy_profile():
    db.refresh_energy_profile()
    profile = db.get_energy_profile()
    return jsonify({"status": "ok", "profile": profile})


@app.route("/api/slices/auto-generate/yesterday", methods=["POST"])
def api_auto_generate_yesterday():
    """手动触发昨日自动切片生成"""
    yesterday = (datetime.now() - timedelta(days=1)).date()
    count = generate_auto_slices(yesterday, db)
    return jsonify({"status": "ok", "count": count, "date": yesterday.isoformat()})


def init_rules_endpoint():
    """初始化规则引擎全局实例（在 init_db 后调用）"""
    global rule_engine
    rule_engine = RuleEngine(db)


def start_rule_timer():
    """每 15 分钟检查 slice_gap / task_stale 等定时触发器"""
    def _check():
        try:
            if rule_engine:
                # slice_gap: 检查最后 N 小时是否有切片
                hours = 4
                recent = db.get_slices()
                has_recent = False
                if recent:
                    latest = max(r["timestamp"] for r in recent)
                    try:
                        latest_dt = datetime.fromisoformat(latest.replace(" ", "T"))
                        if (datetime.now() - latest_dt).total_seconds() < hours * 3600:
                            has_recent = True
                    except (ValueError, TypeError):
                        pass
                if not has_recent:
                    rule_engine.evaluate("slice_gap", {"hours": hours})

                # task_stale: 检查多日未推进的任务
                days = 3
                tasks = db.get_tasks(status_filter="pending")
                for task in tasks:
                    created = task.get("created_at", "")
                    if created:
                        try:
                            created_dt = datetime.fromisoformat(created.replace(" ", "T"))
                            if (datetime.now() - created_dt).days >= days:
                                rule_engine.evaluate("task_stale", {
                                    "task_name": task["title"], "days": days
                                })
                        except (ValueError, TypeError):
                            pass

                # task_deadline_approaching
                now = datetime.now()
                for task in tasks:
                    dl = task.get("deadline")
                    if dl:
                        try:
                            dl_dt = datetime.fromisoformat(dl.replace(" ", "T"))
                            delta = dl_dt - now
                            if 0 < delta.total_seconds() < 3600:
                                hours_left = int(delta.total_seconds() / 60)
                                rule_engine.evaluate("task_deadline_approaching", {
                                    "task_name": task["title"],
                                    "time": f"{hours_left}分钟" if hours_left < 60 else f"{hours_left // 60}小时",
                                })
                        except (ValueError, TypeError):
                            pass

                # device_usage_daily
                today_logs = db.get_device_logs_aggregated(date.today().isoformat())
                total_seconds = sum(l.get("total_seconds", 0) for l in today_logs)
                total_hours = total_seconds / 3600
                if total_hours >= 8:
                    rule_engine.evaluate("device_usage_daily", {"hours": 8})
        except Exception:
            pass
        # 15 分钟后再次调度
        threading.Timer(900, _check).start()

    threading.Timer(900, _check).start()


# ══════════════════════════════════════════════════════════
# 浏览器模式入口（调试用）
# ══════════════════════════════════════════════════════════

if __name__ == "__main__":
    db.init_db()
    init_rules_endpoint()
    start_rule_timer()

    # 检测昨日是否已生成自动切片
    yesterday = (datetime.now() - timedelta(days=1)).date()
    existing = db.get_auto_slices_count_for_date(yesterday)
    if existing == 0:
        try:
            generate_auto_slices(yesterday, db)
            print(f" 补生成昨日自动切片")
        except Exception as e:
            print(f" 补生成昨日自动切片失败: {e}")

    # 生成今日重复任务
    try:
        count = db.generate_recurring_tasks_today()
        if count:
            print(f" 重复任务生成：{count} 条")
    except Exception as e:
        print(f" 重复任务生成失败: {e}")

    # 启动定时器
    start_auto_slice_timer()
    start_recurring_tasks_timer()

    port = 5000
    url = f"http://127.0.0.1:{port}"
    import webbrowser
    webbrowser.open(url)
    print(f" 认知增强系统 已启动 → {url}")
    app.run(host="127.0.0.1", port=port, debug=False)


def start_auto_slice_timer():
    """每天 23:55 自动生成当日切片"""
    now = datetime.now()
    target = now.replace(hour=23, minute=55, second=0, microsecond=0)
    if target < now:
        target += timedelta(days=1)
    delay = (target - now).total_seconds()

    def _auto_slice():
        try:
            count = generate_auto_slices(datetime.now().date(), db)
            print(f" 自动切片生成：{count} 条")
        except Exception as e:
            print(f" 自动切片生成失败: {e}")
        # 24h 后再次调度
        threading.Timer(86400, _auto_slice).start()

    threading.Timer(delay, _auto_slice).start()


def start_recurring_tasks_timer():
    """每天 00:05 自动生成重复任务实例"""
    now = datetime.now()
    target = now.replace(hour=0, minute=5, second=0, microsecond=0)
    if target < now:
        target += timedelta(days=1)
    delay = (target - now).total_seconds()

    def _generate():
        try:
            count = db.generate_recurring_tasks_today()
            if count:
                print(f" 重复任务生成：{count} 条")
        except Exception as e:
            print(f" 重复任务生成失败: {e}")
        # 24h 后再次调度
        threading.Timer(86400, _generate).start()

    threading.Timer(delay, _generate).start()
