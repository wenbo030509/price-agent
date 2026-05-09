# 多平台比价功能说明

## 功能概述

已成功实现多平台比价功能，支持4个电商平台模拟数据：
- 🛒 京东
- 🛍️ 淘宝
- 🎁 拼多多
- 📺 苏宁

## 核心特性

### 1. 多数据库架构
- 每个平台独立SQLite数据库文件
- 文件名格式：`platform_{平台id}.db`
- 支持独立的商品定价、库存、运费

### 2. 并行查询机制
- 使用Python `concurrent.futures` 线程池
- 4个平台同时查询，高效响应
- 超时控制，避免卡死
- 线程安全的数据库连接

### 3. 智能比价分析
- 自动找出最低价和最高价平台
- 计算平均价格和价格差异
- 考虑运费，显示真实总价
- 库存状态显示

## 新增文件

```
platforms/
├── __init__.py                    # 包导出
├── platform_config.py             # 平台配置
├── platform_database.py           # 单平台数据库管理
└── parallel_agent.py              # 并行查询Agent

tools/
└── multi_platform_tools.py        # 多平台工具

test_multi_platform.py             # 测试脚本
MULTI_PLATFORM_README.md           # 本文件
```

## 修改文件

- `app.py` - 添加多平台API接口
- `agent/prompts.py` - 更新系统提示
- `tools/__init__.py` - 导出新工具
- `templates/index.html` - 添加比价UI
- `static/css/style.css` - 添加比价样式
- `static/js/app.js` - 添加比价交互

## API接口

### 获取平台列表
```
GET /api/platforms
```

### 多平台比价
```
POST /api/multi-platform/compare
Content-Type: application/json
{
  "product_name": "iPhone 15"
}
```

### 获取所有平台商品
```
GET /api/multi-platform/products
```

## 使用方式

### 1. Web界面
- 打开 http://127.0.0.1:5001
- 右侧面板点击「多平台比价」标签
- 输入商品名称或点击快速查询标签
- 查看比价结果

### 2. Agent对话
- 在聊天框中询问："iPhone 15哪个平台便宜"
- Agent会自动调用 `multi_platform_price_comparison` 工具
- 展示比价结果

### 3. 命令行测试
```bash
python3 test_multi_platform.py
```

## 示例商品数据

每个平台预置13个商品，价格略有差异：
- iPhone 15
- iPhone 15 Pro
- 小米14
- 华为Mate60
- 华为Mate60 Pro
- iPad Pro
- 小米平板6
- 小米平板6 Pro
- MacBook Pro 14
- AirPods Pro

## 技术亮点

1. **线程安全**：每个平台独立数据库连接
2. **并行执行**：4个平台同时查询，提升效率
3. **统一接口**：PlatformParallelAgent封装复杂逻辑
4. **工具集成**：与ReAct Agent无缝集成
5. **用户友好**：格式化输出，清晰直观

## 未来扩展

- 添加更多电商平台
- 支持实时爬取真实数据
- 历史价格走势图
- 降价提醒功能
- 优惠券叠加计算
