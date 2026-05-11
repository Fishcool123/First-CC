# 认知增强系统 v3 自主性升级 — 执行规格书

> **目标：** 将任务助理和时间切片从「手动工具」升级为「半自主系统」
> **执行者：** Claude Code
> **规格书版本：** v1.0
> **预计工期：** 6-8 天（按阶段推进，每阶段独立可验收）

---

## 总览：5 个阶段

```
Phase 1（0.5天）  Bug 修复 + 自动重排 + 优先级衰减
      ↓
Phase 2（1.5天）  规则引擎（数据库 + 后端评估器 + 前端面板）
      ↓
Phase 3（2天）    精力曲线子系统（energy_profile + scheduler 升级）
      ↓
Phase 4（1.5天）  自动切片生成（设备日志 → 粗粒度切片）
      ↓
Phase 5（1天）    重复任务 + 快速切片弹窗 + 收尾
```

---

# Phase 1：基础修复与自主化（0.5天）

## 1.1 修复 monitor.py 聚合失效 ⚠️ 严重

**文件：** `monitor.py`

**问题：**
- 第65行 `strftime("%Y-%m-%d %H:%M:%S")` 包含秒，导致 `_device_log_buffer` 的 key 精确到秒，同一分钟内的采样永远无法命中已有 buffer，聚合完全失效。
- 第38行 buffer key 仅为字符串，但逻辑中依赖 `minute_key` 做分钟去重，存在歧义。

**修复步骤：**

### 步骤 A：修改 minute_key 格式（去掉秒）

找到第65行附近（在 `_record_device_sample` 方法中生成 `minute_key` 的位置），将：
```python
minute_key = now.strftime("%Y-%m-%d %H:%M:%S")
```
改为：
```python
minute_key = now.strftime("%Y-%m-%d %H:%M")
```

### 步骤 B：buffer 键改为复合键

将 `_device_log_buffer` 的键从纯 `minute_key` 改为 `(minute_key, process_name)` 元组。

找到 `_device_log_buffer` 初始化的位置（约第38行，`__init__` 或 `start` 方法），确认 dict 类型。然后在 `_record_device_sample` 中，将：
```python
if minute_key in self._device_log_buffer:
    self._device_log_buffer[minute_key]['duration'] += 10
```
改为：
```python
buffer_key = (minute_key, process_name)
if buffer_key in self._device_log_buffer:
    self._device_log_buffer[buffer_key]['duration'] += 10
```

相应地，所有访问 `_device_log_buffer` 的地方（包括 `_flush_buffer`）都改为使用 `buffer_key`。

### 步骤 C：分钟边界检测适配

在检测分钟边界的位置（约第68-77行，判断 `if last_minute and last_minute != minute_key`），改为遍历 buffer 的所有键，提取分钟部分进行比较。具体地：

```python
# 检查是否有前一个分钟的缓存需要 flush
keys_to_flush = []
for key in self._device_log_buffer:
    if key[0] != minute_key:  # key[0] 是 minute_key 部分
        keys_to_flush.append(key)
for key in keys_to_flush:
    # flush 单条记录
    # 从 buffer 中取出并写入 DB，然后 del
```

### 步骤 D：`_flush_buffer` 适配

`_flush_buffer` 方法需要修改为遍历所有 buffer 条目，提取 `minute_key` 和 `process_name`，调用 `self.db.add_device_log(minute_key, process, title, duration)`。

**验收标准：**
- 重启系统后，在 `device_usage_logs` 表中同一分钟同一进程只有一条记录
- `get_device_logs_aggregated` 查询返回正确的分钟级聚合数据
- 热力图数据密度合理（不再有大量 10 秒的微记录）

---

## 1.2 自动触发排程重算

**文件：** `app.py` + `static/js/tasks.js`

**改动：**

### 后端：无需改动（现有排程 API 已可用）

### 前端：在以下操作成功后自动调用 `this.loadSchedule()`

1. **添加任务后** — `add_task()` 的 `.then()` 回调中追加：
   ```javascript
   .then(() => this.loadSchedule())
   ```

2. **编辑任务后** — 同上

3. **删除任务后** — 同上

4. **修改可用时段后** — `saveTimeBlocks()` 成功后追加：
   ```javascript
   .then(() => {
       this.closeModal('timeBlocksModal');
       this.loadSchedule();
   })
   ```

### 前端 UI 调整（可选但推荐）

排程区域中，「重新排程」按钮保留但缩小为图标按钮（🔄），tooltip 写「手动强制重排」，因为正常情况下不再需要手动点击。

**验收标准：**
- 添加/编辑/删除任务后，排程区自动刷新
- 修改可用时段后，排程区自动刷新
- 「重新排程」按钮仍可用于手动强制重排

---

## 1.3 优先级动态衰减

**文件：** `scheduler.py` 的 `schedule_tasks` 函数（约第30-50行 `sort_key` 处）

**改动：**

在构建排序键之前，对每个任务动态计算有效优先级：

```python
from datetime import datetime, timedelta

def _effective_priority(task, now=None):
    """
    根据距截止时间动态调整优先级。
    - deadline < 2小时  → 强制 P0
    - deadline < 24小时 → 强制 P1
    - deadline < 3天    → 原优先级 +1（不超过 P0）
    - 否则保持原优先级
    """
    if now is None:
        now = datetime.now()
    
    base_priority = task.get('priority', 3)
    
    if not task.get('deadline'):
        return base_priority
    
    try:
        dl = datetime.fromisoformat(task['deadline'])
    except (ValueError, TypeError):
        return base_priority
    
    delta = dl - now
    
    if delta.total_seconds() < 0:
        return 0  # 已过期，强制 P0
    elif delta < timedelta(hours=2):
        return 0
    elif delta < timedelta(hours=24):
        return 1
    elif delta < timedelta(days=3):
        return max(0, base_priority - 1)  # 数字越小优先级越高，所以 -1
    else:
        return base_priority
```

然后在 `sort_key` 中使用 `_effective_priority(task)` 替代 `task.get('priority', 3)`。

**前端：** 在任务列表中，如果有效优先级与原始优先级不同，在优先级数字旁显示小箭头（↑ 表示被提升），tooltip 显示原因（如「距截止 3 小时，自动提升至 P0」）。

**验收标准：**
- 创建一个 deadline 为 1 小时后的 P3 任务 → 排程时应排在所有 P1/P2 任务之前
- deadline 已过期的任务自动变为 P0
- 无 deadline 的任务保持原优先级

---

# Phase 2：规则引擎（1.5天）

## 2.1 数据库迁移

**文件：** `database.py`

**新增表：**

```sql
CREATE TABLE IF NOT EXISTS rules (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    description TEXT DEFAULT '',
    trigger_type TEXT NOT NULL,
    trigger_params TEXT NOT NULL DEFAULT '{}',  -- JSON
    action_type TEXT NOT NULL,
    action_params TEXT NOT NULL DEFAULT '{}',   -- JSON
    enabled     INTEGER DEFAULT 1,
    is_preset   INTEGER DEFAULT 0,              -- 1=预设模板, 0=用户自定义
    created_at  TEXT DEFAULT (datetime('now','localtime')),
    updated_at  TEXT DEFAULT (datetime('now','localtime'))
);
```

**新增方法：**

```python
def get_rules(self, enabled_only=False):
    """获取所有规则"""
    pass

def toggle_rule(self, rule_id, enabled):
    """启用/禁用规则"""
    pass

def get_enabled_rules_by_trigger(self, trigger_type):
    """根据触发器类型获取启用的规则"""
    pass

def create_rule(self, name, trigger_type, trigger_params, action_type, action_params, is_preset=0):
    """创建规则"""
    pass

def update_rule(self, rule_id, **kwargs):
    """更新规则字段"""
    pass

def delete_rule(self, rule_id):
    """删除规则（预设规则不可删除，只能禁用）"""
    pass
```

**预设规则种子数据：** 在 `init_db()` 中插入 8 条预设规则：

| id | name | trigger_type | trigger_params | action_type | action_params |
|----|------|-------------|----------------|-------------|---------------|
| 1 | 长时间未记录切片提醒 | slice_gap | {"hours": 4} | notify | {"title":"该切一片了","message":"你已经{hours}小时没记录切片了"} |
| 2 | 设备连续使用超时提醒 | device_usage_duration | {"process":"*","minutes":90} | notify | {"title":"休息提醒","message":"你已连续使用{process}{minutes}分钟"} |
| 3 | 每日屏幕时间超限 | device_usage_daily | {"hours":8} | notify | {"title":"屏幕时间提醒","message":"今日屏幕使用已超过{hours}小时"} |
| 4 | 任务即将截止提醒 | task_deadline_approaching | {"hours":1} | notify | {"title":"任务即将截止","message":"「{task_name}」将在{time}后截止"} |
| 5 | 任务多日未推进提醒 | task_stale | {"days":3} | notify | {"title":"任务提醒","message":"「{task_name}」已经{days}天没有推进了"} |
| 6 | 连续低精力提醒 | energy_drop | {"count":2,"threshold":2} | notify | {"title":"精力提醒","message":"你已连续{count}次标记低精力，建议休息"} |
| 7 | 焦虑情绪上升提醒 | slice_mood_spike | {"tag":"焦虑","count":3,"days":7} | prompt_slice | {"title":"情绪关怀","message":"最近{days}天内你标记了{count}次焦虑，要聊聊吗？"} |
| 8 | 排程冲突检测 | schedule_conflict | {} | notify | {"title":"排程冲突","message":"同一时段手动分配已覆盖自动排程"} |

---

## 2.2 规则评估器

**新建文件：** `rule_engine.py`

**核心类：**

```python
class RuleEngine:
    def __init__(self, db):
        self.db = db
    
    def evaluate(self, trigger_type, context):
        """
        触发规则评估。
        - trigger_type: 触发器类型字符串
        - context: 触发上下文 dict，如 {'process':'Chrome', 'duration_minutes':95}
        
        遍历该类型所有启用的规则，匹配条件后执行动作。
        """
        rules = self.db.get_enabled_rules_by_trigger(trigger_type)
        for rule in rules:
            if self._match(rule['trigger_params'], context):
                self._execute(rule['action_type'], rule['action_params'], context)
    
    def _match(self, trigger_params, context):
        """条件匹配逻辑"""
        # 解析 trigger_params JSON
        # 对每个参数做比较：等于、大于、包含等
        pass
    
    def _execute(self, action_type, action_params, context):
        """执行动作"""
        if action_type == 'notify':
            self._action_notify(action_params, context)
        elif action_type == 'prompt_slice':
            self._action_prompt_slice(action_params, context)
        elif action_type == 'log':
            self._action_log(action_params, context)
        # 预留: 'chat'（对接 LLM）、'reschedule'
    
    def _action_notify(self, params, context):
        """发送桌面通知，使用 plyer"""
        # 对 message 模板做变量替换：{hours} → context['hours']
        pass
    
    def _action_prompt_slice(self, params, context):
        """触发前端弹窗（通过 SSE 或轮询标记）"""
        # 在系统状态中设置 flag，前端定时轮询检测
        pass
```

**挂载点：** 在 `app.py` 启动时初始化 `RuleEngine` 实例，注入到以下位置：

1. **`monitor.py`** — 在 `_flush_buffer` 写入设备日志后：
   ```python
   rule_engine.evaluate('device_usage_duration', {
       'process': process_name,
       'duration_minutes': duration // 60,
       'window_title': window_title
   })
   ```

2. **`app.py`** — 在 `add_slice()` 路由中，切片写入成功后：
   ```python
   rule_engine.evaluate('slice_mood_spike', {
       'tag': mood_tag,
       'recent_count': recent_anxiety_count  # 需查询
   })
   rule_engine.evaluate('energy_drop', {
       'energy_level': energy_level,
       'consecutive_low': consecutive_low_count  # 需查询
   })
   ```

3. **定时轮询（app.py 中新增）：**
   ```python
   def start_rule_timer():
       """每 15 分钟检查 slice_gap / task_stale 等定时触发器"""
       # 使用 threading.Timer 递归调度
       rule_engine.evaluate('slice_gap', {...})
       rule_engine.evaluate('task_stale', {...})
       rule_engine.evaluate('task_deadline_approaching', {...})
       rule_engine.evaluate('device_usage_daily', {...})
       # 15 分钟后再次调度
       threading.Timer(900, start_rule_timer).start()
   ```

---

## 2.3 规则引擎前端面板

**文件：** `templates/index.html` + `static/js/app.js`

**UI 位置：** 在现有「设置」标签页内新增子导航或分区「⚙️ 自动化规则」

**UI 结构：**

```
┌─────────────────────────────────────────┐
│ ⚙️ 自动化规则                            │
│                                         │
│ ┌─ 预设规则 ──────────────────────────┐  │
│ │ [✓] 长时间未记录切片提醒 (4小时)    │  │
│ │ [✓] 设备连续使用超时提醒 (90分钟)   │  │
│ │ [ ] 每日屏幕时间超限 (8小时)        │  │
│ │ [✓] 任务即将截止提醒 (1小时)        │  │
│ │ [ ] 任务多日未推进提醒 (3天)        │  │
│ │ [✓] 连续低精力提醒                 │  │
│ │ [ ] 焦虑情绪上升提醒               │  │
│ │ [✓] 排程冲突检测                   │  │
│ └────────────────────────────────────┘  │
│                                         │
│ 每个规则行：                             │
│  [开关] 规则名称  简短描述  参数值        │
│                                         │
└─────────────────────────────────────────┘
```

**交互：**
- 开关切换 → `POST /api/rules/<id>/toggle` → 即时生效
- 点击规则名 → 展开查看完整描述和参数（但首版不可编辑参数，仅开关）

**前端数据流：**
```javascript
// app.js 新增 mixin 方法
loadRules()      // GET /api/rules
toggleRule(id)   // POST /api/rules/<id>/toggle
```

**API 新增：**

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/rules` | 获取所有规则（含启用状态） |
| POST | `/api/rules/<id>/toggle` | 切换启用/禁用 |
| POST | `/api/rules/evaluate` | 手动触发一次规则评估（调试用） |

**验收标准：**
- 设置页能看到 8 条预设规则，默认全部启用
- 关闭某条规则后，对应触发器不再执行（如关闭「屏幕时间超限」，连续用 10 小时也不弹通知）
- 后续 Phase 4 自动切片生成时，规则引擎已就绪可挂载

---

# Phase 3：精力曲线子系统（2天）

## 3.1 数据库 migration

**文件：** `database.py`

**新增表：**

```sql
CREATE TABLE IF NOT EXISTS energy_profile (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    period          TEXT NOT NULL,        -- 'morning' / 'afternoon' / 'evening'
    avg_energy      REAL,                -- 平均精力值 (1.0~5.0)
    sample_count    INTEGER DEFAULT 0,
    updated_at      TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(period)
);
```

**新增方法：**

```python
def get_energy_profile(self):
    """返回三个时段的精力画像，如：
    [
        {'period':'morning', 'avg_energy':4.2, 'sample_count':23},
        {'period':'afternoon', 'avg_energy':2.8, 'sample_count':20},
        {'period':'evening', 'avg_energy':3.1, 'sample_count':18}
    ]
    若 sample_count == 0，返回 avg_energy: null
    """
    pass

def refresh_energy_profile(self, days=30):
    """
    根据 slices 表中最近 N 天的数据重新计算精力画像。
    - 只计算 granularity != 'auto' 的切片（手动记录才含情绪/精力）
    - 按 timestamp 的小时数划分时段：
        morning:   5:00 - 11:59
        afternoon: 12:00 - 17:59
        evening:   18:00 - 4:59
    - 对每个时段计算 AVG(energy_level)，写入 energy_profile 表
    """
    pass
```

---

## 3.2 调度器精力匹配升级

**文件：** `scheduler.py`

**改动：** 在 `schedule_tasks` 函数中，在贪心填充之前增加精力匹配步骤。

**新算法流程：**

```
输入：tasks（任务列表），time_blocks（可用时段），energy_profile（精力画像）

1. 任务按有效优先级排序（Phase 1.3 的 _effective_priority）
2. 时段按精力值排序：
   - 高精力时段（avg_energy ≥ 3.5 或 无数据） → 排 P0/P1 任务
   - 低精力时段（avg_energy < 2.5）→ 排 P3/P4 简单任务
3. 在每个时段内用贪心填充：
   - 遍历时段内的空闲间隙
   - 尝试填入最合适的任务
4. 未排上的任务放入「待安排」池

精力数据不足时（总 sample_count < 7）→ 降级为传统贪心
```

**代码结构：**

```python
def schedule_tasks(tasks, blocks, energy_profile=None):
    # 1. 排序
    sorted_tasks = sorted(tasks, key=_effective_priority)
    
    # 2. 时段分类
    high_energy_blocks = []
    low_energy_blocks = []
    normal_blocks = []
    
    if energy_profile and total_samples(energy_profile) >= 7:
        for block in blocks:
            period = get_period_for_block(block)  # morning/afternoon/evening
            avg = get_avg_energy(energy_profile, period)
            if avg and avg >= 3.5:
                high_energy_blocks.append(block)
            elif avg and avg < 2.5:
                low_energy_blocks.append(block)
            else:
                normal_blocks.append(block)
    else:
        normal_blocks = blocks  # 降级
    
    # 3. 精力匹配分配
    # P0/P1 → 优先高精力时段
    # P3/P4 → 可分配到低精力时段
    # ...
    
    # 4. 贪心填充（同现有逻辑）
    # ...
```

**验收标准：**
- 精力数据充足（≥7天）时，高优先级任务优先排在精力高峰时段
- 精力数据不足时，降级为传统贪心，不报错
- 精力画像可手动刷新（`POST /api/slices/energy-profile/refresh`）
- 精力画像不阻塞正常排程

---

## 3.3 精力曲线 API

**文件：** `app.py`

**新增路由：**

```python
@app.route('/api/slices/energy-profile', methods=['GET'])
def get_energy_profile():
    """返回精力画像 + 最近 N 天的精力变化趋势"""
    profile = db.get_energy_profile()
    # 额外返回趋势数据：每天各时段的精力平均值
    trend = db.get_energy_trend(days=14)  # [{'date':'2025-12-01','morning':4.0,'afternoon':2.5,...}]
    return jsonify({'profile': profile, 'trend': trend})

@app.route('/api/slices/energy-profile/refresh', methods=['POST'])
def refresh_energy_profile():
    """强制重算精力画像"""
    db.refresh_energy_profile()
    return jsonify({'status': 'ok'})
```

**前端可视化（在 slices.js 中）：**

在切片页面底部（热力图下方）增加一个「精力趋势」区块：
- 14 天折线图（Chart.js 或纯 SVG 简单版）
- 三条线：上午（橙）、下午（蓝）、晚上（紫）
- 若 Chart.js 引入太重，首版可用 CSS bar chart 替代

**验收标准：**
- API 返回精力画像和 14 天趋势
- 前端至少显示简单的柱状图或折线图
- 无数据时显示「精力数据不足，请多记录几天切片」

---

# Phase 4：自动切片生成（1.5天）

## 4.1 设计方案：每半天聚合（方案B）

**触发时机：**
1. 每天 **23:55** 自动触发（Flask 后台定时器）
2. 当天首次启动系统时，检测昨日是否已生成 → 若未，补生成
3. 手动触发：设置页「立即生成昨日切片」按钮

**生成逻辑：**

```python
# auto_slice_generator.py（新建）

def generate_auto_slices(target_date, db):
    """
    根据 device_usage_logs 为指定日期生成自动切片。
    target_date: datetime.date 对象（目标日期）
    
    生成规则：
    1. 查询 target_date 当天所有 device_usage_logs
    2. 按时段分组：morning(5-11:59) / afternoon(12-17:59) / evening(18-4:59)
    3. 每个时段内按进程聚合 duration_seconds
    4. 过滤：单进程总时长 < 5 分钟的忽略
    5. 对每个 (时段, 进程) 生成一条切片：
       - timestamp: target_date + 时段代表性时间（如 morning→08:00）
       - activity_desc: "{进程名} ({时长分钟}分钟)"  如 "Chrome (85分钟)"
       - mood_tags: []   (自动切片无情绪标签)
       - energy_level: null
       - granularity: "auto"
       - content: "{进程名} - {时段} - 自动记录"
    6. 批量写入 slices 表
    7. 标记生成状态（在 device_usage_logs 表或新建 meta 表记录上次生成日期）
    """
    
    # 先删除该日期的旧自动切片（幂等性——重复生成时覆盖而非重复）
    db.delete_auto_slices_for_date(target_date)
    
    logs = db.get_device_logs_by_date(target_date)
    
    # 分组聚合
    groups = {}
    for log in logs:
        period = get_period_for_hour(log['log_time'].hour)
        key = (period, log['process'])
        if key not in groups:
            groups[key] = 0
        groups[key] += log['duration']
    
    # 过滤 < 5min 的
    groups = {k: v for k, v in groups.items() if v >= 300}
    
    # 写入
    for (period, process), total_seconds in groups.items():
        minutes = total_seconds // 60
        timestamp = f"{target_date.isoformat()} {PERIOD_TIMES[period]}"
        db.add_slice({
            'timestamp': timestamp,
            'activity_desc': f"{process} ({minutes}分钟)",
            'mood_tags': [],
            'energy_level': None,
            'granularity': 'auto',
            'content': f"{process} - {period} - 自动记录"
        })
```

**时段划分（与精力曲线一致）：**

```python
PERIOD_MAP = {
    'morning':   (5, 11),    # 5:00 - 11:59
    'afternoon': (12, 17),   # 12:00 - 17:59
    'evening':   (18, 4),    # 18:00 - 4:59 (跨夜)
}
PERIOD_TIMES = {
    'morning':   '08:00:00',
    'afternoon': '14:00:00',
    'evening':   '20:00:00',
}
```

**定时器挂载（app.py）：**

```python
def start_auto_slice_timer():
    """每天 23:55 自动生成当日切片"""
    now = datetime.now()
    target = now.replace(hour=23, minute=55, second=0, microsecond=0)
    if target < now:
        target += timedelta(days=1)
    delay = (target - now).total_seconds()
    threading.Timer(delay, _auto_slice_and_reschedule).start()

def _auto_slice_and_reschedule():
    from auto_slice_generator import generate_auto_slices
    generate_auto_slices(datetime.now().date(), db)
    # 24h 后再次调度
    threading.Timer(86400, _auto_slice_and_reschedule).start()
```

**首次启动补生成：**

在 `app.py` 的启动逻辑中（`if __name__ == '__main__'` 附近）：
```python
# 检测昨日是否已生成自动切片
yesterday = (datetime.now() - timedelta(days=1)).date()
existing = db.get_auto_slices_count_for_date(yesterday)
if existing == 0:
    generate_auto_slices(yesterday, db)
```

---

## 4.2 自动切片标记与过滤

**slices 表需要新增字段（若尚未存在）：**

```sql
ALTER TABLE slices ADD COLUMN granularity TEXT DEFAULT 'manual';
-- 'manual' = 手动录入, 'coarse' = 粗粒度标注, 'auto' = 自动生成
```

若 ALTER TABLE 不方便（SQLite 限制），可以在 database.py init 时确保建表语句包含此字段。

**前端过滤：**

在切片列表视图中，自动切片显示时：
- 活动描述前加 🤖 图标
- 不可编辑情绪标签（灰化）
- 可手动删除

**验收标准：**
- 每天 23:55 自动生成当日切片（无弹窗、静默）
- 第二天首次打开系统，切片列表中出现自动生成的条目（带 🤖 标记）
- 自动切片与手动切片在同一列表中按时间排序
- 手动删除某条自动切片后，重新生成不会复活（幂等：先生成新再删旧）

---

# Phase 5：重复任务 + 快速切片弹窗（1天）

## 5.1 重复任务

**数据库改动（tasks 表）：**

```sql
ALTER TABLE tasks ADD COLUMN recurrence TEXT DEFAULT 'none';
-- 'none' / 'daily' / 'weekly' / 'weekday'（仅工作日）
ALTER TABLE tasks ADD COLUMN last_generated_date TEXT;
-- 上次自动生成实例的日期，防止同一天重复生成
```

**每日 00:05 自动生成逻辑（app.py 定时器）：**

```python
def generate_recurring_tasks():
    """每日凌晨检查重复任务，生成今日实例"""
    today = datetime.now().date().isoformat()
    recurring_tasks = db.get_tasks_by_recurrence(['daily', 'weekly', 'weekday'])
    
    for task in recurring_tasks:
        # 检查今天是否已生成
        if task['last_generated_date'] == today:
            continue
        
        # 工作日检查
        if task['recurrence'] == 'weekday' and datetime.now().weekday() >= 5:
            continue
        
        # 周任务检查（仅周一生成）
        if task['recurrence'] == 'weekly' and datetime.now().weekday() != 0:
            continue
        
        # 生成今日实例（复制任务，清除 id，设置 today 日期）
        new_task = task.copy()
        new_task['id'] = None
        new_task['created_at'] = today
        new_task['recurrence'] = 'none'  # 生成的是单次任务
        new_task['parent_recurring_id'] = task['id']  # 追溯源头
        db.add_task(new_task)
        
        # 更新原任务的 last_generated_date
        db.update_task(task['id'], {'last_generated_date': today})
```

**前端：**

在任务编辑模态框中，新增「重复」下拉框：不重复 / 每天 / 每周 / 工作日。

**验收标准：**
- 创建一个每日重复任务，第二天自动出现在任务列表中
- 同一天不会重复生成
- 删除生成的实例不影响原重复任务
- 禁用/删除原重复任务后不再生成

---

## 5.2 快速切片弹窗

**文件：** `desktop.py` + `app.py` + 新增迷你前端页面

**系统托盘右键菜单新增：**「⚡ 快速记录」

点击后触发：
1. `desktop.py` 调用 `app.py` 的 API 获取当前弹窗触发标记
2. 或者更简单：打开一个超轻量 HTML 弹窗（`templates/quick-slice.html`）

**`quick-slice.html` 设计：**

```
┌──────────────────────┐
│ ⚡ 快速记录          │
│                      │
│ 情绪：                │
│ [😊] [😐] [😟] [😡] [😴]│
│                      │
│ 精力：                │
│ [●] [●●] [●●●] [●●●●] [●●●●●]│
│                      │
│ 备注（可选）：        │
│ [______________]     │
│                      │
│ [记录]  (Enter 提交) │
└──────────────────────┘
```

- 窗口大小：350×280px
- 无标题栏（frameless）
- Enter 键提交自动关闭
- 3 秒内完成记录

**API：**

```python
@app.route('/api/slices/quick', methods=['POST'])
def quick_slice():
    """快速切片录入"""
    data = request.json
    # mood: '😊'→'愉快', '😐'→'平静', '😟'→'焦虑', '😡'→'愤怒', '😴'→'疲惫'
    # energy: 1-5
    # note: 可选
    db.add_slice({
        'timestamp': datetime.now().isoformat(),
        'activity_desc': '快速记录',
        'mood_tags': [MOOD_MAP[data['mood']]],
        'energy_level': data['energy'],
        'granularity': 'manual',
        'content': data.get('note', '')
    })
    return jsonify({'status': 'ok'})
```

**验收标准：**
- 系统托盘右键 → 快速记录 → 3 秒完成一次切片
- 记录后自动关闭弹窗
- 主窗口切片列表同步更新（轮询或 SSE）

---

# 附录：文件改动总览

| 文件 | Phase | 改动类型 |
|------|-------|----------|
| `monitor.py` | P1 | 🔧 修复聚合 bug |
| `app.py` | P1-P5 | ➕ 多个新增路由 + 定时器 |
| `database.py` | P2/P3/P4/P5 | ➕ 新表 + 新方法 + migration |
| `scheduler.py` | P1/P3 | 🔧 优先级衰减 + ➕ 精力匹配 |
| `rule_engine.py` | P2 | 🆕 新建文件 |
| `auto_slice_generator.py` | P4 | 🆕 新建文件 |
| `desktop.py` | P5 | 🔧 托盘菜单新增项 |
| `templates/index.html` | P2/P3/P5 | ➕ 规则面板 + 精力图表 + 重复任务UI |
| `static/js/app.js` | P2/P3 | ➕ 规则管理 + 精力趋势 |
| `static/js/tasks.js` | P1/P5 | 🔧 自动重排 + 重复任务 |
| `static/js/slices.js` | P3/P4 | ➕ 精力趋势 + 自动切片展示 |
| `static/css/style.css` | P3/P5 | ➕ 精力图表样式 + 规则面板样式 |
| `templates/quick-slice.html` | P5 | 🆕 新建文件 |

---

# 验收总览

| 自主性维度 | Phase 1 | Phase 2-5 | 目标状态 |
|-----------|---------|-----------|----------|
| 排程触发 | 手动 → 自动 | — | **自动** |
| 优先级管理 | 静态 → 动态衰减 | — | **自适应** |
| 设备数据 | 只记录不分析 | 自动生成切片 + 触发规则 | **闭环** |
| 精力感知 | 无 | 精力画像 + 排程匹配 | **数据驱动** |
| 用户配置 | 改代码 | 规则面板开关 | **可视化配置** |
| 重复任务 | 手动添加 | 自动生成实例 | **零操作** |
| 切片录入 | 打开主窗口 | 托盘快速记录 | **3秒完成** |

---

> **⚠️ 给 Claude Code 的执行提示：**
> 1. 严格按 Phase 顺序执行，每个 Phase 完成后确认可运行再进下一个
> 2. 数据库 migration 使用 `ALTER TABLE ADD COLUMN IF NOT EXISTS` 模式（SQLite 需要 try/except）
> 3. 所有新增路由需在 `app.py` 中注册，所有新增 Python 文件需确保 import 路径正确
> 4. 前端新增的 API 调用使用与现有代码一致的 fetch 模式（见 `static/js/app.js` 现有示例）
> 5. 规则引擎评估器需注意线程安全（monitor.py 在独立线程运行）
> 6. 精力曲线计算首次运行时可能无数据，必须优雅降级
