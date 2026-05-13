# Phase 5 收尾 — Claude Code 执行指令

## 项目背景

- 路径：`C:\Users\www15\Desktop\First CC\认知增强系统`
- 当前状态：Phase 1-4 已完成（bug修复、规则引擎、精力曲线、自动切片）
- 技术栈：Python/Flask + Vue 3 CDN + SQLite + pywin32 + Edge WebView
- 原则：简洁实现，不过度工程化

---

## 任务一：任务拆分建议

**做什么：** 预估 > 90 分钟且排程时找不到连续空闲时段的任务，前端自动标记「建议拆分」，用户可一键拆为 N 份子任务。

**后端：**

1. `database.py` — tasks 表新增字段：
```sql
ALTER TABLE tasks ADD COLUMN parent_id INTEGER DEFAULT NULL;
ALTER TABLE tasks ADD COLUMN split_total INTEGER DEFAULT NULL;
```

2. `database.py` — 新增方法：
   - `split_task(task_id, num_parts)` → 创建 N 个子任务（继承标题/优先级/deadline，标题后缀 `(1/N)`），父任务标记 split_total=N
   - `unsplit_task(task_id)` → 删除所有子任务，父任务恢复正常

3. `scheduler.py` — 新增 `find_oversized_tasks(tasks, available_slots)` → 找出无连续空闲装下的大任务，返回建议拆分份数

4. `app.py` — 新增两个路由：
   - `POST /api/tasks/<id>/split` (body: `{num_parts: 2}`)
   - `POST /api/tasks/<id>/unsplit`
   - 排程 API 返回新增字段 `oversized_tasks: []`

**前端：**

1. 任务卡片：检测 oversized_tasks，显示 🧩建议拆分 徽标（橙色圆角标签）
2. 点徽标弹出 Modal：快捷按钮「拆为2份」「拆为3份」+ 自定义份数（2-6）
3. 确认后调 split API，自动刷新任务列表和排程
4. 子任务显示标题后缀 `(1/3)`，父任务变为折叠进度条 `2/3 完成`
5. 所有子任务完成后父任务自动标记完成

---

## 任务二：前端工程化迁移（CDN → Vite）

**做什么：** 将 CDN 引入的 Vue 3 迁移到 Vite + SFC + Pinia。新旧并行（`/` 旧版，`/v2` 新版），功能完全对齐后再切换。

**新建前端项目：**

1. 在项目根目录创建 `frontend/` 目录结构：
```
frontend/
├── index.html
├── package.json
├── vite.config.js
├── .env.development      # VITE_API_BASE=http://127.0.0.1:5007
├── src/
│   ├── main.js
│   ├── App.vue            # 三标签页容器（任务/切片/设置）
│   ├── api/index.js       # axios 封装
│   ├── stores/
│   │   ├── tasks.js       # Pinia
│   │   └── slices.js
│   ├── assets/style.css   # 从 static/css/style.css 完整复制
│   └── components/
│       ├── TaskPanel.vue
│       ├── SlicePanel.vue
│       ├── SettingsPanel.vue
│       ├── TaskCard.vue
│       ├── SliceCard.vue
│       ├── HeatmapCalendar.vue
│       ├── EnergyChart.vue      # Chart.js
│       ├── RulePanel.vue
│       ├── QuickSliceModal.vue
│       ├── SplitModal.vue       # 任务一拆分弹窗
│       └── WeeklyGantt.vue      # 任务三甘特图
```

2. **依赖：** `vue@^3.4 pinia axios sortablejs chart.js frappe-gantt`
   **开发依赖：** `vite @vitejs/plugin-vue`

3. **vite.config.js：** base: `/v2/`，dev proxy `/api` → `127.0.0.1:5007`

4. **迁移策略：** 逐个组件迁移，Pinia 替代全局 Mixin。先小后大（SettingsPanel → TaskPanel → SlicePanel），每完成一个验证功能对齐。

**Flask 适配：**
```python
@app.route('/v2')
@app.route('/v2/<path:filename>')
# → send_from_directory('frontend/dist', ...)
```

**构建：** 新增 `build_frontend.bat`：`cd frontend && npm run build && xcopy dist\* ..\static\v2\`

---

## 任务三：桌面悬浮窗（周视图 + 甘特图）

**做什么：** 独立悬浮窗 420×680，置顶，托盘右键打开，显示本周甘特图 + 精力提示。纯展示，不交互编辑。

**后端：**

1. `app.py` — 新增 `GET /api/tasks/weekly-view?date=YYYY-MM-DD`：
   - 返回本周所有已排程任务（转为 gantt_bars 格式）
   - 空闲时段标记为灰色条
   - energy_tips：精力画像中 avg < 2.5 的时段生成提示
   - stats：本周任务总数/已完成/日均专注小时

2. `app.py` — 新增 `PUT /api/system/config`，接受 `{weekly_win_x, weekly_win_y}` 持久化悬浮窗位置

**桌面端（desktop.py）：**

1. 新增 `open_weekly_view()`：启动 Edge `--app` 窗口，`--window-size=420,680 --window-position=x,y`，置顶，加载 `/v2/weekly`
2. 托盘菜单在「显示主窗口」和「快速记录」之间插入「📅 周视图悬浮窗」
3. 窗口关闭时 JS 发送位置到 `PUT /api/system/config`
4. 主窗口退出时一同关闭悬浮窗

**前端：**

1. `WeeklyGantt.vue`：加载 `/api/tasks/weekly-view`，用 Frappe Gantt 渲染周视图甘特图
   - 禁用拖拽/编辑交互
   - 不同优先级不同颜色条
   - 底部显示统计卡片 + 精力提示
2. 通过 URL hash `#weekly` 激活该页面（不引入 Vue Router）

---

## 执行顺序

```
任务一（1天）→ 任务二（2天）→ 任务三（1天）
```

## 关键约束

- 迁移期间旧前端不能断（`/` 保持可用）
- 所有新功能在新前端（`/v2`）中实现
- 不引入 TypeScript、linting、测试框架
- 不引入 Vue Router（用 activeTab 状态 + URL hash 足够）
- Frappe Gantt 用 npm 包，不用 CDN
