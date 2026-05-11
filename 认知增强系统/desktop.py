"""
desktop.py — 桌面应用入口：Edge --app 原生窗口 + pystray 系统托盘 + plyer 通知
启动方式：python desktop.py  或  双击 start.bat
"""
import os, sys, io, threading, time, subprocess, signal, traceback
from datetime import datetime, timedelta
from pathlib import Path

# ── 确保 stdout 支持 UTF-8 ──────────────────────────────
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# ── 基础路径 ──────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"

# ── 日志 ──────────────────────────────────────────────────
LOGS_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOGS_DIR / f"desktop_{datetime.now():%Y%m%d_%H%M%S}.log"

def log(msg):
    line = f"[{datetime.now():%H:%M:%S}] {msg}"
    try:
        print(line, flush=True)
    except Exception:
        pass  # 控制台写入失败时静默忽略
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
# 配置
# ══════════════════════════════════════════════════════════
FLASK_HOST = "127.0.0.1"
FLASK_PORT = 5000
APP_URL = f"http://{FLASK_HOST}:{FLASK_PORT}"
APP_NAME = u"认知增强系统"
SETTINGS_FILE = DATA_DIR / "settings.json"
FIRST_CLOSE_MARKER = DATA_DIR / ".first_close_shown"
LAST_DB_CLEANUP = DATA_DIR / ".last_db_cleanup"

EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
if not os.path.exists(EDGE_PATH):
    EDGE_PATH = r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"
if not os.path.exists(EDGE_PATH):
    EDGE_PATH = "msedge.exe"


# ══════════════════════════════════════════════════════════
# 日志清理（第三阶段 #6）
# ══════════════════════════════════════════════════════════

def cleanup_old_logs(days=7):
    """清理 logs/ 目录下超过 N 天的 .log 文件"""
    cutoff = time.time() - days * 86400
    cleaned = 0
    for f in LOGS_DIR.glob("*.log"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
                cleaned += 1
        except OSError:
            pass
    if cleaned:
        log(f"日志清理：删除 {cleaned} 个旧日志文件")


# ══════════════════════════════════════════════════════════
# 数据库定期清理（第三阶段 #12）
# ══════════════════════════════════════════════════════════

def periodic_db_cleanup():
    """启动时检查是否需要清理 >30 天的设备日志"""
    try:
        if LAST_DB_CLEANUP.exists():
            age = time.time() - LAST_DB_CLEANUP.stat().st_mtime
            if age < 7 * 86400:  # 7 天内已经清理过
                return
        deleted = db.cleanup_old_device_logs()
        LAST_DB_CLEANUP.touch()
        if deleted:
            log(f"DB清理：删除 {deleted} 条旧设备日志")
    except Exception:
        log_error()


# ══════════════════════════════════════════════════════════
# Flask 实例导入
# ══════════════════════════════════════════════════════════

import database as db
from app import app, init_rules_endpoint, start_rule_timer, start_auto_slice_timer, start_recurring_tasks_timer
from monitor import start_monitor, stop_monitor
from auto_slice_generator import generate_auto_slices


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
    global _edge_proc
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


def on_tray_quick_slice(icon, item):
    """托盘右键 → 快速记录：打开一个超轻量 Edge 窗口"""
    try:
        subprocess.Popen(
            [EDGE_PATH, f"--app={APP_URL}/quick-slice",
             "--window-size=350,300", "--new-window"],
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
    except Exception as e:
        log(f"快速记录窗口启动失败: {e}")


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
# 第一次关闭提示（第三阶段 #7）
# ══════════════════════════════════════════════════════════

def show_first_close_notification():
    if FIRST_CLOSE_MARKER.exists():
        # 检查设置中是否关闭了提示
        settings = _load_settings()
        if settings.get("hide_close_tip"):
            return
    else:
        FIRST_CLOSE_MARKER.touch()
    try:
        plyer_notify.notify(
            title=APP_NAME,
            message=u"应用仍在后台运行，可通过系统托盘重新打开或退出",
            app_name=APP_NAME, timeout=8)
    except Exception:
        pass


def _load_settings():
    try:
        if SETTINGS_FILE.exists():
            import json
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def save_settings(data):
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        import json
        # 合并现有设置
        current = _load_settings()
        current.update(data)
        SETTINGS_FILE.write_text(json.dumps(current, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
    except Exception:
        pass


# ══════════════════════════════════════════════════════════
# 整点通知（第三阶段 #8 修复）
# ══════════════════════════════════════════════════════════

_last_hourly = None

def notify_loop():
    global _last_hourly
    # 等待到下一个整点（不补发已过去的整点）
    now = datetime.now()
    next_hour = (now.minute + 1) % 60  # 分钟归零需要等下一个整点
    if next_hour == 0:
        wait_seconds = (60 - now.second)  # 当前分钟结束后就是整点
    else:
        wait_seconds = (60 - now.minute) * 60 - now.second
    log(f"整点通知：{wait_seconds:.0f} 秒后开始")
    time.sleep(wait_seconds)

    while True:
        try:
            now = datetime.now()
            h = now.hour
            if 8 <= h <= 22:
                _last_hourly = now
                plyer_notify.notify(
                    title=u"⏱ 该切一片了",
                    message=u"现在是 %d:00 — 记录一下当前状态吧！" % h,
                    app_name=APP_NAME, timeout=5)
        except Exception:
            pass
        time.sleep(3600)  # 每小时一次


# ══════════════════════════════════════════════════════════
# Edge 进程监控
# ══════════════════════════════════════════════════════════

def edge_watcher():
    """每 3 秒检查 Edge 是否还活着"""
    while True:
        time.sleep(3)
        global _edge_proc
        if _edge_proc and _edge_proc.poll() is not None:
            log("Edge 窗口已关闭")
            _edge_proc = None
            # 首次关闭提示
            show_first_close_notification()


# ══════════════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════════════

def main():
    global _tray, _stop_mon

    # 清理旧日志
    cleanup_old_logs()

    # 初始化数据库
    try:
        db.init_db()
        init_rules_endpoint()
        log("数据库初始化完成")
    except Exception:
        log_error()
        sys.exit(1)

    # 检测昨日是否已生成自动切片
    try:
        yesterday = (datetime.now() - timedelta(days=1)).date()
        existing = db.get_auto_slices_count_for_date(yesterday)
        if existing == 0:
            count = generate_auto_slices(yesterday, db)
            log(f"补生成昨日自动切片：{count} 条")
    except Exception:
        log_error()

    # 生成今日重复任务
    try:
        count = db.generate_recurring_tasks_today()
        if count:
            log(f"重复任务生成：{count} 条")
    except Exception:
        log_error()

    # 1. Flask 后台线程
    log("启动 Flask...")
    threading.Thread(
        target=lambda: app.run(host=FLASK_HOST, port=FLASK_PORT, debug=False, use_reloader=False),
        daemon=True, name="Flask"
    ).start()

    # 等待 Flask 就绪
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

    # 2. 窗口监控
    try:
        monitor = start_monitor(db.add_device_log)
        _stop_mon = stop_monitor
        log("窗口监控已启动")
    except Exception:
        log_error()

    # 3. 系统托盘
    _tray = pystray.Icon(
        "CogEnhancer", create_tray_image(), APP_NAME,
        menu=pystray.Menu(
            pystray.MenuItem(u"显示窗口", on_tray_show, default=True),
            pystray.MenuItem(u"⚡ 快速记录", on_tray_quick_slice),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(u"退出", on_tray_exit),
        ),
    )
    threading.Thread(target=_tray.run, daemon=True, name="Tray").start()
    log("系统托盘就绪")

    # 4. 定期 DB 清理
    try:
        periodic_db_cleanup()
    except Exception:
        log_error()

    # 4.5 规则引擎定时器
    try:
        start_rule_timer()
        log("规则引擎定时器就绪")
    except Exception:
        log_error()

    # 4.6 自动切片定时器
    try:
        start_auto_slice_timer()
        log("自动切片定时器就绪")
    except Exception:
        log_error()

    # 4.7 重复任务定时器
    try:
        start_recurring_tasks_timer()
        log("重复任务定时器就绪")
    except Exception:
        log_error()

    # 5. 整点通知
    threading.Thread(target=notify_loop, daemon=True, name="Notify").start()

    # 6. 启动 Edge 窗口
    launch_edge()

    # 7. Edge 存活监控
    threading.Thread(target=edge_watcher, daemon=True, name="EdgeWatch").start()

    # 8. 主线程挂起
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
