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
USD_TO_CNY = 7.25  # 美元兑人民币汇率（浮动值，可手动更新）

# 各模型价格（人民币 / 百万 token）
# 格式: (input_price, cache_hit_price, output_price) per 1M tokens
# 数据来源: DeepSeek 官方 API 定价页（2026-05-09 折扣价）
# https://api-docs.deepseek.com/zh-cn/quick_start/pricing
MODEL_PRICING_CNY: Dict[str, Tuple[float, float, float]] = {
    "deepseek-v4-pro":     (3.0,  0.025, 6.0),    # 原价 12/0.1/24，限时2.5折至5月底
    "deepseek-v3":          (0.5,  0.05,  1.1),    # V3.2 定价
    "deepseek-v4-flash":    (1.0,  0.02,  2.0),    # V4 Flash
    "claude-opus-4-7":      (108.0, 10.8, 540.0),  # $15/$1.5/$75 × 7.2
    "claude-sonnet-4-6":    (21.6,  2.16, 108.0),  # $3/$0.3/$15 × 7.2
    "claude-haiku-4-5":     (5.76,  0.58, 28.8),   # $0.8/$0.08/$4 × 7.2
    "qwen3.6-plus":         (2.9,   0.29,  8.7),   # ¥0.4/¥0.04/¥1.2 per 1K → scaled to 1M
    "qwen3.5-plus":         (2.9,   0.29,  8.7),
    "qwen3-max":            (5.8,   0.58,  17.4),
    "default":              (7.2,   0.72,  14.4),   # 默认 $1/$0.1/$2
}


# ============================================================================
# 核心：JSONL 解析
# ============================================================================

def get_claude_home() -> Path:
    """获取 Claude Code 配置目录路径。"""
    return Path(os.environ.get("CLAUDE_HOME", Path.home() / ".claude"))


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

                msg_type = d.get("type")
                ts = d.get("timestamp", "")

                if msg_type != "assistant":
                    if msg_type == "user" and not first_ts and ts:
                        first_ts = ts
                    continue

                msg_count += 1
                msg_body = d.get("message", {})
                usage = msg_body.get("usage", {})
                total_in += usage.get("input_tokens", 0)
                total_out += usage.get("output_tokens", 0)
                total_cache_read += usage.get("cache_read_input_tokens", 0)
                total_cache_create += usage.get("cache_creation_input_tokens", 0)

                if not model:
                    model = msg_body.get("model", "")

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


def format_cny(yuan: float) -> str:
    """人民币价格格式化。"""
    if yuan < 0.01:
        return f"¥{yuan:.4f}"
    elif yuan < 1:
        return f"¥{yuan:.2f}"
    return f"¥{yuan:.2f}"


def estimate_cost_cny(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_hit_tokens: int = 0,
) -> float:
    """
    估算 token 费用（人民币）。
    区分输入、缓存命中、输出三种计费项。
    """
    prices = MODEL_PRICING_CNY.get(model, MODEL_PRICING_CNY["default"])
    price_in, price_cache, price_out = prices
    cost_in = (input_tokens / 1_000_000) * price_in
    cost_cache = (cache_hit_tokens / 1_000_000) * price_cache
    cost_out = (output_tokens / 1_000_000) * price_out
    return cost_in + cost_cache + cost_out


def _normalize_ts(ts_str: str) -> str:
    """将 ISO 时间戳中的 Z 后缀替换为 +00:00 以便 fromisoformat 解析。"""
    return ts_str[:-1] + "+00:00" if ts_str.endswith("Z") else ts_str


def ts_to_date(ts_str: str) -> str:
    """ISO 时间戳转日期字符串（北京时间）。"""
    try:
        dt = datetime.fromisoformat(_normalize_ts(ts_str))
        dt_cn = dt.astimezone(CN_TZ)
        return dt_cn.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return "未知"


# ============================================================================
# 状态栏缓存（避免每次刷新都解析全部 JSONL 文件）
# ============================================================================

def _cache_path(project_dir: str) -> Path:
    key = project_dir_to_key(project_dir)
    return get_claude_home() / "projects" / key / ".token_cache.json"


def _load_grand_total_cache(project_dir: str) -> Optional[Dict[str, Any]]:
    try:
        p = _cache_path(project_dir)
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    return None


def _save_grand_total_cache(project_dir: str, cache_key: Any, value: int) -> None:
    try:
        p = _cache_path(project_dir)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"key": cache_key, "value": value}), encoding="utf-8")
    except OSError:
        pass


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

    # 全部会话合计（当前会话 + 缓存的历史合计）
    grand_total = cur_total
    if len(jsonl_files) > 1:
        # 检查缓存是否有效（基于文件最后修改时间）
        cache_key = tuple((f.name, f.stat().st_mtime) for f in jsonl_files[1:])
        cached = _load_grand_total_cache(project_dir)
        if cached and cached.get("key") == cache_key:
            grand_total += cached["value"]
        else:
            # 缓存失效，重新计算
            historical = 0
            for f in jsonl_files[1:]:
                s = parse_session_tokens(f)
                historical += s["total_in"] + s["total_out"]
            _save_grand_total_cache(project_dir, cache_key, historical)
            grand_total += historical

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
                ts = _normalize_ts(s["first_ts"])
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
    model_cache: Dict[str, int] = defaultdict(int)
    for s in sessions:
        m = s["model"] or "unknown"
        model_counter[m] += 1
        prev_in, prev_out = model_tokens[m]
        model_tokens[m] = (prev_in + s["total_in"], prev_out + s["total_out"])
        model_cache[m] += s["total_cache_read"]

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

    # 费用估算（含缓存命中折扣）
    total_cost_cny = 0.0
    for m, (m_in, m_out) in model_tokens.items():
        m_cache = model_cache.get(m, 0)
        total_cost_cny += estimate_cost_cny(m, m_in, m_out, m_cache)
    print(f"  估算费用 (CNY) : {format_cny(total_cost_cny):>12}")

    # 2. 模型分布
    print(f"\n{'─'*50}")
    print("  2. 模型使用分布")
    print(f"{'─'*50}")
    print(f"  {'模型':<25s} {'次数':>5s}  {'输入':>10s}  {'输出':>10s}  {'合计':>10s}  {'费用(CNY)':>10s}")
    print(f"  {'─'*25} {'─'*5} {'─'*10} {'─'*10} {'─'*10} {'─'*10}")
    for m, count in model_counter.items():
        m_in, m_out = model_tokens[m]
        m_total = m_in + m_out
        m_cost = estimate_cost_cny(m, m_in, m_out, model_cache.get(m, 0))
        print(f"  {m:<25s} {count:>5d}  {format_tokens(m_in):>10s}  "
              f"{format_tokens(m_out):>10s}  {format_tokens(m_total):>10s}  {format_cny(m_cost):>10s}")

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
