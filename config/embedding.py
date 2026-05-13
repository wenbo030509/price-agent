"""
config/embedding.py
火山引擎 ARK 多模态 Embedding 客户端。

API: POST https://ark.cn-beijing.volces.com/api/v3/embeddings/multimodal
Model: doubao-embedding-vision-251215
维度: 2048
Docs: https://www.volcengine.com/docs/82379/1523520?lang=zh

注意：该端点将多个输入（text/image/video）融合为单个 embedding 向量。
因此批量文本需要逐条调用，内部用 ThreadPoolExecutor 并行加速。
"""
import requests
import numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional


class EmbeddingClient:
    """火山引擎 ARK Embedding 客户端，支持文本向量化"""

    def __init__(
        self,
        api_key: str,
        model: str = "doubao-embedding-vision-251215",
        base_url: str = "https://ark.cn-beijing.volces.com/api/v3",
        timeout: int = 30,
        max_workers: int = 8,
    ):
        self.api_key = api_key
        self.model = model
        self.endpoint = f"{base_url}/embeddings/multimodal"
        self.timeout = timeout
        self.max_workers = max_workers

    # ── 单条向量化 ─────────────────────────────────────────────────

    def embed_text(self, text: str, encoding_format: str = "float") -> np.ndarray:
        """
        单条文本 → 向量。

        Args:
            text: 输入文本
            encoding_format: float | base64

        Returns:
            np.ndarray: 2048 维 float32 向量
        """
        payload = {
            "model": self.model,
            "encoding_format": encoding_format,
            "input": [{"type": "text", "text": text}],
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        try:
            resp = requests.post(
                self.endpoint,
                json=payload,
                headers=headers,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Embedding API 调用失败: {e}")

        # 返回格式: {"data": {"embedding": [...], "object": "embedding"}}
        emb_data = data.get("data", {})
        embedding = emb_data.get("embedding", [])

        if not embedding:
            raise RuntimeError(f"Embedding 返回为空: {str(data)[:200]}")

        return np.array(embedding, dtype=np.float32)

    # ── 批量向量化（并行）───────────────────────────────────────────

    def embed_texts(
        self,
        texts: List[str],
        max_workers: Optional[int] = None,
    ) -> List[np.ndarray]:
        """
        批量文本向量化，ThreadPoolExecutor 并行调用。

        Args:
            texts: 文本列表
            max_workers: 并发数，默认 8

        Returns:
            List[np.ndarray]: 与 texts 等长的向量列表
        """
        if not texts:
            return []

        workers = max_workers or self.max_workers
        results = [None] * len(texts)

        def _embed_one(idx: int, text: str):
            return idx, self.embed_text(text)

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(_embed_one, i, t): i
                for i, t in enumerate(texts)
            }
            for future in as_completed(futures):
                try:
                    idx, vec = future.result(timeout=self.timeout + 5)
                    results[idx] = vec
                except Exception as e:
                    raise RuntimeError(
                        f"Embedding 第 {futures[future]} 条失败: {e}"
                    )

        return results

    # ── 工具方法 ────────────────────────────────────────────────────

    @property
    def dimension(self) -> Optional[int]:
        """获取向量维度（首次调用后缓存）"""
        if not hasattr(self, "_dimension"):
            try:
                emb = self.embed_text("dimension probe")
                self._dimension = len(emb)
            except Exception:
                self._dimension = None
        return self._dimension

    def embed_batched(
        self,
        texts: List[str],
        batch_size: int = 8,
    ) -> List[np.ndarray]:
        """
        大批量向量化，分批 + 并行。

        Args:
            texts: 文本列表
            batch_size: 每批并发数（不要太大，避免触发限流）

        Returns:
            List[np.ndarray]: 全部向量
        """
        all_embeddings = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            all_embeddings.extend(self.embed_texts(batch))
        return all_embeddings
