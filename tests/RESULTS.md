# Test 运行结果记录

> 运行时间：2026-05-14 13:00 ~ 13:10  
> 触发原因：修复 `_react_loop` tool_calls 并行处理 + `run()` intent UnboundLocalError + `test_color_memory.py` import 顺序  
> 运行环境：macOS, Python 3.13, DeepSeek API

## test_react_engine.py

| 状态 | **✓ 10/10 全部通过** |
|------|----------------------|
| 耗时 | <100ms（全部 mock，无 LLM 调用） |

| Case | 覆盖内容 | 结果 |
|------|----------|------|
| [1/10] _slide_window — 空输入 | 空列表返回空 | ✓ |
| [2/10] _slide_window — 过滤非 user/assistant | tool/system 角色被过滤 | ✓ |
| [3/10] _slide_window — 按轮数截断 | max_history_rounds=3 截断至 6 条 | ✓ |
| [4/10] _slide_window — 按字符数截断 | max_history_chars=20 截断 | ✓ |
| [5/10] _detect_intent | query/recommendation/comparison 分类 | ✓ |
| [6/10] _react_loop — 无工具调用 | 直接返回 LLM 答案 | ✓ |
| [7/10] _react_loop — 单工具调用 | 单 tool_call → 执行 → 最终答案 | ✓ |
| [8/10] **回归** — 多 tool_calls 数量匹配 | tool_calls=2 → tool 消息=2，防 400 错误 | ✓ |
| [9/10] ShoppingContext | 状态机 add/get_missing/reset | ✓ |
| [10/10] run — 意图路由 | 3 种意图各跑一次 | ✓ |

## test_m5_shopping.py

| 状态 | **✓ 全部通过** |
|------|---------------|
| 耗时 | ~60s（含 LLM 调用） |

| Case | 内容 | 结果 |
|------|------|------|
| [1/6] ShoppingContext 单元 | 状态机基本操作 | ✓ |
| [2/6] 意图分类 | 10 个 case 全部正确 | ✓ |
| [3/6] 槽位提取 | use_case/budget/brand/processor | ✓ |
| [4/6] 购物对话流程 | 3 轮：追问→推荐→筛选 | ✓ |
| [5/6] FOLLOW_UP + COMPARING | 对比触发 + 退出重置 | ✓ |
| [6/6] 已有功能回归 | 33/33 回归通过 | ✓ |

## test_query_fix.py

| 状态 | **✓ 全部通过** |
|------|---------------|

| 测试查询 | 京东 | 淘宝 | 拼多多 | 苏宁 |
|----------|------|------|--------|------|
| `iPhone 15` | ¥5999 | ¥5899 | ¥5750 | ¥6049 |
| `iPhone15` | ✓ | ✓ | ✓ | ✓ |
| `iphone15` | ✓ | ✓ | ✓ | ✓ |
| `IPHONE15` | ✓ | ✓ | ✓ | ✓ |
| ` iphone15 ` | ✓ | ✓ | ✓ | ✓ |
| `小米14` | ✓ | ✓ | ✓ | ✓ |
| `小米 14` | ✓ | ✓ | ✓ | ✓ |

## test_color_memory.py

| 状态 | **✓ 通过** |
|------|-----------|
| 备注 | 修复 import 顺序后运行，12 个商品颜色/内存字段正常 |

## test_m1_config.py

| 状态 | **✓ 7/7 全部通过** |
|------|-------------------|

| Case | 内容 |
|------|------|
| [1/7] Config 加载 | 17 个字段，默认值补齐 |
| [2/7] embedding_fields | 5 个字段正确 |
| [3/7] filter_fields | exact/range/tag_match 分组 |
| [4/7] 枚举值 | 7 场景标签 + 3 性能层级 + 14 处理器映射 |
| [5/7] 购物槽位 | 5 个槽位，1 个必填 |
| [6/7] Prompt 模板 | decompose 1083 chars, rerank 546 chars |
| [7/7] Settings 注入链路 | industry/mobile + 17 字段 + 未知行业回退 |

## test_m2_recall.py

| 状态 | **✓ 5/5 全部通过** |
|------|-------------------|

| Case | 内容 |
|------|------|
| [1/5] build_product_text | 104 chars 输出含商品名/品牌/处理器/场景 |
| [2/5] enable_vector_recall=False | 关闭时规则过滤行为不变 |
| [3/5] 向量召回效果 | 游戏手机语义召回 Top-1 小米14 |
| [4/5] 混合召回 | gaming + budget_max=8000 → 12 个结果 |
| [5/5] enable_vector_recall 完整流程 | 向量+规则混合，所有结果满足过滤条件 |

## test_m3_rag.py

| 状态 | **✓ 全部通过** |
|------|---------------|
| 耗时 | ~25s（含 Embedding API 调用） |

| Case | 内容 |
|------|------|
| [1/6] 索引构建与分片 | 21 个有效 chunk，全部通过校验 |
| [2/6] 检索质量 | 4/5 命中 Top-1，1 个未在 Top-3 |
| [3/6] 知识类型过滤 | chipset_compare/reviews/auto 过滤正确 |
| [4/6] Agent 工具注册 | 6 个工具均已注册，调用正常 |
| [5/6] 已有功能回归 | 16/16 回归通过 |
| [6/6] EmbeddingClient 缓存 | 懒加载 + 缓存正确 |

## test_embedding.py

| 状态 | **✓ 6/6 全部通过** |
|------|-------------------|
| 耗时 | ~3s（含 ARK API 调用） |

| Case | 内容 |
|------|------|
| [1/6] 单条文本 | 2048 维 float32 |
| [2/6] 并行批量 | 3 向量 x 2048 维，139ms |
| [3/6] 分批向量化 | 5 条 batch_size=2，3 批完成 |
| [4/6] 向量维度 | 2048 |
| [5/6] 语义相似度 | 拍照-拍照 0.544，拍照-学生 0.367，Δ=0.177 |
| [6/6] 商品召回模拟 | 2/4 命中，可调整 embedding_fields |

## test_multi_platform.py

| 状态 | **✓ 全部通过** |
|------|---------------|

| 测试 | 结果 |
|------|------|
| 单平台查询 | iPhone 15 京东 ¥5999 |
| 并行查询 iPhone 15 | 16 个匹配，最便宜拼多多 ¥5750 |
| 并行查询 小米平板6 | 4 个匹配，最便宜拼多多 ¥2099 |

## 汇总

| 测试文件 | 通过/总数 | 通过率 |
|----------|-----------|--------|
| test_react_engine.py | 10/10 | 100% |
| test_m5_shopping.py | 6/6 + 33 回归 | 100% |
| test_query_fix.py | 全部 | 100% |
| test_color_memory.py | 全部 | 100% |
| test_m1_config.py | 7/7 | 100% |
| test_m2_recall.py | 5/5 | 100% |
| test_m3_rag.py | 6/6 + 16 回归 | 100% |
| test_embedding.py | 6/6 | 100% |
| test_multi_platform.py | 全部 | 100% |
| **合计** | **9/9 文件** | **100%** |
