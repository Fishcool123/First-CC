/* app.js — Vue 3 主应用：侧边栏导航 + Mixin 合并 */
/* 依赖：tasks.js (tasksMixin)、slices.js (slicesMixin) 已提前加载 */

const { createApp } = Vue;

createApp({
    mixins: [tasksMixin, slicesMixin],

    data() {
        return {
            currentTab: "tasks",  // 'tasks' | 'slices' | 'settings'
            rules: [],
            pendingPrompt: null,
            rulesPollTimer: null,
        };
    },

    methods: {
        /* ── 共享 API 工具（tasks/slices 均使用） ────────── */
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

        /* ── 切换标签 ──────────────────────────────────── */
        switchTab(tab) {
            this.currentTab = tab;
            if (tab === "settings") this.loadRules();
        },

        /* ── 规则引擎 ──────────────────────────────────── */
        async loadRules() {
            this.rules = await this.api("/api/rules");
        },
        async toggleRuleItem(rule) {
            await this.api(`/api/rules/${rule.id}/toggle`, {
                method: "POST",
                body: JSON.stringify({ enabled: !rule.enabled }),
            });
            rule.enabled = !rule.enabled;
        },
        formatRuleParams(rule) {
            const p = rule.trigger_params;
            const keys = Object.keys(p);
            if (keys.length === 0) return "";
            return keys.map(k => `${p[k]}`).join(" · ");
        },
        async checkPendingPrompts() {
            try {
                const prompts = await this.api("/api/rules/prompts");
                if (prompts && prompts.length > 0) {
                    this.pendingPrompt = prompts[0];
                }
            } catch (_) {}
        },

        /* ── 弹出窗口模式（保留 PC助理的窗口位置记忆版） ── */
        popupMode() {
            const saved = this.loadWindowPrefs();
            const w = saved.width  || 1100;
            const h = saved.height || 750;
            const left = saved.left ?? Math.round((screen.width - w) / 2);
            const top  = saved.top  ?? Math.round((screen.height - h) / 2);

            const popup = window.open(
                location.href, "CogEnhancer",
                `width=${w},height=${h},left=${left},top=${top},` +
                "menubar=no,toolbar=no,location=no,status=no,resizable=yes,scrollbars=yes"
            );

            if (popup) {
                const saveTimer = setInterval(() => {
                    if (popup.closed) { clearInterval(saveTimer); return; }
                    try {
                        const prefs = {
                            width:  popup.outerWidth,
                            height: popup.outerHeight,
                            left:   popup.screenX,
                            top:    popup.screenY,
                        };
                        if (prefs.width > 0 && prefs.height > 0)
                            this.saveWindowPrefs(prefs);
                    } catch (_) { /* 跨域忽略 */ }
                }, 1000);
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
            } catch (_) { /* quota exceeded */ }
        },
    },

    /* ── 生命周期 ──────────────────────────────────────── */
    async mounted() {
        // 初始化两个模块，按当前标签优先加载
        if (this.currentTab === "tasks") {
            await this.initTasks();
            this.initSlices();  // 后台加载，不阻塞
        } else if (this.currentTab === "slices") {
            await this.initSlices();
            this.initTasks();
        }
        // 规则弹窗轮询
        this.rulesPollTimer = setInterval(() => this.checkPendingPrompts(), 10000);
    },
}).mount("#app");
