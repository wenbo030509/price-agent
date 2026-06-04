"""
AB Test Demo — Agent 实验效果评估
独立 Flask 应用，复用 price-agent 的 Agent 框架。

启动: cd abtest-demo && python app.py
访问: http://localhost:5002
"""

import sys
import os
import json
import time
from pathlib import Path

LOCAL_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(LOCAL_DIR)

# 本地目录优先（避免 tools 与父项目 tools/ 冲突），父项目 agent/ 次之
sys.path.insert(0, LOCAL_DIR)
sys.path.insert(1, PARENT_DIR)

# 加载父项目的 .env 文件
from dotenv import load_dotenv
load_dotenv(os.path.join(PARENT_DIR, ".env"))

from flask import Flask, render_template, request, jsonify, Response, stream_with_context
from flask_cors import CORS
from openai import OpenAI

from agent.react_engine import ReActAgent
from agent.trace import TraceCollector, TraceEvent, EventType
from agent.skills.loader import SkillLoader
from tools import TOOL_SCHEMAS, TOOL_MAP

app = Flask(__name__)
CORS(app)

# ── LLM 客户端 ──
API_KEY = os.getenv("DEEPSEEK_API_KEY")
if not API_KEY:
    raise RuntimeError(
        "DEEPSEEK_API_KEY 未设置。请在 price-agent/.env 文件中配置 DEEPSEEK_API_KEY=your_key"
    )

client = OpenAI(api_key=API_KEY, base_url="https://api.deepseek.com")
MODEL = "deepseek-v4-flash"

# ── Agent 初始化 ──
agent = ReActAgent(
    client=client,
    model=MODEL,
    tools=TOOL_SCHEMAS,
    tool_map=TOOL_MAP,
    max_round=12,
    config={
        "model_react": MODEL,
        "model_plan": MODEL,
        "model_synthesize": MODEL,
        "max_history_rounds": 8,
        "max_history_chars": 8000,
    },
)

# ── Skills 架构：加载本地 AB 实验分析技能 ──
_skills_dir = Path(LOCAL_DIR) / "skills"
agent.skill_loader = SkillLoader(_skills_dir)
# 覆盖意图解析：始终加载 abtest_analysis 技能
agent._resolve_skills = lambda intent="", **kw: {"abtest_analysis"}
# 预加载技能，让 _build_skill_system_prompt() 使用 SKILL.md 内容
agent._preload_skills({"abtest_analysis"})


# ═══════════════════════════════════════════════════════════
# 页面路由
# ═══════════════════════════════════════════════════════════

@app.route("/")
def index():
    return render_template("index.html")


# ═══════════════════════════════════════════════════════════
# Chat API（SSE 流式）
# ═══════════════════════════════════════════════════════════

@app.route("/api/chat/stream", methods=["POST"])
def chat_stream():
    data = request.get_json()
    if not data:
        return jsonify({"error": "请求体为空"}), 400

    query = data.get("query", "").strip()
    if not query:
        return jsonify({"error": "查询为空"}), 400

    def generate():
        agent.trace.reset()
        agent.trace.start_stream()

        # 在后台线程运行 agent
        import threading

        answer_holder = [""]

        def run():
            try:
                result = agent.run(
                    user_query=query,
                    history=None,
                    verbose=False,
                )
                answer_holder[0] = result or ""
            except Exception as e:
                answer_holder[0] = f"分析过程出错: {str(e)}"
                agent.trace.error(message=str(e), context="agent_run")
            finally:
                agent.trace.finish_stream(answer_holder[0])

        thread = threading.Thread(target=run, daemon=True)
        thread.start()

        # 流式输出 TraceEvent
        for ev in agent.trace.iter_events():
            event_json = json.dumps(ev.to_dict(), ensure_ascii=False)
            yield f"data: {event_json}\n\n"

        thread.join(timeout=120)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ═══════════════════════════════════════════════════════════
# 健康检查
# ═══════════════════════════════════════════════════════════

@app.route("/api/health")
def health():
    return jsonify({
        "status": "ok",
        "model": MODEL,
        "tools": list(TOOL_MAP.keys()),
    })


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5002)
