"""
测试多平台比价功能
"""
import sys
sys.path.insert(0, '.')

from platforms import init_all_platforms, PlatformParallelAgent, format_comparison_result

print("=" * 70)
print("测试多平台比价功能")
print("=" * 70)

# 1. 初始化所有平台
print("\n1. 初始化平台数据库...")
init_all_platforms()

# 2. 测试单个平台查询
print("\n2. 测试单平台查询...")
from platforms import PlatformDatabase
jd_db = PlatformDatabase('jd')
result = jd_db.query_product('iPhone 15')
print(f"   京东查询 iPhone 15: {result}")
jd_db.close()

# 3. 测试并行查询
print("\n3. 测试并行查询...")
with PlatformParallelAgent() as agent:
    # 查询单个商品
    print("\n   查询 iPhone 15...")
    comparison = agent.compare_product_price('iPhone 15')
    print(format_comparison_result(comparison))
    
    # 查询另一个商品
    print("\n" + "=" * 70)
    print("   查询小米平板6...")
    comparison2 = agent.compare_product_price('小米平板6')
    print(format_comparison_result(comparison2))

print("\n" + "=" * 70)
print("所有测试完成！")
print("=" * 70)
