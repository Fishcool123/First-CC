"""
desktop.py — 桌面应用入口：Edge --app 原生窗口 + pystray 系统托盘 + plyer 通知
启动方式：python desktop.py  或  双击 start.bat
"""
import os, sys, threading, time, subprocess, signal, traceback
from datetime import datetime
from pathlib import Path

# ── 日志 ──────────────────────────────────────────────────
LOG_FILE = Path(__file__).parent / f"desktop_{datetime.now():%Y%m%d_%H%M%S}.log"

def log(msg):
    line = f"[{datetime.now():%H:%M:%S}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

def log_error():
    log(traceback.format_exc())

sys.excepthook = lambda t, v, tb: log("".join(traceback.format_exception(t, v, tb)))
log("desktop.py 启动")

# ── 依赖 ──────────────────────────────────────────────────
try:
    from PIL import Image, ImageDraw
    import pystray
    from plyer import notification as plyer_notify
    import psutil
    log("核心依赖加载完成")
except Exception:
    log_error()
    sys.exit(1)

# ══════════════════════════════════════════════════════════
FLASK_HOST = "127.0.0.1"
FLASK_PORT = 5001
APP_URL = f"http://{FLASK_HOST}:{FLASK_PORT}"
PROJ_DIR = Path(__file__).parent

EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
if not os.path.exists(EDGE_PATH):
    EDGE_PATH = r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"
if not os.path.exists(EDGE_PATH):
    EDGE_PATH = "msedge.exe"

# ══════════════════════════════════════════════════════════
# Flask 路由
# ══════════════════════════════════════════════════════════
from flask import Flask, render_template, request, jsonify
flask_app = Flask(__name__)

def setup_flask():
    from datetime import date as date_cls, timedelta
    import database as db
    from monitor import start_monitor, stop_monitor

    @flask_app.route("/")
    def index():
        return render_template("index.html")

    @flask_app.route("/api/slices", methods=["GET"])
    def api_get_slices():
        qd = request.args.get("date") or date_cls.today().isoformat()
        return jsonify(db.get_slices(date_str=qd))

    @flask_app.route("/api/slices", methods=["POST"])
    def api_add_slice():
        data = request.get_json()
        if "timestamp" not in data or "activity_desc" not in data:
            return jsonify({"error": "缺少必填字段"}), 400
        slc = db.add_slice(
            timestamp=data["timestamp"], activity_desc=data["activity_desc"],
            mood_tags=data.get("mood_tags", []),
            mood_intensity=int(data.get("mood_intensity", 3)),
            energy_level=int(data.get("energy_level", 3)),
            related_task_id=data.get("related_task_id"),
            notes=data.get("notes", ""),
        )
        return jsonify(slc), 201

    @flask_app.route("/api/slices/<int:slice_id>", methods=["DELETE"])
    def api_delete_slice(slice_id):
        db.delete_slice(slice_id)
        return jsonify({"ok": True})

    @flask_app.route("/api/device-logs", methods=["GET"])
    def api_get_device_logs():
        return jsonify(db.get_device_logs(request.args.get("date") or date_cls.today().isoformat()))

    @flask_app.route("/api/device-logs/summary", methods=["GET"])
    def api_get_device_summary():
        return jsonify(db.get_device_logs_aggregated(request.args.get("date") or date_cls.today().isoformat()))

    @flask_app.route("/api/heatmap", methods=["GET"])
    def api_heatmap():
        today = date_cls.today()
        return jsonify(db.get_heatmap_data((today - timedelta(days=90)).isoformat(), today.isoformat()))

    @flask_app.route("/api/assistant-tasks", methods=["GET"])
    def api_assistant_tasks():
        return jsonify(db.get_assistant_tasks())

    @flask_app.route("/api/mood-tags", methods=["GET"])
    def api_mood_tags():
        return jsonify(db.get_mood_tags())

    return start_monitor, stop_monitor

# ══════════════════════════════════════════════════════════
# 系统托盘
# ══════════════════════════════════════════════════════════
_tray = None
_edge_proc = None
_stop_mon = None

def create_tray_image():
    img = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([2, 2, 30, 30], fill=(94, 106, 210, 255))
    cx, cy = 16, 16
    draw.line([cx, cy, cx, 8], fill="white", width=2)
    draw.line([cx, cy, cx + 7, cy + 5], fill="white", width=2)
    return img

def launch_edge():
    """启动 Edge --app 窗口"""
    global _edge_proc
    # 先杀掉之前的 Edge app 实例（避免多窗口）
    kill_edge_app()
    try:
        _edge_proc = subprocess.Popen(
            [EDGE_PATH, f"--app={APP_URL}", "--new-window",
             "--no-first-run", "--no-default-browser-check"],
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        log(f"Edge 已启动 (PID={_edge_proc.pid})")
    except Exception as e:
        log(f"Edge 启动失败: {e}")
        _edge_proc = None

def kill_edge_app():
    """杀掉运行中的 Edge app 实例（只杀访问我们 URL 的）"""
    global _edge_proc
    if _edge_proc and _edge_proc.poll() is None:
        try:
            _edge_proc.terminate()
            _edge_proc.wait(timeout=3)
        except Exception:
            try:
                _edge_proc.kill()
            except Exception:
                pass
    _edge_proc = None

def on_tray_show(icon, item):
    launch_edge()

def on_tray_exit(icon, item):
    global _tray, _stop_mon
    log("托盘退出...")
    kill_edge_app()
    if _stop_mon:
        try: _stop_mon()
        except Exception: pass
    if _tray:
        _tray.stop()
    os._exit(0)

# ══════════════════════════════════════════════════════════
# 通知
# ══════════════════════════════════════════════════════════
_last_hourly = None

def notify_loop():
    global _last_hourly
    while True:
        time.sleep(60)
        try:
            now = datetime.now()
            h = now.hour
            if 8 <= h <= 22 and (_last_hourly is None or _last_hourly.hour != h):
                _last_hourly = now
                plyer_notify.notify(
                    title=u"⏱ 该切一片了",
                    message=u"现在是 %d:00 — 记录一下当前状态吧！" % h,
                    app_name=u"时间切片系统", timeout=5)
        except Exception:
            pass

# ══════════════════════════════════════════════════════════
# Edge 进程监控（窗口关闭后自动检测）
# ══════════════════════════════════════════════════════════

def edge_watcher():
    """每 3 秒检查 Edge 是否还活着，死了就记录"""
    while True:
        time.sleep(3)
        global _edge_proc
        if _edge_proc and _edge_proc.poll() is not None:
            log("Edge 窗口已关闭")
            _edge_proc = None

# ══════════════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════════════

def main():
    global _tray, _stop_mon

    try:
        import database as db
        db.init_db()
        db.seed_defaults()
        start_mon, stop_mon = setup_flask()
        _stop_mon = stop_mon
    except Exception:
        log_error()
        sys.exit(1)

    # 1. Flask
    log("启动 Flask...")
    threading.Thread(
        target=lambda: flask_app.run(host=FLASK_HOST, port=FLASK_PORT, debug=False, use_reloader=False),
        daemon=True, name="Flask"
    ).start()

    import urllib.request
    for i in range(60):
        try:
            urllib.request.urlopen(APP_URL, timeout=1)
            break
        except Exception:
            time.sleep(0.2)
    else:
        log("Flask 启动超时")
        sys.exit(1)
    log("Flask 就绪")

    # 2. 监控
    try:
        start_mon(db.add_device_log)
        log("窗口监控已启动")
    except Exception:
        log_error()

    # 3. 托盘
    _tray = pystray.Icon(
        "TimeSlicer", create_tray_image(), u"时间切片系统",
        menu=pystray.Menu(
            pystray.MenuItem(u"显示窗口", on_tray_show, default=True),
            pystray.MenuItem(u"退出", on_tray_exit),
        ),
    )
    threading.Thread(target=_tray.run, daemon=True, name="Tray").start()
    log("系统托盘就绪")

    # 4. 通知
    threading.Thread(target=notify_loop, daemon=True, name="Notify").start()

    # 5. 启动 Edge 窗口
    launch_edge()

    # 6. Edge 存活监控
    threading.Thread(target=edge_watcher, daemon=True, name="EdgeWatch").start()

    # 7. 主线程挂起（托盘线程是 daemon，但主线程需保持存活）
    log("进入主循环（Ctrl+C 退出）")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log("收到中断信号")
    finally:
        kill_edge_app()
        if _stop_mon: _stop_mon()
        if _tray: _tray.stop()
        log("已退出")

if __name__ == "__main__":
    main()
