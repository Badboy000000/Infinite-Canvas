"""`app.identity.tables` — Identity 层 SQLAlchemy `Table` 定义(权限 PR-10)。

**定位**:与 `app.services.auth.tables` 平行组织 · 定义 6 张 identity 核心表
的 SQLAlchemy Core `Table` 单例 · 供 `SqliteIdentityStore` 消费。

**硬约束**:
- 6 张表的字段清单**逐字对齐** `app/db/migrations/versions/0006_identity.py`
  已建 DDL · **不新增字段** · 不新增 migration。
- 所有 `Table` 必须挂到 `from app.db.base import metadata` 单例上
  (与 `app/services/auth/tables.py` 一致)· 保证 `env.py::target_metadata`
  能感知 schema 事实。
- 类型选择:
    - 主键 / FK UUID 走 `sqlalchemy.types.Uuid(as_uuid=True)`
      (SQLAlchemy 2.0 portable 类型 · SQLite → CHAR(36) / PostgreSQL → uuid)
    - 时间戳走 `DateTime(timezone=True)`
    - 文本走 `Text`

**GM-16 pre-flight**(codegraph_explore 已跑 · 2026-07-25):
- `app.identity.tables` 模块 = greenfield
- 6 张 Table 变量名(`user_table` / `workspace_table` / `membership_table` /
  `role_table` / `permission_table` / `user_alias_table`)= greenfield
- 变量名带 `_table` 后缀避免与 `user` / `role` 等 SQL 关键字混淆

**决策边界备案**(Lead 圆桌 2026-07-25):
- 冲突 A 决议 α:`membership` 表本 PR 只映射 workspace membership · project
  membership 语义留权限 PR-11 承接(schema 需扩 `project_id` 列 · 走独立 CB)
- 冲突 B 决议 δ:`user` 表只承载 6 列 public subset · 冗余 JSON 字段
  (username / status / email)不跨层污染
- 冲突 C 决议 η:`role.permissions_json` 空 seed 反序列化为 `{}` · 与
  JsonStore 空 dict 等价

**本 PR 不做**:
- 不建 `resource_acl` 表(schema 未建 · `get_resource_acl` 恒返回 `[]`)
- 不新增 migration(消费 0006_identity 已建表)
- 不定义任何 ORM 聚合根类(仅 Core Table)
"""
from __future__ import annotations

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.types import Uuid

from app.db.base import metadata

# ---------------------------------------------------------------------------
# user 表 · 0006_identity L89-97
# ---------------------------------------------------------------------------

user_table = Table(
    "user",
    metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True, nullable=False),
    Column("legacy_user_key", Text, nullable=True),
    Column("display_name", Text, nullable=True),
    Column("avatar_url", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    extend_existing=True,
)

# ---------------------------------------------------------------------------
# workspace 表 · 0006_identity L102-111
# ---------------------------------------------------------------------------

workspace_table = Table(
    "workspace",
    metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True, nullable=False),
    Column("name", Text, nullable=False),
    Column("kind", Text, nullable=False, server_default="system"),
    Column("raw_json", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    extend_existing=True,
)

# ---------------------------------------------------------------------------
# membership 表 · 0006_identity L116-143
# ---------------------------------------------------------------------------

membership_table = Table(
    "membership",
    metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True, nullable=False),
    Column(
        "user_id",
        Uuid(as_uuid=True),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "workspace_id",
        Uuid(as_uuid=True),
        ForeignKey("workspace.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("role", Text, nullable=False, server_default="member"),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("user_id", "workspace_id", name="uq_membership_user_workspace"),
    extend_existing=True,
)

# ---------------------------------------------------------------------------
# role 表 · 0006_identity L148-158
# ---------------------------------------------------------------------------

role_table = Table(
    "role",
    metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True, nullable=False),
    Column("name", Text, nullable=False),
    Column("permissions_json", Text, nullable=True),
    Column("raw_json", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("name", name="uq_role_name"),
    extend_existing=True,
)

# ---------------------------------------------------------------------------
# permission 表 · 0006_identity L163-172
# ---------------------------------------------------------------------------

permission_table = Table(
    "permission",
    metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True, nullable=False),
    Column("code", Text, nullable=False),
    Column("description", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("code", name="uq_permission_code"),
    extend_existing=True,
)

# ---------------------------------------------------------------------------
# user_alias 表 · 0006_identity L177-201
# ---------------------------------------------------------------------------

user_alias_table = Table(
    "user_alias",
    metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True, nullable=False),
    Column(
        "user_id",
        Uuid(as_uuid=True),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("legacy_user_key", Text, nullable=False),
    Column("raw_json", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("legacy_user_key", name="uq_user_alias_legacy_user_key"),
    extend_existing=True,
)


#: 本 PR 消费的 6 张 identity 表名(供测试断言使用)。
IDENTITY_TABLE_NAMES = (
    "user",
    "workspace",
    "membership",
    "role",
    "permission",
    "user_alias",
)


__all__ = [
    "user_table",
    "workspace_table",
    "membership_table",
    "role_table",
    "permission_table",
    "user_alias_table",
    "IDENTITY_TABLE_NAMES",
]
