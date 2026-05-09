"""
多平台并行查询Agent
支持同时从多个平台查询商品数据并汇总结果
"""
import concurrent.futures
import threading
from typing import List, Dict, Optional, Tuple
from .platform_config import get_platform_config, get_platform_ids
from .platform_database import PlatformDatabase


class PlatformAgent:
    """单个平台的查询Agent"""
    
    def __init__(self, platform_id: str):
        self.platform_id = platform_id
        self.config = get_platform_config(platform_id)
        self.db = PlatformDatabase(platform_id)
        self._lock = threading.Lock()
    
    def query_product(self, product_name: str) -> Optional[Dict]:
        """查询单个商品"""
        with self._lock:
            try:
                result = self.db.query_product(product_name)
                return result
            except Exception as e:
                print(f"⚠️  {self.config['name']}查询出错: {e}")
                return None
    
    def query_all_products(self) -> List[Dict]:
        """查询所有商品"""
        with self._lock:
            try:
                return self.db.query_all_products()
            except Exception as e:
                print(f"⚠️  {self.config['name']}查询出错: {e}")
                return []
    
    def close(self):
        """关闭数据库连接"""
        self.db.close()


class PlatformParallelAgent:
    """多平台并行查询管理器"""
    
    def __init__(self, platform_ids: List[str] = None):
        """
        初始化并行查询Agent
        :param platform_ids: 要查询的平台ID列表，默认为所有平台
        """
        self.platform_ids = platform_ids or get_platform_ids()
        self.agents = {
            pid: PlatformAgent(pid)
            for pid in self.platform_ids
        }
        self._executor = None
    
    def _get_executor(self, max_workers: int = 4):
        """获取线程池执行器"""
        if self._executor is None:
            self._executor = concurrent.futures.ThreadPoolExecutor(
                max_workers=max_workers
            )
        return self._executor
    
    def query_product_parallel(self, product_name: str, timeout: int = 10) -> Dict:
        """
        并行查询所有平台的商品
        :param product_name: 商品名称
        :param timeout: 超时时间（秒）
        :return: 各平台查询结果汇总
        """
        executor = self._get_executor()
        futures = {}
        
        # 提交所有查询任务
        for platform_id, agent in self.agents.items():
            future = executor.submit(agent.query_product, product_name)
            futures[future] = platform_id
        
        results = {}
        errors = {}
        
        # 收集结果
        for future in concurrent.futures.as_completed(futures, timeout=timeout):
            platform_id = futures[future]
            try:
                result = future.result()
                if result:
                    results[platform_id] = result
                else:
                    results[platform_id] = {
                        "platform_id": platform_id,
                        "platform_name": self.agents[platform_id].config["name"],
                        "found": False
                    }
            except concurrent.futures.TimeoutError:
                errors[platform_id] = "查询超时"
            except Exception as e:
                errors[platform_id] = str(e)
        
        return {
            "product_name": product_name,
            "results": results,
            "errors": errors,
            "summary": self._summarize_results(results)
        }
    
    def query_all_products_parallel(self, timeout: int = 10) -> Dict:
        """
        并行查询所有平台的所有商品
        :param timeout: 超时时间（秒）
        :return: 各平台查询结果汇总
        """
        executor = self._get_executor()
        futures = {}
        
        # 提交所有查询任务
        for platform_id, agent in self.agents.items():
            future = executor.submit(agent.query_all_products)
            futures[future] = platform_id
        
        results = {}
        errors = {}
        
        # 收集结果
        for future in concurrent.futures.as_completed(futures, timeout=timeout):
            platform_id = futures[future]
            try:
                products = future.result()
                results[platform_id] = {
                    "platform_id": platform_id,
                    "platform_name": self.agents[platform_id].config["name"],
                    "products": products,
                    "count": len(products)
                }
            except concurrent.futures.TimeoutError:
                errors[platform_id] = "查询超时"
            except Exception as e:
                errors[platform_id] = str(e)
        
        return {
            "results": results,
            "errors": errors
        }
    
    def compare_product_price(self, product_name: str, timeout: int = 10) -> Dict:
        """
        比价查询：找出最低价和最高价的平台
        :param product_name: 商品名称
        :param timeout: 超时时间（秒）
        :return: 比价结果
        """
        query_result = self.query_product_parallel(product_name, timeout)
        results = query_result["results"]
        
        valid_results = []
        for platform_id, result in results.items():
            if result.get("found", True) and "price" in result:
                valid_results.append(result)
        
        if not valid_results:
            return {
                "product_name": product_name,
                "found": False,
                "message": "在所有平台都未找到该商品"
            }
        
        # 找出最低和最高价格
        valid_results.sort(key=lambda x: x["platform_price"])
        cheapest = valid_results[0]
        most_expensive = valid_results[-1]
        
        # 计算平均价格
        avg_price = sum(r["platform_price"] for r in valid_results) / len(valid_results)
        
        return {
            "product_name": product_name,
            "found": True,
            "valid_platforms": len(valid_results),
            "all_results": valid_results,
            "cheapest": {
                "platform": cheapest["platform_name"],
                "platform_id": cheapest["platform_id"],
                "price": cheapest["platform_price"],
                "stock": cheapest["stock"],
                "shipping_fee": cheapest["shipping_fee"],
                "total_price": cheapest["platform_price"] + cheapest["shipping_fee"]
            },
            "most_expensive": {
                "platform": most_expensive["platform_name"],
                "platform_id": most_expensive["platform_id"],
                "price": most_expensive["platform_price"],
                "stock": most_expensive["stock"],
                "shipping_fee": most_expensive["shipping_fee"],
                "total_price": most_expensive["platform_price"] + most_expensive["shipping_fee"]
            },
            "average_price": round(avg_price, 2),
            "price_range": {
                "min": cheapest["platform_price"],
                "max": most_expensive["platform_price"],
                "diff": round(most_expensive["platform_price"] - cheapest["platform_price"], 2)
            }
        }
    
    def _summarize_results(self, results: Dict) -> Dict:
        """汇总查询结果"""
        found_count = sum(1 for r in results.values() if r.get("found", True) and "price" in r)
        total_count = len(results)
        
        return {
            "total_platforms": total_count,
            "found_platforms": found_count,
            "not_found_platforms": total_count - found_count
        }
    
    def close(self):
        """关闭所有资源"""
        if self._executor:
            self._executor.shutdown(wait=True)
            self._executor = None
        
        for agent in self.agents.values():
            agent.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


def format_comparison_result(comparison: Dict) -> str:
    """格式化比价结果为易读文本"""
    if not comparison["found"]:
        return comparison["message"]
    
    lines = []
    lines.append(f"📊 商品「{comparison['product_name']}」多平台比价结果")
    lines.append("=" * 70)
    
    cheapest = comparison["cheapest"]
    most_expensive = comparison["most_expensive"]
    
    lines.append(f"🏆 最划算: {cheapest['platform']} - ¥{cheapest['price']}")
    if cheapest['shipping_fee'] > 0:
        lines.append(f"   运费: ¥{cheapest['shipping_fee']}, 总计: ¥{cheapest['total_price']}")
    lines.append(f"   库存: {cheapest['stock']}件")
    
    lines.append("")
    lines.append(f"💎 最高价: {most_expensive['platform']} - ¥{most_expensive['price']}")
    if most_expensive['shipping_fee'] > 0:
        lines.append(f"   运费: ¥{most_expensive['shipping_fee']}, 总计: ¥{most_expensive['total_price']}")
    
    lines.append("")
    lines.append(f"📈 价格区间: ¥{comparison['price_range']['min']} ~ ¥{comparison['price_range']['max']}")
    lines.append(f"📉 价格差异: ¥{comparison['price_range']['diff']}")
    lines.append(f"📊 平均价格: ¥{comparison['average_price']}")
    lines.append("")
    lines.append("📋 各平台详情:")
    lines.append("-" * 70)
    
    for result in comparison["all_results"]:
        platform = result["platform_name"]
        config = get_platform_config(result["platform_id"])
        icon = config.get("icon", "🛒")
        price = result["platform_price"]
        total = result["platform_price"] + result["shipping_fee"]
        stock = result["stock"]
        in_stock = "有货" if result["is_in_stock"] else "缺货"
        
        line = f"{icon} {platform:<10} ¥{price:<10}"
        if result["shipping_fee"] > 0:
            line += f" (+¥{result['shipping_fee']}运费 = ¥{total})"
        line += f" | 库存: {stock} | {in_stock}"
        lines.append(line)
    
    return "\n".join(lines)
