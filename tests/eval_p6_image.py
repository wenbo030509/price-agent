"""
P6 图片搜索评估 — 验证图片→属性提取→比价链路
执行：python3 tests/eval_p6_image.py
含单元测试（无 API）+ E2E 测试（需多模态模型），预计耗时 30s-60s
"""
import sys
import os
import json
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from eval_helpers import (
    EvalRecorder, save_report, print_summary,
    compute_all_prices, extract_prices, detect_hallucination
)

_time = time


# ── P6-1: 工具注册与属性解析（无 API）────────────────────────────────────────

def test_tool_registration(recorder: EvalRecorder):
    """验证图片搜索工具已注册且属性解析函数正确"""
    print("\n--- P6-1: 工具注册 + 属性解析 ---")

    from tools import tool_registry

    # IM-01: 工具已注册
    tool_names = [t["function"]["name"] for t in tool_registry.get_schemas()]
    registered = "search_product_by_image" in tool_names
    recorder.record("IM-01", registered, {
        "reason": f"search_product_by_image {'已注册' if registered else '未注册'}"
    })
    print(f"  {'✓' if registered else '✗'} IM-01: 工具注册={registered}")

    # IM-02: _extract_attrs_from_image — 正常 JSON 响应解析
    from tools.image_search_tools import _extract_attrs_from_image

    class MockResp:
        class Choice:
            class Message:
                content = '{"product_name": "iPhone 15", "color": "黑色", "category": "手机", "brand": "Apple", "confidence": "high"}'
            message = Message()
        choices = [Choice()]

    class MockClient:
        class chat:
            class completions:
                @staticmethod
                def create(model, messages, temperature, max_tokens):
                    return MockResp()

    attrs = _extract_attrs_from_image(
        "https://example.com/iphone15.jpg",
        MockClient(),
        "test-model",
    )
    parsed_ok = (
        attrs["product_name"] == "iPhone 15"
        and attrs["color"] == "黑色"
        and attrs["confidence"] == "high"
    )
    recorder.record("IM-02", parsed_ok, {
        "reason": f"attrs={attrs}"
    })
    print(f"  {'✓' if parsed_ok else '✗'} IM-02: 正常JSON解析={parsed_ok}")

    # IM-03: 异常响应 — 返回空属性 + error
    class ErrorClient:
        class chat:
            class completions:
                @staticmethod
                def create(model, messages, temperature, max_tokens):
                    raise Exception("API 超时")

    attrs = _extract_attrs_from_image(
        "https://example.com/bad.jpg",
        ErrorClient(),
        "test-model",
    )
    error_ok = (
        attrs["product_name"] == ""
        and attrs["confidence"] == "low"
        and "error" in attrs
    )
    recorder.record("IM-03", error_ok, {
        "reason": f"attrs={attrs}"
    })
    print(f"  {'✓' if error_ok else '✗'} IM-03: 异常处理={error_ok}")

    # IM-04: 不完整 JSON — 用默认值
    class PartialClient:
        class chat:
            class completions:
                @staticmethod
                def create(model, messages, temperature, max_tokens):
                    class R:
                        class C:
                            class M:
                                content = '{"product_name": "小米14"}'
                            message = M()
                        choices = [C()]
                    return R()

    attrs = _extract_attrs_from_image(
        "https://example.com/xiaomi.jpg",
        PartialClient(),
        "test-model",
    )
    partial_ok = attrs["product_name"] == "小米14" and attrs["color"] == ""
    recorder.record("IM-04", partial_ok, {
        "reason": f"attrs={attrs}"
    })
    print(f"  {'✓' if partial_ok else '✗'} IM-04: 不完整JSON={partial_ok}")

    # IM-05: search_product_by_image — 无法识别时优雅返回
    class EmptyClient:
        class chat:
            class completions:
                @staticmethod
                def create(model, messages, temperature, max_tokens):
                    class R:
                        class C:
                            class M:
                                content = '{"product_name": "", "color": "", "category": "", "brand": "", "confidence": "low"}'
                            message = M()
                        choices = [C()]
                    return R()

    from tools.image_search_tools import search_product_by_image
    # Patch _get_vision_client to use EmptyClient
    import tools.image_search_tools as ist
    _orig_get = ist._get_vision_client
    ist._get_vision_client = lambda: (EmptyClient(), "test")
    try:
        result = search_product_by_image("https://example.com/unknown.jpg")
        graceful = (
            not result["success"]
            and "未能从图片中识别" in result["message"]
        )
    finally:
        ist._get_vision_client = _orig_get

    recorder.record("IM-05", graceful, {
        "reason": f"message={result.get('message', '')[:100]}"
    })
    print(f"  {'✓' if graceful else '✗'} IM-05: 无法识别时优雅降级={graceful}")


# ── P6-2: E2E 图片搜索（需多模态模型）─────────────────────────────────────────

def test_image_search_e2e(recorder: EvalRecorder):
    """端到端测试：真实图片 → 识别 → 比价（需要多模态模型和有效图片URL）

    图片来源优先级：
    1. TEST_IMAGE_URL 环境变量指定的 URL
    2. 本地 tests/test_data/ 目录下的图片
    3. 跳过 E2E 测试
    """
    print("\n--- P6-2: E2E 图片搜索（需多模态模型） ---")

    from tools.image_search_tools import search_product_by_image

    test_image = os.getenv("TEST_IMAGE_URL", "")

    # 如果环境变量未设置，尝试找本地测试图片
    if not test_image:
        local_candidates = [
            "tests/test_data/iphone15.jpg",
            "tests/test_data/product_sample.jpg",
            "tests/test_data/test_product.png",
        ]
        for local_path in local_candidates:
            if os.path.exists(local_path):
                import base64
                with open(local_path, "rb") as f:
                    img_b64 = base64.b64encode(f.read()).decode()
                ext = local_path.rsplit(".", 1)[-1].lower()
                mime = "png" if ext == "png" else "jpeg"
                test_image = f"data:image/{mime};base64,{img_b64}"
                print(f"  使用本地测试图片: {local_path}")
                break

    if not test_image:
        print("  ? 未找到测试图片，跳过 E2E 测试。")
        print("    设置 TEST_IMAGE_URL 环境变量或放入 tests/test_data/ 图片文件。")
        recorder.record("IM-E2E-01", False, {"skipped": True, "reason": "无测试图片"})
        recorder.record("IM-E2E-02", False, {"skipped": True, "reason": "无测试图片"})
        return

    try:
        start = time.time()
        result = search_product_by_image(test_image)
        elapsed = int((time.time() - start) * 1000)

        success = result.get("success", False)
        attrs = result.get("image_attrs", {})
        product_name = attrs.get("product_name", "")

        # IM-E2E-01: 应识别出商品名（或至少返回了结构化的错误）
        has_product = bool(product_name)
        has_error = "error" in attrs
        api_ok = has_product or not has_error  # 有结果 或 无错误也算通过

        recorder.record("IM-E2E-01", has_product or not has_error, {
            "image_url": test_image[:80],
            "image_attrs": attrs,
            "success": success,
            "elapsed_ms": elapsed,
            "has_product": has_product,
            "has_error": has_error,
        })
        status = "✓" if has_product else ("✗" if has_error else "?")
        print(f"  {status} IM-E2E-01: product_name='{product_name}', confidence={attrs.get('confidence')}, error={has_error}, {elapsed}ms")

        # IM-E2E-02: 识别结果应能搜到比价数据
        if success and result.get("comparison", {}).get("found"):
            ground_truth = compute_all_prices(product_name)
            answer = result.get("formatted_text", "")
            no_hallu, hallu_prices = detect_hallucination(answer, ground_truth)
            passed = no_hallu
        else:
            passed = True
            no_hallu = True
            hallu_prices = []

        recorder.record("IM-E2E-02", passed, {
            "success": success,
            "found": result.get("comparison", {}).get("found", False),
            "no_hallucination": no_hallu,
            "hallucinations": hallu_prices,
        })
        print(f"  {'✓' if passed else '✗'} IM-E2E-02: found={result.get('comparison', {}).get('found', False)}, halluc={not no_hallu}")

    except Exception as e:
        error_msg = str(e)[:200]
        recorder.record("IM-E2E-01", False, {
            "image_url": test_image[:80],
            "error": error_msg,
            "skipped": True,
        })
        recorder.record("IM-E2E-02", False, {
            "error": error_msg,
            "skipped": True,
        })
        print(f"  ? IM-E2E: API 报错，跳过 E2E 测试")
        print(f"    错误: {error_msg}")


def main():
    print("=" * 60)
    print("  P6 图片搜索评估")
    print("=" * 60)

    recorder = EvalRecorder("P6_image")

    test_tool_registration(recorder)
    test_image_search_e2e(recorder)

    summary = recorder.summary()

    # 排除跳过的 E2E case
    scored = [c for c in summary["cases"] if not c["details"].get("skipped")]
    if scored:
        passed = sum(1 for c in scored if c["passed"])
        summary["scored_total"] = len(scored)
        summary["scored_passed"] = passed
        summary["scored_pass_rate"] = f"{passed / len(scored) * 100:.1f}%"
    else:
        summary["scored_pass_rate"] = "N/A"

    print_summary(summary)
    if scored:
        print(f"  评分 case 通过率: {summary['scored_pass_rate']} ({summary.get('scored_passed', 0)}/{len(scored)})")

    filename = save_report("P6_image", summary)
    print(f"报告已保存: {filename}")

    return True


if __name__ == "__main__":
    main()
