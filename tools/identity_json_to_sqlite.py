#!/usr/bin/env python3
"""`identity_json_to_sqlite.py` — JSON→SQLite 迁移 CLI(权限 PR-10)。

**定位**:扫描 `data/identity/*.json` 8 类文件 · 幂等写入 SQLite identity
6 张表(user / workspace / membership / role / permission / user_alias)·
`--verify` 模式做 JsonStore vs SqliteStore 逐方法对账。

三档子命令:
- `--dry-run`:扫描 · 输出计数矩阵 · 不写盘
- `--apply`:幂等写入 SQLite(INSERT OR IGNORE 按业务主键 · 重复调用产生相同结果)
- `--verify`:对账模式 · JsonIdentityStore vs SqliteIdentityStore 逐方法比对

**幂等保证**:
- user:按 (id) 主键 INSERT OR IGNORE
- workspace:按 (id) 主键 INSERT OR IGNORE
- role:按 (name) UNIQUE INSERT OR IGNORE
- user_alias:按 (legacy_user_key) UNIQUE INSERT OR IGNORE
- membership:按 (user_id, workspace_id) UNIQUE INSERT OR IGNORE

**明确不做**(冲突 A 决议 α · Lead 圆桌 2026-07-25):
- **不迁 project_memberships**(schema 缺 `project_id` 列 · 语义留权限
  PR-11 承接 · CLI 输出显式 "skipped: awaits PR-11")
- 不迁 resource_acl(schema 未建 · 留 PR-11)
- 不迁 role_permissions.json(权限矩阵事实层在 PermissionService 常量 ·
  不入 DB · 冲突 C 决议 η)
- 不迁 auth_migration_state(继续走 JSON · 留 PR-11 迁 K/V 元数据表)
- 不迁 audit_logs.jsonl(追加型日志 · 不入 identity 表)

**参照**:`tools/bridge_migrate.py`(391 行 · 权限 PR-9)pattern。

**P0 密钥零泄漏**:identity JSON 8 类文件 · 无密码 hash / session_id ·
CLI 输出 summary 只 emit 计数矩阵 · 不 emit 原始 legacy_user_key 值。
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid as _uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# 允许作为脚本从项目根目录运行
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


DEFAULT_IDENTITY_DIR = _ROOT / "data" / "identity"


# ---------------------------------------------------------------------------
# 扫描:JSON → 计数矩阵
# ---------------------------------------------------------------------------


def _read_json(p: Path) -> Any:
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def scan_json_dir(identity_dir: Path) -> Dict[str, Any]:
    """扫描 identity JSON 目录 · 返回计数矩阵 + 结构化数据。"""
    users_data = _read_json(identity_dir / "users.json") or {}
    aliases_data = _read_json(identity_dir / "user_aliases.json") or {}
    workspaces_data = _read_json(identity_dir / "workspaces.json") or {}
    memberships_data = _read_json(identity_dir / "memberships.json") or {}
    roles_data = _read_json(identity_dir / "roles.json") or {}
    role_perms_data = _read_json(identity_dir / "role_permissions.json") or {}
    resource_acl_data = _read_json(identity_dir / "resource_acl.json") or {}

    users = users_data.get("users", {}) if isinstance(users_data, dict) else {}
    aliases = (
        aliases_data.get("aliases", []) if isinstance(aliases_data, dict) else []
    )
    workspaces = (
        workspaces_data.get("workspaces", {})
        if isinstance(workspaces_data, dict)
        else {}
    )
    ws_memberships = (
        memberships_data.get("workspace_memberships", [])
        if isinstance(memberships_data, dict)
        else []
    )
    proj_memberships = (
        memberships_data.get("project_memberships", [])
        if isinstance(memberships_data, dict)
        else []
    )
    roles = roles_data.get("roles", {}) if isinstance(roles_data, dict) else {}
    role_perms = (
        role_perms_data.get("role_permissions", {})
        if isinstance(role_perms_data, dict)
        else {}
    )
    acl = (
        resource_acl_data.get("acl", [])
        if isinstance(resource_acl_data, dict)
        else []
    )

    return {
        "counts": {
            "users": len(users),
            "user_aliases": len(aliases),
            "workspaces": len(workspaces),
            "workspace_memberships": len(ws_memberships),
            "project_memberships_skipped_pr11": len(proj_memberships),
            "roles": len(roles),
            "role_permissions_skipped_pr4_matrix": len(role_perms),
            "resource_acl_skipped_pr11": len(acl),
        },
        "data": {
            "users": users,
            "aliases": aliases,
            "workspaces": workspaces,
            "workspace_memberships": ws_memberships,
            "roles": roles,
        },
    }


# ---------------------------------------------------------------------------
# 写入:JSON data → SQLite(幂等 INSERT OR IGNORE)
# ---------------------------------------------------------------------------


def _to_uuid(value: Any) -> Optional[_uuid.UUID]:
    """字符串 → UUID · 失败返回 None(不 raise 让 CLI 跳过并计入未匹配)。"""
    if value is None:
        return None
    if isinstance(value, _uuid.UUID):
        return value
    try:
        return _uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def _parse_ts(value: Any) -> datetime:
    """ISO 8601 str → datetime · 失败返回 now(UTC)。"""
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def apply_to_sqlite(scan_result: Dict[str, Any]) -> Dict[str, Any]:
    """把扫描结果**幂等**写入 SQLite · 返回写入统计。

    幂等策略:
    - user / workspace / role / user_alias / membership 都用 `INSERT OR IGNORE`
      (SQLite 特有 · SQLAlchemy Core `.insert().prefix_with('OR IGNORE')`)
    - 冲突键:user.id / workspace.id / role.name / user_alias.legacy_user_key
      / (membership.user_id, membership.workspace_id)
    """
    from sqlalchemy.dialects.sqlite import insert as _sqlite_insert

    from app.db.session import get_session
    from app.identity.tables import (
        membership_table,
        role_table,
        user_alias_table,
        user_table,
        workspace_table,
    )

    data = scan_result["data"]
    stats = {
        "users_inserted_or_ignored": 0,
        "aliases_inserted_or_ignored": 0,
        "workspaces_inserted_or_ignored": 0,
        "memberships_inserted_or_ignored": 0,
        "roles_inserted_or_ignored": 0,
        "skipped_invalid_uuid": 0,
    }

    with get_session() as session:
        # user
        for uid_str, record in data["users"].items():
            uid = _to_uuid(uid_str)
            if uid is None:
                stats["skipped_invalid_uuid"] += 1
                continue
            stmt = _sqlite_insert(user_table).values(
                id=uid,
                legacy_user_key=record.get("legacy_user_key"),
                display_name=record.get("display_name"),
                avatar_url=record.get("avatar_url"),
                created_at=_parse_ts(record.get("created_at")),
                updated_at=_parse_ts(
                    record.get("updated_at") or record.get("created_at")
                ),
            ).on_conflict_do_nothing()
            session.execute(stmt)
            stats["users_inserted_or_ignored"] += 1

        # workspace
        for wid_str, record in data["workspaces"].items():
            wid = _to_uuid(wid_str)
            if wid is None:
                stats["skipped_invalid_uuid"] += 1
                continue
            # description 存入 raw_json(冲突 B 决议 δ 一致)
            raw_json_payload = {}
            if record.get("description") is not None:
                raw_json_payload["description"] = record["description"]
            stmt = _sqlite_insert(workspace_table).values(
                id=wid,
                name=record.get("name", ""),
                kind=record.get("kind", "system"),
                raw_json=json.dumps(raw_json_payload) if raw_json_payload else None,
                created_at=_parse_ts(record.get("created_at")),
                updated_at=_parse_ts(
                    record.get("updated_at") or record.get("created_at")
                ),
            ).on_conflict_do_nothing()
            session.execute(stmt)
            stats["workspaces_inserted_or_ignored"] += 1

        # workspace_memberships(冲突 A α:project_memberships 不迁)
        for mem in data["workspace_memberships"]:
            uid = _to_uuid(mem.get("user_id"))
            wid = _to_uuid(mem.get("workspace_id"))
            if uid is None or wid is None:
                stats["skipped_invalid_uuid"] += 1
                continue
            stmt = _sqlite_insert(membership_table).values(
                id=_uuid.uuid4(),
                user_id=uid,
                workspace_id=wid,
                role=mem.get("role", "member"),
                created_at=_parse_ts(mem.get("created_at")),
                updated_at=_parse_ts(mem.get("created_at")),
            ).on_conflict_do_nothing()
            session.execute(stmt)
            stats["memberships_inserted_or_ignored"] += 1

        # role(冲突 C η:permissions_json 保持空 seed · 矩阵事实层在 PermissionService 常量)
        for role_key, record in data["roles"].items():
            rid = _uuid.uuid4()
            raw_json_payload = {
                k: record.get(k)
                for k in ("display_name", "description", "scope")
                if record.get(k) is not None
            }
            stmt = _sqlite_insert(role_table).values(
                id=rid,
                name=record.get("key", role_key),
                permissions_json="{}",  # 保持 seed 语义(冲突 C 决议 η)
                raw_json=json.dumps(raw_json_payload) if raw_json_payload else "{}",
                created_at=_parse_ts(record.get("created_at")),
                updated_at=_parse_ts(record.get("created_at")),
            ).on_conflict_do_nothing()
            session.execute(stmt)
            stats["roles_inserted_or_ignored"] += 1

        # user_alias
        for alias in data["aliases"]:
            aid = _to_uuid(alias.get("id")) or _uuid.uuid4()
            uid = _to_uuid(alias.get("user_id"))
            legacy_key = alias.get("legacy_user_key")
            if legacy_key is None or uid is None:
                # user_id 是 NOT NULL 列 · alias 未 claim 到 user 则跳过
                stats["skipped_invalid_uuid"] += 1
                continue
            raw_json_payload = {"kind": alias.get("kind", "x_user_id")}
            stmt = _sqlite_insert(user_alias_table).values(
                id=aid,
                user_id=uid,
                legacy_user_key=legacy_key,
                raw_json=json.dumps(raw_json_payload),
                created_at=_parse_ts(alias.get("created_at")),
                updated_at=_parse_ts(alias.get("created_at")),
            ).on_conflict_do_nothing()
            session.execute(stmt)
            stats["aliases_inserted_or_ignored"] += 1

    return stats


# ---------------------------------------------------------------------------
# 验证:JsonStore vs SqliteStore 对账
# ---------------------------------------------------------------------------


def verify_parity(identity_dir: Path) -> Dict[str, Any]:
    """逐方法比对 JsonIdentityStore vs SqliteIdentityStore 结果。

    返回 dict:每方法 status(match / mismatch) + 少量诊断信息。
    """
    from app.identity.store import JsonIdentityStore, SqliteIdentityStore

    json_store = JsonIdentityStore(identity_dir)
    sqlite_store = SqliteIdentityStore(base_dir=identity_dir)

    report: Dict[str, Any] = {}

    # list_workspaces:比 name 集合(SQLite 侧 0006 seed 额外含 system)
    j_ws = json_store.list_workspaces()
    s_ws = sqlite_store.list_workspaces()
    j_ws_names = sorted(w["name"] for w in j_ws)
    s_ws_names_no_seed = sorted(w["name"] for w in s_ws if w["name"] != "system")
    report["list_workspaces"] = {
        "status": "match" if j_ws_names == s_ws_names_no_seed else "mismatch",
        "json_count": len(j_ws),
        "sqlite_count_ex_seed": len(s_ws_names_no_seed),
    }

    # list_roles:比 key 集合(SQLite 侧 0006 seed 含 admin/member/viewer)
    j_roles = {r["key"] for r in json_store.list_roles()}
    s_roles = {r["key"] for r in sqlite_store.list_roles()}
    # JSON 侧 roles 可能是 5 内置 · SQLite 侧 seed 是 3 内置 · 用户 seed 后可能不一致
    report["list_roles"] = {
        "status": "match" if j_roles.issubset(s_roles) or s_roles.issubset(j_roles) else "check",
        "json_count": len(j_roles),
        "sqlite_count": len(s_roles),
    }

    # list_role_permissions:严格 == `{}`(冲突 C η)
    j_perms = json_store.list_role_permissions()
    s_perms = sqlite_store.list_role_permissions()
    report["list_role_permissions"] = {
        "status": "match" if j_perms == s_perms == {} else "mismatch",
        "json": j_perms,
        "sqlite": s_perms,
    }

    # get_resource_acl:两侧都空
    j_acl = json_store.get_resource_acl("canvas", "any")
    s_acl = sqlite_store.get_resource_acl("canvas", "any")
    report["get_resource_acl"] = {
        "status": "match" if j_acl == s_acl == [] else "mismatch",
    }

    # read_auth_migration_state:两侧读同 JSON
    j_state = json_store.read_auth_migration_state()
    s_state = sqlite_store.read_auth_migration_state()
    report["read_auth_migration_state"] = {
        "status": "match" if j_state == s_state else "mismatch",
    }

    # list_user_aliases:比条目数(两侧应该等价 · 前提 apply 已跑)
    j_aliases = json_store.list_user_aliases()
    s_aliases = sqlite_store.list_user_aliases()
    report["list_user_aliases"] = {
        "status": "match" if len(j_aliases) == len(s_aliases) else "count_mismatch",
        "json_count": len(j_aliases),
        "sqlite_count": len(s_aliases),
    }

    overall = all(
        v.get("status") in ("match",) for v in report.values() if isinstance(v, dict)
    )
    report["_overall"] = "match" if overall else "check_details"
    return report


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------


def run_dry_run(*, identity_dir: Path) -> Dict[str, Any]:
    scan = scan_json_dir(identity_dir)
    return {
        "mode": "dry-run",
        "identity_dir": str(identity_dir),
        "counts": scan["counts"],
        "note": (
            "project_memberships / resource_acl / role_permissions / "
            "auth_migration_state 不迁 · 语义留权限 PR-11 承接"
        ),
    }


def run_apply(*, identity_dir: Path) -> Dict[str, Any]:
    scan = scan_json_dir(identity_dir)
    stats = apply_to_sqlite(scan)
    return {
        "mode": "apply",
        "identity_dir": str(identity_dir),
        "counts": scan["counts"],
        "stats": stats,
    }


def run_verify(*, identity_dir: Path) -> Dict[str, Any]:
    return {
        "mode": "verify",
        "identity_dir": str(identity_dir),
        "report": verify_parity(identity_dir),
    }


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "权限 PR-10 JSON→SQLite identity 迁移 CLI"
            " · dry-run / apply / verify 三档"
        )
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--dry-run",
        action="store_true",
        help="扫描 identity JSON · 输出计数矩阵 · 不写盘",
    )
    group.add_argument(
        "--apply",
        action="store_true",
        help="幂等写入 SQLite(INSERT OR IGNORE)",
    )
    group.add_argument(
        "--verify",
        action="store_true",
        help="JsonStore vs SqliteStore 逐方法对账",
    )
    parser.add_argument(
        "--identity-dir",
        type=Path,
        default=DEFAULT_IDENTITY_DIR,
        help=f"identity JSON 目录(默认 {DEFAULT_IDENTITY_DIR})",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    if args.dry_run:
        result = run_dry_run(identity_dir=args.identity_dir)
    elif args.apply:
        result = run_apply(identity_dir=args.identity_dir)
    elif args.verify:
        result = run_verify(identity_dir=args.identity_dir)
    else:
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
