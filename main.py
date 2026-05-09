from config import Settings
from tools import tool_registry, init_parallel_agent
from platforms import init_all_platforms
from agent import ReActAgent


def main():
    print("===== ReAct + Tool Calling 商品对比Agent =====\n")

    settings = Settings()

    init_parallel_agent()

    init_all_platforms()

    agent = ReActAgent(
        client=settings.client,
        model=settings.model,
        tools=tool_registry.get_schemas(),
        tool_map=tool_registry.get_tool_map(),
        max_round=settings.max_round
    )

    print("请输入你的问题（输入 'quit' 或 'exit' 退出）：")
    while True:
        try:
            user_query = input("\n> ").strip()

            if user_query.lower() in ["quit", "exit"]:
                print("再见！")
                break

            if not user_query:
                print("请输入有效的问题")
                continue

            print(f"\n用户问题：{user_query}")
            answer = agent.run(user_query, verbose=True)
            print(f"\n【Final Answer】{answer}")

        except KeyboardInterrupt:
            print("\n\n再见！")
            break
        except Exception as e:
            print(f"\n发生错误：{str(e)}")


if __name__ == "__main__":
    main()
