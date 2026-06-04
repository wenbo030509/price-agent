"""
Trace 训练数据处理模块
————————————————
将 trace JSON 转化为 OpenAI SFT fine-tuning 格式的 JSONL 数据集。
提供 trace 列表、格式提取、质量打分、JSONL 导出等核心功能。
"""

import json
import os
import glob
import re
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field


TRACE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "eval", "results", "traces")

# ── 质量打分（业务视角）──────────────────────────────────────────
#
# 评分回答一个问题：这条 trace 对训练 Agent 能力的贡献有多大？
#
# 四个维度：
#   A. Agent 能力展现 (0-40)：工具协调、规划推理、多步执行
#   B. 执行质量     (0-30)：工具是否成功、是否有错误、是否有纠错
#   C. 回答可信度   (0-20)：答案是否基于工具数据、有无具体信息
#   D. 数据完整度   (0-10)：trace 结构是否完整可训练
#


@dataclass
class TraceMeta:
    """Trace 元数据"""
    filename: str
    query: str
    timestamp: str
    session_id: str
    answer: str
    intent: str = ""
    mode: str = ""
    tool_count: int = 0
    round_count: int = 0
    has_error: bool = False
    answer_length: int = 0
    answer_preview: str = ""
    event_count: int = 0


@dataclass
class TrainingSample:
    """单个训练样本"""
    filename: str
    query: str
    intent: str
    mode: str
    messages: List[Dict]
    tools: List[Dict]
    metadata: Dict = field(default_factory=dict)
    # 质量分
    quality_score: float = 0.0
    quality_details: Dict = field(default_factory=dict)
    # 统计
    tool_count: int = 0
    round_count: int = 0


def list_traces(trace_dir: str = None) -> List[TraceMeta]:
    """列出所有 trace 及其元数据"""
    if trace_dir is None:
        trace_dir = TRACE_DIR

    results = []
    for fpath in sorted(glob.glob(os.path.join(trace_dir, "trace_*.json")), reverse=True):
        try:
            with open(fpath, "r") as f:
                trace = json.load(f)
        except (json.JSONDecodeError, IOError):
            continue

        meta = trace.get("meta", {})
        events = trace.get("events", [])

        answer_text = meta.get("answer", "")
        tm = TraceMeta(
            filename=os.path.basename(fpath),
            query=meta.get("query", "")[:120],
            timestamp=meta.get("timestamp", ""),
            session_id=meta.get("session_id", ""),
            answer=answer_text,
            answer_length=len(answer_text),
            answer_preview=answer_text[:200] if answer_text else "",
            event_count=len(events),
        )

        for ev in events:
            t = ev.get("type", "")
            d = ev.get("data", {})
            if t == "intent":
                tm.intent = d.get("intent", "")
            elif t == "mode_select":
                tm.mode = d.get("mode", "")
            elif t == "tool_call":
                tm.tool_count += 1
            elif t == "react_round":
                tm.round_count += 1
            elif t == "error":
                tm.has_error = True

        results.append(tm)

    return results


def extract_sample(filepath: str) -> Optional[TrainingSample]:
    """从单个 trace JSON 提取训练样本"""
    try:
        with open(filepath, "r") as f:
            trace = json.load(f)
    except (json.JSONDecodeError, IOError):
        return None

    meta = trace.get("meta", {})
    events = trace.get("events", [])

    # ── 提取元信息 ──
    intent = ""
    mode = ""
    skill_names = []
    for ev in events:
        if ev["type"] == "intent":
            intent = ev["data"].get("intent", "")
        elif ev["type"] == "mode_select":
            mode = ev["data"].get("mode", "")
        elif ev["type"] == "skill_load":
            skill_names = ev["data"].get("skills", [])

    # ── 构建 system prompt ──
    system_content = _build_system_prompt(intent, mode, skill_names)

    # ── 重建 messages ──
    messages = [{"role": "system", "content": system_content}]
    messages.append({"role": "user", "content": meta.get("query", "")})

    # 按 round 分组事件
    rounds = _group_events_by_round(events)
    tools_used = set()

    for round_num, round_events in rounds.items():
        tool_calls_in_round = [e for e in round_events if e["type"] == "tool_call"]
        tool_results_in_round = [e for e in round_events if e["type"] == "tool_result"]

        if not tool_calls_in_round:
            continue

        # 构建 assistant 消息（含 tool_calls）
        assistant_tool_calls = []
        for i, tc_ev in enumerate(tool_calls_in_round):
            d = tc_ev["data"]
            tool_name = d.get("tool", "unknown")
            args = d.get("args", {})
            tools_used.add(tool_name)
            call_id = f"call_{round_num}_{i}"

            assistant_tool_calls.append({
                "id": call_id,
                "type": "function",
                "function": {
                    "name": tool_name,
                    "arguments": json.dumps(args, ensure_ascii=False),
                },
            })

        messages.append({
            "role": "assistant",
            "content": None,
            "tool_calls": assistant_tool_calls,
        })

        # 构建 tool 消息（配对 tool_call 和 tool_result）
        for i, (tc_ev, tr_ev) in enumerate(
            zip(tool_calls_in_round, tool_results_in_round)
        ):
            call_id = f"call_{round_num}_{i}"
            tr_data = tr_ev["data"]
            summary = tr_data.get("summary", "")

            # 尝试解析 summary 为 JSON
            tool_content = summary
            try:
                parsed = json.loads(summary)
                tool_content = json.dumps(parsed, ensure_ascii=False)
            except (json.JSONDecodeError, TypeError):
                pass

            messages.append({
                "role": "tool",
                "tool_call_id": call_id,
                "content": tool_content,
            })

    # 最终 assistant 回答
    answer = meta.get("answer", "")
    if answer:
        messages.append({"role": "assistant", "content": answer})

    # ── 构建 tools schema ──
    tools_schema = _build_tools_schema(tools_used)

    # ── 质量打分 ──
    score, details = compute_quality(events, answer, tools_used)

    sample = TrainingSample(
        filename=os.path.basename(filepath),
        query=meta.get("query", ""),
        intent=intent,
        mode=mode,
        messages=messages,
        tools=tools_schema,
        quality_score=score,
        quality_details=details,
        tool_count=len(tools_used),
        round_count=len(rounds),
        metadata={
            "timestamp": meta.get("timestamp", ""),
            "session_id": meta.get("session_id", ""),
            "skills": skill_names,
        },
    )

    return sample


def compute_quality(events: List[Dict], answer: str, tools_used: Set[str]) -> Tuple[float, Dict]:
    """计算训练样本质量分 (0-100)，从业务视角评估 trace 对训练 Agent 能力的贡献度"""

    # ── 预计算事件统计 ──
    tool_call_events = [e for e in events if e["type"] == "tool_call"]
    tool_result_events = [e for e in events if e["type"] == "tool_result"]
    tool_errors = sum(1 for e in tool_result_events if e["data"].get("error"))
    empty_results = sum(1 for e in tool_result_events
                        if not e["data"].get("found") and not e["data"].get("error"))
    has_reflection = any(e["type"] == "reflection" for e in events)
    has_error_event = any(e["type"] == "error" for e in events)
    mode = ""
    for e in events:
        if e["type"] == "mode_select":
            mode = e["data"].get("mode", "")  # 取最后一个（实际执行的 mode）
    rounds = len(set(e["data"].get("round", 0) for e in tool_call_events if e["data"].get("round")))

    details = {}
    total = 0.0

    # ═══════════════════════════════════════════════════════════
    # A. Agent 能力展现 (0-40)
    #    这条 trace 展示了 Agent 的哪些能力？
    #    多工具协调 > 规划推理 > 单工具调用 > 无工具
    # ═══════════════════════════════════════════════════════════

    tc = len(tool_call_events)

    if tc == 0:
        # 无工具调用：仅对话交互，训练价值最低
        details["agent_capability"] = "no_tools"
        capability = 0
    elif mode == "plan_execute":
        # Plan-Execute：展示了规划和分步执行能力 — 最高价值
        details["agent_capability"] = "plan_execute"
        base = 25
        # 额外加分：工具数多、有并行调用
        parallel_bonus = min(tc * 3, 15)
        capability = base + parallel_bonus
    elif tc >= 3:
        # 多工具协调：并行调用、信息综合 — 高价值
        details["agent_capability"] = "multi_tool_coordination"
        capability = 25 + min(tc * 3, 15)
    elif tc == 2:
        details["agent_capability"] = "dual_tool"
        capability = 20
    elif rounds >= 2:
        # 多轮工具调用（链式推理）
        details["agent_capability"] = "multi_round_chain"
        capability = 18
    else:
        details["agent_capability"] = "single_tool"
        capability = 10

    # Shopping 模式槽位填充：有一定的交互训练价值
    if mode == "shopping":
        slot_count = sum(1 for e in events if e["type"] == "slot_filled")
        if slot_count > 0:
            details["agent_capability"] = "shopping_with_slots"
            capability = max(capability, 12 + min(slot_count * 2, 8))

    capability = min(capability, 40)
    details["capability_score"] = capability
    total += capability

    # ═══════════════════════════════════════════════════════════
    # B. 执行质量 (0-30)
    #    工具调用是否成功？有没有错误？有没有尝试纠错？
    # ═══════════════════════════════════════════════════════════

    if tc == 0:
        # 无工具调用，不扣分也不加分
        details["execution_quality"] = "no_tools"
        execution = 15  # 中性分
    else:
        # 工具成功率
        success_rate = (tc - tool_errors) / tc if tc > 0 else 1.0
        # 工具查到数据的比例（排除 error 的）
        data_rate = (tc - tool_errors - empty_results) / tc if tc > 0 else 1.0

        if success_rate == 1.0 and data_rate == 1.0:
            details["execution_quality"] = "all_success_with_data"
            execution = 30
        elif success_rate == 1.0 and data_rate >= 0.5:
            details["execution_quality"] = "all_success_partial_data"
            execution = 22
        elif success_rate >= 0.8:
            details["execution_quality"] = "mostly_success"
            execution = 15
        elif has_reflection:
            # 有错误但尝试了反思纠错 — 对训练纠错能力有价值
            details["execution_quality"] = "with_reflection_recovery"
            execution = 12
        else:
            details["execution_quality"] = "has_errors"
            execution = 5

    # 有错误事件直接扣分
    if has_error_event:
        execution = min(execution, 10)

    details["execution_score"] = execution
    total += execution

    # ═══════════════════════════════════════════════════════════
    # C. 回答可信度 (0-20)
    #    答案是否基于工具返回的真实数据？有没有具体信息？
    # ═══════════════════════════════════════════════════════════

    answer_len = len(answer) if answer else 0
    grounding = 0

    if tc == 0:
        # 无工具：回答可信度取决于是否有实质内容
        if answer_len >= 100:
            details["response_grounding"] = "conversational_content"
            grounding = 8
        elif answer_len >= 20:
            details["response_grounding"] = "short_reply"
            grounding = 3
        else:
            details["response_grounding"] = "minimal"
            grounding = 0
    else:
        # 有工具调用：检查答案是否引用了数据
        has_price = bool(re.search(r'[¥￥]\s*\d[\d,]*', answer)) if answer else False
        has_platform = any(p in answer for p in ["京东", "淘宝", "拼多多", "苏宁"]) if answer else False
        has_spec = any(kw in answer for kw in ["GB", "mAh", "英寸", "处理器", "电池", "屏幕", "品牌"]) if answer else False
        has_conclusion = any(kw in answer for kw in ["推荐", "建议", "总结", "性价比", "值得买", "选择"]) if answer else False

        if has_price and has_platform:
            # 明确引用了价格和平台 — 高度可信
            details["response_grounding"] = "price_and_platform_cited"
            grounding = 20
        elif has_price or has_platform:
            details["response_grounding"] = "partial_data_cited"
            grounding = 14
        elif has_spec:
            details["response_grounding"] = "spec_data_cited"
            grounding = 10
        elif has_conclusion:
            details["response_grounding"] = "conclusion_only"
            grounding = 6
        else:
            details["response_grounding"] = "no_clear_grounding"
            grounding = 2

    # 答案过短说明没有充分展开
    if answer_len < 50 and tc > 0:
        grounding = min(grounding, 5)

    details["grounding_score"] = grounding
    total += grounding

    # ═══════════════════════════════════════════════════════════
    # D. 数据完整度 (0-10)
    #    trace 结构是否完整，能否构成有效的训练样本？
    # ═══════════════════════════════════════════════════════════

    completeness = 0
    # 有 system prompt（从 skill_load 事件判断）
    has_system = any(e["type"] == "skill_load" for e in events)
    completeness += 2 if has_system else 0
    # 有用户查询
    completeness += 2 if answer or any(e["type"] == "intent" for e in events) else 0
    # 有完整的工具调用闭环（call + result 配对）
    if tc > 0:
        completeness += 3
        # 所有 tool_call 都有对应 result
        if len(tool_result_events) == tc:
            completeness += 3
        elif len(tool_result_events) > 0:
            completeness += 1
    # 无工具但有答案
    elif answer_len > 0:
        completeness += 2

    details["completeness_score"] = completeness
    total += completeness

    return round(min(total, 100), 1), details


def export_jsonl(samples: List[TrainingSample]) -> str:
    """将训练样本导出为 JSONL 字符串"""
    lines = []
    for s in samples:
        record = {
            "messages": s.messages,
            "tools": s.tools,
            "parallel_tool_calls": s.tool_count > 1,
        }
        lines.append(json.dumps(record, ensure_ascii=False))
    return "\n".join(lines)


# ── 内部辅助函数 ──────────────────────────────────────────────────

def _group_events_by_round(events: List[Dict]) -> Dict[int, List[Dict]]:
    """将事件按 round 分组"""
    rounds: Dict[int, List[Dict]] = {}
    for ev in events:
        d = ev.get("data", {})
        round_num = d.get("round", 0)
        if round_num not in rounds:
            rounds[round_num] = []
        rounds[round_num].append(ev)
    return rounds


def _build_system_prompt(intent: str, mode: str, skills: List[str]) -> str:
    """根据技能信息构建 system prompt 摘要"""
    parts = ["你是智能购物助手，帮助用户搜索商品、比较价格、提供购买建议。"]

    if skills:
        skill_descs = {
            "price_comparison": "跨平台比价",
            "rag_knowledge": "商品知识库检索",
            "shopping_guide": "引导式购物",
            "semantic_recommend": "语义商品推荐",
            "image_search": "图片识别搜索",
        }
        skill_list = [skill_descs.get(s, s) for s in skills]
        parts.append(f"当前激活技能: {', '.join(skill_list)}。")

    if mode:
        mode_hints = {
            "react": "使用 ReAct 模式进行逐步推理和工具调用。",
            "plan_execute": "使用 Plan-Execute 模式先制定计划再逐步执行。",
            "shopping": "使用引导式购物模式，通过多轮对话了解用户需求。",
        }
        parts.append(mode_hints.get(mode, ""))

    parts.append("请基于工具返回的真实数据回答，不要编造信息。如果工具返回为空，如实告知用户。")

    return " ".join(parts)


def _build_tools_schema(tool_names: Set[str]) -> List[Dict]:
    """构建工具 schema（简化版，用于训练数据格式）"""
    tool_schemas = {
        "multi_platform_price_comparison": {
            "name": "multi_platform_price_comparison",
            "description": "在京东/淘宝/拼多多/苏宁四个平台搜索商品价格，返回各平台最低价及库存信息",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_name": {"type": "string", "description": "商品名称"},
                    "color": {"type": "string", "description": "颜色（可选）"},
                    "memory": {"type": "string", "description": "存储容量（可选）"},
                },
                "required": ["product_name"],
            },
        },
        "search_product_knowledge": {
            "name": "search_product_knowledge",
            "description": "搜索商品知识库，获取评测、参数、竞品对比等信息",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词"},
                    "knowledge_type": {
                        "type": "string",
                        "enum": ["review", "spec", "all", "phone_review"],
                        "description": "知识类型",
                    },
                    "top_k": {"type": "integer", "description": "返回条数，默认3"},
                },
                "required": ["query"],
            },
        },
        "semantic_product_search": {
            "name": "semantic_product_search",
            "description": "基于语义理解的商品推荐搜索，根据用户需求描述匹配最合适的商品",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "用户需求描述"},
                    "top_k": {"type": "integer", "description": "返回商品数量"},
                    "use_case": {"type": "string", "description": "使用场景标签"},
                    "budget_min": {"type": "number", "description": "最低预算"},
                    "budget_max": {"type": "number", "description": "最高预算"},
                },
                "required": ["query"],
            },
        },
        "query_product_by_attrs": {
            "name": "query_product_by_attrs",
            "description": "按属性（品牌、价格区间、使用场景等）精确查询商品",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "商品类目"},
                    "brand": {"type": "string", "description": "品牌"},
                    "price_min": {"type": "number"},
                    "price_max": {"type": "number"},
                    "use_case": {"type": "string"},
                    "color": {"type": "string"},
                },
                "required": [],
            },
        },
        "compare_product_price": {
            "name": "compare_product_price",
            "description": "对指定商品进行跨平台比价",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_name": {"type": "string", "description": "商品名称"},
                },
                "required": ["product_name"],
            },
        },
        "get_all_platform_products": {
            "name": "get_all_platform_products",
            "description": "获取所有平台的商品列表，可按类目筛选",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "商品类目"},
                    "platform_id": {"type": "string", "description": "平台ID（可选，不传则返回全部）"},
                },
                "required": [],
            },
        },
    }

    return [
        {"type": "function", "function": tool_schemas[name]}
        for name in sorted(tool_names)
        if name in tool_schemas
    ]


# ═══════════════════════════════════════════════════════════════
# LLM-as-Judge：用 LLM 评估训练样本质量
# ═══════════════════════════════════════════════════════════════

JUDGE_SYSTEM_PROMPT = """你是一个训练数据质量评估专家。你的任务是评估 Agent 执行 trace 作为后训练（SFT）数据样本的质量。

请从以下 4 个维度评估，与启发式评分体系保持一致：

A. **Agent 能力展现 (agent_capability) 0–10 分**：这条 trace 展示了 Agent 的哪些能力？
  - Plan-Execute 多步规划、多工具协调（≥3工具）、多轮链式调用 → 高分（8-10）
  - 双工具调用、Shopping 槽位填充 → 中等（5-7）
  - 单工具调用 → 较低（2-4）
  - 无工具调用 → 最低（0-1）

B. **执行质量 (execution_quality) 0–10 分**：工具调用是否成功？有没有错误？
  - 全部成功且查到数据 → 高分（8-10）
  - 全部成功但部分无数据 → 中等偏高（6-7）
  - 成功率 ≥ 80% → 中等（4-5）
  - 有错误但尝试反思纠错 → 有一定价值（3-4）
  - 大量错误且无纠错 → 低分（0-2）
  - 无工具调用 → 中性（5）

C. **回答可信度 (response_grounding) 0–10 分**：答案是否基于工具返回的真实数据？
  - 明确引用价格和平台名 → 高分（8-10）
  - 引用价格或平台之一 → 中等偏高（6-7）
  - 含规格关键词（GB/mAh/英寸/处理器等）→ 中等（4-5）
  - 仅结论性推荐，无具体数据 → 较低（2-3）
  - 无明确数据引用 → 低分（0-1）
  - 无工具调用时：答案 ≥ 100 字给 3-4 分，≥ 20 字给 1-2 分
  - ⚠️ 答案短于 50 字且有工具调用 → 上限 3 分

D. **数据完整度 (data_completeness) 0–10 分**：trace 结构是否完整？
  - 有 system prompt (+2)、有用户查询 (+2)
  - 有工具调用 (+3)、所有 tool_call 都有对应 result (+3)
  - 部分有 result (+1)、无工具但有答案 (+2)

额外检查：
- **幻觉检测 (hallucination)**：回答中是否包含工具返回数据中没有的具体信息（如价格数字、产品名）？通过/不通过

请以 JSON 格式返回评估结果，不要包含其他文字：
{
  "overall_score": 1-100,
  "dimensions": {
    "agent_capability": 1-10,
    "execution_quality": 1-10,
    "response_grounding": 1-10,
    "data_completeness": 1-10
  },
  "hallucination": "通过" | "不通过",
  "summary": "一句话总结评估结论",
  "issues": ["问题1", "问题2"]
}"""


def build_judge_user_prompt(sample: dict) -> str:
    """构建 LLM Judge 的用户 prompt，格式化展示训练样本"""

    # 提取关键信息
    query = sample.get("query", "")
    messages = sample.get("messages", [])

    parts = ["请评估以下 Agent 训练样本：\n"]

    # System prompt
    sys_msg = next((m for m in messages if m["role"] == "system"), None)
    if sys_msg:
        parts.append(f"## System Prompt\n{sys_msg['content'][:500]}\n")

    # User query
    parts.append(f"## 用户查询\n{query}\n")

    # Tool calls
    tool_calls = [m for m in messages if m["role"] == "assistant" and m.get("tool_calls")]
    if tool_calls:
        parts.append("## 工具调用")
        for tc_msg in tool_calls:
            for tc in tc_msg["tool_calls"]:
                fn = tc["function"]
                parts.append(f"- {fn['name']}({fn['arguments'][:200]})")

    # Tool results (truncated)
    tool_msgs = [m for m in messages if m["role"] == "tool"]
    if tool_msgs:
        parts.append("\n## 工具返回（摘要）")
        for tm in tool_msgs:
            content = tm["content"]
            # 尝试提取关键信息
            try:
                data = json.loads(content)
                if "raw_data" in data:
                    rd = data["raw_data"]
                    parts.append(f"- found={rd.get('found')}, matches={rd.get('total_matches')}, "
                                f"platforms={rd.get('platform_count')}")
                elif "references" in data:
                    parts.append(f"- knowledge_refs={len(data.get('references', []))}")
                else:
                    parts.append(f"- {str(data)[:150]}")
            except (json.JSONDecodeError, TypeError):
                parts.append(f"- {content[:150]}")

    # Final answer
    final = next((m for m in reversed(messages) if m["role"] == "assistant" and m.get("content")), None)
    if final:
        parts.append(f"\n## 最终回答\n{final['content'][:800]}\n")

    parts.append("\n请返回 JSON 格式的评估结果。")

    return "\n".join(parts)


def judge_sample(sample: dict, api_key: str = None, base_url: str = None) -> dict:
    """用 LLM 评估单个训练样本

    Args:
        sample: 训练样本 dict（含 messages, tools, query 等）
        api_key: API key（默认从环境变量 DEEPSEEK_API_KEY 读取）
        base_url: API base URL（默认 https://api.deepseek.com）

    Returns:
        {"overall_score": 85, "dimensions": {...}, "hallucination": "通过", ...}
    """
    import os
    api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise ValueError("未设置 DEEPSEEK_API_KEY 环境变量")

    base_url = base_url or "https://api.deepseek.com"

    from openai import OpenAI
    client = OpenAI(api_key=api_key, base_url=base_url)

    user_prompt = build_judge_user_prompt(sample)

    try:
        resp = client.chat.completions.create(
            model="deepseek-chat",  # 评估任务用通用模型即可
            messages=[
                {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,  # 低温度保证一致性
            max_tokens=800,
            response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content
        result = json.loads(content)
        # 确保字段完整
        result.setdefault("overall_score", 0)
        result.setdefault("dimensions", {})
        result.setdefault("hallucination", "未知")
        result.setdefault("summary", "")
        result.setdefault("issues", [])
        return result
    except Exception as e:
        return {
            "overall_score": 0,
            "dimensions": {},
            "hallucination": "未知",
            "summary": f"评估失败: {str(e)[:100]}",
            "issues": [str(e)[:200]],
            "error": True,
        }
