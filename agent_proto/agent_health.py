# -*- coding: utf-8 -*-
"""
agent_health.py — 小米手环 10 NFC 数据接口（Phase 4G）
预留：心率、HRV、睡眠数据接入。

当前状态：占位模块。数据接口已定义完毕，待硬件连接后填充。
隐私约束：全部生理数据仅本地 9B 处理，绝不送云端。

运行测试: py agent_proto/agent_health.py
"""

# ═══════════════════════════════════════════════════════════
# 数据格式定义
# ═══════════════════════════════════════════════════════════

# 心率样本（bpm）
# 来源：小米手环 10 NFC 蓝牙 BLE 实时推送
# 接口：待接入后补充（Zepp OS / Mi Fitness API / 第三方如 Gadgetbridge）
HEART_RATE_SAMPLE = {
    "timestamp": "2026-05-12T14:30:00",
    "bpm": 72,
    "source": "mi_band_10",
}

# HRV 样本（毫秒）
# SDNN / RMSSD 等指标，需手环支持
HRV_SAMPLE = {
    "timestamp": "2026-05-12T14:30:00",
    "sdnn_ms": 45.2,
    "rmssd_ms": 32.1,
    "source": "mi_band_10",
}

# 睡眠数据
SLEEP_SAMPLE = {
    "date": "2026-05-12",
    "deep_sleep_min": 120,
    "light_sleep_min": 240,
    "rem_min": 90,
    "awake_min": 30,
    "score": 82,
    "source": "mi_band_10",
}


# ═══════════════════════════════════════════════════════════
# 占位实现
# ═══════════════════════════════════════════════════════════

def is_available():
    """检查手环数据是否可用"""
    return False  # 未接入


def get_latest_heart_rate():
    """获取最近一次心率读数，不可用时返回 None"""
    return None


def get_today_avg_heart_rate():
    """今日平均心率，不可用时返回 None"""
    return None


def get_last_night_sleep():
    """昨晚睡眠数据，不可用时返回 None"""
    return None


def get_hrv_trend():
    """最近 HRV 趋势（上升/下降/平稳），不可用时返回 None"""
    return None


# ═══════════════════════════════════════════════════════════
# 接入指南
# ═══════════════════════════════════════════════════════════

SETUP_GUIDE = """
小米手环 10 NFC 数据接入方案：

方案 A — Zepp OS 开放平台
  1. 注册小米开发者账号
  2. 创建应用获取 API Key
  3. 通过 HTTPS 拉取健康数据

方案 B — Gadgetbridge（开源）
  1. 安装 Gadgetbridge Android 应用
  2. 配对小米手环
  3. 通过 Gadgetbridge API 或直接读取其 SQLite 数据库

方案 C — 手机中转
  1. 手机安装 Mi Fitness 并同步手环数据
  2. 使用自动化工具（如 Tasker）将数据推送到 PC
  3. PC 端接收并写入本模块

当前推荐：方案 B（Gadgetbridge），无需小米账号，数据本地化。
接入后实现 is_available/get_latest_heart_rate/get_today_avg_heart_rate 等函数即可。
"""


# ═══════════════════════════════════════════════════════════
# 测试
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    print("── Agent Health 模块 ──\n")
    print(f"手环数据可用: {is_available()}")
    print(f"最近心率: {get_latest_heart_rate()}")
    print(f"今日平均心率: {get_today_avg_heart_rate()}")
    print(f"昨晚睡眠: {get_last_night_sleep()}")
    print(f"HRV 趋势: {get_hrv_trend()}")
    print()
    print(SETUP_GUIDE)
