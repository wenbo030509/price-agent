"""
tools/knowledge_indexer.py
知识库索引与检索 — Markdown 分块 + Embedding + BM25 混合检索。

M3: 自研方案 + rank-bm25 混合检索。
- KnowledgeIndexer: 遍历 knowledge/<industry>/ 下 .md 文件，按 ## 标题分块，embedding 预热
- KnowledgeRetriever: BM25 + 语义向量混合检索
"""
import os
import re
import numpy as np
from typing import List, Dict, Optional


class KnowledgeIndexer:
    """知识库索引器 — 读取 Markdown，分 chunk，embedding，缓存"""

    def __init__(self, industry: str = "mobile"):
        self.industry = industry
        self.base_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "knowledge", industry
        )
        self.chunks: List[Dict] = []

    def index_all(self):
        """遍历 knowledge/<industry>/ 下所有 .md 文件"""
        if not os.path.isdir(self.base_path):
            return

        for root, dirs, files in os.walk(self.base_path):
            dirs.sort()
            for f in sorted(files):
                if f.endswith(".md"):
                    path = os.path.join(root, f)
                    source_dir = os.path.basename(os.path.dirname(path))
                    chunks = self._chunk_file(path, source_dir)
                    self.chunks.extend(chunks)

        if self.chunks:
            self._embed_chunks()

    def _chunk_file(self, filepath: str, source_dir: str) -> List[Dict]:
        """按 ## 标题分块，每块 300-800 字符，过长按段落再切"""
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        source = os.path.basename(filepath)

        # 去掉文件级标题（# xxx），保留 ## 标题
        sections = re.split(r'\n(?=## )', content)
        chunks = []
        for sec in sections:
            sec = sec.strip()
            if not sec or len(sec) < 50:   # 跳过空块和文档标题（# xxx 无实质内容）
                continue

            title_match = re.match(r'## (.+)', sec)
            title = title_match.group(1) if title_match else ""

            if len(sec) <= 800:
                chunks.append({
                    "text": sec,
                    "source": source,
                    "source_dir": source_dir,
                    "section": title,
                })
            else:
                # 按段落再切
                paragraphs = sec.split('\n\n')
                buf = ""
                for p in paragraphs:
                    if len(buf) + len(p) > 800 and buf:
                        chunks.append({
                            "text": buf.strip(),
                            "source": source,
                            "source_dir": source_dir,
                            "section": title,
                        })
                        buf = p
                    else:
                        buf = (buf + "\n\n" + p).strip()
                if buf:
                    chunks.append({
                        "text": buf,
                        "source": source,
                        "source_dir": source_dir,
                        "section": title,
                    })
        return chunks

    def _embed_chunks(self):
        """批量 embedding（复用 M2 的 EmbeddingClient）"""
        from config import Settings

        client = Settings().embedding_client
        texts = [c["text"] for c in self.chunks]
        embeddings = client.embed_texts(texts)

        for i, emb in enumerate(embeddings):
            self.chunks[i]["embedding"] = np.array(emb, dtype=np.float32)


class KnowledgeRetriever:
    """BM25 + 语义向量混合检索器"""

    def __init__(self, indexer: KnowledgeIndexer):
        self.indexer = indexer
        self.embedding_client = None  # 懒加载

    def _get_emb_client(self):
        if self.embedding_client is None:
            from config import Settings
            self.embedding_client = Settings().embedding_client
        return self.embedding_client

    def retrieve(
        self,
        query: str,
        knowledge_type: str = "auto",
        top_k: int = 5,
        alpha: float = 0.7,
    ) -> Dict:
        """BM25 + 语义混合检索"""
        candidates = self._filter_by_type(self.indexer.chunks, knowledge_type)

        if not candidates:
            return {
                "success": True,
                "total_indexed": len(self.indexer.chunks),
                "references": [],
            }

        # ── 语义得分 ──
        client = self._get_emb_client()
        query_vec = client.embed_text(query)

        semantic_scores = []
        for chunk in candidates:
            if "embedding" not in chunk:
                semantic_scores.append(0.0)
                continue
            cv = chunk["embedding"]
            sim = float(np.dot(query_vec, cv) / (
                np.linalg.norm(query_vec) * np.linalg.norm(cv)
            ))
            semantic_scores.append(sim)

        # 归一化到 [0,1]
        smin, smax = min(semantic_scores), max(semantic_scores)
        if smax > smin:
            semantic_scores = [(s - smin) / (smax - smin) for s in semantic_scores]
        else:
            semantic_scores = [0.5] * len(semantic_scores)

        # ── BM25 得分 ──
        from rank_bm25 import BM25Okapi

        # 中文按字符切分
        corpus = [list(c["text"].replace(" ", "")) for c in candidates]
        bm25 = BM25Okapi(corpus)
        tokenized = list(query.replace(" ", ""))
        bm25_scores = bm25.get_scores(tokenized)

        bmin, bmax = min(bm25_scores), max(bm25_scores)
        if bmax > bmin:
            bm25_scores = [(s - bmin) / (bmax - bmin) for s in bm25_scores]
        else:
            bm25_scores = [0.5] * len(bm25_scores)

        # ── 融合 ──
        merged = []
        for i, chunk in enumerate(candidates):
            score = alpha * semantic_scores[i] + (1 - alpha) * bm25_scores[i]
            merged.append((score, chunk))

        merged.sort(key=lambda x: x[0], reverse=True)

        return {
            "success": True,
            "total_indexed": len(self.indexer.chunks),
            "references": [
                {
                    "source": c.get("source", ""),
                    "source_dir": c.get("source_dir", ""),
                    "section": c.get("section", ""),
                    "content": c["text"][:500],
                    "score": round(s, 4),
                }
                for s, c in merged[:top_k]
            ],
        }

    def _filter_by_type(self, chunks: List[Dict], knowledge_type: str) -> List[Dict]:
        if knowledge_type == "auto":
            return chunks
        type_dir_map = {
            "chipset_compare": "processors",
            "phone_review": "reviews",
            "spec_lookup": "specs",
        }
        target = type_dir_map.get(knowledge_type)
        if not target:
            return chunks
        return [c for c in chunks if c.get("source_dir", "") == target]
