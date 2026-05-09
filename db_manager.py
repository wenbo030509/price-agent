#!/usr/bin/env python3
"""
数据库管理工具
用于管理SQLite数据库中的商品、会话和消息
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import (
    DatabaseConnection,
    init_mock_db,
    add_product,
    get_all_products,
    get_all_sessions,
    get_session_messages,
    delete_session
)


def print_products(db):
    """打印所有商品"""
    products = get_all_products(db)
    if not products:
        print("暂无商品数据")
        return
    
    print("\n=== 商品列表 ===")
    print(f"{'ID':<5} {'商品名称':<20} {'价格':<10} {'库存':<8} {'品类':<10}")
    print("-" * 65)
    for p in products:
        print(f"{p['id']:<5} {p['product_name']:<20} {p['price']:<10} {p['stock']:<8} {p['category']:<10}")


def print_sessions(db):
    """打印所有会话"""
    sessions = get_all_sessions(db)
    if not sessions:
        print("暂无会话数据")
        return
    
    print("\n=== 会话列表 ===")
    print(f"{'会话ID':<38} {'创建时间'}")
    print("-" * 70)
    for s in sessions:
        print(f"{s['session_id']:<38} {s['created_at']}")


def print_session_details(db, session_id):
    """打印会话详情"""
    messages = get_session_messages(db, session_id)
    if not messages:
        print("该会话暂无消息")
        return
    
    print(f"\n=== 会话 {session_id[:8]}... 的消息 ===")
    for msg in messages:
        role = "用户" if msg['role'] == "user" else "AI助手"
        print(f"\n[{msg['timestamp']}] {role}:")
        print(f"  {msg['content']}")


def add_new_product(db):
    """添加新商品"""
    print("\n=== 添加新商品 ===")
    try:
        name = input("商品名称: ").strip()
        price = float(input("价格: "))
        stock = int(input("库存: "))
        category = input("品类: ").strip()
        
        if not name or not category:
            print("商品名称和品类不能为空！")
            return
        
        product = add_product(db, name, price, stock, category)
        print(f"商品添加成功！ID: {product['id']}")
    except ValueError:
        print("价格和库存必须是数字！")
    except Exception as e:
        print(f"添加商品失败：{str(e)}")


def delete_existing_session(db):
    """删除会话"""
    print("\n=== 删除会话 ===")
    sessions = get_all_sessions(db)
    if not sessions:
        print("暂无会话可删除")
        return
    
    print_sessions(db)
    session_idx = input("\n输入要删除的会话编号（1开始）：").strip()
    
    try:
        idx = int(session_idx) - 1
        if 0 <= idx < len(sessions):
            if delete_session(db, sessions[idx]['session_id']):
                print("会话删除成功！")
        else:
            print("无效的会话编号")
    except ValueError:
        print("请输入有效的数字")


def main():
    """主函数"""
    print("=" * 60)
    print("  商品对比Agent - 数据库管理工具")
    print("=" * 60)
    
    # 初始化数据库
    db = DatabaseConnection("price_agent.db")
    
    # 检查数据库是否已初始化
    cursor = db.get_cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='products'")
    if not cursor.fetchone():
        print("\n检测到新数据库，正在初始化...")
        init_mock_db(db)
        print("数据库初始化完成！")
    
    # 主菜单
    while True:
        print("\n" + "=" * 60)
        print("主菜单:")
        print("  1. 查看商品列表")
        print("  2. 添加新商品")
        print("  3. 查看会话列表")
        print("  4. 查看会话详情")
        print("  5. 删除会话")
        print("  0. 退出")
        print("=" * 60)
        
        choice = input("\n请选择操作 (0-5): ").strip()
        
        if choice == "0":
            print("再见！")
            break
        elif choice == "1":
            print_products(db)
        elif choice == "2":
            add_new_product(db)
        elif choice == "3":
            print_sessions(db)
        elif choice == "4":
            sessions = get_all_sessions(db)
            if not sessions:
                print("暂无会话数据")
                continue
            print_sessions(db)
            session_idx = input("\n输入要查看的会话编号（1开始）：").strip()
            try:
                idx = int(session_idx) - 1
                if 0 <= idx < len(sessions):
                    print_session_details(db, sessions[idx]['session_id'])
                else:
                    print("无效的会话编号")
            except ValueError:
                print("请输入有效的数字")
        elif choice == "5":
            delete_existing_session(db)
        else:
            print("无效的选择，请重新输入")


if __name__ == "__main__":
    main()
