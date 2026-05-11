import json
import concurrent.futures
from typing import Dict, List, Callable, Optional
from openai import OpenAI
from .prompts import SYSTEM_PROMPT

# 滑动窗口配置
MAX_HISTORY_ROUNDS = 6
MAX_HISTORY_CHARS = 6000

# Plan-Execute 配置
MAX_PLAN_STEPS = 8

# 复杂度判断关键词
COMPLEXITY_KEYWORDS = [
    "对比", "比较", "vs", "和", "与", "以及", "还有",
    "分析", "推荐", "建议", "哪个更", "怎么选", "哪个好",
    "并且", "同时", "还要", "另外", "分别",
]


def _build_tools_description(tools: List[Dict]) -> str:
    """将 tools schema 转为可读文本供 plan prompt 使用"""
    lines = []
    for t in tools:
        func = t.get("function", {})
        name = func.get("name", "")
        desc = func.get("description", "")
        params = func.get("parameters", {}).get("properties", {})
        param_str = ", ".join(
            f"{k}: {v.get('type', '?')}" for k, v in params.items()
        )
        lines.append(f"- {name}({param_str}): {desc}")
    return "\n".join(lines)


class ReActAgent:
    """ReAct 推理引擎，支持 Plan-Execute 策略和滑动窗口上下文"""

    def __init__(
        self,
        client: OpenAI,
        model: str,
        tools: List[Dict],
        tool_map: Dict[str, Callable],
        max_round: int = 5
    ):
        self.client = client
        self.model = model
        self.tools = tools
        self.tool_map = tool_map
        self.max_round = max_round

    # ── 入口 ──────────────────────────────────────────────────────────

    def run(
        self,
        user_query: str,
        history: Optional[List[Dict]] = None,
        verbose: bool = True
    ) -> str:
        """
        运行 Agent。复杂 query 走 Plan-Execute，简单 query 走传统 ReAct。

        :param user_query: 当前用户输入
        :param history:   历史对话，格式 [{"role":"user","content":"..."}, ...]
        :param verbose:   是否打印推理过程
        :return:          最终答案
        """
        if history:
            history = self._slide_window(history)

        # 复杂度判断
        if self._is_complex(user_query):
            if verbose:
                print(f"\n[Plan-Execute] 检测到复杂 query，启用规划模式")
            return self._plan_and_execute(user_query, history, verbose)

        return self._react_loop(user_query, history, verbose)

    # ── Plan-Execute 模式 ─────────────────────────────────────────────

    def _is_complex(self, query: str) -> bool:
        """判断是否需要用 Plan-Execute 策略"""
        if any(kw in query for kw in COMPLEXITY_KEYWORDS):
            return True
        # 多个商品名（简单启发式：两个以上已知品牌/型号关键词）
        product_hints = ["iPhone", "小米", "iPad", "AirPods", "华为", "平板", "手机"]
        count = sum(1 for h in product_hints if h.lower() in query.lower())
        return count >= 2

    def _plan_and_execute(
        self,
        user_query: str,
        history: Optional[List[Dict]],
        verbose: bool
    ) -> str:
        """Plan-Execute 主流程"""

        # ── Phase 1: Plan ──
        plan = self._generate_plan(user_query, history, verbose)
        if plan is None:
            # LLM 判定为 simple，回退
            if verbose:
                print(f"[Plan-Execute] LLM 判定为简单 query，回退 ReAct")
            return self._react_loop(user_query, history, verbose)

        # ── Phase 2: Execute ──
        observations = self._execute_plan(plan, verbose)

        # ── Phase 3: Synthesize ──
        return self._synthesize(user_query, plan, observations, history, verbose)

    def _generate_plan(
        self,
        user_query: str,
        history: Optional[List[Dict]],
        verbose: bool
    ) -> Optional[List[Dict]]:
        """Phase 1: LLM 生成执行计划"""
        tools_desc = _build_tools_description(self.tools)

        plan_prompt = f"""分析用户 query 并生成执行计划。只输出 JSON，不要其他文字。

## 可用工具
{tools_desc}

## 用户 query
{user_query}

## 输出格式
{{
  "complexity": "simple|complex",
  "reasoning": "为什么 simple 或 complex",
  "plan": [
    {{
      "step": 1,
      "tool": "工具名称",
      "args": {{"参数名": "参数值"}},
      "depends_on": null,
      "purpose": "这一步的目的"
    }}
  ]
}}

## 规则
1. 如果只需要 1 个工具且无需后续分析 → complexity: "simple"，plan 为空数组
2. 如果需要 2+ 个独立查询或综合分析 → complexity: "complex"，列出所有步骤
3. 没有依赖关系的步骤标记 depends_on: null（可并行执行）
4. 有依赖关系时标记 depends_on: 前置步骤的 step 编号
5. 尽量并行化，步骤数 ≤ {MAX_PLAN_STEPS}"""

        messages = [{"role": "system", "content": plan_prompt}]
        if history:
            messages.append({"role": "system", "content": "## 历史对话上下文（用于理解指代）"})
            messages.extend(history)
        messages.append({"role": "user", "content": user_query})

        if verbose:
            print(f"\n[Phase 1] 生成执行计划...")

        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0,
                max_tokens=800,
            )
            raw = resp.choices[0].message.content.strip()
            raw = raw.strip("`").lstrip("json").strip()
            plan_data = json.loads(raw)

            if plan_data.get("complexity") == "simple":
                return None

            steps = plan_data.get("plan", [])
            if verbose:
                print(f"[Phase 1] 计划 {len(steps)} 步：")
                for s in steps:
                    dep = f" (依赖 step {s['depends_on']})" if s.get("depends_on") else ""
                    print(f"  Step {s['step']}: {s['tool']}{dep} — {s.get('purpose', '')}")

            return steps
        except Exception as e:
            if verbose:
                print(f"[Phase 1] Plan 生成失败: {e}，回退 ReAct")
            return None

    def _execute_plan(
        self,
        steps: List[Dict],
        verbose: bool
    ) -> Dict[int, Dict]:
        """Phase 2: 按依赖关系分组并行执行"""
        if verbose:
            print(f"\n[Phase 2] 执行计划...")

        # 按 depends_on 分组
        independent = []
        dependent = []

        for s in steps:
            if s.get("depends_on") is None:
                independent.append(s)
            else:
                dependent.append(s)

        results = {}
        errors = {}

        # 无依赖组 → 并行执行
        if independent:
            if verbose:
                print(f"  并行执行 {len(independent)} 个步骤...")

            with concurrent.futures.ThreadPoolExecutor(
                max_workers=min(len(independent), 4)
            ) as executor:
                futures = {}
                for step in independent:
                    f = executor.submit(
                        self._call_tool_safe,
                        step["tool"],
                        step.get("args", {}),
                    )
                    futures[f] = step

                for f in concurrent.futures.as_completed(futures):
                    step = futures[f]
                    try:
                        results[step["step"]] = f.result(timeout=30)
                        if verbose:
                            print(f"  ✓ Step {step['step']}: {step['tool']} 完成")
                    except Exception as e:
                        errors[step["step"]] = str(e)
                        results[step["step"]] = {"error": str(e)}
                        if verbose:
                            print(f"  ✗ Step {step['step']}: {step['tool']} 失败 — {e}")

        # 有依赖组 → 串行执行
        for step in dependent:
            dep = step["depends_on"]
            dep_result = results.get(dep, {})
            # 注入依赖结果（如果 args 中有占位符）
            args = step.get("args", {})
            if verbose:
                print(f"  Step {step['step']}: {step['tool']} (依赖 Step {dep})")

            try:
                results[step["step"]] = self._call_tool_safe(step["tool"], args)
                if verbose:
                    print(f"  ✓ Step {step['step']}: {step['tool']} 完成")
            except Exception as e:
                errors[step["step"]] = str(e)
                results[step["step"]] = {"error": str(e)}
                if verbose:
                    print(f"  ✗ Step {step['step']}: {step['tool']} 失败 — {e}")

        if errors and verbose:
            print(f"  共 {len(errors)} 个步骤失败")

        return results

    def _synthesize(
        self,
        user_query: str,
        plan: List[Dict],
        observations: Dict[int, Dict],
        history: Optional[List[Dict]],
        verbose: bool
    ) -> str:
        """Phase 3: LLM 综合所有 observation 生成最终答案"""
        if verbose:
            print(f"\n[Phase 3] 综合分析结果...")

        # 压缩 observation（只保留关键字段，避免超出 token 限制）
        obs_text_parts = []
        for step in plan:
            step_num = step["step"]
            obs = observations.get(step_num, {"error": "未执行"})
            purpose = step.get("purpose", "")

            if "formatted_text" in obs:
                # 工具返回了格式化文本，直接用
                obs_text_parts.append(f"## Step {step_num}: {purpose}\n{obs['formatted_text']}")
            elif "raw_data" in obs:
                # 提取关键数据
                raw = obs["raw_data"]
                if raw.get("found"):
                    cheapest = raw.get("cheapest", {})
                    obs_text_parts.append(
                        f"## Step {step_num}: {purpose}\n"
                        f"找到 {raw.get('total_matches', '?')} 个匹配，"
                        f"最便宜: {cheapest.get('platform_name', '?')} "
                        f"¥{cheapest.get('platform_price', '?')}"
                    )
                else:
                    obs_text_parts.append(f"## Step {step_num}: {purpose}\n未找到匹配")
            elif "error" in obs:
                obs_text_parts.append(f"## Step {step_num}: {purpose}\n执行失败: {obs['error']}")
            else:
                obs_text_parts.append(
                    f"## Step {step_num}: {purpose}\n{json.dumps(obs, ensure_ascii=False, indent=2)[:500]}"
                )

        obs_combined = "\n\n".join(obs_text_parts)

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
        ]
        if history:
            messages.extend(history)
        messages.append({
            "role": "user",
            "content": f"用户问题：{user_query}\n\n以下是工具查询结果，请综合分析并回答：\n\n{obs_combined}"
        })

        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.3,
                max_tokens=1500,
            )
            answer = resp.choices[0].message.content
            if verbose:
                print(f"[Phase 3] 答案生成完成 ({len(answer)} 字符)")
            return answer
        except Exception as e:
            if verbose:
                print(f"[Phase 3] 合成失败: {e}")
            return f"综合分析时出错: {e}\n\n原始查询结果:\n{obs_combined[:1000]}"

    def _call_tool_safe(self, tool_name: str, args: Dict) -> Dict:
        """安全调用工具，捕获异常"""
        func = self.tool_map.get(tool_name)
        if func is None:
            return {"error": f"未知工具: {tool_name}"}
        return func(**args)

    # ── 传统 ReAct 模式 ───────────────────────────────────────────────

    def _react_loop(
        self,
        user_query: str,
        history: Optional[List[Dict]],
        verbose: bool
    ) -> str:
        """传统 ReAct 循环（用于简单 query 或 Plan-Execute 回退）"""
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]

        if history:
            messages.extend(history)

        messages.append({"role": "user", "content": user_query})

        for round_num in range(self.max_round):
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=self.tools,
                tool_choice="auto"
            )
            response_msg = response.choices[0].message
            thoughts = response_msg.content or "正在调用工具获取数据..."

            if verbose:
                print(f"\n【Round {round_num + 1} - Thought】{thoughts}")

            if not response_msg.tool_calls:
                return response_msg.content

            tool_call = response_msg.tool_calls[0]
            tool_name = tool_call.function.name
            tool_args = json.loads(tool_call.function.arguments)

            if verbose:
                print(f"【Action】调用工具：{tool_name}，参数：{tool_args}")

            try:
                tool_func = self.tool_map[tool_name]
                observation = tool_func(**tool_args)
            except Exception as e:
                observation = {"error": f"工具执行失败：{str(e)}"}

            observation_str = json.dumps(observation, ensure_ascii=False, indent=2)

            if verbose:
                print(f"【Observation】{observation_str}")

            messages.append(response_msg)
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": observation_str
            })

        return "已达到最大推理轮次，无法完成回答"

    # ── 滑动窗口 ──────────────────────────────────────────────────────

    def _slide_window(self, history: List[Dict]) -> List[Dict]:
        """滑动窗口截断历史消息"""
        clean = [m for m in history if m.get("role") in ("user", "assistant")]

        if len(clean) > MAX_HISTORY_ROUNDS * 2:
            clean = clean[-(MAX_HISTORY_ROUNDS * 2):]

        total_chars = sum(len(m.get("content", "")) for m in clean)
        while total_chars > MAX_HISTORY_CHARS and len(clean) >= 2:
            clean.pop(0)
            if clean and clean[0].get("role") == "assistant":
                clean.pop(0)
            total_chars = sum(len(m.get("content", "")) for m in clean)

        return clean
