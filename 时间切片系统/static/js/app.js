/* app.js — Vue 3 应用：切片录入、列表查看、日历热力图、设备记录 */

const { createApp } = Vue;

createApp({
    data() {
        const now = new Date();
        const local = new Date(now.getTime() - now.getTimezoneOffset() * 60000)
            .toISOString().slice(0, 16);
        return {
            /* 新增切片表单 */
            form: {
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
            heatmapMonth: 0,               // 0=当月, -1=上月, +1=下月
            heatmapOffset: 0,             // Bug #1 修复：从 computed 改为 data
        };
    },

    computed: {
        weekDays() { return ["一", "二", "三", "四", "五", "六", "日"]; },

        heatmapTitle() {
            const d = new Date();
            d.setMonth(d.getMonth() + this.heatmapMonth);
            return `${d.getFullYear()}年${d.getMonth() + 1}月`;
        },

        /* heatmapOffset → 改为 data 属性 heatmapOffset，在下方 computed 中更新 */

        heatmapCells() {
            const d = new Date();
            d.setMonth(d.getMonth() + this.heatmapMonth);
            const year = d.getFullYear(), month = d.getMonth();
            const firstDay = new Date(year, month, 1);
            const lastDay = new Date(year, month + 1, 0);

            // Bug #1 修复：直接更新 data 属性（响应式）
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
                    date: ds,
                    day,
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
        /* ── API ─────────────────────────────────────── */
        async api(url, options = {}) {
            const res = await fetch(url, {
                headers: { "Content-Type": "application/json" },
                ...options,
            });
            if (!res.ok) {
                const e = await res.json().catch(() => ({}));
                throw new Error(e.error || `HTTP ${res.status}`);
            }
            return res.json();
        },

        /* ── 数据加载 ────────────────────────────────── */
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
            this.deviceLogs = await this.api(`/api/device-logs?date=${this.viewDate}`);
        },
        async loadDeviceSummary() {
            this.deviceSummary = await this.api(`/api/device-logs/summary?date=${this.viewDate}`);
        },
        async loadHeatmap() {
            this.heatmapData = await this.api("/api/heatmap");
        },

        /* ── 新增切片 ────────────────────────────────── */
        async submitSlice() {
            if (!this.form.activity_desc.trim()) return alert("请输入活动描述");
            try {
                await this.api("/api/slices", {
                    method: "POST",
                    body: JSON.stringify({
                        timestamp: this.form.timestamp.replace("T", " ") + ":00",
                        activity_desc: this.form.activity_desc.trim(),
                        mood_tags: this.form.mood_tags,
                        mood_intensity: this.form.mood_intensity,
                        energy_level: this.form.energy_level,
                        related_task_id: this.form.related_task_id,
                        notes: this.form.notes.trim(),
                    }),
                });

                // 清空部分表单
                this.form.activity_desc = "";
                this.form.notes = "";
                this.form.mood_tags = [];

                // Bug #5 修复：时间戳自动推进到当前时间
                const now = new Date();
                this.form.timestamp = new Date(now.getTime() - now.getTimezoneOffset() * 60000)
                    .toISOString().slice(0, 16);

                await this.loadAll();
            } catch (e) {
                alert("提交失败：" + e.message);
            }
        },

        async deleteSlice(id) {
            if (!confirm("删除该切片？")) return;
            await this.api(`/api/slices/${id}`, { method: "DELETE" });
            await this.loadAll();
        },

        /* ── 情绪标签 ────────────────────────────────── */
        toggleTag(name) {
            const idx = this.form.mood_tags.indexOf(name);
            if (idx >= 0) this.form.mood_tags.splice(idx, 1);
            else this.form.mood_tags.push(name);
        },

        tagColor(name) {
            const t = this.moodTags.find(m => m.name === name);
            return t ? t.color : "#6e6e73";
        },

        /* ── 关联任务 ────────────────────────────────── */
        getTaskTitle(taskId) {
            const t = this.assistantTasks.find(x => x.id === taskId);
            return t ? t.title : "(已删除)";
        },

        /* ── 热力图 ──────────────────────────────────── */
        heatLevel(count) {
            /* Bug #3 修复：阈值改为手动切片数（0/1/2-3/4-5/6+） */
            if (count === 0) return "lvl-0";
            if (count === 1) return "lvl-1";
            if (count <= 3) return "lvl-2";
            if (count <= 5) return "lvl-3";
            return "lvl-4";
        },

        deviceDot(hasDevice) {
            /* 设备日志标记（格子底部小圆点） */
            return hasDevice ? "dot-yes" : "dot-no";
        },

        goDate(dateStr) {
            this.viewDate = dateStr;
            this.loadAll();
        },

        /* ── 日期导航 ────────────────────────────────── */
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

        /* ── 工具 ────────────────────────────────────── */
        formatTime(ts) {
            if (!ts) return "";
            return ts.slice(11, 16);
        },

        /* ── 弹出窗口（浏览器模式保留） ──────────────── */
        popupMode() {
            const w = 1200, h = 800;
            window.open(location.href, "TimeSlicer",
                `width=${w},height=${h},` +
                "menubar=no,toolbar=no,location=no,status=no,resizable=yes,scrollbars=yes");
        },
    },

    /* ── 生命周期 ──────────────────────────────────── */
    async mounted() {
        this.moodTags = await this.api("/api/mood-tags");
        this.assistantTasks = await this.api("/api/assistant-tasks");
        await this.loadAll();
        // 初始化当月偏移
        const today = new Date();
        const firstDay = new Date(today.getFullYear(), today.getMonth(), 1);
        this.heatmapOffset = (firstDay.getDay() + 6) % 7;
    },
}).mount("#app");
