"""
config/industries/mobile.py
手机品类行业配置 — 所有模块（M2-M5）的行业参数都从这里读取。

字段说明：
  embedding_fields      — 向量化时拼接哪些字段（M2 使用）
  filter_fields         — 规则过滤字段分组（M2 使用）
  sort_strategies       — 排序公式（M2 使用）
  use_case_taxonomy     — 场景标签枚举
  processor_normalize   — 用户自然语言 → 数据库 processor_brand 值
  performance_tier_map  — 性能层级 → 数值映射
  recommend_dimensions  — 推荐评估维度与权重（M4 使用）
  compare_dimensions    — 对比维度与权重（M5 使用）
  shopping_slots        — 购物槽位定义（M5 使用）
  max_slot_questions    — 最多追问次数（M5 使用）
  prompts               — Prompt 模板（M3/M4 使用）
  enable_*              — 功能开关
"""


# ══════════════════════════════════════════════════════════════════════════════
# Prompt 模板（需在 MOBILE_CONFIG 之前定义）
# ══════════════════════════════════════════════════════════════════════════════

_DECOMPOSE_PROMPT = """你是手机推荐专家。将用户的模糊需求分解为结构化筛选条件。

## 可筛选维度
- use_case: gaming(游戏) / photography(拍照) / battery(续航) / business(商务) / student(学生) / budget(性价比) / flagship(旗舰)。多个用逗号分隔
- processor_brand: sd(骁龙) / mt(天玑) / apple(苹果芯片) / kirin(麒麟)
- performance_tier: flagship / mid / budget
- budget_max / budget_min: 价格区间（数字，单位元）
- brand: 品牌偏好，如 Apple、小米
- battery_min: 最低电池容量（mAh）
- screen_min / screen_max: 屏幕尺寸范围（寸）

## 隐式需求推理规则
- "旅游" / "户外" → use_case=photography,battery + battery_min≥4500
- "刷剧" / "看视频" → screen_min≥6.5 + battery_min≥4500
- "上学" / "学生" → use_case=student + budget_max≤3000
- "打游戏" / "电竞" → use_case=gaming + performance_tier=flagship
- "办公" / "商务" → use_case=business
- "送父母" / "老人用" → use_case=battery,business + performance_tier=mid

## 规则
1. 用户没说的维度不填（留空字符串或 null）
2. 金额数字精确提取（"5000以内" → budget_max=5000）
3. 不猜测用户没提到的属性
4. 只输出 JSON，不要其他文字

## Few-Shot
用户："5000以内适合打游戏的手机"
输出：{{"use_case":"gaming","budget_max":5000,"category":"手机"}}

用户："去青海旅游，拍照好续航长"
输出：{{"use_case":"photography,battery","battery_min":4500,"category":"手机"}}

用户："想买个手机"
输出：{{"category":"手机"}}

## 当前用户需求
{query}"""


_RERANK_PROMPT = """你是手机推荐专家。根据用户需求对候选商品排序，并解释推荐理由。

## 手机评估维度（按重要度）
1. 处理器性能（决定游戏、多任务体验）
2. 拍照能力（传感器、算法、焦段）
3. 续航（电池容量 + 功耗优化）
4. 屏幕素质（尺寸、刷新率、分辨率）
5. 价格（性价比）

## 用户需求
{query}

## 候选商品
{candidates}

## 要求
- 选出 top-3 进行详细推荐
- 每款给出 2-3 句推荐理由，理由必须基于商品的实际参数（处理器型号、电池容量等）
- 标注一款"最佳选择"和一款"性价比之选"
- 如果有明显不适合的商品，简要说明原因
- 输出 JSON 格式

输出格式：
{{
  "recommendations": [
    {{
      "rank": 1,
      "product_name": "小米14",
      "tag": "最佳选择",
      "reasons": ["骁龙8Gen3性能强劲，适合游戏", "¥3999性价比突出"],
      "price": 3999,
      "platform": "京东"
    }}
  ],
  "summary": "一句话总结推荐"
}}"""


# ══════════════════════════════════════════════════════════════════════════════
# 基础标识
# ══════════════════════════════════════════════════════════════════════════════

MOBILE_CONFIG = {
    "industry": "mobile",
    "category": "手机",

    # ═══════════════════════════════════════════════════════════════════════
    # 向量化字段 — M2 使用
    # build_product_text() 拼接这些字段为一段文本后 embedding
    # ═══════════════════════════════════════════════════════════════════════

    "embedding_fields": [
        "product_name",
        "brand",
        "description",
        "use_case_tags",
        "processor",
    ],

    # ═══════════════════════════════════════════════════════════════════════
    # 规则过滤字段 — M2 使用
    # exact:   精确匹配（值必须相等）
    # range:   范围过滤（min/max 区间）
    # tag_match: 标签包含匹配（use_case_tags JSON 数组 contains）
    # ═══════════════════════════════════════════════════════════════════════

    "filter_fields": {
        "exact": ["category", "brand", "processor_brand", "performance_tier"],
        "range": ["price", "screen_size", "battery"],
        "tag_match": ["use_case_tags"],
    },

    # ═══════════════════════════════════════════════════════════════════════
    # 排序策略 — M2 使用
    # value:       性价比（性能分 / 价格）
    # price:       最低价优先
    # performance: 性能优先
    # ═══════════════════════════════════════════════════════════════════════

    "sort_strategies": {
        "value": "performance_score / price * 10000",
        "price": "-price",
        "performance": "performance_score",
    },

    # ═══════════════════════════════════════════════════════════════════════
    # 场景标签枚举 — M2/M4 使用
    # ═══════════════════════════════════════════════════════════════════════

    "use_case_taxonomy": [
        "gaming",       # 游戏
        "photography",  # 拍照
        "battery",      # 续航
        "business",     # 商务
        "student",      # 学生
        "budget",       # 性价比/入门
        "flagship",     # 旗舰
    ],

    # 性能层级映射
    "performance_tier_map": {
        "flagship": 100,
        "mid": 65,
        "budget": 35,
    },

    # ═══════════════════════════════════════════════════════════════════════
    # 处理器归一化 — M2/M5 使用
    # 用户自然语言中的关键词 → 数据库 processor_brand 字段值
    # ═══════════════════════════════════════════════════════════════════════

    "processor_normalize": {
        # 骁龙 → sd
        "骁龙": "sd",
        "高通": "sd",
        "snapdragon": "sd",
        # 天玑 → mt
        "天玑": "mt",
        "联发科": "mt",
        "dimensity": "mt",
        # 麒麟 → kirin
        "麒麟": "kirin",
        "kirin": "kirin",
        # 苹果 → apple
        "苹果": "apple",
        "apple": "apple",
        "A17": "apple",
        "A16": "apple",
        "M2": "apple",
        "M3": "apple",
    },

    # ═══════════════════════════════════════════════════════════════════════
    # 推荐维度与权重 — M4 使用
    # LLM Rerank 时作为参考维度注入 Prompt
    # ═══════════════════════════════════════════════════════════════════════

    "recommend_dimensions": [
        {"name": "性能",     "key": "performance_tier", "weight": 0.30},
        {"name": "拍照",     "key": "use_case_tags",    "weight": 0.25},
        {"name": "续航",     "key": "battery",          "weight": 0.20},
        {"name": "价格",     "key": "price",            "weight": 0.15},
        {"name": "屏幕",     "key": "screen_size",      "weight": 0.10},
    ],

    # ═══════════════════════════════════════════════════════════════════════
    # 对比维度 — M5 使用
    # 用户选择 2-3 款商品对比时，按此维度逐项比较
    # ═══════════════════════════════════════════════════════════════════════

    "compare_dimensions": [
        {"name": "性能",       "key": "performance_tier", "weight": 0.30},
        {"name": "拍照能力",   "key": "use_case_tags",    "weight": 0.25},
        {"name": "续航",       "key": "battery",          "weight": 0.20},
        {"name": "价格",       "key": "price",            "weight": 0.15},
        {"name": "屏幕尺寸",   "key": "screen_size",      "weight": 0.10},
    ],

    # ═══════════════════════════════════════════════════════════════════════
    # 购物槽位 — M5 使用
    # required=True 的关键槽位缺失时主动追问
    # max_slot_questions 控制最多追问次数
    # ═══════════════════════════════════════════════════════════════════════

    "shopping_slots": [
        {
            "name": "primary_use_case",
            "required": True,
            "question": "主要是打游戏、拍照，还是日常使用？",
            "options": ["gaming", "photography", "battery", "business", "student"],
            "extract_keywords": {
                "游戏": "gaming", "打游戏": "gaming", "电竞": "gaming",
                "拍照": "photography", "摄影": "photography", "拍视频": "photography",
                "续航": "battery", "电池": "battery", "耐用": "battery",
                "办公": "business", "商务": "business",
                "学习": "student", "上学": "student", "学生": "student",
            },
        },
        {
            "name": "budget_range",
            "required": False,
            "question": "预算大概多少呢？",
            "extract_pattern": r"(\d+)\s*[块元]|预算.*?(\d+)",
        },
        {
            "name": "brand_preference",
            "required": False,
            "question": "有偏好的品牌吗？比如 Apple、小米、华为？",
            "options": ["Apple", "小米", "华为", "OPPO", "vivo", "三星"],
            "extract_keywords": ["Apple", "小米", "华为", "OPPO", "vivo", "三星", "苹果"],
        },
        {
            "name": "processor_preference",
            "required": False,
            "question": "对处理器有要求吗？骁龙、天玑还是苹果芯片？",
            "extract_keywords": ["骁龙", "高通", "天玑", "联发科", "麒麟", "苹果", "A17", "A16", "M2", "M3"],
        },
        {
            "name": "screen_size_preference",
            "required": False,
            "question": "喜欢大屏（6.5寸以上）还是小屏？",
            "options": ["大屏", "小屏", "无所谓"],
        },
    ],
    "max_slot_questions": 3,

    # ═══════════════════════════════════════════════════════════════════════
    # 功能开关
    # ═══════════════════════════════════════════════════════════════════════

    "enable_vector_recall": True,     # M2: 向量召回已启用
    "enable_llm_rerank": False,       # M4 完成后开启
    "enable_rag": True,               # M3: RAG 知识库已启用

    # ═══════════════════════════════════════════════════════════════════════
    # 前端展示字段 — 商品卡片展示哪些字段
    # ═══════════════════════════════════════════════════════════════════════

    "product_display_fields": [
        "product_name", "brand", "price", "platform",
        "processor", "performance_tier", "battery",
        "screen_size", "description",
    ],

    # ═══════════════════════════════════════════════════════════════════════
    # Prompt 模板 — M3/M4 使用
    # decompose: LLM 意图分解（模糊需求 → 结构化条件）
    # rerank:     LLM Rerank（候选商品重排序 + 推荐理由）
    # ═══════════════════════════════════════════════════════════════════════

    "prompts": {
        "decompose": _DECOMPOSE_PROMPT,
        "rerank": _RERANK_PROMPT,
    },
}
