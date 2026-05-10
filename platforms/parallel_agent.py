"""
多平台并行查询Agent
支持同时从多个平台查询商品数据并汇总结果
"""
import concurrent.futures
import threading
from typing import List, Dict, Optional
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

    def query_product_by_attrs(
        self,
        product_name: str,
        color: Optional[str] = None,
        memory: Optional[str] = None,
    ) -> Optional[Dict]:
        """按属性查询单个商品"""
        with self._lock:
            try:
                return self.db.query_product_by_attrs(
                    product_name=product_name,
                    color=color,
                    memory=memory,
                )
            except Exception as e:
                print(f"⚠️  {self.config['name']}查询出错: {e}")
                return None

    def query_products_by_attrs(
        self,
        product_name: str,
        color: Optional[str] = None,
        memory: Optional[str] = None,
    ) -> List[Dict]:
        """按属性查询所有匹配商品（模糊查询用）"""
        with self._lock:
            try:
                return self.db.query_products_by_attrs(
                    product_name=product_name,
                    color=color,
                    memory=memory,
                )
            except Exception as e:
                print(f"⚠️  {self.config['name']}查询出错: {e}")
                return []

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
    
    def compare_product_price(
        self,
        product_name: str,
        color: Optional[str] = None,
        memory: Optional[str] = None,
        timeout: int = 10
    ) -> Dict:
        """
        比价查询：在所有平台并行查询，返回各平台所有匹配商品及比价分析。
        模糊查询时会返回该平台所有候选商品。
        """
        executor = self._get_executor()
        futures = {}

        for platform_id, agent in self.agents.items():
            future = executor.submit(
                agent.query_products_by_attrs,
                product_name,
                color=color,
                memory=memory,
            )
            futures[future] = platform_id

        platform_results = {}
        errors = {}

        for future in concurrent.futures.as_completed(futures, timeout=timeout):
            platform_id = futures[future]
            try:
                matches = future.result()
                if matches:
                    platform_results[platform_id] = matches
            except concurrent.futures.TimeoutError:
                errors[platform_id] = "查询超时"
            except Exception as e:
                errors[platform_id] = str(e)

        # 汇总所有匹配商品
        all_matches = []
        for matches in platform_results.values():
            all_matches.extend(matches)

        if not all_matches:
            return {
                "product_name": product_name,
                "found": False,
                "message": "在所有平台都未找到该商品"
            }

        # 按匹配分数降序、总价升序排列（高分完全匹配优先）
        all_matches.sort(key=lambda x: (-x.get("_match_score", 0), x["platform_price"] + x["shipping_fee"]))
        cheapest = all_matches[0]
        # 最贵/最便宜按实际总价独立计算
        actual_cheapest = min(all_matches, key=lambda x: x["platform_price"] + x["shipping_fee"])
        actual_most_expensive = max(all_matches, key=lambda x: x["platform_price"] + x["shipping_fee"])
        avg_price = sum(m["platform_price"] for m in all_matches) / len(all_matches)

        return {
            "product_name": product_name,
            "found": True,
            "total_matches": len(all_matches),
            "platform_count": len(platform_results),
            "platform_results": platform_results,
            "all_matches": all_matches,
            "cheapest": cheapest,
            "most_expensive": actual_most_expensive,
            "average_price": round(avg_price, 2),
            "price_range": {
                "min": actual_cheapest["platform_price"] + actual_cheapest["shipping_fee"],
                "max": actual_most_expensive["platform_price"] + actual_most_expensive["shipping_fee"],
                "diff": round(
                    (actual_most_expensive["platform_price"] + actual_most_expensive["shipping_fee"]) -
                    (actual_cheapest["platform_price"] + actual_cheapest["shipping_fee"]), 2
                )
            }
        }
    
    def _summarize_results(self, results: Dict) -> Dict:
        """汇总查询结果"""
        found_count = sum(1 for r in results.values() if r.get("found", False) and "price" in r)
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
    product_name = comparison["product_name"]
    total = comparison["total_matches"]
    cheapest = comparison["cheapest"]
    price_range = comparison["price_range"]

    # 标题和一句话结论
    lines.append(f"📊 {product_name} 比价结果")
    lines.append("")

    cheapest_total = cheapest["platform_price"] + cheapest["shipping_fee"]
    lines.append(
        f"🏆 最划算：{cheapest['platform_name']} ¥{cheapest['platform_price']}"
    )
    if cheapest["shipping_fee"] > 0:
        lines[-1] += f"（含运费 ¥{cheapest['shipping_fee']}，合计 ¥{cheapest_total}）"
    lines.append(f"   库存 {cheapest['stock']} 件 | 颜色 {cheapest.get('color', '-')} | 内存 {cheapest.get('memory', '-')}")

    # 各平台匹配商品
    platform_results = comparison.get("platform_results", {})
    # 按最便宜平台排
    sorted_platforms = sorted(
        platform_results.items(),
        key=lambda kv: min(m["platform_price"] + m["shipping_fee"] for m in kv[1])
    )

    for platform_id, matches in sorted_platforms:
        if not matches:
            continue
        config = get_platform_config(platform_id)
        icon = config.get("icon", "🛒")
        name = config.get("name", platform_id)

        if len(matches) == 1:
            m = matches[0]
            ship = f" +运费¥{m['shipping_fee']}" if m["shipping_fee"] > 0 else ""
            lines.append(
                f"  {icon} {name:<6} ¥{m['platform_price']:<8}{ship}  "
                f"库存{m['stock']} | {m.get('color','-')}/{m.get('memory','-')}"
            )
        else:
            lines.append(f"  {icon} {name}（{len(matches)} 个匹配）")
            for m in matches[:5]:  # 最多展示 5 个
                ship = f" +运费¥{m['shipping_fee']}" if m["shipping_fee"] > 0 else ""
                lines.append(
                    f"     ¥{m['platform_price']:<8} {m['product_name']}{ship}"
                )
            if len(matches) > 5:
                lines.append(f"     ... 还有 {len(matches) - 5} 个匹配")

    lines.append("")
    lines.append(
        f"💰 共 {total} 个匹配 | "
        f"均价 ¥{comparison['average_price']} | "
        f"价差 ¥{price_range['diff']} "
        f"（¥{price_range['min']} ~ ¥{price_range['max']}）"
    )

    return "\n".join(lines)
