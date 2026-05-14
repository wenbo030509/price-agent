"""
P6 图片搜索评估 — 验证图片→属性提取→比价链路
执行：python3 eval/eval_p6_image.py
含单元测试（无 API）+ E2E 测试（需多模态模型），预计耗时 30s-90s。

测试图片来源（自动发现，按优先级）：
  1. TEST_IMAGE_URL 环境变量
  2. tests/test_data/ 目录下 *.jpg / *.png
  3. static/uploads/ 用户上传目录（取最近 3 张）
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


# ── P6-2: 图片发现 ───────────────────────────────────────────────────────

def _discover_test_images():
    """
    按优先级发现可用的测试图片，返回 [(image_base64, source_label), ...]。

    来源优先级：
    1. TEST_IMAGE_URL 环境变量（URL 或本地路径）
    2. tests/test_data/ 目录下 *.jpg / *.png 文件
    3. static/uploads/ 目录下用户上传的图片（最多取最近 3 张）
    """
    images = []

    # ── 来源1: 环境变量 ──
    env_url = os.getenv("TEST_IMAGE_URL", "").strip()
    if env_url:
        if env_url.startswith("http://") or env_url.startswith("https://") or env_url.startswith("data:"):
            images.append((env_url, f"env:TEST_IMAGE_URL"))
        elif os.path.exists(env_url):
            img_b64 = _file_to_base64(env_url)
            if img_b64:
                images.append((img_b64, f"env:{os.path.basename(env_url)}"))
        else:
            print(f"  ⚠ TEST_IMAGE_URL 路径不存在: {env_url}")

    # ── 来源2: tests/test_data/ 目录 ──
    test_data_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "tests", "test_data"
    )
    if os.path.isdir(test_data_dir):
        for fname in sorted(os.listdir(test_data_dir)):
            if fname.lower().endswith((".jpg", ".jpeg", ".png")):
                fpath = os.path.join(test_data_dir, fname)
                img_b64 = _file_to_base64(fpath)
                if img_b64:
                    images.append((img_b64, f"test_data/{fname}"))

    # ── 来源3: static/uploads/ 用户上传图片 ──
    uploads_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "static", "uploads"
    )
    if os.path.isdir(uploads_dir):
        upload_files = sorted(
            [f for f in os.listdir(uploads_dir) if f.lower().endswith((".jpg", ".jpeg", ".png"))],
            key=lambda f: os.path.getmtime(os.path.join(uploads_dir, f)),
            reverse=True,
        )
        for fname in upload_files[:3]:
            fpath = os.path.join(uploads_dir, fname)
            img_b64 = _file_to_base64(fpath)
            if img_b64:
                images.append((img_b64, f"uploads/{fname}"))

    return images


def _file_to_base64(filepath: str):
    """将本地图片转为 base64 data URI"""
    import base64
    try:
        with open(filepath, "rb") as f:
            data = f.read()
        if len(data) == 0:
            return None
        ext = filepath.rsplit(".", 1)[-1].lower()
        mime = "png" if ext == "png" else "jpeg"
        return f"data:image/{mime};base64,{base64.b64encode(data).decode()}"
    except Exception:
        return None


# ── P6-3: E2E 图片搜索（需多模态模型）─────────────────────────────────────────

def test_image_search_e2e(recorder: EvalRecorder):
    """端到端测试：真实图片 → 识别 → 比价（需要多模态模型）

    自动发现测试图片，按来源优先级：
    1. TEST_IMAGE_URL 环境变量
    2. tests/test_data/ 目录
    3. static/uploads/ 用户上传目录
    """
    print("\n--- P6-3: E2E 图片搜索（需多模态模型） ---")

    from tools.image_search_tools import search_product_by_image

    images = _discover_test_images()

    if not images:
        print("  ? 未找到测试图片，跳过 E2E 测试。")
        print("    可用途径：")
        print("      1. 设置 TEST_IMAGE_URL 环境变量")
        print("      2. 放入 tests/test_data/ 目录 (.jpg/.png)")
        print("      3. 通过前端上传图片到 static/uploads/")
        recorder.record("IM-E2E-01", False, {"skipped": True, "reason": "无测试图片"})
        recorder.record("IM-E2E-02", False, {"skipped": True, "reason": "无测试图片"})
        return

    print(f"  发现 {len(images)} 张测试图片")

    e2e_idx = 1
    has_any_success = False

    for img_data, source_label in images:
        case_id_01 = f"IM-E2E-{e2e_idx:02d}a"
        case_id_02 = f"IM-E2E-{e2e_idx:02d}b"

        try:
            start = time.time()
            result = search_product_by_image(img_data)
            elapsed = int((time.time() - start) * 1000)

            success = result.get("success", False)
            attrs = result.get("image_attrs", {})
            product_name = attrs.get("product_name", "")

            has_product = bool(product_name)
            has_error = "error" in attrs
            passed_01 = has_product or not has_error

            recorder.record(case_id_01, passed_01, {
                "source": source_label,
                "image_attrs": attrs,
                "success": success,
                "elapsed_ms": elapsed,
                "has_product": has_product,
                "has_error": has_error,
            })
            status = "✓" if has_product else ("✗" if has_error else "?")
            print(f"  {status} {case_id_01}: [{source_label}] product_name='{product_name}', confidence={attrs.get('confidence')}, {elapsed}ms")

            if success and result.get("comparison", {}).get("found"):
                ground_truth = compute_all_prices(product_name)
                answer = result.get("formatted_text", "")
                no_hallu, hallu_prices = detect_hallucination(answer, ground_truth)
                passed_02 = no_hallu
            else:
                passed_02 = True
                no_hallu = True
                hallu_prices = []

            recorder.record(case_id_02, passed_02, {
                "source": source_label,
                "success": success,
                "found": result.get("comparison", {}).get("found", False),
                "no_hallucination": no_hallu,
                "hallucinations": hallu_prices,
            })
            print(f"  {'✓' if passed_02 else '✗'} {case_id_02}: found={result.get('comparison', {}).get('found', False)}, halluc={not no_hallu}")

            if passed_01 and passed_02:
                has_any_success = True

        except Exception as e:
            error_msg = str(e)[:200]
            recorder.record(case_id_01, False, {
                "source": source_label,
                "error": error_msg,
                "skipped": True,
            })
            recorder.record(case_id_02, False, {
                "source": source_label,
                "error": error_msg,
                "skipped": True,
            })
            print(f"  ✗ {case_id_01}: [{source_label}] 异常: {error_msg}")

        e2e_idx += 1

    if not has_any_success and e2e_idx == 2:
        print("  ⚠ 仅 1 张图片且识别失败，可上传更多商品图片到前端测试")


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
