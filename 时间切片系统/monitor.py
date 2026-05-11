"""
monitor.py — 后台窗口监控线程：每10秒抓取活跃窗口，按分钟聚合写入 slices.db
依赖：pywin32（win32gui, win32process）+ psutil
"""
import time
import threading
import atexit
from datetime import datetime

try:
    import win32gui
    import win32process
    import psutil
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False


class WindowMonitor:
    """
    后台窗口监控器。
    设计：
    - 每 10 秒采样一次活跃窗口标题和进程名
    - 同一分钟内的多次采样合为一条记录（duration_seconds += 10）
    - 作为 daemon 线程运行，Flask 关闭时自动结束
    """

    def __init__(self, db_callback, interval=10):
        """
        db_callback: 可调用对象，接收 (timestamp, window_title, process_name, duration)
                     用于写入数据库
        interval:    采样间隔（秒），默认 10 秒
        """
        self.callback = db_callback
        self.interval = interval
        self._running = False
        self._thread = None
        self._minute_buffer = {}  # { "YYYY-MM-DD HH:MM": {title, process, duration} }

    def start(self):
        """启动后台监控线程"""
        if not HAS_WIN32:
            print("[Monitor] pywin32 未安装，跳过窗口监控")
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="WinMonitor")
        self._thread.start()
        print(f"[Monitor] 窗口监控已启动，采样间隔 {self.interval}s")

    def stop(self):
        """停止监控线程"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        # 刷出当前缓冲区
        self._flush_buffer()
        print("[Monitor] 窗口监控已停止")

    def _loop(self):
        """监控主循环"""
        while self._running:
            try:
                title, process = self._get_active_window_info()
                now = datetime.now()
                minute_key = now.strftime("%Y-%m-%d %H:%M:%S")

                # 同一分钟的采样累加时长
                if minute_key in self._minute_buffer:
                    self._minute_buffer[minute_key]["duration_seconds"] += self.interval
                else:
                    # 新分钟开始，先刷出上一分钟的缓冲
                    self._flush_buffer()
                    self._minute_buffer[minute_key] = {
                        "window_title": title,
                        "process_name": process,
                        "duration_seconds": self.interval,
                    }
            except Exception:
                # 监控异常不应影响主程序
                pass

            time.sleep(self.interval)

    def _flush_buffer(self):
        """将缓冲区的聚合记录写入数据库并清空"""
        for minute_key, data in list(self._minute_buffer.items()):
            try:
                self.callback(
                    timestamp=minute_key,
                    window_title=data["window_title"],
                    process_name=data["process_name"],
                    duration_seconds=min(data["duration_seconds"], 60),
                )
            except Exception as e:
                print(f"[Monitor] 写入失败: {e}")
        self._minute_buffer.clear()

    def _get_active_window_info(self):
        """获取当前活跃窗口的标题和进程名"""
        try:
            hwnd = win32gui.GetForegroundWindow()
            title = win32gui.GetWindowText(hwnd) or "(无标题)"

            # 获取进程名
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            process = psutil.Process(pid).name() if pid else "(未知)"

            return title, process
        except Exception:
            return "(未知)", "(未知)"


# ══════════════════════════════════════════════════════════
# 全局单例 & 优雅退出注册
# ══════════════════════════════════════════════════════════

_monitor_instance = None


def get_monitor(db_callback):
    """获取/创建全局监控器实例"""
    global _monitor_instance
    if _monitor_instance is None:
        _monitor_instance = WindowMonitor(db_callback)
    return _monitor_instance


def start_monitor(db_callback):
    """启动监控"""
    monitor = get_monitor(db_callback)
    monitor.start()
    # 注册退出清理
    atexit.register(monitor.stop)
    return monitor


def stop_monitor():
    """停止监控"""
    global _monitor_instance
    if _monitor_instance:
        _monitor_instance.stop()
        _monitor_instance = None
