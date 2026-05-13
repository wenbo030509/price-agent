"""
评估工具公共模块
- Ground Truth 计算：绕过 LLM，直接从数据库获取标准答案
- 答案解析：从 Agent 输出中提取金额、平台名等
- 评分函数：对比期望与实际
- 报告生成：汇总各阶段结果
"""

import re
import json
import time
import os
from datetime import datetime
from typing import Dict, List, Optional, Tuple


# ── Ground Truth 计算 ──────────────────────────────────────────────────────

def compute_cheapest(product_name: str, color: str = None, memory: str = None) -> Dict:
    """直接从数据库计算最便宜的商品，返回 {platform, price, total_price, ...}"""
    from platforms.parallel_agent import PlatformParallelAgent
    agent = PlatformParallelAgent()
    result = agent.compare_product_price(product_name, color=color, memory=memory)
    agent.close()
    if result["found"]:
        c = result["cheapest"]
        return {
            "platform_id": c["platform_id"],
            "platform_name": c["platform_name"],
            "price": c["platform_price"],
            "product_name": c["product_name"],
            "color": c.get("color", ""),
            "memory": c.get("memory", ""),
        }
    return {"found": False}


def compute_all_prices(product_name: str, color: str = None, memory: str = None) -> List[Dict]:
    """获取所有平台该商品的价格列表（ground truth）"""
    from platforms.parallel_agent import PlatformParallelAgent
    agent = PlatformParallelAgent()
    result = agent.compare_product_price(product_name, color=color, memory=memory)
    agent.close()
    if result["found"]:
        return [
            {
                "platform_id": m["platform_id"],
                "platform_name": m["platform_name"],
                "price": m["platform_price"],
                "total_price": m["platform_price"] + m.get("shipping_fee", 0),
                "product_name": m["product_name"],
            }
            for m in result["all_matches"]
        ]
    return []


def compute_platform_count() -> int:
    """获取有数据的平台数量"""
    from platforms.parallel_agent import PlatformParallelAgent
    agent = PlatformParallelAgent()
    result = agent.query_all_products_parallel()
    agent.close()
    return len([r for r in result["results"].values() if r["count"] > 0])


# ── 答案解析 ──────────────────────────────────────────────────────────────

def extract_prices(text: str) -> List[float]:
    """从文本中提取所有金额（¥符号 或 数字+元）"""
    matches = re.findall(r'[¥￥](\d+(?:\.\d+)?)', text)
    # 也匹配 "6850元" 格式
    matches += re.findall(r'(\d+(?:\.\d+)?)\s*元', text)
    return [float(m) for m in matches]


def extract_platform_names(text: str) -> List[str]:
    """从文本中提取平台名称"""
    platforms = []
    for name in ["京东", "淘宝", "拼多多", "苏宁"]:
        if name in text:
            platforms.append(name)
    return platforms


def extract_product_names(text: str, candidates: List[str]) -> List[str]:
    """检查文本中出现了哪些候选商品名"""
    return [c for c in candidates if c.lower() in text.lower()]


def price_in_range(price: float, expected_prices: List[Dict], tolerance: float = 1.0) -> bool:
    """检查金额是否在 ground truth 的合理范围内"""
    if not expected_prices:
        return False
    all_prices = [p["total_price"] for p in expected_prices]
    return abs(price - min(all_prices)) <= tolerance or any(
        abs(price - p) <= tolerance for p in all_prices
    )


# ── 幻觉检测 ──────────────────────────────────────────────────────────────

def detect_hallucination(answer: str, ground_truth_matches: List[Dict]) -> Tuple[bool, List[float]]:
    """检测答案是否编造了不存在的商品价格。
    策略：抽取答案中 >= 1000 的金额（排除运费、差价、均价），逐一比对 ground truth。
    阈值 1000：电子产品价格通常 >= 1700，运费 0-20，差价 < 500。"""
    prices_in_answer = extract_prices(answer)
    if not prices_in_answer or not ground_truth_matches:
        return True, []

    valid_prices = set()
    for m in ground_truth_matches:
        valid_prices.add(m["price"])
        valid_prices.add(m["total_price"])

    # 只检查 >= 2000 的金额（排除运费 0-20、差价 100-1500、均价等衍生值）
    large_prices = [p for p in prices_in_answer if p >= 2000]

    # 用 5% 容差匹配（允许 LLM 回答中价格有轻微偏差，如四舍五入）
    hallucinations = []
    for p in large_prices:
        tolerance = max(10.0, p * 0.05)
        if not any(abs(p - v) <= tolerance for v in valid_prices):
            hallucinations.append(p)

    return len(hallucinations) == 0, hallucinations


# ── 评分 ──────────────────────────────────────────────────────────────────

def score_param_extraction(actual: Dict, expected: Dict) -> Dict:
    """对属性提取结果打分，每项 1 分，满分 3。
    严格模式：product_name 不应残留颜色/内存等修饰词。"""
    scores = {}

    # product_name：检查 actual 是否仅包含核心名称（不含颜色/内存修饰词）
    expected_pn = (expected.get("product_name") or "").lower().strip()
    actual_pn = (actual.get("product_name") or "").lower().strip()

    if not expected_pn:
        scores["product_name"] = True
    else:
        # 必须包含核心名称
        contains_core = expected_pn in actual_pn or actual_pn in expected_pn
        # 且不应残留已知的属性词（说明 LLM 没做属性分离）
        attr_words = ["黑色", "白色", "蓝色", "红色", "绿色", "紫色", "粉色", "金色",
                       "128gb", "256gb", "512gb", "1tb", "128g", "256g", "512g", "1t",
                       "水果", "苹果", "ip15", "米14"]
        has_residual = any(w in actual_pn for w in attr_words if w not in expected_pn)
        scores["product_name"] = contains_core and not has_residual

    # color
    expected_color = (expected.get("color") or "").lower().strip()
    actual_color = (actual.get("color") or "").lower().strip()
    if not expected_color:
        scores["color"] = True
    else:
        scores["color"] = expected_color in actual_color or actual_color in expected_color

    # memory
    expected_mem = (expected.get("memory") or "").lower().strip()
    actual_mem = (actual.get("memory") or "").lower().strip()
    if not expected_mem:
        scores["memory"] = True
    else:
        scores["memory"] = expected_mem in actual_mem or actual_mem in expected_mem

    scores["total"] = sum(1 for v in scores.values() if v)
    return scores


# ── 结果记录 ──────────────────────────────────────────────────────────────

class EvalRecorder:
    """评估结果收集器"""

    def __init__(self, phase: str):
        self.phase = phase
        self.cases = []
        self.start_time = time.time()

    def record(self, case_id: str, passed: bool, details: Dict = None):
        self.cases.append({
            "case_id": case_id,
            "passed": passed,
            "details": details or {},
        })

    def summary(self) -> Dict:
        total = len(self.cases)
        passed = sum(1 for c in self.cases if c["passed"])
        return {
            "phase": self.phase,
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "pass_rate": f"{passed / total * 100:.1f}%" if total > 0 else "N/A",
            "duration_ms": int((time.time() - self.start_time) * 1000),
            "cases": self.cases,
        }


def save_report(phase: str, summary: Dict):
    """保存单阶段评估报告"""
    os.makedirs("eval/results", exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    filename = f"tests/eval_results/{timestamp}_{phase}.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    return filename


def print_summary(summary: Dict):
    """打印阶段汇总"""
    print(f"\n{'='*60}")
    print(f"  {summary['phase']} 评估结果")
    print(f"{'='*60}")
    print(f"  总计: {summary['total']}  |  通过: {summary['passed']}  |  失败: {summary['failed']}")
    print(f"  通过率: {summary['pass_rate']}")
    print(f"  耗时: {summary['duration_ms']}ms")

    if summary["failed"] > 0:
        print(f"\n  失败 case:")
        for c in summary["cases"]:
            if not c["passed"]:
                print(f"    ✗ {c['case_id']}: {c['details'].get('reason', 'unknown')}")
    print()
