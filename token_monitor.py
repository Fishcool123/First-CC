#!/usr/bin/env python3
"""
token_monitor.py — Claude Code Token 用量实时监控工具
======================================================
用途: 实时监控和统计分析 Claude Code 的 token 消耗
依赖: Python 3.8+（仅标准库）
运行方式:
  - 状态栏模式（默认）:    py.exe token_monitor.py
  - 交互报告模式:          py.exe token_monitor.py --report
  - 指定项目目录:          py.exe token_monitor.py --project "D:/Academic"
  - 指定天数范围:          py.exe token_monitor.py --report --days 7
输入: stdin JSON（状态栏模式）或命令行参数
输出: 状态栏字符串 或 格式化统计报告
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------- Windows UTF-8 终端兼容 ----------
if sys.platform == "win32":
    sys.stdout = open(sys.stdout.fileno(), mode="w", encoding="utf-8",
                       errors="replace", buffering=1)

# ---------- 常量 ----------
CN_TZ = timezone(offset=timedelta(hours=8))

# 各模型近似价格（美元 / 百万 token）⚠️ 待验证: 基于公开定价估算
MODEL_PRICING: Dict[str, Tuple[float, float]] = {
    # (input_price, output_price) per 1M tokens
    "deepseek-v4-pro": (0.14, 0.28),
    "deepseek-v3": (0.07, 0.14),
    "claude-opus-4-7": (15.0, 75.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (0.80, 4.0),
    "qwen3.6-plus": (0.50, 1.50),
    "qwen3.5-plus": (0.40, 1.20),
    "qwen3-max": (0.80, 2.40),
    "default": (1.0, 2.0),
}


# ============================================================================
# 核心：JSONL 解析
# ============================================================================

def get_claude_home() -> Path:
    """获取 Claude Code 配置目录路径。"""
    return Path(os.environ.get("CLAUDE_HOME",
               os.path.expandvars(r"%USERPROFILE%\.claude")))


def project_dir_to_key(project_path: str) -> str:
    r"""
    将项目路径编码为 Claude Code 的目录名格式。
    Claude Code 编码规则: `:` → `--`, 分隔符和空格 → `-`
    例: C:\Users\...\First CC → C--Users-...-First CC
    """
    # 先处理驱动器冒号 + 紧跟的路径分隔符（C:\ → C--）
    result = project_path.replace(":\\", "--").replace(":/", "--")
    # 再处理剩余的 : \ / 和空格
    result = result.replace(":", "--").replace("\\", "-")
    result = result.replace("/", "-").replace(" ", "-")
    return result


def find_project_jsonls(project_dir: str) -> List[Path]:
    """获取项目目录下所有会话 JSONL 文件，按修改时间降序排列。"""
    key = project_dir_to_key(project_dir)
    proj_path = get_claude_home() / "projects" / key
    if not proj_path.exists():
        return []
    files = sorted(proj_path.glob("*.jsonl"),
                   key=lambda f: f.stat().st_mtime, reverse=True)
    return files


def parse_session_tokens(jsonl_path: Path) -> Dict[str, Any]:
    """
    解析单个会话的 JSONL 文件，聚合 token 用量。

    返回: {
        "session_id": str, "total_in": int, "total_out": int,
        "total_cache_read": int, "total_cache_create": int,
        "msg_count": int, "model": str, "first_ts": str, "last_ts": str
    }
    """
    total_in = 0
    total_out = 0
    total_cache_read = 0
    total_cache_create = 0
    msg_count = 0
    model: str = ""
    first_ts: str = ""
    last_ts: str = ""

    try:
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if d.get("type") != "assistant":
                    # 也尝试从 user 事件的 timestamp 获取 first_ts
                    if d.get("type") == "user" and not first_ts:
                        ts = d.get("timestamp", "")
                        if ts:
                            first_ts = ts
                    continue

                msg_count += 1
                usage = d.get("message", {}).get("usage", {})
                total_in += usage.get("input_tokens", 0)
                total_out += usage.get("output_tokens", 0)
                total_cache_read += usage.get("cache_read_input_tokens", 0)
                total_cache_create += usage.get("cache_creation_input_tokens", 0)

                if not model:
                    model = d.get("message", {}).get("model", "")

                ts = d.get("timestamp", "")
                if ts:
                    if not first_ts:
                        first_ts = ts
                    last_ts = ts
    except (OSError, IOError):
        pass

    session_id = jsonl_path.stem  # 文件名即 session ID

    return {
        "session_id": session_id,
        "total_in": total_in,
        "total_out": total_out,
        "total_cache_read": total_cache_read,
        "total_cache_create": total_cache_create,
        "msg_count": msg_count,
        "model": model,
        "first_ts": first_ts,
        "last_ts": last_ts,
    }


# ============================================================================
# 格式化输出
# ============================================================================

def format_tokens(n: int) -> str:
    """人性化 token 数字格式化。"""
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    elif n >= 1_000:
        return f"{n/1_000:.0f}K"
    return str(n)


def format_price(usd: float) -> str:
    """价格格式化。"""
    if usd < 0.01:
        return f"${usd:.4f}"
    elif usd < 1:
        return f"${usd:.2f}"
    return f"${usd:.2f}"


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """估算 token 费用（美元）。"""
    prices = MODEL_PRICING.get(model, MODEL_PRICING["default"])
    return (input_tokens / 1_000_000) * prices[0] + \
           (output_tokens / 1_000_000) * prices[1]


def ts_to_date(ts_str: str) -> str:
    """ISO 时间戳转日期字符串（北京时间）。"""
    try:
        if ts_str.endswith("Z"):
            ts_str = ts_str[:-1] + "+00:00"
        dt = datetime.fromisoformat(ts_str)
        dt_cn = dt.astimezone(CN_TZ)
        return dt_cn.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return "未知"


# ============================================================================
# 状态栏模式
# ============================================================================

def statusline_output() -> None:
    """
    状态栏模式：从 stdin 读取 Claude Code 状态数据，
    解析当前项目 token 用量，输出紧凑状态行。
    """
    # 读取 stdin JSON
    try:
        stdin_data = json.load(sys.stdin)
    except json.JSONDecodeError:
        stdin_data = {}

    # 提取 Claude Code 传入的状态信息
    cc_context = stdin_data.get("context_window", {})
    remaining_pct = cc_context.get("remaining_percentage", 100)
    used_pct = 100 - remaining_pct

    cc_model = stdin_data.get("model", {})
    model_name = cc_model.get("display_name", "?")

    cc_workspace = stdin_data.get("workspace", {})
    project_dir = cc_workspace.get("current_dir", os.getcwd())

    # 获取项目目录名（用于显示）
    proj_name = Path(project_dir).name or project_dir

    # 解析 token 用量
    jsonl_files = find_project_jsonls(project_dir)

    if not jsonl_files:
        print(f"{proj_name} | {model_name} | ctx:{used_pct:.0f}% | no data")
        return

    # 当前会话（最新文件）
    current = parse_session_tokens(jsonl_files[0])
    cur_total = current["total_in"] + current["total_out"]

    # 全部会话合计
    grand_total = 0
    for f in jsonl_files:
        # 快速聚合（不逐个完整解析以节省时间）
        s = parse_session_tokens(f)
        grand_total += s["total_in"] + s["total_out"]

    # 缓存命中率（当前会话）
    cache_hit = current["total_cache_read"]
    if current["total_in"] + cache_hit > 0:
        cache_rate = cache_hit / (current["total_in"] + cache_hit) * 100
    else:
        cache_rate = 0.0

    # 输出紧凑状态行
    parts = [
        f"{proj_name}",
        f"{model_name}",
        f"会话:{format_tokens(cur_total)}",
        f"总计:{format_tokens(grand_total)}",
    ]
    if cache_rate > 10:
        parts.append(f"cache:{cache_rate:.0f}%")
    parts.append(f"ctx:{used_pct:.0f}%")

    print(" | ".join(parts))


# ============================================================================
# 报告模式
# ============================================================================

def report_output(project_dir: str, days: Optional[int] = None) -> None:
    """
    报告模式：输出详细的 token 使用统计。
    """
    jsonl_files = find_project_jsonls(project_dir)
    if not jsonl_files:
        print(f"未找到项目 {project_dir} 的会话记录。")
        return

    # 截止时间过滤
    if days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # 解析所有会话
    sessions: List[Dict[str, Any]] = []
    for f in jsonl_files:
        s = parse_session_tokens(f)
        # 时间过滤
        if days and s["first_ts"]:
            try:
                ts = s["first_ts"]
                if ts.endswith("Z"):
                    ts = ts[:-1] + "+00:00"
                dt = datetime.fromisoformat(ts)
                if dt < cutoff:
                    continue
            except (ValueError, TypeError):
                pass
        if s["total_in"] + s["total_out"] > 0:  # 跳过空会话
            sessions.append(s)

    if not sessions:
        print("指定时间范围内无有效会话记录。")
        return

    # 计算总计
    grand_in = sum(s["total_in"] for s in sessions)
    grand_out = sum(s["total_out"] for s in sessions)
    grand_cache_read = sum(s["total_cache_read"] for s in sessions)
    grand_cache_create = sum(s["total_cache_create"] for s in sessions)
    grand_total = grand_in + grand_out

    # 模型使用分布
    model_counter: Dict[str, int] = defaultdict(int)
    model_tokens: Dict[str, Tuple[int, int]] = defaultdict(lambda: (0, 0))
    for s in sessions:
        m = s["model"] or "unknown"
        model_counter[m] += 1
        prev_in, prev_out = model_tokens[m]
        model_tokens[m] = (prev_in + s["total_in"], prev_out + s["total_out"])

    # 每日统计
    daily_tokens: Dict[str, int] = defaultdict(int)
    daily_sessions: Dict[str, int] = defaultdict(int)
    for s in sessions:
        date = ts_to_date(s["first_ts"])
        daily_tokens[date] += s["total_in"] + s["total_out"]
        daily_sessions[date] += 1

    # --- 输出报告 ---
    proj_name = Path(project_dir).name or "项目"
    print(f"\n{'='*60}")
    print(f"  Token 用量报告 — {proj_name}")
    print(f"{'='*60}")
    if days:
        print(f"  时间范围：最近 {days} 天")
    print(f"  统计时间：{datetime.now(CN_TZ).strftime('%Y-%m-%d %H:%M:%S')}（北京时间）")

    # 1. 总览
    print(f"\n{'─'*50}")
    print("  1. 用量总览")
    print(f"{'─'*50}")
    print(f"  会话数         : {len(sessions)}")
    print(f"  输入 tokens    : {grand_in:>12,}")
    print(f"  输出 tokens    : {grand_out:>12,}")
    print(f"  合计 tokens    : {grand_total:>12,}")
    if grand_cache_read:
        print(f"  缓存读取 hits  : {grand_cache_read:>12,}")
    if grand_cache_create:
        print(f"  缓存写入       : {grand_cache_create:>12,}")

    # 费用估算
    total_cost = 0.0
    for m, (m_in, m_out) in model_tokens.items():
        total_cost += estimate_cost(m, m_in, m_out)
    print(f"  估算费用 (USD) : {format_price(total_cost):>12}")

    # 2. 模型分布
    print(f"\n{'─'*50}")
    print("  2. 模型使用分布")
    print(f"{'─'*50}")
    print(f"  {'模型':<25s} {'次数':>5s}  {'输入':>10s}  {'输出':>10s}  {'合计':>10s}")
    print(f"  {'─'*25} {'─'*5} {'─'*10} {'─'*10} {'─'*10}")
    for m, count in model_counter.items():
        m_in, m_out = model_tokens[m]
        m_total = m_in + m_out
        print(f"  {m:<25s} {count:>5d}  {format_tokens(m_in):>10s}  "
              f"{format_tokens(m_out):>10s}  {format_tokens(m_total):>10s}")

    # 3. 每日统计
    print(f"\n{'─'*50}")
    print("  3. 每日用量")
    print(f"{'─'*50}")
    print(f"  {'日期':<12s} {'会话':>4s}  {'Tokens':>10s}  {'分布图'}")
    print(f"  {'─'*12} {'─'*4} {'─'*10} {'─'*30}")
    max_daily = max(daily_tokens.values()) if daily_tokens else 1
    for date in sorted(daily_tokens.keys()):
        t = daily_tokens[date]
        s = daily_sessions[date]
        bar_len = int(t / max_daily * 30) if max_daily > 0 else 0
        bar = "█" * bar_len
        print(f"  {date:<12s} {s:>4d}  {format_tokens(t):>10s}  {bar}")

    # 4. 单次会话排行
    print(f"\n{'─'*50}")
    print("  4. 单次会话用量排行 (Top 10)")
    print(f"{'─'*50}")
    print(f"  {'#':>3s}  {'会话 ID':<20s} {'Tokens':>10s}  {'模型':<20s}  {'日期'}")
    print(f"  {'─'*3}  {'─'*20} {'─'*10}  {'─'*20}  {'─'*12}")
    sorted_sessions = sorted(sessions, key=lambda s: s["total_in"] + s["total_out"], reverse=True)
    for i, s in enumerate(sorted_sessions[:10], 1):
        sid = s["session_id"][:16]
        st = s["total_in"] + s["total_out"]
        date = ts_to_date(s["first_ts"])
        print(f"  {i:>3d}  {sid:<20s} {format_tokens(st):>10s}  "
              f"{s['model']:<20s}  {date}")

    print(f"\n{'='*60}\n")


# ============================================================================
# 入口
# ============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Claude Code Token 用量监控工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--report", "-r",
        action="store_true",
        help="生成详细统计报告（默认：状态栏紧凑模式）",
    )
    parser.add_argument(
        "--project", "-p",
        type=str,
        default=None,
        help="指定项目目录路径（默认：状态栏模式从 stdin 读取，报告模式使用当前目录）",
    )
    parser.add_argument(
        "--days", "-d",
        type=int,
        default=None,
        help="仅统计最近 N 天的数据（默认：全部）",
    )
    parser.add_argument(
        "--watch", "-w",
        type=int,
        default=None,
        help="持续监控模式，每 N 秒刷新（终端下有效）",
    )

    args = parser.parse_args()

    if args.watch:
        # 持续监控模式
        _run_watch(args)
    elif args.report:
        project = args.project or os.getcwd()
        report_output(project, args.days)
    else:
        # 状态栏模式
        statusline_output()


def _run_watch(args: argparse.Namespace) -> None:
    """持续监控模式：定期刷新显示。"""
    project = args.project or os.getcwd()
    interval = args.watch or 5

    print(f"Token 用量实时监控 — {Path(project).name}")
    print(f"刷新间隔：{interval} 秒 | Ctrl+C 退出\n")
    try:
        while True:
            os.system("cls" if sys.platform == "win32" else "clear")
            report_output(project, args.days)
            print(f"[下次刷新：{interval} 秒后...]")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n监控已停止。")


if __name__ == "__main__":
    main()
