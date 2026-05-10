# ReAct + Tool Calling 商品对比智能助手

基于ReAct（推理+行动）策略的LLM智能Agent，支持自动调用数据库查询工具，完成商品数据查询、价格对比、多维度分析等任务。

## 功能特性

### 核心功能
- ✅ **ReAct推理闭环**：Thought → Action → Observation → Final Answer
- ✅ **工具调用集成**：支持查询商品、对比价格、查询品类
- ✅ **可视化界面**：Web界面展示聊天和推理过程
- ✅ **会话历史**：所有对话历史持久化存储
- ✅ **商品管理**：支持添加、编辑、删除商品数据
- ✅ **多平台比价**：支持京东、淘宝、拼多多、苏宁4个平台并行比价
- ✅ **多轮对话上下文**：滑动窗口管理历史消息，支持上下文指代（"那小米14呢"）

### 数据库存储
- 🗄️ **SQLite文件存储**：每个平台独立数据库 `platform_{jd/taobao/pdd/suning}.db`
- 📦 **商品数据**：存储商品名称、参考价、平台价、库存、品类、颜色、内存、运费、库存状态
- 💬 **会话记录**：保存所有历史会话和消息

### UI交互优化
- 🎨 **侧边栏折叠**：支持左侧边栏完全折叠/展开
- 🔍 **商品搜索**：商品列表支持模糊搜索（名称、品类、颜色、内存）
- 📝 **全字段编辑**：商品编辑支持模态框编辑所有字段
- 📦 **折叠表单**：添加商品表单默认折叠，节省空间

## 项目结构

```
price-agent/
├── app.py                          # Flask Web应用（后端）
├── main.py                         # 命令行版本
├── db_manager.py                   # 数据库管理工具
├── test_multi_platform.py          # 多平台比价测试
├── test_query_fix.py               # 查询修复验证测试
├── test_color_memory.py            # 颜色和内存字段测试
├── config/
│   └── settings.py                 # 配置管理
├── database/
│   ├── connection.py               # 数据库连接（线程安全）
│   └── models.py                   # 数据模型和操作
├── agent/
│   ├── prompts.py                  # 系统提示词
│   └── react_engine.py             # ReAct推理引擎
├── platforms/
│   ├── __init__.py                 # 平台模块导出
│   ├── platform_config.py          # 平台配置
│   ├── platform_database.py        # 单平台数据库管理
│   └── parallel_agent.py           # 并行查询Agent
├── tools/
│   ├── __init__.py                 # 工具模块导出
│   ├── registry.py                 # 工具注册器
│   └── multi_platform_tools.py     # 多平台比价工具（3个核心工具）
├── templates/
│   └── index.html                  # 前端页面
├── static/
│   ├── css/style.css               # 样式文件
│   └── js/app.js                   # 前端逻辑
├── tests/
│   ├── eval_helpers.py             # 评估工具（ground truth 计算、打分、报告）
│   ├── eval_p0_unit.py             # P0 单元测试（无 LLM）
│   ├── eval_p1_parse.py            # P1 属性解析测试
│   ├── eval_p2_e2e.py              # P2 端到端测试（ReAct 完整循环）
│   ├── eval_p3_boundary.py         # P3 能力边界测试
│   ├── eval_p4_benchmark.py        # P4 回归基准汇总
│   └── eval_results/               # 评估结果输出
├── platform_jd.db                  # 京东平台数据库
├── platform_taobao.db              # 淘宝平台数据库
├── platform_pdd.db                 # 拼多多平台数据库
├── platform_suning.db              # 苏宁平台数据库
├── requirements.txt
├── .env
├── README.md
├── 评估文档.md                      # 评估方案与实测结果
├── 优化文档.md                      # 优化记录和待办项
└── MULTI_PLATFORM_README.md        # 多平台比价详细文档
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置API

编辑 `.env` 文件：

```
# 火山引擎 Ark API 配置
ARK_API_KEY=your_api_key_here
ARK_MODEL=doubao-seed-1-8-251228
```

### 3. 启动应用

#### 方式一：启动Web界面（包含前后端，推荐）

**后端和前端是一体化的，只需一个启动命令：**

```bash
python3 app.py
```

启动成功后，在浏览器中访问：
```
http://127.0.0.1:5001
```

**说明：**
- 后端：Flask应用运行在 5001 端口
- 前端：HTML/CSS/JS通过Flask提供，无需单独启动
- 数据库：首次运行自动创建并初始化

#### 方式二：命令行版本

```bash
python3 main.py
```

#### 方式三：测试多平台比价功能

```bash
python3 test_multi_platform.py
```

#### 方式四：数据库管理工具

```bash
python3 db_manager.py
```

## 数据库说明

### 数据库文件

每个平台使用独立的SQLite数据库文件：`platform_{jd/taobao/pdd/suning}.db`，首次运行时会自动创建并初始化。

### 数据表结构

#### products（商品表）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 主键，自增 |
| product_name | TEXT | 商品名称 |
| price | REAL | 参考价 |
| platform_price | REAL | 平台价（可选） |
| stock | INTEGER | 库存 |
| category | TEXT | 品类 |
| color | TEXT | 颜色（可选） |
| memory | TEXT | 内存/容量（可选） |
| shipping_fee | REAL | 运费 |
| is_in_stock | BOOLEAN | 是否有货 |

#### sessions（会话表）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 主键，自增 |
| session_id | TEXT | 会话ID |
| created_at | TIMESTAMP | 创建时间 |

#### messages（消息表）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 主键，自增 |
| session_id | TEXT | 会话ID（外键） |
| role | TEXT | 角色（user/assistant） |
| content | TEXT | 消息内容 |
| timestamp | TIMESTAMP | 时间戳 |

### 初始化数据

首次运行时，会自动为每个平台创建示例商品，包含手机和平板品类，带有颜色和内存信息。

## 使用示例

### Agent能力测试示例

#### 第一类：单工具基础查询（测试基础能力）

1. **单个商品详情查询**
   ```
   查询iPhone 15的完整信息
   ```
   - 测试工具：`multi_platform_price_comparison`
   - 评估点：能否准确调用多平台比价工具并展示各平台价格

2. **指定平台商品查询**
   ```
   在京东平台查询iPhone 15的价格
   ```
   - 测试工具：`query_single_platform_product`
   - 评估点：能否指定平台查询

3. **获取全平台商品列表**
   ```
   查看所有平台都有哪些商品
   ```
   - 测试工具：`get_all_platform_products`
   - 评估点：能否并行获取所有平台数据

#### 第二类：多平台比价（测试并行查询能力）

4. **单商品全平台比价**
   ```
   iPhone 15在哪个平台最便宜？
   ```
   - 测试工具：`multi_platform_price_comparison`
   - 评估点：能否并行查询4个平台并汇总分析

5. **多商品全平台比价**
   ```
   对比iPhone 15和小米14在京东、淘宝、拼多多、苏宁这四个平台的价格
   ```
   - 测试工具：`multi_platform_price_comparison`（多次调用）
   - 评估点：能否理解复杂需求并规划多步查询

6. **平板类商品平台比价**
   ```
   iPad Pro在各个平台的价格对比
   ```
   - 测试工具：`multi_platform_price_comparison`
   - 评估点：能否处理不同品类商品的比价

7. **指定平台+多商品查询**
   ```
   在淘宝平台查询iPhone 15和小米14的价格对比
   ```
   - 测试工具：`query_single_platform_product`（多次调用）
   - 评估点：能否在指定平台进行多商品查询

#### 第三类：复合推理查询（测试推理和组合能力）

8. **全平台比价+最低价分析**
   ```
   查询小米14在所有平台的价格，找出最低价平台
   ```
   - 测试工具：`multi_platform_price_comparison`
   - 评估点：能否从比价结果中找出最低价

9. **全平台比价+库存分析**
   ```
   查询华为Mate60在哪个平台有货且价格最低
   ```
   - 测试工具：`multi_platform_price_comparison`
   - 评估点：能否综合考虑价格和库存

10. **全平台商品浏览**
    ```
    查看所有平台一共有哪些商品在卖
    ```
    - 测试工具：`get_all_platform_products`
    - 评估点：能否汇总展示所有平台商品

#### 第四类：边界和异常测试（测试鲁棒性）

11. **不存在的商品查询**
    ```
    查询iPhone 20的价格
    ```
    - 评估点：能否优雅处理商品不存在的情况

12. **模糊商品名称查询**
    ```
    查询"苹果手机"的价格
    ```
    - 评估点：能否通过模糊匹配找到相关商品

13. **复杂自然语言理解**
    ```
    我想买一部性价比高的手机，预算5000左右，你能帮我推荐一下吗？
    ```
    - 评估点：能否理解开放式需求并规划查询

#### 第五类：上下文连贯测试（测试多轮对话）✅ 已实现

> 滑动窗口上下文管理：保留最近 6 轮对话（≤6000 字符），自动过滤 ReAct 中间产物。

14. **多轮对话-第1轮**
    ```
    查询iPhone 15在各个平台的价格
    ```
15. **多轮对话-第2轮（引用上文）**
    ```
    那小米14呢？
    ```
16. **多轮对话-第3轮（决策）**
    ```
    这两个哪个更值得买？
    ```
    - 评估点：能否保持上下文连贯性
    - 实测结果：Agent 正解理解"那"=最便宜平台，"这两个"=iPhone 15+小米14

### Web界面功能

- **左侧边栏**：会话历史管理
  - 创建新会话
  - 切换历史会话
  - 删除会话
  - 侧边栏折叠/展开

- **中间区域**：聊天对话
  - 输入问题
  - 查看AI回复
  - 显示完整推理过程

- **右侧面板**：
  - **商品管理**：
    - 支持4个平台商品切换（京东/淘宝/拼多多/苏宁）
    - 商品搜索（模糊搜索名称、品类、颜色、内存）
    - 全字段编辑（模态框编辑）
    - 添加商品（表单默认折叠）
    - 删除商品
  - **多平台比价**：输入商品名称一键比价4个平台，快速查询标签
  - **推理过程**：查看ReAct详细推理步骤

## 工具说明

### 内置工具

本系统提供3个核心工具，均通过 `@register_tool` 装饰器注册：

1. **multi_platform_price_comparison** - 多平台并行比价
   - 功能：在京东、淘宝、拼多多、苏宁4个平台并行查询商品价格，支持颜色、内存属性精确匹配
   - 参数：`product_name` (商品名称，可包含颜色/内存，工具自动解析)、`color` (可选)、`memory` (可选)
   - 返回：各平台价格对比结果，包含最低价、最高价、平均价、运费

2. **get_all_platform_products** - 获取所有平台所有商品
   - 功能：并行查询所有平台的商品列表
   - 参数：无
   - 返回：各平台商品汇总

3. **query_single_platform_product** - 查询指定平台商品
   - 功能：查询单个平台指定商品的信息，支持颜色、内存属性精确筛选
   - 参数：`platform_id` (平台ID: jd/taobao/pdd/suning)、`product_name` (商品名称)、`color` (可选)、`memory` (可选)
   - 返回：指定平台的商品信息

### 添加新工具

在 `tools/multi_platform_tools.py` 中添加新函数，使用 `@register_tool` 装饰器注册即可。

## 技术栈

- **Python 3.10+**
- **OpenAI API (兼容)** - LLM推理
- **Flask** - Web框架
- **SQLite** - 数据存储
- **Bootstrap 5** - 前端界面

## 配置说明

可在 `config/settings.py` 中修改配置：
- API配置
- 模型名称
- 最大推理轮数
- 数据库路径
- 上下文窗口大小（`MAX_HISTORY_ROUNDS` / `MAX_HISTORY_CHARS`）

## 评估测试

项目内置 4 阶段评估体系，详见 `评估文档.md`：

```bash
# 逐阶段执行
python3 tests/eval_p0_unit.py       # P0 单元测试（无 LLM）
python3 tests/eval_p1_parse.py      # P1 参数提取测试
python3 tests/eval_p2_e2e.py        # P2 端到端测试
python3 tests/eval_p3_boundary.py   # P3 能力边界测试
python3 tests/eval_p4_benchmark.py  # P4 汇总所有阶段
```

**最新实测结果（2026-05-11）：综合通过率 96.3% (52/54)**

| 阶段 | 通过率 | 说明 |
|------|--------|------|
| P0 单元测试 | 100% (18/18) | 数据库 CRUD、打分、并行查询、回归 |
| P1 参数提取 | 100% (17/17) | 属性提取 + 品牌别名改写 |
| P2 端到端 | 85.7% (12/14) | ReAct 完整循环，2 个失败为 API 限流 |
| P3 能力边界 | 80% (12/15) | 8/8 评分通过，3 个 known_missing（已修复） |

## 许可证

MIT License
