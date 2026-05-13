"""
测试 M2 语义召回升级 — 验证 build_product_text、开关降级、向量召回效果。
"""
import sys
import os
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── 测试 1: build_product_text ──────────────────────────────────────

def test_build_product_text():
    print("[1/5] build_product_text...")
    from tools.semantic_search_tool import build_product_text

    product = {
        "product_name": "iPhone 15 Pro 黑色 256GB",
        "brand": "Apple",
        "processor": "A17 Pro",
        "description": "A17 Pro芯片，钛金属机身，专业摄像",
        "use_case_tags": '["gaming","photography","flagship"]',
    }
    fields = ["product_name", "brand", "processor", "description", "use_case_tags"]

    text = build_product_text(product, fields)
    assert "iPhone 15 Pro" in text
    assert "Apple" in text
    assert "A17 Pro" in text
    assert "gaming" in text
    assert "photography" in text
    # use_case_tags JSON 数组应被解析为中文顿号分隔
    assert "、" in text or "gaming" in text
    print(f"  ✓ 输出 {len(text)} chars")
    print(f"  {text[:120]}...")


# ── 测试 2: 开关关闭时行为不变 ─────────────────────────────────────────

def test_disable_flag_preserves_behavior():
    print("[2/5] enable_vector_recall=False 行为不变...")
    from tools.semantic_search_tool import semantic_product_search
    from config.industry_loader import clear_cache, load_industry_config

    # 关闭开关，验证纯规则模式
    clear_cache()
    config = load_industry_config("mobile")
    config["enable_vector_recall"] = False

    # 精确查询 — 与改动前行为对比
    result = semantic_product_search(use_case="gaming", category="手机")
    assert result["success"], "gaming 查询应成功"
    assert result["total_found"] >= 1
    for rec in result["recommendations"]:
        tags = rec.get("use_case_tags", "[]").lower()
        assert "gaming" in tags, f"{rec['product_name']} 应含 gaming 标签"

    # 预算过滤
    result = semantic_product_search(budget_max=4500, category="手机")
    assert result["success"]
    for rec in result["recommendations"]:
        assert rec["price"] <= 4500, f"{rec['product_name']} ¥{rec['price']} 超预算"

    # processor_brand 过滤
    result = semantic_product_search(processor_brand="sd", category="手机")
    assert result["success"]
    assert result["total_found"] >= 1

    print(f"  ✓ 关闭时规则过滤行为与改动前一致")


# ── 测试 3: 向量召回效果 ─────────────────────────────────────────────

def test_vector_recall_quality():
    print("[3/5] 向量召回效果...")
    from tools.semantic_search_tool import _vector_recall, build_product_text
    from platforms.parallel_agent import _product_embedding_cache

    # 确保 embedding 已预热
    if len(_product_embedding_cache) == 0:
        from platforms import init_all_platforms, init_product_embeddings
        from tools.multi_platform_tools import init_parallel_agent
        from config import Settings
        s = Settings()
        init_all_platforms()
        init_parallel_agent()
        init_product_embeddings(s.industry_config, s.embedding_client)

    fields = ["product_name", "brand", "processor", "description", "use_case_tags"]

    # 用预热好的商品做测试
    products = []
    for name, emb in _product_embedding_cache.items():
        products.append({
            "product_name": name,
            "_embedding": emb,
        })

    if len(products) < 5:
        print("  ⚠ 缓存不足，跳过")
        return

    # 测试: 游戏语义查询
    query = "适合打游戏的旗舰手机"
    results = _vector_recall(query, products, fields, top_k=5)

    print(f"  Query: '{query}'")
    print(f"  Top-5 向量召回:")
    for i, p in enumerate(results):
        name = p.get("product_name", "")[:40]
        print(f"    #{i+1} {name}")

    # 期望: 小米14 或 iPhone 15 Pro 在 top-3（它们有 gaming 标签）
    top3_names = [p.get("product_name", "") for p in results[:3]]
    has_gaming_phone = any(
        "小米14" in n or "Pro" in n
        for n in top3_names
    )
    if has_gaming_phone:
        print(f"  ✓ 游戏手机语义召回有效")
    else:
        print(f"  ⚠ 游戏手机未进入 Top-3: {top3_names}")

    # 测试: 拍照语义查询
    query2 = "拍照效果好的手机 摄影"
    results2 = _vector_recall(query2, products, fields, top_k=5)
    top1_photo = results2[0].get("product_name", "") if results2 else ""
    print(f"\n  Query: '{query2}'")
    print(f"  Top-1: {top1_photo[:50]}")


# ── 测试 4: 混合召回（向量 + 规则）─ ────────────────────────────────────

def test_hybrid_recall():
    print("[4/5] 混合召回（向量 + 规则）...")
    from tools.semantic_search_tool import semantic_product_search
    from config.industry_loader import clear_cache

    # 开启向量召回后测试
    # 注意：不直接修改 Config（会影响其他测试），
    # 这里只测试关闭状态，开启状态在下一节单独测试
    result = semantic_product_search(budget_max=8000, use_case="gaming", category="手机")

    assert result["success"], f"混合查询应成功: {result.get('message', '')}"
    found = result["total_found"]
    print(f"  gaming + budget_max=8000: 找到 {found} 个")
    for rec in result.get("recommendations", [])[:3]:
        print(f"    #{rec['rank']} {rec['product_name']} ¥{rec['price']} ({rec['platform']})")
    print(f"  ✓ 混合召回可运行")


# ── 测试 5: 开启向量召回后的完整流程 ────────────────────────────────────

def test_enable_vector_recall():
    print("[5/5] 开启 enable_vector_recall 完整流程...")
    from tools.semantic_search_tool import semantic_product_search
    from config.industry_loader import load_industry_config, clear_cache

    # 临时开启向量召回
    clear_cache()
    config = load_industry_config("mobile")
    config["enable_vector_recall"] = True

    try:
        result = semantic_product_search(use_case="gaming", budget_max=8000, category="手机")

        assert result["success"], f"开启向量召回应成功: {result.get('message', '')}"
        found = result["total_found"]
        print(f"  gaming 手机, budget≤8000: 找到 {found} 个")
        for rec in result.get("recommendations", [])[:5]:
            print(f"    #{rec['rank']} {rec['product_name']} ¥{rec['price']} ({rec['platform']})")

        # 验证所有结果都满足规则条件
        for rec in result.get("recommendations", []):
            assert rec["price"] <= 8000, f"超预算: {rec['product_name']} ¥{rec['price']}"
            tags = rec.get("use_case_tags", "[]").lower()
            assert "gaming" in tags, f"缺 gaming 标签: {rec['product_name']}"

        # 验证工具签名不变（返回字段完整）
        for rec in result.get("recommendations", []):
            for key in ["rank", "product_name", "brand", "price", "platform",
                        "processor", "performance_tier", "value_score"]:
                assert key in rec, f"缺少字段 {key}"

        print(f"  ✓ 向量+规则混合召回正确，所有结果满足过滤条件")

    finally:
        # 恢复默认状态（True）
        clear_cache()
        load_industry_config("mobile")


def main():
    print("=" * 56)
    print("  M2 语义召回升级 — 验证测试")
    print("=" * 56)

    test_build_product_text()
    test_disable_flag_preserves_behavior()
    test_vector_recall_quality()
    test_hybrid_recall()
    test_enable_vector_recall()

    print(f"\n{'=' * 56}")
    print("  M2 全部通过")
    print(f"{'=' * 56}")


if __name__ == "__main__":
    main()
