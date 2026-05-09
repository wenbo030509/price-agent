from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import uuid
import sys
import io

from config import Settings
from database import (
    DatabaseConnection,
    init_mock_db,
    add_product,
    get_all_products,
    create_session,
    get_all_sessions,
    add_message,
    get_session_messages,
    delete_session
)
from tools import tool_registry, init_parallel_agent, cleanup_parallel_agent
from agent import ReActAgent
from platforms import (
    init_all_platforms,
    get_all_platforms,
    PlatformParallelAgent,
    format_comparison_result,
    PlatformDatabase
)


app = Flask(__name__)
CORS(app)

# 全局初始化
settings = None
db = None
agent = None


def initialize():
    """初始化应用"""
    global settings, db, agent
    
    # 初始化配置
    settings = Settings()
    
    # 初始化数据库（使用文件数据库而不是内存数据库）
    db = DatabaseConnection("price_agent.db")
    
    # 检查数据库是否已初始化
    cursor = db.get_cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='products'")
    if not cursor.fetchone():
        init_mock_db(db)
    
    # 初始化多平台数据库
    try:
        init_all_platforms()
    except Exception as e:
        print(f"初始化平台数据库时出错: {e}")
    
    # 初始化并行查询Agent
    init_parallel_agent()
    
    # 初始化Agent
    agent = ReActAgent(
        client=settings.client,
        model=settings.model,
        tools=tool_registry.get_schemas(),
        tool_map=tool_registry.get_tool_map(),
        max_round=settings.max_round
    )


initialize()


@app.route('/')
def index():
    """首页"""
    return render_template('index.html')


@app.route('/api/products', methods=['GET'])
def get_products():
    """获取所有商品"""
    products = get_all_products(db)
    return jsonify({"success": True, "products": products})


@app.route('/api/products', methods=['POST'])
def create_product():
    """添加新商品"""
    data = request.json
    try:
        product = add_product(
            db,
            product_name=data['product_name'],
            price=float(data['price']),
            stock=int(data['stock']),
            category=data['category']
        )
        return jsonify({"success": True, "product": product})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route('/api/sessions', methods=['GET'])
def list_sessions():
    """获取所有会话"""
    sessions = get_all_sessions(db)
    return jsonify({"success": True, "sessions": sessions})


@app.route('/api/sessions', methods=['POST'])
def create_new_session():
    """创建新会话"""
    session_id = str(uuid.uuid4())
    session = create_session(db, session_id)
    return jsonify({"success": True, "session": session})


@app.route('/api/sessions/<session_id>', methods=['DELETE'])
def delete_session_api(session_id):
    """删除会话"""
    delete_session(db, session_id)
    return jsonify({"success": True})


@app.route('/api/sessions/<session_id>/messages', methods=['GET'])
def get_messages(session_id):
    """获取会话消息"""
    messages = get_session_messages(db, session_id)
    return jsonify({"success": True, "messages": messages})


@app.route('/api/chat', methods=['POST'])
def chat():
    """聊天接口"""
    data = request.json
    user_message = data['message']
    session_id = data.get('session_id')
    
    # 如果没有session_id，创建新会话
    if not session_id:
        session_id = str(uuid.uuid4())
        create_session(db, session_id)
    
    # 保存用户消息
    add_message(db, session_id, 'user', user_message)
    
    # 捕获Agent的输出
    old_stdout = sys.stdout
    sys.stdout = buffer = io.StringIO()
    
    try:
        # 运行Agent
        answer = agent.run(user_message, verbose=True)
        
        # 获取并解析推理过程
        reasoning_output = buffer.getvalue()
        
        # 保存助手消息
        add_message(db, session_id, 'assistant', answer)
        
        return jsonify({
            "success": True,
            "session_id": session_id,
            "answer": answer,
            "reasoning": reasoning_output
        })
    finally:
        sys.stdout = old_stdout


@app.route('/api/platforms', methods=['GET'])
def get_platforms():
    """获取所有平台列表"""
    platforms = get_all_platforms()
    return jsonify({
        "success": True,
        "platforms": platforms
    })


@app.route('/api/multi-platform/compare', methods=['POST'])
def multi_platform_compare():
    """多平台比价API"""
    data = request.json
    product_name = data.get('product_name')
    
    if not product_name:
        return jsonify({
            "success": False,
            "error": "请提供商品名称"
        }), 400
    
    try:
        parallel_agent = PlatformParallelAgent()
        comparison = parallel_agent.compare_product_price(product_name)
        formatted_text = format_comparison_result(comparison)
        parallel_agent.close()
        
        return jsonify({
            "success": True,
            "product_name": product_name,
            "comparison": comparison,
            "formatted_text": formatted_text
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route('/api/multi-platform/products', methods=['GET'])
def get_multi_platform_products():
    """获取所有平台的商品"""
    try:
        parallel_agent = PlatformParallelAgent()
        result = parallel_agent.query_all_products_parallel()
        parallel_agent.close()
        
        return jsonify({
            "success": True,
            "data": result
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route('/api/platforms/<platform_id>/products', methods=['GET'])
def get_platform_products(platform_id):
    """获取指定平台的商品"""
    try:
        platform_db = PlatformDatabase(platform_id)
        products = platform_db.query_all_products()
        platform_db.close()
        
        platforms = get_all_platforms()
        platform_info = platforms.get(platform_id)
        
        return jsonify({
            "success": True,
            "platform_id": platform_id,
            "platform_name": platform_info.get('name', platform_id) if platform_info else platform_id,
            "products": products
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route('/api/platforms/<platform_id>/products', methods=['POST'])
def add_platform_product(platform_id):
    """添加商品到指定平台"""
    try:
        data = request.json
        platform_db = PlatformDatabase(platform_id)
        
        product = platform_db.add_product(
            product_name=data['product_name'],
            price=float(data['price']),
            stock=int(data['stock']),
            category=data['category'],
            platform_price=float(data.get('platform_price', data['price'])) if data.get('platform_price') else None,
            shipping_fee=float(data.get('shipping_fee', 0)),
            is_in_stock=bool(data.get('is_in_stock', True)),
            color=data.get('color'),
            memory=data.get('memory')
        )
        platform_db.close()
        
        return jsonify({
            "success": True,
            "product": product
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 400


@app.route('/api/platforms/<platform_id>/products/<int:product_id>', methods=['PUT'])
def update_platform_product(platform_id, product_id):
    """更新指定平台的商品"""
    try:
        data = request.json
        platform_db = PlatformDatabase(platform_id)
        
        product = platform_db.update_product(
            product_id=product_id,
            product_name=data.get('product_name'),
            price=float(data['price']) if data.get('price') is not None else None,
            stock=int(data['stock']) if data.get('stock') is not None else None,
            category=data.get('category'),
            platform_price=float(data['platform_price']) if data.get('platform_price') is not None else None,
            shipping_fee=float(data['shipping_fee']) if data.get('shipping_fee') is not None else None,
            is_in_stock=bool(data['is_in_stock']) if data.get('is_in_stock') is not None else None,
            color=data.get('color'),
            memory=data.get('memory')
        )
        platform_db.close()
        
        if product:
            return jsonify({
                "success": True,
                "product": product
            })
        else:
            return jsonify({
                "success": False,
                "error": "商品不存在"
            }), 404
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 400


@app.route('/api/platforms/<platform_id>/products/<int:product_id>', methods=['DELETE'])
def delete_platform_product(platform_id, product_id):
    """删除指定平台的商品"""
    try:
        platform_db = PlatformDatabase(platform_id)
        deleted = platform_db.delete_product(product_id)
        platform_db.close()
        
        if deleted:
            return jsonify({
                "success": True,
                "message": "商品删除成功"
            })
        else:
            return jsonify({
                "success": False,
                "error": "商品不存在"
            }), 404
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.teardown_appcontext
def teardown(exception):
    """应用关闭时清理资源"""
    cleanup_parallel_agent()


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001)
