"""
AB Test Demo — 工具包
导入所有工具模块以触发 @register_tool 装饰器注册。
导出 TOOL_SCHEMAS 和 TOOL_MAP，与 price-agent tools/ 接口一致。
"""

from .registry import tool_registry

# 导入所有工具模块 → 触发 @register_tool 注册
from . import experiment_list       # get_experiment_list
from . import experiment_overview   # get_experiment_overview
from . import experiment_detail     # get_experiment_detail
from . import statistical_test      # run_statistical_test
from . import multi_metric_check    # run_multi_metric_check
from . import segment_consistency   # check_segment_consistency
from . import strategy_decision     # make_strategy_decision
from . import daily_trend           # get_daily_trend

TOOL_SCHEMAS = tool_registry.get_schemas()
TOOL_MAP = tool_registry.get_tool_map()
