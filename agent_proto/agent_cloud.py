# -*- coding: utf-8 -*-
"""
agent_cloud.py — 云端 API 接入层（Phase 4F）
DeepSeek V4 Pro 用于脱敏后的长周期趋势分析。

隐私守则（硬约束）：
- 窗口标题、剪贴板原文、浏览器 URL、系统通知内容绝不离开本地
- 发送前必须脱敏——仅传输聚合统计量，不含任何原始文本
- 默认不自动调用，需用户确认

运行测试: py agent_proto/agent_cloud.py
"""
import os
import json
import yaml
# datetime/timedelta reserved for future aggregation functions

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def load_config():
    with open(os.path.join(BASE_DIR, "llm_config.yaml"), "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _get_client():
    """惰性初始化 DeepSeek 客户端"""
    cfg = load_config()
    cloud_cfg = cfg.get("cloud_primary", {})
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        return None
    from openai import OpenAI
    return OpenAI(base_url=cloud_cfg.get("endpoint"), api_key=api_key)


# ═══════════════════════════════════════════════════════════
# 脱敏聚合分析
# ═══════════════════════════════════════════════════════════

def analyze_weekly_summary(stats):
    """发送脱敏后的周统计到云端，获取趋势洞察。

    参数:
        stats: 聚合统计 dict，字段：
            daily_slice_counts: [7] 每日切片数
            top_processes: [(进程名, 总分钟数), ...] 最多 5 个
            avg_idle_hours: 日均空闲时长
            work_hour_distribution: {时段: 占比}

    返回: 云端生成的文字摘要（中文字符串），失败返回 None。

    隐私保证：stats 中不含任何窗口标题、URL、剪贴板内容、通知文字。
    """
    client = _get_client()
    if not client:
        return None

    cfg = load_config()
    cloud_cfg = cfg.get("cloud_primary", {})
    model = cloud_cfg.get("model", "deepseek-v4-pro")

    # 构建脱敏 prompt
    prompt = f"""以下是一周的行为统计摘要（已脱敏，不含任何个人身份信息）：

每日活动记录数: {stats.get('daily_slice_counts', [])}
高频应用（按使用时长）: {stats.get('top_processes', [])}
日均空闲时长: {stats.get('avg_idle_hours', 0):.1f} 小时
时段分布: {stats.get('work_hour_distribution', {})}

请用 2-3 句中文，概括这周的节奏变化或趋势。语气温和、自然，像朋友在聊天。
不要说「根据数据分析」，直接说观察到的模式。"""

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=256,
            temperature=0.7,
            timeout=30,
        )
        return resp.choices[0].message.content.strip()
    except Exception:
        return None


def analyze_pattern_shift(current_week, previous_week):
    """对比两周数据，检测显著变化。

    参数:
        current_week:  本周聚合统计（同 analyze_weekly_summary）
        previous_week: 上周聚合统计

    返回: 变化描述字符串，无显著变化时返回 None
    """
    client = _get_client()
    if not client:
        return None

    cfg = load_config()
    cloud_cfg = cfg.get("cloud_primary", {})
    model = cloud_cfg.get("model", "deepseek-v4-pro")

    prompt = f"""以下是两周的行为摘要对比（已脱敏）：

本周: {json.dumps(current_week, ensure_ascii=False)}
上周: {json.dumps(previous_week, ensure_ascii=False)}

如果两周之间有明显的模式变化（如活动时间段改变、高频应用更换、空闲增多/减少），用 1-2 句中文描述变化。
如果没有明显变化，回复一个字：无。"""

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0.5,
            timeout=30,
        )
        text = resp.choices[0].message.content.strip()
        return text if text != "无" else None
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════
# 健康检查
# ═══════════════════════════════════════════════════════════

def is_available():
    """检查云端 API 是否可用"""
    client = _get_client()
    if not client:
        return False
    cfg = load_config()
    cloud_cfg = cfg.get("cloud_primary", {})
    model = cloud_cfg.get("model", "deepseek-v4-pro")
    try:
        client.chat.completions.create(
            model=model, messages=[{"role": "user", "content": "ping"}],
            max_tokens=4, timeout=5,
        )
        return True
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════
# 测试
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    print("── Agent Cloud API 测试 ──\n")

    if is_available():
        print("DeepSeek V4 Pro: 在线")

        # 模拟聚合统计
        mock_stats = {
            "daily_slice_counts": [3, 5, 2, 4, 6, 1, 0],
            "top_processes": [("Cursor.exe", 480), ("chrome.exe", 320),
                              ("WeChat.exe", 180), ("explorer.exe", 60)],
            "avg_idle_hours": 2.5,
            "work_hour_distribution": {"上午": 0.35, "下午": 0.45, "晚上": 0.20},
        }
        print("\n模拟周统计 → 云端分析...")
        result = analyze_weekly_summary(mock_stats)
        if result:
            print(f"云端回复: {result}")
        else:
            print("请求失败")
    else:
        print("DeepSeek V4 Pro: 不可用")
        print("原因: DEEPSEEK_API_KEY 环境变量未设置或无法连接")
        print("设置方法: set DEEPSEEK_API_KEY=你的key")
