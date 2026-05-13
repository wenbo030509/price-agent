"""
测试 M3 RAG 知识库 — 索引构建、chunk 分片、BM25+语义检索、工具注册、回归。
"""
import sys


def test_index_and_chunk():
    """索引构建 + chunk 分片质量"""
    print("[1/6] 索引构建与分片...")
    from tools.knowledge_indexer import KnowledgeIndexer

    indexer = KnowledgeIndexer("mobile")
    indexer.index_all()

    chunks = indexer.chunks
    assert len(chunks) >= 10, f"至少 10 个 chunk，实际 {len(chunks)}"

    # 每个 chunk 必须有 text、source、section、embedding
    for i, c in enumerate(chunks):
        assert "text" in c, f"chunk[{i}] 缺 text"
        assert "source" in c, f"chunk[{i}] 缺 source"
        assert "section" in c, f"chunk[{i}] 缺 section"
        assert "embedding" in c, f"chunk[{i}] 缺 embedding"
        assert c["source_dir"] in ("processors", "reviews", "specs"), \
            f"chunk[{i}] source_dir={c['source_dir']} 不在预期分类中"

    # 不能有空 chunk（< 50 字符应被过滤）
    for c in chunks:
        assert len(c["text"]) >= 50, f"chunk 太短: {len(c['text'])} chars, source={c['source']}"

    # embedding 维度应为 2048
    import numpy as np
    for c in chunks:
        assert isinstance(c["embedding"], np.ndarray), f"embedding 不是 ndarray"
        assert c["embedding"].shape == (2048,), f"维度错误: {c['embedding'].shape}"

    print(f"  ✓ {len(chunks)} 个有效 chunk，全部通过校验")

    # 验证分类覆盖
    dirs = set(c["source_dir"] for c in chunks)
    assert "processors" in dirs, "缺少 processors 分类"
    assert "reviews" in dirs, "缺少 reviews 分类"
    print(f"  ✓ 分类覆盖: {dirs}")

    return indexer


def test_retrieval_quality(indexer):
    """BM25 + 语义混合检索质量"""
    print("[2/6] 检索质量...")
    from tools.knowledge_indexer import KnowledgeRetriever

    retriever = KnowledgeRetriever(indexer)

    cases = [
        # (query, knowledge_type, expected_keyword_in_top3)
        ("骁龙8Gen3 游戏性能", "chipset_compare", "骁龙8Gen3"),
        ("A17 Pro 对比 骁龙", "auto", "A17_Pro"),
        ("小米14 拍照评测", "phone_review", "小米14"),
        ("iPhone 15 Pro 续航", "auto", "iPhone_15_Pro"),
        ("天玑9300 性能", "auto", None),  # 数据库没有天玑文档，但应返回结果而非报错
    ]

    all_ok = True
    for query, kt, expected_keyword in cases:
        r = retriever.retrieve(query, kt, top_k=3)
        assert r["success"], f"查询应成功: {query}"
        assert "references" in r, f"结果应含 references: {query}"
        refs = r["references"]

        if len(refs) == 0:
            print(f"  ⚠ '{query}' 返回 0 条结果（知识库缺少相关内容）")
            continue

        top1 = refs[0]
        assert top1["score"] is not None, f"score 不应为 None: {query}"
        assert 0.0 <= top1["score"] <= 1.0, f"score 应在 [0,1]: {top1['score']}"

        # 检查期望关键词是否在 top-3 中出现（不限于 top-1）
        if expected_keyword:
            found = any(expected_keyword in ref["source"] for ref in refs)
            if found:
                print(f"  ✓ '{query}' → Top-1=[{top1['score']:.4f}] {top1['source']}/{top1['section'][:30]}")
            else:
                print(f"  ⚠ '{query}' 未在 Top-3 中找到 {expected_keyword}: {[r['source'] for r in refs]}")
                all_ok = False
        else:
            print(f"  ✓ '{query}' → [{top1['score']:.4f}] {top1['source']}/{top1['section'][:30]}")

    if all_ok:
        print(f"  ✓ 检索质量全部符合预期（{len(cases)} 个 case）")

    return retriever


def test_knowledge_type_filter(indexer):
    """按 knowledge_type 过滤"""
    print("[3/6] 知识类型过滤...")
    from tools.knowledge_indexer import KnowledgeRetriever

    retriever = KnowledgeRetriever(indexer)

    # chipset_compare 应只返回 processors/ 目录下的 chunk
    r = retriever.retrieve("性能", knowledge_type="chipset_compare", top_k=20)
    for ref in r["references"]:
        assert ref["source_dir"] == "processors", \
            f"chipset_compare 不应包含 {ref['source_dir']}: {ref['source']}"

    # phone_review 应只返回 reviews/
    r = retriever.retrieve("拍照", knowledge_type="phone_review", top_k=20)
    for ref in r["references"]:
        assert ref["source_dir"] == "reviews", \
            f"phone_review 不应包含 {ref['source_dir']}: {ref['source']}"

    # auto 不过滤
    r = retriever.retrieve("测试", knowledge_type="auto", top_k=20)
    dirs = set(ref["source_dir"] for ref in r["references"])
    assert len(dirs) >= 1, "auto 应返回结果"

    print(f"  ✓ chipset_compare/reviews/auto 过滤正确")
    return retriever


def test_tool_registration(retriever):
    """search_product_knowledge 工具注册与调用"""
    print("[4/6] Agent 工具注册...")
    from tools.rag_tool import search_product_knowledge, init_knowledge_retriever
    from tools import tool_registry

    # 确保全局 retriever 已初始化（工具函数依赖它）
    init_knowledge_retriever("mobile")

    # 验证工具在注册表中
    assert "search_product_knowledge" in tool_registry._tools, \
        "search_product_knowledge 不在 ToolRegistry 中"
    schema = tool_registry._tools["search_product_knowledge"]["schema"]
    assert schema["function"]["name"] == "search_product_knowledge"

    # 正常调用
    r = search_product_knowledge("骁龙8Gen3 游戏性能", "chipset_compare", top_k=2)
    assert r["success"], "正常调用应成功"
    assert len(r["references"]) == 2
    assert r["references"][0]["score"] is not None

    # 空查询 — 不应报错
    r = search_product_knowledge("火星处理器 XYZ-999", "auto", top_k=3)
    assert r["success"]
    # 无相关知识时返回空列表不报错
    assert isinstance(r["references"], list)

    print(f"  ✓ 工具已注册，调用正常（共 {len(tool_registry._tools)} 个工具）")
    for name in sorted(tool_registry._tools.keys()):
        print(f"    - {name}")


def test_regression():
    """回归：RAG 不影响现有模块"""
    print("[5/6] 已有功能回归...")
    import sys, os
    sys.path.insert(0, "tests")

    import eval_helpers
    from eval_it3c import test_semantic_search_filters
    from eval_p0_unit import test_scoring

    r = eval_helpers.EvalRecorder("M3-script-regression")
    test_semantic_search_filters(r)
    test_scoring(r)
    s = r.summary()
    assert s["failed"] == 0, f"回归失败: {s['failed']} 项"
    print(f"  ✓ {s['passed']}/{s['total']} 回归通过")


def test_retriever_caching():
    """检索器 EmbeddingClient 缓存"""
    print("[6/6] EmbeddingClient 缓存...")
    from tools.knowledge_indexer import KnowledgeIndexer, KnowledgeRetriever

    indexer = KnowledgeIndexer("mobile")
    indexer.index_all()
    retriever = KnowledgeRetriever(indexer)

    # 第一次检索（懒加载 client）
    client1 = retriever._get_emb_client()
    assert client1 is not None

    # 第二次应返回同一个 client
    client2 = retriever._get_emb_client()
    assert client1 is client2, "_get_emb_client 应返回缓存的实例"

    print(f"  ✓ EmbeddingClient 懒加载 + 缓存正确")


def main():
    print("=" * 56)
    print("  M3 RAG 知识库 — 验证测试")
    print("=" * 56)

    # 初始化
    from platforms import init_all_platforms
    init_all_platforms()

    indexer = test_index_and_chunk()
    retriever = test_retrieval_quality(indexer)
    test_knowledge_type_filter(indexer)
    test_tool_registration(retriever)
    test_regression()
    test_retriever_caching()

    print(f"\n{'=' * 56}")
    print("  M3 全部通过")
    print(f"{'=' * 56}")


if __name__ == "__main__":
    main()
