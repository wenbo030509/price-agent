import json
from typing import Dict, List, Callable
from openai import OpenAI
from .prompts import SYSTEM_PROMPT


class ReActAgent:
    """ReAct推理引擎类"""

    def __init__(
        self,
        client: OpenAI,
        model: str,
        tools: List[Dict],
        tool_map: Dict[str, Callable],
        max_round: int = 5
    ):
        """
        初始化ReAct Agent
        :param client: OpenAI客户端
        :param model: 模型名称
        :param tools: 工具Schema列表
        :param tool_map: 工具名称到函数的映射
        :param max_round: 最大推理轮次
        """
        self.client = client
        self.model = model
        self.tools = tools
        self.tool_map = tool_map
        self.max_round = max_round

    def run(self, user_query: str, verbose: bool = True) -> str:
        """
        运行ReAct Agent
        :param user_query: 用户查询
        :param verbose: 是否打印推理过程
        :return: 最终答案
        """
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_query}
        ]

        for round_num in range(self.max_round):
            # LLM推理
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

            # 判断是否需要调用工具
            if not response_msg.tool_calls:
                return response_msg.content

            # 执行工具调用
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

            # 更新对话历史
            messages.append(response_msg)
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": observation_str
            })

        return "已达到最大推理轮次，无法完成回答"
