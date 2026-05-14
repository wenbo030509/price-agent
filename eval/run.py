#!/usr/bin/env python3
"""
eval/run.py — 评估主控脚本

按依赖层级依次执行各评估阶段，支持全量和增量执行。

层级定义：
  Level 0 — 无 LLM（毫秒·秒级，始终安全）
  Level 1 — 单次 LLM 调用（秒级）
  Level 2 — 多次 LLM 调用（分钟级，完整 Agent 循环）
  Level 3 — 后处理（汇总报告）

用法：
  python3 eval/run.py --all                     # 全量评估
  python3 eval/run.py --level 0                 # 仅无 LLM 的测试
  python3 eval/run.py --level 1                 # 无 LLM + 单次 LLM
  python3 eval/run.py --phase P2_e2e,P3_boundary  # 指定阶段
  python3 eval/run.py --skip P6_image           # 跳过特定阶段
  python3 eval/run.py --list                    # 列出所有阶段
"""

import sys
import os
import time
import subprocess
import json
import argparse
from datetime import datetime
from typing import Dict, List, Optional

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_DIR)

from eval_helpers import set_session_id, get_session_id, find_session_reports

# ══════════════════════════════════════════════════════════════════
# 阶段注册表
#
# 按执行依赖分组为 Level 0-3。新增评估只需在这里注册：
#   1. 写一个新 eval_xxx.py（独立可运行）
#   2. 在这里添加一条，指定 script / level / desc
#   3. 主控自动按 level 顺序调用，不需要修改其他代码
# ══════════════════════════════════════════════════════════════════

PHASES = {
    # ── Level 0: 无 LLM，始终安全 ──
    "P0_unit": {
        "script": "eval_p0_unit.py",
        "level": 0,
        "desc": "单元测试（DB CRUD / 属性匹配 / 并行查询 / Bug 回归）",
    },
    "IT3C_P0": {
        "script": "eval_it3c.py",
        "level": 0,
        "desc": "IT3C P0（语义过滤 / 意图分类 / 处理器别名 / M2 回归）",
        "args": [],
    },

    # ── Level 1: 单次 LLM 调用 ──
    "P1_parse": {
        "script": "eval_p1_parse.py",
        "level": 1,
        "desc": "属性提取（LLM 解析颜色/内存/别名）",
    },

    # ── Level 2: 多次 LLM 调用（完整 ReAct 循环）──
    "P2_e2e": {
        "script": "eval_p2_e2e.py",
        "level": 2,
        "desc": "端到端（ReAct + Plan-Execute 完整循环）",
    },
    "P3_boundary": {
        "script": "eval_p3_boundary.py",
        "level": 2,
        "desc": "能力边界（异常/歧义/矛盾/多轮对话）",
    },
    "P5_optimization": {
        "script": "eval_p5_optimization.py",
        "level": 2,
        "desc": "优化验证（自反思 / Prompt / 依赖注入 / 复杂度）",
    },
    "P6_image": {
        "script": "eval_p6_image.py",
        "level": 2,
        "desc": "图片搜索（工具注册 + 自动发现上传图片）",
    },
    "IT3C_all": {
        "script": "eval_it3c.py",
        "level": 2,
        "args": ["--all"],
        "desc": "IT3C 全量（含 P1 属性提取 + P2 推荐 E2E）",
    },

    # ── Level 3: 后处理 ──
    "P4_benchmark": {
        "script": "eval_p4_benchmark.py",
        "level": 3,
        "desc": "汇总报告（聚合本 session 内所有阶段结果）",
    },
}


def run_phase(phase_name: str, phase_cfg: dict, session_id: str) -> dict:
    """执行单个阶段，返回 {phase, success, duration_ms, exit_code}"""
    script_path = os.path.join(SCRIPT_DIR, phase_cfg["script"])
    extra_args = phase_cfg.get("args", [])

    cmd = [sys.executable, script_path] + extra_args
    env = os.environ.copy()
    env["EVAL_SESSION_ID"] = session_id

    print(f"\n{'─' * 65}")
    print(f"  ▶ {phase_name}: {phase_cfg['desc']}")
    print(f"  └─ {' '.join(cmd)}")
    print(f"{'─' * 65}")

    start = time.time()
    result = subprocess.run(cmd, cwd=PROJECT_DIR, env=env,
                            capture_output=True, text=True)
    elapsed_ms = int((time.time() - start) * 1000)

    success = result.returncode == 0
    stdout = result.stdout
    stderr = result.stderr

    if stderr:
        print(f"  stderr: {stderr[:500]}")

    # 提取最后的关键行打印
    last_lines = stdout.strip().split("\n")
    print("\n".join(last_lines[-15:]))

    return {
        "phase": phase_name,
        "success": success,
        "duration_ms": elapsed_ms,
        "exit_code": result.returncode,
    }


def run_p4_benchmark(session_id: str) -> dict:
    """P4 汇总报告：从 session 结果聚合"""
    print(f"\n{'─' * 65}")
    print(f"  ▶ P4_benchmark: 汇总报告")
    print(f"{'─' * 65}")

    reports = find_session_reports(session_id)
    if not reports:
        print("  ✗ 未找到本 session 的评估报告")
        return {"phase": "P4_benchmark", "success": False, "exit_code": 1}

    print(f"  读取 {len(reports)} 个报告: {list(reports.keys())}")

    from eval_helpers import load_report
    all_cases = []
    by_phase = {}
    total = 0
    total_passed = 0

    for phase_name, filepath in reports.items():
        if "benchmark" in phase_name.lower() or "P4" in phase_name:
            continue
        try:
            r = load_report(filepath)
        except Exception:
            with open(filepath, "r", encoding="utf-8") as f:
                r = json.load(f)

        n_total = r.get("total", len(r.get("cases", [])))
        n_passed = r.get("passed", 0)
        by_phase[phase_name] = {
            "total": n_total,
            "passed": n_passed,
            "failed": n_total - n_passed,
            "pass_rate": r.get("pass_rate", "N/A"),
            "duration_ms": r.get("duration_ms", 0),
        }
        total += n_total
        total_passed += n_passed

        for c in r.get("cases", []):
            c["_phase"] = phase_name
            all_cases.append(c)

    scorable = [c for c in all_cases
                if not c.get("details", {}).get("skipped")
                and not c.get("details", {}).get("manual_review")]
    scored_passed = sum(1 for c in scorable if c.get("passed"))

    report = {
        "timestamp": datetime.now().isoformat(),
        "session_id": session_id,
        "summary": {
            "total_cases": len(all_cases),
            "scorable_cases": len(scorable),
            "passed": scored_passed,
            "failed": len(scorable) - scored_passed,
            "pass_rate": f"{scored_passed / len(scorable) * 100:.1f}%" if scorable else "N/A",
        },
        "by_phase": by_phase,
    }

    os.makedirs("eval/results", exist_ok=True)
    filename = f"eval/results/{session_id}_P4_benchmark.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\n{'=' * 60}")
    print("  综合评估报告")
    print(f"{'=' * 60}")
    print(f"  Session: {session_id}")
    print(f"  总 case: {len(all_cases)} | 可评分: {len(scorable)} | 通过: {scored_passed}")
    print(f"  综合通过率: {report['summary']['pass_rate']}")
    print(f"\n  各阶段：")
    for phase_name in sorted(by_phase.keys()):
        p = by_phase[phase_name]
        print(f"    {phase_name}: {p['pass_rate']} ({p['passed']}/{p['total']})")
    print(f"  报告已保存: {filename}")

    return {"phase": "P4_benchmark", "success": True, "exit_code": 0}


def list_phases():
    """打印所有注册阶段"""
    print("注册的评估阶段（按 Level 分组）：\n")
    for level in range(4):
        phases = [(n, c) for n, c in PHASES.items() if c["level"] == level]
        if not phases:
            continue
        print(f"  Level {level}:")
        for name, cfg in phases:
            print(f"    {name:<20s}  {cfg['desc']}")
        print()


def main():
    parser = argparse.ArgumentParser(
        description="评估主控脚本 — 按依赖层级依次执行评估阶段")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--all", action="store_true", help="全量评估（Level 0→3）")
    group.add_argument("--level", type=int, choices=[0, 1, 2, 3],
                       help="执行到指定层级（如 --level 1 = Level 0+1）")
    group.add_argument("--phase", type=str,
                       help="指定阶段，逗号分隔（如 P2_e2e,P3_boundary）")
    group.add_argument("--list", action="store_true", help="列出所有阶段")

    parser.add_argument("--skip", type=str,
                        help="跳过的阶段，逗号分隔（如 P6_image）")
    parser.add_argument("--session", type=str,
                        help="使用指定 session ID（默认自动生成）")

    args = parser.parse_args()

    if args.list:
        list_phases()
        return

    # 确定执行阶段列表
    if args.all:
        selected = [n for n in PHASES if n != "IT3C_P0"]  # IT3C_all 已含 P0
    elif args.level is not None:
        selected = [n for n, c in PHASES.items() if c["level"] <= args.level]
    elif args.phase:
        selected = [p.strip() for p in args.phase.split(",") if p.strip() in PHASES]
        unknown = [p.strip() for p in args.phase.split(",") if p.strip() not in PHASES]
        if unknown:
            print(f"✗ 未知阶段: {unknown}")
            list_phases()
            return
    else:
        print("请指定 --all / --level / --phase，或 --list 查看可用阶段")
        return

    # 跳过指定阶段
    skip_set = set(s.strip() for s in (args.skip or "").split(",") if s.strip())
    selected = [s for s in selected if s not in skip_set]

    # P4 总是在最后追加（如不在 skip 中且不在 selected 中）
    if "P4_benchmark" not in skip_set and "P4_benchmark" not in selected:
        selected.append("P4_benchmark")

    if not selected:
        print("✗ 没有可执行的阶段")
        return

    # 按 level 排序
    selected.sort(key=lambda n: PHASES[n]["level"])

    # Session 初始化
    session_id = args.session or datetime.now().strftime("%Y%m%d_%H%M%S")
    set_session_id(session_id)

    print("=" * 65)
    print(f"  评估 Session: {session_id}")
    print(f"  阶段: {', '.join(selected)}")
    print(f"  共 {len(selected)} 个阶段")
    print("=" * 65)

    results = []
    overall_start = time.time()

    for phase_name in selected:
        cfg = PHASES[phase_name]

        if phase_name == "P4_benchmark":
            res = run_p4_benchmark(session_id)
        else:
            res = run_phase(phase_name, cfg, session_id)
        results.append(res)

    total_elapsed = int((time.time() - overall_start) * 1000)

    # ── 最终汇总 ──
    print(f"\n{'=' * 65}")
    print("  执行完成")
    print(f"{'=' * 65}")
    print(f"  Session: {session_id}")
    print(f"  总耗时: {total_elapsed}ms")

    passed = sum(1 for r in results if r["success"])
    failed = len(results) - passed
    for r in results:
        status = "✓" if r["success"] else "✗"
        print(f"    {status} {r['phase']}: {r.get('duration_ms', 0)}ms (exit={r.get('exit_code', '?')})")

    print(f"\n  阶段通过: {passed}/{len(results)}")
    if failed > 0:
        failed_names = [r["phase"] for r in results if not r["success"]]
        print(f"  失败阶段: {', '.join(failed_names)}")

    print(f"\n  结果文件目录: eval/results/{session_id}_*.json")


if __name__ == "__main__":
    main()
