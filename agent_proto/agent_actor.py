# -*- coding: utf-8 -*-
"""
agent_actor.py — 行动执行器
Phase 3: 终端彩色输出 + Windows 原生通知 + proto_log.md 写入

依赖: plyer（Windows 通知）
"""
import os
import sys
import time
from datetime import datetime
from threading import Lock

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(BASE_DIR, "proto_log.md")

_write_lock = Lock()

# Windows 通知
try:
    from plyer import notification
    HAS_NOTIFY = True
except Exception:
    HAS_NOTIFY = False

# ── ANSI 颜色 ──────────────────────────────────────────────

COLORS = {
    "recorder":  "\033[36m",  # 青色
    "companion": "\033[32m",  # 绿色
    "scheduler": "\033[33m",  # 黄色
    "system":    "\033[37m",  # 白色
    "reset":     "\033[0m",
    "bold":      "\033[1m",
    "dim":       "\033[2m",
}


# ═══════════════════════════════════════════════════════════
# 核心动作
# ═══════════════════════════════════════════════════════════

_last_actor_speak = 0.0  # 全局最小间隔兜底（P0-3）

def speak(message, persona="recorder"):
    """终端彩色输出 + Windows 通知 + proto_log.md 写入。"""
    global _last_actor_speak
    # P0-3: 最小间隔兜底（3 秒），主力防护在 agent_loop 的 P0-1
    now = time.time()
    if now - _last_actor_speak < 3.0:
        return
    _last_actor_speak = now

    color = COLORS.get(persona, COLORS["system"])
    reset = COLORS["reset"]
    bold = COLORS["bold"]
    dim = COLORS["dim"]
    timestamp = datetime.now().strftime("%H:%M:%S")

    # 终端彩色输出
    print(f"\n{color}{bold}┌─ Agent [{persona}] ──────────────────────────{reset}")
    print(f"{color}│ {message}{reset}")
    print(f"{color}└{dim} {timestamp}{reset}\n")
    sys.stdout.flush()

    # Windows 原生通知
    _notify(persona, message)

    # 写入日志
    _write_log(persona, message, timestamp)


def record_slice(context, message):
    """预留：向 v2 slices.db 写入切片记录。
    MVP 阶段仅记录到 proto_log.md，不写入 v2 数据库。

    参数:
        context: Observer + Memory 提供的上下文字典
        message: Thinker 生成的话术（作为切片描述）
    """
    ts = datetime.now().strftime("%H:%M:%S")
    win = context.get("window", {})
    app = f"{win.get('process', '?')} - {win.get('title', '?')}"
    print(f"{COLORS['dim']}[Actor] 切片已记录（仅日志）: [{app}] {message}{COLORS['reset']}")

    _write_log("recorder", f"[AUTO-SLICE] {app}: {message}", ts)


def update_status(color=None, breath_rate=None):
    """预留：更新悬浮窗状态（颜色/呼吸频率）。
    MVP 阶段仅打印到终端，后续换为 IPC/WebSocket 通知。
    """
    parts = []
    if color:
        parts.append(f"color={color}")
    if breath_rate:
        parts.append(f"breath={breath_rate}")
    if parts:
        print(f"{COLORS['dim']}[Actor] status: {', '.join(parts)}{COLORS['reset']}")


# ═══════════════════════════════════════════════════════════
# 内部
# ═══════════════════════════════════════════════════════════

def _notify(persona, message):
    """弹出 Windows 原生通知"""
    if not HAS_NOTIFY:
        return
    try:
        persona_labels = {"recorder": "记录伙伴", "companion": "陪伴者", "scheduler": "调度助手"}
        title = persona_labels.get(persona, "Agent")
        notification.notify(
            title=title,
            message=message[:120],
            app_name="Agent Proto",
            timeout=8,
        )
    except Exception:
        pass  # 通知失败不影响主流程


def _write_log(persona, message, timestamp):
    """追加一行到 proto_log.md（线程安全）"""
    with _write_lock:
        try:
            # 首次写入时添加文件头
            if not os.path.exists(LOG_PATH) or os.path.getsize(LOG_PATH) == 0:
                with open(LOG_PATH, "a", encoding="utf-8") as f:
                    f.write("# Proto Log — Agent Loop 运行记录\n\n")

            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(f"## {datetime.now().isoformat(timespec='seconds')}\n")
                f.write(f"- **Persona**: {persona}\n")
                f.write(f"- **Message**: {message}\n\n")
        except Exception:
            pass  # 日志写入失败不应影响主循环


# ═══════════════════════════════════════════════════════════
# 独立测试
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    print("── Actor 独立测试 ──\n")
    speak("刚才在 VS Code 忙了 20 分钟，要记一下吗？", "recorder")
    speak("今天好像有点紧绷，需要我陪聊聊吗？", "companion")
    update_status("blue", "slow")
    record_slice(
        {"window": {"process": "Cursor.exe", "title": "agent_loop.py"}},
        "自动记录：编码 agent_loop.py"
    )
    print(f"日志位置: {LOG_PATH}")
