/* slices.js — 切片系统模块 Vue Mixin：切片录入、热力图、设备日志 */
/* 与 tasks.js 合并到 app.js 主应用 */

const slicesMixin = {
    data() {
        const now = new Date();
        const local = new Date(now.getTime() - now.getTimezoneOffset() * 60000)
            .toISOString().slice(0, 16);
        return {
            /* 新增切片表单 */
            sliceForm: {
                timestamp: local,
                activity_desc: "",
                mood_tags: [],
                mood_intensity: 3,
                energy_level: 3,
                related_task_id: null,
                notes: "",
            },

            /* 数据 */
            slices: [],
            deviceLogs: [],
            deviceSummary: [],
            heatmapData: [],
            moodTags: [],
            assistantTasks: [],

            /* UI 状态 */
            viewDate: new Date().toISOString().slice(0, 10),
            showDeviceLogs: false,
            heatmapMonth: 0,
            heatmapOffset: 0,

            /* 切片编辑弹窗（第三阶段 #9） */
            showEditSliceModal: false,
            editSliceForm: {},

            /* 粗粒度快速标注（第三阶段 #11） */
            showCoarseModal: false,
            coarseForm: { period: "", activity_desc: "", mood_intensity: 3, energy_level: 3, mood_tags: [] },
            sliceError: "",       /* 内联错误提示（第三阶段 #13） */

            /* 精力趋势 */
            energyProfile: [],
            energyTrend: [],
            showEnergyChart: false,
        };
    },

    computed: {
        weekDays() { return ["一", "二", "三", "四", "五", "六", "日"]; },

        heatmapTitle() {
            const d = new Date();
            d.setMonth(d.getMonth() + this.heatmapMonth);
            return `${d.getFullYear()}年${d.getMonth() + 1}月`;
        },

        heatmapCells() {
            const d = new Date();
            d.setMonth(d.getMonth() + this.heatmapMonth);
            const year = d.getFullYear(), month = d.getMonth();
            const firstDay = new Date(year, month, 1);
            const lastDay = new Date(year, month + 1, 0);
            this.heatmapOffset = (firstDay.getDay() + 6) % 7;
            const countMap = {};
            const deviceMap = {};
            this.heatmapData.forEach(h => {
                countMap[h.date] = h.slice_count || 0;
                deviceMap[h.date] = h.has_device_data || false;
            });
            const cells = [];
            for (let day = 1; day <= lastDay.getDate(); day++) {
                const ds = `${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
                cells.push({
                    date: ds, day,
                    slice_count: countMap[ds] || 0,
                    has_device_data: deviceMap[ds] || false,
                });
            }
            return cells;
        },
    },

    watch: {
        heatmapMonth() { this.loadHeatmap(); },
    },

    methods: {
        /* ── 数据加载 ──────────────────────────────────── */
        async loadAll() {
            await Promise.all([
                this.loadSlices(),
                this.loadDeviceLogs(),
                this.loadDeviceSummary(),
                this.loadHeatmap(),
            ]);
        },

        async loadSlices() {
            this.slices = await this.api(`/api/slices?date=${this.viewDate}`);
        },
        async loadDeviceLogs() {
            this.deviceLogs = await this.api(`/api/slices/device-logs?date=${this.viewDate}`);
        },
        async loadDeviceSummary() {
            this.deviceSummary = await this.api(`/api/slices/device-logs/summary?date=${this.viewDate}`);
        },
        async loadHeatmap() {
            this.heatmapData = await this.api("/api/slices/heatmap");
        },

        /* ── 新增切片 ──────────────────────────────────── */
        async submitSlice() {
            this.sliceError = "";
            if (!this.sliceForm.activity_desc.trim()) {
                this.sliceError = "请输入活动描述"; return;
            }
            try {
                await this.api("/api/slices", {
                    method: "POST",
                    body: JSON.stringify({
                        timestamp: this.sliceForm.timestamp.replace("T", " ") + ":00",
                        activity_desc: this.sliceForm.activity_desc.trim(),
                        mood_tags: this.sliceForm.mood_tags,
                        mood_intensity: this.sliceForm.mood_intensity,
                        energy_level: this.sliceForm.energy_level,
                        related_task_id: this.sliceForm.related_task_id,
                        notes: this.sliceForm.notes.trim(),
                    }),
                });
                this.sliceForm.activity_desc = "";
                this.sliceForm.notes = "";
                this.sliceForm.mood_tags = [];
                const now = new Date();
                this.sliceForm.timestamp = new Date(now.getTime() - now.getTimezoneOffset() * 60000)
                    .toISOString().slice(0, 16);
                await this.loadAll();
            } catch (e) {
                this.sliceError = "提交失败：" + e.message;
            }
        },

        /* ── 编辑切片（第三阶段 #9） ────────────────────── */
        openEditSlice(slc) {
            this.editSliceForm = {
                id: slc.id,
                timestamp: slc.timestamp.slice(0, 16).replace(" ", "T"),
                activity_desc: slc.activity_desc,
                mood_tags: [...slc.mood_tags],
                mood_intensity: slc.mood_intensity,
                energy_level: slc.energy_level,
                related_task_id: slc.related_task_id,
                notes: slc.notes || "",
            };
            this.showEditSliceModal = true;
        },

        closeEditSlice() { this.showEditSliceModal = false; },

        async saveEditSlice() {
            this.sliceError = "";
            if (!this.editSliceForm.activity_desc.trim()) {
                this.sliceError = "请输入活动描述"; return;
            }
            try {
                const body = {
                    timestamp: this.editSliceForm.timestamp.replace("T", " ") + ":00",
                    activity_desc: this.editSliceForm.activity_desc.trim(),
                    mood_tags: this.editSliceForm.mood_tags,
                    mood_intensity: this.editSliceForm.mood_intensity,
                    energy_level: this.editSliceForm.energy_level,
                    related_task_id: this.editSliceForm.related_task_id,
                    notes: (this.editSliceForm.notes || "").trim(),
                };
                await this.api(`/api/slices/${this.editSliceForm.id}`, {
                    method: "PUT",
                    body: JSON.stringify(body),
                });
                this.showEditSliceModal = false;
                await this.loadAll();
            } catch (e) {
                this.sliceError = "保存失败：" + e.message;
            }
        },

        async deleteSlice(id) {
            if (!confirm("删除该切片？")) return;
            await this.api(`/api/slices/${id}`, { method: "DELETE" });
            await this.loadAll();
        },

        /* ── 情绪标签 ──────────────────────────────────── */
        toggleTag(name) {
            const idx = this.sliceForm.mood_tags.indexOf(name);
            if (idx >= 0) this.sliceForm.mood_tags.splice(idx, 1);
            else this.sliceForm.mood_tags.push(name);
        },

        tagColor(name) {
            const t = this.moodTags.find(m => m.name === name);
            return t ? t.color : "#6e6e73";
        },

        /* ── 关联任务 ──────────────────────────────────── */
        getTaskTitle(taskId) {
            const t = this.assistantTasks.find(x => x.id === taskId);
            return t ? t.title : "(已删除)";
        },

        /* ── 热力图 ──────────────────────────────────── */
        heatLevel(count) {
            if (count === 0) return "lvl-0";
            if (count === 1) return "lvl-1";
            if (count <= 3) return "lvl-2";
            if (count <= 5) return "lvl-3";
            return "lvl-4";
        },

        deviceDot(hasDevice) {
            return hasDevice ? "dot-yes" : "dot-no";
        },

        goDate(dateStr) {
            this.viewDate = dateStr;
            this.loadAll();
        },

        /* ── 日期导航 ──────────────────────────────────── */
        shiftDate(delta) {
            const d = new Date(this.viewDate);
            d.setDate(d.getDate() + delta);
            this.viewDate = d.toISOString().slice(0, 10);
            this.loadAll();
        },

        goToday() {
            this.viewDate = new Date().toISOString().slice(0, 10);
            this.loadAll();
        },

        /* ── 粗粒度快速标注（第三阶段 #11） ────────────── */
        openCoarse(period) {
            const now = new Date();
            const local = new Date(now.getTime() - now.getTimezoneOffset() * 60000)
                .toISOString().slice(0, 16);
            const hourMap = { morning: "08:00", afternoon: "14:00", evening: "20:00" };
            this.coarseForm = {
                period,
                timestamp: local.slice(0, 10) + "T" + hourMap[period],
                activity_desc: "",
                mood_intensity: 3,
                energy_level: 3,
                mood_tags: [],
            };
            this.showCoarseModal = true;
            this.sliceError = "";
        },

        closeCoarse() { this.showCoarseModal = false; },

        async submitCoarse() {
            this.sliceError = "";
            if (!this.coarseForm.activity_desc.trim()) {
                this.sliceError = "请输入活动描述"; return;
            }
            try {
                await this.api("/api/slices", {
                    method: "POST",
                    body: JSON.stringify({
                        timestamp: this.coarseForm.timestamp.replace("T", " ") + ":00",
                        activity_desc: this.coarseForm.activity_desc.trim(),
                        mood_tags: this.coarseForm.mood_tags,
                        mood_intensity: this.coarseForm.mood_intensity,
                        energy_level: this.coarseForm.energy_level,
                        related_task_id: null,
                        notes: "",
                        granularity: "coarse",
                    }),
                });
                this.showCoarseModal = false;
                await this.loadAll();
            } catch (e) {
                this.sliceError = "提交失败：" + e.message;
            }
        },

        /* ── 工具 ──────────────────────────────────────── */
        formatTime(ts) {
            return ts ? ts.slice(11, 16) : "";
        },

        /* ── 切片模块初始化 ────────────────────────────── */
        async initSlices() {
            this.moodTags = await this.api("/api/slices/mood-tags");
            this.assistantTasks = await this.api("/api/slices/assistant-tasks");
            await this.loadAll();
            const today = new Date();
            const firstDay = new Date(today.getFullYear(), today.getMonth(), 1);
            this.heatmapOffset = (firstDay.getDay() + 6) % 7;
        },

        /* ── 精力趋势 ──────────────────────────────────── */
        async loadEnergyProfile() {
            try {
                const data = await this.api("/api/slices/energy-profile");
                this.energyProfile = data.profile;
                this.energyTrend = data.trend;
            } catch (e) {
                console.error("加载精力数据失败:", e);
            }
        },
        async refreshEnergyProfile() {
            try {
                const data = await this.api("/api/slices/energy-profile/refresh", { method: "POST" });
                this.energyProfile = data.profile;
            } catch (e) {
                alert("刷新精力数据失败：" + e.message);
            }
        },
        async generateYesterdaySlices() {
            try {
                const data = await this.api("/api/slices/auto-generate/yesterday", { method: "POST" });
                alert(`已生成 ${data.count} 条昨日自动切片`);
                await this.loadAll();
            } catch (e) {
                alert("生成失败：" + e.message);
            }
        },
        energyBarWidth(avg) {
            if (!avg) return 0;
            return Math.round((avg / 5) * 100);
        },
        periodLabel(period) {
            return { morning: "上午", afternoon: "下午", evening: "晚上" }[period] || period;
        },
        energyTrendLabel(day) {
            return day.slice(5);  // MM-DD
        },
    },
};
