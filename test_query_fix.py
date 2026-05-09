"""
测试修复后的商品查询逻辑
"""
import sys
sys.path.insert(0, '.')

from platforms import PlatformDatabase, init_all_platforms

print("=" * 70)
print("测试修复后的查询逻辑")
print("=" * 70)

# 1. 确保数据库已初始化
init_all_platforms()

# 2. 测试不同的查询方式
test_queries = [
    "iPhone 15",    # 正常查询
    "iPhone15",     # 没有空格
    "iphone15",     # 小写
    "IPHONE15",     # 大写
    " iphone15 ",   # 有前后空格
    "小米14",       # 中文测试
    "小米 14",      # 中文加空格
]

platforms = ["jd", "taobao", "pdd", "suning"]

for query in test_queries:
    print(f"\n🔍 测试查询: '{query}'")
    found_count = 0
    
    for platform_id in platforms:
        db = PlatformDatabase(platform_id)
        result = db.query_product(query)
        db.close()
        
        if result:
            print(f"   ✓ {result['platform_name']}: 找到 '{result['product_name']}' - ¥{result['platform_price']}")
            found_count += 1
    
    if found_count == 0:
        print(f"   ✗ 所有平台都未找到")

print("\n" + "=" * 70)
print("测试完成！")
print("=" * 70)
