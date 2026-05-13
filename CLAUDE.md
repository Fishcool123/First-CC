# CLAUDE.md

## 语言
默认中文回答。代码注释、docstring 用中文，技术术语保留原词。

## 项目定位
个人认知增强三大系统 → 一个 PyQt5 桌面应用 → 本地 Agent 常驻驱动。
目标：将模糊的主观体验（情绪、精力、行为）转化为可追踪分析的客观数据，
实现隐私死守的自我认知基础设施。
用户为中国计量大学数据科学专业大一学生，编程基础薄弱。

## 演进路径
v1（三个独立 Flask）→ v2（统一 Flask+Vue3，已完成）→ v3（agent_proto PyQt5 桌面应用，开发中）。
v2 可用但即将被取代。v1 目录仅保留参考。

## 目录
```
First CC/
├── 🟢 agent_proto/          ← v3 当前开发（Agent 闭环 + PyQt5 桌面应用）
├── 🔒 认知增强系统/         ← v2 统一应用（Flask+Vue3，即将废弃）
├── 🔒 时间切片系统/         ← v1 旧版（保留参考）
├── 🔒 PC智能任务助理/       ← v1 旧版（保留参考）
├── 📋 策划案撰写/           ← 参考文档
└── 📋 历史要求记录/         ← 需求文档
```
🟢=活跃开发  🔒=废弃/参考  📋=参考文档

## 三大系统（概念不变，实现演进）
1. **时间切片系统** — 底层数据土壤。多粒度时间点状态记录（思想/情绪/行为/环境）。
2. **AI情感辅助系统** — 核心健康模块。情绪→数据，趋势报告+认知重构+主动介入。
3. **PC智能任务助理** — 效率调度模块。任务排程+精力匹配+甘特图。
三者关系：切片系统是数据源，情感和任务各取所需。

## v3 核心架构

### Agent 闭环
Observer（窗口监控+空闲检测+剪贴板）→ Thinker（本地9B推理+人格卡）→ Actor（通知+日志+UI更新）。
10秒采样周期。分层隐私：原始数据留本地，脱敏聚合后可上云。

### 三 Persona（统一声音）
recorder（记录提醒）/ companion（情感关切）/ scheduler（任务调度）。
三个侧面，同一声音，仅微妙色调区分。用户不感知"现在是谁在说话"。

### 目标 UI
三个 tab：⏱时间切片 / 💬情感辅助（方案C上下铺：聊天窗+可折叠数据图表） / 📋任务助理。
底部终端日志面板（可折叠+可独立弹出）。

详见 `agent_proto/DESIGN.md`。

## 关键设计决策（2026-05-13 锁定）
| 决策 | 结论 |
|------|------|
| 数据库 | database.py 独立维护于 agent_proto/，不引用 v2 |
| 情感辅助 UI | 方案C上下铺混合型，C1→C4 分级实现 |
| Persona | 统一声音，微妙色调 |
| 终端日志 | 嵌入底部可折叠 + 可独立弹出 |
| 执行顺序 | P0修复 → UI重构 → 功能补全 |
| 打包 | UI重构开始时建 .spec，每 tab 验证 |
| v2 | 完全废弃 Web 版，全部重写进 PyQt5 |

## 技术栈
Python 3.13.5 / PyQt5 / SQLite WAL / llama.cpp HTTP API（本地 Qwen3.5-9B-Q4_K_M）/
pywin32+psutil（窗口监控）/ DeepSeek API + Qwen3.6-Plus API（云端脱敏数据）

## 用户工具链
Cherry Studio（主用对话端）/ Claude Code（系统构筑）/ llama.cpp 桌面版（本地推理）/
ima（知识库）/ Qwen Studio（偶尔）

## 常用命令
```bash
# 语法检查
py -c "import py_compile; py_compile.compile('agent_loop.py', doraise=True)"

# 依赖
py -m pip install flask psutil pywin32 pystray plyer pillow pyqt5 openai pyyaml pyperclip

# 启动 v3 Agent
cd agent_proto && py agent_loop.py
```

## 工作前必读
1. `agent_proto/DESIGN.md` — 完整架构设计
2. `agent_proto/BUILD_PLAN.md` — 分阶段构建计划
3. `agent_proto/agent_personas/` — 三个人格卡
