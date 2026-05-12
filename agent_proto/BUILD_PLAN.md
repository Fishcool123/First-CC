# Agent Loop 原型 — 构建计划

> 状态：待 Claude Code 执行 | 原则：每步可独立验证，不做无用功

---

## 阶段 0：环境验证（Day 1）

**目标**：确认所有依赖可用，9B 模型端点可连通。

### 任务
1. 验证 llama.cpp 端点：`http://localhost:8080/v1/chat/completions`
   - 发送简单请求，确认 32 tok/s 输出
   - 测试中文对话质量
2. 验证 Python 环境：`py --version`（确认 Python 3.13.5）
3. 安装 agent_proto 需要的额外依赖：
   - `openai`（用于调用兼容 API）
   - `pyyaml`（读取 llm_config.yaml）
   - `pyperclip`（剪贴板监听）
4. 验证可读取 v2 数据库：`../认知增强系统/data/slices.db` 和 `task_assistant.db`

### 成功标准
- 终端中运行 Python 脚本，成功调用本地 9B 并得到中文回复
- 成功连接 v2 SQLite 并执行 SELECT 查询

---

## 阶段 1：Observer 层（Day 1-2）

**目标**：搭建确定性数据采集，输出结构化上下文给 Thinker。

### 任务
1. 实现 `agent_loop.py` 主循环骨架：
   - 事件监听器（窗口切换、空闲超时、时段切换）
   - 5 分钟兜底定时器
   - 主循环不阻塞，Observer→Thinker→Actor 串行执行
2. 实现 Observer 采集函数（在 agent_loop.py 内或独立 observer.py）：
   - `get_active_window_info()` → {title, process_name, started_at}
   - `get_idle_duration()` → 秒（调用 `GetLastInputInfo`）
   - `get_time_context()` → {hour, weekday, is_work_hour, is_night}
   - `get_clipboard_text()` → 剪贴板内容（首次仅记录，不送 LLM）
3. 每个事件触发时，组装 `context` dict 并打印到终端
4. Observer 采样频率：事件触发即时 + 每 10 秒轻量采样（仅更新窗口计时器，不送 Thinker）

### 成功标准
- 运行 agent_loop.py，终端持续输出格式化的上下文数据
- 切换窗口、空闲后恢复时，终端即时打印事件信息

### 复用参考
- v2 `monitor.py` 的 `WindowMonitor` 类和 `_minute_buffer` 逻辑
- 但 Agent 版的 Observer **不按分钟聚合**——保留原始事件粒度

---

## 阶段 2：Thinker 层（Day 2-3）

**目标**：本地 9B 根据上下文判断「该不该说话」并生成话术。

### 任务
1. 实现 `agent_thinker.py`：
   - `load_persona(persona_name)` → 读取人格卡 markdown + 返回 system prompt
   - `build_context_prompt(context)` → 将 Observer 上下文填入人格卡模板
   - `think(context, persona)` → 调用本地 9B API，返回决策
2. 实现 `llm_config.yaml` 配置文件 + 加载函数
3. Thinker 决策输出格式（JSON 解析）：
   ```json
   {
     "should_speak": true/false,
     "message": "刚才在 VS Code 待了 25 分钟，要记一下吗？",
     "autonomy_level": "L1",
     "persona": "recorder"
   }
   ```
4. 首次只实现 recorder persona
5. 错误处理：LLM 返回非 JSON → 降级为静默（should_speak=false）

### 成功标准
- 提供一段模拟上下文 → 9B 返回正确的决策 JSON
- 窗口切换事件 → Thinker 判断应说话 → 输出恰当的中文话术
- 深夜时段 → Thinker 判断不应说话 → should_speak=false

---

## 阶段 3：Actor 层 + 闭环（Day 3-4）

**目标**：Actor 执行 Thinker 的决策，完成首次闭环。

### 任务
1. 实现 `agent_actor.py`：
   - `speak(message)` → 终端彩色打印（初期）+ 写入 proto_log.md
   - `record_slice(context, message)` → 通过 agent_memory.py 写入 v2 slices.db（可选）
   - `update_status(color, breath_rate)` → 预留，暂不实现（等悬浮窗阶段）
2. 实现 `agent_memory.py`：
   - `read_v2_db()` → 只读连接 v2 SQLite
   - `get_today_slice_count()` → 今日切片数
   - `get_last_manual_record()` → 上次手动记录时间
   - `get_recent_activity()` → 最近 N 小时设备日志摘要
3. 跑通完整闭环：
   ```
   Observer 检测事件 → Thinker(9B) 决策 → Actor 终端输出 + 写日志
   ```
4. 观察 30 分钟真实运行，记录 Agent 的决策质量

### 成功标准
- 运行 agent_loop.py，正常工作期间 Agent **自主**在终端打印至少一条恰当消息
- proto_log.md 中记录完整对话历史
- Agent 不在深夜/专注模式中误触发

---

## 阶段 3.5：初始数据积累（Day 4-7）

**目标**：Agent 在后台静默运行，积累基础行为数据。

### 任务
1. 让 agent_loop.py 在后台持续运行 2-3 天
2. 每日检查 proto_log.md，评估：
   - 触发频率是否合适（不太多也不太少）
   - 话术是否自然（而非机器人感）
   - 是否有误触发或漏触发
3. 根据观察结果微调：
   - 人格卡话术
   - 触发阈值（如「15 分钟」窗口切换阈值）
   - 时段策略

### 成功标准
- 2 天内 Agent 行为趋于稳定
- 用户对 Agent 的存在感到自然而非打扰

---

## 阶段 4：Persona 扩展 + UI（后续）

> 以下仅规划，MVP 不执行

1. 基于积累的情绪数据，激活 companion 人格卡
2. 基于积累的任务数据，激活 scheduler 人格卡
3. 搭建悬浮窗 UI（PyQt/PySide 或 Tkinter Canvas）
4. 实现灵动岛式变形动画（悬浮窗 ↔ 聊天窗）
5. 实现托盘图标 + 模式切换菜单
6. 云端 API 接口接入（脱敏后的趋势分析）
7. 小米手环数据接口接入

---

## 文件清单（Claude Code 需创建）

```
agent_proto/
├── DESIGN.md                         ✅ 已存在（本设计文档）
├── BUILD_PLAN.md                     ✅ 本文件
├── agent_personas/
│   ├── recorder.md                   ✅ 已存在
│   ├── companion.md                  ✅ 已存在（骨架）
│   └── scheduler.md                  ✅ 已存在（骨架）
│
├── agent_loop.py                     ❌ 待创建 — 主循环
├── agent_thinker.py                  ❌ 待创建 — LLM推理引擎
├── agent_memory.py                   ❌ 待创建 — v2数据只读
├── agent_actor.py                    ❌ 待创建 — 行动执行器
├── llm_config.yaml                   ❌ 待创建 — LLM配置
└── proto_log.md                      ❌ 待创建 — 运行日志（空文件）
```

---

## 技术规范（给 Claude Code）

- **语言**：Python 3.13.5（`py.exe`）
- **LLM 调用**：使用 `openai` Python 库，base_url 指向 `http://localhost:8080/v1`
- **数据库**：sqlite3（只读模式打开 v2 数据库，WAL 模式兼容）
- **窗口监控**：pywin32 + psutil（参考 v2 monitor.py）
- **剪贴板**：pyperclip（轮询检测变化）
- **日志**：Python logging 模块，同时输出终端和文件
- **异步**：`threading` 多线程（Observer 采样线程 + Thinker 推理线程 + 主循环线程）
- **配置**：YAML 格式，pyyaml 解析
- **注释/docstring**：中文，技术术语保留原词

### 时段切换定义

阶段1 中「时段切换」触发事件的精确时间边界：

| 时段 | 时间范围 | 特征 |
|------|---------|------|
| 上午 | 06:00–12:00 | 默认陪伴态 |
| 下午 | 12:00–18:00 | 默认陪伴态 |
| 晚上 | 18:00–23:00 | 默认对话态（更放松） |
| 深夜 | 23:00–06:00 | 强制休眠态（L0静默，除非L4紧急） |

切换到新时段时触发 Thinker 判断一次（如从下午切到晚上，agent 可以问候）。深夜时段内所有 Persona 默认 L0。

### 线程安全规范

阶段1 起即需遵守：

- **Observer 采样线程**（10秒间隔）写入 `observer_buffer`（list + threading.Lock）
- **事件检测**在主循环中轮询 `observer_buffer`，取出事件后清空
- **Thinker 推理线程**单例运行：新事件到达时，若 Thinker 正在推理，新事件**排队**（最多 3 个事件），超出则丢弃最旧事件并记录日志
- **Actor 执行**在 Thinker 线程完成后同步调用（不另开线程），确保话术输出不并发
- 所有共享状态（`observer_buffer`、`last_thinker_result`、`persona_state`）使用 `threading.Lock` 保护

### L2 监听实现指导

阶段 0-3 中实现以下 L2 监听（已在观察范围中确认全开）：

- **剪贴板监听**（pyperclip）：
  - 每 2 秒检查剪贴板内容是否变化
  - 变化时：记录时间戳 + 文本内容到 `clipboard_log` 表（SQLite，本地加密存储）
  - MVP 阶段不送 LLM，先积累数据；后续阶段由本地 9B 做任务语义识别
  - 注意：pyperclip 在 Windows 上需确保有活动窗口，否则可能失败

- **浏览器 URL 监听**：
  - 通过活跃窗口标题判断是否浏览器（Chrome/Firefox/Edge）
  - 若是浏览器，尝试从窗口标题中提取 URL（部分浏览器在标题中显示当前标签页 URL）
  - 若无法从标题提取，暂不做额外监听（等后续阶段研究浏览器扩展方案）
  - 敏感参数剥离：写入前去除 `token`、`access_key`、`session` 等 query param

- **系统通知监听**（winrt/winsdk）：
  - 使用 `winrt` 库订阅 Windows 通知监听器
  - 若 winrt 不可用，降级为监听 `action center` 的轮询（每 30 秒）
  - 仅记录通知标题+应用名，不记录通知正文详情
  - 技术难度较高，MVP 阶段若受阻可标记为 TODO 并跳过
