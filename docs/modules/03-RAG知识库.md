# Module 3: RAG 知识库

> 新增 `search_product_knowledge` 工具，通过现有 `@register_tool` 注册为第 6 个 Agent 工具。
> 构建手机领域知识库（处理器对比、机型评测），Agent 在需要时检索外部知识增强回答。
>
> **状态：已完成（2026-05-14）** — 33 项回归通过，21 chunk 索引，BM25+语义混合检索验证通过。
>
> **技术决策（2026-05-14）**：经评估 SynapseKit / ragplus / RAGLite，决定自研 + rank-bm25 混合检索。
>
> **修订记录**：
> - 2026-05-14 v1.2: 实施完成。改 10 个文件，新增 knowledge_indexer.py + rag_tool.py + 4 篇知识文档
---

## 一、模块定位

### 1.1 要解决的问题

当前 Agent 回答完全依赖两个信息源：
1. System prompt 中的静态规则（如何查价、如何输出格式）
2. 数据库中的商品字段（17 个结构字段）

这导致以下问题无法回答：

| 用户问 | 当前回答 | 缺失什么 |
|--------|---------|---------|
| "骁龙8Gen3 和 A17 Pro 打游戏哪个好" | 只能列搭载这两款芯片的机型价格 | 芯片性能对比知识 |
| "小米14 拍照真的比 iPhone 15 强吗" | 只能列价格差异 | 拍照评测知识 |
| "5000 以内性价比最高，为什么" | 能排序但说不清原因 | 综合评测 + 推荐理由 |
| "青海旅游带什么手机" | 完全无法理解 | 场景→属性推理 + 户外评测 |

### 1.2 目标

- 构建手机领域的轻量知识库（处理器对比、热门机型评测、参数解读）
- 新增 `search_product_knowledge` Agent 工具，走现有 `@register_tool` 注册
- Agent 在 Plan-Execute 的 Synthesize 阶段或 ReAct 循环中按需检索知识
- System prompt 更新，引导 Agent 何时使用该工具

### 1.3 不改什么

- `ToolRegistry` 注册机制
- `ReActAgent` 的工具调用循环
- 现有 5 个工具的行为
- 前端

---

## 二、方案设计

### 2.1 知识库范围（v0.1）

第一期聚焦三类高价值知识：

| 类型 | 内容示例 | 数量 | 来源 |
|------|---------|------|------|
| 处理器对比 | 骁龙8Gen3 vs A17 Pro vs 天玑9300：跑分、功耗、游戏帧率、AI 能力 | 5-8 篇 | 公开评测整理 |
| 机型评测 | 小米14、iPhone 15 Pro、红魔9 Pro：拍照样张、续航测试、散热表现 | 10-15 篇 | 公开评测整理 |
| 参数规格 | 屏幕、电池、重量、充电功率等官方数据表 | 1 份总表 | 官网数据 |

**v0.1 不做**：购机指南、数码资讯（这些更新频繁，维护成本高，P2 再考虑）。

### 2.2 知识存储

```python
"""
knowledge/mobile/
  processors/
    骁龙8Gen3.md
    A17_Pro.md
    天玑9300.md
    ...
  reviews/
    小米14.md
    iPhone_15_Pro.md
    红魔9_Pro.md
    ...
  specs/
    phone_specs_2024.md      # Markdown 表格
"""
```

Markdown 格式存储，便于人工维护和版本管理。索引时：
1. 读取文件 → 按 `## ` 标题分 chunk
2. 每个 chunk 做 embedding
3. 存入向量存储（复用 M2 的 embedding 基础设施）

### 2.3 索引流水线

```python
class KnowledgeIndexer:
    """知识库索引器 — 读取 Markdown 文件，分 chunk，embedding，入库"""
    
    def __init__(self, industry: str = "mobile"):
        self.industry = industry
        self.base_path = f"knowledge/{industry}/"
        self.chunks = []  # [{text, source, chunk_id, embedding}]
    
    def index_all(self):
        """遍历 knowledge/<industry>/ 下所有 .md 文件，索引"""
        for root, dirs, files in os.walk(self.base_path):
            for f in sorted(files):
                if f.endswith(".md"):
                    path = os.path.join(root, f)
                    chunks = self._chunk_file(path)
                    self.chunks.extend(chunks)
        
        # 批量 embedding
        self._embed_chunks()
    
    def _chunk_file(self, filepath: str) -> list:
        """
        分块策略：
        - 按 ## 标题切分，每个 section 为一个 chunk
        - chunk 大小控制在 300-800 字符
        - 过大的 section 按段落再切
        
        每个 chunk 携带元数据：source 文件名、section 标题
        """
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        
        # 按 ## 标题切分
        sections = re.split(r'\n(?=## )', content)
        chunks = []
        for sec in sections:
            sec = sec.strip()
            if not sec:
                continue
            # 提取标题作为元数据
            title_match = re.match(r'## (.+)', sec)
            title = title_match.group(1) if title_match else ""
            
            # 过长则按段落再切
            if len(sec) > 800:
                paragraphs = sec.split('\n\n')
                buffer = ""
                for p in paragraphs:
                    if len(buffer) + len(p) > 800 and buffer:
                        chunks.append({
                            "text": buffer.strip(),
                            "source": os.path.basename(filepath),
                            "section": title,
                        })
                        buffer = p
                    else:
                        buffer = (buffer + "\n\n" + p).strip()
                if buffer:
                    chunks.append({
                        "text": buffer,
                        "source": os.path.basename(filepath),
                        "section": title,
                    })
            else:
                chunks.append({
                    "text": sec,
                    "source": os.path.basename(filepath),
                    "section": title,
                })
        return chunks
    
    def _embed_chunks(self):
        """批量 embedding，使用 M2 相同的 EmbeddingClient"""
        import numpy as np
        from config import Settings
        
        client = Settings().embedding_client  # doubao-embedding-vision-251215
        texts = [c["text"] for c in self.chunks]
        
        # embed_texts 内部 ThreadPoolExecutor 并行
        embeddings = client.embed_texts(texts)
        for i, emb in enumerate(embeddings):
            self.chunks[i]["embedding"] = np.array(emb, dtype=np.float32)
```

### 2.4 检索器（BM25 + 语义混合检索）

```python
class KnowledgeRetriever:
    """知识检索器 — BM25 + 语义向量混合检索"""

    def __init__(self, indexer: KnowledgeIndexer):
        self.indexer = indexer
        self.embedding_client = Settings().embedding_client

    def retrieve(
        self,
        query: str,
        knowledge_type: str = "auto",
        top_k: int = 5,
        alpha: float = 0.7,   # 语义权重（0.7 = 语义为主，BM25 为辅）
    ) -> dict:
        """
        BM25 + 语义向量混合检索。

        先按 knowledge_type 预过滤，再计算两路得分：
        - semantic_score: cosine similarity（query embedding × chunk embedding）
        - bm25_score: 关键词匹配（BM25 算法）
        - final_score = alpha * semantic_score + (1-alpha) * bm25_score
        """
        import numpy as np

        # 按类型预过滤
        candidates = self._filter_by_type(self.indexer.chunks, knowledge_type)

        if not candidates:
            return {"success": True, "total_indexed": len(self.indexer.chunks), "references": []}

        # ── 语义得分 ──
        query_vec = self.embedding_client.embed_text(query)
        semantic_scores = []
        for chunk in candidates:
            if "embedding" not in chunk:
                continue
            chunk_vec = chunk["embedding"]
            sim = float(np.dot(query_vec, chunk_vec) / (
                np.linalg.norm(query_vec) * np.linalg.norm(chunk_vec)
            ))
            semantic_scores.append(sim)

        # 归一化语义分到 [0, 1]
        if semantic_scores:
            smin, smax = min(semantic_scores), max(semantic_scores)
            if smax > smin:
                semantic_scores = [(s - smin) / (smax - smin) for s in semantic_scores]
            else:
                semantic_scores = [0.5] * len(semantic_scores)

        # ── BM25 得分 ──
        from rank_bm25 import BM25Okapi

        # 简单分词（按空白 + 中文单字切分）
        corpus = [
            list(c["text"].replace(" ", ""))  for c in candidates
        ]
        bm25 = BM25Okapi(corpus)
        tokenized_query = list(query.replace(" ", ""))
        bm25_scores = bm25.get_scores(tokenized_query)

        # 归一化 BM25 分到 [0, 1]
        bmin, bmax = min(bm25_scores), max(bm25_scores)
        if bmax > bmin:
            bm25_scores = [(s - bmin) / (bmax - bmin) for s in bm25_scores]
        else:
            bm25_scores = [0.5] * len(bm25_scores)

        # ── 融合排序 ──
        merged = []
        for i, chunk in enumerate(candidates):
            final_score = alpha * semantic_scores[i] + (1 - alpha) * bm25_scores[i]
            merged.append((final_score, chunk))

        merged.sort(key=lambda x: x[0], reverse=True)
        top_chunks = merged[:top_k]

        return {
            "success": True,
            "total_indexed": len(self.indexer.chunks),
            "references": [
                {
                    "source": c.get("source", ""),
                    "section": c.get("section", ""),
                    "content": c["text"][:500],
                    "score": round(s, 4),
                }
                for s, c in top_chunks
            ]
        }

    def _filter_by_type(self, chunks: list, knowledge_type: str) -> list:
        """按知识类型预过滤"""
        if knowledge_type == "auto":
            return chunks

        type_dir_map = {
            "chipset_compare": "processors",
            "phone_review": "reviews",
            "spec_lookup": "specs",
        }
        target_dir = type_dir_map.get(knowledge_type)
        if not target_dir:
            return chunks

        return [c for c in chunks if c.get("source_dir", "") == target_dir]
```

**检索策略说明**：
- `alpha=0.7`：语义为主（理解意图），BM25 为辅（保证精确关键词命中）
- 两路得分归一化到 [0,1] 后加权融合，避免量纲不同导致的偏差
- 对中文的特殊处理：`list(text.replace(" ", ""))` 按字符切分，简单高效

### 2.5 Agent Tool 注册

```python
# tools/rag_tool.py

from .registry import register_tool

# 全局检索器实例（app 启动时初始化）
_retriever = None


def init_knowledge_retriever(industry: str = "mobile"):
    """在 app initialize() 中调用，初始化知识库"""
    global _retriever
    from tools.knowledge_indexer import KnowledgeIndexer, KnowledgeRetriever
    indexer = KnowledgeIndexer(industry)
    indexer.index_all()
    _retriever = KnowledgeRetriever(indexer)


@register_tool(
    name="search_product_knowledge",
    schema={
        "type": "function",
        "function": {
            "name": "search_product_knowledge",
            "description": (
                "检索手机领域知识库（处理器性能对比、机型评测、参数规格）。"
                "适用于：用户问'骁龙8Gen3和A17 Pro哪个好'、"
                "'小米14拍照怎么样'、'这个处理器什么水平'等需要专业知识的问题。"
                "注意：本工具返回的是评测/参数知识，不返回商品价格。查价格请用 multi_platform_price_comparison。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "自然语言查询，如 '骁龙8Gen3 游戏性能'、'小米14 拍照评测'"
                    },
                    "knowledge_type": {
                        "type": "string",
                        "description": (
                            "知识类型：chipset_compare(芯片对比) / phone_review(机型评测) / "
                            "spec_lookup(参数规格) / auto(自动判断)"
                        ),
                        "default": "auto",
                        "enum": ["auto", "chipset_compare", "phone_review", "spec_lookup"]
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "返回知识条数，默认 3",
                        "default": 3
                    }
                },
                "required": ["query"]
            }
        }
    },
)
def search_product_knowledge(
    query: str,
    knowledge_type: str = "auto",
    top_k: int = 3,
) -> dict:
    if _retriever is None:
        return {"success": False, "error": "知识库未初始化", "references": []}
    return _retriever.retrieve(query, knowledge_type, top_k)
```

### 2.6 System Prompt 更新

在 `agent/prompts.py` 的 `SYSTEM_PROMPT` 工具选择指南部分新增第 6 个工具说明：

```markdown
### 工具6: search_product_knowledge

**什么情况下用：**
- 用户问芯片性能对比 → "骁龙8Gen3 和 A17 Pro 哪个打游戏好"
- 用户问机型评测 → "小米14 拍照真的比 iPhone 15 强吗"
- 用户问处理器水平 → "天玑9300 是什么级别的芯片"
- 在推荐商品后，用户追问"为什么推荐这款" → 检索评测知识增强解释

**什么情况下不要用：**
- 用户只需要查价格 → 用 multi_platform_price_comparison
- 用户只需要推荐商品 → 用 semantic_product_search
- 知识库返回空结果 → 直接告知用户"暂未收录该信息"，不要编造

**使用策略：**
- 先调用其他工具（multi_platform_price_comparison / semantic_product_search）获取商品数据
- 再根据用户追问调用本工具检索评测/对比知识
- 综合商品数据 + 知识库内容给出最终回答
```

---

## 三、文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `tools/rag_tool.py` | **新增** | `search_product_knowledge` 工具 + 初始化函数 |
| `tools/knowledge_indexer.py` | **新增** | `KnowledgeIndexer` + `KnowledgeRetriever`（BM25 + 语义混合） |
| `tools/__init__.py` | 修改 | 新增 `from . import rag_tool` |
| `agent/prompts.py` | 修改 | `SYSTEM_PROMPT` 新增工具 6 的使用指南 |
| `knowledge/mobile/processors/` | **新增目录** | 处理器对比文档（5-8 篇 .md） |
| `knowledge/mobile/reviews/` | **新增目录** | 机型评测文档（10-15 篇 .md） |
| `knowledge/mobile/specs/` | **新增目录** | 参数规格表（1 份 .md） |
| `app.py` | 修改 | `initialize()` 中调 `init_knowledge_retriever("mobile")` |
| `config/industries/mobile.py` | 修改 | `enable_rag: True` |
| `requirements.txt` | 修改 | 新增 `rank-bm25` |

**不改的文件**：
- `tools/registry.py` — 注册机制通用
- `agent/react_engine.py` — 工具调用循环通用
- `platforms/` — 全部不动

---

## 四、知识库文档示例

### 4.1 处理器对比文档结构

```markdown
# 骁龙8Gen3

## 基本参数
- 制程：台积电 4nm
- CPU：1×Cortex-X4 @3.3GHz + 3×A720 @3.2GHz + 2×A720 @3.0GHz + 2×A520 @2.3GHz
- GPU：Adreno 750
- AI：Hexagon NPU，支持端侧 10B 参数模型

## 性能跑分
- 安兔兔 v10：约 210 万分
- Geekbench 6：单核 2300 / 多核 7200
- GFXBench 曼哈顿 3.1：约 260fps

## 游戏实测
- 原神 最高画质 60fps：平均帧率 59.2fps，功耗 5.2W，机身温度 43°C
- 崩坏：星穹铁道：平均帧率 58.5fps，功耗 5.8W

## 对比 A17 Pro
- 单核性能低于 A17 Pro 约 20%
- 多核性能基本持平
- GPU 峰值性能接近，持续性能优于 A17 Pro（散热更好）
- AI 算力低于 A17 Pro 的 Neural Engine

## 对比天玑9300
- CPU 多核性能略低于天玑9300
- GPU 性能旗鼓相当
- 功耗控制优于天玑9300
```

### 4.2 机型评测文档结构

```markdown
# 小米14

## 基本规格
- 处理器：骁龙8Gen3
- 屏幕：6.36寸 1.5K OLED，120Hz LTPO
- 电池：4610mAh，90W有线+50W无线
- 重量：193g

## 拍照评测
- 主摄：50MP 光影猎人900，1/1.31寸底，f/1.6
- 长焦：50MP 3.2x 光学变焦
- 超广角：50MP
- 徕卡色彩调校，直出色彩讨喜
- 夜景模式噪点控制优秀
- 视频支持 8K@24fps，4K@60fps

## 续航测试
- 日常综合使用：约 7.5 小时亮屏
- 游戏续航（原神）：约 3.5 小时
- 充电：90W 有线 0-100% 约 35 分钟

## 适合人群
- 追求直屏小尺寸旗舰的用户
- 徕卡色彩爱好者
- 游戏玩家（骁龙8Gen3 + 好散热）
- 不追求最顶级长焦的用户

## 竞品对比
- vs iPhone 15 Pro：屏幕更大、充电更快、价格低 3000+；但录像和生态不如苹果
- vs 小米14 Pro：配置接近但更小巧，性价比更高
```

---

## 五、测试方案

### 5.1 检索质量测试

```python
# tests/eval_m3_rag/test_retrieval.py

RAG_TEST_CASES = [
    # (query, knowledge_type, expected_source_contains)
    ("骁龙8Gen3 和 A17 Pro 对比", "chipset_compare", "骁龙8Gen3"),
    ("小米14 拍照怎么样", "phone_review", "小米14"),
    ("iPhone 15 Pro 电池容量", "spec_lookup", "iPhone 15 Pro"),
    ("天玑9300 是什么水平", "auto", "天玑9300"),
]
```

评估指标：
- **Precision@3**：返回的 3 条 chunk 中，相关的占多少
- **MRR**：第一个相关 chunk 的倒数排名

### 5.2 端到端测试

对比有/无 RAG 时的回答质量：

| 测试 query | 无 RAG 预期 | 有 RAG 预期 |
|-----------|-----------|-----------|
| "骁龙8Gen3 和 A17 Pro 打游戏哪个好" | "数据库中搭载这两款芯片的机型有..." | 包含芯片性能对比 + 推荐具体机型 |
| "小米14 拍照好吗" | "小米14 ¥3999，京东有售" | 包含徕卡影像、夜景表现等评测信息 |

### 5.3 测试文件

```
tests/
  eval_m3_rag/
    __init__.py
    test_indexer.py           ← 索引构建、chunk 分片正确性
    test_retrieval.py         ← Precision@3, MRR
    test_e2e.py               ← 有/无 RAG 回答质量对比
    test_hallucination.py     ← RAG 是否会引入幻觉
```

---

## 六、验收标准

- [ ] `KnowledgeIndexer.index_all()` 成功索引 `knowledge/mobile/` 下所有 .md 文件
- [ ] `search_product_knowledge(query="骁龙8Gen3 游戏性能")` 返回相关 chunk
- [ ] Agent 在 "芯片对比" 场景自动调用该工具
- [ ] 有 RAG 的回答质量显著优于无 RAG（人工评估）
- [ ] 知识库返回空时不编造信息
- [ ] 知识库索引耗时 < 5s（50 个 chunk 以内）
- [ ] 现有 P2 E2E 测试通过（RAG 不破坏已有功能）

---

## 七、依赖

```
M1: 行业配置框架 → enable_rag
M2: 语义召回升级 → EmbeddingClient（共享 doubao-embedding-vision-251215）

新增 Python 包: rank-bm25（纯 Python，PIP 一行安装）
```

M3 复用 M2 的 EmbeddingClient（`Settings().embedding_client`），索引和检索走同一套 embedding 基础设施。

---

## 八、真实场景下的知识库维护

> 当前 Demo 方案：工程师手写 .md → Git 提交 → 启动时索引。Demo 阶段完全合理。
> 但真实业务场景下需要回答三个问题：内容从哪来、谁负责维护、质量如何保证。

### 8.1 当前方案的局限

| 环节 | Demo（现在） | 真实场景的问题 |
|------|------------|--------------|
| 内容来源 | 工程师手写 | 工程师不懂芯片/拍照评测，写出来像参数搬运。手机行业每年上百款新机，靠人工不可持续 |
| 内容加工 | 无（手写即成品） | 一篇长评测可能 5000 字，需要拆成拍照/续航/性能等维度的短 chunk |
| 人工审核 | 无 | 谁审核？工程师不懂数码，内容运营招不到。全自动则无法保证准确度 |
| 存储格式 | .md 文件 | 无法记录"这条内容来源哪个评测""什么时候采集的""置信度如何" |
| 索引更新 | 启动时全量 | 新增一篇评测就要重启服务？不合理 |
| 质量监控 | 无 | 热门 query 有没有返回空？某条内容已过期？用户反馈有没有闭环？ |
| 多行业扩展 | 每行业加目录 | 笔记本看 GPU、相机看传感器——每行业需要不同的内容源和质量校验 |

### 8.2 真实场景的合理架构

四层分离，每层由不同角色负责：

```
┌─────────────────────────────────────────────────┐
│ Layer 1: 内容摄入（自动化）                       │
│ 爬虫/API → 原始内容入库                           │
│ 工程写爬虫，运营配置数据源                          │
├─────────────────────────────────────────────────┤
│ Layer 2: 内容加工（半自动）                       │
│ 原始内容 → LLM 摘要/结构化 → 人工抽检              │
│ LLM 加工，运营只看"冲突""低置信度"异常              │
├─────────────────────────────────────────────────┤
│ Layer 3: 知识索引（自动化）                       │
│ 结构化内容 → Embedding → 向量库                   │
│ 工程负责 ← 当前 M3 所做的工作                      │
├─────────────────────────────────────────────────┤
│ Layer 4: 质量监控（自动化 + 人工）                 │
│ 检索命中率 / 用户反馈 / 时效性检查                 │
│ 工程搭监控，运营处理告警                           │
└─────────────────────────────────────────────────┘
```

### 8.3 各层详细说明

**Layer 1 — 内容摄入**

工程团队写爬虫/API 适配器，从以下源自动拉取：
- GSMArena / 中关村在线 → 规格参数
- Geekbench / 安兔兔 → 跑分数据
- 快科技 / 数字尾巴 → 评测文章
- 电商评论 → 用户口碑

运营团队在后台配置"关注哪些机型""哪些评测源可信"，勾选开关即可，不需要写代码。

**Layer 2 — 内容加工**

LLM 自动做三件事：
1. **去重合并**：同一款机型的多条评测，识别并合并相似内容
2. **结构化拆分**：把长文评测按维度拆成短 chunk（拍照/续航/性能/散热）
3. **冲突检测**：评测 A 说续航 7h，评测 B 说续航 5h → 标记为"待人工确认"

运营的工作量大幅压缩：不看全部内容，只看 LLM 标记的"冲突""低置信度"异常条目。

**Layer 3 — 知识索引**

当前 M3 所做的工作。真实场景下需要升级：
- **增量索引**：新内容进来只 embed 新增的，不重跑全量（当前 21 个 chunk 无所谓，5 万 chunk 就不能全量了）
- **时效性权重**：新评测的检索权重高于旧评测（去年的处理器跑分不应排在今年的评测前面）
- **多行业路由**：根据 query 自动选择对应的知识库目录（当前用 `knowledge_type` 做简单预过滤）

**Layer 4 — 质量监控**

自动化指标：
- 检索命中率：热门 query 有没有返回空结果
- 时效性告警：某条 chunk 超过 N 天未更新（如"骁龙8Gen3"信息已发布 1 年）
- 用户反馈闭环：用户说"不对"/"过时了"→ 标记 chunk → 人工复核

### 8.4 角色分工

| 角色 | Demo（现在） | 真实场景 |
|------|------------|---------|
| 工程师 | 手写 .md 内容 | 搭摄入管道 + 索引管道 + 监控面板。**不写知识内容** |
| 运营/编辑 | 不存在 | 配置数据源、审核 LLM 标记的异常、处理用户反馈 |
| LLM | 不存在 | 摘要、结构化、冲突检测。无人工审核权限 |
| 领域专家 | 不存在 | 解决 LLM 判定不了的争议内容（极低频） |

### 8.5 结论

**Demo 阶段**：4 篇 .md + Git 版本控制，完全合理。零额外成本，改动即生效。

**真实场景**：核心矛盾不在"怎么存"（.md 足够），在于"谁负责内容"和"内容从哪来"。应演进为一个**内容运营平台**——工程搭摄入+索引管道，运营做数据源配置+质量抽检，LLM 做加工+摘要。工程师不应该写知识库内容，就像后端工程师不应该写 App 的运营文案。
