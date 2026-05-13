# -*- coding: utf-8 -*-
"""
agent_loop.py — Agent 主循环：Observer → Thinker → Actor
Phase 1: Observer 层 — 确定性数据采集 + 事件检测 + 终端输出验证

依赖: pywin32, psutil, pyperclip（可选）
运行: py agent_proto/agent_loop.py
"""
import sys
import time
import threading
import ctypes
from datetime import datetime

from agent_bridge import bridge

# ═══════════════════════════════════════════════════════════
# Thinker 集成（Phase 2）
# ═══════════════════════════════════════════════════════════

try:
    from agent_thinker import Thinker, route_persona
    HAS_THINKER = True
except ImportError:
    HAS_THINKER = False
    route_persona = lambda e, c: "recorder"  # fallback
    print("[Agent] agent_thinker.py 未找到，Thinker 不可用")

try:
    from agent_memory import enrich_context
    from agent_actor import speak as actor_speak, record_slice as actor_record_slice
    HAS_MEMORY = True
except ImportError:
    HAS_MEMORY = False
    print("[Agent] agent_memory/agent_actor 未找到，记忆层不可用")

# ═══════════════════════════════════════════════════════════
# 环境检测
# ═══════════════════════════════════════════════════════════

try:
    import win32gui
    import win32process
    import psutil
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False
    print("[Observer] pywin32/psutil 未安装，窗口监控不可用")

try:
    import pyperclip
    HAS_CLIPBOARD = True
except ImportError:
    HAS_CLIPBOARD = False
    print("[Observer] pyperclip 未安装，剪贴板监听不可用")

# ═══════════════════════════════════════════════════════════
# P2-3: 系统通知监听探测
# ═══════════════════════════════════════════════════════════

HAS_NOTIFICATION_LISTENER = False

def _try_init_notification_listener():
    """探测 Windows 通知监听 API 是否可用（P2-3）。

    winrt 方案需要: pip install winrt + Windows 设置中授予通知监听权限。
    不可用时输出清晰说明，预留接口供后续启用。
    """
    global HAS_NOTIFICATION_LISTENER
    try:
        import winrt.windows.ui.notifications as wun  # noqa: F401
        import winrt.windows.applicationmodel as wam   # noqa: F401
        HAS_NOTIFICATION_LISTENER = True
        print("[启动] 系统通知监听已启用（winrt）")
    except ImportError:
        print("[P2-3] 系统通知监听不可用：winrt 未安装")
        print("       如需启用，运行以下命令：")
        print("       pip install winrt-Windows.Foundation winrt-Windows.UI.Notifications winrt-Windows.ApplicationModel")
        print("       然后：Windows 设置 → 隐私和安全性 → 通知 → 允许应用访问通知")
        print("       当前版本跳过通知监听，Agent 其他功能正常")
    except Exception as e:
        print(f"[P2-3] 系统通知监听初始化异常: {e}")


# ═══════════════════════════════════════════════════════════
# 空闲检测 — Win32 GetLastInputInfo
# ═══════════════════════════════════════════════════════════

class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint),
        ("dwTime", ctypes.c_uint),
    ]


def get_idle_duration():
    """返回用户空闲时长（秒），调用 Win32 GetLastInputInfo。
    兼容无 win32 环境：返回 0。
    """
    try:
        lii = LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
            tick_count = ctypes.windll.kernel32.GetTickCount()
            return (tick_count - lii.dwTime) / 1000.0
    except Exception:
        pass
    return 0.0

# ═══════════════════════════════════════════════════════════
# 时段定义
# ═══════════════════════════════════════════════════════════

def get_period(hour):
    """根据小时返回时段标签"""
    if 6 <= hour < 12:
        return "morning"      # 上午
    elif 12 <= hour < 18:
        return "afternoon"    # 下午
    elif 18 <= hour < 23:
        return "evening"      # 晚上
    else:
        return "night"        # 深夜 23:00–06:00


def get_time_context():
    """返回当前时间上下文"""
    now = datetime.now()
    h = now.hour
    wd = now.weekday()  # 0=周一, 6=周日
    period = get_period(h)
    return {
        "datetime": now.isoformat(timespec="seconds"),
        "hour": h,
        "weekday": wd,
        "period": period,
        "is_work_hour": 9 <= h < 18 and wd < 5,
        "is_night": period == "night",
    }

# ═══════════════════════════════════════════════════════════
# 活跃窗口采集
# ═══════════════════════════════════════════════════════════

def get_active_window_info():
    """获取当前活跃窗口标题和进程名。
    无 win32 环境时返回占位值。
    """
    if not HAS_WIN32:
        return {"title": "(不可用)", "process": "(不可用)"}
    try:
        hwnd = win32gui.GetForegroundWindow()
        title = win32gui.GetWindowText(hwnd) or "(无标题)"
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        process = psutil.Process(pid).name() if pid else "(未知)"
        return {"title": title, "process": process}
    except Exception:
        return {"title": "(错误)", "process": "(错误)"}

# ═══════════════════════════════════════════════════════════
# Observer — 采样线程 + 事件检测
# ═══════════════════════════════════════════════════════════

class Observer:
    """后台采样器：每 10 秒采集窗口/空闲/时段信息，检测事件推入 buffer。

    状态管理：
    - last_window_key: 上次活跃窗口标识 "process|title"
    - last_period:     上次时段标签
    - last_idle_state: 上次空闲状态（True=空闲 / False=活跃）
    - idle_threshold:  空闲判定阈值（秒），默认 300（5 分钟）
    """

    # 浏览器进程名集合
    BROWSERS = {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe"}

    def __init__(self, buffer, lock):
        self.buffer = buffer
        self.lock = lock
        self.last_window_key = None
        self.last_window_start = None  # 当前窗口首次采样的时间戳
        self.last_period = None
        self.last_idle_state = False
        self.idle_threshold = 300
        # URL 去重：{page_title: last_event_timestamp}
        self._last_url_events = {}

        # 初始化基准状态，避免启动时误报窗口切换/时段切换
        win = get_active_window_info()
        self.last_window_key = f"{win['process']}|{win['title']}"
        self.last_window_start = datetime.now()
        tctx = get_time_context()
        self.last_period = tctx["period"]
        self.last_idle_state = get_idle_duration() > self.idle_threshold

    def sample(self):
        """单次采样：采集当前状态 → 比对 → 检测到事件则推入共享 buffer"""
        now = datetime.now()
        win = get_active_window_info()
        idle_sec = get_idle_duration()
        tctx = get_time_context()
        is_idle = idle_sec > self.idle_threshold

        events = []

        # 1) 窗口切换检测
        current_key = f"{win['process']}|{win['title']}"
        if current_key != self.last_window_key:
            # 计算上一窗口持续时长
            prev_duration = ""
            if self.last_window_start:
                delta = (now - self.last_window_start).total_seconds()
                if delta >= 60:
                    prev_duration = f"{int(delta / 60)} 分钟"
                else:
                    prev_duration = f"{int(delta)} 秒"
            events.append({
                "type": "window_switch",
                "timestamp": now.isoformat(timespec="seconds"),
                "from": self.last_window_key,
                "to": current_key,
                "prev_duration": prev_duration,
            })
            self.last_window_key = current_key
            self.last_window_start = now

        # 2) 空闲状态变化
        if is_idle != self.last_idle_state:
            events.append({
                "type": "idle" if is_idle else "idle_return",
                "timestamp": now.isoformat(timespec="seconds"),
                "idle_seconds": round(idle_sec),
            })
            self.last_idle_state = is_idle

        # 3) 时段切换
        if tctx["period"] != self.last_period:
            events.append({
                "type": "period_change",
                "timestamp": now.isoformat(timespec="seconds"),
                "from": self.last_period,
                "to": tctx["period"],
            })
            self.last_period = tctx["period"]

        # 4) 浏览器 URL 检测（P2-2）
        url_event = self._detect_url(win, now)
        if url_event:
            events.append(url_event)

        if events:
            with self.lock:
                self.buffer.extend(events)

    def _detect_url(self, win, now):
        """检测浏览器窗口标题中的页面信息，生成 url_change 事件。

        同一页面标题每 5 分钟最多记录一次。
        """
        proc = win.get("process", "").lower()
        if proc not in self.BROWSERS:
            return None
        title = win.get("title", "")
        if not title or title == "(无标题)":
            return None
        # 去除浏览器后缀
        page_title = _clean_browser_title(title)
        if not page_title:
            return None
        # 去重：同标题 5 分钟内不重复
        last_ts = self._last_url_events.get(page_title)
        if last_ts is not None and (now - last_ts).total_seconds() < 300:
            return None
        self._last_url_events[page_title] = now
        # 清理旧条目（> 1 小时的移除）
        cutoff = now.timestamp() - 3600
        self._last_url_events = {
            k: v for k, v in self._last_url_events.items()
            if isinstance(v, datetime) and v.timestamp() > cutoff
        }
        return {
            "type": "url_change",
            "timestamp": now.isoformat(timespec="seconds"),
            "browser": proc,
            "page_title": page_title,
            "sensitive": True,
        }

    def get_context(self):
        """组装完整上下文 dict（供 Thinker/Actor 使用）"""
        win = get_active_window_info()
        tctx = get_time_context()
        idle_sec = get_idle_duration()
        # 当前窗口持续时长
        current_dur = ""
        if self.last_window_start:
            delta = (datetime.now() - self.last_window_start).total_seconds()
            if delta >= 60:
                current_dur = f"{int(delta / 60)} 分钟"
            else:
                current_dur = f"{int(delta)} 秒"
        return {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "window": win,
            "idle_seconds": round(idle_sec),
            "time": tctx,
            "current_window_duration": current_dur,
        }

# ═══════════════════════════════════════════════════════════
# 剪贴板轮询线程
# ═══════════════════════════════════════════════════════════

def clipboard_poller(buffer, lock, interval=2.0):
    """后台线程：每 interval 秒检测剪贴板变化，全量记录（上限 5000 字符）。

    隐私：事件标记 sensitive=True，仅本地 9B 处理，不落盘。
    """
    if not HAS_CLIPBOARD:
        return
    last_text = ""
    MAX_LEN = 5000  # 单次记录上限，防止大文件撑爆内存
    while True:
        try:
            text = pyperclip.paste() or ""
            # 去重：内容相同则跳过
            if text != last_text and len(text) > 0:
                last_text = text
                clipped = text[:MAX_LEN]
                with lock:
                    buffer.append({
                        "type": "clipboard_change",
                        "timestamp": datetime.now().isoformat(timespec="seconds"),
                        "content": clipped,
                        "length": len(text),
                        "truncated": len(text) > MAX_LEN,
                        "sensitive": True,  # Thinker 必须走本地 9B
                    })
        except Exception:
            pass
        time.sleep(interval)

# ═══════════════════════════════════════════════════════════
# IDE 自动切换检测（Fix 3）
# ═══════════════════════════════════════════════════════════

IDE_KEYWORDS = [
    "Cursor", "VS Code", "Visual Studio Code", "PyCharm",
    "IntelliJ IDEA", "Android Studio", "Eclipse", "Sublime Text",
    "Vim", "Neovim", "JetBrains",
]


def _is_ide_window(process_name, window_title):
    """检测窗口是否为 IDE"""
    combined = f"{process_name} {window_title}".lower()
    for kw in IDE_KEYWORDS:
        if kw.lower() in combined:
            return True
    # 特殊：devenv.exe (Visual Studio)
    if process_name.lower() == "devenv.exe":
        return True
    return False


# ═══════════════════════════════════════════════════════════
# 格式化输出
# ═══════════════════════════════════════════════════════════

PERIOD_LABELS = {
    "morning": "上午", "afternoon": "下午",
    "evening": "晚上", "night": "深夜",
}
EVENT_LABELS = {
    "window_switch": "窗口切换",
    "idle":          "进入空闲",
    "idle_return":   "空闲恢复",
    "period_change": "时段切换",
    "clipboard_change": "剪贴板变化",
    "heartbeat":     "5分钟心跳",
}

def format_context(ctx):
    """格式化上下文 dict 为可读终端输出"""
    t = ctx["time"]
    w = ctx["window"]
    period_cn = PERIOD_LABELS.get(t["period"], t["period"])
    lines = [
        f"  时间: {ctx['timestamp']} | {period_cn} | 星期{t['weekday']+1}",
        f"  窗口: [{w['process']}] {w['title'][:60]}",
        f"  空闲: {ctx['idle_seconds']}s",
    ]
    return "\n".join(lines)


def _clean_browser_title(title):
    """从浏览器窗口标题中提取页面标题，去除浏览器名称后缀"""
    import re
    suffixes = [
        r"\s*[-–—]\s*Google Chrome$",
        r"\s*[-–—]\s*Microsoft\s*Edge$",
        r"\s*[-–—]\s*Mozilla Firefox$",
        r"\s*[-–—]\s*Brave$",
        r"\s*[-–—]\s*Opera$",
        r"\s*[-–—]\s*Chromium$",
    ]
    for pat in suffixes:
        cleaned = re.sub(pat, "", title, flags=re.IGNORECASE).strip()
        if cleaned != title:
            return cleaned
    return title.strip()


def _parse_duration_seconds(dur_str):
    """解析 'X 分钟' 或 'X 秒' 格式的时长字符串，返回秒数。无法解析返回 None。"""
    if not dur_str:
        return None
    try:
        if "分钟" in dur_str:
            return int(dur_str.replace("分钟", "").strip()) * 60
        elif "秒" in dur_str:
            return int(dur_str.replace("秒", "").strip())
    except (ValueError, AttributeError):
        pass
    return None


def _print_thinker_result(r):
    """格式化打印 Thinker 决策结果"""
    decision = "SPEAK" if r["should_speak"] else "SILENT"
    level = r.get("autonomy_level", "L?")
    elapsed = r.get("elapsed_ms", 0)
    print(f"  [Thinker] {decision} | {level} | {elapsed:.0f}ms")
    if r["should_speak"]:
        print(f"  [Thinker 话术] {r['message']}")
    if r.get("reason"):
        print(f"  [Thinker 理由] {r['reason']}")

# ═══════════════════════════════════════════════════════════
# 主循环
# ═══════════════════════════════════════════════════════════

def run_agent(thinker=None):
    """启动 Agent 主循环（可被 agent_ui.py 以线程调用）。

    Agent 通过 agent_bridge.bridge 信号与 UI 通信（线程安全）。
    参数:
        thinker: 可选外部 Thinker 实例（共享给聊天窗使用）
    """
    # 确保管道输出不缓冲、编码正确
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    try:
        sys.stdout = open(sys.stdout.fileno(), 'w', encoding='utf-8', buffering=1)
    except Exception:
        pass  # 管道环境可能失败，忽略

    print("=" * 56)
    print("  Agent Loop 原型 — Phase 4: 完整闭环 + 悬浮窗")
    print("  Observer → Memory → Thinker(9B) → Actor → UI")
    print("  采样 10s | 空闲阈值 5min | 兜底 5min | Ctrl+C 退出")
    print("=" * 56)
    print()

    buffer = []
    lock = threading.Lock()
    observer = Observer(buffer, lock)

    # ── 初始化 Thinker + 健康检查 ──
    if thinker is None and HAS_THINKER:
        try:
            thinker = Thinker()
            test_resp = thinker.client.chat.completions.create(
                model=thinker.model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=4, timeout=5,
            )
            test_text = test_resp.choices[0].message.content.strip()[:20]
            print(f"[启动] Thinker 就绪 | 9B 端点在线 ({test_text})")
        except Exception as e:
            print(f"[警告] Thinker 连接失败: {e}")
            print("       Agent 将以静默模式运行（仅数据采集，无主动发言）")
            print("       [启动] 请确认 llama.cpp 已启动且 llm_config.yaml 配置正确")
            thinker = None
    elif thinker:
        print(f"[启动] Thinker 已共享（来自 UI 线程）")

    # ── 记忆摘要 ──
    if HAS_MEMORY:
        try:
            today = enrich_context({"time": get_time_context(), "window": {"title": "", "process": ""}})
            print(f"[记忆] 今日切片: {today.get('today_slice_count', '?')} | "
                  f"上次记录: {today.get('time_ago', '?')}前 | "
                  f"待办任务: {today.get('pending_task_count', '?')}")
            print(f"[记忆] 近2h活动: {today.get('recent_activity_summary', '?')}")
        except Exception as e:
            print(f"[记忆] 摘要获取失败: {e}")
    print()

    # 启动剪贴板轮询线程
    if HAS_CLIPBOARD:
        cp_thread = threading.Thread(
            target=clipboard_poller, args=(buffer, lock),
            daemon=True, name="Clipboard"
        )
        cp_thread.start()
        print("[启动] 剪贴板监听（2s 间隔）")

    # 启动 Observer 采样线程
    def observer_loop():
        while True:
            observer.sample()
            time.sleep(10)

    obs_thread = threading.Thread(
        target=observer_loop, daemon=True, name="Observer"
    )
    obs_thread.start()
    print("[启动] Observer 采样（10s 间隔）")

    # P2-3: 系统通知监听 — 探测 winrt 可用性
    _try_init_notification_listener()

    # 主循环：轮询 buffer + 5 分钟兜底
    last_event_time = time.time()
    last_speak_time = 0           # 上次说话时间戳，用于冷却期
    SPEAK_COOLDOWN = 10 * 60      # 发言冷却期：10 分钟
    MIN_WINDOW_DURATION = 2 * 60  # 窗口最短持续时间：2 分钟

    # IDE 自动切换：连续使用 IDE 15 分钟后降低呼吸频率（不完全休眠）
    ide_since = None
    ide_sleep_sent = False
    IDE_THRESHOLD = 15 * 60

    print("[启动] 主循环，等待事件...\n")

    try:
        while True:
            # 取出 buffer 中的事件
            with lock:
                if buffer:
                    events = buffer[:]
                    buffer.clear()
                else:
                    events = []

            # ── P0-1: 批次级冷却检查（for 循环之前）──
            batch_in_cooldown = (time.time() - last_speak_time) < SPEAK_COOLDOWN
            batch_spoke = False  # 同一批次只允许一次 speak

            if batch_in_cooldown and events:
                actionable = [e for e in events if e["type"] != "clipboard_change"]
                if actionable:
                    remaining = int(SPEAK_COOLDOWN - (time.time() - last_speak_time))
                    print(f"[冷却] 距上次发言 {remaining // 60} 分 {remaining % 60} 秒，"
                          f"跳过 {len(actionable)} 个事件\n")

            for ev in events:
                ctx = observer.get_context()
                ctx["event_type"] = ev["type"]
                if ev["type"] == "window_switch":
                    ctx["previous_window"] = ev["from"]
                    ctx["window_duration"] = ev.get("prev_duration", "?")
                elif ev["type"] == "period_change":
                    ctx["previous_period"] = ev["from"]
                elif ev["type"] == "clipboard_change":
                    # 剪贴板内容加入上下文（脱敏交给 Thinker）
                    ctx["clipboard_content"] = ev.get("content", "")[:500]
                    ctx["clipboard_length"] = ev.get("length", 0)

                # ── IDE 检测（不依赖详细日志）──
                if ev["type"] == "window_switch":
                    to_key = ev["to"]
                    parts = to_key.split("|", 1)
                    to_proc = parts[0] if parts else ""
                    to_title = parts[1] if len(parts) > 1 else ""
                    if _is_ide_window(to_proc, to_title):
                        if ide_since is None:
                            ide_since = time.time()
                            ide_sleep_sent = False
                            print(f"  [IDE] 检测到 IDE 窗口，{IDE_THRESHOLD // 60} 分钟后降低呼吸")
                    else:
                        if ide_since is not None:
                            bridge.mode_requested.emit("accompany")
                            print("  [IDE] 离开 IDE → 自动恢复陪伴态")
                            ide_since = None
                            ide_sleep_sent = False

                # ── 记忆增强 ──
                if HAS_MEMORY:
                    enrich_context(ctx)

                # ── 事件过滤 ──
                skip_reason = None
                if ev["type"] == "window_switch":
                    dur_str = ev.get("prev_duration", "")
                    dur_sec = _parse_duration_seconds(dur_str)
                    if dur_sec is not None and dur_sec < MIN_WINDOW_DURATION:
                        skip_reason = f"窗口仅活跃 {dur_str}，跳过"

                # ── Thinker + Actor 管道 ──
                if thinker and not skip_reason and not batch_in_cooldown and not batch_spoke:
                    if 0 <= datetime.now().hour < 6:
                        if ev["type"] != "clipboard_change":
                            print("  [Agent] SILENT | L0 | 凌晨静默\n")
                    else:
                        try:
                            persona = route_persona(ev["type"], ctx)
                            result = thinker.think(ctx, persona)
                            last_event_time = time.time()

                            # 仅在 Thinker 产出有意义的决策时输出日志
                            if result["should_speak"] or result["autonomy_level"] in ("L2", "L3"):
                                label = EVENT_LABELS.get(ev["type"], ev["type"])
                                print(f"[{label}] {ev['timestamp']}")
                                _print_thinker_result(result)

                            if result["should_speak"]:
                                bridge.status_updated.emit("orange", "fast",
                                                          result["message"][:40])
                                bridge.message_added.emit(persona, result["message"])
                                actor_speak(result["message"], persona)
                                last_speak_time = time.time()
                                batch_spoke = True
                            elif result["autonomy_level"] == "L0":
                                bridge.status_updated.emit("blue", "slow", "")

                            if result["autonomy_level"] in ("L2", "L3"):
                                actor_record_slice(ctx, result.get("message", ""))
                                print()
                        except Exception as e:
                            print(f"  [Thinker 错误] {e}\n")
                elif skip_reason:
                    pass  # 静默跳过短暂窗口，不刷日志

            # ── IDE 自动休眠阈值检查（Fix 3）──
            if ide_since is not None and not ide_sleep_sent \
                    and (time.time() - ide_since) >= IDE_THRESHOLD:
                bridge.status_updated.emit("blue", "slow", "编码中，静默陪伴...")
                print("  [IDE] 编码超过 15 分钟 → 降低呼吸频率（不进入休眠）\n")
                ide_sleep_sent = True

            # 5 分钟兜底心跳
            if time.time() - last_event_time >= 300:
                ctx = observer.get_context()
                ctx["event_type"] = "heartbeat"
                print(f"[心跳] ─ {ctx['timestamp']}")
                print(format_context(ctx))

                # P0-2: 心跳也检查窗口时长
                dur_str = ctx.get("current_window_duration", "")
                dur_sec = _parse_duration_seconds(dur_str)
                heartbeat_skip = (dur_sec is not None and dur_sec < MIN_WINDOW_DURATION)

                if HAS_MEMORY:
                    enrich_context(ctx)

                if thinker:
                    if 0 <= datetime.now().hour < 6:
                        print("  [Agent] SILENT | L0 | 凌晨静默（0-6时）")
                    elif time.time() - last_speak_time < SPEAK_COOLDOWN:
                        remaining = int(SPEAK_COOLDOWN - (time.time() - last_speak_time))
                        print(f"  [冷却] 距上次发言 {remaining // 60} 分 {remaining % 60} 秒，"
                              f"心跳跳过 Thinker")
                    elif heartbeat_skip:
                        print(f"  [过滤] 心跳跳过：当前窗口仅活跃 {dur_str}")
                    else:
                        try:
                            persona = route_persona("heartbeat", ctx)
                            result = thinker.think(ctx, persona)
                            _print_thinker_result(result)

                            if result["should_speak"]:
                                bridge.status_updated.emit("orange", "fast",
                                                          result["message"][:40])
                                bridge.message_added.emit(persona, result["message"])
                            else:
                                bridge.status_updated.emit("blue", "slow", "")

                            if result["should_speak"]:
                                actor_speak(result["message"], persona)
                                last_speak_time = time.time()
                        except Exception as e:
                            print(f"  [Thinker 错误] {e}")
                print()
                last_event_time = time.time()

            time.sleep(1)

    except KeyboardInterrupt:
        print("\n[Agent] 收到退出信号，Observer 已停止。")


def main():
    """兼容旧用法：终端直接运行 agent_loop.py"""
    run_agent()


if __name__ == "__main__":
    main()
