"""
多平台并行查询Agent
支持同时从多个平台查询商品数据并汇总结果
"""
import os
import pickle
import hashlib
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
        processor_brand: Optional[str] = None,
        processor_hint: Optional[str] = None,
        use_case: Optional[str] = None,
        performance_tier: Optional[str] = None,
        budget_max: Optional[float] = None,
        budget_min: Optional[float] = None,
    ) -> List[Dict]:
        """按属性查询所有匹配商品（模糊查询用，6 维评分）"""
        with self._lock:
            try:
                return self.db.query_products_by_attrs(
                    product_name=product_name,
                    color=color,
                    memory=memory,
                    processor_brand=processor_brand,
                    processor_hint=processor_hint,
                    use_case=use_case,
                    performance_tier=performance_tier,
                    budget_max=budget_max,
                    budget_min=budget_min,
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
        processor_brand: Optional[str] = None,
        processor_hint: Optional[str] = None,
        use_case: Optional[str] = None,
        performance_tier: Optional[str] = None,
        budget_max: Optional[float] = None,
        budget_min: Optional[float] = None,
        timeout: int = 10
    ) -> Dict:
        """
        比价查询：在所有平台并行查询，返回各平台所有匹配商品及比价分析。
        支持 IT3C 全量属性过滤（处理器/场景/预算/性能层级）。
        """
        executor = self._get_executor()
        futures = {}

        for platform_id, agent in self.agents.items():
            future = executor.submit(
                agent.query_products_by_attrs,
                product_name,
                color=color,
                memory=memory,
                processor_brand=processor_brand,
                processor_hint=processor_hint,
                use_case=use_case,
                performance_tier=performance_tier,
                budget_max=budget_max,
                budget_min=budget_min,
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


# ── Embedding 预热（M2）─────────────────────────────────────────────────

# 商品名 → embedding 向量缓存
_product_embedding_cache: Dict[str, any] = {}

# embedding 持久化缓存文件
_EMBEDDING_CACHE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "embeddings_cache.pkl")


def _product_fingerprint(product: dict, fields: List[str]) -> int:
    """计算商品 embedding 文本的哈希指纹，用于检测内容变化"""
    from tools.semantic_search_tool import build_product_text
    text = build_product_text(product, fields)
    return int(hashlib.md5(text.encode("utf-8")).hexdigest(), 16) % (2 ** 63)


def _load_embedding_cache() -> Dict:
    """从磁盘加载持久化的 embedding 缓存"""
    if not os.path.exists(_EMBEDDING_CACHE_FILE):
        return {}
    try:
        with open(_EMBEDDING_CACHE_FILE, "rb") as f:
            cached = pickle.load(f)
        return cached or {}
    except Exception:
        return {}


def _save_embedding_cache(cache: dict):
    """将 embedding 缓存持久化到磁盘"""
    try:
        with open(_EMBEDDING_CACHE_FILE, "wb") as f:
            pickle.dump(cache, f)
    except Exception as e:
        print(f"[Embedding] 缓存保存失败: {e}")


def init_product_embeddings(industry_config: dict, embedding_client):
    """
    对所有平台的商品预计算 embedding 并缓存。
    首次运行全量计算并持久化；后续只对新增/变更商品做增量更新。
    """
    import numpy as np
    from tools.semantic_search_tool import build_product_text

    embedding_fields = industry_config.get("embedding_fields", [])
    if not embedding_fields:
        return

    agent = PlatformParallelAgent()
    result = agent.query_all_products_parallel()

    all_products = []
    for platform_id, data in result.get("results", {}).items():
        platform_name = data.get("platform_name", platform_id)
        for p in data.get("products", []):
            p["_platform_name"] = platform_name
            all_products.append(p)

    if not all_products:
        return

    # 1. 加载已有缓存
    cached = _load_embedding_cache()
    global _product_embedding_cache

    # 2. 计算每个商品的指纹，找出新增/变更的商品
    current_fingerprints = {}
    to_embed = []
    reused = 0

    for p in all_products:
        name = p.get("product_name", "")
        if not name:
            continue
        fp = _product_fingerprint(p, embedding_fields)
        current_fingerprints[name] = fp

        if name in cached and cached[name].get("fingerprint") == fp:
            # 缓存命中，直接复用
            _product_embedding_cache[name] = cached[name]["embedding"]
            reused += 1
        else:
            # 新增或内容变更，需要重新计算
            to_embed.append(p)

    # 3. 只对需要更新的商品计算 embedding
    if to_embed:
        texts = [build_product_text(p, embedding_fields) for p in to_embed]
        embeddings = embedding_client.embed_texts(texts)
        for product, emb in zip(to_embed, embeddings):
            name = product.get("product_name", "")
            if name:
                vec = np.array(emb, dtype=np.float32)
                _product_embedding_cache[name] = vec
                cached[name] = {
                    "embedding": vec,
                    "fingerprint": current_fingerprints[name],
                }
        print(f"[Embedding] 增量更新 {len(to_embed)} 个商品")

    # 4. 清理缓存中已删除的商品
    current_names = set(current_fingerprints.keys())
    stale = [n for n in cached if n not in current_names]
    for n in stale:
        del cached[n]

    # 5. 持久化
    _save_embedding_cache(cached)

    print(f"[Embedding] 缓存就绪: {reused} 复用 + {len(to_embed)} 新算 = {len(_product_embedding_cache)} 个向量")


def get_cached_embedding(product_name: str):
    """获取预热的 embedding 向量，未命中返回 None"""
    return _product_embedding_cache.get(product_name)


# ── 比价结果格式化 ─────────────────────────────────────────────────────

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
