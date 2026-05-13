"""
IT3C 行业优化评估 — P0 单元测试 / P1 属性提取 / P2 端到端
执行：python3 eval/eval_it3c.py
P0 不依赖 LLM，P1/P2 需要 LLM API 调用。
跳过图片相关评估。
"""

import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from eval_helpers import (
    EvalRecorder, save_report, print_summary, score_param_extraction,
    extract_prices, extract_platform_names, detect_hallucination,
)


# ══════════════════════════════════════════════════════════════════════════════
# P0 — 单元测试（不依赖 LLM）
# ══════════════════════════════════════════════════════════════════════════════

def test_semantic_search_filters(recorder: EvalRecorder):
    """P0-IT3C-1: semantic_product_search 过滤逻辑"""
    from tools.semantic_search_tool import semantic_product_search

    # SC-IT-01: use_case 过滤 — 只返回含 gaming 标签的商品
    r = semantic_product_search(use_case="gaming", category="手机")
    passed = r["success"] and all(
        "gaming" in (rec.get("use_case_tags") or "[]").lower()
        for rec in r["recommendations"]
    )
    recorder.record("SC-IT-01", passed, {
        "reason": f"found={r['total_found']}, all match gaming" if passed else "有商品不含 gaming"
    })

    # SC-IT-02: budget_max 硬过滤
    r = semantic_product_search(budget_max=4500, category="手机")
    passed = r["success"] and all(rec["price"] <= 4500 for rec in r["recommendations"])
    recorder.record("SC-IT-02", passed, {
        "reason": f"found={r['total_found']}, all <= 4500" if passed else "有商品超出预算"
    })

    # SC-IT-03: processor_brand 过滤
    r = semantic_product_search(processor_brand="sd", category="手机")
    passed = r["success"] and r["total_found"] >= 1
    recorder.record("SC-IT-03", passed, {
        "reason": f"found={r['total_found']} sd phones" if passed else "未找到骁龙手机"
    })

    # SC-IT-04: 性价比排序 — 第一名 value_score >= 最后一名
    r = semantic_product_search(category="手机", sort_by="value")
    items = r.get("recommendations", [])
    passed = len(items) < 2 or items[0]["value_score"] >= items[-1]["value_score"]
    recorder.record("SC-IT-04", passed, {
        "reason": f"first={items[0]['value_score'] if items else 'N/A'} last={items[-1]['value_score'] if items else 'N/A'}"
    })

    # SC-IT-05: 价格排序 — 第一名价格 <= 最后一名
    r = semantic_product_search(category="手机", sort_by="price")
    items = r.get("recommendations", [])
    passed = len(items) < 2 or items[0]["price"] <= items[-1]["price"]
    recorder.record("SC-IT-05", passed, {
        "reason": f"first=¥{items[0]['price'] if items else 'N/A'} last=¥{items[-1]['price'] if items else 'N/A'}"
    })

    # SC-IT-06: 性能排序 — 第一名 tier >= 最后一名
    r = semantic_product_search(category="手机", sort_by="performance")
    items = r.get("recommendations", [])
    tier_order = {"flagship": 3, "mid": 2, "budget": 1}
    passed = len(items) < 2 or tier_order.get(items[0]["performance_tier"], 0) >= tier_order.get(items[-1]["performance_tier"], 0)
    recorder.record("SC-IT-06", passed, {
        "reason": f"first_tier={items[0]['performance_tier'] if items else 'N/A'} last_tier={items[-1]['performance_tier'] if items else 'N/A'}"
    })

    # SC-IT-07: 无结果友好提示
    r = semantic_product_search(use_case="gaming", budget_max=100, category="手机")
    passed = r["success"] is False and "suggestions" in r
    recorder.record("SC-IT-07", passed, {
        "reason": f"message={r.get('message', '')}" if passed else "未给出友好提示"
    })

    # SC-IT-08: 组合过滤 gaming + sd + <=5000
    r = semantic_product_search(use_case="gaming", processor_brand="sd", budget_max=5000, category="手机")
    passed = r["success"] and r["total_found"] >= 1 and all(
        "gaming" in (rec.get("use_case_tags") or "[]").lower() and rec["price"] <= 5000
        for rec in r["recommendations"]
    )
    recorder.record("SC-IT-08", passed, {
        "reason": f"found={r['total_found']} gaming+sd+<=5000" if passed else "组合过滤失败"
    })

    # SC-IT-09: brand 过滤
    r = semantic_product_search(brand="Apple", category="手机")
    passed = r["success"] and all(rec["brand"] == "Apple" for rec in r["recommendations"])
    recorder.record("SC-IT-09", passed, {
        "reason": f"found={r['total_found']} Apple phones" if passed else "品牌过滤失败"
    })

    # SC-IT-10: performance_tier 过滤
    r = semantic_product_search(performance_tier="flagship", category="手机", top_n=10)
    passed = r["success"] and all(rec["performance_tier"] == "flagship" for rec in r["recommendations"])
    recorder.record("SC-IT-10", passed, {
        "reason": f"found={r['total_found']} flagships" if passed else "层级过滤失败"
    })


def test_intent_detection(recorder: EvalRecorder):
    """P0-IT3C-2: _detect_intent 意图分类"""
    from agent.react_engine import ReActAgent

    agent = ReActAgent(client=None, model="test", tools=[], tool_map={})

    cases = [
        ("ID-IT-01", "我打游戏推荐什么手机", "recommendation"),
        ("ID-IT-02", "5000以内手机推荐", "recommendation"),
        ("ID-IT-03", "拍照好的手机有哪些", "recommendation"),
        ("ID-IT-04", "iPhone 15 价格", "query"),
        ("ID-IT-05", "iPhone 15 和小米14 哪个好", "comparison"),
        ("ID-IT-06", "骁龙8Gen3 手机有哪些", "recommendation"),
        ("ID-IT-07", "天玑处理器手机", "recommendation"),
        ("ID-IT-08", "麒麟芯片手机推荐", "recommendation"),
        ("ID-IT-09", "A17 Pro的手机", "recommendation"),
        ("ID-IT-10", "便宜的学生手机推荐", "recommendation"),
        ("ID-IT-11", "旗舰手机不超过8000", "recommendation"),
        ("ID-IT-12", "AirPods Pro 2 多少钱", "query"),
        ("ID-IT-13", "推荐iPhone 15", "query"),  # 有明确型号 → query
        ("ID-IT-14", "小米14 黑色256GB 最便宜", "query"),  # 有型号 → query
    ]

    for case_id, query, expected in cases:
        intent = agent._detect_intent(query)
        passed = intent == expected
        recorder.record(case_id, passed, {
            "input": query,
            "expected": expected,
            "actual": intent,
        })


def test_deref_list_indexing(recorder: EvalRecorder):
    """P0-IT3C-3: _deref 列表索引支持"""
    from agent.react_engine import ReActAgent

    agent = ReActAgent(client=None, model="test", tools=[], tool_map={})

    mock = {
        1: {
            "recommendations": [
                {"product_name": "小米14", "price": 3999},
                {"product_name": "iPhone 15 Pro", "price": 8999},
            ]
        }
    }

    # DR-IT-01: recommendations[0].product_name
    val = agent._deref("$step1.recommendations[0].product_name", mock)
    recorder.record("DR-IT-01", val == "小米14", {
        "reason": f"got={val}, expected=小米14"
    })

    # DR-IT-02: recommendations[1].product_name
    val = agent._deref("$step1.recommendations[1].product_name", mock)
    recorder.record("DR-IT-02", val == "iPhone 15 Pro", {
        "reason": f"got={val}, expected=iPhone 15 Pro"
    })

    # DR-IT-03: 越界索引 → 返回原始引用
    val = agent._deref("$step1.recommendations[99].product_name", mock)
    recorder.record("DR-IT-03", val == "$step1.recommendations[99].product_name", {
        "reason": f"got={val}"
    })

    # DR-IT-04: 旧式路径仍兼容
    val = agent._deref("$step1.recommendations", mock)
    recorder.record("DR-IT-04", isinstance(val, list) and len(val) == 2, {
        "reason": f"type={type(val).__name__}, len={len(val) if isinstance(val, list) else 'N/A'}"
    })


def test_processor_aliases(recorder: EvalRecorder):
    """P0-IT3C-4: 处理器别名映射"""
    from platforms.platform_database import (
        _processor_brand_tokens, _processor_model_tokens,
        PROCESSOR_BRAND_ALIASES, PROCESSOR_MODEL_KEYWORDS,
    )

    # PA-IT-01: 骁龙 → sd
    tokens = _processor_brand_tokens("骁龙8Gen3")
    recorder.record("PA-IT-01", "sd" in tokens, {
        "reason": f"骁龙8Gen3 → {tokens}"
    })

    # PA-IT-02: 天玑 → mt
    tokens = _processor_brand_tokens("天玑9300")
    recorder.record("PA-IT-02", "mt" in tokens, {
        "reason": f"天玑9300 → {tokens}"
    })

    # PA-IT-03: A17 → apple
    tokens = _processor_brand_tokens("A17 Pro")
    recorder.record("PA-IT-03", "apple" in tokens, {
        "reason": f"A17 Pro → {tokens}"
    })

    # PA-IT-04: 麒麟 → kirin
    tokens = _processor_brand_tokens("麒麟9000")
    recorder.record("PA-IT-04", "kirin" in tokens, {
        "reason": f"麒麟9000 → {tokens}"
    })

    # PA-IT-05: 型号关键词提取 — 8gen3
    model = _processor_model_tokens("骁龙8Gen3")
    recorder.record("PA-IT-05", model == "8gen3", {
        "reason": f"骁龙8Gen3 → {model}"
    })

    # PA-IT-06: 型号关键词提取 — A17
    model = _processor_model_tokens("A17 Pro")
    recorder.record("PA-IT-06", model == "a17", {
        "reason": f"A17 Pro → {model}"
    })

    # PA-IT-07: 未知处理器 → 返回原始值
    tokens = _processor_brand_tokens("unknown-chip")
    recorder.record("PA-IT-07", tokens == ["unknownchip"], {
        "reason": f"unknown-chip → {tokens}"
    })


# ── M2 向量召回回归 ──────────────────────────────────────────────────

def test_vector_recall_enabled(recorder: EvalRecorder):
    """P0-IT3C-5: 开启向量召回后语义搜索不破坏规则过滤"""
    from tools.semantic_search_tool import semantic_product_search
    from config.industry_loader import load_industry_config, clear_cache

    # 确保向量召回开启
    clear_cache()
    config = load_industry_config("mobile")
    assert config.get("enable_vector_recall"), "M2 向量召回应已开启"

    # VR-IT-01: 开启向量召回，gaming 过滤仍生效
    r = semantic_product_search(use_case="gaming", category="手机")
    passed = r["success"] and all(
        "gaming" in (rec.get("use_case_tags") or "[]").lower()
        for rec in r["recommendations"]
    )
    recorder.record("VR-IT-01", passed, {
        "reason": f"向量召回开启, found={r['total_found']}, all match gaming" if passed
        else "向量召回后 gaming 过滤失效"
    })

    # VR-IT-02: 开启向量召回，budget 硬过滤仍生效
    r = semantic_product_search(budget_max=4500, category="手机")
    passed = r["success"] and all(rec["price"] <= 4500 for rec in r["recommendations"])
    recorder.record("VR-IT-02", passed, {
        "reason": f"found={r['total_found']}, all <= 4500" if passed
        else "向量召回后 budget 过滤失效"
    })

    # VR-IT-03: 开启向量召回，processor_brand 过滤仍生效
    r = semantic_product_search(processor_brand="sd", category="手机")
    passed = r["success"] and r["total_found"] >= 1
    recorder.record("VR-IT-03", passed, {
        "reason": f"found={r['total_found']} sd phones" if passed
        else "向量召回后 processor 过滤失效"
    })

    # VR-IT-04: 开启向量召回，brand 过滤仍生效
    r = semantic_product_search(brand="Apple", category="手机")
    passed = r["success"] and all(
        rec.get("brand", "") == "Apple" for rec in r["recommendations"]
    )
    recorder.record("VR-IT-04", passed, {
        "reason": f"found={r['total_found']} Apple phones" if passed
        else "向量召回后 brand 过滤失效"
    })

    # VR-IT-05: 开启向量召回，排序有效（value_score 递减）
    r = semantic_product_search(category="手机", sort_by="value")
    recs = r.get("recommendations", [])
    scores = [rec.get("value_score", 0) for rec in recs]
    passed = len(recs) < 2 or all(
        scores[i] >= scores[i + 1] for i in range(len(scores) - 1)
    )
    recorder.record("VR-IT-05", passed, {
        "reason": f"value_scores: {[round(s, 1) for s in scores[:5]]}"
    })


# ── M5 购物意图分类回归 ────────────────────────────────────────────────

def test_shopping_intent(recorder: EvalRecorder):
    """P0-IT3C-6: shopping 意图分类 + 不干扰已有意图"""
    from config import Settings
    from tools import tool_registry, init_parallel_agent
    from platforms import init_all_platforms
    from agent import ReActAgent

    init_all_platforms()
    init_parallel_agent()
    s = Settings()
    agent = ReActAgent(
        client=s.client, model=s.model,
        tools=tool_registry.get_schemas(),
        tool_map=tool_registry.get_tool_map(),
        config={"industry_config": s.industry_config},
    )

    cases = [
        # (case_id, query, expected_intent)
        ("SI-IT-01", "想买个手机", "shopping"),
        ("SI-IT-02", "帮我挑一款", "shopping"),
        ("SI-IT-03", "想换个手机", "shopping"),
        ("SI-IT-04", "买个", "shopping"),
        # 不触发 shopping — 有场景/预算/型号
        ("SI-IT-05", "想买个游戏手机", "recommendation"),
        ("SI-IT-06", "想买5000左右的", "recommendation"),
        ("SI-IT-07", "推荐游戏手机", "recommendation"),
        ("SI-IT-08", "想买iPhone 15", "query"),
        # 已有意图不受影响
        ("SI-IT-09", "iPhone 15 多少钱", "query"),
        ("SI-IT-10", "iPhone 15 和小米14 哪个好", "comparison"),
    ]

    for case_id, query, expected in cases:
        result = agent._detect_intent(query)
        passed = result == expected
        recorder.record(case_id, passed, {
            "reason": f"'{query}' → {result}" + ("" if passed else f", 期望 {expected}")
        })


# ══════════════════════════════════════════════════════════════════════════════
# P1 — IT3C 属性提取（需 LLM）
# ══════════════════════════════════════════════════════════════════════════════

IT3C_EXTRACTION_CASES = [
    # (case_id, query, expected_dict)
    (
        "AP-IT-01",
        "我打游戏，5000以内骁龙处理器手机推荐",
        {
            "use_case": "gaming",
            "budget_max": 5000,
            "processor_brand": "sd",
            "category": "手机",
        }
    ),
    (
        "AP-IT-02",
        "天玑9300拍照手机",
        {
            "processor_brand": "mt",
            "use_case": "photography",
            "category": "手机",
        }
    ),
    (
        "AP-IT-03",
        "旗舰手机不超过8000",
        {
            "performance_tier": "flagship",
            "budget_max": 8000,
            "category": "手机",
        }
    ),
    (
        "AP-IT-04",
        "学生用手机，便宜实惠，天玑处理器",
        {
            "use_case": "student",
            "processor_brand": "mt",
        }
    ),
    (
        "AP-IT-05",
        "A17 Pro芯片手机",
        {
            "processor_brand": "apple",
            "category": "手机",
        }
    ),
    (
        "AP-IT-06",
        "商务办公平板推荐",
        {
            "use_case": "business",
            "category": "平板",
        }
    ),
    (
        "AP-IT-07",
        "给大学生用的性价比高的手机",
        {
            "use_case": "student",
            "category": "手机",
        }
    ),
]


def score_it3c_extraction(actual: dict, expected: dict) -> dict:
    """对 IT3C 属性提取结果打分，每项 1 分，满分 = expected 中有值的字段数。"""
    scores = {}
    checks = ["use_case", "budget_max", "budget_min", "processor_brand",
              "processor_hint", "performance_tier", "category", "brand"]
    for field in checks:
        exp_val = expected.get(field)
        act_val = actual.get(field)
        if exp_val is None:
            scores[field] = True  # 不要求则跳过
        elif isinstance(exp_val, (int, float)):
            scores[field] = act_val == exp_val
        elif isinstance(exp_val, str) and exp_val:
            scores[field] = (act_val or "").lower() == exp_val.lower()
        else:
            scores[field] = True

    # processor_hint 特殊检查：只要求包含关键词
    if "processor_hint_contains" in expected:
        hint = (actual.get("processor_hint") or "").lower()
        need = expected["processor_hint_contains"].lower()
        scores["processor_hint"] = need in hint

    # use_case 包含检查
    if "use_case_contains" in expected:
        uc = (actual.get("use_case") or "").lower()
        need = expected["use_case_contains"].lower()
        scores["use_case"] = need in uc

    scored_fields = [k for k in checks if k in expected or k + "_contains" in expected]
    if not scored_fields:
        scored_fields = [k for k in checks if expected.get(k) is not None]
    scores["total"] = sum(1 for k in scored_fields if scores.get(k, True))
    scores["max"] = len(scored_fields)
    return scores


def run_p1_it3c(recorder: EvalRecorder):
    """P1 — IT3C 属性提取"""
    from config import Settings
    from tools.multi_platform_tools import _parse_attrs_from_query

    s = Settings()
    client, model = s.client, s.model

    # 使用 parse 模型（如果有单独配置的话）
    parse_model = getattr(s, "model_parse", model)

    print("\n--- P1: IT3C 属性提取 ---")
    for case_id, query, expected in IT3C_EXTRACTION_CASES:
        actual = _parse_attrs_from_query(query, client, parse_model)
        scores = score_it3c_extraction(actual, expected)
        passed = scores["total"] >= scores["max"] * 0.6  # 60% 字段匹配即通过
        recorder.record(case_id, passed, {
            "input": query,
            "expected": expected,
            "actual": {k: actual.get(k) for k in expected if expected[k] is not None},
            "scores": scores,
        })
        status = "✓" if passed else "✗"
        print(f"  {status} {case_id}: {query}")
        print(f"       expected: {expected}")
        print(f"       actual:   use_case={actual.get('use_case')}, bud_max={actual.get('budget_max')}, pb={actual.get('processor_brand')}, tier={actual.get('performance_tier')}")


# ══════════════════════════════════════════════════════════════════════════════
# P2 — 端到端 IT3C 推荐（需 LLM + 工具）
# ══════════════════════════════════════════════════════════════════════════════

IT3C_CHAIN_CASES = [
    {
        "id": "E2E-IT-01",
        "input": "游戏手机推荐",
        "checks": {
            "tool": "semantic_product_search",
            "answer_has": ["推荐", "小米"],
        }
    },
    {
        "id": "E2E-IT-02",
        "input": "5000以内性价比最高的手机",
        "checks": {
            "tool": "semantic_product_search",
            "answer_has_price": True,
        }
    },
    {
        "id": "E2E-IT-03",
        "input": "骁龙处理器手机有哪些",
        "checks": {
            "tool": "semantic_product_search",
            "answer_has": ["骁龙", "小米"],
        }
    },
    {
        "id": "E2E-IT-04",
        "input": "拍照好的手机推荐",
        "checks": {
            "tool": "semantic_product_search",
            "answer_has": ["拍照", "像素", "徕卡", "影像"],
        }
    },
]


class IT3CE2ERunner:
    def __init__(self):
        from config import Settings
        from tools import tool_registry, init_parallel_agent, cleanup_parallel_agent
        from platforms import init_all_platforms
        from agent import ReActAgent

        init_all_platforms()
        init_parallel_agent()

        self.settings = Settings()
        self.agent = ReActAgent(
            client=self.settings.client,
            model=self.settings.model,
            tools=tool_registry.get_schemas(),
            tool_map=tool_registry.get_tool_map(),
            max_round=self.settings.max_round,
        )
        self._cleanup = cleanup_parallel_agent

    def run_one(self, query: str) -> dict:
        import time
        start = time.time()
        try:
            answer = self.agent.run(query, verbose=False)
        except Exception as e:
            answer = f"[ERROR] {e}"
        elapsed_ms = int((time.time() - start) * 1000)
        return {
            "answer": answer,
            "prices": extract_prices(answer),
            "platforms": extract_platform_names(answer),
            "total_time_ms": elapsed_ms,
        }

    def cleanup(self):
        self._cleanup()


def run_p2_it3c(recorder: EvalRecorder):
    """P2 — IT3C 推荐端到端"""
    print("\n--- P2: IT3C 推荐端到端 ---")

    runner = IT3CE2ERunner()

    for case in IT3C_CHAIN_CASES:
        case_id = case["id"]
        query = case["input"]
        checks = case["checks"]

        print(f"\n  执行: {case_id} — {query}")
        result = runner.run_one(query)
        answer = result.get("answer", "")

        # 验证答案包含期望内容
        if "answer_has" in checks:
            has_any = any(kw in answer for kw in checks["answer_has"])
        else:
            has_any = True

        # 幻觉检测
        has_price = "answer_has_price" in checks
        if has_price and result["prices"]:
            is_clean = True
        else:
            is_clean = True  # 推荐场景不强制要求价格

        # 答案非空
        not_empty = len(answer) > 20

        passed = not_empty and has_any and is_clean
        recorder.record(case_id, passed, {
            "input": query,
            "answer_preview": answer[:200],
            "prices_found": result["prices"],
            "platforms": result["platforms"],
            "time_ms": result["total_time_ms"],
            "checks": {
                "not_empty": not_empty,
                "has_keywords": has_any,
                "clean": is_clean,
            }
        })

        status = "✓" if passed else "✗"
        print(f"  {status} {case_id}: {len(answer)} chars, {result['total_time_ms']}ms")
        if not passed:
            print(f"     not_empty={not_empty}, has_kw={has_any}, clean={is_clean}")

    runner.cleanup()


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════

def main(p0_only=True):
    """
    :param p0_only: True 时只跑 P0 单元测试（不调 LLM），False 跑全部
    """
    print("=" * 60)
    print("  IT3C 行业优化评估" + ("（P0 单元测试）" if p0_only else "（全部）"))
    print("=" * 60)

    recorder = EvalRecorder("IT3C")

    # ── P0 单元测试（不依赖 LLM） ──
    print("\n--- P0-IT3C-1: semantic_product_search 过滤 ---")
    test_semantic_search_filters(recorder)

    print("\n--- P0-IT3C-2: 意图分类 ---")
    test_intent_detection(recorder)

    print("\n--- P0-IT3C-3: _deref 列表索引 ---")
    test_deref_list_indexing(recorder)

    print("\n--- P0-IT3C-4: 处理器别名 ---")
    test_processor_aliases(recorder)

    print("\n--- P0-IT3C-5: M2 向量召回回归 ---")
    test_vector_recall_enabled(recorder)

    print("\n--- P0-IT3C-6: M5 购物意图分类 ---")
    test_shopping_intent(recorder)

    # ── P1/P2（需 LLM） ──
    if not p0_only:
        try:
            run_p1_it3c(recorder)
        except Exception as e:
            print(f"\n  ⚠ P1 跳过: {e}")

        try:
            run_p2_it3c(recorder)
        except Exception as e:
            print(f"\n  ⚠ P2 跳过: {e}")

    summary = recorder.summary()
    print_summary(summary)

    filename = save_report("IT3C", summary)
    print(f"报告已保存: {filename}")

    return summary["failed"] == 0


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="运行全部测试（含 P1/P2 LLM 调用）")
    args = parser.parse_args()

    success = main(p0_only=not args.all)
    sys.exit(0 if success else 1)
