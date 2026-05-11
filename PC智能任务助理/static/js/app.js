/* app.js — Vue 3 应用：任务管理、拖拽排序、排程交互、编辑、手动分配、桌面通知 */

const { createApp } = Vue;

createApp({
    data() {
        return {
            /* 新增任务表单 */
            form: { title: "", priority: 3, estimated_minutes: 30, deadline: "" },

            /* 数据 */
            tasks: [],              // 全部任务
            availabilities: [],     // 可用时段
            scheduled: [],          // 今日排程结果（从 schedule_results 表加载）
            unscheduled: [],        // 未排入的任务
            loading: false,         // 排程加载标志
            dragId: null,           // 当前拖拽中的任务 id
            notifyGranted: false,   // 通知权限状态
            sortable: null,         // SortableJS 实例

            /* 编辑弹窗 */
            showEditModal: false,
            editForm: { id: null, title: "", priority: 3, estimated_minutes: 30, deadline: "" },
            editTaskWasScheduled: false,

            /* 手动分配弹窗 */
            showAssignModal: false,
            assignTask: null,
            assignGaps: [],
            selectedGapIndex: null,
        };
    },

    computed: {
        allTasks()       { return this.tasks; },
        pendingTasks()   { return this.tasks.filter(t => t.status === "pending"); },
        doneTasks()      { return this.tasks.filter(t => t.status === "done"); },
    },

    methods: {
        /* ── API 工具方法 ──────────────────────────────── */
        async api(url, options = {}) {
            const res = await fetch(url, {
                headers: { "Content-Type": "application/json" },
                ...options,
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.error || `HTTP ${res.status}`);
            }
            return res.json();
        },

        /* ── 数据加载 ──────────────────────────────────── */
        async fetchTasks() {
            this.tasks = await this.api("/api/tasks?status=all");
            this.$nextTick(() => this.initSortable());
        },
        async fetchAvailability() {
            this.availabilities = await this.api("/api/availability");
        },

        /* ── 排程加载（从持久化表读取，不重新计算） ────── */
        async loadSchedule() {
            try {
                const data = await this.api("/api/schedule");
                this.scheduled = data.scheduled;
                this.unscheduled = data.unscheduled;
            } catch (e) {
                console.error("加载排程失败:", e);
            }
        },

        /* ── 重新排程（计算 → 持久化 → 加载） ──────────── */
        async refreshSchedule() {
            this.loading = true;
            try {
                const data = await this.api("/api/schedule", { method: "POST" });
                this.scheduled = data.scheduled;
                this.unscheduled = data.unscheduled;
            } catch (e) {
                alert("排程失败：" + e.message);
            } finally {
                this.loading = false;
            }
        },

        /* ── 删除排程项（手动分配的退回未排程） ────────── */
        async removeScheduleItem(itemId) {
            await this.api(`/api/schedule/${itemId}`, { method: "DELETE" });
            await Promise.all([this.fetchTasks(), this.loadSchedule()]);
        },

        /* ── 任务操作 ──────────────────────────────────── */
        async submitTask() {
            const title = this.form.title.trim();
            if (!title) return alert("请输入任务名称");
            if (!this.form.estimated_minutes || this.form.estimated_minutes < 1)
                return alert("请输入有效的预估时长");

            const deadline = this.form.deadline
                ? this.form.deadline.replace("T", " ") + ":00"
                : null;

            try {
                await this.api("/api/tasks", {
                    method: "POST",
                    body: JSON.stringify({
                        title,
                        priority: this.form.priority,
                        estimated_minutes: this.form.estimated_minutes,
                        deadline,
                    }),
                });
                this.form.title = "";
                this.form.priority = 3;
                this.form.estimated_minutes = 30;
                this.form.deadline = "";
                await Promise.all([this.fetchTasks(), this.loadSchedule()]);
            } catch (e) {
                alert("添加失败：" + e.message);
            }
        },

        async markDone(taskId) {
            await this.api(`/api/tasks/${taskId}`, {
                method: "PUT",
                body: JSON.stringify({ status: "done" }),
            });
            await Promise.all([this.fetchTasks(), this.loadSchedule()]);
        },

        async markUndo(taskId) {
            await this.api(`/api/tasks/${taskId}`, {
                method: "PUT",
                body: JSON.stringify({ status: "pending" }),
            });
            await Promise.all([this.fetchTasks(), this.loadSchedule()]);
        },

        async deleteTask(taskId) {
            if (!confirm("确认删除该任务？")) return;
            await this.api(`/api/tasks/${taskId}`, { method: "DELETE" });
            await Promise.all([this.fetchTasks(), this.loadSchedule()]);
        },

        /* ── 编辑任务 ──────────────────────────────────── */
        openEdit(task) {
            this.editForm.id = task.id;
            this.editForm.title = task.title;
            this.editForm.priority = task.priority;
            this.editForm.estimated_minutes = task.estimated_minutes;
            // 将 "YYYY-MM-DD HH:MM:SS" 转回 datetime-local 格式
            this.editForm.deadline = task.deadline
                ? task.deadline.replace(" ", "T").slice(0, 16)
                : "";
            // 检查该任务是否已在今日排程中
            this.editTaskWasScheduled = this.scheduled.some(
                s => s.task.id === task.id
            );
            this.showEditModal = true;
        },

        closeEdit() {
            this.showEditModal = false;
        },

        async saveEdit() {
            const title = this.editForm.title.trim();
            if (!title) return alert("请输入任务名称");

            const deadline = this.editForm.deadline
                ? this.editForm.deadline.replace("T", " ") + ":00"
                : null;

            try {
                await this.api(`/api/tasks/${this.editForm.id}`, {
                    method: "PUT",
                    body: JSON.stringify({
                        title,
                        priority: this.editForm.priority,
                        estimated_minutes: this.editForm.estimated_minutes,
                        deadline,
                    }),
                });
                this.showEditModal = false;
                await Promise.all([this.fetchTasks(), this.loadSchedule()]);

                if (this.editTaskWasScheduled) {
                    alert("任务已更新！该任务此前已排程，建议点击「重新排程」刷新排程结果。");
                }
            } catch (e) {
                alert("保存失败：" + e.message);
            }
        },

        /* ── 手动分配 ──────────────────────────────────── */
        async openAssign(task) {
            this.assignTask = task;
            this.selectedGapIndex = null;
            this.showAssignModal = true;
            try {
                this.assignGaps = await this.api("/api/schedule/gaps");
            } catch (e) {
                this.assignGaps = [];
                alert("获取空闲时段失败：" + e.message);
            }
        },

        closeAssign() {
            this.showAssignModal = false;
            this.assignTask = null;
            this.assignGaps = [];
            this.selectedGapIndex = null;
        },

        async confirmAssign() {
            if (this.selectedGapIndex === null || !this.assignTask) return;
            const gap = this.assignGaps[this.selectedGapIndex];
            const taskMin = this.assignTask.estimated_minutes;

            // 将任务放在间隙开头，但不超过 gap_end
            const [sh, sm] = gap.gap_start.split(":").map(Number);
            const startMin = sh * 60 + sm;
            const endMin = Math.min(startMin + taskMin, startMin + gap.gap_minutes);
            const eh = Math.floor(endMin / 60), em = endMin % 60;
            const endTime = `${String(eh).padStart(2, "0")}:${String(em).padStart(2, "0")}`;

            const today = new Date().toISOString().slice(0, 10);

            try {
                await this.api("/api/schedule/assign", {
                    method: "POST",
                    body: JSON.stringify({
                        task_id: this.assignTask.id,
                        scheduled_date: today,
                        start_time: gap.gap_start,
                        end_time: endTime,
                        slot_label: gap.slot_label,
                    }),
                });
                this.closeAssign();
                await Promise.all([this.fetchTasks(), this.loadSchedule()]);
            } catch (e) {
                alert("分配失败：" + e.message);
            }
        },

        /* ── 拖拽排序（SortableJS） ──────────────────────── */
        initSortable() {
            const el = this.$refs.sortableList;
            if (!el) return;
            if (this.sortable) this.sortable.destroy();

            this.sortable = Sortable.create(el, {
                animation: 150,
                handle: ".drag-handle",
                ghostClass: "task-dragging",
                onStart: (evt) => {
                    this.dragId = this.pendingTasks[evt.oldIndex]?.id;
                },
                onEnd: async (evt) => {
                    this.dragId = null;
                    const movedTask = this.pendingTasks[evt.oldIndex];
                    if (!movedTask || evt.oldIndex === evt.newIndex) return;

                    const reordered = [...this.pendingTasks];
                    const [item] = reordered.splice(evt.oldIndex, 1);
                    reordered.splice(evt.newIndex, 0, item);

                    const updates = reordered.map((t, i) =>
                        this.api(`/api/tasks/${t.id}`, {
                            method: "PUT",
                            body: JSON.stringify({ sort_order: i }),
                        })
                    );
                    await Promise.all(updates);
                    await this.fetchTasks();
                },
            });
        },

        /* ── 可用时段操作 ──────────────────────────────── */
        async addAvail() {
            try {
                await this.api("/api/availability", {
                    method: "POST",
                    body: JSON.stringify({ label: "新时段", start_time: "08:00", end_time: "10:00" }),
                });
                await this.fetchAvailability();
            } catch (e) { alert("添加时段失败"); }
        },

        async saveAvail(avail) {
            if (!avail.id) return;
            try {
                await this.api(`/api/availability/${avail.id}`, {
                    method: "PUT",
                    body: JSON.stringify({
                        label: avail.label,
                        start_time: avail.start_time,
                        end_time: avail.end_time,
                    }),
                });
            } catch (e) { alert("保存时段失败"); }
        },

        async deleteAvail(availId) {
            if (!confirm("删除该可用时段？")) return;
            await this.api(`/api/availability/${availId}`, { method: "DELETE" });
            await Promise.all([this.fetchAvailability(), this.loadSchedule()]);
        },

        /* ── 桌面通知 ──────────────────────────────────── */
        async requestNotification() {
            if (!("Notification" in window)) return alert("浏览器不支持桌面通知");
            const perm = await Notification.requestPermission();
            this.notifyGranted = perm === "granted";
            if (this.notifyGranted) {
                new Notification("PC智能任务助理", {
                    body: "通知已开启！排程任务开始前会提醒你。",
                });
            }
        },

        checkScheduleNotifications() {
            if (!this.notifyGranted || this.scheduled.length === 0) return;
            const now = new Date();
            const nowMin = now.getHours() * 60 + now.getMinutes();
            this.scheduled.forEach(item => {
                const [h, m] = item.start.split(":").map(Number);
                const itemMin = h * 60 + m;
                if (itemMin - nowMin <= 2 && itemMin - nowMin >= 0) {
                    new Notification(` 任务即将开始: ${item.task.title}`, {
                        body: `${item.start} – ${item.end}  ${item.slot_label}`,
                    });
                }
            });
        },

        /* ── 弹出窗口模式（记住位置和大小） ────────────── */
        popupMode() {
            const saved = this.loadWindowPrefs();
            const w = saved.width  || 1100;
            const h = saved.height || 750;
            const left = saved.left ?? Math.round((screen.width - w) / 2);
            const top  = saved.top  ?? Math.round((screen.height - h) / 2);

            const popup = window.open(
                location.href,
                "TaskAssistant",
                `width=${w},height=${h},left=${left},top=${top},` +
                "menubar=no,toolbar=no,location=no,status=no,resizable=yes,scrollbars=yes"
            );

            // 窗口关闭前写入位置/大小（需要同源）
            if (popup) {
                const saveTimer = setInterval(() => {
                    if (popup.closed) {
                        clearInterval(saveTimer);
                        return;
                    }
                    try {
                        const prefs = {
                            width:  popup.outerWidth,
                            height: popup.outerHeight,
                            left:   popup.screenX,
                            top:    popup.screenY,
                        };
                        if (prefs.width > 0 && prefs.height > 0)
                            this.saveWindowPrefs(prefs);
                    } catch (_) { /* 跨域时忽略 */ }
                }, 1000);

                // 原窗口也关闭自己（可选：注释掉则保留主窗口）
                // window.close();
            }
        },

        loadWindowPrefs() {
            try {
                return JSON.parse(localStorage.getItem("popupWindowPrefs")) || {};
            } catch (_) { return {}; }
        },

        saveWindowPrefs(prefs) {
            try {
                localStorage.setItem("popupWindowPrefs", JSON.stringify(prefs));
            } catch (_) { /* quota exceeded, ignore */ }
        },

        /* ── 工具 ──────────────────────────────────────── */
        formatDeadline(dl) {
            if (!dl) return "";
            const d = new Date(dl.replace(" ", "T"));
            const m = d.getMonth() + 1, day = d.getDate();
            const hh = String(d.getHours()).padStart(2, "0");
            const mm = String(d.getMinutes()).padStart(2, "0");
            return `${m}/${day} ${hh}:${mm}`;
        },

        isSoon(dl) {
            if (!dl) return false;
            const diff = new Date(dl.replace(" ", "T")) - new Date();
            return diff > 0 && diff < 24 * 60 * 60 * 1000;
        },
    },

    /* ── 生命周期 ──────────────────────────────────────── */
    async mounted() {
        await Promise.all([this.fetchTasks(), this.fetchAvailability()]);
        await this.loadSchedule();      // 从持久化表加载排程，不重新计算

        if ("Notification" in window && Notification.permission === "granted") {
            this.notifyGranted = true;
        }

        // 每分钟自动刷新排程 + 检查通知
        setInterval(() => {
            this.loadSchedule();
            this.checkScheduleNotifications();
        }, 60000);

        // 标签页切回前台时立即检查通知（对抗后台节流）
        document.addEventListener("visibilitychange", () => {
            if (!document.hidden) {
                this.loadSchedule();
                this.checkScheduleNotifications();
            }
        });
    },
}).mount("#app");
