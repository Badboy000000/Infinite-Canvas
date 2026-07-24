"""`SqliteIdentityStore` 契约测试(权限 PR-10 · Wave 3-N.9 Batch 3 主线 A)。

**测试范围**:
- 空数据 fixture 下 10 方法契约(与 JsonIdentityStore 语义等价)
- Seeded fixture 下 workspace / role / membership 语义等价
- `get_user` 6 键 public subset(冲突 B 决议 δ)
- `list_memberships` project 端硬编码空 list(冲突 A 决议 α)
- `list_role_permissions` 空 seed 过滤为 `{}`(冲突 C 决议 η)
- `get_resource_acl` 恒返回 `[]`
- `write_auth_migration_state` 幂等字节稳定(与 JsonStore 相同)
- factory `get_identity_store()` 按 env flag 分派

**fixture 策略**:复用 `tests/shadow_read/_helpers.py` 的
`isolated_shadow_env` + `migrate_baseline` · alembic upgrade head 建 6 张
identity 表 · 手动 seed 测试数据。
"""
from __future__ import annotations

import json
import uuid as _uuid
from pathlib import Path

import pytest

from tests.shadow_read._helpers import isolated_shadow_env, migrate_baseline


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_env(monkeypatch, tmp_path):
    with isolated_shadow_env(monkeypatch, tmp_path) as sandbox:
        yield sandbox


@pytest.fixture
def migrated_env(isolated_env):
    """alembic upgrade head · 建 identity 6 张表 · 返回 tmp_path。"""
    migrate_baseline(isolated_env)
    yield isolated_env


@pytest.fixture
def identity_base_dir(migrated_env, tmp_path) -> Path:
    """auth_migration_state.json 存放目录 · 建空占位。"""
    base = tmp_path / "identity"
    base.mkdir(parents=True, exist_ok=True)
    (base / "auth_migration_state.json").write_text(
        json.dumps(
            {
                "_schema_version": 1,
                "bootstrap_completed_at": None,
                "legacy_mapping_completed_at": None,
                "notes": [],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return base


@pytest.fixture
def sqlite_store(migrated_env, identity_base_dir):
    """SqliteIdentityStore 实例 · migrated_env 已 alembic upgrade head。"""
    from app.identity.store import SqliteIdentityStore

    return SqliteIdentityStore(base_dir=identity_base_dir)


def _seed_user(session, *, uid, legacy_key=None, display_name=None, avatar=None, ts=None):
    from datetime import datetime, timezone

    from app.identity.tables import user_table

    if ts is None:
        ts = datetime(2026, 7, 20, 0, 0, 0, tzinfo=timezone.utc)
    session.execute(
        user_table.insert().values(
            id=uid,
            legacy_user_key=legacy_key,
            display_name=display_name,
            avatar_url=avatar,
            created_at=ts,
            updated_at=ts,
        )
    )


def _seed_workspace(session, *, wid, name, kind="system", raw_json=None, ts=None):
    from datetime import datetime, timezone

    from app.identity.tables import workspace_table

    if ts is None:
        ts = datetime(2026, 7, 20, 0, 0, 0, tzinfo=timezone.utc)
    session.execute(
        workspace_table.insert().values(
            id=wid,
            name=name,
            kind=kind,
            raw_json=raw_json,
            created_at=ts,
            updated_at=ts,
        )
    )


def _seed_membership(session, *, mid, uid, wid, role="member", ts=None):
    from datetime import datetime, timezone

    from app.identity.tables import membership_table

    if ts is None:
        ts = datetime(2026, 7, 20, 0, 0, 0, tzinfo=timezone.utc)
    session.execute(
        membership_table.insert().values(
            id=mid,
            user_id=uid,
            workspace_id=wid,
            role=role,
            created_at=ts,
            updated_at=ts,
        )
    )


def _seed_role(session, *, rid, name, permissions_json="{}", raw_json="{}", ts=None):
    from datetime import datetime, timezone

    from app.identity.tables import role_table

    if ts is None:
        ts = datetime(2026, 7, 20, 0, 0, 0, tzinfo=timezone.utc)
    session.execute(
        role_table.insert().values(
            id=rid,
            name=name,
            permissions_json=permissions_json,
            raw_json=raw_json,
            created_at=ts,
            updated_at=ts,
        )
    )


def _seed_alias(session, *, aid, uid, legacy_key, raw_json=None, ts=None):
    from datetime import datetime, timezone

    from app.identity.tables import user_alias_table

    if ts is None:
        ts = datetime(2026, 7, 20, 0, 0, 0, tzinfo=timezone.utc)
    session.execute(
        user_alias_table.insert().values(
            id=aid,
            user_id=uid,
            legacy_user_key=legacy_key,
            raw_json=raw_json,
            created_at=ts,
            updated_at=ts,
        )
    )


# ---------------------------------------------------------------------------
# 契约锁 · 空 DB 语义
# ---------------------------------------------------------------------------


def test_sqlite_store_impl_get_user_returns_none_when_empty(sqlite_store):
    """空 DB · get_user 任何 id 都返回 None(0006 seed 有 3 role · 无 user)。"""
    assert sqlite_store.get_user(str(_uuid.uuid4())) is None


def test_sqlite_store_impl_find_alias_returns_none_when_empty(sqlite_store):
    """空 DB · find_alias 任何 key 返回 None。"""
    assert sqlite_store.find_alias("x_user_id", "any-key") is None


def test_sqlite_store_impl_returns_empty_resource_acl_pr10_scope(sqlite_store):
    """resource_acl 表未建 · 恒返回空 list(PR-11 承接)。"""
    assert sqlite_store.get_resource_acl("canvas", "canvas-x") == []


def test_sqlite_store_impl_list_user_aliases_empty(sqlite_store):
    """空 DB · list_user_aliases 返回空 list。"""
    assert sqlite_store.list_user_aliases() == []


def test_sqlite_store_impl_list_memberships_empty(sqlite_store):
    """空 DB + 任意 user_id · workspace + project 都空。"""
    result = sqlite_store.list_memberships(str(_uuid.uuid4()))
    assert result == {"workspace": [], "project": []}


# ---------------------------------------------------------------------------
# 契约锁 · seeded DB 语义
# ---------------------------------------------------------------------------


def test_sqlite_store_impl_get_user_returns_public_field_subset(
    sqlite_store, migrated_env
):
    """PR-10 冲突 B 决议 δ:get_user 返回 dict 精确含 6 键 public subset。"""
    from app.db.session import get_session

    uid = _uuid.uuid4()
    with get_session() as session:
        _seed_user(
            session,
            uid=uid,
            legacy_key="legacy-abc",
            display_name="Alice",
            avatar="https://example.com/a.png",
        )

    result = sqlite_store.get_user(str(uid))
    assert result is not None
    # 精确 6 键(public field subset · 无 username/status/email)
    assert set(result.keys()) == {
        "id",
        "legacy_user_key",
        "display_name",
        "avatar_url",
        "created_at",
        "updated_at",
    }
    assert result["id"] == str(uid)
    assert result["legacy_user_key"] == "legacy-abc"
    assert result["display_name"] == "Alice"
    assert result["avatar_url"] == "https://example.com/a.png"


def test_sqlite_store_impl_list_workspaces_ordered_by_created_at(
    sqlite_store, migrated_env
):
    """list_workspaces 按 created_at 升序稳定输出。"""
    from datetime import datetime, timezone

    from app.db.session import get_session

    w1 = _uuid.uuid4()
    w2 = _uuid.uuid4()
    ts1 = datetime(2026, 7, 20, 10, 0, 0, tzinfo=timezone.utc)
    ts2 = datetime(2026, 7, 20, 12, 0, 0, tzinfo=timezone.utc)
    with get_session() as session:
        _seed_workspace(session, wid=w1, name="ws-A", ts=ts1)
        _seed_workspace(session, wid=w2, name="ws-B", ts=ts2)

    workspaces = sqlite_store.list_workspaces()
    # 0006_identity 已 seed 一个 system workspace + 本测试的 2 个 = 3 个
    names = [w["name"] for w in workspaces]
    assert "ws-A" in names
    assert "ws-B" in names
    # 找出本测试 seed 的两个 · 断言顺序
    a_idx = names.index("ws-A")
    b_idx = names.index("ws-B")
    assert a_idx < b_idx, "ws-A(earlier ts) 应先于 ws-B(later ts)"


def test_sqlite_store_impl_list_memberships_partitions_workspace_vs_project(
    sqlite_store, migrated_env
):
    """冲突 A 决议 α:workspace 端有数据 · project 端硬编码空 list。"""
    from app.db.session import get_session

    uid = _uuid.uuid4()
    wid = _uuid.uuid4()
    mid = _uuid.uuid4()
    with get_session() as session:
        _seed_user(session, uid=uid)
        _seed_workspace(session, wid=wid, name="ws-1")
        _seed_membership(session, mid=mid, uid=uid, wid=wid, role="workspace_admin")

    result = sqlite_store.list_memberships(str(uid))
    assert set(result.keys()) == {"workspace", "project"}
    assert len(result["workspace"]) == 1
    assert result["workspace"][0]["role"] == "workspace_admin"
    assert result["workspace"][0]["user_id"] == str(uid)
    assert result["workspace"][0]["workspace_id"] == str(wid)
    # 冲突 A 决议 α:project 端**硬编码**空 list
    assert result["project"] == []


def test_sqlite_store_impl_list_roles_ordered_by_key(sqlite_store, migrated_env):
    """list_roles 按 name 升序(0006_identity 已 seed 3 role:admin/member/viewer)。"""
    roles = sqlite_store.list_roles()
    # 0006_identity seed:admin / member / viewer
    keys = [r["key"] for r in roles]
    assert keys == sorted(keys), f"roles 未按 name 升序:{keys}"
    # 至少包含 seed 的 3 项
    assert "admin" in keys
    assert "member" in keys
    assert "viewer" in keys


def test_sqlite_store_impl_list_role_permissions_matches_role_permissions_json(
    sqlite_store, migrated_env
):
    """冲突 C 决议 η:seed 全空 `'{}'` → 过滤 → 返回 `{}`。"""
    # 0006_identity seed 的 3 role 都是 permissions_json='{}' · 应全部过滤
    result = sqlite_store.list_role_permissions()
    # 严格 == 空 dict(与 JsonStore role_permissions.json 空 map 等价)
    assert result == {}


def test_sqlite_store_impl_list_role_permissions_emits_non_empty(
    sqlite_store, migrated_env
):
    """冲突 C 决议 η 反例:非空 permissions_json seed 会被 emit。"""
    from app.db.session import get_session

    rid = _uuid.uuid4()
    with get_session() as session:
        _seed_role(
            session,
            rid=rid,
            name="test_role_pr10",
            permissions_json=json.dumps({"canvas:read": True, "canvas:write": False}),
        )

    result = sqlite_store.list_role_permissions()
    assert "test_role_pr10" in result
    assert result["test_role_pr10"] == {"canvas:read": True, "canvas:write": False}


def test_sqlite_store_impl_find_alias_matches_by_legacy_key(
    sqlite_store, migrated_env
):
    """find_alias 按 legacy_user_key 匹配(schema 未扩 kind 列 · kind 参数忽略)。"""
    from app.db.session import get_session

    uid = _uuid.uuid4()
    aid = _uuid.uuid4()
    with get_session() as session:
        _seed_user(session, uid=uid)
        _seed_alias(
            session,
            aid=aid,
            uid=uid,
            legacy_key="legacy-target",
            raw_json=json.dumps({"kind": "x_user_id"}),
        )

    result = sqlite_store.find_alias("x_user_id", "legacy-target")
    assert result is not None
    assert result["legacy_user_key"] == "legacy-target"
    assert result["user_id"] == str(uid)
    assert result["kind"] == "x_user_id"


def test_sqlite_store_impl_list_user_aliases_ordered(sqlite_store, migrated_env):
    """list_user_aliases 稳定按 created_at 升序返回。"""
    from datetime import datetime, timezone

    from app.db.session import get_session

    uid = _uuid.uuid4()
    a1 = _uuid.uuid4()
    a2 = _uuid.uuid4()
    ts1 = datetime(2026, 7, 20, 10, 0, 0, tzinfo=timezone.utc)
    ts2 = datetime(2026, 7, 20, 12, 0, 0, tzinfo=timezone.utc)
    with get_session() as session:
        _seed_user(session, uid=uid)
        _seed_alias(session, aid=a1, uid=uid, legacy_key="key-1", ts=ts1)
        _seed_alias(session, aid=a2, uid=uid, legacy_key="key-2", ts=ts2)

    aliases = sqlite_store.list_user_aliases()
    keys = [a["legacy_user_key"] for a in aliases]
    assert keys.index("key-1") < keys.index("key-2")


# ---------------------------------------------------------------------------
# 契约锁 · auth_migration_state 幂等序列化(与 JsonStore 相同)
# ---------------------------------------------------------------------------


def test_sqlite_store_impl_round_trip_write_read_auth_migration_state(sqlite_store):
    """write → read 往返 · 内容一致。"""
    new_state = {
        "_schema_version": 1,
        "bootstrap_completed_at": "2026-07-20T00:00:00+00:00",
        "legacy_mapping_completed_at": None,
        "notes": ["pr10-test"],
    }
    sqlite_store.write_auth_migration_state(new_state)
    reread = sqlite_store.read_auth_migration_state()
    assert reread["bootstrap_completed_at"] == "2026-07-20T00:00:00+00:00"
    assert reread["notes"] == ["pr10-test"]


def test_sqlite_store_impl_write_auth_migration_state_idempotent(
    sqlite_store, identity_base_dir
):
    """两次写同内容产生字节相同文件(与 JsonStore 相同幂等语义)。"""
    new_state = {
        "_schema_version": 1,
        "bootstrap_completed_at": "2026-07-20T00:00:00+00:00",
        "legacy_mapping_completed_at": None,
        "notes": ["idempotent"],
    }
    sqlite_store.write_auth_migration_state(new_state)
    first = (identity_base_dir / "auth_migration_state.json").read_bytes()
    sqlite_store.write_auth_migration_state(new_state)
    second = (identity_base_dir / "auth_migration_state.json").read_bytes()
    assert first == second


# ---------------------------------------------------------------------------
# 契约锁 · factory 与 env flag 分派
# ---------------------------------------------------------------------------


def test_get_identity_store_default_json(monkeypatch, tmp_path):
    """默认 env(未设 IDENTITY_STORE_BACKEND)→ JsonIdentityStore。"""
    from app.identity.store import JsonIdentityStore, get_identity_store

    monkeypatch.delenv("IDENTITY_STORE_BACKEND", raising=False)
    # 建空 identity dir 让 JsonStore 构造不 raise
    base = tmp_path / "identity"
    base.mkdir()
    store = get_identity_store(base_dir=base)
    assert isinstance(store, JsonIdentityStore)


def test_get_identity_store_sqlite_flag(monkeypatch, tmp_path):
    """IDENTITY_STORE_BACKEND=sqlite → SqliteIdentityStore。"""
    from app.identity.store import SqliteIdentityStore, get_identity_store

    monkeypatch.setenv("IDENTITY_STORE_BACKEND", "sqlite")
    store = get_identity_store(base_dir=tmp_path)
    assert isinstance(store, SqliteIdentityStore)


def test_get_identity_store_illegal_env_falls_back_to_json(monkeypatch, tmp_path):
    """非法 env 值降级 json(GM-22 defaults-off pattern)。"""
    from app.identity.store import JsonIdentityStore, get_identity_store

    monkeypatch.setenv("IDENTITY_STORE_BACKEND", "banana")
    base = tmp_path / "identity"
    base.mkdir()
    store = get_identity_store(base_dir=base)
    assert isinstance(store, JsonIdentityStore)


def test_get_identity_store_backend_case_insensitive(monkeypatch):
    """env 值大小写不敏感。"""
    from app.identity.store import get_identity_store_backend

    monkeypatch.setenv("IDENTITY_STORE_BACKEND", "SQLITE")
    assert get_identity_store_backend() == "sqlite"
    monkeypatch.setenv("IDENTITY_STORE_BACKEND", "  Json  ")
    assert get_identity_store_backend() == "json"
