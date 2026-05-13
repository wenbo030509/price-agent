import os
from dotenv import load_dotenv
from openai import OpenAI


class Settings:
    """配置管理类"""

    def __init__(self):
        load_dotenv()
        self._load_api_config()
        self._load_embedding_config()
        self._load_agent_config()

    def _load_api_config(self):
        """加载 API 配置"""
        # DeepSeek API（OpenAI 兼容）— 文本模型
        self.api_key = os.getenv("DEEPSEEK_API_KEY")
        if not self.api_key:
            raise ValueError(
                "DEEPSEEK_API_KEY 未设置。请在 .env 文件中配置 DEEPSEEK_API_KEY=your_key"
            )
        self.base_url = "https://api.deepseek.com"

        # ── 多模型路由配置 ──
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

        # 视觉模型 — 火山引擎 ARK
        self.model_vision = os.getenv(
            "ARK_VISION_MODEL", "doubao-seed-2-0-pro-260215"
        )

        # 文本模型 client（DeepSeek）
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url
        )

    def _load_embedding_config(self):
        """加载 Embedding 配置 — 火山引擎 ARK 多模态 Embedding"""
        # ARK API Key — 与视觉模型共用同一个 key
        self.ark_api_key = os.getenv("ARK_API_KEY", "")
        self.embedding_model = os.getenv(
            "ARK_EMBEDDING_MODEL", "doubao-embedding-vision-251215"
        )
        self.embedding_base_url = os.getenv(
            "ARK_EMBEDDING_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"
        )

        # 延迟初始化 embedding_client（避免 import 时无 ark_api_key 就报错）
        self._embedding_client = None

    @property
    def embedding_client(self):
        """懒加载 embedding client"""
        if self._embedding_client is None:
            if not self.ark_api_key:
                raise ValueError(
                    "ARK_API_KEY 未设置。请在 .env 文件中配置 ARK_API_KEY=your_key"
                )
            from .embedding import EmbeddingClient
            self._embedding_client = EmbeddingClient(
                api_key=self.ark_api_key,
                model=self.embedding_model,
                base_url=self.embedding_base_url,
            )
        return self._embedding_client

    def _load_agent_config(self):
        """加载 Agent 配置"""
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
        self.max_step_react_rounds = 2

        # ── 行业配置 ──
        self.industry = os.getenv("INDUSTRY", "mobile")
        self._load_industry_config()

    def _load_industry_config(self):
        """加载行业 Config — 从 config/industries/<industry>.py 动态加载"""
        try:
            from .industry_loader import load_industry_config
            self.industry_config = load_industry_config(self.industry)
        except Exception:
            self.industry_config = {}

    def reload_industry_config(self, industry: str = None):
        """重新加载行业 Config（热切换行业用）"""
        if industry:
            self.industry = industry
        try:
            from .industry_loader import load_industry_config, clear_cache
            clear_cache(self.industry)
            self.industry_config = load_industry_config(self.industry)
        except Exception:
            pass


# 全局配置实例
settings = Settings()
