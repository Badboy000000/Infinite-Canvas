"""dry_run_flag_flip.py — Wave 3-N.11 Batch 10 · 生产切换 flag 翻转 dry-run。

**只读**:打印翻转计划 + 前置条件检查 + 影响面 · **不改** .env · **不重启** app · **不调** MinIO / DB。

用法:
    python scripts/production/dry_run_flag_flip.py --flag AUDIT_ENABLED
    python scripts/production/dry_run_flag_flip.py --flag MINIO_SWITCHOVER_ENABLED --phase shadow
    python scripts/production/dry_run_flag_flip.py --flag CSRF_ENABLED,CORS_STRICT_ENABLED
    python scripts/production/dry_run_flag_flip.py --flag MINIO_SWITCHOVER_ENABLED --rollback-plan

Lead 交付 · 由用户/运维在生产切换 D-day 前一天跑 · 得到:
    1. 翻转前后 flag 值对比
    2. 骨架依赖检查(前置 flag 是否已开)
    3. 影响面报告(哪些 endpoint / 模块 / audit 事件受影响)
    4. 观察窗口指标预期
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

# Windows GBK 兼容 · 强制 stdout/stderr 走 UTF-8(生产切换 log 里会有 ✓✗⚠️ 等符号)
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

# --- Flag 元数据(骨架层已定) ---
_FLAG_META: Dict[str, Dict[str, object]] = {
    "AUDIT_ENABLED": {
        "runbook": "docs/runbooks/05-audit-enable.md",
        "depends_on": [],
        "affected_modules": ["app.security.audit_policy"],
        "observation_days": 7,
        "rollback_cost_minutes": 0,  # 立即
        "rollback_note": "flag off · 已入库事件保留",
    },
    "IDENTITY_BRIDGE_ENFORCE": {
        "runbook": "docs/runbooks/02-identity-bridge-enforce.md",
        "depends_on": ["AUDIT_ENABLED"],
        "affected_modules": ["IdentityBridgeMiddleware", "app.api.context"],
        "observation_days": 7,
        "rollback_cost_minutes": 5,
        "rollback_note": "flag off + 重启",
    },
    "CSRF_ENABLED": {
        "runbook": "docs/runbooks/03-csrf-cors-enable.md",
        "depends_on": ["AUDIT_ENABLED", "RATE_LIMIT_ENABLED"],
        "affected_modules": ["app.security.csrf_policy"],
        "observation_days": 7,
        "rollback_cost_minutes": 5,
        "rollback_note": "flag off + 重启",
    },
    "CORS_STRICT_ENABLED": {
        "runbook": "docs/runbooks/03-csrf-cors-enable.md",
        "depends_on": ["AUDIT_ENABLED"],
        "affected_modules": ["app.security.csp", "CORS middleware"],
        "observation_days": 7,
        "rollback_cost_minutes": 5,
        "rollback_note": "flag off + 重启",
    },
    "PERMISSION_ENFORCE": {
        "runbook": "docs/runbooks/04-permission-enforce.md",
        "depends_on": ["AUDIT_ENABLED", "IDENTITY_BRIDGE_ENFORCE", "CSRF_ENABLED"],
        "affected_modules": ["require_permission dep", "app.services.auth"],
        "observation_days": 7,
        "rollback_cost_minutes": 5,
        "rollback_note": "flag off + 重启",
    },
    "RATE_LIMIT_ENABLED": {
        "runbook": "docs/runbooks/06-rate-limit-enable.md",
        "depends_on": ["AUDIT_ENABLED", "PERMISSION_ENFORCE"],
        "affected_modules": ["app.security.rate_limit_policy"],
        "observation_days": 7,
        "rollback_cost_minutes": 5,
        "rollback_note": "flag off + 重启",
    },
    "MINIO_SWITCHOVER_ENABLED": {
        "runbook": "docs/runbooks/01-minio-switchover.md",
        "depends_on": [
            "AUDIT_ENABLED", "IDENTITY_BRIDGE_ENFORCE", "CSRF_ENABLED",
            "PERMISSION_ENFORCE", "RATE_LIMIT_ENABLED",
        ],
        "affected_modules": [
            "app.services.files.minio_switchover",
            "app.adapters.storage.minio_adapter",
        ],
        "observation_days": 28,  # 4 phase × 7
        "rollback_cost_minutes": 5,  # shadow / dual_write · cutover 需 rollback plan
        "rollback_note": "shadow/dual_write=5min · cutover 需 rollback plan",
    },
}


def _read_current_env(env_path: Path) -> Dict[str, str]:
    """读取 .env · 返回 dict(不修改文件)。"""
    result: Dict[str, str] = {}
    if not env_path.exists():
        return result
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        result[k.strip()] = v.strip()
    return result


def _flag_is_on(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _print_flag_report(flag: str, env: Dict[str, str], phase: Optional[str], rollback: bool) -> int:
    meta = _FLAG_META.get(flag)
    if meta is None:
        print(f"[ERROR] 未知 flag: {flag}", file=sys.stderr)
        print(f"支持的 flag: {', '.join(_FLAG_META.keys())}", file=sys.stderr)
        return 2

    print()
    print("=" * 72)
    print(f"  Flag: {flag}")
    print("=" * 72)
    print(f"  当前值: {env.get(flag, '<未设置>')}")
    print(f"  目标值: {'off (rollback)' if rollback else 'on'}")
    if flag == "MINIO_SWITCHOVER_ENABLED" and phase:
        print(f"  Phase: {phase}")
    print(f"  Runbook: {meta['runbook']}")
    print(f"  观察窗口: {meta['observation_days']} 天")
    print(f"  回滚代价: {meta['rollback_cost_minutes']} 分钟 · {meta['rollback_note']}")

    # 前置依赖检查
    depends_on = meta["depends_on"]  # type: ignore[index]
    if depends_on and not rollback:
        print()
        print("  --- 前置依赖检查 ---")
        for dep in depends_on:  # type: ignore[union-attr]
            dep_val = env.get(dep, "")
            ok = _flag_is_on(dep_val)
            mark = "✓" if ok else "✗"
            print(f"  {mark} {dep}={dep_val or '<未设置>'} {'(已启用)' if ok else '(未启用 · 应先启用它)'}")
        missing = [d for d in depends_on if not _flag_is_on(env.get(d, ""))]  # type: ignore[union-attr]
        if missing:
            print()
            print(f"  ⚠️ 缺失前置 flag: {missing}")
            print(f"  ⚠️ 建议先按顺序启用它们 · 参考 docs/runbooks/README.md")

    # 影响面
    print()
    print("  --- 影响面 ---")
    print(f"  受影响模块: {meta['affected_modules']}")

    # rollback plan(仅 MinIO cutover)
    if rollback and flag == "MINIO_SWITCHOVER_ENABLED":
        print()
        print("  --- Rollback Plan(cutover 阶段专用)---")
        print("  1. .env: MINIO_SWITCHOVER_PHASE=rollback + STORAGE_BACKEND=local")
        print("  2. 重启 app · 主写立即回 local")
        print("  3. 从 MinIO 搬回灰度期新增文件(手动 · Lead 不代执行)")
        print("  4. 搬运完成后 MINIO_SWITCHOVER_ENABLED=off · 重启")
        print("  5. 到骨架期 default")

    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Dry-run production flag flip planner (只读)")
    parser.add_argument("--flag", required=True, help="要翻转的 flag · 多个用逗号分隔")
    parser.add_argument("--phase", default=None, help="MinIO switchover phase(shadow/dual_write/cutover/rollback)")
    parser.add_argument("--rollback-plan", action="store_true", help="打印回滚计划")
    parser.add_argument("--env", default=".env", help=".env 路径 · 默认 ./.env")
    args = parser.parse_args(argv)

    env_path = Path(args.env)
    env = _read_current_env(env_path)

    print()
    print("╔" + "═" * 70 + "╗")
    print("║" + " Wave 3-N.11 · Production Flag Flip Dry-Run(只读)".center(70) + "║")
    print("╚" + "═" * 70 + "╝")
    print(f"  .env 路径: {env_path.resolve()}")
    print(f"  .env 存在: {env_path.exists()}")
    print(f"  DEPLOY_MODE: {env.get('DEPLOY_MODE', '<未设置>')}")

    exit_code = 0
    for flag in args.flag.split(","):
        flag = flag.strip().upper()
        rc = _print_flag_report(flag, env, args.phase, args.rollback_plan)
        exit_code = max(exit_code, rc)

    print()
    print("─" * 72)
    print("  ⚠️ 本脚本 **不修改** .env · **不重启** app · **不调** MinIO/DB")
    print("  ⚠️ 真正翻转由用户/运维手动改 .env 后 docker compose restart")
    print("  ⚠️ 每 flag 翻转后须走 observation_window_verify.py 7 天观察")
    print("─" * 72)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
