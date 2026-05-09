import json
import sqlite3
from openai import OpenAI
from dotenv import load_dotenv
import os

# ===================== 1. 环境配置 =====================
load_dotenv()
client = OpenAI(
    api_key=os.getenv("ARK_API_KEY"),
    base_url="https://ark.cn-beijing.volces.com/api/v3"
)
MODEL = os.getenv("ARK_MODEL", "doubao-seed-2-0-lite-260215")

# ===================== 2. Mock 内存数据库 =====================
def init_mock_db():
    """初始化内存数据库，Mock商品数据"""
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_name TEXT NOT NULL,
            price REAL NOT NULL,
            stock INTEGER NOT NULL,
            category TEXT NOT NULL
        )
    ''')
    mock_products = [
        ("iPhone 15", 5999, 100, "手机"),
        ("小米14", 3999, 150, "手机"),
        ("华为Mate60", 4999, 80, "手机"),
        ("iPad Pro", 6299, 50, "平板"),
        ("小米平板6", 2199, 120, "平板")
    ]
    cursor.executemany(
        "INSERT INTO products (product_name, price, stock, category) VALUES (?, ?, ?, ?)",
        mock_products
    )
    conn.commit()
    return conn

db_conn = init_mock_db()

# ===================== 3. 工具函数定义 =====================
def query_single_product(product_name: str) -> dict:
    """
    工具1：查询单个商品详情
    :param product_name: 商品名称
    :return: 商品结构化数据
    """
    cursor = db_conn.cursor()
    cursor.execute("SELECT * FROM products WHERE product_name = ?", (product_name,))
    result = cursor.fetchone()
    if not result:
        return {"error": f"未找到商品：{product_name}"}
    return {
        "product_name": result[1],
        "price": result[2],
        "stock": result[3],
        "category": result[4]
    }

def multi_product_price_compare(product_names: list) -> dict:
    """
    工具2：对比多个商品价格
    :param product_names: 商品名称列表
    :return: 价格对比结果
    """
    cursor = db_conn.cursor()
    price_map = {}
    for name in product_names:
        cursor.execute("SELECT price FROM products WHERE product_name = ?", (name,))
        res = cursor.fetchone()
        price_map[name] = res[0] if res else "未找到"
    
    valid_prices = {k: v for k, v in price_map.items() if v != "未找到"}
    if not valid_prices:
        return {"error": "未找到任何有效商品"}
    
    return {
        "price_map": price_map,
        "lowest_product": min(valid_prices, key=valid_prices.get),
        "highest_product": max(valid_prices, key=valid_prices.get)
    }

def query_products_by_category(category: str) -> list:
    """
    工具3：查询指定品类下所有商品
    :param category: 商品品类
    :return: 商品列表
    """
    cursor = db_conn.cursor()
    cursor.execute("SELECT product_name, price FROM products WHERE category = ?", (category,))
    results = cursor.fetchall()
    return [{"product_name": row[0], "price": row[1]} for row in results]

TOOL_MAP = {
    "query_single_product": query_single_product,
    "multi_product_price_compare": multi_product_price_compare,
    "query_products_by_category": query_products_by_category
}

# ===================== 4. ReAct 工具配置 =====================
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_single_product",
            "description": "查询单个商品的名称、价格、库存、品类信息",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_name": {"type": "string", "description": "商品名称"}
                },
                "required": ["product_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "multi_product_price_compare",
            "description": "对比多个商品的价格，返回最低价和最高价商品",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "商品名称列表"
                    }
                },
                "required": ["product_names"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_products_by_category",
            "description": "查询指定品类下的所有商品和价格",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "商品品类，如手机/平板"}
                },
                "required": ["category"]
            }
        }
    }
]

# ===================== 5. ReAct 核心推理引擎 =====================
def react_agent(user_query: str) -> str:
    """
    ReAct Agent主函数：循环推理+工具调用+总结答案
    """
    messages = [
        {
            "role": "system",
            "content": """你是一个基于ReAct策略的商品对比智能助手，严格遵循以下流程：
            1. Thought：思考用户问题，明确是否需要调用工具、调用哪个工具
            2. Action：调用对应工具，传入正确参数
            3. Observation：获取工具返回结果
            4. 循环：直到能完整回答用户问题，输出Final Answer
            禁止编造数据，所有结论必须基于工具返回的真实结果"""
        },
        {"role": "user", "content": user_query}
    ]

    max_round = 5
    for round in range(max_round):
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto"
        )
        response_msg = response.choices[0].message
        thoughts = response_msg.content or "正在调用工具获取数据..."
        
        print(f"\n【Round {round+1} - Thought】{thoughts}")

        if not response_msg.tool_calls:
            return response_msg.content

        tool_call = response_msg.tool_calls[0]
        tool_name = tool_call.function.name
        tool_args = json.loads(tool_call.function.arguments)
        
        print(f"【Action】调用工具：{tool_name}，参数：{tool_args}")

        try:
            tool_func = TOOL_MAP[tool_name]
            observation = tool_func(**tool_args)
        except Exception as e:
            observation = {"error": f"工具执行失败：{str(e)}"}

        observation_str = json.dumps(observation, ensure_ascii=False, indent=2)
        print(f"【Observation】{observation_str}")

        messages.append(response_msg)
        messages.append({
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": observation_str
        })

    return "已达到最大推理轮次，无法完成回答"

# ===================== 6. 测试Demo =====================
if __name__ == "__main__":
    print("===== ReAct + Tool Calling 商品对比Agent =====")
    query1 = "对比iPhone 15和小米14的价格，哪个更便宜？"
    print(f"\n用户问题：{query1}")
    answer = react_agent(query1)
    print(f"\n【Final Answer】{answer}")
