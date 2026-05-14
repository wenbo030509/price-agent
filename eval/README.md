# Eval 评估体系

## 概述

`eval/` 目录是项目质量保障的第二道防线。与 `tests/` 不同，eval 侧重于**端到端+LLM 行为验证**，通过对比 Agent 输出与 Ground Truth 来量化质量指标。

### eval 与 tests 的分工

| 维度 | `tests/` | `eval/` |
|------|----------|---------|
| 测试对象 | 函数/模块（纯代码） | Agent 行为（含 LLM 调用） |
| 运行速度 | 毫秒级 | 秒到分钟级 |
| 外部依赖 | 大部分可 mock | 需要 LLM API Key |
| 验证方式 | assert 断言 | 阶段性评分 + 汇总报告 |
| 执行频率 | 每次修改后 | PR / 每日 / 发版前 |

## 评估阶段

评估分 6 个阶段（P0-P6），渐进式地覆盖从底层逻辑到 LLM 行为：

| 阶段 | 文件 | 含义 | LLM 调用 | 预计耗时 |
|------|------|------|----------|----------|
| P0 | `eval_p0_unit.py` | 单元测试：DB CRUD、属性匹配、并行查询、Bug 回归 | 否 | 3s |
| P1 | `eval_p1_parse.py` | 属性提取：LLM 将用户输入解析为结构化参数 | 单次 | 40s |
| P2 | `eval_p2_e2e.py` | 端到端：完整 ReAct/Plan-Execute 循环 | 多次 | 2min |
| P3 | `eval_p3_boundary.py` | 能力边界：异常输入、歧义、矛盾需求、多轮对话 | 多次 | 90s |
| P4 | `eval_p4_benchmark.py` | 汇总报告：从最新 P0-P3 报告生成综合基准 | 否 | 1s |
| P5 | `eval_p5_optimization.py` | 优化验证：自反思纠错、Prompt 质量、依赖注入、复杂度 | 多次 | 2min |
| P6 | `eval_p6_image.py` | 图片搜索：工具注册、属性解析、E2E 图片链路 | 可选 | 30s |

### 行业专项评估

| 文件 | 含义 |
|------|------|
| `eval_it3c.py` | IT3C 行业优化：语义过滤、意图分类、处理器别名、向量召回、购物意图 |

## 运行方式

### 单阶段执行

```bash
# 不依赖 LLM 的测试（最快）
python3 eval/eval_p0_unit.py

# 需要 LLM 的单次调用
python3 eval/eval_p1_parse.py

# 需要多次 LLM 调用（耗时较长）
python3 eval/eval_p2_e2e.py
python3 eval/eval_p3_boundary.py
python3 eval/eval_p5_optimization.py

# 汇总所有阶段结果
python3 eval/eval_p4_benchmark.py
```

### IT3C 行业评估

```bash
# 仅 P0 单元（不调 LLM）
python3 eval/eval_it3c.py

# 全量（含 P1/P2 LLM 调用）
python3 eval/eval_it3c.py --all
```

### 全量执行

```bash
# 依次运行所有阶段，最后汇总
python3 eval/eval_p0_unit.py && \
python3 eval/eval_it3c.py --all && \
python3 eval/eval_p1_parse.py && \
python3 eval/eval_p2_e2e.py && \
python3 eval/eval_p3_boundary.py && \
python3 eval/eval_p5_optimization.py && \
python3 eval/eval_p6_image.py && \
python3 eval/eval_p4_benchmark.py
```

## 结果文件

所有评估结果自动保存到 `eval/results/`，命名规则：`YYYY-MM-DD_HHmmss_<阶段>.json`

```
eval/results/
├── 2026-05-14_125519_P0_unit.json
├── 2026-05-14_125548_IT3C.json
├── 2026-05-14_125646_P1_parse.json
├── 2026-05-14_125741_P2_e2e.json
├── 2026-05-14_125926_P3_boundary.json
├── 2026-05-14_130121_P5_optimization.json
├── 2026-05-14_125558_P6_image.json
├── 2026-05-14_130911_P4_benchmark.json
└── ...
```

最新汇总结果见 [RESULTS.md](RESULTS.md)。

### JSON 报告结构

```json
{
  "phase": "P2_e2e",
  "total": 17,
  "passed": 13,
  "failed": 4,
  "pass_rate": "76.5%",
  "duration_ms": 110032,
  "cases": [
    {
      "case_id": "E2E-01",
      "passed": true,
      "details": {
        "query": "iPhone 15 在哪个平台最便宜",
        "answer_preview": "iPhone 15 最便宜的平台是拼多多...",
        "checks": {
          "price_in_answer": true,
          "cheapest_correct": false,
          "no_hallucination": true
        },
        "ground_truth_cheapest": "拼多多 ¥5750.0"
      }
    }
  ]
}
```

## 关键评估维度

P4 汇总报告从各阶段结果中提取多维指标：

| 维度 | 来源 | 含义 |
|------|------|------|
| 基础功能 | P0 | 工具层、DB、属性匹配是否正确 |
| 参数提取 | P1 | LLM 将用户自然语言转结构化参数的准确率 |
| 答案正确率 | P2 | 完整 Agent 循环的最终答案是否正确 |
| 幻觉率 | P2 | Agent 是否编造了不存在于数据库的价格 |
| 优雅降级 | P3 | 面对异常/歧义输入时是否优雅处理而非崩溃 |
| 自反思纠错 | P5 | 空结果时 Agent 是否能自行纠错重试 |
| System Prompt 遵循 | P5 | 是否遵循 Prompt 指令（标注来源、追问等） |

## Ground Truth 机制

`eval_helpers.py` 提供了绕过 LLM 直接从数据库获取标准答案的函数：

```python
from eval_helpers import compute_cheapest, compute_all_prices

# 直接从数据库计算最便宜平台
gt = compute_cheapest("iPhone 15", color="黑色", memory="256GB")
# → {"platform_name": "拼多多", "price": 5750.0, ...}

# 获取所有平台价格列表
all_prices = compute_all_prices("iPhone 15")
# → [{"platform_name": "京东", "total_price": 5999.0}, ...]

# 检测幻觉
from eval_helpers import detect_hallucination
is_clean, hallucinated_prices = detect_hallucination(answer_text, all_prices)
```

## E2E 运行器中 Agent 重建机制

P2/P3/P5 的 E2E 测试**每个 case 重新初始化 Agent**而非复用：
- 防止前一个 case 的状态（shopping_context、tool 缓存）泄漏到下一个
- 首次初始化会触发平台数据库重建（约 2s 延迟）
- `ReActAgent` 构造函数中的 `ShoppingContext()` 确保购物状态干净

## 评测触发时机

| 时机 | 范围 | 命令示例 |
|------|------|----------|
| 修改核心 Agent 逻辑后 | P0 + P1 + P2 + P5 | 验证 ReAct 行为无回归 |
| 修改工具 Schemas 后 | P0 + P1 | 验证属性提取仍正确 |
| 修改行业配置后 | IT3C --all | 验证过滤/分类/召回无退化 |
| PR / 版本发布前 | 全量 | 生成新基准报告 |
