import json
from typing import Dict, List, Callable, Optional
from openai import OpenAI
from .prompts import SYSTEM_PROMPT

# 滑动窗口配置
MAX_HISTORY_ROUNDS = 6       # 最多保留最近 N 轮对话（user + assistant 各算 1 条）
MAX_HISTORY_CHARS = 6000     # 历史消息总字符数硬上限（中英文混合约 3000-4000 token）


class ReActAgent:
    """ReAct 推理引擎类，支持滑动窗口上下文管理"""

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

    def run(
        self,
        user_query: str,
        history: Optional[List[Dict]] = None,
        verbose: bool = True
    ) -> str:
        """
        运行 ReAct Agent。

        :param user_query: 当前用户输入
        :param history:   历史对话消息列表，格式 [{"role": "user", "content": "..."},
                          {"role": "assistant", "content": "..."}, ...]
                          只接受 user/assistant 角色，按滑动窗口截断。
        :param verbose:   是否打印推理过程
        :return:          最终答案
        """
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]

        # 注入滑动窗口后的历史消息
        if history:
            windowed = self._slide_window(history)
            messages.extend(windowed)

        # 当前问题
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

            # 执行工具调用（当前只取第一个，多工具并行见优化文档）
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
        """
        对历史消息做滑动窗口截断。

        策略：
          1. 只保留 user / assistant 角色（过滤 tool、system 等 ReAct 中间产物）
          2. 先按轮数截断（保留最近 MAX_HISTORY_ROUNDS 个 user-assistant 对）
          3. 再按字符数截断（从旧到新逐条移除，直到总字符数 <= MAX_HISTORY_CHARS）

        返回截断后的消息列表，可直接注入 messages。
        """
        # Step 1：只保留 user / assistant
        clean = [m for m in history if m.get("role") in ("user", "assistant")]

        # Step 2：按轮数截断 — 保留最近 N 轮
        # 一轮 = user + assistant 各一条，所以保留 last 2*N 条
        if len(clean) > MAX_HISTORY_ROUNDS * 2:
            clean = clean[-(MAX_HISTORY_ROUNDS * 2):]

        # Step 3：按总字符数截断
        total_chars = sum(len(m.get("content", "")) for m in clean)
        while total_chars > MAX_HISTORY_CHARS and len(clean) >= 2:
            # 从头部移除最早的一对 user+assistant
            removed = clean.pop(0)  # user
            if clean and clean[0].get("role") == "assistant":
                clean.pop(0)        # assistant
            total_chars = sum(len(m.get("content", "")) for m in clean)

        return clean
