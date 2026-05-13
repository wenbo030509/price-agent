"""
测试 EmbeddingClient — 验证火山引擎 ARK Embedding API 连通性和向量质量。

注意：/embeddings/multimodal 端点将多个输入融合为单个向量，
因此批量语义文本需要逐条调用，内部用 ThreadPoolExecutor 并行。
"""
import sys
import time
import numpy as np


def test_single_text(client):
    """单条文本向量化"""
    print("[1/6] 单条文本向量化...")
    try:
        vec = client.embed_text("iPhone 15 Pro 黑色 256GB A17 Pro 拍照旗舰")
        assert isinstance(vec, np.ndarray), f"返回类型错误: {type(vec)}"
        assert vec.ndim == 1, f"向量维度错误: {vec.ndim}"
        assert vec.dtype == np.float32, f"dtype 错误: {vec.dtype}"
        print(f"  ✓ 成功，维度: {len(vec)}, dtype: {vec.dtype}")
        return len(vec)
    except Exception as e:
        print(f"  ✗ 失败: {e}")
        return None


def test_parallel_batch(client):
    """并行批量向量化"""
    print("[2/6] 并行批量向量化 (3条)...")
    texts = [
        "iPhone 15 Pro 拍照旗舰手机",
        "小米14 骁龙8Gen3 游戏手机",
        "红米Note13 学生入门机 长续航",
    ]
    try:
        start = time.time()
        vecs = client.embed_texts(texts, max_workers=3)
        elapsed = (time.time() - start) * 1000
        assert len(vecs) == len(texts), f"返回数量不匹配: {len(vecs)} != {len(texts)}"
        for i, v in enumerate(vecs):
            assert isinstance(v, np.ndarray), f"vec[{i}] 类型错误: {type(v)}"
            assert v.ndim == 1, f"vec[{i}] 维度错误: {v.ndim}"
        print(f"  ✓ 成功，{len(vecs)} 个向量 x {len(vecs[0])} 维，耗时 {elapsed:.0f}ms")
    except Exception as e:
        print(f"  ✗ 失败: {e}")


def test_batched_split(client):
    """分批向量化"""
    print("[3/6] 分批向量化 (5条, batch_size=2)...")
    texts = [f"测试文本 {i}" for i in range(5)]
    try:
        vecs = client.embed_batched(texts, batch_size=2)
        assert len(vecs) == 5, f"返回数量不匹配: {len(vecs)} != 5"
        print(f"  ✓ 成功，分 3 批，返回 {len(vecs)} 个向量")
    except Exception as e:
        print(f"  ✗ 失败: {e}")


def test_dimension(client):
    """维度探测"""
    print("[4/6] 向量维度探测...")
    try:
        dim = client.dimension
        assert dim is not None and dim > 0, f"维度异常: {dim}"
        print(f"  ✓ 维度: {dim}")
    except Exception as e:
        print(f"  ✗ 失败: {e}")


def test_cosine_similarity(client):
    """余弦相似度：验证语义相似文本比不相似文本得分更高"""
    print("[5/6] 语义相似度验证...")

    group_a = [
        "iPhone 15 Pro 拍照效果很好 专业摄像",
        "拍照旗舰手机 徕卡影像 夜景模式 长焦",
    ]
    group_b = [
        "红米Note13 学生入门机 便宜长续航 低预算",
        "iPad Pro 平板电脑 M2芯片 办公学习 画画",
    ]

    try:
        vecs_a = client.embed_texts(group_a)
        vecs_b = client.embed_texts(group_b)

        # 组内相似度 (拍照 vs 拍照)
        sim_aa = float(np.dot(vecs_a[0], vecs_a[1]) / (
            np.linalg.norm(vecs_a[0]) * np.linalg.norm(vecs_a[1])
        ))
        # 跨组相似度 (拍照 vs 学生机)
        sim_ab = float(np.dot(vecs_a[0], vecs_b[0]) / (
            np.linalg.norm(vecs_a[0]) * np.linalg.norm(vecs_b[0])
        ))

        print(f"  拍照-拍照 相似度:    {sim_aa:.4f}")
        print(f"  拍照-学生机 相似度:  {sim_ab:.4f}")

        if sim_aa > sim_ab:
            print(f"  ✓ 语义区分度合格（Δ = {sim_aa - sim_ab:.4f}）")
        else:
            print(f"  ⚠ 语义区分度不足（组内 {sim_aa:.4f} <= 跨组 {sim_ab:.4f}）")
    except Exception as e:
        print(f"  ✗ 失败: {e}")


def test_product_recall_simulation(client):
    """模拟商品召回：query 在候选商品中搜索最相似的"""
    print("[6/6] 商品召回模拟...")

    products = [
        {"name": "iPhone 15 Pro", "desc": "A17 Pro芯片 钛金属机身 专业摄像 三摄系统"},
        {"name": "小米14", "desc": "骁龙8Gen3 徕卡影像 大电池 144Hz高刷 液冷散热"},
        {"name": "红米Note13", "desc": "入门首选 大屏长续航 5000mAh 学生党实惠"},
        {"name": "iPad Pro 11寸", "desc": "M2芯片 Liquid Retina显示屏 办公学习 画画"},
        {"name": "AirPods Pro 2", "desc": "主动降噪 空间音频 H2芯片 无线耳机"},
    ]

    queries = [
        ("适合打游戏的手机 性能强", "小米14"),
        ("拍照效果最好的手机", "iPhone 15 Pro"),
        ("学生党便宜手机 长续航", "红米Note13"),
        ("办公学习用的设备", "iPad Pro 11寸"),
    ]

    all_pass = True
    for query, expected_name in queries:
        query_vec = client.embed_text(query)

        product_texts = [f"{p['name']} {p['desc']}" for p in products]
        product_vecs = client.embed_texts(product_texts)

        scores = []
        for i, p_vec in enumerate(product_vecs):
            sim = float(np.dot(query_vec, p_vec) / (
                np.linalg.norm(query_vec) * np.linalg.norm(p_vec)
            ))
            scores.append((sim, products[i]["name"]))

        scores.sort(reverse=True)
        top1 = scores[0][1]
        flag = "✓" if expected_name in top1 else "✗"
        if flag == "✗":
            all_pass = False
        print(f"  {flag} '{query}' → Top-1: {top1} (期望: {expected_name})")

    if all_pass:
        print(f"  ✓ 召回全部符合预期")
    else:
        print(f"  ⚠ 部分召回未命中，可能需要调整 embedding_fields 的拼接方式")


def main():
    print("=" * 56)
    print("  EmbeddingClient 验证测试")
    print("  模型: doubao-embedding-vision-251215")
    print("  端点: /embeddings/multimodal")
    print("=" * 56)

    from config.settings import Settings
    settings = Settings()

    if not settings.ark_api_key:
        print("\n✗ ARK_API_KEY 未设置，请在 .env 中配置后重试")
        sys.exit(1)

    client = settings.embedding_client
    print(f"\n  API Key: {settings.ark_api_key[:8]}...")
    print(f"  Model: {settings.embedding_model}")
    print(f"  Endpoint: {client.endpoint}")
    print(f"  Max Workers: {client.max_workers}")

    dim = test_single_text(client)
    test_parallel_batch(client)
    test_batched_split(client)
    test_dimension(client)
    test_cosine_similarity(client)
    test_product_recall_simulation(client)

    print(f"\n{'=' * 56}")
    print(f"  验证完成。Embedding 维度: {dim or '获取失败'}")
    print(f"{'=' * 56}")


if __name__ == "__main__":
    main()
