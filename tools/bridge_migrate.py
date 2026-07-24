#!/usr/bin/env python3
"""`bridge_migrate.py` — 权限 PR-9 IdentityBridge 数据承接 CLI(Wave 3-N.9 Batch 2 主线 B)。

**定位**:扫描 legacy 数据资源(画布 / 素材库)· 用 `IdentityBridge` 尝试把
`owner` / `legacy_owner_label` 弱语义字符串 → `user_id` UUID · 输出影子映射
状态到 `data/identity/bridge_state.json` · **不改任何原始资源文件**。

三档子命令:
- `--dry-run`:只输出映射矩阵(matched / unmatched / conflicts)· 不写盘
- `--apply`:把成功映射的 user_id 影子写入 `data/identity/bridge_state.json`
  (幂等 · 重复调用产生字节相同文件)
- `--report`:从 `bridge_state.json` 生成对账报告(总数 / 分布 / 未匹配列表)

**幂等保证**:相同数据源多次 `--apply` 生成的 `bridge_state.json` 内容字节相同
(`json.dumps(sort_keys=True, indent=2)` + 尾随换行)。

**对齐**:
- [[40 实施计划/用户团队权限治理实施计划与PR清单]] PR-9 数据承接
- [[50 决策记录/决策 - 主键类型]]
- 复用 `app.identity.bridge.IdentityBridge` + `app.identity.legacy_mapper` 纯函数

**明确不做**:
- 不改原始画布 / 素材 / 项目 JSON 文件的 `owner` 字段(遵循 PR-2 legacy_mapper 的
  "不删除任何旧字段" 约束)
- 不触发 audit(CLI 无 request 上下文 · audit 由运行时 middleware 承接)
- 不调用真实网络 / DB(纯本地文件操作)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

# 允许作为脚本从项目根目录运行
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.identity.bridge import BridgeResolution, IdentityBridge  # noqa: E402
from app.identity.request_context import RequestContext  # noqa: E402
from app.identity.store import JsonIdentityStore  # noqa: E402

DEFAULT_IDENTITY_DIR = _ROOT / "data" / "identity"
DEFAULT_BRIDGE_STATE_FILE = DEFAULT_IDENTITY_DIR / "bridge_state.json"
DEFAULT_CANVAS_DIR = _ROOT / "data" / "canvases"
DEFAULT_ASSET_LIBRARY_FILE = _ROOT / "data" / "asset_library.json"

BRIDGE_STATE_SCHEMA_VERSION = "v1_bridge"


# ---------------------------------------------------------------------------
# 扫描:资源 → owner_hint 元组列表
# ---------------------------------------------------------------------------


def _iter_canvas_owners(canvas_dir: Path) -> Iterable[Tuple[str, str, Optional[str]]]:
    """遍历 `data/canvases/*.json` · yield (resource_type, resource_id, owner_hint)。

    - resource_type 恒 `"canvas"`
    - resource_id 取文件名(去 .json)
    - owner_hint 取 record 里的 `owner` 或 `legacy_owner_label` · 均无则 None
    """
    if not canvas_dir.is_dir():
        return
    for p in sorted(canvas_dir.glob("*.json")):
        try:
            payload = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        canvas_id = payload.get("id") or p.stem
        owner = payload.get("owner") or payload.get("legacy_owner_label")
        yield ("canvas", str(canvas_id), owner if isinstance(owner, str) else None)


def _iter_asset_owners(asset_file: Path) -> Iterable[Tuple[str, str, Optional[str]]]:
    """遍历 `data/asset_library.json` · yield (resource_type, resource_id, owner_hint)。

    asset_library 结构宽松 · 尝试多种可能的 shape:
    - top-level `assets: [ {id, owner, ...} ]`
    - top-level `library: { <id>: {owner, ...} }`
    - top-level dict of `<id>: {owner, ...}`
    """
    if not asset_file.is_file():
        return
    try:
        payload = json.loads(asset_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return

    def _yield_from_list(items: List[Any]) -> Iterable[Tuple[str, str, Optional[str]]]:
        for entry in items:
            if not isinstance(entry, dict):
                continue
            asset_id = entry.get("id")
            if asset_id is None:
                continue
            owner = entry.get("owner") or entry.get("legacy_owner_label")
            yield ("asset", str(asset_id), owner if isinstance(owner, str) else None)

    def _yield_from_map(m: Dict[str, Any]) -> Iterable[Tuple[str, str, Optional[str]]]:
        for aid, entry in m.items():
            if not isinstance(entry, dict):
                continue
            owner = entry.get("owner") or entry.get("legacy_owner_label")
            yield ("asset", str(aid), owner if isinstance(owner, str) else None)

    if isinstance(payload, dict):
        if isinstance(payload.get("assets"), list):
            yield from _yield_from_list(payload["assets"])
        elif isinstance(payload.get("library"), dict):
            yield from _yield_from_map(payload["library"])
        else:
            # 顶层 dict of id → entry
            yield from _yield_from_map(payload)
    elif isinstance(payload, list):
        yield from _yield_from_list(payload)


def scan_resources(
    *,
    canvas_dir: Path = DEFAULT_CANVAS_DIR,
    asset_file: Path = DEFAULT_ASSET_LIBRARY_FILE,
) -> List[Tuple[str, str, Optional[str]]]:
    """把画布 + 素材库的 owner 线索汇集为 `(resource_type, resource_id, owner)` 列表。"""
    results: List[Tuple[str, str, Optional[str]]] = []
    results.extend(_iter_canvas_owners(canvas_dir))
    results.extend(_iter_asset_owners(asset_file))
    return results


# ---------------------------------------------------------------------------
# 解析:owner_hint → BridgeResolution
# ---------------------------------------------------------------------------


def _make_ctx_for_owner(owner_hint: Optional[str]) -> RequestContext:
    """构造 legacy_alias 语义的 RequestContext · 供 IdentityBridge.resolve 消费。"""
    return RequestContext(
        request_id="bridge-migrate-cli",
        legacy_user_key=owner_hint,
        x_user_id=None,
        workspace_id=None,
        project_id=None,
        client_id=None,
        ip=None,
        user_agent="bridge_migrate.py",
        auth_mode="legacy_alias" if owner_hint else "anonymous_or_legacy",
    )


def build_resolution_matrix(
    bridge: IdentityBridge,
    resources: Iterable[Tuple[str, str, Optional[str]]],
) -> Dict[str, Dict[str, Any]]:
    """对每个 (type, id, owner) 三元组调用 `bridge.resolve` · 汇集矩阵。

    返回:`{ "<type>:<id>": {"owner": ..., "user_id": ..., "kind": ...,
    "fallback_reason": ...} }`
    """
    matrix: Dict[str, Dict[str, Any]] = {}
    for rtype, rid, owner in resources:
        ctx = _make_ctx_for_owner(owner)
        resolution: BridgeResolution = bridge.resolve(ctx)
        key = f"{rtype}:{rid}"
        matrix[key] = {
            "owner": owner,
            "user_id": resolution.user_id,
            "kind": resolution.kind,
            "fallback_reason": resolution.fallback_reason,
        }
    return matrix


# ---------------------------------------------------------------------------
# 持久化:bridge_state.json 稳定序列化
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_bridge_state(state_file: Path) -> Dict[str, Any]:
    """读 bridge_state.json · 缺失或非法回退空模板(不 raise)。"""
    if not state_file.is_file():
        return {"_schema_version": BRIDGE_STATE_SCHEMA_VERSION, "resolutions": {}}
    try:
        payload = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"_schema_version": BRIDGE_STATE_SCHEMA_VERSION, "resolutions": {}}
    if not isinstance(payload, dict):
        return {"_schema_version": BRIDGE_STATE_SCHEMA_VERSION, "resolutions": {}}
    payload.setdefault("_schema_version", BRIDGE_STATE_SCHEMA_VERSION)
    payload.setdefault("resolutions", {})
    return payload


def write_bridge_state(state_file: Path, payload: Dict[str, Any]) -> None:
    """稳定序列化写入 · 多次相同内容产生字节相同文件。"""
    state_file.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    tmp = state_file.with_suffix(state_file.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
        fh.write("\n")
    tmp.replace(state_file)


def apply_matrix_to_state(
    state: Dict[str, Any],
    matrix: Dict[str, Dict[str, Any]],
    *,
    timestamp: Optional[str] = None,
) -> Dict[str, Any]:
    """把成功映射(user_id 非 None)的条目**幂等**写入 state。

    - 已有 key 且 user_id 相同 → matched_at 保持原值(**幂等** · 不刷新时间戳)
    - 已有 key 但 user_id 变了 → 覆盖(以最新 resolve 为准) · matched_at 更新
    - 无 key 且 user_id 非 None → 新增 · matched_at = timestamp or now

    未匹配条目**不写入** state · 避免污染。
    """
    if timestamp is None:
        timestamp = _now_iso()
    resolutions = state.setdefault("resolutions", {})
    for key, entry in matrix.items():
        user_id = entry.get("user_id")
        if not user_id:
            continue
        existing = resolutions.get(key)
        if isinstance(existing, dict) and existing.get("user_id") == user_id:
            # 幂等:相同 user_id 不刷新 matched_at
            continue
        resolutions[key] = {
            "user_id": user_id,
            "matched_at": timestamp,
        }
    state["_schema_version"] = BRIDGE_STATE_SCHEMA_VERSION
    return state


# ---------------------------------------------------------------------------
# 报告
# ---------------------------------------------------------------------------


def summarize(matrix: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """把 matrix 汇总为分布统计 · 便于 dry-run / report 打印。"""
    counters: Dict[str, int] = {}
    unmatched: List[str] = []
    for key, entry in matrix.items():
        kind = entry.get("kind", "unknown")
        counters[kind] = counters.get(kind, 0) + 1
        if entry.get("user_id") is None and kind in ("legacy_unmatched",):
            unmatched.append(key)
    return {
        "total": len(matrix),
        "by_kind": dict(sorted(counters.items())),
        "unmatched": sorted(unmatched),
    }


def build_report_from_state(state: Dict[str, Any]) -> Dict[str, Any]:
    """从 state.json 生成对账报告(不重新 resolve)。"""
    resolutions = state.get("resolutions", {})
    total = len(resolutions)
    return {
        "schema_version": state.get("_schema_version"),
        "total_resolutions": total,
        "sample": dict(list(resolutions.items())[:5]),
    }


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------


def _make_bridge(identity_dir: Path) -> IdentityBridge:
    store = JsonIdentityStore(identity_dir)
    return IdentityBridge(store=store)


def run_dry_run(
    *,
    identity_dir: Path,
    canvas_dir: Path,
    asset_file: Path,
) -> Dict[str, Any]:
    bridge = _make_bridge(identity_dir)
    resources = scan_resources(canvas_dir=canvas_dir, asset_file=asset_file)
    matrix = build_resolution_matrix(bridge, resources)
    return {"matrix": matrix, "summary": summarize(matrix)}


def run_apply(
    *,
    identity_dir: Path,
    canvas_dir: Path,
    asset_file: Path,
    state_file: Path,
    timestamp: Optional[str] = None,
) -> Dict[str, Any]:
    result = run_dry_run(
        identity_dir=identity_dir, canvas_dir=canvas_dir, asset_file=asset_file
    )
    state = read_bridge_state(state_file)
    apply_matrix_to_state(state, result["matrix"], timestamp=timestamp)
    write_bridge_state(state_file, state)
    result["state_file"] = str(state_file)
    result["written"] = True
    return result


def run_report(state_file: Path) -> Dict[str, Any]:
    state = read_bridge_state(state_file)
    return build_report_from_state(state)


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "权限 PR-9 IdentityBridge 数据承接 CLI"
            " · dry-run / apply / report 三档"
        )
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="扫描 · 输出映射矩阵 · 不写盘")
    group.add_argument("--apply", action="store_true", help="扫描 · 写入 bridge_state.json")
    group.add_argument("--report", action="store_true", help="从 bridge_state.json 生成对账报告")
    parser.add_argument(
        "--identity-dir",
        type=Path,
        default=DEFAULT_IDENTITY_DIR,
        help=f"identity JSON 目录(默认 {DEFAULT_IDENTITY_DIR})",
    )
    parser.add_argument(
        "--canvas-dir",
        type=Path,
        default=DEFAULT_CANVAS_DIR,
        help=f"画布目录(默认 {DEFAULT_CANVAS_DIR})",
    )
    parser.add_argument(
        "--asset-file",
        type=Path,
        default=DEFAULT_ASSET_LIBRARY_FILE,
        help=f"素材库文件(默认 {DEFAULT_ASSET_LIBRARY_FILE})",
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        default=DEFAULT_BRIDGE_STATE_FILE,
        help=f"bridge_state.json 路径(默认 {DEFAULT_BRIDGE_STATE_FILE})",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    if args.dry_run:
        result = run_dry_run(
            identity_dir=args.identity_dir,
            canvas_dir=args.canvas_dir,
            asset_file=args.asset_file,
        )
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.apply:
        result = run_apply(
            identity_dir=args.identity_dir,
            canvas_dir=args.canvas_dir,
            asset_file=args.asset_file,
            state_file=args.state_file,
        )
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.report:
        report = run_report(args.state_file)
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    return 2  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
