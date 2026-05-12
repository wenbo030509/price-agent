# price-agent IT3C行业 优化文档

> 使用说明：每个提示词为一个独立的对话任务 
> 执行顺序严格按阶段编号，后续阶段依赖前置阶段的代码。

---

## Phase 1 · 数据基础层

> **目标：** 扩展 Schema，补全 IT3C 手机品类核心字段，修复主 DB 与平台 DB 的 Schema 分裂问题。

---

### Prompt 1-A：platform_database.py Schema 扩展 + IT3C Mock 数据

```
你是一个 Python 后端工程师，正在优化 price-agent 项目（GitHub: wenbo030509/price-agent）。

## 任务
修改 `platforms/platform_database.py`，完成以下两件事：

### 1. 扩展建表 SQL
在现有字段（product_name/price/stock/category/platform_price/shipping_fee/is_in_stock/color/memory）基础上，
新增以下 IT3C 专属字段：

| 字段名            | 类型    | 说明                                          |
|------------------|---------|---------------------------------------------|
| brand            | TEXT    | 品牌，如 "Apple"、"小米"、"华为"              |
| processor        | TEXT    | 处理器型号，如 "A16 Bionic"、"骁龙8Gen3"      |
| processor_brand  | TEXT    | 处理器厂商归一化：sd / mt / apple / kirin     |
| performance_tier | TEXT    | 性能层级：flagship / mid / budget             |
| screen_size      | REAL    | 屏幕尺寸（寸），如 6.1                        |
| battery          | INTEGER | 电池容量（mAh），如 3279                      |
| use_case_tags    | TEXT    | JSON 数组字符串，如 '["gaming","photography"]' |
| description      | TEXT    | 用于前端展示的简短介绍                        |

建表语句示例（在原 CREATE TABLE 里追加这 8 个字段，注意向后兼容：用 ALTER TABLE 还是重建表都可以，但要确保 init_platform_db 幂等）。

### 2. 重写 _PLATFORM_MOCK_DATA
用下面的完整数据替换原有 Mock 数据，保持 4 个平台（jd/taobao/pdd/suning）。
每条记录的字段顺序与建表顺序一致：
(product_name, price, stock, category, platform_price, shipping_fee, is_in_stock,
 color, memory, brand, processor, processor_brand, performance_tier,
 screen_size, battery, use_case_tags, description)

#### 京东（jd）数据参考：
- iPhone 15 黑色 128GB，¥5999，品牌Apple，处理器A16 Bionic，processor_brand=apple，
  tier=flagship，屏6.1，电池3279，tags=["photography","gaming","flagship"]，
  描述="A16芯片，双摄系统，全天续航"
- iPhone 15 白色 128GB，同上价格和规格，颜色白色
- iPhone 15 黑色 256GB，¥6999，其余同上
- iPhone 15 白色 256GB，¥6999
- iPhone 15 Pro 黑色 256GB，¥8999，处理器A17 Pro，tags=["gaming","photography","flagship","business"]，
  描述="A17 Pro芯片，钛金属机身，专业摄像"
- 小米14 黑色 256GB，¥3999，品牌小米，处理器骁龙8Gen3，processor_brand=sd，
  tier=flagship，屏6.36，电池4610，tags=["gaming","photography","flagship"]，
  描述="骁龙8Gen3，徕卡影像，大电池"
- 小米14 白色 256GB，¥4099
- 小米14 Pro 黑色 512GB，¥5299，tags=["gaming","photography","flagship","business"]
- 红米Note13 蓝色 128GB，¥1299，处理器天玑6080，processor_brand=mt，
  tier=budget，tags=["budget","student"]，描述="入门首选，大屏长续航"
- 小米平板6 黑色 128GB，¥2199，category=平板，tags=["student","business"]
- AirPods Pro 2，¥1799，category=耳机，tags=["flagship","business"]
- iPad Pro 11寸 256GB，¥7999，category=平板，处理器M2，processor_brand=apple，tags=["business","flagship"]

（taobao/pdd/suning 请参照以上品类和规格自行设计，价格与现有数据保持相对关系：pdd最低，suning最高，京东/淘宝居中。
每个平台各保留 10-14 条，品类覆盖手机/平板/耳机，各平台颜色款式可有差异。）

> ⚠️ **【Fix-4 · 轻度】非手机品类（平板、耳机）的 processor/processor_brand/performance_tier 字段也需要填充。**
> - iPad Pro：processor="M2"，processor_brand="apple"，performance_tier="flagship"
> - 小米平板6：processor="骁龙870"，processor_brand="sd"，performance_tier="mid"
> - AirPods Pro 2：processor=""，processor_brand=""，performance_tier="flagship"（耳机按品牌定位）
> - 屏幕尺寸/电池字段：平板填实际值，耳机填 NULL
> - use_case_tags：全部商品都需要填，至少含品类相关标签（如耳机填 ["flagship","business"]）

### 3. 同步修改 executemany
确保 init_platform_db() 里的 INSERT 语句字段列表与新 Schema 一致。

### 4. 不要修改其他方法
query_product_by_attrs、_fuzzy_match、query_all_products 等方法暂时不改，下一步单独优化。

> ⚠️ **【Fix-1 · 严重】实际实施时必须同步修改以下方法，因为所有方法使用了硬编码列索引 row[0]~row[9]。**
> Schema 从 9 列扩展到 17 列后，SELECT * 返回的列顺序变了，硬编码索引全部失效：
> - `query_product_by_attrs` 的 `row_to_dict()`（索引映射必须从 17 列取）
> - `query_products_by_attrs` 的 `row_to_dict()`（同上）
> - `_fuzzy_match_all`（索引映射 + SELECT 语句）
> - `_fuzzy_match`（同上）
> - `query_all_products`（同上）
> - `add_product`（INSERT 字段列表 + VALUES 占位符）
> - `update_product`（UPDATE SET 字段列表）
>
> **实施策略**：采用 DROP TABLE + CREATE TABLE 方式重建表（因为这是 mock 数据，无需保留）。
> `init_platform_db` 的幂等检查改为：先 DROP TABLE IF EXISTS products，再 CREATE TABLE。
> 所有 `row_to_dict`、SELECT、INSERT、UPDATE 语句统一更新为 17 列。
> 列顺序固定为：(0=id, 1=product_name, 2=price, 3=stock, 4=category, 5=platform_price, 6=shipping_fee, 7=is_in_stock, 8=color, 9=memory, 10=brand, 11=processor, 12=processor_brand, 13=performance_tier, 14=screen_size, 15=battery, 16=use_case_tags, 17=description)

## 输出
输出完整的 `platforms/platform_database.py` 文件，不要省略任何部分。
```

---

### Prompt 1-B：修复 database/models.py Schema 分裂

```
你是一个 Python 后端工程师，正在优化 price-agent 项目。

## 背景
项目有两套商品数据存储：
1. `platforms/platform_database.py` — 各平台商品 DB（已扩展为 17 个字段）
2. `database/models.py` — 主 DB，products 表只有 5 个字段（id/product_name/price/stock/category）

这导致前端 /api/products 接口返回的数据缺少 color/memory 等字段，展示不完整。

## 任务
修改 `database/models.py`，做以下调整：

### 方案（选择其中之一实现）
**推荐方案 B：主 DB 不再存商品，只做会话管理**
- 删除 `init_mock_db()` 里的 products 表创建和商品数据插入
- 保留 sessions 表和 messages 表不变
- 保留 `add_message`、`get_session_messages`、`create_session`、`get_all_sessions`、`delete_session` 函数不变
- 删除 `add_product` 和 `get_all_products` 函数（商品数据改为走 platforms 模块）
- 在文件顶部加注释说明：商品数据统一由 platforms.PlatformDatabase 管理

### 同步修改 app.py
找到 `/api/products` 路由，把原来调用 `get_all_products(db)` 改为：
```python
from platforms import PlatformParallelAgent
agent = get_parallel_agent()
result = agent.query_all_products_parallel()
# 聚合所有平台商品，去重（同名商品只保留最低价那条）
```

## 输出
1. 完整的 `database/models.py`
2. app.py 里 `/api/products` 路由的替换代码片段（只输出该函数，不用输出整个 app.py）
```

---

## Phase 2 · 属性解析层

> **目标：** 扩展处理器别名映射，让 query 解析覆盖 IT3C 核心属性（处理器、预算、使用场景）。

---

### Prompt 2-A：处理器别名映射 + query_product_by_attrs 评分扩展

```
你是一个 Python 后端工程师，正在优化 price-agent 项目的 `platforms/platform_database.py`。

## 背景
项目已有 COLOR_ALIASES 和 MEMORY_ALIASES 两个别名字典，
用于在 query_product_by_attrs() 里做模糊属性匹配和评分。
现在 Schema 新增了 processor / processor_brand 字段，需要同步扩展匹配逻辑。

## 任务一：新增 PROCESSOR_ALIASES 字典

在 MEMORY_ALIASES 下方新增：

```python
# 处理器厂商归一化别名（key 为 processor_brand 字段的值）
PROCESSOR_BRAND_ALIASES: Dict[str, List[str]] = {
    "sd":    ["骁龙", "snapdragon", "高通", "qualcomm", "soc"],
    "mt":    ["天玑", "dimensity", "联发科", "mediatek"],
    "apple": ["a17", "a16", "a15", "a14", "m2", "m3", "苹果芯片", "apple silicon", "bionic"],
    "kirin": ["麒麟", "kirin", "海思", "hisilicon"],
    "exynos":["猎户座", "exynos"],
}

# 常见处理器型号关键词（用于 processor 字段的 LIKE 匹配）
PROCESSOR_MODEL_KEYWORDS: Dict[str, List[str]] = {
    "8gen3":  ["8gen3", "8 gen 3", "第三代骁龙8"],
    "8gen2":  ["8gen2", "8 gen 2", "第二代骁龙8"],
    "9300":   ["9300", "天玑9300"],
    "9200":   ["9200", "天玑9200"],
    "a17":    ["a17", "a17 pro", "a17 bionic"],
    "a16":    ["a16", "a16 bionic"],
}
```

新增辅助函数：
```python
def _processor_brand_tokens(processor_hint: str) -> List[str]:
    """把用户输入的处理器 hint 映射到 processor_brand key"""
    ...  # 参照 _color_tokens 实现，遍历 PROCESSOR_BRAND_ALIASES

def _processor_model_tokens(processor_hint: str) -> Optional[str]:
    """提取处理器型号关键词，用于 LIKE 匹配"""
    ...  # 遍历 PROCESSOR_MODEL_KEYWORDS，返回匹配的 key 或 None
```

## 任务二：扩展 query_product_by_attrs 方法

在现有 color / memory 两个可选参数基础上，新增：
- `processor_brand: Optional[str] = None`  — 处理器厂商（sd/mt/apple/kirin）
- `processor_hint: Optional[str] = None`   — 处理器关键词（如"骁龙8Gen3"）
- `use_case: Optional[str] = None`         — 使用场景标签（gaming/photography/battery 等）
- `performance_tier: Optional[str] = None` — 性能层级（flagship/mid/budget）
- `budget_max: Optional[float] = None`     — 最高预算
- `budget_min: Optional[float] = None`     — 最低预算

**评分函数 score() 扩展：**
- 颜色匹配    → +1
- 内存匹配    → +1  
- 处理器品牌匹配 → +1（processor_brand 字段与 _processor_brand_tokens 交集）
- 处理器型号匹配 → +1（processor 字段 LIKE）
- 使用场景匹配 → +1（use_case_tags JSON 字符串 LIKE %gaming%）
- 性能层级匹配 → +1（performance_tier 精确匹配）
- 最高分 = 6

**预算过滤（非评分，是硬过滤）：**
在取候选列表的 base_sql 里加：
```sql
AND (? IS NULL OR price <= ?)   -- budget_max
AND (? IS NULL OR price >= ?)   -- budget_min
```

**同分时排序策略：**
score 相同 → 先比 performance_tier（flagship > mid > budget）→ 再比价格（低优先）

## 任务三：向后兼容
原有 query_product() 方法签名不变，内部仍委托给 query_product_by_attrs()。
parallel_agent.py 里调用 query_product_by_attrs() 的地方，新增参数透传即可（参数默认值都是 None，不传不影响原逻辑）。

## 输出
只输出修改后的 `platforms/platform_database.py` 里涉及变化的部分：
1. 两个新增别名字典 + 两个辅助函数（完整代码）
2. query_product_by_attrs 方法的完整新版本（含新参数和新评分逻辑）
3. 不需要输出未修改的部分
```

---

### Prompt 2-B：_parse_attrs_from_query 扩展（processor + budget + use_case）

```
你是一个 Python 后端工程师，正在优化 price-agent 项目的 `tools/multi_platform_tools.py`。

## 背景
现有 _parse_attrs_from_query() 函数调用 LLM 从用户输入中提取结构化属性，
目前只提取：product_name / color / memory / category 四个字段。

需要扩展为提取 IT3C 全量属性，支持"骁龙8Gen3手机"、"5000以内游戏手机"这类查询。

## 任务：重写 _parse_attrs_from_query 的 prompt

将函数内的 prompt 字符串替换为以下内容（保持函数其余逻辑不变）：

```python
prompt = f"""你是一个商品属性提取助手，专注于 IT3C 数字产品（手机、平板、耳机、电脑等）。
从用户输入中提取商品属性，只输出 JSON，不要任何其他文字、解释或 markdown 代码块。

用户输入：{raw_query}

输出格式（所有字段必须存在，未提及的填 null，字符串类型未提及填 ""）：
{{
  "product_name": "商品核心名称（去掉颜色/内存/处理器等修饰词后的型号名）",
  "brand": "品牌名（Apple/小米/华为/OPPO/vivo/三星/荣耀，未知填\"\"）",
  "color": "颜色（黑色/白色/蓝色等，未提及填\"\"）",
  "memory": "内存或容量（128GB/256GB/512GB/1TB等，未提及填\"\"）",
  "category": "品类（手机/平板/耳机/电脑，不确定填\"\"）",
  "processor_hint": "用户提到的处理器关键词（如\"骁龙8Gen3\"\"天玑9300\"\"A17\"，未提及填\"\"）",
  "processor_brand": "处理器厂商归一化：sd(骁龙/高通) mt(天玑/联发科) apple(A系列/M系列) kirin(麒麟)，未提及填\"\"",
  "performance_tier": "性能层级：flagship(旗舰/高端) mid(中端) budget(入门/便宜)，未提及填\"\"",
  "use_case": "使用场景标签，只能从以下选：gaming photography battery business student budget flagship，未提及填\"\"，多个用逗号分隔",
  "budget_max": "最高预算数字（元），未提及填 null。识别：\"5000以内\"→5000，\"不超过4000\"→4000，\"三四千\"→4000",
  "budget_min": "最低预算数字（元），未提及填 null。识别：\"5000以上\"→5000，\"旗舰级\"→4999"
}}

## 品牌/别名标准化规则（必须执行）：
- "水果手机"/"苹果手机"/"ip" 开头 → brand="Apple"，product_name 对应型号
- "ip15"/"ip16" → product_name="iPhone 15"/"iPhone 16"
- "米14"/"mi14" → product_name="小米14"，brand="小米"
- "华为mate" → brand="华为"
- "三星s系列" → brand="三星"

## 示例：
输入："我打游戏，5000以内推荐什么手机，骁龙处理器的"
输出：{{"product_name":"","brand":"","color":"","memory":"","category":"手机","processor_hint":"骁龙","processor_brand":"sd","performance_tier":"","use_case":"gaming","budget_max":5000,"budget_min":null}}

输入："iPhone 15 黑色256GB哪里最便宜"
输出：{{"product_name":"iPhone 15","brand":"Apple","color":"黑色","memory":"256GB","category":"手机","processor_hint":"","processor_brand":"apple","performance_tier":"flagship","use_case":"","budget_max":null,"budget_min":null}}

输入："天玑9300的手机"
输出：{{"product_name":"","brand":"","color":"","memory":"","category":"手机","processor_hint":"天玑9300","processor_brand":"mt","performance_tier":"","use_case":"","budget_max":null,"budget_min":null}}
"""
```

## 同时修改函数返回值
把 return 语句改为返回所有新字段：
```python
return {
    "product_name":     attrs.get("product_name", raw_query) or raw_query,
    "brand":            attrs.get("brand", "") or "",
    "color":            attrs.get("color", "") or "",
    "memory":           attrs.get("memory", "") or "",
    "category":         attrs.get("category", "") or "",
    "processor_hint":   attrs.get("processor_hint", "") or "",
    "processor_brand":  attrs.get("processor_brand", "") or "",
    "performance_tier": attrs.get("performance_tier", "") or "",
    "use_case":         attrs.get("use_case", "") or "",
    "budget_max":       attrs.get("budget_max"),      # 可以是 None
    "budget_min":       attrs.get("budget_min"),      # 可以是 None
}
```

## 同时修改调用方 multi_platform_price_comparison
把 attrs 的新字段透传给 agent.compare_product_price()：
```python
comparison = agent.compare_product_price(
    product_name,
    color=color or None,
    memory=memory or None,
    processor_brand=attrs.get("processor_brand") or None,
    processor_hint=attrs.get("processor_hint") or None,
    use_case=attrs.get("use_case") or None,
    budget_max=attrs.get("budget_max"),
    budget_min=attrs.get("budget_min"),
)
```

## 输出
输出 `tools/multi_platform_tools.py` 里修改的部分（_parse_attrs_from_query 完整函数 + multi_platform_price_comparison 里的调用修改）。
```

---

## Phase 3 · 工具层

> **目标：** 新增 `semantic_product_search` 工具，让 Agent 具备"推荐型"查询能力。

---

### Prompt 3-A：新建 tools/semantic_search_tool.py

```
你是一个 Python 后端工程师，正在为 price-agent 项目新增一个语义推荐工具。

## 背景
现有工具只能做"精确比价"（multi_platform_price_comparison）和"单平台查询"。
用户的"我打游戏推荐什么手机"、"5000以内性价比最高的手机"这类推荐型需求无法被满足。

## 任务：新建 tools/semantic_search_tool.py

实现一个 semantic_product_search 工具，注册到 tool_registry。

### 工具签名

```python
@register_tool(
    name="semantic_product_search",
    schema={...}   # 见下方 JSON Schema
)
def semantic_product_search(
    use_case: str = "",           # 使用场景：gaming/photography/battery/business/student/budget/flagship
    brand: str = "",              # 品牌偏好：Apple/小米/华为 等，为空则不限
    processor_brand: str = "",    # 处理器厂商：sd/mt/apple/kirin，为空则不限
    performance_tier: str = "",   # 性能层级：flagship/mid/budget，为空则不限
    budget_max: float = None,     # 最高预算（元）
    budget_min: float = None,     # 最低预算（元）
    category: str = "手机",       # 品类，默认手机
    sort_by: str = "value",       # 排序方式：value=性价比 / price=最低价 / performance=性能优先
    top_n: int = 5,               # 返回前 N 条推荐
) -> Dict:
```

### JSON Schema（放在 @register_tool 的 schema 参数里）

```json
{
  "type": "function",
  "function": {
    "name": "semantic_product_search",
    "description": "根据使用场景、预算、品牌、处理器等条件推荐商品。适用于：'推荐游戏手机'、'5000以内性价比最高的手机'、'骁龙处理器手机有哪些'、'拍照好的手机'等推荐型需求。与 multi_platform_price_comparison 的区别：本工具做推荐筛选，后者做精确比价。",
    "parameters": {
      "type": "object",
      "properties": {
        "use_case": {
          "type": "string",
          "description": "使用场景标签，可选值：gaming(游戏) photography(拍照) battery(续航) business(商务) student(学生) budget(入门) flagship(旗舰)。多个用逗号分隔，如 'gaming,photography'",
          "default": ""
        },
        "brand": {"type": "string", "description": "品牌偏好，如 'Apple'、'小米'，为空则不限", "default": ""},
        "processor_brand": {"type": "string", "description": "处理器厂商：sd(骁龙) mt(天玑) apple(A/M系列) kirin(麒麟)，为空则不限", "default": ""},
        "performance_tier": {"type": "string", "description": "性能层级：flagship/mid/budget，为空则不限", "default": ""},
        "budget_max": {"type": "number", "description": "最高预算（元），不传则不限"},
        "budget_min": {"type": "number", "description": "最低预算（元），不传则不限"},
        "category": {"type": "string", "description": "品类，默认手机", "default": "手机"},
        "sort_by": {"type": "string", "description": "排序方式：value=性价比优先，price=最低价优先，performance=性能优先", "default": "value"},
        "top_n": {"type": "integer", "description": "返回推荐数量，默认5", "default": 5}
      },
      "required": []
    }
  }
}
```

### 核心实现逻辑

**Step 1：从所有平台聚合候选商品**
调用 PlatformParallelAgent().query_all_products_parallel() 获取所有平台所有商品。
按 product_name 去重（同名商品保留最低价那条，记录来自哪个平台）。

**Step 2：硬过滤（不满足直接排除）**
- category 过滤：row["category"] == category
- budget_max 过滤：row["price"] <= budget_max（如果传了的话）
- budget_min 过滤：row["price"] >= budget_min
- brand 过滤：row["brand"] == brand（如果传了的话）
- processor_brand 过滤：row["processor_brand"] == processor_brand
- performance_tier 过滤：row["performance_tier"] == performance_tier
- use_case 过滤：use_case 的每个标签都要在 row["use_case_tags"] 的 JSON 列表里
  （如 use_case="gaming,photography" → tags 里必须同时含 gaming 和 photography）

**Step 3：性价比评分 + 排序**
```python
TIER_SCORE = {"flagship": 100, "mid": 65, "budget": 35}

def value_score(row):
    tier = TIER_SCORE.get(row.get("performance_tier", "mid"), 50)
    price = row.get("price", 9999)
    if sort_by == "value":
        return tier / price * 10000   # 性价比分，越高越好
    elif sort_by == "price":
        return -price                 # 价格越低越好
    elif sort_by == "performance":
        return tier
    return tier / price * 10000
```

**Step 4：格式化返回**
```python
return {
    "success": True,
    "total_found": len(candidates),
    "recommendations": [
        {
            "rank": i + 1,
            "product_name": item["product_name"],
            "brand": item.get("brand", ""),
            "price": item["price"],
            "platform": item["platform_name"],
            "processor": item.get("processor", ""),
            "performance_tier": item.get("performance_tier", ""),
            "use_case_tags": item.get("use_case_tags", "[]"),
            "description": item.get("description", ""),
            "value_score": round(value_score(item), 2),
        }
        for i, item in enumerate(top_items)
    ],
    "filter_summary": f"品类={category}, 预算={budget_min or '不限'}-{budget_max or '不限'}, 场景={use_case or '不限'}, 排序={sort_by}"
}
```

如果过滤后没有候选商品，返回：
```python
{
    "success": False,
    "total_found": 0,
    "message": "未找到符合条件的商品",
    "suggestions": "您可以放宽条件重试，例如去掉处理器限制或提高预算上限"
}
```

### 注册到 __init__.py
在 `tools/__init__.py` 里 import 这个新文件，确保工具被注册。

> ⚠️ **【Fix-3 · 轻度】性价比公式 `tier/price*10000` 可能反直觉。**
> 按 TIER_SCORE = {"flagship": 100, "mid": 65, "budget": 35} 计算：
> - 红米Note13（budget, ¥1299）→ 35/1299*10000 = **269.4**
> - 小米14（flagship, ¥3999）→ 100/3999*10000 = **250.1**
> - iPhone 15 Pro（flagship, ¥8999）→ 100/8999*10000 = **111.1**
>
> 预算机排第一、旗舰垫底。如果用户搜"5000以内性价比最高"，这个排序是合理的；但如果用户搜"旗舰性价比"，预算机排第一就反直觉了。
> **建议**：增加可选参数 `min_performance_tier`，当用户提到"旗舰"时限定 tier≥mid。后续优化时可以考虑。

## 输出
1. 完整的 `tools/semantic_search_tool.py`
2. `tools/__init__.py` 需要新增的 import 行
```

---

### Prompt 3-B：react_engine.py 增加意图分类

```
你是一个 Python 后端工程师，正在优化 price-agent 项目的 `agent/react_engine.py`。

## 背景
现有 _is_complex() 只判断"是否复杂"，触发 Plan-Execute 或普通 ReAct 两条路。
但"我打游戏推荐什么手机"这类推荐型查询，即使进了 Plan-Execute，
LLM 生成的执行步骤仍然是调价格比较工具，而不是推荐工具。

需要增加意图分类层，让推荐型 query 能感知到"应该调 semantic_product_search"。

## 任务

### 1. 新增 USE_CASE_TRIGGER_MAP 常量（放在 class 外）

```python
# 使用场景触发词 → use_case 标签的映射
USE_CASE_TRIGGER_MAP: Dict[str, str] = {
    # gaming
    "游戏": "gaming", "打游戏": "gaming", "电竞": "gaming",
    "帧率": "gaming", "散热好": "gaming", "吃鸡": "gaming",
    # photography
    "拍照": "photography", "摄影": "photography", "相机": "photography",
    "vlog": "photography", "拍视频": "photography", "夜拍": "photography",
    # battery
    "续航": "battery", "大电池": "battery", "耐用": "battery",
    "不充电": "battery", "省电": "battery",
    # business
    "商务": "business", "办公": "business", "轻薄": "business",
    # student
    "学生": "student", "上学": "student", "学习用": "student",
    # budget
    "便宜": "budget", "实惠": "budget", "入门": "budget", "性价比": "budget",
    # flagship
    "旗舰": "flagship", "高端": "flagship", "顶配": "flagship",
}
```

### 2. 新增 _detect_intent() 方法

```python
def _detect_intent(self, query: str) -> str:
    """
    分类用户意图：
    - "recommendation"：推荐型，如"推荐游戏手机"、"5000以内什么手机好"
    - "comparison"：对比型，如"iPhone 15 和小米14哪个好"
    - "query"：查价型，如"iPhone 15 京东多少钱"
    
    返回 "recommendation" / "comparison" / "query"
    """
    # 推荐意图检测：含场景词 + 无明确商品型号 OR 含"推荐"/"建议"/"适合"
    has_use_case = any(kw in query for kw in USE_CASE_TRIGGER_MAP)
    has_recommend_word = any(w in query for w in ["推荐", "建议", "适合", "哪款好", "什么手机", "选什么"])
    has_budget = any(w in query for w in ["以内", "以下", "不超过", "预算", "多少钱以内"])
    
    # 有明确型号的不算推荐（如"推荐iPhone15"是查价，不是推荐）
    has_specific_model = self._has_specific_model(query)
    
    if (has_use_case or has_recommend_word or has_budget) and not has_specific_model:
        return "recommendation"
    
    # 对比意图：含对比词且有两个以上商品
    if self._is_complex(query):
        return "comparison"
    
    return "query"

def _has_specific_model(self, query: str) -> bool:
    """检测 query 里是否有明确的商品型号"""
    product_hints = self._load_product_hints()
    matches = sum(1 for h in product_hints if h.lower() in query.lower())
    return matches >= 1
```

> ⚠️ **【Fix-2 · 中等】USE_CASE_TRIGGER_MAP 缺少处理器关键词触发，导致"骁龙8Gen3手机有哪些"类查询被误分类为"query"。**
> Phase 5 P0-9 的测试用例 `test_recommendation_with_processor` 期望 `"骁龙8Gen3 手机有哪些" → "recommendation"`，但当前 TRIGGER_MAP 不含处理器词，`has_use_case` 为 False，`has_recommend_word` 也为 False，最终分类为 "query"。
>
> **修复方案**：在 USE_CASE_TRIGGER_MAP 中新增处理器触发词：
> ```python
> # processor — 处理器查询
> "骁龙": "processor", "天玑": "processor", "麒麟": "processor",
> "猎户座": "processor", "A17": "processor", "A16": "processor",
> "8Gen": "processor", "高通": "processor", "联发科": "processor",
> ```
> 同时在 `_detect_intent` 的判断逻辑中增加 `has_processor` 分支：
> ```python
> has_processor = any(kw in query for kw in ["骁龙", "天玑", "麒麟", "猎户座", "高通", "联发科",
>                                             "A17", "A16", "A15", "A14", "M2", "M3",
>                                             "8Gen", "8gen", "9Gen", "9gen"])
> ```
> 判断条件改为：`if (has_use_case or has_recommend_word or has_budget or has_processor) and not has_specific_model:`

### 3. 修改 run() 方法的路由逻辑

把现有的：
```python
if self._is_complex(user_query):
    return self._plan_and_execute(...)
return self._react_loop(...)
```

改为：
```python
intent = self._detect_intent(user_query)

if intent == "recommendation":
    if verbose:
        print(f"[Intent: recommendation] 启用语义推荐模式")
    # 推荐型直接走 ReAct，但在 system prompt 里强调使用 semantic_product_search
    return self._react_loop(user_query, history, verbose, intent_hint="recommendation")

elif intent == "comparison":
    if verbose:
        print(f"[Intent: comparison] 启用 Plan-Execute 对比模式")
    return self._plan_and_execute(user_query, history, verbose)

else:  # query
    return self._react_loop(user_query, history, verbose, intent_hint="query")
```

### 4. _react_loop() 增加 intent_hint 参数

在 _react_loop 的 messages 构建里，当 intent_hint == "recommendation" 时，
在 user message 前追加一条 system 级别的 hint（而不是修改主 SYSTEM_PROMPT）：

```python
if intent_hint == "recommendation":
    messages.append({
        "role": "system", 
        "content": "【意图提示】当前用户需求是商品推荐，请优先调用 semantic_product_search 工具，而不是 multi_platform_price_comparison。"
    })
```

## 输出
输出 `agent/react_engine.py` 里修改的部分：
1. USE_CASE_TRIGGER_MAP 常量（完整）
2. _detect_intent() 完整方法
3. _has_specific_model() 完整方法
4. run() 方法的新路由逻辑（完整）
5. _react_loop() 签名和 intent_hint 注入的相关修改
```

---

## Phase 4 · Prompt 层

> **目标：** 更新 SYSTEM_PROMPT 和 PLAN_PROMPT，让 LLM 知道什么时候用新工具，给 IT3C 推荐场景加 few-shot 示例。

---

### Prompt 4-A：SYSTEM_PROMPT 增加 IT3C 推荐工具指南

```
你是一个 Prompt 工程师，正在优化 price-agent 项目的 `agent/prompts.py`。

## 任务
在现有 SYSTEM_PROMPT 的"工具选择指南"章节里，
在工具4（search_product_by_image）之后新增工具5的描述，
同时在"Few-Shot 示例"章节末尾追加 3 个 IT3C 推荐场景示例。

### 新增工具5描述（插入到 ### 工具4 之后）：

```
### 工具5: semantic_product_search
**什么情况下用：**
- 用户描述使用场景而非具体型号 → 例："我经常打游戏，推荐什么手机"
- 用户给出预算范围 → 例："5000以内性价比最高的手机"
- 用户筛选处理器品牌 → 例："骁龙处理器的手机有哪些"
- 用户问"哪款好"但没给具体型号 → 例："拍照好的手机推荐一下"
- 含"推荐"/"适合"/"建议"/"什么手机"等词，且无明确型号

**什么情况下不要用：**
- 用户有明确型号（iPhone 15、小米14）→ 用 multi_platform_price_comparison 查价格
- 用户做两款机对比 → 用 multi_platform_price_comparison 分别查后对比

**参数填写规则：**
- use_case：从 gaming/photography/battery/business/student/budget/flagship 中选，多个用逗号分隔
- sort_by：用户说"便宜"→ price；用户说"性价比"→ value（默认）；用户说"最强"→ performance
- budget_max：从用户说的金额提取数字（"5000以内"→ 5000）
- 不确定的参数不传（默认不限）
```

### 新增 Few-Shot 示例 6、7、8（追加到现有示例末尾）：

**示例6：纯场景推荐**
```
用户：我经常打游戏，推荐什么手机
助手：
**Thought**：推荐型需求，用户没给明确型号，只给了使用场景（gaming），用 semantic_product_search。
**Action**：调用 semantic_product_search(use_case="gaming", category="手机", sort_by="value")
**Observation**：推荐结果：①小米14 Pro（¥5299，骁龙8Gen3，性价比分97）②iPhone 15 Pro（¥8999，A17 Pro）③小米14（¥3999，骁龙8Gen3，性价比分112）...
**Final Answer**：游戏手机推荐（按性价比排序）：
🥇 **小米14**（¥3999）— 骁龙8Gen3，旗舰游戏性能，各平台最低价在拼多多 ¥3899
🥈 **小米14 Pro**（¥5299）— 骁龙8Gen3 + 更强散热，适合重度游戏用户
🥉 **iPhone 15 Pro**（¥8999）— A17 Pro，iOS生态游戏体验最佳，预算充足首选
```

**示例7：预算 + 场景组合**
```
用户：拍照好的手机，5000以内，推荐几款
助手：
**Thought**：推荐型需求，条件：use_case=photography + budget_max=5000。
**Action**：调用 semantic_product_search(use_case="photography", budget_max=5000, category="手机", sort_by="value")
**Observation**：过滤后找到3款：小米14（¥3999，徕卡影像），iPhone 15（¥5999→超出预算被过滤）...
**Final Answer**：5000以内拍照手机推荐：
🥇 **小米14**（¥3999）— 徕卡联合调校，旗舰影像系统，性价比突出，拼多多 ¥3899
...（若预算内结果少于3款，主动建议："如果预算放宽到6000，还可以考虑 iPhone 15"）
```

**示例8：处理器筛选**
```
用户：骁龙8Gen3处理器的手机有哪些
助手：
**Thought**：用户明确指定处理器，用 semantic_product_search 过滤 processor_brand=sd + processor_hint。
**Action**：调用 semantic_product_search(processor_brand="sd", category="手机")
**Observation**：找到：小米14（骁龙8Gen3）、小米14 Pro（骁龙8Gen3）...
**Final Answer**：搭载骁龙系列处理器的手机：
• **小米14**（¥3999）— 骁龙8Gen3，各平台最低价拼多多 ¥3899
• **小米14 Pro**（¥5299）— 骁龙8Gen3，旗舰散热
如需了解某款详细比价，告诉我商品名即可。
```

## 关键约束
- 保留所有现有内容，只做追加
- 新示例格式与现有示例保持一致
- 不改变现有工具1-4的描述

## 输出
输出 `agent/prompts.py` 里新增的完整内容（工具5描述段落 + 3个示例），
标注好插入位置（"插入在### 工具4 之后"、"追加在示例5之后"）。
不需要输出 PLAN_PROMPT_TEMPLATE。
```

---

### Prompt 4-B：PLAN_PROMPT_TEMPLATE 增加推荐步骤感知

```
你是一个 Prompt 工程师，正在优化 price-agent 项目的 `agent/prompts.py` 中的 PLAN_PROMPT_TEMPLATE。

## 背景
PLAN_PROMPT_TEMPLATE 用于 Plan-Execute 策略下的步骤生成。
目前工具描述里只有比价工具，没有语义推荐工具，
导致 LLM 生成的计划步骤无法调用 semantic_product_search。

## 任务
在 PLAN_PROMPT_TEMPLATE 的 {tools_desc} 占位符渲染逻辑里，
确保 semantic_product_search 的描述被包含进去（这通常是自动的，因为工具已注册）。

同时在 PLAN_PROMPT_TEMPLATE 的示例部分追加一个推荐 + 比价的混合规划示例：

```
## 规划示例3：推荐后追加比价（混合意图）
用户输入："游戏手机5000以内推荐，推荐完告诉我各平台价格"

输出计划：
{
  "goal": "先按游戏场景推荐5000以内手机，再对推荐的手机做全平台比价",
  "steps": [
    {
      "step": 1,
      "tool": "semantic_product_search",
      "args": {"use_case": "gaming", "budget_max": 5000, "category": "手机", "sort_by": "value"},
      "purpose": "筛选5000以内适合游戏的手机列表"
    },
    {
      "step": 2,
      "tool": "multi_platform_price_comparison",
      "args": {"product_name": "$step1.recommendations[0].product_name"},
      "purpose": "对排名第一的推荐商品做全平台比价",
      "depends_on": [1]
    },
    {
      "step": 3,
      "tool": "multi_platform_price_comparison",
      "args": {"product_name": "$step1.recommendations[1].product_name"},
      "purpose": "对排名第二的推荐商品做全平台比价",
      "depends_on": [1]
    }
  ],
  "parallel_steps": [[2, 3]]
}
```

注意：$step1.recommendations[0].product_name 是新的引用路径语法，
需要在 react_engine.py 的 _deref() 函数里支持列表索引解析（如 [0]、[1]）。

## 额外任务：扩展 _deref() 支持列表索引

在 react_engine.py 的 _deref() 方法里，增加对 [N] 列表索引的解析：

```python
# 在遍历 path 的循环里增加：
for part in parts:
    if isinstance(current, list):
        # 支持 recommendations[0] 这种带索引的路径
        m = re.match(r'^(\w+)\[(\d+)\]$', part)
        if m:
            key, idx = m.group(1), int(m.group(2))
            current = current[key][idx] if isinstance(current, dict) else current[int(idx)]
        else:
            break
    elif isinstance(current, dict):
        current = current.get(part)
    else:
        break
```

## 输出
1. PLAN_PROMPT_TEMPLATE 里新增的示例片段（标注插入位置）
2. react_engine.py 里 _deref() 方法的修改部分
```

---

## Phase 5 · 评估层

> **目标：** 补充 IT3C 推荐场景的评估用例，确保新功能有测试覆盖。

---

### Prompt 5-A：评估 case 补充

```
你是一个测试工程师，正在为 price-agent 项目补充 IT3C 场景的评估用例。

## 背景
项目已有完整的 P0-P6 评估框架（见 评估文档.md）。
需要补充针对 IT3C 手机品类的推荐场景用例，涵盖：
1. P0 单元测试：semantic_product_search 的过滤和排序逻辑
2. P1 属性提取：处理器 + 预算 + 场景的 LLM 解析准确率
3. P2 工具调用链：推荐意图的完整端到端流程

## 任务：编写 test_it3c_eval.py

### P0 单元测试（不调 LLM）

```python
# P0-8：semantic_product_search 过滤逻辑
class TestSemanticSearch:

    def test_use_case_filter(self):
        """gaming 标签过滤：只返回 use_case_tags 含 gaming 的商品"""
        result = semantic_product_search(use_case="gaming", category="手机")
        assert result["success"] == True
        for item in result["recommendations"]:
            tags = json.loads(item["use_case_tags"])
            assert "gaming" in tags, f"{item['product_name']} 不含 gaming 标签"

    def test_budget_filter(self):
        """预算过滤：所有推荐商品价格 <= budget_max"""
        result = semantic_product_search(budget_max=4500, category="手机")
        for item in result["recommendations"]:
            assert item["price"] <= 4500

    def test_processor_brand_filter(self):
        """处理器品牌过滤：只返回 processor_brand=sd 的商品"""
        result = semantic_product_search(processor_brand="sd", category="手机")
        # 需要至少有 1 条结果（数据库里有骁龙手机）
        assert result["total_found"] >= 1
        for item in result["recommendations"]:
            assert item.get("processor_brand") == "sd" or "骁龙" in item.get("processor", "")

    def test_sort_by_value(self):
        """性价比排序：第一名的 value_score 应 >= 最后一名"""
        result = semantic_product_search(category="手机", sort_by="value")
        items = result["recommendations"]
        if len(items) >= 2:
            assert items[0]["value_score"] >= items[-1]["value_score"]

    def test_sort_by_price(self):
        """价格排序：第一名价格 <= 最后一名"""
        result = semantic_product_search(category="手机", sort_by="price")
        items = result["recommendations"]
        if len(items) >= 2:
            assert items[0]["price"] <= items[-1]["price"]

    def test_no_result_graceful(self):
        """无结果时返回友好提示"""
        result = semantic_product_search(use_case="gaming", budget_max=100, category="手机")
        assert result["success"] == False
        assert "suggestions" in result

    def test_combined_filter(self):
        """组合过滤：gaming + budget_max=5000 + processor_brand=sd"""
        result = semantic_product_search(
            use_case="gaming", budget_max=5000, processor_brand="sd", category="手机"
        )
        # 至少应匹配小米14
        assert result["total_found"] >= 1
```

### P0-9：_detect_intent 单元测试

```python
class TestIntentDetection:
    def setup_method(self):
        self.agent = ReActAgent(client=None, model="", tools=[], tool_map={})

    def test_recommendation_intent_use_case(self):
        assert self.agent._detect_intent("我打游戏推荐什么手机") == "recommendation"

    def test_recommendation_intent_budget(self):
        assert self.agent._detect_intent("5000以内手机推荐") == "recommendation"

    def test_recommendation_intent_scene_word(self):
        assert self.agent._detect_intent("拍照好的手机有哪些") == "recommendation"

    def test_query_intent_specific_model(self):
        assert self.agent._detect_intent("iPhone 15 价格") == "query"

    def test_comparison_intent(self):
        assert self.agent._detect_intent("iPhone 15 和小米14 哪个好") == "comparison"

    def test_recommendation_with_processor(self):
        assert self.agent._detect_intent("骁龙8Gen3 手机有哪些") == "recommendation"
```

### P1 属性提取测试（调 LLM）

```python
# P1-IT3C：IT3C 专属属性提取
IT3C_EXTRACTION_CASES = [
    {
        "input": "我打游戏，5000以内骁龙处理器手机推荐",
        "expected": {
            "use_case": "gaming",
            "budget_max": 5000,
            "processor_brand": "sd",
            "category": "手机"
        }
    },
    {
        "input": "天玑9300拍照手机",
        "expected": {
            "processor_brand": "mt",
            "processor_hint_contains": "9300",
            "use_case": "photography"
        }
    },
    {
        "input": "旗舰手机不超过8000",
        "expected": {
            "performance_tier": "flagship",
            "budget_max": 8000,
            "category": "手机"
        }
    },
    {
        "input": "学生用手机，便宜实惠，天玑处理器",
        "expected": {
            "use_case_contains": "student",
            "processor_brand": "mt",
            "performance_tier": "budget"
        }
    },
    {
        "input": "A17 Pro芯片手机",
        "expected": {
            "processor_brand": "apple",
            "processor_hint_contains": "A17"
        }
    },
]
```

### P2 工具调用链测试（完整 ReAct）

```python
# P2-IT3C：推荐型端到端测试
IT3C_CHAIN_CASES = [
    {
        "id": "IT3C-01",
        "input": "游戏手机推荐",
        "expect_tool": "semantic_product_search",
        "expect_args_contains": {"use_case": "gaming"},
        "expect_answer_contains": ["推荐", "骁龙"]
    },
    {
        "id": "IT3C-02",
        "input": "5000以内性价比最高的手机",
        "expect_tool": "semantic_product_search",
        "expect_args_contains": {"budget_max": 5000},
    },
    {
        "id": "IT3C-03",
        "input": "骁龙8Gen3手机有哪些，各平台什么价格",
        "expect_tools": ["semantic_product_search", "multi_platform_price_comparison"],
        "expect_answer_contains": ["骁龙", "¥"]
    },
    {
        "id": "IT3C-04",
        "input": "拍照好续航也好的手机",
        "expect_tool": "semantic_product_search",
        "expect_args_contains": {"use_case": "photography,battery"}
    },
]
```

## 输出
输出完整的 `test_it3c_eval.py` 文件，包含：
1. P0 单元测试（不依赖 LLM，可直接 pytest 运行）
2. P0-9 意图检测测试
3. P1/P2 用例数据结构定义（测试执行框架参照现有 P1/P2 测试文件格式）
4. 文件顶部加 docstring 说明本文件覆盖的场景范围
```

---

## Phase 6 · 历史压缩优化（可选 · 建议延后）

> **目标：** 优化多轮对话的 Token 效率，避免长对话中大段比价结果占满 context window。
>
> ⚠️ **【Fix-5 · 轻度】此 Phase 标记为可选，建议等 Phase 1-5 核心功能稳定后再实施。**
> 原因：
> 1. 新 `_slide_window` 逻辑更复杂（从最新到最旧遍历、保留最近 2 条全文），需要充分测试
> 2. `generate_message_summary` 的启发式规则（提取第一行）对结构化比价数据效果有限，可能需要专门的价格信息保留逻辑
> 3. 当前阶段 token 压力不大（mock 数据量小），不是瓶颈
> 4. 不影响 Phase 1-5 任何功能

---

### Prompt 6：历史消息摘要压缩

```
你是一个 Python 后端工程师，正在优化 price-agent 项目的多轮对话 Token 效率。

## 背景
max_history_chars=6000，但一条含完整比价数据的 assistant 回复约 800-1500 字符。
6 轮对话后历史消息就会撑满限制，导致更早的上下文被截断丢失。

## 任务：在 database/models.py 的 add_message 函数里增加摘要存储

### 1. messages 表新增 summary 字段

```sql
ALTER TABLE messages ADD COLUMN summary TEXT;
```

在 init_mock_db 的建表语句里同步加上这个字段（建表时就加，避免迁移）。

### 2. 修改 add_message 函数签名

```python
def add_message(db, session_id: str, role: str, content: str, summary: str = None) -> Dict:
    """
    summary：assistant 消息的摘要版本（可选）。
    如果不传，summary = content 的前 100 字符 + "..."
    """
```

### 3. 新增 generate_message_summary 工具函数

```python
def generate_message_summary(content: str, max_len: int = 120) -> str:
    """
    为 assistant 消息生成摘要，规则：
    - 如果内容 <= max_len，直接返回原文
    - 否则：提取第一个换行前的内容（通常是"最终答案"的核心句）
    - 如果还是太长，截断到 max_len 并加 "..."
    - 特殊处理：含 "¥" 的价格信息保留平台+最低价那行
    """
    if len(content) <= max_len:
        return content
    
    # 提取第一行（通常是核心结论）
    first_line = content.split('\n')[0].strip()
    if len(first_line) <= max_len:
        return first_line
    
    return content[:max_len] + "..."
```

### 4. 修改 react_engine.py 的 _slide_window

在 _slide_window 里，当历史消息超过字符限制时，
优先用 summary 替代 content（如果 summary 存在的话）：

```python
def _slide_window(self, history: List[Dict]) -> List[Dict]:
    """滑动窗口：超出字符限制时，较早的消息用 summary 替代 content"""
    result = []
    total_chars = 0
    
    # 从最新到最旧遍历
    for msg in reversed(history):
        content = msg.get("content", "")
        summary = msg.get("summary", "")
        
        # 最近 2 条消息保持全文
        if len(result) < 2:
            use_content = content
        else:
            # 更早的消息优先用 summary
            use_content = summary if summary and len(summary) < len(content) else content
        
        total_chars += len(use_content)
        if total_chars > self.max_history_chars and len(result) >= 2:
            break
        
        result.append({**msg, "content": use_content})
    
    return list(reversed(result))
```

### 5. app.py 的 /api/chat 路由修改

保存 assistant 消息时，生成并存储 summary：
```python
from database import generate_message_summary
summary = generate_message_summary(answer)
add_message(db, session_id, 'assistant', answer, summary=summary)
```

## 输出
1. database/models.py 里 messages 建表语句的修改 + add_message 函数新版本 + generate_message_summary 函数
2. react_engine.py 里 _slide_window 方法的新版本
3. app.py 里 add_message 调用处的修改（只输出修改的那几行）
```

---

## 提示词使用建议

| 阶段 | 提示词 | 预计改动文件 | 依赖 |
|------|--------|-------------|------|
| Phase 1 | 1-A、1-B | platform_database.py、models.py、app.py | 无 |
| Phase 2 | 2-A、2-B | platform_database.py、multi_platform_tools.py | Phase 1 |
| Phase 3 | 3-A、3-B | semantic_search_tool.py（新建）、react_engine.py | Phase 1、2 |
| Phase 4 | 4-A、4-B | prompts.py、react_engine.py | Phase 3 |
| Phase 5 | 5-A | test_it3c_eval.py（新建） | Phase 1-4 全部 |
| Phase 6 | 6 | models.py、react_engine.py、app.py | Phase 1 |

**每个提示词执行完后，建议运行一次 `pytest test_multi_platform.py` 做回归，确保原有功能不受影响。**

---

## 附录：实际执行记录

> 执行时间：2026-05-12
> 执行模型：DeepSeek V4 Flash（`deepseek-v4-flash`）
> 视觉模型：豆包 `doubao-seed-2-0-pro-260215`（未更换）

### 执行过程发现的额外问题

#### 【Fix-6 · 严重】DeepSeek V4 模型 thinking tokens 导致 JSON 响应截断

**发现过程**：Phase 5 评估时，P1 属性提取测试出现随机性失败——同样的 query 有时能正确提取属性，有时全部返回空值。通过逐步调试发现：DeepSeek V4 系列模型内部使用 thinking tokens（推理链），这些 tokens 会消耗 `max_tokens` 配额。原有 `max_tokens=200` 在 thinking 消耗 100-150 tokens 后，留给实际输出的配额不足 100 tokens，长 JSON 响应被截断，JSON 解析失败后触发 `except` 分支返回空默认值。

**解决方案**：`tools/multi_platform_tools.py` 中 `_parse_attrs_from_query` 的 `max_tokens` 从 200 → 500，为 thinking tokens 留出足够空间。

#### 【Fix-8 · 中等】混合意图路由——同时含推荐 + 对比的复杂 query 处理

**发现过程**：用户提问"如果复杂 query 包含了 recommendation 和 comparison 你怎么处理"，验证发现 "推荐游戏手机，然后和 iPhone 15 对比" 这类 query 被误判为 `query`（因 model_count=1 直接短路）。进一步测试暴露了 3 个路由冲突：`"便宜"` 触发 budget 标签导致查价句式的误判、`"推荐"` 在 complexity_keywords 中导致单商品查价被判为 comparison、以及无型号对比词（如"和苹果比较"）未被正确处理。

**解决方案**：
1. 新增 `has_price_lookup` 检测——含"最便宜""多少钱""哪个平台"的 query 不算推荐触发
2. 从 complexity_keywords 中移除"推荐"/"建议"（意图分类已接管）
3. "推荐"+单型号+无场景/预算/处理器限定 → query（仅查价）
4. 推荐触发 + `is_complex`（含对比词/多步骤） → comparison（Plan-Execute 混合意图）
5. 推荐触发 + 无对比证据 → recommendation

**最终路由矩阵**：

| 触发条件 | model_count | is_complex | 结果 | 示例 |
|---------|:----------:|:----------:|------|------|
| 推荐触发 | 0 | — | recommendation | "骁龙8Gen3手机有哪些" |
| 推荐触发 | ≥1 | True | comparison | "推荐游戏手机，再和iPhone 15对比" |
| 仅推荐词 | ≥1 | False | query | "推荐iPhone 15" |
| 无触发 | 1 | — | query | "iPhone 15 价格" |
| 无触发 | ≥2 | — | comparison | "iPhone 15 和小米14 哪个好" |

#### 【Fix-7 · 轻度】DeepSeek 模型对长 prompt 的 few-shot 示例依赖强

**发现过程**：P1 评估中，"学生用手机便宜实惠天玑处理器" 这类 query，DeepSeek 提取 `use_case=student` 的成功率不如豆包稳定。分析发现 DeepSeek V4 Flash 对隐式语义推断（如"大学生用的"→student）不如豆包模型积极。

**解决方案**：当前 prompt 中的 few-shot 示例已覆盖主要场景，通过率 100%。后续如需提升，可在 few-shot 中增加更多口语化推断示例。

### 各 Phase 执行结果

| Phase | 内容 | 状态 | 改动文件 |
|-------|------|------|---------|
| 1-A | Schema 扩展 + Mock 数据 | ✅ | `platforms/platform_database.py` |
| 1-B | Schema 分裂修复 | ✅ | `database/models.py`, `database/__init__.py`, `app.py` |
| 2-A | 处理器别名 + 评分扩展 | ✅ | `platforms/platform_database.py`, `platforms/parallel_agent.py` |
| 2-B | 属性提取扩展 | ✅ | `tools/multi_platform_tools.py` |
| 3-A | 语义推荐工具 | ✅ | `tools/semantic_search_tool.py`（新建）, `tools/__init__.py` |
| 3-B | 意图分类 | ✅ | `agent/react_engine.py` |
| 4-A | SYSTEM_PROMPT 扩展 | ✅ | `agent/prompts.py` |
| 4-B | PLAN_PROMPT + _deref | ✅ | `agent/prompts.py`, `agent/react_engine.py` |
| 5 | 评估用例 | ✅ | `tests/eval_it3c.py`（新建） |

### 模型配置变更

| 配置项 | 旧值 | 新值 |
|--------|------|------|
| API Provider | 火山引擎 Ark | DeepSeek |
| base_url | `https://ark.cn-beijing.volces.com/api/v3` | `https://api.deepseek.com` |
| 环境变量 | `ARK_API_KEY` | `DEEPSEEK_API_KEY` |
| 文本模型 | `doubao-seed-2-0-pro-260215` | `deepseek-v4-flash` |
| 视觉模型 | `doubao-seed-2-0-pro-260215` | 不变 |
| 属性解析 max_tokens | 200 | 500（适配 thinking tokens） |

### 评估结果汇总

| 评测套件 | 通过 | 总数 | 通过率 |
|----------|------|------|--------|
| IT3C P0 单元测试 | 35 | 35 | 100% |
| IT3C P1 属性提取 | 7 | 7 | 100% |
| IT3C P2 端到端 | 4 | 4 | 100% |
| 原有 P0 回归 | 42 | 43 | 97.7%（1 项为 Schema 设计变更预期） |
