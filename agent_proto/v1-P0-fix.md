# v1-P0-fix：Agent 修复验证 + 数据库独立化 + 冒烟测试

> 给 Claude Code 的执行指令。按顺序执行，每步完成后报告结果再继续。

---

## 背景

FIX_PLAN.md（P0-P3）和 TODO_v5.md（1-5）的修复代码**已经写入源文件**，但 Agent 在修复后从未启动验证过（proto_log.md 最后记录 2026-05-12）。本次任务是：

1. 盘点已完成的修复，确认代码正确性
2. 完成数据库独立化（此前未做的决策）
3. 启动 30 分钟冒烟测试，确认 P0 bug 真正修复

---

## 步骤 1：修复清单盘点

逐项检查以下代码是否已在源文件中正确实现。**只读检查，不要修改**。每项报告「✅ 已实现」或「❌ 缺失」。

### P0（冷却期与窗口过滤）

| 编号 | 修复项 | 检查位置 | 关键特征 |
|------|--------|---------|----------|
| P0-1 | 批次级全局冷却 | `agent_loop.py` 主循环 | `batch_in_cooldown` 变量 + `batch_spoke` 标志 + for 循环前检查 |
| P0-2 | 窗口时长过滤 | `agent_loop.py` 事件处理+心跳 | `_parse_duration_seconds()` + `MIN_WINDOW_DURATION = 120` 检查 |
| P0-3 | Actor 兜底 3s 间隔 | `agent_actor.py` speak() | `_last_actor_speak` 全局变量 + 3.0s 检查 |

### P1（Recorder 人格卡增强）

| 编号 | 修复项 | 检查位置 | 关键特征 |
|------|--------|---------|----------|
| P1-1 | 话术多样化 | `agent_personas/recorder.md` | `## 话术风格` 章节 + 8+ 种情境模板 |
| P1-2 | 情境判断逻辑 | `agent_personas/recorder.md` | `## 决策逻辑` 章节 + 5 步决策流程 |

### TODO_v5

| 编号 | 修复项 | 检查位置 | 关键特征 |
|------|--------|---------|----------|
| T1 | today_mood_summary | `agent_memory.py` | `get_today_mood_summary()` 函数 + enrich_context 调用 |
| T2 | get_pending_tasks | `agent_memory.py` | `get_pending_tasks()` 返回 list[dict] + enrich_context 调用 |
| T3 | IDE 自动切换 | `agent_loop.py` | `IDE_KEYWORDS` 列表 + `ide_since`/`ide_sleep_sent` 变量 + mode_cb 回调 |
| T4 | 凌晨 0-6 静默 | `agent_loop.py` 事件处理+心跳 | `0 <= datetime.now().hour < 6` 检查 |
| T5 | 悬浮窗右键菜单 | `agent_ui.py` FloatingDot | `contextMenuEvent()` 方法 |

### P3（重复代码清理）

| 编号 | 修复项 | 检查位置 | 关键特征 |
|------|--------|---------|----------|
| P3 | update_status 去重 | `agent_ui.py` | 全局空间中只有一个 `def update_status(` 定义 |

**报告格式**：一个表格，列出每项的状态。如果任何项缺失，在此步骤报告，不要自行修改。

---

## 步骤 2：数据库独立化

将 database.py 从 v2 复制到 agent_proto 目录，使 agent_proto 完全独立维护。

### 2.1 复制 database.py

```
源: C:\Users\www15\Desktop\First CC\认知增强系统\database.py
目标: C:\Users\www15\Desktop\First CC\agent_proto\database.py
```

用 `shutil.copy2` 复制（保留时间戳），不要用移动。

### 2.2 创建 agent_proto/data/ 目录

在 `agent_proto/data/` 下创建空目录（如果不存在）。不需要复制 v2 的 .db 文件——agent_proto 会创建自己的数据库。

### 2.3 修改 database.py 的数据库路径

`database.py` 第一行之后插入：
```python
# agent_proto 独立部署：数据库路径相对于本文件
```

确认以下变量指向 agent_proto/data/：
```python
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
TASKS_DB = DATA_DIR / "task_assistant.db"
SLICES_DB = DATA_DIR / "slices.db"
```

这些路径应该**不需要修改**（原来就是相对于 database.py 所在目录），但需要验证。

### 2.4 移除旧项目迁移逻辑（可选但建议）

`database.py` 中有 `_migrate_db()` 函数和 `OLD_TASKS_DIR` / `OLD_SLICES_DIR` 变量，它们引用 `../PC智能任务助理` 和 `../时间切片系统`。在 agent_proto 独立部署中这些路径无效。

**处理方式**：
- 保留 `_migrate_db()` 函数体但修改候选源路径为空列表 `[]`
- 或者保留不动（迁移失败时会静默跳过，不影响功能）
- **选后者**：改动最小，风险最低。`_migrate_db()` 找不到源文件时会打印警告但不会崩溃。

### 2.5 重写 agent_memory.py 的数据库连接

**当前问题**：agent_memory.py 硬编码路径到 `../认知增强系统/data/`。

**目标**：改为 import 本地 database.py，使用它的路径常量。

**修改方式**：

1. 删除现有的硬编码路径变量（第 12-16 行）：
   ```python
   # 删除以下 5 行
   BASE_DIR = os.path.dirname(os.path.abspath(__file__))
   V2_DATA = os.path.normpath(os.path.join(BASE_DIR, "..", "认知增强系统", "data"))
   SLICES_DB = os.path.join(V2_DATA, "slices.db")
   TASKS_DB = os.path.join(V2_DATA, "task_assistant.db")
   ```

2. 在文件顶部导入区域（`import sqlite3` 之后）添加：
   ```python
   from database import SLICES_DB, TASKS_DB
   ```

3. SLICES_DB 和 TASKS_DB 现在是 `Path` 对象（database.py 使用 pathlib），需要转换：
   ```python
   SLICES_DB = str(SLICES_DB)
   TASKS_DB = str(TASKS_DB)
   ```

4. **注意**：`_ro_connect()` 函数使用 `uri=True` 的 SQLite 连接。Path 对象的 `as_uri()` 或直接用 `str(path)` 传给 `file:` URI 都可以。但 database.py 导出的 SLICES_DB 已经是 Path 对象，而 `urllib.parse.quote` 可能需要处理 Windows 反斜杠。修改 `_ro_connect()` 为：
   ```python
   import urllib.parse
   
   def _ro_connect(db_path):
       """WAL 兼容的只读连接"""
       abs_path = os.path.abspath(str(db_path))
       uri = "file:{}?mode=ro".format(urllib.parse.quote(abs_path, safe='/:\\'))
       return sqlite3.connect(uri, uri=True)
   ```

5. 移除不再需要的 `_connect_slices_db()` 和 `_connect_task_db()` 包装函数中的间接调用，直接使用 `_ro_connect(SLICES_DB)` 和 `_ro_connect(TASKS_DB)`。

### 2.6 验证数据库独立化

在 agent_proto 目录下运行：
```bash
python -c "from database import init_db; init_db(); print('OK')"
```

预期：在 `agent_proto/data/` 下创建 `slices.db` 和 `task_assistant.db` 两个空数据库。

---

## 步骤 3：首次启动前的初始化

### 3.1 初始化数据库

```bash
cd C:\Users\www15\Desktop\First CC\agent_proto
python -c "from database import init_db; init_db()"
```

### 3.2 检查依赖

确认以下库已安装：
- `pywin32`（窗口监控）
- `psutil`（进程名获取）
- `pyperclip`（剪贴板监听，可选）
- `plyer`（Windows 通知，可选）
- `PyQt5`（悬浮窗 UI）
- `openai`（Thinker 调用本地 llama.cpp API）

如果缺失，用 `pip install` 安装。

---

## 步骤 4：30 分钟冒烟测试

### 4.1 启动 Agent

```bash
cd C:\Users\www15\Desktop\First CC\agent_proto
python agent_ui.py
```

或者只跑 Agent 循环（无悬浮窗）：
```bash
python agent_loop.py
```

**建议先用 agent_loop.py**（终端模式，日志更清晰），确认稳定后再测 agent_ui.py。

### 4.2 测试期间的行为

在 30 分钟内，正常使用电脑：
- 切换几个窗口（IDE、浏览器、文件管理器）
- 在浏览器中浏览几个页面
- 复制一段文字
- 离开电脑 5 分钟以上（触发空闲检测）

### 4.3 实时检查点

每隔 5-10 分钟检查一次终端输出：

- [ ] 冷却期拦截日志出现：`[冷却] 距上次发言 X 分 X 秒，跳过 Y 个事件`
- [ ] 窗口过滤日志出现：`[过滤] 窗口仅活跃 X 秒，跳过`
- [ ] 凌晨静默日志出现（如果测试时间在 0-6 点）：`[Agent] SILENT | L0 | 凌晨静默`
- [ ] IDE 检测日志出现（打开 Cursor 5 分钟）：`[IDE] 检测到 IDE 窗口，开始计时`
- [ ] 没有同一秒两条 speak
- [ ] 两次主动 speak 之间间隔 ≥ 10 分钟

### 4.4 测试后检查 proto_log.md

```bash
# 统计 speak 次数和时间间隔
python -c "
import re
from datetime import datetime

with open('proto_log.md', 'r', encoding='utf-8') as f:
    content = f.read()

# 提取所有时间戳
timestamps = re.findall(r'## (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})', content)
times = [datetime.fromisoformat(ts) for ts in timestamps]

print(f'总消息数: {len(times)}')
if len(times) >= 2:
    intervals = [(times[i+1] - times[i]).total_seconds() for i in range(len(times)-1)]
    min_interval = min(intervals)
    avg_interval = sum(intervals) / len(intervals)
    print(f'最小间隔: {min_interval:.0f} 秒')
    print(f'平均间隔: {avg_interval/60:.1f} 分钟')
    short = [i for i in intervals if i < 600]
    print(f'间隔 < 10 分钟的次数: {len(short)}')
    if short:
        print('🚨 冷却期违规！')
    else:
        print('✅ 冷却期合规（所有间隔 ≥ 10 分钟）')
"
```

---

## 步骤 5：问题修复（如果有）

如果步骤 4 发现任何问题：

1. **冷却期违规** → 检查 `agent_loop.py` 中 `last_speak_time` 的更新时机。心跳分支（第 691-693 行）和事件分支（第 634-635 行）都必须更新 `last_speak_time`。

2. **窗口过滤不工作** → 检查 `_parse_duration_seconds()` 函数是否正确解析中文格式的时长字符串。

3. **凌晨未静默** → 检查系统时间是否真的在 0-6 点范围内。

4. **proto_log.md 不更新** → 检查 `agent_actor.py` 中 `_write_log()` 的文件写入权限和路径。

---

## 验证清单（最终）

- [ ] 步骤 1：所有修复项已盘点（报告表格）
- [ ] 步骤 2.1：database.py 已复制到 agent_proto/
- [ ] 步骤 2.2：agent_proto/data/ 目录已创建
- [ ] 步骤 2.5：agent_memory.py 已改为引用本地 database.py
- [ ] 步骤 2.6：`from database import init_db` 导入成功
- [ ] 步骤 3.1：数据库初始化成功
- [ ] 步骤 4：Agent 运行 ≥ 30 分钟，终端无异常
- [ ] 步骤 4.4：两次 speak 间隔 ≥ 10 分钟
- [ ] 步骤 4.4：无同一秒内两条消息
- [ ] 步骤 4.4：无「在 X 上待了 Y 秒」（Y < 120）的提醒
- [ ] proto_log.md 持续更新

---

*写入时间：2025-07-23 | 给 Claude Code 的执行指令 | 基于 FIX_PLAN.md + TODO_v5.md（均已代码完成，待验证）*
