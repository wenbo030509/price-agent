"""
P0 单元测试 — 不依赖 LLM，验证底层函数正确性
执行：python3 eval/eval_p0_unit.py
"""

import sys
import os
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from eval_helpers import EvalRecorder, save_report, print_summary


def test_db_crud(recorder: EvalRecorder):
    """P0-1: 数据库 CRUD"""
    from platforms.platform_database import PlatformDatabase

    db = PlatformDatabase("jd")

    # DB-01: add + query
    p = db.add_product("EvalTest Phone X 黑色 64GB", 999, 10, "手机", 999, 0, True, "黑色", "64GB")
    products = db.query_all_products()
    found = [x for x in products if x["id"] == p["id"]]
    recorder.record("DB-01", len(found) == 1,
                    {"reason": "add_product 后 query_all 能找到" if len(found) == 1 else "找不到新增商品"})

    # DB-02: update 持久化
    db.update_product(p["id"], price=1234)
    db.close()
    db2 = PlatformDatabase("jd")
    products2 = db2.query_all_products()
    updated = [x for x in products2 if x["id"] == p["id"]]
    passed = len(updated) == 1 and updated[0]["price"] == 1234
    recorder.record("DB-02", passed,
                    {"reason": f"update price={updated[0]['price'] if updated else 'not_found'}"})

    # DB-03: delete
    db2.delete_product(p["id"])
    products3 = db2.query_all_products()
    deleted = [x for x in products3 if x["id"] == p["id"]]
    recorder.record("DB-03", len(deleted) == 0,
                    {"reason": "delete 后查询不到" if len(deleted) == 0 else "删除后仍存在"})

    # DB-04: 操作不存在的 id
    not_found_upd = db2.update_product(99999, price=100)
    not_found_del = db2.delete_product(99999)
    recorder.record("DB-04", not_found_upd is None and not_found_del is False,
                    {"reason": f"update={not_found_upd}, delete={not_found_del}"})

    db2.close()


def test_scoring(recorder: EvalRecorder):
    """P0-2: 属性匹配打分"""
    from platforms.platform_database import PlatformDatabase

    db = PlatformDatabase("jd")

    # SC-01: 完全匹配 score=2
    r = db.query_product_by_attrs("iPhone 15", color="黑色", memory="256GB")
    recorder.record("SC-01", r is not None and r.get("_match_score") == 2,
                    {"reason": f"score={r.get('_match_score') if r else None} expected=2"})

    # SC-02: 仅颜色匹配 score=1
    r = db.query_product_by_attrs("iPhone 15", color="黑色", memory="512GB")
    recorder.record("SC-02", r is not None and r.get("_match_score") == 1,
                    {"reason": f"score={r.get('_match_score') if r else None} expected=1"})

    # SC-03: 仅内存匹配 score=1
    r = db.query_product_by_attrs("iPhone 15", color="红色", memory="256GB")
    recorder.record("SC-03", r is not None and r.get("_match_score") == 1,
                    {"reason": f"score={r.get('_match_score') if r else None} expected=1"})

    # SC-04: 无属性匹配 score=0
    r = db.query_product_by_attrs("iPhone 15")
    recorder.record("SC-04", r is not None and r.get("_match_score", 0) == 0,
                    {"reason": f"score={r.get('_match_score') if r else None} expected=0"})

    # SC-05: 同分取价格更低
    p_a = db.add_product("EvalScore X 黑色 128GB", 5000, 100, "手机", 5000, 0, True, "黑色", "128GB")
    p_b = db.add_product("EvalScore X 白色 256GB", 6000, 100, "手机", 6000, 0, True, "白色", "256GB")
    r = db.query_product_by_attrs("EvalScore X", color="黑色", memory="256GB")
    passed = r is not None and r["platform_price"] == 5000
    recorder.record("SC-05", passed,
                    {"reason": f"同分时价格={r['platform_price'] if r else None} expected=5000"})

    # SC-06: 模糊匹配兜底（P0 层面用简单子串，LLM 别名改写由 P1 覆盖）
    r = db.query_product_by_attrs("iPhone")
    recorder.record("SC-06", r is not None and "iPhone" in r.get("product_name", ""),
                    {"reason": f"模糊匹配: {r.get('product_name') if r else None}"})

    db.delete_product(p_a["id"])
    db.delete_product(p_b["id"])
    db.close()


def test_parallel(recorder: EvalRecorder):
    """P0-3: 并行查询"""
    from platforms.parallel_agent import PlatformParallelAgent

    agent = PlatformParallelAgent()

    # PQ-01: 返回多个平台
    r = agent.compare_product_price("iPhone 15")
    recorder.record("PQ-01", r["found"] and r.get("platform_count", 0) >= 1,
                    {"reason": f"platform_count={r.get('platform_count', 0)}"})

    # PQ-02: 每个平台有匹配列表
    platform_results = r.get("platform_results", {})
    all_have_matches = all(len(v) > 0 for v in platform_results.values())
    recorder.record("PQ-02", all_have_matches,
                    {"reason": f"各平台匹配数: {[(pid, len(v)) for pid, v in platform_results.items()]}"})

    # PQ-03: 高分在前
    matches = r.get("all_matches", [])
    if len(matches) >= 2:
        scores_ok = matches[0].get("_match_score", 0) >= matches[-1].get("_match_score", 0)
    else:
        scores_ok = True
    recorder.record("PQ-03", scores_ok,
                    {"reason": f"首尾score: {matches[0].get('_match_score')}/{matches[-1].get('_match_score') if matches else None}"})

    agent.close()


def test_complexity_detection(recorder: EvalRecorder):
    """P0-5: 复杂度判断 — 验证 _is_complex() 三层判断逻辑"""
    from agent.react_engine import ReActAgent

    # 创建一个最小化的 agent（不需要真正调 LLM）
    agent = ReActAgent(
        client=None, model="test", tools=[], tool_map={}, max_round=1,
    )

    # CD-01: 简单单商品查询 → 不触发复杂判定
    recorder.record("CD-01", not agent._is_complex("iPhone 15 价格"),
                    {"reason": "简单单商品查询不应判定为complex"})

    # CD-02: 关键词"对比"→ 触发
    recorder.record("CD-02", agent._is_complex("对比 iPhone 15 和小米14"),
                    {"reason": "含关键词'对比'应判定为complex"})

    # CD-03: 关键词"哪个更"→ 触发
    recorder.record("CD-03", agent._is_complex("iPhone 15 和小米14 哪个更值得买"),
                    {"reason": "含关键词'哪个更'应判定为complex"})

    # CD-04: 关键词"分别"→ 触发
    recorder.record("CD-04", agent._is_complex("分别查 iPhone 15 和小米14 的价格"),
                    {"reason": "含关键词'分别'应判定为complex"})

    # CD-05: 正则模式"A和B都"→ 触发
    recorder.record("CD-05", agent._is_complex("iPhone 15 和小米14 都查一下价格"),
                    {"reason": "结构模式'A和B都'应判定为complex"})

    # CD-06: 正则模式"哪...最"→ 触发
    recorder.record("CD-06", agent._is_complex("在哪个平台买iPhone 15最便宜"),
                    {"reason": "结构模式'哪...最'应判定为complex"})

    # CD-07: 多商品检测 — 两个已知商品
    recorder.record("CD-07", agent._is_complex("iPhone 15 小米14"),
                    {"reason": "两个已知商品应判定为complex"})

    # CD-08: 单商品 + 无关键词 → 不触发
    recorder.record("CD-08", not agent._is_complex("小米14 黑色"),
                    {"reason": "单商品无复杂关键词不应判定为complex"})


def test_dependency_injection(recorder: EvalRecorder):
    """P0-6: 依赖注入 — 验证 $step{N} 引用解析"""
    from agent.react_engine import ReActAgent

    agent = ReActAgent(
        client=None, model="test", tools=[], tool_map={}, max_round=1,
    )

    # Mock 结果：模拟 Step 1 返回的比价数据
    mock_results = {
        1: {
            "raw_data": {
                "found": True,
                "total_matches": 8,
                "cheapest": {
                    "platform_id": "pdd",
                    "platform_name": "拼多多",
                    "platform_price": 5750,
                },
                "most_expensive": {
                    "platform_id": "suning",
                    "platform_name": "苏宁",
                    "platform_price": 6049,
                },
            },
            "formatted_text": "...",
        }
    }

    # DI-01: 基本引用解析 — platform_id
    val = agent._deref("$step1.raw_data.cheapest.platform_id", mock_results)
    recorder.record("DI-01", val == "pdd",
                    {"reason": f"$step1.raw_data.cheapest.platform_id = {val}, expected=pdd"})

    # DI-02: 嵌套路径 — platform_price
    val = agent._deref("$step1.raw_data.cheapest.platform_price", mock_results)
    recorder.record("DI-02", val == 5750,
                    {"reason": f"$step1.raw_data.cheapest.platform_price = {val}, expected=5750"})

    # DI-03: 不存在路径 — 返回原始引用
    val = agent._deref("$step1.raw_data.nonexistent.field", mock_results)
    recorder.record("DI-03", val == "$step1.raw_data.nonexistent.field",
                    {"reason": f"不存在路径应返回原始引用, got={val}"})

    # DI-04: 不存在的 step → 返回原始引用
    val = agent._deref("$step99.raw_data.field", mock_results)
    recorder.record("DI-04", val == "$step99.raw_data.field",
                    {"reason": f"不存在step应返回原始引用, got={val}"})

    # DI-05: _resolve_step_refs — 混合引用和非引用
    args = {
        "platform_id": "$step1.raw_data.cheapest.platform_id",
        "product_name": "iPhone 15",
        "color": None,
    }
    resolved = agent._resolve_step_refs(args, mock_results)
    recorder.record("DI-05",
                    resolved == {"platform_id": "pdd", "product_name": "iPhone 15", "color": None},
                    {"reason": f"混合引用解析: {resolved}"})

    # DI-06: 无引用 args → 原样返回
    args = {"product_name": "小米14", "color": "黑色"}
    resolved = agent._resolve_step_refs(args, mock_results)
    recorder.record("DI-06",
                    resolved == {"product_name": "小米14", "color": "黑色"},
                    {"reason": f"无引用应原样返回: {resolved}"})


def test_empty_result_detection(recorder: EvalRecorder):
    """P0-7: 空结果检测 — 验证 _is_empty_result()"""
    from agent.react_engine import ReActAgent

    agent = ReActAgent(
        client=None, model="test", tools=[], tool_map={}, max_round=1,
    )

    # ER-01: raw_data found=False → empty
    recorder.record("ER-01",
                    agent._is_empty_result({"raw_data": {"found": False, "message": "未找到"}}),
                    {"reason": "found=False 应判定为空"})

    # ER-02: raw_data total_matches=0 → empty
    recorder.record("ER-02",
                    agent._is_empty_result({"raw_data": {"found": True, "total_matches": 0}}),
                    {"reason": "total_matches=0 应判定为空"})

    # ER-03: raw_data found=True with matches → not empty
    recorder.record("ER-03",
                    not agent._is_empty_result({"raw_data": {"found": True, "total_matches": 3}}),
                    {"reason": "found=True + matches 不应判定为空"})

    # ER-04: success=False → empty
    recorder.record("ER-04",
                    agent._is_empty_result({"success": False, "message": "未找到"}),
                    {"reason": "success=False 应判定为空"})

    # ER-05: success=True → not empty
    recorder.record("ER-05",
                    not agent._is_empty_result({"success": True, "product": {"id": 1}}),
                    {"reason": "success=True 不应判定为空"})

    # ER-06: error dict → not empty (error != empty)
    recorder.record("ER-06",
                    not agent._is_empty_result({"error": "连接超时"}),
                    {"reason": "工具执行错误不应判定为空结果"})

    # ER-07: get_all_platform_products empty → empty
    recorder.record("ER-07",
                    agent._is_empty_result({
                        "raw_data": {"results": {"jd": {"products": []}, "taobao": {"products": []}}}
                    }),
                    {"reason": "各平台均无商品应判定为空"})

    # ER-08: get_all_platform_products with data → not empty
    recorder.record("ER-08",
                    not agent._is_empty_result({
                        "raw_data": {"results": {"jd": {"products": [{"id": 1}]}}}
                    }),
                    {"reason": "有平台存在商品不应判定为空"})


def test_reflection_message(recorder: EvalRecorder):
    """P0-8: 反思消息构建 — 验证 _build_reflection_message()"""
    from agent.react_engine import ReActAgent

    agent = ReActAgent(
        client=None, model="test", tools=[], tool_map={}, max_round=1,
    )

    # RF-01: 第1次空结果 + 有属性筛选 → 应引导放宽属性
    msg = agent._build_reflection_message(
        "multi_platform_price_comparison",
        {"product_name": "iPhone 15", "color": "紫色", "memory": "1TB"},
        {"raw_data": {"found": False}},
        retry_count=1,
    )
    recorder.record("RF-01",
                    "放宽属性" in msg and "color" in msg,
                    {"reason": f"第1次有属性→引导放宽, msg长度={len(msg)}"})

    # RF-02: 第2次空结果 → 应引导停止并给出替代
    msg = agent._build_reflection_message(
        "multi_platform_price_comparison",
        {"product_name": "华为Mate60"},
        {"raw_data": {"found": False}},
        retry_count=2,
    )
    recorder.record("RF-02",
                    "停止重试" in msg and "告知用户" in msg,
                    {"reason": f"第2次→引导停止并告知用户, msg长度={len(msg)}"})

    # RF-03: 无属性筛选 + 第1次 → 应引导宽泛搜索
    msg = agent._build_reflection_message(
        "multi_platform_price_comparison",
        {"product_name": "诺基亚3310"},
        {"raw_data": {"found": False}},
        retry_count=1,
    )
    recorder.record("RF-03",
                    "宽泛" in msg or "更短" in msg or "通用" in msg or "确认" in msg,
                    {"reason": f"无属性第1次→引导宽泛搜索或确认, msg长度={len(msg)}"})


def test_regression(recorder: EvalRecorder):
    """P0-4: 已知 Bug 回归"""
    from platforms.platform_database import PlatformDatabase, init_all_platforms

    # RG-01: update_product 方法存在
    recorder.record("RG-01", hasattr(PlatformDatabase, "update_product"),
                    {"reason": "update_product 方法"})

    # RG-02: delete_product 方法存在
    recorder.record("RG-02", hasattr(PlatformDatabase, "delete_product"),
                    {"reason": "delete_product 方法"})

    # RG-03: 重启后数据持久化
    db = PlatformDatabase("jd")
    products = db.query_all_products()
    if products:
        pid = products[0]["id"]
        old_price = products[0]["price"]
        db.update_product(pid, price=99999)
        db.close()
        init_all_platforms()  # 模拟重启
        db2 = PlatformDatabase("jd")
        products2 = db2.query_all_products()
        modified = [p for p in products2 if p["id"] == pid]
        price_kept = len(modified) == 1 and modified[0]["price"] == 99999
        # 恢复
        db2.update_product(pid, price=old_price)
        db2.close()
    else:
        price_kept = True  # 空库跳过
    recorder.record("RG-03", price_kept,
                    {"reason": "重启后价格保留" if price_kept else "重启后价格丢失"})

    # RG-04: API Key 缺失抛异常（用子进程隔离模块级 Settings() 影响）
    import subprocess
    result = subprocess.run(
        [sys.executable, "-c", """
import os
os.environ["DEEPSEEK_API_KEY"] = ""
try:
    from config.settings import Settings
    print("NO_ERROR")
except ValueError:
    print("VALUE_ERROR")
"""],
        capture_output=True, text=True,
        env={**os.environ, "DEEPSEEK_API_KEY": ""}
    )
    recorder.record("RG-04", "VALUE_ERROR" in result.stdout + result.stderr,
                    {"reason": f"stdout={result.stdout.strip()}, stderr={result.stderr.strip()}"})

    # RG-05: 非法输入返回友好错误
    try:
        from app import app
        with app.test_client() as client:
            resp = client.post("/api/platforms/jd/products", json={
                "product_name": "Test",
                "price": "not_a_number",
                "stock": 10,
                "category": "手机",
            })
            data = resp.get_json()
            recorder.record("RG-05", not data["success"] and "参数错误" in data.get("error", ""),
                            {"reason": f"error={data.get('error', '')}"})
    except Exception as e:
        recorder.record("RG-05", False, {"reason": f"测试异常: {e}"})


def main():
    print("=" * 60)
    print("  P0 单元测试（无 LLM）")
    print("=" * 60)

    recorder = EvalRecorder("P0_unit")

    print("\n--- P0-1: 数据库 CRUD ---")
    test_db_crud(recorder)

    print("\n--- P0-2: 属性匹配打分 ---")
    test_scoring(recorder)

    print("\n--- P0-3: 并行查询 ---")
    test_parallel(recorder)

    print("\n--- P0-4: Bug 回归 ---")
    test_regression(recorder)

    print("\n--- P0-5: 复杂度判断 ---")
    test_complexity_detection(recorder)

    print("\n--- P0-6: 依赖注入 ---")
    test_dependency_injection(recorder)

    print("\n--- P0-7: 空结果检测 ---")
    test_empty_result_detection(recorder)

    print("\n--- P0-8: 反思消息构建 ---")
    test_reflection_message(recorder)

    summary = recorder.summary()
    print_summary(summary)

    filename = save_report("P0_unit", summary)
    print(f"报告已保存: {filename}")

    return summary["failed"] == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
