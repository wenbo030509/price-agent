"""
测试 M1 行业配置框架 — 加载、默认值、Schema、注入链路。
"""
import sys


def test_load_default():
    """Config 加载 + 默认值补齐"""
    print("[1/7] Config 加载与默认值补齐...")
    from config import load_industry_config, clear_cache
    clear_cache()
    config = load_industry_config("mobile")

    checks = [
        ("industry", "mobile"),
        ("category", "手机"),
        ("max_slot_questions", 3),
        ("enable_vector_recall", True),    # M2 已开启
        ("enable_llm_rerank", False),
        ("enable_rag", True),             # M3 已开启
    ]
    for key, expected in checks:
        actual = config.get(key)
        assert actual == expected, f"{key}: {actual} != {expected}"

    print(f"  ✓ 加载成功，{len(config)} 个字段")


def test_embedding_fields():
    """向量化字段配置"""
    print("[2/7] embedding_fields 配置...")
    from config import load_industry_config
    config = load_industry_config("mobile")

    fields = config.get("embedding_fields", [])
    assert len(fields) >= 3, f"至少 3 个字段，实际 {len(fields)}"
    assert "product_name" in fields, "须包含 product_name"
    assert "description" in fields, "须包含 description"
    print(f"  ✓ {fields}")


def test_filter_fields():
    """规则过滤字段配置"""
    print("[3/7] filter_fields 配置...")
    from config import load_industry_config
    config = load_industry_config("mobile")

    filters = config.get("filter_fields", {})
    assert "exact" in filters, "缺少 exact 分组"
    assert "range" in filters, "缺少 range 分组"
    assert "tag_match" in filters, "缺少 tag_match 分组"
    assert len(filters["exact"]) >= 2, f"exact 至少 2 个字段"
    assert len(filters["range"]) >= 1, f"range 至少 1 个字段"
    print(f"  ✓ exact={filters['exact']}, range={filters['range']}, tag_match={filters['tag_match']}")


def test_taxonomy():
    """枚举值体系"""
    print("[4/7] 枚举值体系...")
    from config import load_industry_config
    config = load_industry_config("mobile")

    taxonomy = config.get("use_case_taxonomy", [])
    assert len(taxonomy) >= 5, f"至少 5 个标签，实际 {len(taxonomy)}"

    tier_map = config.get("performance_tier_map", {})
    assert tier_map.get("flagship") == 100
    assert tier_map.get("mid") == 65
    assert tier_map.get("budget") == 35

    proc_norm = config.get("processor_normalize", {})
    assert proc_norm.get("骁龙") == "sd"
    assert proc_norm.get("A17") == "apple"
    print(f"  ✓ 场景标签 {len(taxonomy)} 个, 性能层级 {len(tier_map)}, 处理器映射 {len(proc_norm)}")


def test_shopping_slots():
    """购物槽位配置"""
    print("[5/7] 购物槽位配置...")
    from config import load_industry_config
    config = load_industry_config("mobile")

    slots = config.get("shopping_slots", [])
    assert len(slots) >= 3, f"至少 3 个槽位，实际 {len(slots)}"

    # 检查必填槽位
    required = [s for s in slots if s.get("required")]
    assert len(required) >= 1, "至少 1 个必填槽位"
    assert required[0]["name"] == "primary_use_case", "第一个必填槽位应为 primary_use_case"

    # 每个槽位有 question
    for s in slots:
        assert s.get("question"), f"槽位 {s['name']} 缺少 question"

    print(f"  ✓ {len(slots)} 个槽位, 必填: {[s['name'] for s in required]}")


def test_prompts():
    """Prompt 模板"""
    print("[6/7] Prompt 模板...")
    from config import load_industry_config
    config = load_industry_config("mobile")

    prompts = config.get("prompts", {})
    assert "decompose" in prompts, "缺少 decompose prompt"
    assert "rerank" in prompts, "缺少 rerank prompt"

    # 验证占位符
    decompose = prompts["decompose"]
    assert "{query}" in decompose, "decompose 须包含 {query}"

    rerank = prompts["rerank"]
    assert "{query}" in rerank, "rerank 须包含 {query}"
    assert "{candidates}" in rerank, "rerank 须包含 {candidates}"

    # 验证 format 可执行
    try:
        decompose.format(query="测试")
        rerank.format(query="测试", candidates="候选")
    except KeyError as e:
        assert False, f"format 失败: {e}"

    print(f"  ✓ decompose={len(decompose)} chars, rerank={len(rerank)} chars")


def test_settings_injection():
    """Settings → Agent 注入链路"""
    print("[7/7] Settings 注入链路...")
    from config import Settings

    settings = Settings()
    assert settings.industry == "mobile"
    assert settings.industry_config is not None
    assert len(settings.industry_config) > 0

    # 验证关键字段可达
    cfg = settings.industry_config
    assert cfg["industry"] == "mobile"
    assert cfg["category"] == "手机"
    assert cfg["embedding_fields"] is not None

    print(f"  ✓ Settings.industry={settings.industry}")
    print(f"  ✓ Settings.industry_config 包含 {len(cfg)} 个字段")


def test_fallback():
    """不存在的行业回退到默认值"""
    print("\n--- 附加: 不存在的行业 ---")
    from config import load_industry_config, clear_cache
    clear_cache()
    config = load_industry_config("nonexistent")
    assert config["category"] == "", "未知行业 category 应为空"
    assert config["max_slot_questions"] == 3, "应使用默认值"
    assert config["enable_vector_recall"] is False
    print("  ✓ 未知行业正确回退到默认值")


def main():
    print("=" * 56)
    print("  M1 行业配置框架 — 验证测试")
    print("=" * 56)

    test_load_default()
    test_embedding_fields()
    test_filter_fields()
    test_taxonomy()
    test_shopping_slots()
    test_prompts()
    test_settings_injection()
    test_fallback()

    print(f"\n{'=' * 56}")
    print("  M1 全部通过")
    print(f"{'=' * 56}")


if __name__ == "__main__":
    main()
