import json
import re
import concurrent.futures
from typing import Dict, List, Callable, Optional
from openai import OpenAI
from .prompts import SYSTEM_PROMPT, PLAN_PROMPT_TEMPLATE


class ReActAgent:
    """ReAct 推理引擎，支持 Plan-Execute 策略、滑动窗口上下文、自反思纠错"""

    def __init__(
        self,
        client: OpenAI,
        model: str,
        tools: List[Dict],
        tool_map: Dict[str, Callable],
        max_round: int = 5,
        config: Optional[Dict] = None,
    ):
        self.client = client
        self.model = model  # 默认/兜底模型
        self.tools = tools
        self.tool_map = tool_map
        self.max_round = max_round

        # 配置参数（可从 Settings 传入）
        cfg = config or {}

        # ── 多模型路由：不同阶段使用不同模型 ──
        self.model_react = cfg.get("model_react", model)        # ReAct 循环（默认模型）
        self.model_plan = cfg.get("model_plan", model)          # Phase 1 计划生成
        self.model_synthesize = cfg.get("model_synthesize", model)  # Phase 3 综合回答

        self.max_plan_steps = cfg.get("max_plan_steps", 8)
        self.max_history_rounds = cfg.get("max_history_rounds", 6)
        self.max_history_chars = cfg.get("max_history_chars", 6000)
        self.complexity_keywords = cfg.get("complexity_keywords", [
            "对比", "比较", "vs", "和", "与", "以及", "还有",
            "分析", "推荐", "建议", "哪个更", "怎么选", "哪个好",
            "并且", "同时", "还要", "另外", "分别",
        ])
        self.complexity_patterns = cfg.get("complexity_patterns", [
            r".*(?:和|与|以及).*(?:都|分别|各).*",
            r".*(?:哪|什么|怎么).*(?:更|最|比较).*",
            r".*(?:除了|还有|另外).*",
        ])
        self.max_reflection_retries = cfg.get("max_reflection_retries", 2)
        self.auto_relax_attributes = cfg.get("auto_relax_attributes", True)

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

        if self._is_complex(user_query):
            if verbose:
                print(f"\n[Plan-Execute] 检测到复杂 query，启用规划模式")
            return self._plan_and_execute(user_query, history, verbose)

        return self._react_loop(user_query, history, verbose)

    # ── 复杂度判断 ────────────────────────────────────────────────────

    def _is_complex(self, query: str) -> bool:
        """判断是否需要用 Plan-Execute 策略（关键词 + 结构模式）"""
        # 关键词匹配
        if any(kw in query for kw in self.complexity_keywords):
            return True
        # 结构模式匹配（如"A和B都查一下"、"哪个更划算"）
        for pattern in self.complexity_patterns:
            if re.search(pattern, query):
                return True
        # 多商品检测：统计已知商品关键词出现次数
        product_hints = self._load_product_hints()
        count = sum(1 for h in product_hints if h.lower() in query.lower())
        return count >= 2

    def _load_product_hints(self) -> List[str]:
        """从数据库动态加载商品名称作为 hints（失败时返回默认列表）"""
        try:
            from platforms.platform_database import PlatformDatabase
            hints = set()
            for pid in ["jd", "taobao", "pdd", "suning"]:
                try:
                    db = PlatformDatabase(pid)
                    products = db.query_all_products()
                    for p in products:
                        name = p.get("product_name", "")
                        # 提取品牌词（第一个空格前）
                        brand = name.split()[0] if name else ""
                        if brand:
                            hints.add(brand)
                    db.close()
                except Exception:
                    pass
            return list(hints) if hints else ["iPhone", "小米", "iPad", "AirPods", "华为"]
        except Exception:
            return ["iPhone", "小米", "iPad", "AirPods", "华为"]

    # ── Plan-Execute 模式 ─────────────────────────────────────────────

    def _plan_and_execute(
        self,
        user_query: str,
        history: Optional[List[Dict]],
        verbose: bool
    ) -> str:
        """Plan-Execute 主流程"""

        plan = self._generate_plan(user_query, history, verbose)
        if plan is None:
            if verbose:
                print(f"[Plan-Execute] LLM 判定为简单 query，回退 ReAct")
            return self._react_loop(user_query, history, verbose)

        observations = self._execute_plan(plan, verbose)

        return self._synthesize(user_query, plan, observations, history, verbose)

    def _generate_plan(
        self,
        user_query: str,
        history: Optional[List[Dict]],
        verbose: bool
    ) -> Optional[List[Dict]]:
        """Phase 1: LLM 生成执行计划（含复杂度判断和依赖引用语法）"""
        tools_desc = self._build_tools_description()
        plan_prompt = PLAN_PROMPT_TEMPLATE.format(
            tools_desc=tools_desc,
            user_query=user_query,
            max_steps=self.max_plan_steps,
        )

        messages = [{"role": "system", "content": plan_prompt}]
        if history:
            messages.append({"role": "system", "content": "## 历史对话上下文（用于理解指代）"})
            messages.extend(history)
        messages.append({"role": "user", "content": user_query})

        if verbose:
            print(f"\n[Phase 1] 生成执行计划...")

        try:
            resp = self.client.chat.completions.create(
                model=self.model_plan,
                messages=messages,
                temperature=0,
                max_tokens=800,
            )
            raw = resp.choices[0].message.content.strip()
            raw = raw.strip("`").lstrip("json").strip()
            plan_data = json.loads(raw)

            if verbose:
                plan_model_used = self.model_plan
                if plan_model_used != self.model:
                    print(f"[Phase 1] 使用模型: {plan_model_used}")

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
        """Phase 2: 按依赖关系分组并行执行，支持 $step{N} 引用解析和自反思重试"""
        if verbose:
            print(f"\n[Phase 2] 执行计划...")

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
                        raw_result = f.result(timeout=30)
                        results[step["step"]] = self._check_and_retry(
                            step, raw_result, verbose
                        )
                        if verbose:
                            print(f"  ✓ Step {step['step']}: {step['tool']} 完成")
                    except Exception as e:
                        errors[step["step"]] = str(e)
                        results[step["step"]] = {"error": str(e)}
                        if verbose:
                            print(f"  ✗ Step {step['step']}: {step['tool']} 失败 — {e}")

        # 有依赖组 → 串行执行（解析 $step{N} 引用）
        for step in dependent:
            dep = step["depends_on"]
            args = self._resolve_step_refs(step.get("args", {}), results)

            if verbose:
                print(f"  Step {step['step']}: {step['tool']} (依赖 Step {dep})")

            try:
                raw_result = self._call_tool_safe(step["tool"], args)
                results[step["step"]] = self._check_and_retry(
                    step, raw_result, verbose
                )
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

    # ── $step{N} 引用解析 ─────────────────────────────────────────────

    def _resolve_step_refs(
        self, args: Dict, results: Dict[int, Dict]
    ) -> Dict:
        """解析 args 中的 $step{N}.path.to.field 引用"""
        resolved = {}
        for key, value in args.items():
            if isinstance(value, str) and value.startswith("$step"):
                resolved[key] = self._deref(value, results)
            else:
                resolved[key] = value
        return resolved

    def _deref(self, ref: str, results: Dict[int, Dict]):
        """解析单个 $step{N}.path.to.field 引用"""
        m = re.match(r'\$step(\d+)\.(.+)', ref)
        if not m:
            return ref
        step_num = int(m.group(1))
        path = m.group(2).split('.')
        result = results.get(step_num, {})
        for p in path:
            if isinstance(result, dict):
                result = result.get(p)
            else:
                return ref  # 无法继续解析
            if result is None:
                return ref
        return result

    # ── 自反思重试 ────────────────────────────────────────────────────

    def _check_and_retry(
        self,
        step: Dict,
        result: Dict,
        verbose: bool,
    ) -> Dict:
        """
        检查工具返回结果，如果为空/未找到且条件允许，自动放宽属性重试。
        """
        if not self.auto_relax_attributes:
            return result

        # 判断是否为空结果
        is_empty = False
        if "raw_data" in result:
            rd = result["raw_data"]
            is_empty = (not rd.get("found")) or (rd.get("total_matches", 0) == 0)
        elif "error" in result:
            return result  # 执行错误，不重试

        if not is_empty:
            return result

        args = step.get("args", {})
        color = args.get("color")
        memory = args.get("memory")
        product_name = args.get("product_name", "")

        if not (color or memory):
            return result  # 没有可放宽的属性

        if verbose:
            removed = []
            if color:
                removed.append(f"color={color}")
            if memory:
                removed.append(f"memory={memory}")
            print(f"  🔄 Step {step['step']}: 空结果，放宽属性 ({', '.join(removed)}) 重试...")

        relaxed_args = {k: v for k, v in args.items() if k not in ("color", "memory")}
        relaxed_args["color"] = None
        relaxed_args["memory"] = None

        retry_result = self._call_tool_safe(step["tool"], relaxed_args)

        if "raw_data" in retry_result:
            retry_result.setdefault("raw_data", {})
            retry_result["raw_data"]["_auto_relaxed"] = True
        if verbose:
            found = False
            if "raw_data" in retry_result:
                found = retry_result["raw_data"].get("found", False)
            print(f"  {'✓' if found else '✗'} Step {step['step']}: 放宽重试 {'找到结果' if found else '仍为空'}")

        return retry_result

    # ── Phase 3: Synthesize ───────────────────────────────────────────

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

        obs_text_parts = []
        all_empty = True

        for step in plan:
            step_num = step["step"]
            obs = observations.get(step_num, {"error": "未执行"})
            purpose = step.get("purpose", "")

            if "formatted_text" in obs:
                obs_text_parts.append(f"## Step {step_num}: {purpose}\n{obs['formatted_text']}")
                if "未找到" not in obs["formatted_text"] and "未找到" not in obs.get("raw_data", {}).get("message", ""):
                    all_empty = False
            elif "raw_data" in obs:
                raw = obs["raw_data"]
                if raw.get("found"):
                    all_empty = False
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

        # 全部为空时，引导 LLM 进行澄清追问
        clarification_hint = ""
        if all_empty:
            clarification_hint = (
                "\n\n**注意**：以上所有查询均未找到匹配结果。请根据 SYSTEM_PROMPT 中的"
                "「错误处理与追问策略」给出回复：告知用户未找到，建议用户简化关键词或"
                "尝试其他商品名称，并列出数据库中已有的相似商品（如果已知）。"
            )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
        ]
        if history:
            messages.extend(history)
        messages.append({
            "role": "user",
            "content": f"用户问题：{user_query}\n\n以下是工具查询结果，请综合分析并回答：\n\n{obs_combined}{clarification_hint}"
        })

        try:
            if verbose and self.model_synthesize != self.model:
                print(f"[Phase 3] 使用模型: {self.model_synthesize}")
            resp = self.client.chat.completions.create(
                model=self.model_synthesize,
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
        """安全调用工具，过滤掉工具不接受的关键词参数"""
        func = self.tool_map.get(tool_name)
        if func is None:
            return {"error": f"未知工具: {tool_name}"}
        # 过滤掉 _ 开头的内部参数
        clean_args = {k: v for k, v in args.items() if not k.startswith("_")}
        return func(**clean_args)

    def _build_tools_description(self) -> str:
        """将 tools schema 转为可读文本供 plan prompt 使用"""
        lines = []
        for t in self.tools:
            func = t.get("function", {})
            name = func.get("name", "")
            desc = func.get("description", "")
            params = func.get("parameters", {}).get("properties", {})
            param_str = ", ".join(
                f"{k}: {v.get('type', '?')}" for k, v in params.items()
            )
            lines.append(f"- {name}({param_str}): {desc}")
        return "\n".join(lines)

    # ── 传统 ReAct 模式 ───────────────────────────────────────────────

    def _react_loop(
        self,
        user_query: str,
        history: Optional[List[Dict]],
        verbose: bool
    ) -> str:
        """传统 ReAct 循环（含自反思纠错机制）"""
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]

        if history:
            messages.extend(history)

        messages.append({"role": "user", "content": user_query})

        empty_result_count = {}  # 记录各工具连续空结果次数

        for round_num in range(self.max_round):
            if round_num == 0 and verbose and self.model_react != self.model:
                print(f"[ReAct] 使用模型: {self.model_react}")
            response = self.client.chat.completions.create(
                model=self.model_react,
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
                print(f"【Observation】{observation_str[:500]}{'...' if len(observation_str) > 500 else ''}")

            # ── 自反思：检测空结果并引导 LLM 重试或追问 ──
            is_empty = self._is_empty_result(observation)

            if is_empty:
                empty_result_count[tool_name] = empty_result_count.get(tool_name, 0) + 1

                if empty_result_count[tool_name] <= self.max_reflection_retries:
                    reflection_msg = self._build_reflection_message(
                        tool_name, tool_args, observation, empty_result_count[tool_name]
                    )
                    if verbose:
                        print(f"【Reflection】{reflection_msg}")
                    messages.append({
                        "role": "system",
                        "content": reflection_msg
                    })
                    # 不把空结果的 tool message 加入，让 LLM 重新选择工具
                    continue

            # 重置空结果计数（非空结果）
            empty_result_count.pop(tool_name, None)

            messages.append(response_msg)
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": observation_str
            })

        return "已达到最大推理轮次，无法完成回答"

    def _is_empty_result(self, observation: Dict) -> bool:
        """判断工具返回是否为空/未找到"""
        if isinstance(observation, dict):
            if observation.get("error"):
                return False  # 错误不算空结果
            if "raw_data" in observation:
                rd = observation["raw_data"]
                # multi_platform_price_comparison 格式：有 found 字段
                if "found" in rd:
                    return not rd["found"] or rd.get("total_matches", 0) == 0
                # get_all_platform_products 格式：有 results 字段
                if "results" in rd and isinstance(rd["results"], dict):
                    return all(
                        len(v.get("products", [])) == 0
                        for v in rd["results"].values()
                        if isinstance(v, dict)
                    )
            if "success" in observation:
                return not observation["success"]
            if "results" in observation and isinstance(observation["results"], dict):
                return all(
                    len(v.get("products", [])) == 0
                    for v in observation["results"].values()
                    if isinstance(v, dict)
                )
        return False

    def _build_reflection_message(
        self,
        tool_name: str,
        tool_args: Dict,
        observation: Dict,
        retry_count: int,
    ) -> str:
        """构建反思提示消息"""
        has_attrs = bool(tool_args.get("color") or tool_args.get("memory"))

        lines = [
            f"⚠️ 工具 `{tool_name}` 返回了空结果（未找到匹配）。这是第 {retry_count} 次空结果。",
            "",
            "请反思并决定下一步：",
        ]

        if has_attrs and retry_count == 1:
            lines.append(
                "1. **放宽属性重试**：去掉 color/memory 等筛选条件，只用商品核心名称重新查询。"
            )
            lines.append(
                "2. **换工具尝试**：用 get_all_platform_products 查看所有可用商品。"
            )
        elif retry_count >= 2:
            lines.append(
                "1. **停止重试**：数据库中没有该商品，请直接告知用户并给出建议。"
            )
            lines.append(
                "2. **提供替代**：列出数据库中已有的相似或相关商品供用户参考。"
            )
        else:
            lines.append(
                "1. **宽泛搜索**：尝试用更短/更通用的关键词重新查询。"
            )
            lines.append(
                "2. **确认后追问**：如果确认无结果，向用户澄清并询问更多信息。"
            )

        lines.append("")
        lines.append("不要在 Thought 中说'我应该'，直接用 Action 执行你选择的方案。")

        return "\n".join(lines)

    # ── 滑动窗口 ──────────────────────────────────────────────────────

    def _slide_window(self, history: List[Dict]) -> List[Dict]:
        """滑动窗口截断历史消息"""
        clean = [m for m in history if m.get("role") in ("user", "assistant")]

        if len(clean) > self.max_history_rounds * 2:
            clean = clean[-(self.max_history_rounds * 2):]

        total_chars = sum(len(m.get("content", "")) for m in clean)
        while total_chars > self.max_history_chars and len(clean) >= 2:
            clean.pop(0)
            if clean and clean[0].get("role") == "assistant":
                clean.pop(0)
            total_chars = sum(len(m.get("content", "")) for m in clean)

        return clean
