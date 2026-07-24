"""`IdentityStore` 门面（权限 PR-0；SQLite 实装 · 权限 PR-10）。

对外暴露：
- 只读接口 9 个：`get_user / find_alias / list_workspaces / list_memberships /
  list_roles / list_role_permissions / get_resource_acl /
  read_auth_migration_state`（+ `list_user_aliases` 辅助）。
- 写入接口 1 个：`write_auth_migration_state`（供 bootstrap 使用；其它写路径
  由后续 PR 承接：PR-2 legacy_mapper、PR-3 认证入口、PR-4 PermissionService 等）。

实现：
- `JsonIdentityStore(base_dir: Path)`：读 `data/identity/*.json` 8 个文件。
- `SqliteIdentityStore(session_factory, base_dir=None)`：SQL 读取(权限 PR-10)
  · session_factory 注入 `SessionLocal` / `get_session` 等价物 · base_dir 仅
  用于 `auth_migration_state` 元数据 JSON 读写(schema 未建 K/V 元数据表 ·
  留权限 PR-11 承接)。

签名冻结原则：只允许**新增**方法，禁止删除或改现有签名（下游 PR-BE-02 /
权限 PR-2 / PR-3 / PR-4 都会依赖这些方法名）。

**权限 PR-10 补交(Lead 圆桌决议 α+δ+η+D-env+E-tables)**:
- SqliteIdentityStore 占位 → SQL 实装 10 方法 · 语义等价 JsonIdentityStore
- `list_memberships`:project 端硬编码空 list(冲突 A 决议 α · schema 缺
  `project_id` 列 · 语义留权限 PR-11 承接)
- `get_user`:仅返回 `id / created_at / updated_at / legacy_user_key /
  display_name / avatar_url` 6 键 public subset(冲突 B 决议 δ)
- `list_role_permissions`:过滤空 `permissions_json` seed → 空 dict(冲突 C
  决议 η)
- `get_resource_acl`:恒返回 `[]`(schema 未建 resource_acl 表 · 留 PR-11 承接)
- `IDENTITY_STORE_BACKEND` env flag + `get_identity_store()` factory(D-env)
"""
from __future__ import annotations

import json
import os
import uuid as _uuid
from pathlib import Path
from typing import Any, Callable, Dict, FrozenSet, List, Optional, Protocol

from .schema import (
    AliasKind,
    AuthMigrationStateFile,
    MembershipsFile,
    ResourceAclEntry,
    ResourceAclFile,
    RolePermissionsFile,
    RoleRecord,
    RolesFile,
    UserAliasRecord,
    UserAliasesFile,
    UserRecord,
    UsersFile,
    WorkspaceRecord,
    WorkspacesFile,
    validate_auth_migration_state_file,
    validate_memberships_file,
    validate_resource_acl_file,
    validate_role_permissions_file,
    validate_roles_file,
    validate_user_aliases_file,
    validate_users_file,
    validate_workspaces_file,
)


# ---------------------------------------------------------------------------
# 门面协议
# ---------------------------------------------------------------------------


class IdentityStore(Protocol):
    """`IdentityStore` 门面协议。

    9 个只读接口 + 1 个写入接口（`write_auth_migration_state`）。

    - `get_user(user_id)` — 按 id 查用户；不存在返回 `None`。
    - `find_alias(kind, key)` — 按 kind + legacy_user_key 唯一定位 UserAlias。
    - `list_user_aliases()` — 列全部 UserAlias（PR-2 消费）。
    - `list_workspaces()` — 列全部 Workspace（顺序按 `created_at` 升序）。
    - `list_memberships(user_id)` — 返回 `{"workspace": [...], "project": [...]}`。
    - `list_roles()` — 列全部内置角色。
    - `list_role_permissions()` — 返回完整 role → action → bool 矩阵
      （本 PR 为空 dict；PR-4 承接）。
    - `get_resource_acl(resource_type, resource_id)` — 返回该资源的 ACL 条目列表。
    - `read_auth_migration_state()` — 返回 `auth_migration_state.json` 完整内容。
    - `write_auth_migration_state(state)` — **唯一**写入方法；供 bootstrap 使用。
    """

    def get_user(self, user_id: str) -> Optional[UserRecord]: ...
    def find_alias(
        self, kind: AliasKind, key: str
    ) -> Optional[UserAliasRecord]: ...
    def list_user_aliases(self) -> List[UserAliasRecord]: ...
    def list_workspaces(self) -> List[WorkspaceRecord]: ...
    def list_memberships(self, user_id: str) -> Dict[str, List[Dict[str, Any]]]: ...
    def list_roles(self) -> List[RoleRecord]: ...
    def list_role_permissions(self) -> Dict[str, Dict[str, bool]]: ...
    def get_resource_acl(
        self, resource_type: str, resource_id: str
    ) -> List[ResourceAclEntry]: ...
    def read_auth_migration_state(self) -> AuthMigrationStateFile: ...
    def write_auth_migration_state(
        self, state: AuthMigrationStateFile
    ) -> None: ...


# ---------------------------------------------------------------------------
# JSON 实现
# ---------------------------------------------------------------------------


class JsonIdentityStore:
    """基于 `data/identity/*.json` 的 IdentityStore 实现。

    - 每次调用都从磁盘重读（无内存缓存）：本 PR 无高并发场景，读延迟不敏感；
      避免与 bootstrap 脚本的写入产生缓存一致性问题。
    - 校验：读入后过 schema.validate_* 校验；不合法直接抛 SchemaValidationError。
    - 幂等：写入 `write_auth_migration_state` 使用"整体覆盖 + 稳定序列化"，
      同内容多次写入产生**字节完全相同**的文件（bootstrap 幂等的必要条件）。
    """

    USERS_FILE = "users.json"
    USER_ALIASES_FILE = "user_aliases.json"
    WORKSPACES_FILE = "workspaces.json"
    MEMBERSHIPS_FILE = "memberships.json"
    ROLES_FILE = "roles.json"
    ROLE_PERMISSIONS_FILE = "role_permissions.json"
    RESOURCE_ACL_FILE = "resource_acl.json"
    AUTH_MIGRATION_STATE_FILE = "auth_migration_state.json"
    AUDIT_LOGS_FILE = "audit_logs.jsonl"

    def __init__(self, base_dir: Path | str) -> None:
        self.base_dir = Path(base_dir)

    # ---- 内部读写 helpers -------------------------------------------------

    def _read_json(self, name: str) -> Any:
        p = self.base_dir / name
        if not p.is_file():
            raise FileNotFoundError(
                f"identity JSON 文件缺失：{p}（请先跑 tools/migrate_identity_bootstrap.py）"
            )
        with p.open("r", encoding="utf-8") as fh:
            return json.load(fh)

    def _write_json(self, name: str, payload: Any) -> None:
        p = self.base_dir / name
        p.parent.mkdir(parents=True, exist_ok=True)
        # 稳定序列化：`sort_keys=True` + `ensure_ascii=False` + 固定缩进
        # + 尾随换行；两次写同内容 → 字节完全相同（幂等）。
        text = json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        # 原子替换：先写临时文件再 rename，避免半写状态
        tmp = p.with_suffix(p.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.write("\n")
        tmp.replace(p)

    def _load_users(self) -> UsersFile:
        return validate_users_file(self._read_json(self.USERS_FILE))

    def _load_aliases(self) -> UserAliasesFile:
        return validate_user_aliases_file(self._read_json(self.USER_ALIASES_FILE))

    def _load_workspaces(self) -> WorkspacesFile:
        return validate_workspaces_file(self._read_json(self.WORKSPACES_FILE))

    def _load_memberships(self) -> MembershipsFile:
        return validate_memberships_file(self._read_json(self.MEMBERSHIPS_FILE))

    def _load_roles(self) -> RolesFile:
        return validate_roles_file(self._read_json(self.ROLES_FILE))

    def _load_role_permissions(self) -> RolePermissionsFile:
        return validate_role_permissions_file(
            self._read_json(self.ROLE_PERMISSIONS_FILE)
        )

    def _load_resource_acl(self) -> ResourceAclFile:
        return validate_resource_acl_file(self._read_json(self.RESOURCE_ACL_FILE))

    # ---- 只读接口 ---------------------------------------------------------

    def get_user(self, user_id: str) -> Optional[UserRecord]:
        users = self._load_users()["users"]
        return users.get(user_id)

    def find_alias(self, kind: AliasKind, key: str) -> Optional[UserAliasRecord]:
        for entry in self._load_aliases()["aliases"]:
            if entry.get("kind") == kind and entry.get("legacy_user_key") == key:
                return entry
        return None

    def list_user_aliases(self) -> List[UserAliasRecord]:
        return list(self._load_aliases()["aliases"])

    def list_workspaces(self) -> List[WorkspaceRecord]:
        workspaces = self._load_workspaces()["workspaces"]
        # 按 created_at 升序稳定输出
        return sorted(
            workspaces.values(),
            key=lambda w: (w.get("created_at", ""), w.get("id", "")),
        )

    def list_memberships(
        self, user_id: str
    ) -> Dict[str, List[Dict[str, Any]]]:
        data = self._load_memberships()
        return {
            "workspace": [
                m for m in data["workspace_memberships"] if m.get("user_id") == user_id
            ],
            "project": [
                m for m in data["project_memberships"] if m.get("user_id") == user_id
            ],
        }

    def list_roles(self) -> List[RoleRecord]:
        roles = self._load_roles()["roles"]
        return sorted(roles.values(), key=lambda r: r.get("key", ""))

    def list_role_permissions(self) -> Dict[str, Dict[str, bool]]:
        # 完整矩阵；本 PR 为空 dict，PR-4 填充
        return dict(self._load_role_permissions()["role_permissions"])

    def get_resource_acl(
        self, resource_type: str, resource_id: str
    ) -> List[ResourceAclEntry]:
        return [
            entry
            for entry in self._load_resource_acl()["acl"]
            if entry.get("resource_type") == resource_type
            and entry.get("resource_id") == resource_id
        ]

    def read_auth_migration_state(self) -> AuthMigrationStateFile:
        return validate_auth_migration_state_file(
            self._read_json(self.AUTH_MIGRATION_STATE_FILE)
        )

    # ---- 唯一写入接口 -----------------------------------------------------

    def write_auth_migration_state(
        self, state: AuthMigrationStateFile
    ) -> None:
        """整体覆盖 `auth_migration_state.json`。

        校验后原子写入，稳定序列化保证多次相同内容写入产生字节相同的文件。
        供 `tools/migrate_identity_bootstrap.py` 使用；其它调用点须走后续 PR。
        """
        validate_auth_migration_state_file(state)
        self._write_json(self.AUTH_MIGRATION_STATE_FILE, state)


# ---------------------------------------------------------------------------
# SQLite 实装（权限 PR-10 · 消费 0006_identity 已建表 · 零新 migration）
# ---------------------------------------------------------------------------


# ---- public field subset(冲突 B 决议 δ · Lead 圆桌 2026-07-25)-----------
#
# `user` 表本 PR 只承载 6 列 → `get_user()` 返回 dict 精确 6 键(与 JsonStore
# 语义等价的**公共键集子集**)· 冗余 JSON 字段(username / status / email)
# 不跨层污染 · 未来若真需要走独立 CB(数据 PR 增列 + migration)。
SQLITE_USER_PUBLIC_FIELDS: FrozenSet[str] = frozenset(
    {
        "id",
        "legacy_user_key",
        "display_name",
        "avatar_url",
        "created_at",
        "updated_at",
    }
)


def _isoformat_or_none(value: Any) -> Optional[str]:
    """把 `datetime` / `str` / `None` 归一为 ISO 8601 str 或 None。

    SQLAlchemy `DateTime(timezone=True)` 在 SQLite 上返回 **naive datetime**
    (SQLite 无 tz 存储 · 只存 UTC 字符串)· PostgreSQL 返回 aware datetime。
    统一策略:naive → 视为 UTC · aware → 保持 · 输出 ISO 8601 带 `+00:00`
    保证跨方言输出稳定 · 与 JsonStore(纯 ISO 字符串)语义等价。
    """
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        import datetime as _dt

        if isinstance(value, _dt.datetime) and value.tzinfo is None:
            # SQLite naive datetime · 视为 UTC(0006/0007 migration 写入时是 UTC aware)
            value = value.replace(tzinfo=_dt.timezone.utc)
        return value.isoformat()  # type: ignore[no-any-return]
    return str(value)


def _uuid_to_str(value: Any) -> str:
    """把 `uuid.UUID` / `str` 归一为 str。"""
    if isinstance(value, _uuid.UUID):
        return str(value)
    return str(value) if value is not None else ""


class SqliteIdentityStore:
    """`IdentityStore` 的 SQLite 实装(权限 PR-10 · Wave 3-N.9 Batch 3 主线 A)。

    **架构决策**:
    - **懒 import SQLAlchemy**:类体内不 import ORM/Core · 只在方法体内按需
      拿 `session_factory()` 生成的 Session · 让 `IDENTITY_STORE_BACKEND=json`
      默认路径下 `sys.modules` 不加载 SQL 层(遵守 MinioAdapter pattern)。
    - **session_factory 注入**:构造参数 `session_factory: Callable[[], Session]`
      · 默认从 `app.db.session.SessionLocal` 懒加载 · 测试可注入 mock。
    - **auth_migration_state 仍走 JSON**:0006/0007 schema 未建 K/V 元数据
      表 · 本 PR 不扩表 · `read/write_auth_migration_state` 内部沿用
      `data/identity/auth_migration_state.json`(与 JsonStore 幂等序列化一致)。
    - **project membership 硬编码空 list(冲突 A 决议 α)**:0006_identity
      的 `membership` 表无 `project_id` 列 · 无法区分 workspace vs project ·
      本 PR project 端返回 `{"project": []}` 硬编码 · 语义留权限 PR-11 承接
      (schema 需扩 `project_id` 列 · 走独立 CB)。
    - **public field subset(冲突 B 决议 δ)**:`get_user()` 返回 dict 只含
      `SQLITE_USER_PUBLIC_FIELDS` 6 键 · 与 JsonStore 语义"公共键集子集全等"
      · 冗余 JSON 字段(username / status / email)不跨层污染。
    - **role.permissions_json 过滤空 seed(冲突 C 决议 η)**:
      `list_role_permissions()` 遍历 role 表 · 只 emit `permissions_json`
      反序列化后**非空**的条目 · seed 全空 → 返回 `{}` · 与 JsonStore
      `role_permissions.json.role_permissions = {}` 严格 == 等价。
    - **resource_acl 恒空**:schema 未建 `resource_acl` 表 ·
      `get_resource_acl()` 恒返回 `[]` · 留权限 PR-11 扩展。

    **P0 密钥零泄漏**:
    - `password_hash` 只在 `auth_credentials` 表(权限 PR-3) · 不在
      identity 6 表 · 本 store 完全不接触。
    - `session_id` 只在 `sessions` 表(权限 PR-3) · 本 store 完全不接触。
    - `raw_json` 列可能承载 legacy 冗余数据 · 但本 store 只反序列化
      `role.permissions_json`(明确无密钥)· 其他 `raw_json` 列不消费。

    **线程安全**:每次方法调用现开 Session · 用完关闭 · 无实例级缓存 · 无锁。

    **未来演进**:
    - PR-11 承接 `resource_acl` 表 + `membership.project_id` 列扩展
    - `auth_migration_state` 迁到 K/V 元数据表
    - `get_user` 6 键 subset 若需扩(username/status/email)走独立 CB
    """

    def __init__(
        self,
        session_factory: Optional[Callable[[], Any]] = None,
        base_dir: Optional[Path] = None,
    ) -> None:
        """
        Args:
            session_factory: `SessionLocal` 等价工厂 · 无参调用返回新 Session。
                默认懒 import `app.db.session.SessionLocal`。
            base_dir: `auth_migration_state.json` 存放目录 · 默认
                `data/identity`。仅本 PR 用 · 未来迁到 K/V 元数据表后弃用。
        """
        self._session_factory = session_factory
        # base_dir 默认对齐 JsonStore · 允许 None(懒解析)
        self._base_dir: Optional[Path] = Path(base_dir) if base_dir else None

    # ---- 懒解析 ----------------------------------------------------------

    def _get_session(self) -> Any:
        """现拿一个 Session · 调用方负责关闭。

        `session_factory` 未注入时懒 import `SessionLocal`;
        规避 `IDENTITY_STORE_BACKEND=json` 默认路径下加载 SQLAlchemy。
        """
        if self._session_factory is not None:
            return self._session_factory()
        # 懒 import:只在真正需要 SQL 时才加载
        from app.db.session import SessionLocal  # noqa: WPS433

        return SessionLocal()

    def _get_base_dir(self) -> Path:
        """`auth_migration_state.json` 存放路径 · 默认 `data/identity`。"""
        if self._base_dir is not None:
            return self._base_dir
        # 默认相对项目根
        root = Path(__file__).resolve().parents[2]
        return root / "data" / "identity"

    # ---- 只读接口 -------------------------------------------------------

    def get_user(self, user_id: str) -> Optional[UserRecord]:
        """按 id 查 user · 返回 6 键 public subset dict 或 None。

        与 JsonStore 语义等价"公共键集子集全等":
        - 相同 user_id 存在 → 返回 dict 精确包含 6 键 · 每个 value 与 JsonStore 一致
        - 不存在 → None
        """
        from sqlalchemy import select

        from app.identity.tables import user_table

        session = self._get_session()
        try:
            # user_id 可能是 str 或 UUID · 统一转为 UUID
            try:
                uid_val: Any = _uuid.UUID(user_id) if isinstance(user_id, str) else user_id
            except (ValueError, TypeError, AttributeError):
                return None
            row = session.execute(
                select(user_table).where(user_table.c.id == uid_val)
            ).first()
            if row is None:
                return None
            # 显式构造 6 键 subset · 不透 legacy 冗余字段
            result: Dict[str, Any] = {
                "id": _uuid_to_str(row.id),
                "legacy_user_key": row.legacy_user_key,
                "display_name": row.display_name,
                "avatar_url": row.avatar_url,
                "created_at": _isoformat_or_none(row.created_at) or "",
                "updated_at": _isoformat_or_none(row.updated_at),
            }
            return result  # type: ignore[return-value]
        finally:
            session.close()

    def find_alias(
        self, kind: AliasKind, key: str
    ) -> Optional[UserAliasRecord]:
        """按 kind + legacy_user_key 定位 user_alias。

        **重要**:0006_identity 的 `user_alias` 表**无** `kind` 列 · 唯一约束
        只在 `legacy_user_key` 上 · 本 PR 里 `kind` 参数**不消费**(只用 key
        匹配)· 语义弱化明示:JsonStore 侧同一 key 不同 kind 会失败匹配 ·
        SqliteStore 侧只按 key 匹配 · 未来扩 `kind` 列走独立 CB。
        """
        from sqlalchemy import select

        from app.identity.tables import user_alias_table

        _ = kind  # 保留参数位 · schema 未扩 · 未来消费
        session = self._get_session()
        try:
            row = session.execute(
                select(user_alias_table).where(
                    user_alias_table.c.legacy_user_key == key
                )
            ).first()
            if row is None:
                return None
            # 反序列化 raw_json(若有)获取 kind · 否则默认标 x_user_id
            raw_kind: Optional[str] = None
            if row.raw_json:
                try:
                    parsed = json.loads(row.raw_json)
                    if isinstance(parsed, dict):
                        raw_kind = parsed.get("kind")
                except (json.JSONDecodeError, TypeError):
                    raw_kind = None
            result: Dict[str, Any] = {
                "id": _uuid_to_str(row.id),
                "user_id": _uuid_to_str(row.user_id) if row.user_id else None,
                "kind": raw_kind or "x_user_id",  # schema 未扩 kind 列 · 默认兜底
                "legacy_user_key": row.legacy_user_key,
                "created_at": _isoformat_or_none(row.created_at) or "",
            }
            return result  # type: ignore[return-value]
        finally:
            session.close()

    def list_user_aliases(self) -> List[UserAliasRecord]:
        """列全部 user_alias · 按 created_at 升序稳定输出。"""
        from sqlalchemy import select

        from app.identity.tables import user_alias_table

        session = self._get_session()
        try:
            rows = session.execute(
                select(user_alias_table).order_by(
                    user_alias_table.c.created_at, user_alias_table.c.id
                )
            ).all()
            result: List[Dict[str, Any]] = []
            for row in rows:
                raw_kind: Optional[str] = None
                if row.raw_json:
                    try:
                        parsed = json.loads(row.raw_json)
                        if isinstance(parsed, dict):
                            raw_kind = parsed.get("kind")
                    except (json.JSONDecodeError, TypeError):
                        raw_kind = None
                result.append(
                    {
                        "id": _uuid_to_str(row.id),
                        "user_id": _uuid_to_str(row.user_id) if row.user_id else None,
                        "kind": raw_kind or "x_user_id",
                        "legacy_user_key": row.legacy_user_key,
                        "created_at": _isoformat_or_none(row.created_at) or "",
                    }
                )
            return result  # type: ignore[return-value]
        finally:
            session.close()

    def list_workspaces(self) -> List[WorkspaceRecord]:
        """列全部 workspace · 按 (created_at, id) 升序稳定输出。"""
        from sqlalchemy import select

        from app.identity.tables import workspace_table

        session = self._get_session()
        try:
            rows = session.execute(
                select(workspace_table).order_by(
                    workspace_table.c.created_at, workspace_table.c.id
                )
            ).all()
            result: List[Dict[str, Any]] = []
            for row in rows:
                # description 从 raw_json 反查(schema 无 description 列)
                description: Optional[str] = None
                if row.raw_json:
                    try:
                        parsed = json.loads(row.raw_json)
                        if isinstance(parsed, dict):
                            description = parsed.get("description")
                    except (json.JSONDecodeError, TypeError):
                        description = None
                result.append(
                    {
                        "id": _uuid_to_str(row.id),
                        "name": row.name,
                        "description": description,
                        "created_at": _isoformat_or_none(row.created_at) or "",
                        "updated_at": _isoformat_or_none(row.updated_at),
                    }
                )
            return result  # type: ignore[return-value]
        finally:
            session.close()

    def list_memberships(
        self, user_id: str
    ) -> Dict[str, List[Dict[str, Any]]]:
        """返回 `{"workspace": [...], "project": []}`。

        **冲突 A 决议 α(Lead 圆桌 2026-07-25)**:
        - `workspace` 端:从 `membership` 表按 user_id 过滤返回
        - `project` 端:**硬编码空 list** · schema 缺 `project_id` 列 ·
          语义留权限 PR-11 承接(schema 需扩 · 走独立 CB)

        与 JsonStore 契约等价性锁:两实现的 project 端都是空 list · shape
        一致 · workspace 端 role/created_at 值全等。
        """
        from sqlalchemy import select

        from app.identity.tables import membership_table

        session = self._get_session()
        try:
            try:
                uid_val: Any = _uuid.UUID(user_id) if isinstance(user_id, str) else user_id
            except (ValueError, TypeError, AttributeError):
                return {"workspace": [], "project": []}
            rows = session.execute(
                select(membership_table)
                .where(membership_table.c.user_id == uid_val)
                .order_by(membership_table.c.created_at, membership_table.c.id)
            ).all()
            workspace_memberships: List[Dict[str, Any]] = []
            for row in rows:
                workspace_memberships.append(
                    {
                        "workspace_id": _uuid_to_str(row.workspace_id),
                        "user_id": _uuid_to_str(row.user_id),
                        "role": row.role,
                        "created_at": _isoformat_or_none(row.created_at) or "",
                    }
                )
            # project 端:硬编码空 list(冲突 A 决议 α · 语义留 PR-11)
            return {"workspace": workspace_memberships, "project": []}
        finally:
            session.close()

    def list_roles(self) -> List[RoleRecord]:
        """列全部 role · 按 name 升序稳定输出。

        JsonStore 侧字典 key 是 `key`(与 name 语义等价) · SqliteStore 从
        `role.name` 列读取 · 排序键统一为 name / key。

        **注意**:0006_identity 的 role 表列名是 `name` · JsonStore 侧
        RoleRecord 字段名是 `key`(与 `name` 语义等价 · 命名不同源自治理期
        双轨记录)。本方法把 SQL `name` 映射到 dict `key` 字段 · 与
        JsonStore 输出等价。scope / display_name / description 从 raw_json
        反查(schema 未拆列)· 若 raw_json 无这些字段则用默认值。
        """
        from sqlalchemy import select

        from app.identity.tables import role_table

        session = self._get_session()
        try:
            rows = session.execute(
                select(role_table).order_by(role_table.c.name)
            ).all()
            result: List[Dict[str, Any]] = []
            for row in rows:
                display_name: str = ""
                description: str = ""
                scope: str = "workspace"  # 默认兜底
                if row.raw_json:
                    try:
                        parsed = json.loads(row.raw_json)
                        if isinstance(parsed, dict):
                            display_name = parsed.get("display_name", "") or ""
                            description = parsed.get("description", "") or ""
                            scope = parsed.get("scope", "workspace") or "workspace"
                    except (json.JSONDecodeError, TypeError):
                        pass
                result.append(
                    {
                        "key": row.name,  # role.name → RoleRecord.key
                        "display_name": display_name,
                        "description": description,
                        "scope": scope,
                        "created_at": _isoformat_or_none(row.created_at) or "",
                    }
                )
            return result  # type: ignore[return-value]
        finally:
            session.close()

    def list_role_permissions(self) -> Dict[str, Dict[str, bool]]:
        """返回 role → action → bool 矩阵(seed 全空 → `{}`)。

        **冲突 C 决议 η(Lead 圆桌 2026-07-25)**:
        - 遍历 role 表 · 反序列化 `permissions_json` 列
        - 只 emit **非空** dict 的条目(过滤 `{}` seed)
        - seed 全空(0006_identity 默认)→ 返回 `{}` · 与 JsonStore
          `role_permissions.json.role_permissions = {}` 严格 == 等价

        权限矩阵事实层:`PermissionService.DEFAULT_PERMISSION_MATRIX` 常量
        (权限 PR-4 · Wave 3-N.8 Batch 4)· DB 层不承载矩阵。
        """
        from sqlalchemy import select

        from app.identity.tables import role_table

        session = self._get_session()
        try:
            rows = session.execute(
                select(role_table.c.name, role_table.c.permissions_json)
            ).all()
            result: Dict[str, Dict[str, bool]] = {}
            for row in rows:
                if not row.permissions_json:
                    continue
                try:
                    parsed = json.loads(row.permissions_json)
                except (json.JSONDecodeError, TypeError):
                    continue
                if not isinstance(parsed, dict) or not parsed:
                    # 空 dict `{}` 或非法 → 过滤(冲突 C 决议 η)
                    continue
                # 校验 value 类型 · 只保留 bool
                valid: Dict[str, bool] = {}
                for action, allow in parsed.items():
                    if isinstance(allow, bool):
                        valid[action] = allow
                if valid:
                    result[row.name] = valid
            return result
        finally:
            session.close()

    def get_resource_acl(
        self, resource_type: str, resource_id: str
    ) -> List[ResourceAclEntry]:
        """恒返回 `[]`。

        **原因**:0006_identity / 0007_sessions schema 均**未建**
        `resource_acl` 表 · 语义留权限 PR-11 扩展(独立 migration + CB 承接)。

        与 JsonStore 契约等价性锁:JsonStore 侧 `resource_acl.json.acl` 治理期
        为空 list · SqliteStore 硬编码空 list · 两侧 shape 一致语义等价。
        """
        _ = resource_type
        _ = resource_id
        return []

    # ---- auth_migration_state:JSON 元数据存储(PR-11 迁 K/V 表) --------

    def read_auth_migration_state(self) -> AuthMigrationStateFile:
        """读 `auth_migration_state.json` · 复用 JsonStore 稳定序列化。

        **原因**:0006/0007 schema 未建 K/V 元数据表 · 本 PR 不扩表 ·
        `auth_migration_state` 是 bootstrap 期一次性元数据 · 沿用 JSON 元数据
        存储成本更低 · 语义留权限 PR-11 迁到 K/V 表(独立 migration)。
        """
        base_dir = self._get_base_dir()
        state_file = base_dir / "auth_migration_state.json"
        if not state_file.is_file():
            raise FileNotFoundError(
                f"identity JSON 文件缺失:{state_file}"
                f"(请先跑 tools/migrate_identity_bootstrap.py)"
            )
        with state_file.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
        return validate_auth_migration_state_file(payload)

    def write_auth_migration_state(
        self, state: AuthMigrationStateFile
    ) -> None:
        """整体覆盖 `auth_migration_state.json` · 幂等字节稳定。

        校验后原子写入 · 稳定序列化保证多次相同内容写入产生字节相同的文件
        (与 `JsonIdentityStore.write_auth_migration_state` 语义等价)。
        """
        validate_auth_migration_state_file(state)
        base_dir = self._get_base_dir()
        base_dir.mkdir(parents=True, exist_ok=True)
        state_file = base_dir / "auth_migration_state.json"
        text = json.dumps(
            state,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        tmp = state_file.with_suffix(state_file.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.write("\n")
        tmp.replace(state_file)


# ---------------------------------------------------------------------------
# Env flag + factory(D-env · GM-22 defaults-off · 第 13 次复用)
# ---------------------------------------------------------------------------

IDENTITY_STORE_BACKEND_ENV = "IDENTITY_STORE_BACKEND"
"""env key · 值 `"json"`(默认)或 `"sqlite"` · 大小写不敏感。"""

_VALID_BACKENDS: FrozenSet[str] = frozenset({"json", "sqlite"})


def get_identity_store_backend() -> str:
    """读 `IDENTITY_STORE_BACKEND` env · 默认 `"json"` · 非法值降级 `"json"`。

    参照现有 pattern:
    - `IDENTITY_BRIDGE_ENFORCE`(权限 PR-9)· 三档语义
    - `PERMISSION_SERVICE_ENFORCE`(权限 PR-4)· 二档语义

    本 flag 二档:`json`(默认) / `sqlite`。非法值(拼错 / 遗留)恒回退
    `json` 保证升级过程零副作用(GM-22 defaults-off pattern 第 13 次复用)。
    """
    raw = os.environ.get(IDENTITY_STORE_BACKEND_ENV, "").strip().lower()
    if raw not in _VALID_BACKENDS:
        return "json"
    return raw


def get_identity_store(
    base_dir: Optional[Path] = None,
    session_factory: Optional[Callable[[], Any]] = None,
) -> IdentityStore:
    """按 `IDENTITY_STORE_BACKEND` env 分派 · 返回 JsonIdentityStore 或
    SqliteIdentityStore 实例。

    Args:
        base_dir: JsonStore 的 identity JSON 目录 · SqliteStore 的
            `auth_migration_state.json` 目录。默认 `data/identity`。
        session_factory: 仅 SqliteStore 消费 · 默认懒 import `SessionLocal`。

    Returns:
        JsonIdentityStore 或 SqliteIdentityStore 实例(满足 `IdentityStore`
        Protocol · 类型不透)。

    **本 PR 不改任何调用点**:调用方消费 factory 归权限 PR-11 后续改造。
    """
    backend = get_identity_store_backend()
    if backend == "sqlite":
        return SqliteIdentityStore(
            session_factory=session_factory, base_dir=base_dir
        )  # type: ignore[return-value]
    # 默认 json · base_dir None 时 JsonStore 用当前工作目录 · 消费方自负责传入
    default_dir = base_dir if base_dir else Path("data/identity")
    return JsonIdentityStore(default_dir)  # type: ignore[return-value]


__all__ = [
    "IdentityStore",
    "JsonIdentityStore",
    "SqliteIdentityStore",
    "SQLITE_USER_PUBLIC_FIELDS",
    "IDENTITY_STORE_BACKEND_ENV",
    "get_identity_store_backend",
    "get_identity_store",
]
