# Agent Proto 当前状态（2026-05-14）

> 离队前快照 — 数模竞赛归来后可从此续接

---

## 完成度总览

| 模块 | 状态 | 说明 |
|------|------|------|
| Observer | ✅ 完成 | 窗口监控（pywin32）+ 空闲检测 + 剪贴板轮询 + IDE 自动识别 |
| Thinker | ✅ 完成 | 本地 9B（llama.cpp）推理 + 3 persona（recorder/companion/scheduler） |
| Actor | ✅ 完成 | 终端彩色输出 + proto_log 持久化 + 悬浮窗状态更新 |
| Agent Bridge | ✅ 完成 | Qt Signal 总线，解耦 Agent 线程与 UI 线程 |
| UI v3 | ✅ 完成 | PyQt5 桌面应用，Cherry Studio 浅色风格，左侧 sidebar 导航 |
| 数据库 | ✅ 完成 | SQLite WAL 模式，独立维护于 agent_proto/data/ |
| 打包 | ️ 待验证 | .spec 已存在，需重新验证打包 |

---

## 当前架构

```
agent_proto/
├── agent_loop.py          ← Observer + 主循环 + 事件分发
├── agent_thinker.py       ← LLM 推理（本地 9B + 人格卡）
├── agent_actor.py         ← 行动执行（输出 + 日志）
├── agent_memory.py        ← 数据读取（slices.db + task_assistant.db）
├── agent_bridge.py        ← Qt Signal 总线（Agent → UI）
├── agent_cloud.py         ← 云端 API（DeepSeek Qwen，脱敏聚合）
├── agent_health.py        ← 健康数据（小米手环，预留接口）
├── agent_ui.py            ← 主入口（MainWindow + CompanionDot + TrayManager）
├── database.py            ← SQLite 连接 + WAL 初始化
├── llm_config.yaml        ← LLM 端点配置
├── cherry_style_light.qss ← 浅色全局样式
├── requirements.txt       ← 依赖列表
│
├── widgets/
│   ├── time_slice_tab.py   ← 时间切片 tab（热力图 + 快速记录 + 历史表格）
│   ├── emotional_tab.py    ← 情感辅助 tab（聊天窗嵌入/弹出 + DataPanel）
│   ├── task_tab.py         ← 任务助理 tab（任务 CRUD + 甘特图）
│   ├── terminal_panel.py   ← 终端日志（QDockWidget，黑底绿字）
│   ├── data_panel.py       ← 情绪数据可视化（折线图 + 标签云）
│   ├── gantt_chart.py      ← 甘特图（QPainter 手绘）
│   └── heatmap.py          ← 年度热力图（GitHub 风格）
│
└── agent_personas/
    ├── recorder.md         ← recorder 人格卡（记录提醒）
    ├── companion.md        ← companion 人格卡（情感关切）
    └── scheduler.md        ← scheduler 人格卡（任务调度）
```

---

## 已知问题

### 🔴 严重（无）

### 🟡 中优先级

1. **打包未验证** — `.spec` 在上次大改后未重新测试，需运行 `py -m PyInstaller agent_proto.spec` 验证
2. **winrt 通知监听未启用** — 因依赖安装复杂，当前跳过，功能完整但无系统通知感知
3. **Browser URL 提取降级** — 仅从窗口标题提取域名，未实现完整 URL 获取（需浏览器扩展）

### 🟢 低优先级（改进建议）

1. 终端日志 ANSI 颜色可增强（当前用 HTML 着色）
2. 甘特图/热力图性能可优化（当前 QPainter 直接绘制，数据量大时可能卡顿）
3. ChatWindow 的 Thinker 连接为 `None` — 需在 Agent 线程中动态注入

---

## 下一步计划（归来后）

### Phase 1：打包验证 + 问题修复
- [ ] 运行 PyInstaller 打包，验证 exe 可独立运行
- [ ] 修复打包后可能缺失的依赖（qtawesome、.qss 文件等）
- [ ] 测试 exe 的三大 tab + 悬浮窗 + 托盘全部功能

### Phase 2：功能增强
- [ ] 浏览器 URL 完整获取（研究 Accessibility API 或浏览器扩展）
- [ ] winrt 通知监听配置向导（提供 GUI 引导用户授权）
- [ ] 健康数据接入（小米手环蓝牙/API 对接）

### Phase 3：云端智能
- [ ] 脱敏聚合数据 → DeepSeek 周趋势分析
- [ ] 情绪模式发现报告（聚类 + 自然语言描述）
- [ ] 云端建议本地执行（保护隐私前提下利用大模型）

---

## 运行方式

```bash
# 开发模式
cd agent_proto
py agent_ui.py

# 仅 Agent（无 UI）
py agent_loop.py

# 打包
py -m PyInstaller agent_proto.spec
```

---

*最后更新：2026-05-14 | 作者：Claude Code | 离队原因：长三角数模竞赛*
