# Eval 评估体系

## 概述

`eval/` 是项目质量保障的第二道防线。与 `tests/` 不同，eval 侧重于**端到端 + LLM 行为验证**，通过对比 Agent 输出与 Ground Truth 来量化质量指标。

### eval 与 tests 的分工

| 维度 | `tests/` | `eval/` |
|------|----------|---------|
| 测试对象 | 函数/模块（纯代码） | Agent 行为（含 LLM 调用） |
| 运行速度 | 毫秒级 | 秒到分钟级 |
| 外部依赖 | 大部分可 mock | 需要 LLM API Key |
| 验证方式 | assert 断言 | 阶段性评分 + 汇总报告 |
| 执行频率 | 每次修改后 | PR / 每日 / 发版前 |

## 统一入口

```bash
python3 eval/run.py --all           # 全量评估（Level 0 → 3）
python3 eval/run.py --level 0       # 仅无 LLM 的快速验证
python3 eval/run.py --level 1       # 含单次 LLM 调用
python3 eval/run.py --phase P2_e2e  # 仅运行指定阶段（增量）
python3 eval/run.py --skip P6_image # 跳过特定阶段
python3 eval/run.py --list          # 列出所有阶段
```

**特性：**
- **增量评估**：改了什么就跑对应阶段，不需要全量重跑
- **Session 分组**：一次 `--all` 或 `--level` 运行生成统一 session ID，所有阶段报告共享同一个时间戳前缀
- **独立运行**：每个 `eval_xxx.py` 仍可独立执行，不依赖主控
- **扩展友好**：新增阶段只需在 `PHASES` 注册表中加一条

## 阶段注册表

新增评估只需在 `run.py` 的 `PHASES` dict 中注册：

```python
PHASES = {
    "new_phase": {
        "script": "eval_new_phase.py",  # 需要写的脚本
        "level": 2,                     # 0/1/2/3，决定依赖层级
        "args": ["--flag"],             # 可选，额外的 CLI 参数
        "desc": "一句话描述",
    },
}
```

无需修改其他任何代码，主控会自动按 level 排序调用。

## 层级执行顺序

评估按 4 个层级依次执行，高 level 依赖低 level 的结果（语义上，非强制）：

| Level | 阶段 | 脚本 | LLM 调用 | 预计耗时 |
|-------|------|------|----------|----------|
| 0 | P0_unit | `eval_p0_unit.py` | 否 | 3s |
| 0 | IT3C_P0 | `eval_it3c.py` | 否 | 5s |
| 1 | P1_parse | `eval_p1_parse.py` | 单次 | 40s |
| 2 | P2_e2e | `eval_p2_e2e.py` | 多次 | 2min |
| 2 | P3_boundary | `eval_p3_boundary.py` | 多次 | 90s |
| 2 | P5_optimization | `eval_p5_optimization.py` | 多次 | 2min |
| 2 | P6_image | `eval_p6_image.py` | 可选 | 30s |
| 2 | IT3C_all | `eval_it3c.py --all` | 多次 | 50s |
| 3 | P4_benchmark | `eval_p4_benchmark.py` | 否 | 1s |

```
Level 0 (无 LLM, 安全快速)
  ├── P0_unit      ── 单元: DB CRUD / 属性匹配 / 并行查询 / Bug 回归
  └── IT3C_P0       ── 行业: 语义过滤 / 意图分类 / 处理器别名 / M2 回归

Level 1 (单次 LLM)
  └── P1_parse      ── 属性提取: 颜色 / 内存 / 别名

Level 2 (多次 LLM, 完整 ReAct)
  ├── P2_e2e        ── 端到端: ReAct + Plan-Execute
  ├── P3_boundary   ── 边界: 异常输入 / 歧义 / 矛盾 / 多轮
  ├── P5_optimization ─ 优化: 自反思 / Prompt / 依赖注入 / 复杂度
  ├── P6_image      ── 图片: 自动发现上传图片 + 识别 + 比价
  └── IT3C_all      ── IT3C 全量: P0 + 属性提取 + 推荐 E2E

Level 3 (后处理)
  └── P4_benchmark  ── 汇总: 聚合本 session 所有阶段
```

## Session 机制

每次 `run.py --all` 或 `run.py --level N` 生成一个 session ID（时间戳格式 `YYYYMMDD_HHmmss`），通过环境变量 `EVAL_SESSION_ID` 传给每个子进程。

同一 session 的所有结果文件共享前缀：

```
eval/results/
├── 20260514_133353_P0_unit.json
├── 20260514_133353_P1_parse.json
├── 20260514_133353_P2_e2e.json
├── 20260514_133353_P3_boundary.json
├── 20260514_133353_P5_optimization.json
├── 20260514_133353_P6_image.json
├── 20260514_133353_IT3C.json
└── 20260514_133353_P4_benchmark.json     ← 聚合报告
```

- P4 只读取同 session 的报告，不会混入其他运行的结果
- 每次独立运行生成新 session，互不干扰
- 手动指定 session: `--session 20260514_133353`

## 增量评估场景

| 场景 | 命令 | 耗时 |
|------|------|------|
| 改了 DB 层 | `--phase P0_unit` | 3s |
| 改了属性提取 | `--level 1` | 45s |
| 改了 ReAct 循环 | `--phase P2_e2e,P3_boundary` | 3min |
| 改了 Prompt | `--phase P5_optimization` | 2min |
| 前端上传了图片 | `--phase P6_image` | 30s |
| 改了行业配置 | `--phase IT3C_all` | 50s |
| 发版前全量检查 | `--all` | 7min |

## Ground Truth 机制

`eval_helpers.py` 提供绕过 LLM 直接从数据库获取标准答案：

```python
from eval_helpers import compute_cheapest, compute_all_prices, detect_hallucination

gt = compute_cheapest("iPhone 15", color="黑色", memory="256GB")
# → {"platform_name": "拼多多", "price": 5750.0}

prices = compute_all_prices("iPhone 15")
# → [{"platform_name": "京东", "total_price": 5999.0}, ...]

is_clean, hallucinations = detect_hallucination(answer_text, prices)
```

## 关键评估维度

P4 汇总从各阶段提取多维指标：

| 维度 | 来源 | 含义 |
|------|------|------|
| 基础功能 | P0 | DB / 工具层正确性 |
| 参数提取 | P1 | LLM 结构化解析准确率 |
| 答案正确率 | P2 | 完整 Agent 循环结果 |
| 幻觉率 | P2 | 编造不存在价格的比例 |
| 优雅降级 | P3 | 异常输入时是否崩溃 |
| 自反思纠错 | P5 | 空结果时自行纠错能力 |
| System Prompt 遵循 | P5 | 标注来源/追问等规则遵循度 |

## 新增评估指南

1. 写新脚本 `eval/eval_p7_xxx.py`（独立可运行，内部用 `EvalRecorder`）
2. 在 `run.py` 的 `PHASES` 中注册（指定 script / level / desc）
3. 运行 `python3 eval/run.py --phase P7_xxx` 验证
4. 更新本文档的层级表

不需要改任何其他文件。
