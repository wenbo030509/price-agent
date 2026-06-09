import json
import re
import time
import threading
import concurrent.futures
from dataclasses import dataclass, field
from typing import Dict, List, Callable, Optional, Generator, Set
from openai import OpenAI
from .prompts import (SYSTEM_PROMPT, PLAN_PROMPT_TEMPLATE,
                       COMMON_ROLE, COMMON_RULES, COMMON_FORMAT, COMMON_ERROR_HANDLING)
from .skills.loader import SkillLoader, SkillDef
from .trace import TraceCollector, TraceEvent, EventType


# ── 意图分类触发词 ──────────────────────────────────────────────────────────

# 使用场景触发词 → use_case 标签的映射
USE_CASE_TRIGGER_MAP: Dict[str, str] = {
    # gaming
    "游戏": "gaming", "打游戏": "gaming", "电竞": "gaming",
    "帧率": "gaming", "散热好": "gaming", "吃鸡": "gaming",
    # photography
    "拍照": "photography", "摄影": "photography", "相机": "photography",
    "vlog": "photography", "拍视频": "photography", "夜拍": "photography",
    # battery
    "续航": "battery", "大电池": "battery", "耐用": "battery",
    "不充电": "battery", "省电": "battery",
    # business
    "商务": "business", "办公": "business", "轻薄": "business",
    # student
    "学生": "student", "上学": "student", "学习用": "student",
    # budget
    "便宜": "budget", "实惠": "budget", "入门": "budget", "性价比": "budget",
    # flagship
    "旗舰": "flagship", "高端": "flagship", "顶配": "flagship",
}

# 处理器关键词（补充触发推荐意图）
_PROCESSOR_TRIGGERS = [
    "骁龙", "天玑", "麒麟", "猎户座", "高通", "联发科",
    "A17", "A16", "A15", "A14", "M2", "M3",
    "8Gen", "8gen", "9Gen", "9gen", "9300", "9200",
]


# ── M5: ShoppingContext 状态机 ──────────────────────────────────────────

@dataclass
class ShoppingContext:
    """购物上下文 — 跨多轮持久化"""
    phase: str = "greeting"          # greeting | slot_filling | searching | recommending | comparing | follow_up
    slots: Dict = field(default_factory=dict)
    candidates: List = field(default_factory=list)
    compare_basket: List = field(default_factory=list)
    question_count: int = 0
    last_recommendation: Optional[Dict] = None

    def reset(self):
        self.phase = "greeting"
        self.slots.clear()
        self.candidates.clear()
        self.compare_basket.clear()
        self.question_count = 0
        self.last_recommendation = None

    def add_slot(self, key: str, value):
        self.slots[key] = value

    def get_missing_required(self, slot_defs: list) -> list:
        return [s for s in slot_defs if s.get("required") and s["name"] not in self.slots]


class ReActAgent:
    """ReAct 推理引擎，支持 Plan-Execute 策略、滑动窗口上下文、自反思纠错"""

    def __init__(
        self,
        client: OpenAI,
        model: str,
        tools: List[Dict],
        tool_map: Dict[str, Callable],
        max_round: int = 10,
        config: Optional[Dict] = None,
    ):
        self.client = client
        self.model = model  # 默认/兜底模型
        self.tools = tools
        self.tool_map = tool_map
        self.max_round = max_round

        # 配置参数（可从 Settings 传入）
        cfg = config or {}

        # 保存最近一次运行的完整 messages（供 trace 持久化，M6 训练数据提取使用）
        self._last_messages: Optional[List[Dict]] = None

        # ── 多模型路由：不同阶段使用不同模型 ──
        self.model_react = cfg.get("model_react", model)        # ReAct 循环（默认模型）
        self.model_plan = cfg.get("model_plan", model)          # Phase 1 计划生成
        self.model_synthesize = cfg.get("model_synthesize", model)  # Phase 3 综合回答
        self.model_vision = cfg.get("model_vision", model)      # VLM 图片识别模型

        self.max_plan_steps = cfg.get("max_plan_steps", 8)
        self.max_history_rounds = cfg.get("max_history_rounds", 6)
        self.max_history_chars = cfg.get("max_history_chars", 6000)
        self.complexity_keywords = cfg.get("complexity_keywords", [
            "对比", "比较", "vs", "和", "与", "以及", "还有",
            "分析", "哪个更", "怎么选", "哪个好",
            "并且", "同时", "还要", "另外", "分别",
        ])
        self.complexity_patterns = cfg.get("complexity_patterns", [
            r".*(?:和|与|以及).*(?:都|分别|各).*",
            r".*(?:哪|什么|怎么).*(?:更|最|比较).*",
            r".*(?:除了|还有|另外).*",
        ])
        self.max_reflection_retries = cfg.get("max_reflection_retries", 2)
        self.auto_relax_attributes = cfg.get("auto_relax_attributes", True)
        self.max_step_react_rounds = cfg.get("max_step_react_rounds", 2)

        # M1: 行业配置
        self.industry_config = cfg.get("industry_config", {})

        # M5: 购物上下文
        self.shopping_context = ShoppingContext()

        # Trace 事件收集器（推理可视化）
        self.trace = TraceCollector()

        # Skills 架构：LLM 按需加载 Skill（SKILL.md 文件驱动）
        self.skill_loader = SkillLoader()
        self._loaded_skills: Dict[str, str] = {}  # skill_name → content

        # load_skill 元工具 schema（LLM 通过此工具按需加载 Skill）
        self._load_skill_tool_schema = {
            "type": "function",
            "function": {
                "name": "load_skill",
                "description": (
                    "加载一个专业技能模块的完整指令。当你判断当前任务需要特定领域知识或操作指南时调用。"
                    "加载后该技能的行为指导和工具选择规则将注入到上下文中。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "skill_name": {
                            "type": "string",
                            "description": self.skill_loader.get_catalog_for_tool(),
                        }
                    },
                    "required": ["skill_name"],
                },
            },
        }

    # ── LLM 调用（含重试） ────────────────────────────────────────────

    def _call_llm(self, max_retries=3, **kwargs):
        for attempt in range(1, max_retries + 1):
            try:
                return self.client.chat.completions.create(**kwargs)
            except Exception as e:
                err = str(e)[:120]
                retryable = any(s in err for s in
                    ["503", "502", "504", "429", "busy", "rate_limit", "timeout"])
                if not retryable or attempt >= max_retries:
                    raise
                wait = 2 ** attempt
                print(f"  ⚠ LLM 调用失败 (attempt {attempt}/{max_retries}): {err}")
                print(f"  ↻ {wait}s 后重试...")
                time.sleep(wait)

    # ── 入口 ──────────────────────────────────────────────────────────

    def run(
        self,
        user_query: str,
        history: Optional[List[Dict]] = None,
        verbose: bool = True,
        has_image: bool = False,
    ) -> str:
        """
        运行 Agent。根据意图分类路由到不同的执行模式。
        - recommendation：推荐型 → ReAct + intent hint
        - comparison：Plan-Execute
        - shopping：引导式购物 → ShoppingContext 状态机
        - query：ReAct

        Skills 架构：根据意图 + 上下文按需组合 prompt + 工具子集。
        """
        self.trace.reset()

        if history:
            history = self._slide_window(history)

        # ── 检测 /skill-name 用户显式调用 ──
        user_skill = self._extract_user_skill_invocation(user_query)
        if user_skill:
            skill_name, actual_query = user_skill
            content = self.skill_loader.get_content(skill_name)
            if content:
                self._loaded_skills[skill_name] = content
                if verbose:
                    print(f"\n[Skills] 用户调用 /{skill_name}")
                self.trace.skill_load(
                    skills=[skill_name],
                    prompt_chars=len(content),
                    tool_count=len(self._build_skill_tool_set()),
                    mode="user_invoked", source="user",
                )
                user_query = actual_query or user_query  # 去掉前缀
            elif verbose:
                print(f"\n[Skills] 未知技能: /{skill_name}，忽略")

        # ── M5: 购物状态机激活时，后续输入直接路由到引导式购物 ──
        # 不再经过意图分类，避免"打游戏""预算4000"等槽位回复被误判为
        # recommendation/comparison 而绕过 ShoppingContext
        if self.shopping_context.phase != "greeting":
            # 先检测话题切换（优先级高于结束购物，因为"算了帮我查XX"是切换不是结束）
            if self._is_topic_switch(user_query):
                if verbose:
                    print(f"\n[Shopping] 检测到话题切换，退出购物模式 → 正常路由")
                self.shopping_context.reset()
                # 继续走正常意图路由（不 return）
            elif self._is_ending_shopping(user_query):
                if verbose:
                    print(f"\n[Shopping] 用户退出购物模式")
                self.shopping_context.reset()
                return "好的！如果还有其他需要，随时告诉我。"
            else:
                if verbose:
                    print(f"\n[Shopping] 购物模式续 ({self.shopping_context.phase})")
                self.trace.intent(intent="shopping", query=user_query)
                self.trace.mode_select(mode="shopping", reason="购物引导模式（续）", model=self.model_react)
                # Skills: 按购物阶段重新预加载
                cont_skill_names = self._resolve_skills(
                    "shopping", has_image=has_image,
                    shopping_phase=self.shopping_context.phase,
                )
                self._preload_skills(cont_skill_names, verbose=verbose)
                cont_prompt = self._build_skill_system_prompt()
                self.trace.skill_load(
                    skills=list(self._loaded_skills.keys()),
                    prompt_chars=len(cont_prompt),
                    tool_count=len(self._build_skill_tool_set()),
                    mode="shopping", source="preload",
                )
                return self._guided_shopping(user_query, history, verbose,
                                             system_prompt_override=cont_prompt)

        intent = self._detect_intent(user_query)
        self.trace.intent(intent=intent, query=user_query, model_count=self._count_models(user_query))

        # ── Skills 架构：预加载 Skill + 构建 system prompt ──
        skill_names = self._resolve_skills(
            intent, has_image=has_image,
            shopping_phase=self.shopping_context.phase if intent == "shopping" else "",
        )
        self._preload_skills(skill_names, verbose=verbose)

        system_prompt = self._build_skill_system_prompt()
        tools_subset = self._build_tool_list_from_skills()

        self.trace.skill_load(
            skills=list(self._loaded_skills.keys()),
            prompt_chars=len(system_prompt),
            tool_count=len(tools_subset),
            mode=intent, source="preload",
        )

        if verbose:
            skills_str = ", ".join(self._loaded_skills.keys()) if self._loaded_skills else "fallback(全量)"
            print(f"[Skills] 激活: {skills_str} | prompt: {len(system_prompt)} chars | tools: {len(tools_subset)}")

        if intent == "recommendation":
            self.trace.mode_select(mode="react", reason="推荐型查询，启用语义推荐模式", model=self.model_react)
            if verbose:
                print(f"\n[Intent: recommendation] 启用语义推荐模式")
            return self._react_loop(user_query, history, verbose, intent_hint="recommendation",
                                    system_prompt_override=system_prompt,
                                    tools_override=tools_subset)

        elif intent == "comparison":
            self.trace.mode_select(mode="plan_execute", reason="对比型查询，启用 Plan-Execute 模式", model=self.model_react)
            if verbose:
                print(f"\n[Intent: comparison] 启用 Plan-Execute 对比模式")
            return self._plan_and_execute(user_query, history, verbose,
                                          system_prompt_override=system_prompt)

        elif intent == "shopping":
            self.trace.mode_select(mode="shopping", reason="购物引导模式", model=self.model_react)
            if verbose:
                print(f"\n[Intent: shopping] 启用引导式购物模式")
            return self._guided_shopping(user_query, history, verbose,
                                         system_prompt_override=system_prompt)

        else:  # query
            self.trace.mode_select(mode="react", reason="简单查询，ReAct 模式", model=self.model_react)
            return self._react_loop(user_query, history, verbose,
                                    system_prompt_override=system_prompt,
                                    tools_override=tools_subset)

    # ── 流式运行 ──────────────────────────────────────────────────────

    def run_stream(
        self,
        user_query: str,
        history: Optional[List[Dict]] = None,
        verbose: bool = True,
        has_image: bool = False,
    ) -> Generator[TraceEvent, None, None]:
        """在后台线程运行 Agent，yield 实时 TraceEvent 供 SSE 消费"""
        self.trace.start_stream()
        answer_container: List[str] = []

        def target():
            try:
                answer = self.run(user_query, history, verbose, has_image=has_image)
                answer_container.append(answer)
            except Exception as e:
                answer_container.append(f"处理出错: {e}")
            finally:
                self.trace.finish_stream(answer_container[0] if answer_container else "")

        thread = threading.Thread(target=target, daemon=True)
        thread.start()

        yield from self.trace.iter_events()

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

    # ── 意图分类 ────────────────────────────────────────────────────────

    def _detect_intent(self, query: str) -> str:
        """
        分类用户意图：
        - "recommendation"：推荐型，如"推荐游戏手机"、"5000以内什么手机好"
        - "comparison"：对比型，如"iPhone 15 和小米14哪个好"
        - "shopping"：引导购物，如"想买个手机"、"帮我挑一款"
        - "query"：查价型，如"iPhone 15 京东多少钱"

        返回 "recommendation" / "comparison" / "shopping" / "query"
        """
        # 推荐意图检测
        has_use_case = any(kw in query for kw in USE_CASE_TRIGGER_MAP)
        has_recommend_word = any(w in query for w in ["推荐", "建议", "适合", "哪款好", "什么手机", "选什么"])
        has_budget = any(w in query for w in ["以内", "以下", "不超过", "预算", "多少钱以内", "左右"])
        has_processor = any(kw in query for kw in _PROCESSOR_TRIGGERS)

        # "最便宜"/"哪里便宜" 等是查价意图，不算推荐触发
        has_price_lookup = any(w in query for w in ["最便宜", "哪里便宜", "哪个平台", "多少钱", "什么价格"])
        has_recommend_trigger = (has_use_case or has_recommend_word or has_budget or has_processor) and not has_price_lookup

        # 有明确型号的不算推荐（如"推荐iPhone15"是查价，不是推荐）
        model_count = self._count_models(query)
        is_complex = self._is_complex(query)

        # "推荐" + 单型号 + 无场景/预算/处理器限定 = 只是查价
        if has_recommend_trigger and model_count >= 1:
            only_recommend_word = has_recommend_word and not (has_use_case or has_budget or has_processor)
            if only_recommend_word and not is_complex:
                return "query"

        # 混合意图：推荐触发 + 含对比/多步骤证据 → Plan-Execute
        # 例："推荐游戏手机，然后和iPhone 15对比"、"骁龙手机推荐，再和苹果比较"
        if has_recommend_trigger and is_complex:
            return "comparison"

        # 纯推荐：有触发词 + 无对比证据 → ReAct + intent_hint
        if has_recommend_trigger:
            return "recommendation"

        # 有明确型号的单商品查询 → 直接走 query
        if model_count == 1:
            return "query"

        # 对比意图：多个商品 或 含对比词
        if is_complex:
            return "comparison"

        # ── M5: shopping 意图检测 ──
        # 条件：有购物意图 + 无明确型号 + 无场景/预算触发词（有则走 recommendation）
        shopping_keywords = ["买", "想买", "想换", "换个", "挑", "选"]
        has_shopping = any(w in query for w in shopping_keywords)
        if has_shopping and model_count == 0:
            has_scene = any(kw in query for kw in USE_CASE_TRIGGER_MAP)
            budget_words = ["以内", "以下", "预算", "左右", "不超过"]
            has_budget_word = any(w in query for w in budget_words)
            if not has_scene and not has_budget_word:
                return "shopping"

        return "query"

    def _count_models(self, query: str) -> int:
        """统计 query 中包含的已知商品型号数量"""
        product_hints = self._load_product_hints()
        return sum(1 for h in product_hints if h.lower() in query.lower())

    # ── Skills 路由 ──────────────────────────────────────────────────────

    def _resolve_skills(self, intent: str, has_image: bool = False,
                        shopping_phase: str = "") -> Set[str]:
        """根据意图解析需要激活的 Skill 名称集合（优化预加载，避免 load_skill 多一轮）。"""
        skills: Set[str] = set()

        if intent == "query":
            skills.add("price_comparison")
        elif intent == "recommendation":
            skills.add("semantic_recommend")
            skills.add("price_comparison")
        elif intent == "comparison":
            skills.add("price_comparison")
            skills.add("rag_knowledge")
        elif intent == "shopping":
            skills.add("shopping_guide")
            if shopping_phase in ("searching", "comparing"):
                skills.add("price_comparison")
            if shopping_phase == "recommending":
                skills.add("semantic_recommend")

        if has_image:
            skills.add("vision_search")

        return skills

    def _extract_user_skill_invocation(self, query: str) -> Optional[tuple]:
        """检测 /skill-name 前缀。返回 (skill_name, remainder) 或 None。"""
        query = query.strip()
        if not query.startswith("/"):
            return None
        parts = query[1:].split(maxsplit=1)
        name = parts[0].lower().replace("-", "_")
        if name not in self.skill_loader.list_skills():
            return None
        remainder = parts[1] if len(parts) > 1 else ""
        return (name, remainder)

    def _preload_skills(self, skill_names: Set[str], verbose: bool = False):
        """预加载 Skill 到 _loaded_skills（不重复加载，上限 4 个）。"""
        max_skills = 4
        loaded = 0
        for name in sorted(skill_names, key=lambda n: self._skill_priority(n), reverse=True):
            if loaded >= max_skills:
                break
            if name not in self._loaded_skills:
                content = self.skill_loader.get_content(name)
                if content:
                    self._loaded_skills[name] = content
                    loaded += 1
                    if verbose:
                        print(f"  [Skills] 预加载: /{name}")

    def _skill_priority(self, name: str) -> int:
        skill = self.skill_loader.get(name)
        return skill.priority if skill else 0

    def _build_skill_system_prompt(self) -> str:
        """从已加载 Skill 构建 system prompt。无 Skill 时回退 SYSTEM_PROMPT。"""
        if not self._loaded_skills:
            return SYSTEM_PROMPT

        parts = [COMMON_ROLE, COMMON_RULES]

        all_skills = self.skill_loader.load_all()
        for name in self._loaded_skills:
            skill = all_skills.get(name)
            if skill and skill.content:
                parts.append(skill.content)

        parts.append(COMMON_FORMAT)
        parts.append(COMMON_ERROR_HANDLING)
        parts.append(self.skill_loader.get_catalog())

        return "\n\n".join(parts)

    def _build_skill_tool_set(self) -> Set[str]:
        """已加载 Skill 所需工具名称的并集。"""
        tool_names: Set[str] = set()
        all_skills = self.skill_loader.load_all()
        for name in self._loaded_skills:
            skill = all_skills.get(name)
            if skill:
                tool_names.update(skill.tools)
        return tool_names

    def _build_tool_list_from_skills(self) -> List[Dict]:
        """从已加载 Skill 筛选工具 schema 子集。无 Skill 时返回全量。"""
        tool_names = self._build_skill_tool_set()
        if not tool_names:
            return list(self.tools)
        filtered = [
            t for t in self.tools
            if t.get("function", {}).get("name") in tool_names
        ]
        return filtered if filtered else list(self.tools)

    # ── Plan-Execute 模式 ─────────────────────────────────────────────

    def _plan_and_execute(
        self,
        user_query: str,
        history: Optional[List[Dict]],
        verbose: bool,
        system_prompt_override: str = "",
    ) -> str:
        """Plan-Execute 主流程"""

        self.trace.plan_start()
        plan = self._generate_plan(user_query, history, verbose)
        if plan is None:
            self.trace.mode_select(mode="react", reason="LLM 判定为简单查询，回退 ReAct", model=self.model_react)
            if verbose:
                print(f"[Plan-Execute] LLM 判定为简单 query，回退 ReAct")
            return self._react_loop(user_query, history, verbose,
                                    system_prompt_override=system_prompt_override)

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
            resp = self._call_llm(
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
            self.trace.plan_generated(steps=steps, model=self.model_plan)
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
        """Phase 2: 每个 Step 独立 mini-ReAct，按依赖关系分组并行/串行"""
        if verbose:
            print(f"\n[Phase 2] 执行计划（每 Step 独立 mini-ReAct）...")

        independent = []
        dependent = []

        for s in steps:
            if s.get("depends_on") is None:
                independent.append(s)
            else:
                dependent.append(s)

        results = {}
        errors = {}

        # 无依赖组 → 并行执行（每个 Step 内部做 mini-ReAct）
        if independent:
            if verbose:
                print(f"  并行执行 {len(independent)} 个 Step...")

            # Trace: mark all independent steps as starting
            for step in independent:
                sn = step["step"]
                self.trace.step_start(
                    step_num=sn, tool=step.get("tool", ""),
                    purpose=step.get("purpose", ""), depends_on=None,
                    group="independent",
                )

            with concurrent.futures.ThreadPoolExecutor(
                max_workers=min(len(independent), 4)
            ) as executor:
                futures = {}
                for step in independent:
                    f = executor.submit(
                        self._execute_step_with_react,
                        step,
                        None,   # 无依赖结果
                        verbose,
                    )
                    futures[f] = step

                for f in concurrent.futures.as_completed(futures):
                    step = futures[f]
                    sn = step["step"]
                    try:
                        results[sn] = f.result(timeout=60)
                        success = "error" not in results[sn]
                        summary = self._format_step_result(results[sn])
                        self.trace.step_end(step_num=sn, success=success, summary=summary,
                                            error=results[sn].get("error", "") if not success else "")
                        if verbose:
                            status = "✓" if success else "✗"
                            print(f"  {status} Step {sn}: {step['tool']} 完成")
                    except Exception as e:
                        errors[sn] = str(e)
                        results[sn] = {"error": str(e)}
                        self.trace.step_end(step_num=sn, success=False, error=str(e))
                        if verbose:
                            print(f"  ✗ Step {sn}: {step['tool']} 异常 — {e}")

        # 有依赖组 → 串行执行（解析 $step{N} 引用后，每个 Step 内部做 mini-ReAct）
        for step in dependent:
            dep = step["depends_on"]
            args = self._resolve_step_refs(step.get("args", {}), results)
            sn = step["step"]

            self.trace.step_start(
                step_num=sn, tool=step.get("tool", ""),
                purpose=step.get("purpose", ""), depends_on=dep,
                group="dependent",
            )

            if verbose:
                print(f"  Step {sn}: {step['tool']} (依赖 Step {dep})")

            try:
                results[sn] = self._execute_step_with_react(
                    step, args, verbose
                )
                success = "error" not in results[sn]
                summary = self._format_step_result(results[sn])
                self.trace.step_end(step_num=sn, success=success, summary=summary,
                                    error=results[sn].get("error", "") if not success else "")
                if verbose:
                    status = "✓" if success else "✗"
                    print(f"  {status} Step {sn}: {step['tool']} 完成")
            except Exception as e:
                errors[sn] = str(e)
                results[sn] = {"error": str(e)}
                self.trace.step_end(step_num=sn, success=False, error=str(e))
                if verbose:
                    print(f"  ✗ Step {sn}: {step['tool']} 异常 — {e}")

        if errors and verbose:
            print(f"  共 {len(errors)} 个 Step 失败")

        return results

    # ── Step 级 mini-ReAct ──────────────────────────────────────────────

    def _execute_step_with_react(
        self,
        step: Dict,
        resolved_args: Optional[Dict],
        verbose: bool,
    ) -> Dict:
        """
        以 mini-ReAct 循环执行单个 Plan Step。

        流程：
        1. 执行 Plan 指定的工具/参数
        2. 如果结果为空/异常 → LLM 反思决定：重试（换参数）| 换工具 | 放弃
        3. 最多执行 max_step_react_rounds 轮
        """
        tool_name = step["tool"]
        purpose = step.get("purpose", "")
        args = resolved_args or step.get("args", {})

        if verbose:
            print(f"\n  ── Step {step['step']}: {purpose} ──")

        # Round 1: 按 Plan 执行
        self.trace.tool_call(tool_name=tool_name, args=args, step=step.get("step", 0), round_num=1, model=self._tool_model(tool_name))
        t0 = time.time()
        result = self._call_tool_safe(tool_name, args)
        tool_elapsed = round((time.time() - t0) * 1000)
        round_num = 1
        result_str = self._format_step_result(result)
        found_r1 = not self._is_empty_result(result) and "error" not in result
        match_count_r1 = 0
        if "raw_data" in result:
            match_count_r1 = result["raw_data"].get("total_matches", 0)
        self.trace.tool_result(
            tool_name=tool_name, found=found_r1, match_count=match_count_r1,
            summary=result_str[:300], step=step.get("step", 0), round_num=1,
        )

        if verbose:
            found_info = ""
            if "raw_data" in result:
                rd = result["raw_data"]
                if rd.get("found"):
                    found_info = f" (找到 {rd.get('total_matches', '?')} 个匹配)"
                else:
                    found_info = " (未找到)"
            print(f"    Round 1: {tool_name}{found_info}")

        # 如果第一轮就拿到数据，直接返回
        if not self._is_empty_result(result) and "error" not in result:
            if verbose:
                print(f"    ✓ 数据有效，完成")
            return result

        # Round 2+: 空结果或异常 → LLM 反思决定
        tools_desc = self._build_tools_description()

        for round_num in range(2, self.max_step_react_rounds + 2):
            reflection_prompt = f"""你正在执行一个搜索计划的第 {step['step']} 步。

**步骤目的**：{purpose}
**上轮调用**：{tool_name}({json.dumps(args, ensure_ascii=False)})
**上轮结果**：{result_str[:800]}

**可用工具**：
{tools_desc}

请决定下一步，只输出 JSON：
{{
  "action": "retry | switch_tool | done",
  "reasoning": "为什么做这个决定的简要说明",
  "tool": "工具名（retry 或 switch_tool 时必填）",
  "args": {{"参数": "值"}}（retry 或 switch_tool 时必填）
}}

决策规则：
- retry：上轮结果为空，换个参数重试（如去掉颜色/内存、缩短关键词、尝试别名）
- switch_tool：当前工具不合适，换一个工具（如从单平台切换为全平台查询）
- done：已经重试过了仍无结果，或有足够数据，停止尝试

只输出 JSON，不要其他文字。"""

            try:
                resp = self._call_llm(
                    model=self.model_react,
                    messages=[{"role": "user", "content": reflection_prompt}],
                    temperature=0,
                    max_tokens=300,
                )
                raw = resp.choices[0].message.content.strip()
                raw = raw.strip("`").lstrip("json").strip()
                decision = json.loads(raw)
            except Exception:
                decision = {"action": "done", "reasoning": "LLM 调用失败"}

            action = decision.get("action", "done")
            self.trace.reflection(
                tool_name=tool_name, retry_count=round_num - 1,
                action=action, reasoning=decision.get("reasoning", ""),
                step=step.get("step", 0),
            )

            if verbose:
                print(f"    Round {round_num}: {decision.get('reasoning', action)}")

            if action in ("retry", "switch_tool"):
                new_tool = decision.get("tool", tool_name)
                new_args = decision.get("args", args)
                self.trace.tool_call(tool_name=new_tool, args=new_args, step=step.get("step", 0), round_num=round_num, model=self._tool_model(new_tool))
                try:
                    t_retry = time.time()
                    result = self._call_tool_safe(new_tool, new_args)
                    result_str = self._format_step_result(result)
                    retry_found = not self._is_empty_result(result) and "error" not in result
                    retry_matches = 0
                    if "raw_data" in result:
                        retry_matches = result["raw_data"].get("total_matches", 0)
                    self.trace.tool_result(
                        tool_name=new_tool, found=retry_found, match_count=retry_matches,
                        summary=result_str[:300], step=step.get("step", 0), round_num=round_num,
                    )

                    if retry_found:
                        if verbose:
                            found_info = ""
                            if "raw_data" in result:
                                rd = result["raw_data"]
                                if rd.get("found"):
                                    found_info = f" (找到 {rd.get('total_matches', '?')} 个匹配)"
                            print(f"    ✓ 重试成功{found_info}")
                        return result
                except Exception as e:
                    self.trace.tool_result(
                        tool_name=new_tool, found=False, error=str(e),
                        step=step.get("step", 0), round_num=round_num,
                    )
                    if verbose:
                        print(f"    ✗ 重试失败: {e}")

            elif action == "done":
                break

        # 所有重试结束还是没有数据
        if verbose:
            print(f"    ⚠ 未找到数据，返回空结果标记")
        return result  # 返回最后一次的结果（即使是空的）

    def _format_step_result(self, result: Dict) -> str:
        """格式化 tool 结果用于 step-reflection prompt"""
        if "formatted_text" in result:
            return result["formatted_text"][:800]
        if "raw_data" in result:
            rd = result["raw_data"]
            if rd.get("found"):
                cheapest = rd.get("cheapest", {})
                return f"找到 {rd.get('total_matches', '?')} 个匹配，最便宜: {cheapest.get('platform_name', '?')} ¥{cheapest.get('platform_price', '?')}"
            return f"未找到匹配"
        if "error" in result:
            return f"执行错误: {result['error']}"
        return json.dumps(result, ensure_ascii=False, indent=2)[:500]

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
        """解析单个 $step{N}.path.to.field 引用，支持 recommendations[0] 列表索引"""
        m = re.match(r'\$step(\d+)\.(.+)', ref)
        if not m:
            return ref
        step_num = int(m.group(1))
        path = m.group(2).split('.')
        current = results.get(step_num, {})
        for part in path:
            if current is None:
                return ref
            if isinstance(current, list):
                # 纯数字索引（如路径里直接出现 "0"）
                try:
                    current = current[int(part)]
                except (ValueError, IndexError):
                    return ref
            elif isinstance(current, dict):
                # 支持 recommendations[0] 带索引的路径
                idx_m = re.match(r'^(\w+)\[(\d+)\]$', part)
                if idx_m:
                    key, idx = idx_m.group(1), int(idx_m.group(2))
                    inner = current.get(key)
                    if isinstance(inner, list) and idx < len(inner):
                        current = inner[idx]
                    else:
                        return ref
                else:
                    current = current.get(part)
            else:
                return ref
        return current

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
        self.trace.synthesize_start(model=self.model_synthesize)
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
            resp = self._call_llm(
                model=self.model_synthesize,
                messages=messages,
                temperature=0.3,
                max_tokens=1500,
            )
            answer = resp.choices[0].message.content
            self.trace.synthesize_end(char_count=len(answer), model=self.model_synthesize)
            # 保存完整 messages 供 M6 训练数据提取
            final_msg = {"role": "assistant", "content": answer}
            self._last_messages = list(messages) + [final_msg]
            if verbose:
                print(f"[Phase 3] 答案生成完成 ({len(answer)} 字符)")
            return answer
        except Exception as e:
            self.trace.error(message=str(e), context="synthesize")
            if verbose:
                print(f"[Phase 3] 合成失败: {e}")
            return f"综合分析时出错: {e}\n\n原始查询结果:\n{obs_combined[:1000]}"

    def _call_tool_safe(self, tool_name: str, args: Dict) -> Dict:
        """安全调用工具，过滤掉工具不接受的关键词参数"""
        func = self.tool_map.get(tool_name)
        if func is None:
            return {"error": f"未知工具: {tool_name}"}
        clean_args = {k: v for k, v in args.items() if not k.startswith("_")}
        return func(**clean_args)

    def _tool_model(self, tool_name: str) -> str:
        """返回工具内部使用的 LLM 模型名（用于 trace 显示）"""
        if tool_name == "search_product_by_image":
            return self.model_vision
        return self.model_react

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
        verbose: bool,
        intent_hint: str = "query",
        system_prompt_override: str = "",
        tools_override: Optional[List[Dict]] = None,
    ) -> str:
        """传统 ReAct 循环（含自反思纠错机制）。intent_hint 用于注入工具选择提示。"""
        system_prompt = system_prompt_override or self._build_skill_system_prompt()
        if tools_override is not None:
            tools = list(tools_override)
        else:
            tools = self._build_tool_list_from_skills()
        # 始终包含 load_skill 元工具
        tools = tools + [self._load_skill_tool_schema]

        messages = [{"role": "system", "content": system_prompt}]

        if intent_hint == "recommendation":
            messages.append({
                "role": "system",
                "content": "【意图提示】当前用户需求是商品推荐，请优先调用 semantic_product_search 工具，而不是 multi_platform_price_comparison。"
            })

        if history:
            messages.extend(history)

        messages.append({"role": "user", "content": user_query})

        empty_result_count = {}  # 记录各工具连续空结果次数

        for round_num in range(self.max_round):
            if round_num == 0 and verbose and self.model_react != self.model:
                print(f"[ReAct] 使用模型: {self.model_react}")
            response = self._call_llm(
                model=self.model_react,
                messages=messages,
                tools=tools,
                tool_choice="auto"
            )
            response_msg = response.choices[0].message
            thoughts = response_msg.content or "正在调用工具获取数据..."

            self.trace.react_round(round_num=round_num + 1, thought=thoughts, model=self.model_react)

            if verbose:
                print(f"\n【Round {round_num + 1} - Thought】{thoughts}")

            if not response_msg.tool_calls:
                # 保存完整 messages 供 M6 训练数据提取
                final_msg = {"role": "assistant", "content": response_msg.content}
                self._last_messages = list(messages) + [final_msg]
                return response_msg.content

            # ── 分离元工具（load_skill）和正常工具 ──
            load_skill_calls = [tc for tc in response_msg.tool_calls
                                if tc.function.name == "load_skill"]
            normal_calls = [tc for tc in response_msg.tool_calls
                            if tc.function.name != "load_skill"]

            appended_assistant = False

            if load_skill_calls and not normal_calls:
                # 纯元工具调用：加载 Skill 后重新构建上下文，继续下一轮
                for tc in load_skill_calls:
                    try:
                        meta_args = json.loads(tc.function.arguments)
                        skill_name = meta_args.get("skill_name", "")
                    except (json.JSONDecodeError, KeyError):
                        skill_name = ""

                    content = self.skill_loader.get_content(skill_name)
                    if content:
                        if len(self._loaded_skills) >= 4:
                            # 超上限：移除最早加载的
                            oldest = next(iter(self._loaded_skills))
                            del self._loaded_skills[oldest]
                        self._loaded_skills[skill_name] = content
                        result = f"技能「{skill_name}」已加载。请使用该技能的知识指导后续操作。"
                        if verbose:
                            print(f"  ├─【Meta-Action】load_skill({skill_name}) → 已加载")
                    else:
                        result = f"错误：未找到技能「{skill_name}」。可用：{', '.join(self.skill_loader.list_skills())}"
                        if verbose:
                            print(f"  ├─【Meta-Action】load_skill({skill_name}) → 失败")

                    self.trace.skill_load(
                        skills=list(self._loaded_skills.keys()),
                        prompt_chars=sum(len(c) for c in self._loaded_skills.values()),
                        tool_count=len(self._build_skill_tool_set()),
                        mode="llm_loaded", source="llm",
                    )

                    messages.append(response_msg.model_dump())
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result,
                    })

                # 重建 system prompt 和工具列表
                new_system = self._build_skill_system_prompt()
                tools = self._build_tool_list_from_skills() + [self._load_skill_tool_schema]
                messages = [m for m in messages if m.get("role") != "system"]
                messages.insert(0, {"role": "system", "content": new_system})
                continue

            # ── 混合调用（load_skill + 正常工具）：先 append assistant，再处理 tool 结果 ──
            messages.append(response_msg.model_dump())
            appended_assistant = True

            for tc in load_skill_calls:
                try:
                    meta_args = json.loads(tc.function.arguments)
                    skill_name = meta_args.get("skill_name", "")
                except (json.JSONDecodeError, KeyError):
                    skill_name = ""

                content = self.skill_loader.get_content(skill_name)
                if content:
                    if len(self._loaded_skills) >= 4:
                        oldest = next(iter(self._loaded_skills))
                        del self._loaded_skills[oldest]
                    self._loaded_skills[skill_name] = content
                    meta_result = f"技能「{skill_name}」已加载。"
                    if verbose:
                        print(f"  ├─【Meta-Action】load_skill({skill_name}) → 已加载")
                else:
                    meta_result = f"错误：未找到技能「{skill_name}」。"
                    if verbose:
                        print(f"  ├─【Meta-Action】load_skill({skill_name}) → 失败")

                self.trace.skill_load(
                    skills=list(self._loaded_skills.keys()),
                    prompt_chars=sum(len(c) for c in self._loaded_skills.values()),
                    tool_count=len(self._build_skill_tool_set()),
                    mode="llm_loaded", source="llm",
                )
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": meta_result,
                })

            # ── 处理正常工具（原有逻辑不变） ──
            tool_call_count = len(normal_calls)
            if verbose and tool_call_count > 1:
                print(f"【需要调用 {tool_call_count} 个工具】")

            all_tool_results = []
            all_empty = True
            should_reflect = False
            reflect_tool_name = None
            reflect_tool_args = None
            reflect_observation = None
            reflect_retry_count = 0

            for tc in normal_calls:
                tool_name = tc.function.name
                try:
                    tool_args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    tool_args = {}

                if verbose:
                    print(f"  ├─【Action】{tool_name}({tool_args})")

                t0 = time.time()
                try:
                    tool_func = self.tool_map[tool_name]
                    observation = tool_func(**tool_args)
                except Exception as e:
                    observation = {"error": f"工具执行失败：{str(e)}"}
                tool_elapsed = round((time.time() - t0) * 1000)

                observation_str = json.dumps(observation, ensure_ascii=False, indent=2)

                if verbose:
                    print(f"  └─【Observation-{tool_name}】{observation_str[:300]}")

                is_empty = self._is_empty_result(observation)

                # Trace: tool call + result
                found = not is_empty if not observation.get("error") else False
                match_count = 0
                cheapest = None
                if isinstance(observation, dict) and "raw_data" in observation:
                    rd = observation["raw_data"]
                    match_count = rd.get("total_matches", 0)
                    if rd.get("cheapest"):
                        cheapest = rd["cheapest"]

                self.trace.tool_call(tool_name=tool_name, args=tool_args, round_num=round_num + 1, model=self._tool_model(tool_name))
                self.trace.tool_result(
                    tool_name=tool_name, found=found, match_count=match_count,
                    cheapest=cheapest, error=observation.get("error", ""),
                    summary=observation_str[:300], round_num=round_num + 1,
                )

                if is_empty:
                    empty_result_count[tool_name] = empty_result_count.get(tool_name, 0) + 1

                    if empty_result_count[tool_name] <= self.max_reflection_retries:
                        should_reflect = True
                        reflect_tool_name = reflect_tool_name or tool_name
                        reflect_tool_args = reflect_tool_args or tool_args
                        reflect_observation = reflect_observation or observation
                        reflect_retry_count = max(reflect_retry_count, empty_result_count[tool_name])
                else:
                    all_empty = False
                    empty_result_count.pop(tool_name, None)

                all_tool_results.append({
                    "tool_call_id": tc.id,
                    "tool_name": tool_name,
                    "content": observation_str,
                    "is_empty": is_empty,
                })

            # 所有工具都空且触发反思 → 加反思消息跳过 tool 结果
            if all_empty and should_reflect:
                reflection_msg = self._build_reflection_message(
                    reflect_tool_name, reflect_tool_args, reflect_observation, reflect_retry_count
                )
                self.trace.reflection(
                    tool_name=reflect_tool_name, retry_count=reflect_retry_count,
                    action="retry" if reflect_retry_count <= self.max_reflection_retries else "done",
                    reasoning=reflection_msg[:200],
                )
                if verbose:
                    print(f"【Reflection】{reflection_msg}")
                messages.append({
                    "role": "system",
                    "content": reflection_msg
                })
                continue

            # 追加 assistant 消息和全部 tool 结果
            if not appended_assistant:
                messages.append(response_msg.model_dump())
            for tr in all_tool_results:
                messages.append({
                    "role": "tool",
                    "tool_call_id": tr["tool_call_id"],
                    "content": tr["content"],
                })

        self._last_messages = list(messages)
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

    # ═══════════════════════════════════════════════════════════════════════
    # M5: 引导式购物
    # ═══════════════════════════════════════════════════════════════════════

    def _is_ending_shopping(self, query: str) -> bool:
        """检测用户是否在结束购物（纯结束，不含新查询意图）"""
        end_words = ["谢谢", "好的", "就这个", "下单", "买了", "不用了", "算了", "不买了"]
        has_end = any(w in query for w in end_words)
        if not has_end:
            return False
        # 如果同时表达了新查询意图（如"算了帮我查iPhone 15"），不算结束
        has_new_query = self._count_models(query) > 0 or any(
            w in query for w in ["帮我查", "搜一下", "多少钱", "比价", "推荐"]
        )
        return not has_new_query

    def _is_topic_switch(self, query: str) -> bool:
        """检测用户是否在购物中途切换到具体商品查询。
        购物模式下用户突然提到具体商品型号，说明想离开购物流程做精确查询。"""
        model_count = self._count_models(query)
        if model_count == 0:
            return False
        # 检查提到的型号是否在当前推荐候选列表中（在候选内不算切换）
        for c in self.shopping_context.candidates:
            name = c.get("product_name", "")
            if name and name in query:
                return False
        return True

    def _guided_shopping(
        self,
        user_query: str,
        history: Optional[List[Dict]],
        verbose: bool,
        system_prompt_override: str = "",
    ) -> str:
        """引导式购物主流程"""
        slots_cfg = self.industry_config.get("shopping_slots", [])
        max_questions = self.industry_config.get("max_slot_questions", 3)
        ctx = self.shopping_context

        # Phase: GREETING
        if ctx.phase == "greeting":
            self.trace.shopping_phase(phase="slot_filling", from_phase="greeting")
            ctx.phase = "slot_filling"
            self._inject_from_history(history, slots_cfg)
            self._extract_slots_from_query(user_query, slots_cfg)

            missing = ctx.get_missing_required(slots_cfg)
            if not missing:
                ctx.phase = "searching"
                self.trace.shopping_phase(phase="searching", from_phase="slot_filling")
            else:
                return self._greet_and_ask(missing, slots_cfg)

        # Phase: SLOT_FILLING
        if ctx.phase == "slot_filling":
            prev_slots = set(ctx.slots.keys())
            self._extract_slots_from_query(user_query, slots_cfg)
            new_slots = set(ctx.slots.keys()) - prev_slots

            if not new_slots:
                # 用户输入未提取到任何槽位 — 可能是无关闲聊或前言不搭后语
                # 不计入 question_count，重新追问当前缺失的槽位
                missing = ctx.get_missing_required(slots_cfg)
                if missing:
                    return f"我没太理解您的意思，{self._ask_slot_question(missing[0])}"
                # 没有必填缺失，直接进入搜索
                ctx.phase = "searching"
                self.trace.shopping_phase(phase="searching", from_phase="slot_filling")
            else:
                for s in new_slots:
                    self.trace.slot_filled(slot_name=s, value=ctx.slots.get(s), phase="slot_filling")

                ctx.question_count += 1
                missing = ctx.get_missing_required(slots_cfg)

                if not missing:
                    ctx.phase = "searching"
                    self.trace.shopping_phase(phase="searching", from_phase="slot_filling")
                elif ctx.question_count >= max_questions:
                    ctx.phase = "searching"
                    self.trace.shopping_phase(phase="searching", from_phase="slot_filling")
                else:
                    optional = [s for s in slots_cfg if not s.get("required") and s["name"] not in ctx.slots]
                    if optional:
                        return self._ask_slot_question(optional[0])
                    ctx.phase = "searching"
                    self.trace.shopping_phase(phase="searching", from_phase="slot_filling")

        # Phase: SEARCHING
        if ctx.phase == "searching":
            result = self._search_with_slots(ctx.slots)
            ctx.candidates = result.get("recommendations", [])
            ctx.last_recommendation = result
            ctx.phase = "recommending"
            self.trace.shopping_phase(phase="recommending", from_phase="searching")
            return self._format_recommendation(result)

        # Phase: RECOMMENDING / COMPARING / FOLLOW_UP
        if ctx.phase in ("recommending", "comparing", "follow_up"):
            return self._handle_followup(user_query)

        # 兜底
        return self._react_loop(user_query, history, verbose,
                                system_prompt_override=system_prompt_override)

    def _inject_from_history(self, history, slots_cfg):
        """从历史对话提取上下文注入槽位"""
        if not history:
            return
        recent = " ".join(
            h.get("content", "") for h in history[-6:]
            if isinstance(h, dict) and h.get("role") == "user"
        )
        if recent:
            self._extract_slots_from_query(recent, slots_cfg)

    def _extract_slots_from_query(self, query: str, slots_cfg: list):
        """从用户输入中提取槽位信息"""
        ctx = self.shopping_context
        for slot_def in slots_cfg:
            name = slot_def["name"]
            if name in ctx.slots:
                continue

            # 策略 1: 关键词匹配（dict 做值映射，list 做存在检测）
            keywords = slot_def.get("extract_keywords")
            if isinstance(keywords, dict):
                for kw, mapped in keywords.items():
                    if kw in query:
                        ctx.add_slot(name, mapped)
                        break
            elif isinstance(keywords, list):
                for kw in keywords:
                    if kw in query:
                        ctx.add_slot(name, kw)
                        break

            # 策略 2: 正则提取
            pattern = slot_def.get("extract_pattern")
            if pattern and name not in ctx.slots:
                m = re.search(pattern, query)
                if m:
                    # group(0) 是整个匹配，从中提取第一个数字
                    nums = re.findall(r'\d+', m.group(0))
                    if nums:
                        ctx.add_slot(name, int(max(nums, key=int)))

        # budget_range → budget_max 映射
        if "budget_range" in ctx.slots and "budget_max" not in ctx.slots:
            ctx.add_slot("budget_max", ctx.slots.pop("budget_range"))

    def _greet_and_ask(self, missing: list, slots_cfg: list) -> str:
        """打招呼 + 追问第一个必填槽位"""
        first = missing[0]
        question = first.get("question", "")
        options = first.get("options", [])
        lines = ["您好！让我帮您挑选合适的手机。", ""]
        if question:
            lines.append(question)
        if options:
            lines.append("可选：" + " / ".join(options))
        return "\n".join(lines)

    def _ask_slot_question(self, slot_def: dict) -> str:
        """追问单个槽位"""
        q = slot_def.get("question", "")
        opts = slot_def.get("options", [])
        if opts:
            q += " 可选：" + " / ".join(opts)
        return q

    def _search_with_slots(self, slots: dict) -> dict:
        """将槽位转换为 semantic_product_search 参数并调用"""
        from tools.semantic_search_tool import semantic_product_search

        params = {"category": self.industry_config.get("category", "手机")}
        if "primary_use_case" in slots:
            params["use_case"] = slots["primary_use_case"]
        if "budget_max" in slots:
            params["budget_max"] = slots["budget_max"]
        if "brand_preference" in slots:
            params["brand"] = slots["brand_preference"]
        if "processor_preference" in slots:
            proc_map = self.industry_config.get("processor_normalize", {})
            pref = slots["processor_preference"]
            params["processor_brand"] = proc_map.get(pref, pref)

        try:
            return semantic_product_search(**params)
        except Exception as e:
            print(f"  ⚠ 购物搜索失败: {e}")
            return {"recommendations": [], "total_found": 0, "error": str(e)}

    def _search_and_respond(self) -> str:
        """执行搜索并格式化推荐返回，完成后 phase → recommending"""
        ctx = self.shopping_context
        result = self._search_with_slots(ctx.slots)
        ctx.candidates = result.get("recommendations", [])
        ctx.last_recommendation = result
        ctx.phase = "recommending"
        return self._format_recommendation(result)

    def _format_recommendation(self, result: dict) -> str:
        """将推荐结果格式化为用户可读文本"""
        recs = result.get("recommendations", [])
        if not recs:
            if result.get("error"):
                return "抱歉，搜索服务暂时不可用，请稍后再试。"
            return "抱歉，没有找到符合条件的商品。要不要调整一下条件试试？"

        lines = ["为您找到以下商品：", ""]
        for r in recs[:5]:
            lines.append(
                f"{r['rank']}. {r['product_name']} — "
                f"¥{r['price']} | {r.get('platform', '')} | "
                f"{r.get('processor', '')}"
            )
            desc = r.get("description", "")
            if desc:
                lines.append(f"   {desc}")
            lines.append("")

        total = result.get("total_found", len(recs))
        lines.append(
            f"共找到 {total} 款商品。您可以继续筛选，比如'便宜点的'、"
            f"'对比前两个'、'再加预算'。"
        )
        return "\n".join(lines)

    def _handle_followup(self, user_query: str) -> str:
        """处理推荐后的用户跟进"""
        ctx = self.shopping_context

        # 对比意图
        if any(w in user_query for w in ["对比", "比较", "哪个好", "哪个更", "这两个", "这几个", "这三个", "哪款好"]):
            self.trace.shopping_phase(phase="comparing", from_phase=ctx.phase)
            ctx.phase = "comparing"
            return self._handle_comparison(user_query)

        # 预算调整
        new_budget = self._detect_budget_adjust(user_query)
        if new_budget:
            ctx.slots["budget_max"] = new_budget
            return self._search_and_respond()

        # 价格敏感
        if any(w in user_query for w in ["便宜", "更便宜", "贵了", "超预算"]):
            return self._search_and_respond()

        # 结束
        if self._is_ending_shopping(user_query):
            ctx.reset()
            return "好的！如果还有其他需要，随时告诉我。"

        # 默认：追加条件重新搜（只有提取到新槽位才重新搜索）
        prev_slots = set(ctx.slots.keys())
        self._extract_slots_from_query(
            user_query, self.industry_config.get("shopping_slots", [])
        )
        if set(ctx.slots.keys()) != prev_slots:
            return self._search_and_respond()

        return "您可以告诉我更多需求，比如预算、品牌偏好，或者让我帮您对比推荐的商品。"

    def _handle_comparison(self, user_query: str) -> str:
        """对比模式"""
        ctx = self.shopping_context
        dimensions = self.industry_config.get("compare_dimensions", [])

        if not ctx.compare_basket:
            ctx.compare_basket = ctx.candidates[:3]

        if not ctx.compare_basket:
            return "目前还没有可以对比的商品，先让我帮您搜一下吧。"

        compare_text = self._format_compare_table(ctx.compare_basket, dimensions)
        dim_lines = "\n".join(
            f"- {d['name']}（权重 {int(d['weight'] * 100)}%）" for d in dimensions
        )

        messages = [
            {"role": "system", "content": "你是手机对比专家。根据参数逐项对比并给出建议。"},
            {"role": "user", "content": f"""请对比以下商品：

{compare_text}

对比维度：
{dim_lines}

请逐项对比，最后给出明确建议。"""},
        ]

        resp = self._call_llm(
            model=self.model_synthesize,
            messages=messages,
            temperature=0.3,
            max_tokens=2000,
        )

        ctx.phase = "follow_up"
        return resp.choices[0].message.content

    def _format_compare_table(self, products: list, dimensions: list) -> str:
        """格式化对比表"""
        lines = []
        for i, p in enumerate(products):
            lines.append(f"[{i+1}] {p.get('product_name', '')} — ¥{p.get('price', '')}")
            for d in dimensions:
                val = p.get(d["key"], "—")
                lines.append(f"    {d['name']}: {val}")
            lines.append("")
        return "\n".join(lines)

    def _detect_budget_adjust(self, query: str):
        """检测预算调整"""
        patterns = [
            r"再加\s*(\d+)",
            r"预算.*?(\d+)",
            r"(\d+)\s*以内",
            r"降到\s*(\d+)",
        ]
        for pat in patterns:
            m = re.search(pat, query)
            if m:
                return int(m.group(1))
        return None

    def _detect_product_switch(self, query: str):
        """检测商品切换"""
        ctx = self.shopping_context
        for c in ctx.candidates:
            name = c.get("product_name", "")
            if name and name in query:
                return name
        return None
