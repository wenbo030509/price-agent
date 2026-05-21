from flask import Flask, render_template, request, jsonify, send_from_directory, Response, stream_with_context
from flask_cors import CORS
import uuid
import sys
import io
import os
import json
import base64

from config import Settings
from database import (
    DatabaseConnection,
    init_mock_db,
    create_session,
    get_all_sessions,
    add_message,
    get_session_messages,
    delete_session
)
from tools import tool_registry, init_parallel_agent, cleanup_parallel_agent, get_parallel_agent
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


def _safe_float(val, default=None):
    """安全转换为 float，失败返回 default 或抛出 ValueError"""
    if val is None or val == "":
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        raise ValueError(f"无法将 '{val}' 转换为数字")


def _safe_int(val, default=None):
    """安全转换为 int，失败返回 default 或抛出 ValueError"""
    if val is None or val == "":
        return default
    try:
        return int(val)
    except (TypeError, ValueError):
        raise ValueError(f"无法将 '{val}' 转换为整数")

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
    
    # 检查数据库是否已初始化（主 DB 只管理会话，不再存商品）
    cursor = db.get_cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sessions'")
    if not cursor.fetchone():
        init_mock_db(db)
    
    # 初始化多平台数据库
    try:
        init_all_platforms()
    except Exception as e:
        print(f"初始化平台数据库时出错: {e}")
    
    # 初始化并行查询Agent
    init_parallel_agent()

    # M2: Embedding 预热（在平台 DB 和并行 Agent 就绪后）
    try:
        from platforms.parallel_agent import init_product_embeddings, _product_embedding_cache
        init_product_embeddings(
            settings.industry_config,
            settings.embedding_client,
        )
        print(f"[M2] Embedding 预热完成，缓存 {len(_product_embedding_cache)} 个商品向量")
    except Exception as e:
        print(f"[M2] Embedding 预热跳过: {e}")

    # M3: RAG 知识库初始化
    try:
        from tools.rag_tool import init_knowledge_retriever
        init_knowledge_retriever("mobile")
        print("[M3] RAG 知识库初始化完成")
    except Exception as e:
        print(f"[M3] RAG 知识库初始化跳过: {e}")

    # 初始化Agent（传入多模型配置和参数）
    agent = ReActAgent(
        client=settings.client,
        model=settings.model,
        tools=tool_registry.get_schemas(),
        tool_map=tool_registry.get_tool_map(),
        max_round=settings.max_round,
        config={
            # 多模型路由
            "model_react": getattr(settings, "model", "doubao-seed-2-0-pro-260215"),
            "model_plan": getattr(settings, "model_plan", "doubao-seed-2-0-code-preview-260215"),
            "model_synthesize": getattr(settings, "model_synthesize", "doubao-seed-2-0-pro-260215"),
            # Agent 参数
            "max_plan_steps": getattr(settings, "max_plan_steps", 8),
            "max_history_rounds": getattr(settings, "max_history_rounds", 6),
            "max_history_chars": getattr(settings, "max_history_chars", 6000),
            "complexity_keywords": getattr(settings, "complexity_keywords", None),
            "complexity_patterns": getattr(settings, "complexity_patterns", None),
            "max_reflection_retries": getattr(settings, "max_reflection_retries", 2),
            "auto_relax_attributes": getattr(settings, "auto_relax_attributes", True),
            "max_step_react_rounds": getattr(settings, "max_step_react_rounds", 2),
        },
    )


initialize()


@app.route('/')
def index():
    """首页"""
    return render_template('index.html')


@app.route('/api/products', methods=['GET'])
def get_products():
    """获取所有商品 — 从各平台 DB 聚合，同名商品只保留最低价"""
    try:
        parallel_agent = get_parallel_agent()
        result = parallel_agent.query_all_products_parallel()

        # 聚合所有平台商品，按 product_name 去重，保留最低价
        best_by_name = {}
        for platform_id, data in result.get("results", {}).items():
            for p in data.get("products", []):
                name = p.get("product_name", "")
                price = p.get("platform_price", p.get("price", 0))
                if name not in best_by_name or price < best_by_name[name].get("platform_price", float("inf")):
                    best_by_name[name] = p

        products = sorted(best_by_name.values(), key=lambda x: x.get("price", 0))
        return jsonify({"success": True, "products": products})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/products', methods=['POST'])
def create_product():
    """添加新商品 — 需指定 platform_id，写入对应平台 DB"""
    data = request.json
    platform_id = data.get("platform_id")
    if not platform_id:
        return jsonify({"success": False, "error": "缺少 platform_id 参数"}), 400
    try:
        platform_db = PlatformDatabase(platform_id)
        product = platform_db.add_product(
            product_name=data.get("product_name", ""),
            price=_safe_float(data.get("price"), 0),
            stock=_safe_int(data.get("stock"), 0),
            category=data.get("category", ""),
            platform_price=_safe_float(data.get("platform_price") or data.get("price")),
            shipping_fee=_safe_float(data.get("shipping_fee"), 0),
            is_in_stock=bool(data.get("is_in_stock", True)),
            color=data.get("color"),
            memory=data.get("memory"),
        )
        platform_db.close()
        return jsonify({"success": True, "product": product})
    except (ValueError, KeyError) as e:
        return jsonify({"success": False, "error": f"参数错误: {e}"}), 400
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
    image_url = data.get('image_url', '')

    # 如果没有session_id，创建新会话
    if not session_id:
        session_id = str(uuid.uuid4())
        create_session(db, session_id)

    # 如果附带图片，将图片URL追加到用户消息中（供 Agent 使用）
    agent_message = user_message
    if image_url:
        full_url = request.host_url.rstrip("/") + image_url
        agent_message = f"{user_message}\n[用户上传了商品图片: {full_url}]"

    # 保存用户消息（保存原始消息，方便前端展示）
    add_message(db, session_id, 'user', user_message)

    # 从数据库读取历史消息作为上下文（排除刚写入的当前消息）
    all_history = get_session_messages(db, session_id)
    history_for_agent = [
        {"role": msg["role"], "content": msg["content"]}
        for msg in all_history[:-1]  # 排除最后一条（刚写入的当前 user 消息）
        if msg.get("role") in ("user", "assistant") and msg.get("content")
    ]

    # 捕获Agent的输出
    old_stdout = sys.stdout
    sys.stdout = buffer = io.StringIO()

    try:
        # 运行Agent（传入历史上下文，如果有图片则消息包含图片URL）
        answer = agent.run(agent_message, history=history_for_agent, verbose=True)

        # 获取推理过程：结构化 trace（新） + 原始文本（兼容旧前端）
        reasoning_output = buffer.getvalue()
        trace_data = agent.trace.to_list()

        # 保存助手消息
        add_message(db, session_id, 'assistant', answer)

        return jsonify({
            "success": True,
            "session_id": session_id,
            "answer": answer,
            "reasoning": reasoning_output,
            "trace": trace_data,
        })
    finally:
        sys.stdout = old_stdout


@app.route('/api/chat/stream', methods=['POST'])
def chat_stream():
    """聊天接口 — SSE 实时流式传输推理过程"""
    data = request.json
    user_message = data['message']
    session_id = data.get('session_id')
    image_url = data.get('image_url', '')

    if not session_id:
        session_id = str(uuid.uuid4())
        create_session(db, session_id)

    agent_message = user_message
    if image_url:
        full_url = request.host_url.rstrip("/") + image_url
        agent_message = f"{user_message}\n[用户上传了商品图片: {full_url}]"

    add_message(db, session_id, 'user', user_message)

    all_history = get_session_messages(db, session_id)
    history_for_agent = [
        {"role": msg["role"], "content": msg["content"]}
        for msg in all_history[:-1]
        if msg.get("role") in ("user", "assistant") and msg.get("content")
    ]

    def generate():
        # 先发送 session_id，确保前端能同步新创建的会话
        init_event = json.dumps({"type": "session", "data": {"session_id": session_id}}, ensure_ascii=False)
        yield f"data: {init_event}\n\n"

        final_answer = ""
        try:
            for ev in agent.run_stream(agent_message, history=history_for_agent, verbose=True):
                event_json = json.dumps(ev.to_dict(), ensure_ascii=False)
                yield f"data: {event_json}\n\n"
                if ev.type == "done":
                    final_answer = ev.data.get("answer", "")
        except Exception as e:
            import traceback
            traceback.print_exc()
            err = json.dumps({"type": "error", "data": {"message": str(e)}}, ensure_ascii=False)
            yield f"data: {err}\n\n"

        if final_answer:
            add_message(db, session_id, 'assistant', final_answer)

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive',
        }
    )


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
        parallel_agent = get_parallel_agent()
        comparison = parallel_agent.compare_product_price(product_name)
        formatted_text = format_comparison_result(comparison)

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
        parallel_agent = get_parallel_agent()
        result = parallel_agent.query_all_products_parallel()

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

        price = _safe_float(data.get('price'), 0)
        platform_price = _safe_float(data.get('platform_price') or data.get('price'))
        product = platform_db.add_product(
            product_name=data.get('product_name', ''),
            price=price,
            stock=_safe_int(data.get('stock'), 0),
            category=data.get('category', ''),
            platform_price=platform_price,
            shipping_fee=_safe_float(data.get('shipping_fee'), 0),
            is_in_stock=bool(data.get('is_in_stock', True)),
            color=data.get('color'),
            memory=data.get('memory'),
            brand=data.get('brand'),
            processor=data.get('processor'),
            processor_brand=data.get('processor_brand'),
            performance_tier=data.get('performance_tier'),
            screen_size=_safe_float(data.get('screen_size')),
            battery=_safe_int(data.get('battery')),
            use_case_tags=data.get('use_case_tags'),
            description=data.get('description'),
        )
        platform_db.close()

        return jsonify({
            "success": True,
            "product": product
        })
    except (ValueError, KeyError) as e:
        return jsonify({
            "success": False,
            "error": f"参数错误: {e}"
        }), 400
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
            price=_safe_float(data.get('price')),
            stock=_safe_int(data.get('stock')),
            category=data.get('category'),
            platform_price=_safe_float(data.get('platform_price')),
            shipping_fee=_safe_float(data.get('shipping_fee')),
            is_in_stock=None if data.get('is_in_stock') is None else bool(data['is_in_stock']),
            color=data.get('color'),
            memory=data.get('memory'),
            brand=data.get('brand'),
            processor=data.get('processor'),
            processor_brand=data.get('processor_brand'),
            performance_tier=data.get('performance_tier'),
            screen_size=_safe_float(data.get('screen_size')),
            battery=_safe_int(data.get('battery')),
            use_case_tags=data.get('use_case_tags'),
            description=data.get('description'),
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
    except (ValueError, KeyError) as e:
        return jsonify({
            "success": False,
            "error": f"参数错误: {e}"
        }), 400
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


@app.route('/api/image-search', methods=['POST'])
def image_search():
    """图片搜索API — 上传图片URL，识别商品并比价"""
    data = request.json
    image_url = data.get('image_url')

    if not image_url:
        return jsonify({
            "success": False,
            "error": "请提供图片URL"
        }), 400

    try:
        from tools.image_search_tools import search_product_by_image
        result = search_product_by_image(
            image_url=image_url,
            color=data.get('color'),
            memory=data.get('memory'),
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ── 图片上传 ────────────────────────────────────────────────────────────────

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "static", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


@app.route("/api/upload-image", methods=["POST"])
def upload_image():
    """接收图片上传，返回访问 URL"""
    if "image" not in request.files:
        # 也支持 base64 JSON 方式
        data = request.get_json(silent=True)
        if data and data.get("image_base64"):
            try:
                img_data = base64.b64decode(data["image_base64"].split(",")[-1])
                ext = "png"
                filename = f"{uuid.uuid4().hex}.{ext}"
                filepath = os.path.join(UPLOAD_DIR, filename)
                with open(filepath, "wb") as f:
                    f.write(img_data)
                return jsonify({
                    "success": True,
                    "image_url": f"/static/uploads/{filename}",
                })
            except Exception as e:
                return jsonify({"success": False, "error": str(e)}), 400
        return jsonify({"success": False, "error": "请上传图片文件"}), 400

    file = request.files["image"]
    if file.filename == "":
        return jsonify({"success": False, "error": "文件名为空"}), 400

    # 限制文件大小 10MB
    file.seek(0, 2)
    size = file.tell()
    file.seek(0)
    if size > 10 * 1024 * 1024:
        return jsonify({"success": False, "error": "图片大小不能超过 10MB"}), 400

    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else "png"
    if ext not in ("jpg", "jpeg", "png", "gif", "webp", "bmp"):
        ext = "png"
    filename = f"{uuid.uuid4().hex}.{ext}"
    filepath = os.path.join(UPLOAD_DIR, filename)
    file.save(filepath)

    return jsonify({
        "success": True,
        "image_url": f"/static/uploads/{filename}",
    })


@app.teardown_appcontext
def teardown(exception):
    """应用关闭时清理资源"""
    cleanup_parallel_agent()


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001)
