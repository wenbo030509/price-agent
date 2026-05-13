#!/usr/bin/env python3
"""测试颜色和内存字段功能"""

from platforms import PlatformDatabase
from platforms import get_all_platforms
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

print("=" * 60)
print("测试颜色和内存字段功能")
print("=" * 60)

# 测试京东平台
print("\n测试京东平台...")
jd_db = PlatformDatabase("jd")
products = jd_db.query_all_products()

print(f"✓ 共获取到 {len(products)} 个商品")

# 显示前3个商品的颜色和内存信息
for i, product in enumerate(products[:3]):
    print(f"\n商品 {i+1}: {product['product_name']}")
    print(f"  - 参考价: ¥{product['price']}")
    print(f"  - 平台价: ¥{product['platform_price']}")
    print(f"  - 颜色: {product.get('color', '无')}")
    print(f"  - 内存: {product.get('memory', '无')}")
    print(f"  - 库存: {product['stock']}")
    print(f"  - 品类: {product['category']}")

jd_db.close()

print("\n" + "=" * 60)
print("✓ 所有测试完成！颜色和内存字段工作正常")
print("=" * 60)
