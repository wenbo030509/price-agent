# 测试指南

## 概述

本项目测试采用**纯 Python 脚本 + assert 断言**的轻量级方式，不依赖 pytest/unittest 等第三方测试框架。每个测试文件独立运行，按功能模块组织。

## 测试文件一览

| 文件 | 覆盖范围 | 类型 | 运行命令 |
|------|----------|------|----------|
| `test_m1_config.py` | 行业配置加载、默认值补齐、Schema 验证 | 单元 | `python3 tests/test_m1_config.py` |
| `test_m2_recall.py` | 向量召回、规则过滤、混合检索、开关降级 | 单元+集成 | `python3 tests/test_m2_recall.py` |
| `test_m3_rag.py` | 知识库索引、BM25+语义检索、工具注册 | 单元+集成 | `python3 tests/test_m3_rag.py` |
| `test_m5_shopping.py` | ShoppingContext 状态机、意图分类、槽位提取、对话流程 | 单元 | `python3 tests/test_m5_shopping.py` |
| `test_embedding.py` | Embedding API 连通性、向量维度、语义相似度 | 集成 | `python3 tests/test_embedding.py` |
| `test_multi_platform.py` | 多平台并行查询、结果格式化 | 集成 | `python3 tests/test_multi_platform.py` |
| `test_query_fix.py` | 商品查询大小写/空格容错 | 集成 | `python3 tests/test_query_fix.py` |
| `test_color_memory.py` | 颜色/内存字段读写 | 集成 | `python3 tests/test_color_memory.py` |
| `test_react_engine.py` | ReActAgent 核心路径、tool_calls 匹配、意图路由 | 单元 | `python3 tests/test_react_engine.py` |

## 什么时候写测试

### 必须写测试（P0）

以下场景**必须**编写测试，建议在代码提交前完成：

| 场景 | 示例 |
|------|------|
| **新功能上线** | 新增 M5 引导式购物 → 写 `test_m5_shopping.py` |
| **Bug 修复** | 修复 tool_calls 与 tool messages 数量不匹配 → 写回归用例 |
| **API 接口变更** | 修改工具 Schema、新增/删除参数 → 更新已有测试 |
| **数据流/管道变更** | 修改历史消息处理、意图路由逻辑 → 验证端到端路径 |
| **依赖升级** | 升级 openai 库、切换模型 → 验证 API 调用仍然正确 |

### 建议写测试（P1）

以下场景建议写测试，可按迭代节奏安排：

| 场景 | 示例 |
|------|------|
| **性能优化** | 并行化工具调用 → 验证结果一致性 |
| **配置变更** | 新增行业配置字段、调整默认值 → 验证加载和回退 |
| **开关/降级** | 新增 `enable_vector_recall` 开关 → 验证开/关行为 |
| **第三方集成** | 对接新的 Embedding API → 验证连通性和数据格式 |

### 可以不写测试（P2）

| 场景 | 说明 |
|------|------|
| 纯前端 UI 调整 | 通过手动回归验证 |
| 日志/打印格式修改 | 不影响业务逻辑 |
| 临时调试代码 | 提交前已移除 |

## 测试模式与约定

### 1. 文件结构

每个测试文件遵循固定的头部模板：

```python
"""测试文档字符串 — 简述测试范围和目的"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```

此后再 import 项目模块。`sys.path.insert` 必须在项目 import 之前。

### 2. 测试函数组织

将测试按功能拆分为独立函数，每个函数打印 `[N/M]` 格式的进度标识：

```python
def test_load_default():
    """Config 加载 + 默认值补齐"""
    print("[1/7] Config 加载与默认值补齐...")
    # ... assert 断言 ...
    print(f"  ✓ 加载成功，{len(config)} 个字段")
```

### 3. 断言风格

- 优先使用 `assert` + 描述性错误信息，失败时能快速定位
- 预期/实际值放在 `f-string` 中，便于阅读

```python
assert len(fields) >= 3, f"至少 3 个字段，实际 {len(fields)}"
assert "product_name" in fields, "须包含 product_name"
```

### 4. 结果输出

- 成功输出 `✓`，失败输出 `✗`
- 复杂场景打印关键数据（如 Top-5 结果、向量维度）
- 通过/失败在末尾汇总

### 5. 入口约定

```python
if __name__ == "__main__":
    # 按依赖顺序注册测试函数
    tests = [test_a, test_b, test_c]
    all_pass = True
    for t in tests:
        try:
            t()
        except Exception as e:
            print(f"  ✗ FAIL: {e}")
            import traceback
            traceback.print_exc()
            all_pass = False

    print("\n" + "=" * 65)
    print("✓ 全部测试通过" if all_pass else "✗ 存在失败用例")
    print("=" * 65)
```

## 什么时候调用测试

### 本地开发

```
# 修改了哪个模块，就跑对应的测试
python3 tests/test_react_engine.py

# 提交前跑全部测试
for f in tests/test_*.py; do echo "== $f =="; python3 "$f" || break; done
```

### CI/CD 建议

推荐在以下时机自动触发测试：

| 触发时机 | 范围 |
|----------|------|
| **Pull Request** | 全量测试（9 个文件） |
| **push 到 main** | 全量测试 |
| **pre-commit hook** | 仅运行修改模块对应的测试文件 |
| **每日定时** | `test_embedding.py`（验证 API 连通性） |

### 有外部依赖的测试

以下测试需要 API Key（`.env` 配置）才能运行：

- `test_embedding.py` — 调用火山引擎 ARK Embedding API
- `test_m2_recall.py` — 向量召回依赖 EmbeddingClient
- `test_m3_rag.py` — 知识库索引依赖 EmbeddingClient

这些测试在没有 API Key 的环境会失败，建议 CI 中配置 secrets 或跳过。

## 测试设计中应包含的内容

### 1. 正常路径验证

覆盖功能的正常使用流程，输入典型参数，验证输出符合预期。

```python
# 例：单工具调用 → 最终答案
tool_msg.tool_calls = [_make_tc(1, "echo", {"msg": "hello"})]
answer = agent._react_loop("test", None, verbose=False)
assert answer == "答案是 hello"
```

### 2. 边界条件

测试极限输入：

- 空输入（`None`、`[]`、`""`）
- 超量输入（超过滑动窗口上限）
- 边界值（`max_round=0`、`max_round=1`）
- 特殊字符（中文、Unicode、长文本）

### 3. 错误处理

验证异常场景不会崩溃，有合理的降级行为：

- 工具未注册 → 返回 error 而非崩溃
- 工具执行异常 → 返回 error 而非崩溃
- API 返回错误格式 → catch 不扩散

### 4. 回归测试

针对已修复的 Bug，保留对应的测试用例，防止再次引入：

```python
def test_react_loop_multi_tool_calls_bug():
    """修复: tool_calls=2 时 tool 消息也必须是 2 条（防 400 错误回归）"""
    # ... mock API 返回 2 个 tool_calls ...
    # 验证第二轮调用时 messages 中有 2 条 tool 消息
    assert tool_msg_count == 2
```

### 5. 开关/降级验证

对于有功能开关的模块，需要验证：

- 关闭开关 → 行为与改动前完全一致（`test_disable_flag_preserves_behavior`）
- 开启开关 → 新功能正常生效

### 6. 数据完整性校验

处理外部数据时验证关键字段存在、类型正确、值在合理范围：

```python
for c in chunks:
    assert "text" in c, f"chunk 缺 text"
    assert isinstance(c["embedding"], np.ndarray)
    assert c["embedding"].shape == (2048,)
```

### 7. Mock 外部依赖

单元测试中 mock 掉外部 API 调用，确保测试快速、稳定、无网络依赖：

```python
mock_client = MagicMock()
mock_client.chat.completions.create.return_value = MagicMock(
    choices=[MagicMock(message=mock_msg)]
)
agent = ReActAgent(client=mock_client, ...)
```

## 命名规范

- 文件名：`test_<功能模块>.py`，如 `test_react_engine.py`
- 函数名：`test_<测试内容>`，如 `test_slide_window_empty`
- 里程碑测试：`test_m<编号>_<功能>.py`，如 `test_m5_shopping.py`
