"""契约等价性锁 · JsonIdentityStore vs SqliteIdentityStore 语义等价
(权限 PR-10 · Wave 3-N.9 Batch 3 主线 A · Lead 圆桌决议 α+δ+η)。

**目的**:同一批 fixture 数据分别喂给两个实现 · 断言 10 方法返回值语义等价。

**等价性等级**(依 Lead 圆桌决议):
- 冲突 A 决议 α:`list_memberships` 的 project 端两侧都是空 list · shape 一致
- 冲突 B 决议 δ:`get_user` 用**公共键集子集**等价(6 键子集 value 全等)
- 冲突 C 决议 η:`list_role_permissions` 两侧空 seed → 空 dict 严格 == 等价
- `get_resource_acl`:两侧都空 list(schema 未建 · JSON 侧治理期空)
- `read/write_auth_migration_state`:两侧共享同一 JSON 文件 · 序列化字节相同

**fixture**:一份 identity JSON dir + 一份 alembic 建表 + 手动 SQL seed
写入等价数据 · 覆盖 2 user + 3 alias + 2 workspace + 2 membership + 2 role
+ 空 role_permissions + 空 resource_acl + auth_migration_state。
"""
from __future__ import annotations

import json
import uuid as _uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import pytest

from tests.shadow_read._helpers import isolated_shadow_env, migrate_baseline


# ---------------------------------------------------------------------------
# 共享 fixture 数据
# ---------------------------------------------------------------------------

FIXTURE_TS_STR = "2026-07-20T10:00:00+00:00"
FIXTURE_TS = datetime(2026, 7, 20, 10, 0, 0, tzinfo=timezone.utc)

USER_1_ID = _uuid.UUID("11111111-1111-1111-1111-111111111111")
USER_2_ID = _uuid.UUID("22222222-2222-2222-2222-222222222222")
WS_1_ID = _uuid.UUID("33333333-3333-3333-3333-333333333333")
WS_2_ID = _uuid.UUID("44444444-4444-4444-4444-444444444444")
MEM_1_ID = _uuid.UUID("55555555-5555-5555-5555-555555555555")
MEM_2_ID = _uuid.UUID("66666666-6666-6666-6666-666666666666")
ALIAS_1_ID = _uuid.UUID("77777777-7777-7777-7777-777777777777")
ALIAS_2_ID = _uuid.UUID("88888888-8888-8888-8888-888888888888")
ROLE_1_ID = _uuid.UUID("99999999-9999-9999-9999-999999999999")
ROLE_2_ID = _uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


def _write_json(p: Path, payload: Any) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


@pytest.fixture
def json_dir(tmp_path: Path) -> Path:
    """构造等价的 identity JSON 目录。"""
    base = tmp_path / "identity_json"
    _write_json(
        base / "users.json",
        {
            "_schema_version": 1,
            "users": {
                str(USER_1_ID): {
                    "id": str(USER_1_ID),
                    "username": "alice",  # 冗余(δ:不在 SQLite subset)
                    "status": "active",
                    "created_at": FIXTURE_TS_STR,
                    "updated_at": FIXTURE_TS_STR,
                    "legacy_user_key": "legacy-1",
                    "display_name": "Alice",
                    "avatar_url": "https://example.com/a.png",
                },
                str(USER_2_ID): {
                    "id": str(USER_2_ID),
                    "username": "bob",
                    "status": "active",
                    "created_at": FIXTURE_TS_STR,
                    "updated_at": FIXTURE_TS_STR,
                    "legacy_user_key": None,
                    "display_name": "Bob",
                    "avatar_url": None,
                },
            },
        },
    )
    _write_json(
        base / "user_aliases.json",
        {
            "_schema_version": 1,
            "aliases": [
                {
                    "id": str(ALIAS_1_ID),
                    "user_id": str(USER_1_ID),
                    "kind": "x_user_id",
                    "legacy_user_key": "alias-key-1",
                    "created_at": FIXTURE_TS_STR,
                },
                {
                    "id": str(ALIAS_2_ID),
                    "user_id": str(USER_2_ID),
                    "kind": "x_user_id",
                    "legacy_user_key": "alias-key-2",
                    "created_at": FIXTURE_TS_STR,
                },
            ],
        },
    )
    _write_json(
        base / "workspaces.json",
        {
            "_schema_version": 1,
            "workspaces": {
                str(WS_1_ID): {
                    "id": str(WS_1_ID),
                    "name": "ws-alpha",
                    "description": None,
                    "created_at": FIXTURE_TS_STR,
                    "updated_at": FIXTURE_TS_STR,
                },
                str(WS_2_ID): {
                    "id": str(WS_2_ID),
                    "name": "ws-beta",
                    "description": "second",
                    "created_at": FIXTURE_TS_STR,
                    "updated_at": FIXTURE_TS_STR,
                },
            },
        },
    )
    _write_json(
        base / "memberships.json",
        {
            "_schema_version": 1,
            "workspace_memberships": [
                {
                    "workspace_id": str(WS_1_ID),
                    "user_id": str(USER_1_ID),
                    "role": "workspace_admin",
                    "created_at": FIXTURE_TS_STR,
                },
                {
                    "workspace_id": str(WS_2_ID),
                    "user_id": str(USER_1_ID),
                    "role": "member",
                    "created_at": FIXTURE_TS_STR,
                },
            ],
            "project_memberships": [],  # 冲突 A α:两侧都空
        },
    )
    _write_json(
        base / "roles.json",
        {
            "_schema_version": 1,
            "roles": {},  # 与 SQLite seed 都是 empty permissions_json 语义等价
        },
    )
    _write_json(
        base / "role_permissions.json",
        {
            "_schema_version": 1,
            "role_permissions": {},  # 冲突 C η:两侧都返回 `{}`
        },
    )
    _write_json(
        base / "resource_acl.json",
        {"_schema_version": 1, "acl": []},  # 两侧都空
    )
    _write_json(
        base / "auth_migration_state.json",
        {
            "_schema_version": 1,
            "bootstrap_completed_at": None,
            "legacy_mapping_completed_at": None,
            "notes": [],
        },
    )
    return base


@pytest.fixture
def isolated_env(monkeypatch, tmp_path):
    with isolated_shadow_env(monkeypatch, tmp_path) as sandbox:
        yield sandbox


@pytest.fixture
def sqlite_seeded(isolated_env, json_dir):
    """alembic head + 手动 seed 等价数据到 SQLite。"""
    migrate_baseline(isolated_env)
    from app.db.session import get_session
    from app.identity.tables import (
        membership_table,
        user_alias_table,
        user_table,
        workspace_table,
    )

    with get_session() as session:
        session.execute(
            user_table.insert().values(
                id=USER_1_ID,
                legacy_user_key="legacy-1",
                display_name="Alice",
                avatar_url="https://example.com/a.png",
                created_at=FIXTURE_TS,
                updated_at=FIXTURE_TS,
            )
        )
        session.execute(
            user_table.insert().values(
                id=USER_2_ID,
                legacy_user_key=None,
                display_name="Bob",
                avatar_url=None,
                created_at=FIXTURE_TS,
                updated_at=FIXTURE_TS,
            )
        )
        session.execute(
            workspace_table.insert().values(
                id=WS_1_ID,
                name="ws-alpha",
                kind="system",
                raw_json=None,
                created_at=FIXTURE_TS,
                updated_at=FIXTURE_TS,
            )
        )
        session.execute(
            workspace_table.insert().values(
                id=WS_2_ID,
                name="ws-beta",
                kind="system",
                raw_json=json.dumps({"description": "second"}),
                created_at=FIXTURE_TS,
                updated_at=FIXTURE_TS,
            )
        )
        session.execute(
            membership_table.insert().values(
                id=MEM_1_ID,
                user_id=USER_1_ID,
                workspace_id=WS_1_ID,
                role="workspace_admin",
                created_at=FIXTURE_TS,
                updated_at=FIXTURE_TS,
            )
        )
        session.execute(
            membership_table.insert().values(
                id=MEM_2_ID,
                user_id=USER_1_ID,
                workspace_id=WS_2_ID,
                role="member",
                created_at=FIXTURE_TS,
                updated_at=FIXTURE_TS,
            )
        )
        session.execute(
            user_alias_table.insert().values(
                id=ALIAS_1_ID,
                user_id=USER_1_ID,
                legacy_user_key="alias-key-1",
                raw_json=json.dumps({"kind": "x_user_id"}),
                created_at=FIXTURE_TS,
                updated_at=FIXTURE_TS,
            )
        )
        session.execute(
            user_alias_table.insert().values(
                id=ALIAS_2_ID,
                user_id=USER_2_ID,
                legacy_user_key="alias-key-2",
                raw_json=json.dumps({"kind": "x_user_id"}),
                created_at=FIXTURE_TS,
                updated_at=FIXTURE_TS,
            )
        )
    return isolated_env


@pytest.fixture
def two_stores(sqlite_seeded, json_dir):
    """返回 (json_store, sqlite_store) 元组 · 供逐方法比对。"""
    from app.identity.store import JsonIdentityStore, SqliteIdentityStore

    json_store = JsonIdentityStore(json_dir)
    sqlite_store = SqliteIdentityStore(base_dir=json_dir)
    return json_store, sqlite_store


# ---------------------------------------------------------------------------
# 契约等价性 · 逐方法
# ---------------------------------------------------------------------------


def _public_subset(user_dict: Dict[str, Any]) -> Dict[str, Any]:
    """冲突 B 决议 δ:提取 6 键 public subset 用于比对。"""
    return {
        k: user_dict.get(k)
        for k in (
            "id",
            "legacy_user_key",
            "display_name",
            "avatar_url",
            "created_at",
            "updated_at",
        )
    }


def test_parity_get_user_public_subset(two_stores):
    """冲突 B 决议 δ:6 键 public subset value 全等。"""
    json_store, sqlite_store = two_stores
    json_user = json_store.get_user(str(USER_1_ID))
    sqlite_user = sqlite_store.get_user(str(USER_1_ID))
    assert json_user is not None
    assert sqlite_user is not None
    # SQLite 侧只有 6 键 · JSON 侧多含 username/status(不比)
    assert _public_subset(json_user) == _public_subset(sqlite_user)


def test_parity_get_user_returns_none_when_missing(two_stores):
    """不存在的 user_id 两侧都返回 None。"""
    json_store, sqlite_store = two_stores
    missing = str(_uuid.uuid4())
    assert json_store.get_user(missing) is None
    assert sqlite_store.get_user(missing) is None


def test_parity_find_alias(two_stores):
    """find_alias 两侧命中同一条 · legacy_user_key + user_id 相等。"""
    json_store, sqlite_store = two_stores
    j = json_store.find_alias("x_user_id", "alias-key-1")
    s = sqlite_store.find_alias("x_user_id", "alias-key-1")
    assert j is not None and s is not None
    assert j["legacy_user_key"] == s["legacy_user_key"]
    assert j["user_id"] == s["user_id"]
    assert j["kind"] == s["kind"]


def test_parity_list_workspaces_count_and_names(two_stores):
    """两侧返回同样多 workspace(2 个) · name 集合相等。

    注意:SQLite 侧 alembic 0006 seed 会额外插一个 'system' workspace · 忽略 seed。
    """
    json_store, sqlite_store = two_stores
    j = json_store.list_workspaces()
    s = sqlite_store.list_workspaces()
    # 过滤掉 0006 seed 的 system workspace(name='system')
    s_test = [w for w in s if w["name"] != "system"]
    assert len(j) == len(s_test) == 2
    j_names = sorted(w["name"] for w in j)
    s_names = sorted(w["name"] for w in s_test)
    assert j_names == s_names


def test_parity_list_memberships_workspace_end(two_stores):
    """workspace 端语义等价:2 条 · role 集合相等。"""
    json_store, sqlite_store = two_stores
    j = json_store.list_memberships(str(USER_1_ID))
    s = sqlite_store.list_memberships(str(USER_1_ID))
    # workspace 端 2 条
    assert len(j["workspace"]) == 2
    assert len(s["workspace"]) == 2
    j_roles = sorted(m["role"] for m in j["workspace"])
    s_roles = sorted(m["role"] for m in s["workspace"])
    assert j_roles == s_roles


def test_parity_list_memberships_project_end_both_empty(two_stores):
    """冲突 A 决议 α:两侧 project 端都是空 list。"""
    json_store, sqlite_store = two_stores
    j = json_store.list_memberships(str(USER_1_ID))
    s = sqlite_store.list_memberships(str(USER_1_ID))
    assert j["project"] == []
    assert s["project"] == []


def test_parity_list_role_permissions_both_empty(two_stores):
    """冲突 C 决议 η:两侧 seed 全空 → 严格 == `{}`。"""
    json_store, sqlite_store = two_stores
    assert json_store.list_role_permissions() == {}
    assert sqlite_store.list_role_permissions() == {}


def test_parity_get_resource_acl_both_empty(two_stores):
    """resource_acl 两侧都返回空 list。"""
    json_store, sqlite_store = two_stores
    assert json_store.get_resource_acl("canvas", "canvas-x") == []
    assert sqlite_store.get_resource_acl("canvas", "canvas-x") == []


def test_parity_read_auth_migration_state(two_stores):
    """两侧读同一 JSON · 内容相等。"""
    json_store, sqlite_store = two_stores
    j = json_store.read_auth_migration_state()
    s = sqlite_store.read_auth_migration_state()
    assert j == s


def test_parity_write_auth_migration_state_byte_stable(two_stores, json_dir):
    """两侧 write 相同 state · 生成的文件字节相同。"""
    json_store, sqlite_store = two_stores
    new_state = {
        "_schema_version": 1,
        "bootstrap_completed_at": "2026-07-20T10:00:00+00:00",
        "legacy_mapping_completed_at": None,
        "notes": ["parity"],
    }
    json_store.write_auth_migration_state(new_state)
    json_bytes = (json_dir / "auth_migration_state.json").read_bytes()
    sqlite_store.write_auth_migration_state(new_state)
    sqlite_bytes = (json_dir / "auth_migration_state.json").read_bytes()
    assert json_bytes == sqlite_bytes
