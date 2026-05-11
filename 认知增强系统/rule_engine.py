"""
rule_engine.py — 规则引擎：评估触发器 → 匹配条件 → 执行动作
依赖：plyer（桌面通知）、json、threading（前端轮询标记）
"""
import json
import threading
from datetime import datetime, timedelta

try:
    from plyer import notification as plyer_notify
    HAS_PLYER = True
except ImportError:
    HAS_PLYER = False


# 全局通知队列（前端轮询检测）
_pending_prompts = []
_prompts_lock = threading.Lock()


class RuleEngine:
    def __init__(self, db):
        self.db = db

    def evaluate(self, trigger_type, context):
        """触发规则评估。
        - trigger_type: 触发器类型字符串
        - context: 触发上下文 dict
        """
        rules = self.db.get_enabled_rules_by_trigger(trigger_type)
        for rule in rules:
            if self._match(rule["trigger_params"], context):
                self._execute(rule["action_type"], rule["action_params"], context, rule["name"])

    def _match(self, trigger_params, context):
        """条件匹配逻辑：逐参数比较"""
        for key, expected in trigger_params.items():
            if key not in context:
                return False
            actual = context[key]
            if isinstance(expected, str) and expected == "*":
                continue  # 通配符
            if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
                if actual < expected:
                    return False  # 数值型参数表示阈值（>= 才触发）
            elif actual != expected:
                return False
        return True

    def _execute(self, action_type, action_params, context, rule_name=""):
        """执行动作"""
        if action_type == "notify":
            self._action_notify(action_params, context)
        elif action_type == "prompt_slice":
            self._action_prompt_slice(action_params, context)
        elif action_type == "log":
            self._action_log(action_params, context, rule_name)

    def _action_notify(self, params, context):
        """发送桌面通知"""
        if not HAS_PLYER:
            return
        title = params.get("title", "认知增强系统")
        message = params.get("message", "")
        # 变量替换
        for key, val in context.items():
            message = message.replace("{" + key + "}", str(val))
            title = title.replace("{" + key + "}", str(val))
        try:
            plyer_notify.notify(title=title, message=message, app_name="认知增强系统", timeout=5)
        except Exception:
            pass

    def _action_prompt_slice(self, params, context):
        """触发前端弹窗（通过全局标记 + 前端轮询）"""
        title = params.get("title", "")
        message = params.get("message", "")
        for key, val in context.items():
            message = message.replace("{" + key + "}", str(val))
            title = title.replace("{" + key + "}", str(val))
        with _prompts_lock:
            _pending_prompts.append({
                "title": title,
                "message": message,
                "timestamp": datetime.now().isoformat(),
            })
            # 只保留最近 10 条
            if len(_pending_prompts) > 10:
                _pending_prompts[:] = _pending_prompts[-10:]

    def _action_log(self, params, context, rule_name):
        """记录规则触发的日志"""
        print(f"[Rule] {rule_name} triggered at {datetime.now().strftime('%H:%M:%S')}")


def get_pending_prompts():
    """获取待处理弹窗（前端轮询）"""
    with _prompts_lock:
        items = list(_pending_prompts)
        _pending_prompts.clear()
    return items
