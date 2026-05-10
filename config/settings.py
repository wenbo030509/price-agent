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
        self.api_key = os.getenv("ARK_API_KEY")
        if not self.api_key:
            raise ValueError(
                "ARK_API_KEY 未设置。请在 .env 文件中配置 ARK_API_KEY=your_key"
            )
        self.base_url = "https://ark.cn-beijing.volces.com/api/v3"
        self.model = os.getenv("ARK_MODEL", "doubao-seed-2-0-mini-260428")
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url
        )

    def _load_agent_config(self):
        """加载Agent配置"""
        self.max_round = 5


# 全局配置实例
settings = Settings()
