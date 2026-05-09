#!/usr/bin/env python3
"""
Qwen Studio 聊天记录解析与提取工具
====================================
功能：解析 Qwen Studio 导出的 JSON 聊天记录，提取用户提问、AI思考过程、
      对话元数据，生成独立 Markdown 文件、索引和统计报告。

作者：自动生成
许可：MIT
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
import textwrap
import time as _time_module
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# ---------- Windows 终端 UTF-8 兼容处理 ----------
# Windows cmd/powershell 默认使用 GBK，emoji 会导致 UnicodeEncodeError
if sys.platform == 'win32':
    sys.stdout = open(sys.stdout.fileno(), mode='w', encoding='utf-8',
                       errors='replace', buffering=1)
    sys.stderr = open(sys.stderr.fileno(), mode='w', encoding='utf-8',
                       errors='replace', buffering=1)

# ---------- 可选依赖 ----------
try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False
    def tqdm(iterable, **kwargs):  # type: ignore[no-redef]
        """无 tqdm 时的降级包装器。"""
        return iterable


# ============================================================================
# 常量定义
# ============================================================================

# 文件名中不允许的字符（Windows 文件系统）
ILLEGAL_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|#\x00-\x1f]')

# 用户消息最小有效长度（字符数）
MIN_USER_MSG_LENGTH: int = 10

# 北京时间时区
CN_TZ = timezone(offset=timedelta(hours=8))

# ---------- 隐私过滤模式 ----------
PRIVACY_PATTERNS: List[Tuple[str, str, str]] = [
    # (名称, 正则模式, 替换文本)
    ("OpenAI_API_Key", r'sk-[a-zA-Z0-9-_]{20,64}', '[API_KEY_REDACTED]'),
    ("Bearer_Token", r'(?:bearer|Bearer)\s+[a-zA-Z0-9\-_\.]{20,}', '[TOKEN_REDACTED]'),
    ("Generic_API_Key", r'(?:api[_-]?key|apikey|API_KEY)\s*[=:]\s*["\']?[\w\-]{16,}["\']?',
     '[API_KEY_REDACTED]'),
    ("Email", r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', '[EMAIL_REDACTED]'),
    ("IPv4", r'\b(?:\d{1,3}\.){3}\d{1,3}\b', '[IP_REDACTED]'),
    ("Phone_CN", r'1[3-9]\d{9}', '[PHONE_REDACTED]'),
    ("Access_Key_ID", r'AKIA[0-9A-Z]{16}', '[AWS_KEY_REDACTED]'),
    ("Secret_Access_Key", r'(?i)secret[_-]?access[_-]?key\s*[=:]\s*["\']?[\w/+]{30,}["\']?',
     '[SECRET_REDACTED]'),
]

# ---------- 自动分类关键词库 ----------
CATEGORY_KEYWORDS: Dict[str, List[str]] = {
    "技术配置": [
        # 开发环境 & 工具
        "配置", "安装", "部署", "环境", "claude code", "cherry studio",
        "api", "token", "设置", "参数", "gpu", "显存", "量化", "gguf",
        "ollama", "docker", "linux", "windows", "mac", "conda", "brew",
        "pip", "npm", "yarn", "git", "github", "gitlab", "服务器", "ssh",
        "代理", "proxy", "vpn", "vscode", "ide", "终端", "terminal",
        "bash", "shell", "wsl", "cmake", "编译", "gcc", "clang", "llvm",
        "驱动", "cuda", "nvidia", "cudnn", "路径", "path", "环境变量",
        "端口", "防火墙", "路由", "nginx", "apache", "k8s", "kubernetes",
        "ci/cd", "jenkins", "action", "webhook", "域名", "dns", "ssl",
        # 模型部署
        "lm studio", "open-webui", "anything llm", "langflow", "flowise",
        "vllm", "sg-lang", "text-generation-webui", "exllama", "llama.cpp",
        "siliconflow", "deepseek", "qwen", "openai", "anthropic", "claude",
        # 编程语言 & 框架
        "python", "pytorch", "tensorflow", "javascript", "typescript",
        "react", "vue", "node", "django", "flask", "fastapi",
        "rust", "golang", "java", "c++", "c#", "sql", "数据库",
        "mysql", "postgresql", "mongodb", "redis", "rabbitmq",
    ],
    "学习相关": [
        # 学科 & 方法
        "学习", "算法", "数学", "建模", "统计", "机器学习", "深度学习",
        "神经网络", "nlp", "自然语言", "论文", "课程", "书籍", "教程",
        "习题", "考试", "数据科学", "分析", "推导", "公式", "理论",
        "原理", "方法", "知识", "概念", "理解", "解释", "定义",
        "区别", "对比", "总结", "笔记", "复习", "练习", "极简学习法",
        # ML/DL 术语
        "pytorch", "tensorflow", "sklearn", "scikit-learn", "pandas",
        "numpy", "scipy", "matplotlib", "jupyter", "可视化", "特征工程",
        "优化", "梯度", "overfitting", "过拟合", "正则化", "损失函数",
        "激活函数", "卷积", "transformer", "attention", "rnn", "lstm",
        "gan", "强化学习", "rl", "ai", "llm", "大模型", "语言模型",
        "prompt", "提示词", "finetune", "微调", "rag", "embedding",
        "向量", "chroma", "pinecone", "langchain", "agent", "智能体",
        # 学术
        "概率", "线性代数", "微积分", "优化理论", "信息论", "贝叶斯",
        "回归", "分类", "聚类", "降维", "pca", "svm", "决策树",
        "随机森林", "xgboost", "lightgbm", "交叉验证", "ablation",
    ],
    "设备硬件": [
        # 硬件设备
        "电脑", "笔记本", "天选", "拯救者", "thinkpad", "macbook",
        "cpu", "gpu", "内存", "硬盘", "ssd", "机械", "显示器",
        "键盘", "鼠标", "耳机", "麦克风", "摄像头", "主板", "电源",
        "散热", "风扇", "机箱", "显卡", "rtx", "gtx", "amd", "intel",
        "ryzen", "core", "ram", "存储", "u盘", "移动硬盘", "nas",
        # 移动设备
        "手机", "平板", "ipad", "iphone", "android", "充电", "电池",
        # 网络设备
        "wifi", "蓝牙", "路由器", "网络", "网卡", "带宽", "mesh",
        # 购物决策
        "硬件", "设备", "配件", "购买", "推荐", "性价比", "测评",
        "笔记本推荐", "装机", "diy", "升级", "更换", "维修", "故障",
        "外设", "屏幕", "分辨率", "刷新率", "色域", "hdr", "雷电",
    ],
    "健康生活": [
        # 身心健康
        "健康", "运动", "锻炼", "健身", "跑步", "游泳", "瑜伽", "冥想",
        "饮食", "营养", "食谱", "减肥", "增肌", "睡眠", "作息", "压力",
        "焦虑", "抑郁", "心理", "体检", "症状", "就医", "药物", "治疗",
        # 效率 & 习惯
        "生活", "习惯", "效率", "时间管理", "专注", "注意力", "拖延",
        "自律", "目标", "计划", "习惯养成", "番茄", "gtd", "pomodoro",
        "休息", "放松", "极简", "断舍离", "整理", "收纳",
        # 休闲 & 理财
        "旅行", "旅游", "户外", "登山", "骑行", "露营", "徒步",
        "音乐", "播客", "阅读", "游戏", "娱乐", "电影", "电视剧",
        "购物", "省钱", "理财", "投资", "基金", "股票", "保险",
        "美食", "咖啡", "茶", "烹饪", "烘焙",
    ],
}


# ============================================================================
# 工具函数
# ============================================================================

def safe_get(d: Any, *keys: str, default: Any = None) -> Any:
    """
    安全获取嵌套字典值，任意层级为 None 或缺失时返回 default。

    用法: safe_get(msg, 'extra', 'summary_thought', 'content', default=[])
    """
    for key in keys:
        if d is None:
            return default
        if isinstance(d, dict):
            d = d.get(key)
        elif isinstance(d, list):
            try:
                idx = int(key)
                d = d[idx] if 0 <= idx < len(d) else None
            except (ValueError, IndexError):
                return default
        else:
            return default
    return d if d is not None else default


def safe_list(val: Any) -> List[Any]:
    """将可能为 None 的值转换为安全列表。"""
    if val is None:
        return []
    if isinstance(val, list):
        return val
    if isinstance(val, (str, bytes)):
        return [val]
    try:
        return list(val)
    except TypeError:
        return [val] if val else []


def safe_str(val: Any) -> str:
    """将任意值安全转换为字符串。"""
    if val is None:
        return ""
    if isinstance(val, str):
        return val
    return str(val)


def sanitize_filename(name: str, max_len: int = 80) -> str:
    """
    清理文件名中的非法字符，截断过长名称。

    Windows 保留字符：\\ / : * ? " < > |
    还会清理 # 和控制字符。
    """
    # 移除非法字符
    cleaned = ILLEGAL_FILENAME_CHARS.sub('', name)
    # 合并连续空格
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    # 去除首尾空白和点号（Windows 不允许以点结尾）
    cleaned = cleaned.strip('. ')
    # 空文件名回退
    if not cleaned:
        cleaned = "untitled"
    # 截断（保留完整中文字符）
    if len(cleaned) > max_len:
        # 尝试在合适位置截断
        truncated = cleaned[:max_len].rsplit(' ', 1)[0]
        cleaned = truncated if len(truncated) > max_len // 2 else cleaned[:max_len]
    return cleaned


def timestamp_to_str(ts: Any) -> str:
    """
    将时间戳（秒）转换为 YYYY-MM-DD HH:MM:SS 格式（北京时间）。

    支持 int / float / str 类型输入。
    """
    if ts is None:
        return "未知时间"
    try:
        if isinstance(ts, str):
            ts = float(ts)
        ts_val = float(ts)
        # 检测是否为毫秒级时间戳（> 1e12）
        if ts_val > 1e12:
            ts_val /= 1000.0
        dt = datetime.fromtimestamp(ts_val, tz=CN_TZ)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, OSError, OverflowError):
        return "未知时间"


def similarity(a: str, b: str) -> float:
    """计算两个字符串的相似度（0.0 ~ 1.0）。"""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


def apply_privacy_filter(text: str, patterns: List[Tuple[str, str, str]] | None = None) -> str:
    """
    对文本应用隐私过滤，替换敏感信息。

    参数：
        text: 原始文本
        patterns: 自定义隐私模式列表，默认使用内置 PRIVACY_PATTERNS
    返回：
        过滤后的文本
    """
    if not text:
        return text
    if patterns is None:
        patterns = PRIVACY_PATTERNS
    filtered = text
    for _name, pattern, replacement in patterns:
        filtered = re.sub(pattern, replacement, filtered)
    return filtered


def extract_code_blocks(text: str) -> List[Dict[str, str]]:
    """
    从 Markdown 文本中提取代码块。

    返回：[{"language": str, "code": str}, ...]
    """
    if not text:
        return []
    # 匹配 ```language\n code \n``` 格式
    pattern = re.compile(r'```(\w*)\n(.*?)```', re.DOTALL)
    results: List[Dict[str, str]] = []
    for match in pattern.finditer(text):
        lang = match.group(1).strip() or "text"
        code = match.group(2).strip()
        if code:
            results.append({"language": lang, "code": code})
    return results


def extract_decisions(text: str) -> List[str]:
    """
    从文本中提取决策/建议性语句。

    匹配以 "建议"、"推荐"、"选择"、"方案"、"决定" 等开头的句子。
    """
    if not text:
        return []
    decision_patterns = [
        r'(?:推荐|建议|首选|最优方案|最佳选择|决定采用|优先考虑|结论[：:]|总结[：:]).*?(?:[。\n]|$)',
    ]
    decisions: List[str] = []
    for pat in decision_patterns:
        for m in re.finditer(pat, text):
            decision = m.group().strip()
            if len(decision) > 8:  # 过滤过短匹配
                decisions.append(decision)
    return decisions


def _extract_thinking_field(content_list: List[Dict], field: str) -> List[str]:
    """从 content_list 的 thinking_summary 阶段提取指定字段内容。"""
    results: List[str] = []
    for item in safe_list(content_list):
        phase = item.get('phase', '')
        if phase == 'thinking_summary':
            st = item.get('extra', {}).get(field, {})
            for t in safe_list(st.get('content', [])):
                t_str = safe_str(t).strip()
                if t_str:
                    results.append(t_str)
        extra = item.get('extra')
        if extra and isinstance(extra, dict) and phase != 'thinking_summary':
            st = extra.get(field, {})
            if st:
                for t in safe_list(st.get('content', [])):
                    t_str = safe_str(t).strip()
                    if t_str:
                        results.append(t_str)
    return results


def extract_thinking_titles(content_list: List[Dict]) -> List[str]:
    return _extract_thinking_field(content_list, 'summary_title')


def extract_thinking_content(content_list: List[Dict]) -> List[str]:
    return _extract_thinking_field(content_list, 'summary_thought')


def extract_answers(content_list: List[Dict]) -> List[str]:
    """从 content_list 中提取 AI 最终回复（answer 阶段的内容）。"""
    answers: List[str] = []
    for item in safe_list(content_list):
        if item.get('phase') == 'answer':
            c = safe_str(item.get('content', '')).strip()
            if c:
                answers.append(c)
    return answers


# ============================================================================
# 消息解析
# ============================================================================

def parse_messages(messages_dict: Dict[str, Dict]) -> List[Dict[str, Any]]:
    """
    将原始消息字典解析为按时间排序的消息列表。

    返回列表中每条消息包含：
        role, content, model, model_name, timestamp,
        thinking_titles, thinking_content, answers, code_blocks, decisions
    """
    parsed: List[Dict[str, Any]] = []

    for msg_id, msg in messages_dict.items():
        if not isinstance(msg, dict):
            continue

        role = msg.get('role', 'unknown')
        content = safe_str(msg.get('content', ''))
        ts = msg.get('timestamp')
        model = msg.get('model', '') or ''
        model_name = msg.get('modelName', '') or ''
        model_display = model_name or model  # 优先用显示名

        # 用户消息：直接读取 content
        thinking_titles: List[str] = []
        thinking_content: List[str] = []
        answers: List[str] = []
        code_blocks: List[Dict[str, str]] = []
        decisions: List[str] = []

        cl = msg.get('content_list')
        if cl and isinstance(cl, list):
            thinking_titles = extract_thinking_titles(cl)
            thinking_content = extract_thinking_content(cl)
            answers = extract_answers(cl)
            # 从所有文本中提取代码块和决策
            all_text = '\n'.join(thinking_content + answers + [content])
            code_blocks = extract_code_blocks(all_text)
            decisions = extract_decisions(all_text)

            # if no model at top level, try to extract from content_list
            if not model:
                for item in cl:
                    m = item.get('model', '') or item.get('modelName', '')
                    if m:
                        model = m
                        break

        parsed.append({
            'id': msg_id,
            'role': role,
            'content': content,
            'model_display': model_display,
            'timestamp': ts,
            'thinking_titles': thinking_titles,
            'thinking_content': thinking_content,
            'answers': answers,
            'code_blocks': code_blocks,
            'decisions': decisions,
        })

    # 按时间戳排序
    parsed.sort(key=lambda m: (m['timestamp'] is None, m['timestamp'] or 0))
    return parsed


# ============================================================================
# 分类与去重
# ============================================================================

def classify_conversation(title: str, user_messages: List[str],
                          all_text: str) -> str:
    """
    基于标题和用户消息内容，将对话分类到预定义类别。

    优先级：技术配置 > 学习相关 > 设备硬件 > 健康生活 > 其他
    """
    # 合并所有文本用于关键词匹配
    combined = (title + ' ' + ' '.join(user_messages) + ' ' + all_text).lower()

    scores: Dict[str, int] = {}
    for category, keywords in CATEGORY_KEYWORDS.items():
        if category == "其他":
            continue
        score = 0
        for kw in keywords:
            count = combined.count(kw.lower())
            if count > 0:
                score += count
        scores[category] = score

    # 选出最高分
    if scores:
        best_cat = max(scores, key=lambda k: scores[k])
        if scores[best_cat] > 0:
            return best_cat

    return "其他"


def detect_duplicates(conversations: List[Dict[str, Any]],
                       threshold: float = 0.8) -> Tuple[Dict[str, List[int]], Dict[int, Optional[int]]]:
    """
    基于标题文本相似度检测重复对话。
    返回:
        (groups_map, index_map)
        - groups_map: {representative_title: [indices...]}
        - index_map: {index: first_dup_partner_index_or_None}  用于 O(1) 查重
    """
    n = len(conversations)
    titles = [c.get('title', '') for c in conversations]
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        px, py = find(x), find(y)
        if px != py:
            parent[px] = py

    for i in range(n):
        for j in range(i + 1, n):
            if find(i) == find(j):
                continue
            sim = similarity(titles[i], titles[j])
            if sim >= threshold:
                union(i, j)

    groups: Dict[int, List[int]] = defaultdict(list)
    for i in range(n):
        groups[find(i)].append(i)

    groups_map: Dict[str, List[int]] = {}
    index_map: Dict[int, Optional[int]] = {}
    for root, members in groups.items():
        if len(members) > 1:
            rep_idx = min(members, key=lambda i: len(titles[i]))
            members_sorted = sorted(members)
            groups_map[titles[rep_idx]] = members_sorted
            # 每个成员指向组内第一个不同的成员
            for m in members_sorted:
                others = [x for x in members_sorted if x != m]
                index_map[m] = others[0] if others else None

    return groups_map, index_map


# ============================================================================
# Markdown 生成
# ============================================================================

def generate_conversation_md(
    conv: Dict[str, Any],
    index: int,
    total: int,
    output_dir: Path,
    dup_index_map: Dict[int, Optional[int]],
    privacy: bool = False,
    extract_code: bool = False,
    extract_decisions_flag: bool = False,
) -> Path:
    """
    为单个对话生成 Markdown 文件。

    返回生成的文件路径。
    """
    title = conv.get('title', 'Untitled')
    conv_id = conv.get('id', 'unknown')
    created = timestamp_to_str(conv.get('created_at'))
    updated = timestamp_to_str(conv.get('updated_at'))
    messages = conv.get('_parsed_messages', [])
    category = conv.get('_category', '其他')

    # 查找重复标记（使用预计算索引映射，O(1)）
    is_duplicate = index in dup_index_map
    dup_of = dup_index_map.get(index)

    # 模型列表（已在预处理阶段计算）
    models_used = conv.get('_models', [])

    # 文件名
    safe_title = sanitize_filename(title)
    filename = f"{index:03d}_{safe_title}.md"
    filepath = output_dir / "conversations" / filename

    # 构建 Markdown 内容
    lines: List[str] = []
    lines.append(f"# {title}\n")

    # --- 元数据区 ---
    lines.append("## 对话信息\n")
    lines.append("| 属性 | 值 |")
    lines.append("|------|-----|")
    lines.append(f"| 序号 | {index} / {total} |")
    lines.append(f"| 对话 ID | `{conv_id}` |")
    lines.append(f"| 创建时间 | {created} |")
    lines.append(f"| 更新时间 | {updated} |")
    lines.append(f"| 使用模型 | {', '.join(models_used) if models_used else '未知'} |")
    lines.append(f"| 自动分类 | **{category}** |")
    if is_duplicate:
        dup_note = f"是（与 #{dup_of} 相似）" if dup_of else "是"
        lines.append(f"| 疑似重复 | ⚠️ {dup_note} |")
    lines.append(f"| 消息总数 | {len(messages)} |")
    lines.append("")

    # --- 对话流水 ---
    lines.append("## 对话流水\n")

    turn_num = 0
    for msg in messages:
        role = msg['role']
        ts = timestamp_to_str(msg['timestamp'])
        model = msg.get('model_display', '')

        if role == 'user':
            turn_num += 1
            content = msg['content']
            if privacy:
                content = apply_privacy_filter(content)
            content = content.strip()
            if len(content) < MIN_USER_MSG_LENGTH and not content:
                continue  # 跳过空消息
            lines.append(f"### 🔹 第 {turn_num} 轮 · 用户提问 `[{ts}]`\n")
            lines.append(content)
            lines.append("")

        elif role == 'assistant':
            has_thinking = bool(msg['thinking_content'] or msg['thinking_titles'])
            has_answer = bool(msg['answers'])

            if has_thinking or has_answer:
                lines.append(f"### 🔸 第 {turn_num} 轮 · AI 回复 `[{ts}]`")
                if model:
                    lines.append(f"> 模型：**{model}**")
                lines.append("")

            # 思考过程
            if msg['thinking_titles']:
                lines.append("#### 💭 思考标题\n")
                # 去重
                seen_ts: Set[str] = set()
                for t in msg['thinking_titles']:
                    if t not in seen_ts:
                        seen_ts.add(t)
                        lines.append(f"- {t}")
                lines.append("")

            if msg['thinking_content']:
                lines.append("#### 🧠 思考过程\n")
                lines.append("> **注意：以下为 AI 内部思考过程，非最终回复。**\n")
                for thought in msg['thinking_content']:
                    if privacy:
                        thought = apply_privacy_filter(thought)
                    # 保留原始格式（可能含 Markdown）
                    lines.append(thought)
                    lines.append("")
                    # 可选代码提取
                    if extract_code:
                        codes = extract_code_blocks(thought)
                        if codes:
                            lines.append("**思考中的代码片段：**\n")
                            for ci, c_block in enumerate(codes, 1):
                                lines.append(f"*代码块 {ci} ({c_block['language']})*：")
                                lines.append(f"```{c_block['language']}")
                                lines.append(c_block['code'])
                                lines.append("```\n")

            # 最终回复
            if msg['answers']:
                lines.append("#### 📝 最终回复\n")
                for ans in msg['answers']:
                    if privacy:
                        ans = apply_privacy_filter(ans)
                    lines.append(ans)
                    lines.append("")

            # 决策提取
            if extract_decisions_flag and msg['decisions']:
                lines.append("#### 🎯 关键决策/建议\n")
                for d in msg['decisions']:
                    if privacy:
                        d = apply_privacy_filter(d)
                    lines.append(f"- {d}")
                lines.append("")

            # 代码提取（从回复中）
            if extract_code and msg['code_blocks']:
                lines.append("#### 💻 代码片段\n")
                for ci, c_block in enumerate(msg['code_blocks'], 1):
                    lines.append(f"*代码块 {ci} ({c_block['language']})*：")
                    lines.append(f"```{c_block['language']}")
                    lines.append(c_block['code'])
                    lines.append("```\n")

        # 分隔线
        lines.append("---\n")

    # 页脚
    lines.append(f"\n> 生成时间：{timestamp_to_str(int(_time_module.time()))}")
    lines.append(f"> 数据来源：Qwen Studio 聊天记录导出")

    content = '\n'.join(lines)

    # 确保目录存在
    filepath.parent.mkdir(parents=True, exist_ok=True)

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

    return filepath


def generate_index(conversations: List[Dict[str, Any]],
                   groups_map: Dict[str, List[int]],
                   dup_index_map: Dict[int, Optional[int]],
                   output_dir: Path) -> Path:
    """生成可点击的对话列表索引 index.md。"""
    filepath = output_dir / "index.md"

    lines: List[str] = []
    lines.append("# Qwen Studio 聊天记录索引\n")
    lines.append(f"> 共 **{len(conversations)}** 个对话\n")
    lines.append(f"> 生成时间：{timestamp_to_str(int(_time_module.time()))}\n")

    # 按分类分组
    categorized: Dict[str, List[Tuple[int, Dict[str, Any]]]] = defaultdict(list)
    for i, conv in enumerate(conversations):
        cat = conv.get('_category', '其他')
        categorized[cat].append((i, conv))

    # 目录
    lines.append("## 分类导航\n")
    for cat in CATEGORY_KEYWORDS:
        if cat in categorized:
            count = len(categorized[cat])
            lines.append(f"- [{cat}](#{cat.replace(' ', '-')})（{count} 个）")
    lines.append("")

    # 按分类输出列表
    for cat in CATEGORY_KEYWORDS:
        if cat not in categorized:
            continue
        items = categorized[cat]
        lines.append(f"## {cat}\n")
        lines.append("| 序号 | 标题 | 模型 | 时间 | 消息数 | 标记 |")
        lines.append("|------|------|------|------|--------|------|")
        for idx, conv in items:
            title = conv.get('title', 'Untitled')
            safe_title = sanitize_filename(title)
            file_num = idx + 1  # 文件编号从 1 开始
            filename = f"{file_num:03d}_{safe_title}.md"
            link = f"[{title}](conversations/{filename})"

            models = conv.get('_models', [])
            model_str = ', '.join(models[:2]) if models else '-'
            time_str = timestamp_to_str(conv.get('created_at'))
            msg_count = len(conv.get('_parsed_messages', []))

            # 重复标记
            flags = "⚠️ 重复" if idx in dup_index_map else ""

            lines.append(f"| {file_num:03d} | {link} | {model_str} | {time_str} | {msg_count} | {flags} |")
        lines.append("")

    content = '\n'.join(lines)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

    return filepath


def generate_statistics(conversations: List[Dict[str, Any]],
                        output_dir: Path) -> Path:
    """生成统计报告 statistics.md。"""
    filepath = output_dir / "statistics.md"

    lines: List[str] = []
    lines.append("# 聊天记录统计报告\n")
    lines.append(f"> 生成时间：{timestamp_to_str(int(_time_module.time()))}\n")

    total = len(conversations)

    # --- 基本统计 ---
    all_timestamps: List[int] = []
    model_counter: Counter = Counter()
    category_counter: Counter = Counter()
    total_user_msgs = 0
    total_assistant_msgs = 0
    total_thinking_blocks = 0
    total_code_blocks = 0
    avg_msg_per_conv: List[int] = []

    for conv in conversations:
        ts = conv.get('created_at')
        if ts:
            all_timestamps.append(int(ts))
        cat = conv.get('_category', '其他')
        category_counter[cat] += 1

        messages = conv.get('_parsed_messages', [])
        avg_msg_per_conv.append(len(messages))

        for msg in messages:
            if msg['role'] == 'user':
                total_user_msgs += 1
            elif msg['role'] == 'assistant':
                total_assistant_msgs += 1
            m = msg.get('model_display', '')
            if m:
                model_counter[m] += 1
            if msg['thinking_content']:
                total_thinking_blocks += len(msg['thinking_content'])
            if msg['code_blocks']:
                total_code_blocks += len(msg['code_blocks'])

    # 时间跨度
    time_span = "未知"
    if all_timestamps:
        min_ts = min(all_timestamps)
        max_ts = max(all_timestamps)
        min_str = timestamp_to_str(min_ts)
        max_str = timestamp_to_str(max_ts)
        span_days = (max_ts - min_ts) / 86400.0
        time_span = f"{min_str} ~ {max_str}（{span_days:.0f} 天）"

    # --- 输出统计 ---
    lines.append("## 1. 基本概览\n")
    lines.append("| 指标 | 数值 |")
    lines.append("|------|------|")
    lines.append(f"| 对话总数 | {total} |")
    lines.append(f"| 用户消息总数 | {total_user_msgs} |")
    lines.append(f"| AI 回复总数 | {total_assistant_msgs} |")
    lines.append(f"| 思考块总数 | {total_thinking_blocks} |")
    lines.append(f"| 代码块总数 | {total_code_blocks} |")
    avg_msg = sum(avg_msg_per_conv) / len(avg_msg_per_conv) if avg_msg_per_conv else 0
    lines.append(f"| 平均每对话消息数 | {avg_msg:.1f} |")
    lines.append(f"| 时间跨度 | {time_span} |")
    lines.append("")

    # --- 模型使用分布 ---
    lines.append("## 2. 模型使用分布\n")
    lines.append("| 模型 | 使用次数 | 占比 |")
    lines.append("|------|----------|------|")
    total_model_uses = sum(model_counter.values())
    for model, count in model_counter.most_common():
        pct = (count / total_model_uses * 100) if total_model_uses > 0 else 0
        lines.append(f"| {model} | {count} | {pct:.1f}% |")
    lines.append("")

    # 可视化条
    lines.append("### 使用频率可视化\n")
    max_count = model_counter.most_common(1)[0][1] if model_counter else 1
    for model, count in model_counter.most_common():
        bar_len = int(count / max_count * 40)
        bar = '█' * bar_len + '░' * (40 - bar_len)
        lines.append(f"```")
        lines.append(f"{model:30s} {bar} {count}")
        lines.append(f"```")
    lines.append("")

    # --- 分类分布 ---
    lines.append("## 3. 对话主题分类分布\n")
    lines.append("| 分类 | 数量 | 占比 |")
    lines.append("|------|------|------|")
    for cat in CATEGORY_KEYWORDS:
        count = category_counter.get(cat, 0)
        pct = (count / total * 100) if total > 0 else 0
        lines.append(f"| {cat} | {count} | {pct:.1f}% |")
    lines.append("")

    # 主题可视化
    lines.append("### 分类分布可视化\n")
    for cat in CATEGORY_KEYWORDS:
        count = category_counter.get(cat, 0)
        bar_len = int(count / total * 40) if total > 0 else 0
        bar = '█' * bar_len + '░' * (40 - bar_len)
        pct = (count / total * 100) if total > 0 else 0
        lines.append(f"```")
        lines.append(f"{cat:10s} {bar} {count} ({pct:.1f}%)")
        lines.append(f"```")
    lines.append("")

    # --- 高频关键词 ---
    lines.append("## 4. 高频对话主题词\n")
    all_titles = ' '.join(c.get('title', '') for c in conversations)
    # 简单分词：提取 2-4 字的中文词
    word_pattern = re.compile(r'[一-鿿]{2,4}')
    words = word_pattern.findall(all_titles)
    word_freq = Counter(words).most_common(30)

    lines.append("| 关键词 | 出现次数 |")
    lines.append("|--------|----------|")
    for word, count in word_freq[:30]:
        if count >= 2:
            lines.append(f"| {word} | {count} |")
    lines.append("")

    # --- 时间分布 ---
    lines.append("## 5. 时间分布\n")
    if all_timestamps:
        # 按日期分组
        date_counter: Counter = Counter()
        for ts in all_timestamps:
            dt_str = timestamp_to_str(ts)[:10]  # YYYY-MM-DD
            date_counter[dt_str] += 1

        lines.append("### 每日对话数量\n")
        lines.append("| 日期 | 对话数 | 分布 |")
        lines.append("|------|--------|------|")
        max_daily = max(date_counter.values()) if date_counter else 1
        for date_str in sorted(date_counter.keys()):
            count = date_counter[date_str]
            bar_len = int(count / max_daily * 30)
            bar = '█' * bar_len
            lines.append(f"| {date_str} | {count} | {bar} |")
        lines.append("")

    # --- 消息最多的对话 ---
    lines.append("## 6. 消息数最多的对话（Top 10）\n")
    lines.append("| 序号 | 标题 | 消息数 | 分类 |")
    lines.append("|------|------|--------|------|")
    sorted_by_msg = sorted(enumerate(conversations), key=lambda x: len(x[1].get('_parsed_messages', [])), reverse=True)
    for rank, (idx, conv) in enumerate(sorted_by_msg[:10], 1):
        title = conv.get('title', 'Untitled')
        safe_title = sanitize_filename(title)
        link = f"[{title}](conversations/{idx + 1:03d}_{safe_title}.md)"
        msg_count = len(conv.get('_parsed_messages', []))
        cat = conv.get('_category', '其他')
        lines.append(f"| {rank} | {link} | {msg_count} | {cat} |")
    lines.append("")

    content = '\n'.join(lines)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

    return filepath


# ============================================================================
# 主流程
# ============================================================================

def parse_arguments() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        description="Qwen Studio 聊天记录解析与提取工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            示例：
              python qwen_chat_extractor.py
              python qwen_chat_extractor.py --input chat.json --output ./output
              python qwen_chat_extractor.py --category 技术配置 --extract-code
              python qwen_chat_extractor.py --privacy -v
        """),
    )

    parser.add_argument(
        '--input', '-i',
        type=str,
        default='chat-export-1778291923790.json',
        help='输入 JSON 文件路径（默认：chat-export-1778291923790.json）',
    )
    parser.add_argument(
        '--output', '-o',
        type=str,
        default='output',
        help='输出目录路径（默认：output）',
    )
    parser.add_argument(
        '--category', '-c',
        type=str,
        default=None,
        choices=['技术配置', '学习相关', '设备硬件', '健康生活', '其他'],
        help='仅处理指定分类的对话（默认：处理全部）',
    )
    parser.add_argument(
        '--extract-code',
        action='store_true',
        default=False,
        help='启用代码块提取功能',
    )
    parser.add_argument(
        '--extract-decisions',
        action='store_true',
        default=False,
        help='启用决策/建议语句提取功能',
    )
    parser.add_argument(
        '--privacy',
        action='store_true',
        default=False,
        help='启用隐私过滤（替换 API 密钥、邮箱、IP 等敏感信息）',
    )
    parser.add_argument(
        '--no-conversations',
        action='store_true',
        default=False,
        help='跳过生成独立对话文件，仅生成索引和统计',
    )
    parser.add_argument(
        '--dup-threshold',
        type=float,
        default=0.8,
        help='重复检测相似度阈值（0.0~1.0，默认 0.8）',
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        default=False,
        help='详细输出模式',
    )

    return parser.parse_args()


def load_json(input_path: str) -> Dict[str, Any]:
    """加载并验证 JSON 文件。"""
    path = Path(input_path)
    if not path.exists():
        print(f"❌ 错误：输入文件不存在: {input_path}")
        sys.exit(1)

    file_size_mb = path.stat().st_size / (1024 * 1024)
    print(f"📂 正在加载 JSON 文件... ({file_size_mb:.1f} MB)")

    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"❌ JSON 解析错误: {e}")
        sys.exit(1)
    except UnicodeDecodeError as e:
        print(f"❌ 编码错误，请确认文件为 UTF-8 编码: {e}")
        sys.exit(1)

    if not data.get('success'):
        print("⚠️  警告：JSON 中 success 字段为 false，继续处理...")

    conversations = data.get('data')
    if not conversations or not isinstance(conversations, list):
        print("❌ 错误：JSON 中缺少 data 数组")
        sys.exit(1)

    print(f"✅ 加载成功：{len(conversations)} 个对话")
    return data


def process_conversations(data: Dict[str, Any], args: argparse.Namespace) -> \
        Tuple[List[Dict[str, Any]], Dict[str, List[int]]]:
    """
    主处理流程：解析所有对话、分类、去重。

    返回：(对话列表, 重复分组)
    """
    raw_conversations: List[Dict[str, Any]] = data.get('data', [])
    total = len(raw_conversations)
    conversations: List[Dict[str, Any]] = []

    print(f"🔄 正在解析对话消息...")

    iterator = enumerate(raw_conversations)
    if HAS_TQDM:
        iterator = tqdm(iterator, total=total, desc="解析进度", unit="对话", ncols=80) if HAS_TQDM else iterator

    for i, conv in iterator:
        if not isinstance(conv, dict):
            continue

        title = conv.get('title', 'Untitled')
        conv_id = conv.get('id', '')
        created_at = conv.get('created_at')
        updated_at = conv.get('updated_at')

        # 解析消息
        messages_dict = safe_get(conv, 'chat', 'history', 'messages', default={})
        parsed_msgs = parse_messages(messages_dict)

        # 收集用户消息文本
        user_texts = [m['content'] for m in parsed_msgs if m['role'] == 'user']
        # 收集所有文本用于分类
        all_text = ' '.join(
            user_texts +
            [t for m in parsed_msgs for t in m['thinking_content']] +
            [a for m in parsed_msgs for a in m['answers']]
        )

        # 自动分类
        category = classify_conversation(title, user_texts, all_text)

        # 收集模型
        models: List[str] = []
        seen: Set[str] = set()
        for msg in parsed_msgs:
            m = msg.get('model_display', '')
            if m and m not in seen:
                models.append(m)
                seen.add(m)

        conversations.append({
            'id': conv_id,
            'title': title,
            'created_at': created_at,
            'updated_at': updated_at,
            '_parsed_messages': parsed_msgs,
            '_category': category,
            '_models': models,
        })

    # 按创建时间排序
    conversations.sort(key=lambda c: (c['created_at'] is None, c['created_at'] or 0))

    # 重复检测
    print(f"🔍 正在进行重复检测（阈值: {args.dup_threshold}）...")
    groups_map, index_map = detect_duplicates(conversations, threshold=args.dup_threshold)
    dup_count = sum(len(v) for v in groups_map.values())
    if groups_map:
        print(f"⚠️  发现 {len(groups_map)} 组疑似重复（共 {dup_count} 个对话）")
        if args.verbose:
            for rep_title, members in groups_map.items():
                member_str = ', '.join(f"#{m}" for m in members)
                print(f"   · [{rep_title}] → {member_str}")
    else:
        print("✅ 未发现疑似重复对话")

    return conversations, groups_map, index_map


def main() -> None:
    """主入口函数。"""
    args = parse_arguments()

    print("=" * 60)
    print("  Qwen Studio 聊天记录解析与提取工具")
    print("=" * 60)
    print()

    # 1. 加载 JSON
    data = load_json(args.input)

    # 2. 解析处理
    conversations, groups_map, index_map = process_conversations(data, args)

    # 3. 按分类过滤
    if args.category:
        conversations = [c for c in conversations if c['_category'] == args.category]
        print(f"🎯 仅处理分类「{args.category}」：{len(conversations)} 个对话")
        if not conversations:
            print("⚠️  警告：没有匹配的对话，将生成空报告")
    else:
        print(f"📊 全部对话：{len(conversations)} 个")

    # 4. 创建输出目录
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    conv_dir = output_dir / "conversations"
    conv_dir.mkdir(parents=True, exist_ok=True)

    # 5. 生成对话 Markdown 文件
    if not args.no_conversations:
        print(f"📝 正在生成对话 Markdown 文件...")
        total = len(conversations)
        iterator = enumerate(conversations)
        if HAS_TQDM:
            iterator = tqdm(iterator, total=total, desc="生成文件", unit="个", ncols=80) if HAS_TQDM else iterator

        for i, conv in iterator:
            generate_conversation_md(
                conv=conv,
                index=i + 1,
                total=total,
                output_dir=output_dir,
                dup_index_map=index_map,
                privacy=args.privacy,
                extract_code=args.extract_code,
                extract_decisions_flag=args.extract_decisions,
            )
        print(f"✅ 已生成 {total} 个对话文件 → {conv_dir}")

    # 6. 生成索引
    print(f"📑 正在生成索引文件...")
    generate_index(conversations, groups_map, index_map, output_dir)
    print(f"✅ index.md → {output_dir / 'index.md'}")

    # 7. 生成统计报告
    print(f"📈 正在生成统计报告...")
    generate_statistics(conversations, output_dir)
    print(f"✅ statistics.md → {output_dir / 'statistics.md'}")

    # 8. 完成摘要
    print()
    print("=" * 60)
    print("  处理完成！")
    print("=" * 60)
    print(f"  对话总数       : {len(conversations)}")
    print(f"  重复组数       : {len(groups_map)}")
    print(f"  输出目录       : {output_dir.resolve()}")
    print(f"  隐私过滤       : {'开启' if args.privacy else '关闭'}")
    print(f"  代码提取       : {'开启' if args.extract_code else '关闭'}")
    print(f"  决策提取       : {'开启' if args.extract_decisions else '关闭'}")
    print()


if __name__ == '__main__':
    main()
