# -*- coding: utf-8 -*-
"""
agent_thinker.py — LLM 推理引擎
Phase 2: 加载人格卡 → 构建上下文 Prompt → 调用本地 9B → 解析决策 JSON

独立测试: py agent_proto/agent_thinker.py
依赖: openai, pyyaml
"""
import os
import json
import re
import time
import yaml
from openai import OpenAI

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# ═══════════════════════════════════════════════════════════
# 配置 & 人格卡加载
# ═══════════════════════════════════════════════════════════

def load_config():
    """加载 llm_config.yaml"""
    path = os.path.join(BASE_DIR, "llm_config.yaml")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_persona(name):
    """读取人格卡 markdown，返回 system_prompt 和 context_template 两部分。

    分割标记：'## 传给 LLM 的上下文格式'
    - system_prompt:  标记之前的所有内容（身份、声音、触发规则、话术示例）
    - context_template: 标记之后的内容（上下文变量 + 输出 JSON 格式指令）
    """
    path = os.path.join(BASE_DIR, "agent_personas", f"{name}.md")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    marker = "## 传给 LLM 的上下文格式"
    if marker in content:
        idx = content.index(marker)
        system_prompt = content[:idx].strip()
        # 保留模板正文（去掉标题行）
        context_template = content[idx + len(marker):].strip()
    else:
        system_prompt = content.strip()
        context_template = ""

    return {
        "name": name,
        "system_prompt": system_prompt,
        "context_template": context_template,
    }


# ═══════════════════════════════════════════════════════════
# Persona 路由（Phase 4D）
# ═══════════════════════════════════════════════════════════

def route_persona(event_type, ctx):
    """根据事件类型和时段决定使用哪个 Persona。

    返回: "recorder" | "companion" | "scheduler"
    """
    t = ctx.get("time", {})
    period = t.get("period", "afternoon")
    idle_sec = ctx.get("idle_seconds", 0)

    # 晚上/深夜 → companion 陪伴
    if period in ("evening", "night"):
        return "companion"

    # 空闲后恢复（>20min）→ companion 关切
    if event_type == "idle_return" and idle_sec > 1200:
        return "companion"

    # 时段切换 → companion 温暖过渡
    if event_type == "period_change":
        return "companion"

    # 上午心跳 → scheduler 晨间简报
    if event_type == "heartbeat" and period == "morning":
        pending = ctx.get("pending_task_count", 0)
        if pending > 0:
            return "scheduler"
        return "companion"

    # 下午心跳 + 有待办 → scheduler 空闲建议
    if event_type == "heartbeat" and period == "afternoon":
        pending = ctx.get("pending_task_count", 0)
        if pending > 0:
            return "scheduler"

    # 默认：recorder 记录提醒
    return "recorder"


# ═══════════════════════════════════════════════════════════
# Thinker
# ═══════════════════════════════════════════════════════════

class Thinker:
    """本地 9B 推理引擎。

    - 配置来自 llm_config.yaml 的 local 段
    - 每次 think() 调用加载人格卡 + 构建 prompt + 调用 API + 解析 JSON
    - 错误降级为静默（should_speak=False, autonomy_level=L0）
    """

    def __init__(self, config=None):
        cfg = config or load_config()
        local_cfg = cfg["local"]
        routing_cfg = cfg.get("routing", {})

        self.client = OpenAI(
            base_url=local_cfg["endpoint"],
            api_key=local_cfg["api_key"],
        )
        self.model = local_cfg["model"]
        self.max_tokens = local_cfg.get("max_tokens", 256)
        self.temperature = local_cfg.get("temperature", 0.7)
        self.timeout = routing_cfg.get("timeout", 15)
        self.retry = routing_cfg.get("retry", 2)

    def think(self, context, persona_name="recorder"):
        """调用本地 9B，根据上下文判断是否说话。

        参数:
            context: Observer 组装的上下文字典，需包含：
                timestamp, window, idle_seconds, time,
                可选: event_type, previous_window, window_duration,
                      today_slice_count, last_manual_record, time_ago,
                      existence_mode, recent_activity_summary
            persona_name: 人格卡名称（默认 recorder）

        返回:
            {
                "should_speak": bool,
                "message": str,
                "autonomy_level": str,   # L0/L1/L2/L3/L4
                "reason": str,
                "persona": str,
                "elapsed_ms": float,
                "raw": str | None,
            }
        """
        persona = load_persona(persona_name)
        user_prompt = self._build_prompt(context, persona)

        last_error = None
        for attempt in range(self.retry + 1):
            try:
                t0 = time.time()
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": persona["system_prompt"]},
                        {"role": "user", "content": user_prompt},
                    ],
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                    timeout=self.timeout,
                )
                elapsed = (time.time() - t0) * 1000
                raw = resp.choices[0].message.content.strip()
                return self._parse_response(raw, persona_name, elapsed)

            except Exception as e:
                last_error = e
                if attempt < self.retry:
                    time.sleep(1)

        return {
            "should_speak": False,
            "message": "",
            "autonomy_level": "L0",
            "persona": persona_name,
            "reason": f"LLM error after {self.retry + 1} attempts: {last_error}",
            "elapsed_ms": 0,
            "raw": None,
        }

    # ── 内部方法 ──────────────────────────────────────────────

    def _build_prompt(self, ctx, persona):
        """将 Observer 上下文填入人格卡模板中的占位符"""
        template = persona["context_template"]

        # 窗口信息
        win = ctx.get("window", {})
        current_win = f"{win.get('process', '?')} - {win.get('title', '?')}" if win else "?"

        # 时间信息
        tctx = ctx.get("time", {})

        # 占位符映射
        subs = {
            "{time}":                    ctx.get("timestamp", ""),
            "{current_window}":          current_win,
            "{duration}":                str(ctx.get("window_duration", "?")),
            "{prev_window}":             str(ctx.get("previous_window", "?")),
            "{idle_duration}":           str(ctx.get("idle_seconds", 0)),
            "{today_slice_count}":       str(ctx.get("today_slice_count", "?")),
            "{last_manual_record}":      str(ctx.get("last_manual_record", "暂无")),
            "{time_ago}":               str(ctx.get("time_ago", "?")),
            "{existence_mode}":          str(ctx.get("existence_mode", "陪伴")),
            "{recent_activity_summary}": str(ctx.get("recent_activity_summary", "(暂无)")),
            # scheduler 专用
            "{pending_task_count}":      str(ctx.get("pending_task_count", "?")),
            "{scheduled_task_count}":    str(ctx.get("scheduled_task_count", "?")),
            "{today_completed_count}":   str(ctx.get("today_completed_count", "0")),
            "{upcoming_deadlines}":      str(ctx.get("upcoming_deadlines", "无")),
            "{free_slots_today}":        str(ctx.get("free_slots_today", "无")),
        }

        result = template
        for key, val in subs.items():
            result = result.replace(key, val)
        return result

    def _parse_response(self, raw, persona_name, elapsed_ms):
        """解析 LLM 返回的 JSON，三层回退：直接解析 → 代码块提取 → 花括号提取 → 降级静默"""
        # 第一层：直接解析
        try:
            data = json.loads(raw)
            return self._normalize(data, persona_name, elapsed_ms, raw)
        except json.JSONDecodeError:
            pass

        # 第二层：从 markdown 代码块提取
        m = re.search(r'```(?:json)?\s*([\s\S]*?)```', raw)
        if m:
            try:
                data = json.loads(m.group(1).strip())
                return self._normalize(data, persona_name, elapsed_ms, raw)
            except json.JSONDecodeError:
                pass

        # 第三层：从文本中提取第一个花括号对象
        m = re.search(r'\{[\s\S]*\}', raw)
        if m:
            try:
                data = json.loads(m.group(0))
                return self._normalize(data, persona_name, elapsed_ms, raw)
            except json.JSONDecodeError:
                pass

        # 降级静默
        return {
            "should_speak": False,
            "message": "",
            "autonomy_level": "L0",
            "persona": persona_name,
            "reason": "JSON parse failed — fallback to silent",
            "elapsed_ms": elapsed_ms,
            "raw": raw,
        }

    @staticmethod
    def _normalize(data, persona_name, elapsed_ms, raw):
        """确保返回字段齐全，类型正确"""
        return {
            "should_speak": bool(data.get("should_speak", False)),
            "message": str(data.get("message", "")),
            "autonomy_level": str(data.get("autonomy_level", "L0")),
            "persona": persona_name,
            "reason": str(data.get("reason", "")),
            "elapsed_ms": elapsed_ms,
            "raw": raw,
        }

    def chat(self, user_message, persona_name="companion", history=None):
        """自由对话模式：用户输入 → 本地 9B → 文本回复。

        参数:
            user_message: 用户输入的文字
            persona_name: 人格卡名称（默认 companion）
            history:      最近对话历史 [{"role":"user","content":"..."}, ...]

        返回: Agent 的文本回复（字符串）
        """
        # 对话用轻量 system prompt（自然、克制、不表演）
        chat_system = """你是小鱼，一个安静的 AI 陪伴者。你住在用户桌面的右下角，是一颗会呼吸的蓝点。

说话风格：
- 自然、平和、不表演。你不是段子手，不是客服，不是人生导师
- 简短。1-3 句足够，不要写小作文
- 真诚。不知道就说不知道，不会就承认不会
- 不要过度热情，但也不要冷冰冰——像一个认识了一段时间的朋友，不用寒暄
- 用户不说话的时候你也不说话，用户说话的时候认真回应
- 不要主动给建议，除非用户明确问
- 不要加表情、语气词、波浪线卖萌
- 深夜保持安静、简短的语气"""

        messages = [{"role": "system", "content": chat_system}]
        if history:
            messages.extend(history[-20:])
        messages.append({"role": "user", "content": user_message})

        for attempt in range(self.retry + 1):
            try:
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    max_tokens=self.max_tokens,
                    temperature=0.9,
                    timeout=self.timeout,
                )
                return resp.choices[0].message.content.strip()
            except Exception as e:
                if attempt == self.retry:
                    return f"(暂时无法回复：{e})"
                time.sleep(1)


# ═══════════════════════════════════════════════════════════
# 独立测试（模拟上下文）
# ═══════════════════════════════════════════════════════════

def _print_result(r):
    """格式化打印 Thinker 结果（独立测试用）"""
    decision = "SPEAK" if r["should_speak"] else "SILENT"
    print(f"  决策: {decision} | 自主级别: {r['autonomy_level']}")
    print(f"  耗时: {r['elapsed_ms']:.0f}ms")
    if r["should_speak"]:
        print(f"  话术: {r['message']}")
    if r["reason"]:
        print(f"  原因: {r['reason']}")


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    print("=" * 56)
    print("  Thinker 独立测试 — recorder 人格卡 + 模拟上下文")
    print("=" * 56)

    thinker = Thinker()

    # 场景1：窗口切换，上一窗口持续了 25 分钟
    print("\n[场景1] 窗口切换 — VS Code → Chrome\n")
    ctx1 = {
        "timestamp": "2026-05-12 14:30:00",
        "window": {"title": "Google Chrome", "process": "chrome.exe"},
        "previous_window": "Code.exe - agent_loop.py - First CC",
        "window_duration": "25 分钟",
        "idle_seconds": 2,
        "time": {
            "datetime": "2026-05-12T14:30:00",
            "hour": 14,
            "weekday": 1,
            "period": "afternoon",
            "is_work_hour": True,
            "is_night": False,
        },
        "today_slice_count": 0,
        "last_manual_record": "暂无",
        "time_ago": "?",
        "existence_mode": "陪伴",
        "recent_activity_summary": "(暂无)",
    }
    result = thinker.think(ctx1, "recorder")
    _print_result(result)

    # 场景2：深夜时段，只应静默
    print("\n[场景2] 深夜时段 — 应静默 (should_speak=false)\n")
    ctx2 = {
        "timestamp": "2026-05-12 02:15:00",
        "window": {"title": "bilibili - 视频", "process": "chrome.exe"},
        "previous_window": "chrome.exe - bilibili",
        "window_duration": "45 分钟",
        "idle_seconds": 5,
        "time": {
            "datetime": "2026-05-12T02:15:00",
            "hour": 2,
            "weekday": 1,
            "period": "night",
            "is_work_hour": False,
            "is_night": True,
        },
        "today_slice_count": 3,
        "last_manual_record": "2 小时前",
        "time_ago": "2 小时",
        "existence_mode": "休眠",
        "recent_activity_summary": "深夜刷视频",
    }
    result = thinker.think(ctx2, "recorder")
    _print_result(result)
