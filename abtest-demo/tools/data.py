"""Mock 数据集：3 个实验、7 个指标、细分维度、分日趋势。"""

ALL_EXPERIMENTS = [
    {
        "id": "exp_rec_20260515_llm_embedding_v2",
        "name": "推荐算法升级：协同过滤 → LLM Embedding",
        "status": "进行中",
        "period": "2026-05-15 ~ 2026-05-28",
        "sample_total": 90420,
        "primary_metric": "购买转化率（CVR）",
    },
    {
        "id": "exp_price_20260401_layout_v3",
        "name": "商品详情页改版：旧版布局 → 新版沉浸式布局",
        "status": "已完成",
        "period": "2026-04-01 ~ 2026-04-14",
        "sample_total": 78200,
        "primary_metric": "人均浏览深度（页数）",
    },
    {
        "id": "exp_ads_20260310_targeting_v5",
        "name": "广告定向策略升级：人口统计 → 行为兴趣标签",
        "status": "已完成",
        "period": "2026-03-10 ~ 2026-03-24",
        "sample_total": 120000,
        "primary_metric": "广告点击率（CTR）",
    },
]

EXPERIMENT = {
    "id": "exp_rec_20260515_llm_embedding_v2",
    "name": "推荐算法升级：协同过滤 → LLM Embedding",
    "hypothesis": "大模型 Embedding 替代协同过滤能提升购买转化率",
    "period": "2026-05-15 ~ 2026-05-28（14天）",
    "split": "50/50 随机分流，基于 user_id hash",
    "sample_size": {"control": 45231, "treatment": 45189},
    "power_analysis": {
        "mde": "CVR 相对提升 8%",
        "power": 0.82,
        "required_sample_per_group": 43000,
        "verdict": "样本量充足，可检测到 8% 以上的 CVR 提升",
    },
}

METRICS = {
    "cvr": {
        "name": "购买转化率", "type": "primary", "higher_is_better": True,
        "control": {"mean": 0.0342, "std": 0.0183, "n": 45231},
        "treatment": {"mean": 0.0389, "std": 0.0196, "n": 45189},
    },
    "gmv_per_user": {
        "name": "人均 GMV（元）", "type": "business", "higher_is_better": True,
        "control": {"mean": 128.5, "std": 42.3, "n": 45231},
        "treatment": {"mean": 141.2, "std": 40.8, "n": 45189},
    },
    "ctr": {
        "name": "点击率", "type": "business", "higher_is_better": True,
        "control": {"mean": 0.128, "std": 0.042, "n": 45231},
        "treatment": {"mean": 0.136, "std": 0.040, "n": 45189},
    },
    "session_duration_s": {
        "name": "平均停留时长（秒）", "type": "experience", "higher_is_better": True,
        "control": {"mean": 252, "std": 108, "n": 45231},
        "treatment": {"mean": 270, "std": 102, "n": 45189},
    },
    "bounce_rate": {
        "name": "跳出率", "type": "guardrail", "higher_is_better": False,
        "control": {"mean": 0.385, "std": 0.098, "n": 45231},
        "treatment": {"mean": 0.378, "std": 0.102, "n": 45189},
    },
    "api_latency_ms": {
        "name": "接口响应时间（ms）", "type": "guardrail", "higher_is_better": False,
        "control": {"mean": 145, "std": 32, "n": 45231},
        "treatment": {"mean": 312, "std": 58, "n": 45189},
    },
    "complaint_rate": {
        "name": "客诉率", "type": "guardrail", "higher_is_better": False,
        "control": {"mean": 0.0021, "std": 0.0018, "n": 45231},
        "treatment": {"mean": 0.0019, "std": 0.0019, "n": 45189},
    },
}

SEGMENT_BREAKDOWN = {
    "by_device": [
        {"segment": "iOS", "traffic_pct": 35, "control_cvr": 0.041, "treatment_cvr": 0.053,
         "lift_pct": 29.3, "n_control": 15830, "n_treatment": 15816},
        {"segment": "Android 高端", "traffic_pct": 30, "control_cvr": 0.035, "treatment_cvr": 0.038,
         "lift_pct": 8.6, "n_control": 13569, "n_treatment": 13557},
        {"segment": "Android 中低端", "traffic_pct": 35, "control_cvr": 0.028, "treatment_cvr": 0.027,
         "lift_pct": -3.6, "n_control": 15832, "n_treatment": 15816,
         "note": "中低端设备 LLM Embedding 推理超时导致推荐结果不完整"},
    ],
    "by_active_level": [
        {"segment": "高活（近7天有浏览）", "traffic_pct": 45, "control_cvr": 0.048, "treatment_cvr": 0.059,
         "lift_pct": 22.9, "n_control": 20354, "n_treatment": 20335},
        {"segment": "中活（近30天有浏览）", "traffic_pct": 35, "control_cvr": 0.029, "treatment_cvr": 0.031,
         "lift_pct": 6.9, "n_control": 15831, "n_treatment": 15816},
        {"segment": "低活（30天以上）", "traffic_pct": 20, "control_cvr": 0.015, "treatment_cvr": 0.014,
         "lift_pct": -6.7, "n_control": 9046, "n_treatment": 9038,
         "note": "样本量较小，虽不显著但趋势需关注"},
    ],
}

DAILY_SERIES = {
    "dates": ["05-15","05-16","05-17","05-18","05-19","05-20","05-21",
              "05-22","05-23","05-24","05-25","05-26","05-27","05-28"],
    "control_cvr":  [0.0338,0.0341,0.0335,0.0344,0.0340,0.0352,0.0345,
                     0.0339,0.0343,0.0338,0.0346,0.0341,0.0344,0.0342],
    "treatment_cvr":[0.0351,0.0362,0.0371,0.0378,0.0382,0.0388,0.0385,
                     0.0391,0.0387,0.0393,0.0390,0.0392,0.0388,0.0389],
    "control_latency": [145]*14,
    "treatment_latency": [328,335,321,318,315,310,308,312,309,314,311,308,313,312],
}
