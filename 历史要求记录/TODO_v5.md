# TODO_v5：直接可用前的 5 项修复

> 同一对话继续，不要新开。按 1→5 顺序执行。

---

## 1. 补 `today_mood_summary` 字段

**文件**：`agent_memory.py`

**问题**：`enrich_context()` 没有填充 `{today_mood_summary}`，导致 companion persona 情绪感知能力为零。

**修复**：

1. 在 `agent_memory.py` 末尾新增函数：

```python
def get_today_mood_summary() -> str:
    """
    查询 slices.db 的 slices 表，统计今日 mood_tags。
    返回格式：'记录3次：焦虑、平静、开心'
    无记录时返回：'今日暂无情绪记录'
    """
    conn = _connect_slices_db()
    if not conn:
        return "（数据库不可用）"
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        cursor = conn.execute(
            "SELECT mood_tags FROM slices WHERE date(timestamp) = ? AND mood_tags IS NOT NULL AND mood_tags != ''",
            (today,)
        )
        rows = cursor.fetchall()
        if not rows:
            return "今日暂无情绪记录"
        tags = []
        for row in rows:
            tags.extend([t.strip() for t in row[0].split(",") if t.strip()])
        summary = f"记录{len(tags)}次：{'、'.join(tags[:10])}"
        if len(tags) > 10:
            summary += f"等{len(tags)}个标签"
        return summary
    except Exception as e:
        return f"（查询情绪数据失败：{e}）"
    finally:
        conn.close()
```

2. 在 `enrich_context()` 中添加调用：

```python
context["today_mood_summary"] = get_today_mood_summary()
```

3. 在文件顶部导入（如果还没有）：无需新增导入，`datetime` 已在标准库。

**验证**：运行后查看 proto_log，companion 触发时的上下文应包含 `today_mood_summary: "今日暂无情绪记录"`。

---

## 2. 补 `get_pending_tasks()` 函数

**文件**：`agent_memory.py`

**问题**：scheduler persona 需要读取 v2 的任务数据，但 agent_memory 没有待办任务查询函数。

**修复**：

在 `agent_memory.py` 末尾新增：

```python
def get_pending_tasks() -> list[dict]:
    """
    读取 task_assistant.db 的 tasks 表，返回待办任务列表。
    返回格式：[{"title": "写论文", "deadline": "2025-03-15", "priority": "高"}, ...]
    无任务时返回空列表。
    """
    conn = _connect_task_db()
    if not conn:
        return []
    try:
        cursor = conn.execute(
            "SELECT title, deadline, priority FROM tasks WHERE status = 'pending' ORDER BY priority DESC, deadline ASC LIMIT 10"
        )
        rows = cursor.fetchall()
        tasks = []
        for row in rows:
            tasks.append({
                "title": row[0] or "（无标题）",
                "deadline": row[1] or "无截止日期",
                "priority": row[2] or "普通"
            })
        return tasks
    except Exception as e:
        logger.warning(f"查询待办任务失败: {e}")
        return []
    finally:
        conn.close()
```

在 `enrich_context()` 中添加：

```python
context["pending_tasks"] = get_pending_tasks()
```

让 scheduler 人格卡的 `{pending_tasks}` 变量有数据可读。

**验证**：如果在 v2 中加了待办任务，scheduler 触发时上下文里应出现任务列表。

---

## 3. 模式自动切换

**文件**：`agent_loop.py` 或 `agent_ui.py`

**问题**：三种存在密度只能手动切。检测到 IDE 活跃应自动切换休眠态，离开 IDE 自动切回陪伴态。

**规则定义**：

| 检测条件 | 动作 |
|---------|------|
| 活跃窗口标题包含 `Cursor`/`VS Code`/`Visual Studio`/`PyCharm`/`IntelliJ`/`Android Studio`/`Eclipse` 且连续 **5 分钟** | → 自动切换休眠态 |
| 从 IDE 窗口切换到非 IDE 窗口 | → 立即切回陪伴态 |
| 用户手动锁定了模式（通过托盘/悬浮窗） | → 不自动切换，尊重锁定 |

**实现要点**：

1. 在 Observer 中新增 `ide_active_start_time` 时间戳变量
2. 每次窗口切换事件检查是否为 IDE：
   - 是 IDE → 记录开始时间，5 分钟后调用 `ui.switch_mode("sleep")`
   - 不是 IDE → 取消计时，如果当前是自动休眠 → `ui.switch_mode("companion")`
3. 在 `agent_ui.py` 的 `switch_mode()` 中加入自动模式标记，手动切换时设置 `_auto_mode = False`

**IDE 识别关键词列表**（窗口标题 starts_with 或 contains）：
```
ide_keywords = ["Cursor", "VS Code", "Visual Studio Code", "PyCharm", 
                "IntelliJ IDEA", "Android Studio", "Eclipse", "Sublime Text",
                "Vim", "Neovim", "Code", "JetBrains"]
```

**验证**：打开 Cursor 5 分钟 → 悬浮窗自动缩小到托盘或消失 → 切回浏览器 → 悬浮窗自动出现。

---

## 4. 凌晨 0-6 点默认静默

**文件**：`agent_loop.py` 的 Thinker 判断逻辑

**问题**：Agent 在深夜也可能主动说话，打扰睡眠。

**规则**：
- 凌晨 00:00–06:00 → 默认 L0（静默观察，不说话）
- 例外：L4 紧急介入（危机检测）仍可触发
- 例外：用户主动点击悬浮窗/发送消息 → 正常回复

**实现**：

在 `agent_loop.py` 主循环的 Thinker 调用前添加：

```python
hour = datetime.now().hour
if 0 <= hour < 6:
    # 凌晨静默，只观察不主动说话
    # 但保留用户手动触发的对话通道
    if not user_initiated:
        continue  # 跳过本轮 Thinker → Actor
```

或者在 `should_speak()` 判断中增加时段检查。

**验证**：系统时间若在凌晨 0-6 点，Agent 不产生任何主动消息。

---

## 5. 悬浮窗右键菜单

**文件**：`agent_ui.py`

**问题**：悬浮窗右键无反应，用户只能通过托盘菜单切换模式。

**修复**：

在 `FloatingDot` 类中添加：

```python
def contextMenuEvent(self, event):
    """右键菜单"""
    menu = QtWidgets.QMenu()
    
    mode_menu = menu.addMenu("切换模式")
    sleep_action = mode_menu.addAction("💤 休眠态")
    companion_action = mode_menu.addAction("🌙 陪伴态")
    chat_action = mode_menu.addAction("💬 对话态")
    
    menu.addSeparator()
    lock_action = menu.addAction("🔒 锁定当前模式" if not self._mode_locked else "🔓 解锁模式")
    menu.addSeparator()
    exit_action = menu.addAction("❌ 退出")
    
    action = menu.exec_(event.globalPos())
    
    if action == sleep_action:
        self.switch_mode("sleep")
    elif action == companion_action:
        self.switch_mode("companion")
    elif action == chat_action:
        self.switch_mode("chat")
    elif action == lock_action:
        self._mode_locked = not self._mode_locked
    elif action == exit_action:
        self._app.quit()
```

需要导入 `QtWidgets`（已导入则跳过）。

**验证**：右键悬浮窗圆点 → 弹出菜单 → 点击「休眠态」→ 悬浮窗消失/最小化 → 点击「陪伴态」→ 恢复。

---

## 执行顺序

```
1. today_mood_summary      ← 解锁 companion 情绪感知
2. get_pending_tasks()     ← 解锁 scheduler 数据源
3. 模式自动切换            ← «智能体感» 核心体验
4. 凌晨静默                ← 防打扰
5. 悬浮窗右键菜单          ← 操作便捷性
```

---

## 验证清单

全部修复后，执行以下验证：

- [ ] 在 v2 写几条带情绪标签的切片 → 晚间触发 companion → 日志中出现 today_mood_summary 不为空
- [ ] 在 v2 加 3 个待办 → 上午心跳 → scheduler 触发 → 日志中出现任务提醒
- [ ] 打开 Cursor 5 分钟 → Agent 自动休眠 → 切回浏览器 → Agent 自动恢复
- [ ] 凌晨 1 点 → Agent 不主动说任何话
- [ ] 右键悬浮窗 → 菜单正常弹出 → 各选项可用
- [ ] 跑一次 30 分钟新会话 → proto_log 中冷却期正常、消息间隔 > 2 分钟
