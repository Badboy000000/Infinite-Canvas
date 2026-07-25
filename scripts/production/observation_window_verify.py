"""observation_window_verify.py — Wave 3-N.11 Batch 10 · 观察窗口指标校验(只读)。

**只读**:读 audit 事件 sink · 打印当前 flag 观察窗口内的关键指标。**不写** DB · **不改** flag。

用法:
    # 单 flag(每日跑一次 · 输出存入 KB 翻转日志)
    python scripts/production/observation_window_verify.py --flag AUDIT_ENABLED
    python scripts/production/observation_window_verify.py --flag MINIO_SWITCHOVER_ENABLED --phase shadow
    python scripts/production/observation_window_verify.py --flag CSRF_ENABLED,CORS_STRICT_ENABLED

输出:
    - 关键指标当前值(如 identity_bridge_reject 数 · shadow_write 成功率)
    - 与该 flag runbook 的阈值对比
    - 是否可进入下一 flag 的判定

**硬约束**:本脚本不做任何 flag 翻转决策 · 只提供数据 · 拍板留给用户/运维。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List, Optional

# Windows GBK 兼容 · 强制 stdout/stderr 走 UTF-8
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

# --- 每个 flag 观察窗口的关键指标 + 通过阈值(骨架层已定) ---
_METRICS: Dict[str, List[Dict[str, object]]] = {
    "AUDIT_ENABLED": [
        {"name": "audit_sink_failed", "op": "==", "threshold": 0, "unit": "count/day"},
        {"name": "audit_event_total", "op": ">", "threshold": 10, "unit": "count/day",
         "note": "证明事件在流"},
        {"name": "audit_disk_daily_mb", "op": "<", "threshold": 100, "unit": "MB/day",
         "note": "警戒线"},
    ],
    "IDENTITY_BRIDGE_ENFORCE": [
        {"name": "identity_bridge_reject", "op": "<", "threshold": 10, "unit": "count/day",
         "note": "第 7 天应 <1"},
        {"name": "auth_login_success_rate", "op": ">=", "threshold": 0.99, "unit": "ratio"},
    ],
    "CSRF_ENABLED": [
        {"name": "csrf_reject", "op": "<", "threshold": 10, "unit": "count/day",
         "note": "第 7 天应 <1"},
    ],
    "CORS_STRICT_ENABLED": [
        {"name": "cors_block", "op": "<", "threshold": 10, "unit": "count/day",
         "note": "第 7 天应 <1"},
    ],
    "PERMISSION_ENFORCE": [
        {"name": "permission_denied_enforced", "op": "<", "threshold": 20, "unit": "count/day",
         "note": "逐日下降"},
        {"name": "admin_operation_success_rate", "op": "==", "threshold": 1.0, "unit": "ratio"},
    ],
    "RATE_LIMIT_ENABLED": [
        {"name": "rate_limit_exceeded_auth", "op": "reports_only", "threshold": None,
         "unit": "count/day", "note": "看是否有异常 ip"},
        {"name": "legitimate_user_429", "op": "==", "threshold": 0, "unit": "count/day"},
    ],
    "MINIO_SWITCHOVER_ENABLED": [
        {"name": "shadow_write_success_rate", "op": ">=", "threshold": 0.995, "unit": "ratio",
         "note": "shadow phase 通过阈值"},
        {"name": "dual_write_diff_ratio", "op": "<=", "threshold": 0.001, "unit": "ratio",
         "note": "dual_write phase 一致性"},
        {"name": "read_from_local_fallback_daily", "op": "reports_only", "threshold": None,
         "unit": "count/day", "note": "cutover 阶段应逐日归零"},
    ],
}


def _read_metric_sink(metrics_dir: Path, flag: str) -> Dict[str, float]:
    """读取观察指标 sink(骨架期是文件 / 生产可切 sqlite)· 返回最新值 dict。

    **骨架期实现**:只 print 无数据的提示 · 实际接入由生产切换 wave 时用户/运维接。
    """
    if not metrics_dir.exists():
        return {}
    # 骨架期:读 <metrics_dir>/<FLAG>.jsonl · 每行 {name, value, ts}
    result: Dict[str, float] = {}
    target = metrics_dir / f"{flag}.jsonl"
    if not target.exists():
        return result
    import json
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
            result[rec["name"]] = float(rec["value"])
        except (json.JSONDecodeError, KeyError, ValueError):
            continue
    return result


def _judge_metric(spec: Dict[str, object], value: Optional[float]) -> str:
    if value is None:
        return "?"
    op = spec["op"]
    if op == "reports_only":
        return "info"
    threshold = spec["threshold"]
    if threshold is None:
        return "info"
    threshold = float(threshold)  # type: ignore[arg-type]
    if op == "==":
        return "pass" if abs(value - threshold) < 1e-9 else "fail"
    if op == ">":
        return "pass" if value > threshold else "fail"
    if op == ">=":
        return "pass" if value >= threshold else "fail"
    if op == "<":
        return "pass" if value < threshold else "fail"
    if op == "<=":
        return "pass" if value <= threshold else "fail"
    return "?"


def _print_flag_verify(flag: str, metrics_dir: Path, phase: Optional[str]) -> int:
    spec_list = _METRICS.get(flag)
    if spec_list is None:
        print(f"[ERROR] 未知 flag: {flag}", file=sys.stderr)
        return 2

    values = _read_metric_sink(metrics_dir, flag)
    print()
    print("=" * 72)
    print(f"  Flag: {flag}{f' · phase={phase}' if phase else ''}")
    print("=" * 72)
    print(f"  指标 sink: {metrics_dir.resolve()}")
    print(f"  已读取指标: {len(values)}")

    any_fail = False
    for spec in spec_list:
        name = spec["name"]
        value = values.get(name)  # type: ignore[arg-type]
        verdict = _judge_metric(spec, value)
        mark = {"pass": "✓", "fail": "✗", "info": "ⓘ", "?": "?"}[verdict]
        threshold_str = "" if spec["threshold"] is None else f" (阈值 {spec['op']} {spec['threshold']})"
        value_str = "<无数据>" if value is None else f"{value}"
        note = spec.get("note", "")
        print(f"  {mark} {name} = {value_str}{threshold_str} · {spec['unit']}"
              f"{'  · ' + str(note) if note else ''}")
        if verdict == "fail":
            any_fail = True

    print()
    if any_fail:
        print("  ⚠️ 存在未达阈值的指标 · **不进入下一 flag** · 排查后再走")
    elif not values:
        print("  ⓘ 骨架期无真实指标数据 · 生产切换时用户/运维需接入 sink")
    else:
        print("  ✓ 全部关键指标通过 · 可考虑进入下一 flag(仍需人工确认)")
    return 1 if any_fail else 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="观察窗口指标校验(只读)")
    parser.add_argument("--flag", required=True, help="要校验的 flag · 多个用逗号分隔")
    parser.add_argument("--phase", default=None, help="MinIO switchover phase")
    parser.add_argument("--metrics-dir", default="./data/observation-metrics",
                        help="指标 sink 目录")
    args = parser.parse_args(argv)

    metrics_dir = Path(args.metrics_dir)
    print()
    print("╔" + "═" * 70 + "╗")
    print("║" + " Wave 3-N.11 · Observation Window Verify(只读)".center(70) + "║")
    print("╚" + "═" * 70 + "╝")

    exit_code = 0
    for flag in args.flag.split(","):
        flag = flag.strip().upper()
        rc = _print_flag_verify(flag, metrics_dir, args.phase)
        exit_code = max(exit_code, rc)

    print()
    print("─" * 72)
    print("  ⚠️ 本脚本 **不做决策** · 只提供指标数据 · 拍板由用户/运维")
    print("  ⚠️ 输出应记入 KB `70 开发过程跟踪/生产切换日志/` 当次翻转日志")
    print("─" * 72)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
