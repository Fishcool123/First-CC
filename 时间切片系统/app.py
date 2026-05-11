"""
app.py — Flask 主入口：路由、API、监控启停、跨库查询
启动方式：python desktop.py（桌面应用） 或 python app.py（浏览器模式）
"""
import os
import json
from datetime import date, datetime, timedelta
from flask import Flask, render_template, request, jsonify

import database as db
from monitor import start_monitor, stop_monitor

app = Flask(__name__)


# ── 页面路由 ──────────────────────────────────────────────

@app.route("/")
def index():
    """主页面"""
    return render_template("index.html")


# ── 手动切片 API ──────────────────────────────────────────

@app.route("/api/slices", methods=["GET"])
def api_get_slices():
    """获取切片列表：?date=YYYY-MM-DD，不传则取今天"""
    query_date = request.args.get("date") or date.today().isoformat()
    slices = db.get_slices(date_str=query_date)
    return jsonify(slices)


@app.route("/api/slices", methods=["POST"])
def api_add_slice():
    """新增手动切片"""
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
    )
    return jsonify(slc), 201


@app.route("/api/slices/<int:slice_id>", methods=["DELETE"])
def api_delete_slice(slice_id):
    """删除手动切片"""
    db.delete_slice(slice_id)
    return jsonify({"ok": True})


# ── 设备使用日志 API ─────────────────────────────────────

@app.route("/api/device-logs", methods=["GET"])
def api_get_device_logs():
    """获取设备使用日志：?date=YYYY-MM-DD"""
    query_date = request.args.get("date") or date.today().isoformat()
    logs = db.get_device_logs(query_date)
    return jsonify(logs)


@app.route("/api/device-logs/summary", methods=["GET"])
def api_get_device_summary():
    """设备使用聚合统计（按进程汇总当天时长）"""
    query_date = request.args.get("date") or date.today().isoformat()
    summary = db.get_device_logs_aggregated(query_date)
    return jsonify(summary)


# ── 日历热力图 API ────────────────────────────────────────

@app.route("/api/heatmap", methods=["GET"])
def api_heatmap():
    """
    返回最近 3 个月每天的手动切片数 + 设备数据标记。
    颜色深度基于 slice_count，has_device_data 用于底栏圆点。
    """
    today = date.today()
    start = today - timedelta(days=90)
    data = db.get_heatmap_data(start.isoformat(), today.isoformat())
    return jsonify(data)


# ── 跨库：PC助理任务 ──────────────────────────────────────

@app.route("/api/assistant-tasks", methods=["GET"])
def api_assistant_tasks():
    """读取 PC智能任务助理 的待办任务列表（跨库 ATTACH）"""
    tasks = db.get_assistant_tasks()
    return jsonify(tasks)


# ── 情绪标签字典 ──────────────────────────────────────────

@app.route("/api/mood-tags", methods=["GET"])
def api_mood_tags():
    """获取情绪标签列表"""
    return jsonify(db.get_mood_tags())


# ── 启动入口（浏览器模式，调试用） ────────────────────────

if __name__ == "__main__":
    db.init_db()
    db.seed_defaults()
    start_monitor(db.add_device_log)

    port = 5001
    url = f"http://127.0.0.1:{port}"
    import webbrowser
    webbrowser.open(url)

    print(f" 时间切片系统 已启动 → {url}")
    try:
        app.run(host="127.0.0.1", port=port, debug=False)
    finally:
        stop_monitor()
