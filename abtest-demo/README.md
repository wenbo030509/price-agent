# AB Test Agent — 实验效果评估 Demo

基于 [price-agent](../) 的 ReAct Agent 框架，演示 LLM Agent 如何对 AB 实验数据执行统计检验、护栏检测、细分一致性和策略决策。

## 场景

**推荐算法升级 AB 实验**：协同过滤 → LLM Embedding，验证新算法能否在护栏安全的前提下提升购买转化率。

核心数据张力：主指标 CVR 显著 +13.7%，但护栏指标延迟翻倍 +115%（145ms → 312ms），Agent 需要给出"条件上线"而非简单二选一。

## 功能

- **实验切换**：3 个实验（1 个完整数据 + 2 个摘要），前端自动适配看板
- **数据看板**：实验背景 → 7 指标对比表 → CVR/延迟趋势图 → 细分维度分析
- **8 个工具**：实验列表、详情、Welch's t-test、Bonferroni 校正、Simpson 检测、策略决策、分日趋势
- **LLM-as-Judge**：Agent 逐步调用工具，前端实时展示推理链 + 表格动态填充统计结果
- **6 条已验证 Query**：每条实验均有预置 query，已验证可正常运行

## 工具清单

| 工具 | 统计能力 |
|------|---------|
| `get_experiment_list` | 列出 3 个可用实验 |
| `get_experiment_overview` | 实验元信息 + 样本量功效分析 |
| `get_experiment_detail` | 7 指标 × 2 组原始数据（均值、标准差、样本量） |
| `run_statistical_test` | Welch's t-test → p 值、95% CI、Cohen's d、效应量 |
| `run_multi_metric_check` | Bonferroni 多重比较校正（α/n） |
| `check_segment_consistency` | Simpson 悖论检测（设备类型 + 用户活跃度下钻） |
| `make_strategy_decision` | 上线 / 条件上线 / 下线 / 延长实验 |
| `get_daily_trend` | 14 天分日趋势（CVR + 延迟） |

## 快速开始

```bash
cd abtest-demo
python app.py
# → http://localhost:5002
```

依赖 price-agent 父项目的 `agent/` 模块和 `.env` 文件（自动加载）。

## 项目结构

```
abtest-demo/
├── app.py                     # Flask 应用（端口 5002）
├── tools/                     # 工具包（与 price-agent 同模式）
│   ├── __init__.py            # 导入全部工具 → 导出 TOOL_SCHEMAS + TOOL_MAP
│   ├── registry.py            # ToolRegistry + @register_tool 装饰器
│   ├── data.py                # Mock 数据集（3 实验 × 7 指标 × 细分 × 趋势）
│   ├── experiment_list.py     # get_experiment_list
│   ├── experiment_overview.py # get_experiment_overview
│   ├── experiment_detail.py   # get_experiment_detail
│   ├── statistical_test.py    # run_statistical_test（Welch's t-test）
│   ├── multi_metric_check.py  # run_multi_metric_check（Bonferroni 校正）
│   ├── segment_consistency.py # check_segment_consistency（Simpson 悖论）
│   ├── strategy_decision.py   # make_strategy_decision
│   └── daily_trend.py         # get_daily_trend
├── templates/
│   └── index.html             # 数据看板 + Agent 交互界面
├── static/
│   └── app.js                 # 看板渲染、Canvas 图表、SSE 流式、实验切换
└── README.md
```

## 与 price-agent 的关系

- 复用父项目 `agent/react_engine.py` + `agent/trace.py`（通过 `sys.path` 导入）
- `tools/` 包使用相同的 `@register_tool` 装饰器模式，与 `price-agent/tools/registry.py` 对齐
- 每个工具独立一个 `.py` 文件，新增工具只需加文件 + `__init__.py` 中 import
- 独立端口 5002、独立 Flask app、不修改 price-agent 任何代码

## 技术栈

- **Agent 框架**：ReActAgent（Think → Act → Observe 循环）
- **LLM**：DeepSeek V4 Flash（通过 `.env` 中 `DEEPSEEK_API_KEY`）
- **统计**：scipy Welch's t-test + numpy
- **前端**：原生 JS + Canvas 图表 + SSE 流式渲染
- **CSS**：与 price-agent 统一的 `#FF4D1C` 品牌色系
