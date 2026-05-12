import os
from dotenv import load_dotenv
from openai import OpenAI


class Settings:
    """配置管理类"""

    def __init__(self):
        load_dotenv()
        self._load_api_config()
        self._load_agent_config()

    def _load_api_config(self):
        """加载API配置"""
        # DeepSeek API（OpenAI 兼容）
        self.api_key = os.getenv("DEEPSEEK_API_KEY")
        if not self.api_key:
            raise ValueError(
                "DEEPSEEK_API_KEY 未设置。请在 .env 文件中配置 DEEPSEEK_API_KEY=your_key"
            )
        self.base_url = "https://api.deepseek.com"

        # ── 多模型路由配置 ──
        # 文本模型统一使用 DeepSeek
        self.model = os.getenv(
            "DEEPSEEK_MODEL", "deepseek-v4-flash"
        )  # 默认/兜底模型（ReAct 循环）
        self.model_plan = os.getenv(
            "DEEPSEEK_MODEL_PLAN", "deepseek-v4-flash"
        )  # Phase 1 Plan 生成
        self.model_synthesize = os.getenv(
            "DEEPSEEK_MODEL_SYNTHESIZE", "deepseek-v4-flash"
        )  # Phase 3 综合回答
        self.model_parse = os.getenv(
            "DEEPSEEK_MODEL_PARSE", "deepseek-v4-flash"
        )  # 属性解析（简单提取）

        # 视觉模型暂不更换，仍使用豆包
        self.model_vision = os.getenv(
            "ARK_VISION_MODEL", "doubao-seed-2-0-pro-260215"
        )  # 图片识别（多模态模型）

        # 文本模型共享 DeepSeek client
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url
        )

    def _load_agent_config(self):
        """加载Agent配置"""
        self.max_round = 5

        # Plan-Execute 配置
        self.max_plan_steps = 8

        # 滑动窗口配置
        self.max_history_rounds = 6
        self.max_history_chars = 6000

        # 复杂度判断关键词（可通过环境变量 COMPLEXITY_KEYWORDS 扩展，逗号分隔）
        default_keywords = [
            "对比", "比较", "vs", "和", "与", "以及", "还有",
            "分析", "推荐", "建议", "哪个更", "怎么选", "哪个好",
            "并且", "同时", "还要", "另外", "分别",
        ]
        env_keywords = os.getenv("COMPLEXITY_KEYWORDS", "")
        if env_keywords:
            default_keywords.extend(kw.strip() for kw in env_keywords.split(",") if kw.strip())
        self.complexity_keywords = default_keywords

        # 复杂度判断结构模式（正则）
        self.complexity_patterns = [
            r".*(?:和|与|以及).*(?:都|分别|各).*",
            r".*(?:哪|什么|怎么).*(?:更|最|比较).*",
            r".*(?:除了|还有|另外).*",
        ]

        # 自反思重试配置
        self.max_reflection_retries = 2
        self.auto_relax_attributes = True
        self.max_step_react_rounds = 2  # Plan-Execute 每 Step 的 mini-ReAct 最大轮数


# 全局配置实例
settings = Settings()
