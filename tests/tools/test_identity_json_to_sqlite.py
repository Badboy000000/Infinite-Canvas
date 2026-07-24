"""`identity_json_to_sqlite.py` CLI 测试(权限 PR-10)。

覆盖 --dry-run / --apply / --verify 三档 + 幂等实证。
"""
from __future__ import annotations

import json
import uuid as _uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tests.shadow_read._helpers import isolated_shadow_env, migrate_baseline


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


FIXTURE_TS_STR = "2026-07-20T10:00:00+00:00"
USER_1_ID = "11111111-1111-1111-1111-111111111111"
USER_2_ID = "22222222-2222-2222-2222-222222222222"
WS_1_ID = "33333333-3333-3333-3333-333333333333"
WS_2_ID = "44444444-4444-4444-4444-444444444444"
ALIAS_1_ID = "77777777-7777-7777-7777-777777777777"
ALIAS_2_ID = "88888888-8888-8888-8888-888888888888"


def _write_json(p: Path, payload) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


@pytest.fixture
def cli_fixture_dir(tmp_path: Path) -> Path:
    """构造标准 identity JSON fixture。"""
    base = tmp_path / "identity_cli"
    _write_json(
        base / "users.json",
        {
            "_schema_version": 1,
            "users": {
                USER_1_ID: {
                    "id": USER_1_ID,
                    "username": "alice",
                    "status": "active",
                    "created_at": FIXTURE_TS_STR,
                    "legacy_user_key": "legacy-1",
                    "display_name": "Alice",
                    "avatar_url": None,
                },
                USER_2_ID: {
                    "id": USER_2_ID,
                    "username": "bob",
                    "status": "active",
                    "created_at": FIXTURE_TS_STR,
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
                    "id": ALIAS_1_ID,
                    "user_id": USER_1_ID,
                    "kind": "x_user_id",
                    "legacy_user_key": "alias-key-1",
                    "created_at": FIXTURE_TS_STR,
                },
                {
                    "id": ALIAS_2_ID,
                    "user_id": USER_2_ID,
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
                WS_1_ID: {
                    "id": WS_1_ID,
                    "name": "ws-alpha",
                    "description": None,
                    "created_at": FIXTURE_TS_STR,
                },
                WS_2_ID: {
                    "id": WS_2_ID,
                    "name": "ws-beta",
                    "description": "desc",
                    "created_at": FIXTURE_TS_STR,
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
                    "workspace_id": WS_1_ID,
                    "user_id": USER_1_ID,
                    "role": "workspace_admin",
                    "created_at": FIXTURE_TS_STR,
                },
                {
                    "workspace_id": WS_2_ID,
                    "user_id": USER_2_ID,
                    "role": "member",
                    "created_at": FIXTURE_TS_STR,
                },
            ],
            "project_memberships": [
                {
                    "project_id": "proj-x",
                    "workspace_id": WS_1_ID,
                    "user_id": USER_1_ID,
                    "role": "editor",
                    "created_at": FIXTURE_TS_STR,
                }
            ],
        },
    )
    _write_json(
        base / "roles.json",
        {
            "_schema_version": 1,
            "roles": {
                "custom_role_pr10": {
                    "key": "custom_role_pr10",
                    "display_name": "PR-10 test role",
                    "description": "for CLI test",
                    "scope": "workspace",
                    "created_at": FIXTURE_TS_STR,
                }
            },
        },
    )
    _write_json(
        base / "role_permissions.json",
        {"_schema_version": 1, "role_permissions": {}},
    )
    _write_json(
        base / "resource_acl.json",
        {"_schema_version": 1, "acl": []},
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
def migrated_env(isolated_env):
    migrate_baseline(isolated_env)
    yield isolated_env


# ---------------------------------------------------------------------------
# --dry-run
# ---------------------------------------------------------------------------


def test_cli_dry_run_no_write(cli_fixture_dir, migrated_env):
    """--dry-run 输出计数矩阵 · 不写 SQLite。"""
    from tools.identity_json_to_sqlite import run_dry_run

    result = run_dry_run(identity_dir=cli_fixture_dir)
    assert result["mode"] == "dry-run"
    assert result["counts"]["users"] == 2
    assert result["counts"]["workspaces"] == 2
    assert result["counts"]["user_aliases"] == 2
    assert result["counts"]["workspace_memberships"] == 2
    # project_memberships 明示 skipped
    assert result["counts"]["project_memberships_skipped_pr11"] == 1
    assert "PR-11" in result["note"]

    # 校验没写 SQLite
    from app.db.session import get_session
    from app.identity.tables import user_table

    with get_session() as session:
        rows = session.execute(user_table.select()).all()
        # 只有 0006 seed 不涉及 user 表 · 应为空
        assert len(rows) == 0


# ---------------------------------------------------------------------------
# --apply
# ---------------------------------------------------------------------------


def test_cli_apply_writes_sqlite(cli_fixture_dir, migrated_env):
    """--apply 幂等写入 SQLite。"""
    from tools.identity_json_to_sqlite import run_apply

    result = run_apply(identity_dir=cli_fixture_dir)
    assert result["mode"] == "apply"
    assert result["stats"]["users_inserted_or_ignored"] == 2
    assert result["stats"]["workspaces_inserted_or_ignored"] == 2
    assert result["stats"]["aliases_inserted_or_ignored"] == 2
    assert result["stats"]["memberships_inserted_or_ignored"] == 2

    # 验证 SQLite 里真有数据
    from sqlalchemy import select

    from app.db.session import get_session
    from app.identity.tables import (
        membership_table,
        user_alias_table,
        user_table,
        workspace_table,
    )

    with get_session() as session:
        users = session.execute(select(user_table)).all()
        assert len(users) == 2
        aliases = session.execute(select(user_alias_table)).all()
        assert len(aliases) == 2
        # 0006 seed 建了一个 workspace('system') · fixture 加 2 → 3
        workspaces = session.execute(select(workspace_table)).all()
        assert len(workspaces) == 3
        memberships = session.execute(select(membership_table)).all()
        assert len(memberships) == 2


def test_cli_apply_is_idempotent(cli_fixture_dir, migrated_env):
    """--apply 跑两次 · SQLite 内容相同(计数不变)。"""
    from sqlalchemy import func, select

    from app.db.session import get_session
    from app.identity.tables import (
        membership_table,
        user_alias_table,
        user_table,
        workspace_table,
    )
    from tools.identity_json_to_sqlite import run_apply

    def _row_counts():
        with get_session() as session:
            return {
                "users": session.execute(
                    select(func.count()).select_from(user_table)
                ).scalar(),
                "workspaces": session.execute(
                    select(func.count()).select_from(workspace_table)
                ).scalar(),
                "aliases": session.execute(
                    select(func.count()).select_from(user_alias_table)
                ).scalar(),
                "memberships": session.execute(
                    select(func.count()).select_from(membership_table)
                ).scalar(),
            }

    run_apply(identity_dir=cli_fixture_dir)
    first = _row_counts()
    run_apply(identity_dir=cli_fixture_dir)
    second = _row_counts()
    assert first == second, f"幂等违反:{first} != {second}"


def test_cli_apply_skips_project_memberships(cli_fixture_dir, migrated_env):
    """冲突 A 决议 α:project_memberships 不迁 · dry-run 计入 skipped 计数。"""
    from tools.identity_json_to_sqlite import run_dry_run

    result = run_dry_run(identity_dir=cli_fixture_dir)
    assert result["counts"]["project_memberships_skipped_pr11"] == 1


# ---------------------------------------------------------------------------
# --verify
# ---------------------------------------------------------------------------


def test_cli_verify_after_apply_reports_match(cli_fixture_dir, migrated_env):
    """--apply 后 --verify 大部分方法应报 match。"""
    from tools.identity_json_to_sqlite import run_apply, run_verify

    run_apply(identity_dir=cli_fixture_dir)
    report = run_verify(identity_dir=cli_fixture_dir)
    assert report["mode"] == "verify"
    r = report["report"]
    # 冲突 C η:role_permissions 两侧空 dict
    assert r["list_role_permissions"]["status"] == "match"
    # resource_acl 两侧都空
    assert r["get_resource_acl"]["status"] == "match"
    # auth_migration_state 读同一 JSON
    assert r["read_auth_migration_state"]["status"] == "match"
    # workspaces:排除 seed 后 count 匹配
    assert r["list_workspaces"]["status"] == "match"
    # user_aliases:apply 后计数应等价
    assert r["list_user_aliases"]["status"] == "match"


def test_cli_verify_before_apply_reports_mismatch(cli_fixture_dir, migrated_env):
    """未 --apply 时 · SQLite 表空 · aliases count 与 JSON 不一致。"""
    from tools.identity_json_to_sqlite import run_verify

    report = run_verify(identity_dir=cli_fixture_dir)
    r = report["report"]
    # aliases 端 SQLite 空 · JSON 2 条 · count_mismatch
    assert r["list_user_aliases"]["status"] == "count_mismatch"


# ---------------------------------------------------------------------------
# CLI 入口 argparse
# ---------------------------------------------------------------------------


def test_cli_main_requires_mode(cli_fixture_dir, migrated_env):
    """无 --dry-run/--apply/--verify · 应 error(argparse required group)。"""
    from tools.identity_json_to_sqlite import main

    with pytest.raises(SystemExit):
        main([])


def test_cli_main_dry_run_exit_zero(cli_fixture_dir, migrated_env, capsys):
    """--dry-run 打印 JSON summary + 返回 0。"""
    from tools.identity_json_to_sqlite import main

    rc = main(["--dry-run", "--identity-dir", str(cli_fixture_dir)])
    assert rc == 0
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert parsed["mode"] == "dry-run"


def test_cli_main_apply_exit_zero(cli_fixture_dir, migrated_env, capsys):
    """--apply 打印 stats + 返回 0。"""
    from tools.identity_json_to_sqlite import main

    rc = main(["--apply", "--identity-dir", str(cli_fixture_dir)])
    assert rc == 0
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert parsed["mode"] == "apply"
    assert parsed["stats"]["users_inserted_or_ignored"] == 2


# ---------------------------------------------------------------------------
# P0 密钥零泄漏
# ---------------------------------------------------------------------------


def test_cli_dry_run_stdout_no_secrets(cli_fixture_dir, migrated_env, capsys):
    """--dry-run stdout 不含 password / session / secret 字面量。"""
    from tools.identity_json_to_sqlite import main

    main(["--dry-run", "--identity-dir", str(cli_fixture_dir)])
    captured = capsys.readouterr()
    for forbidden in ("password", "session_token", "secret", "X-CSRF-Token"):
        assert forbidden.lower() not in captured.out.lower(), (
            f"迁移 CLI stdout 泄漏敏感 token:{forbidden}"
        )


def test_cli_apply_stdout_no_secrets(cli_fixture_dir, migrated_env, capsys):
    """--apply stdout 不含 password / session / secret 字面量。"""
    from tools.identity_json_to_sqlite import main

    main(["--apply", "--identity-dir", str(cli_fixture_dir)])
    captured = capsys.readouterr()
    for forbidden in ("password", "session_token", "secret", "X-CSRF-Token"):
        assert forbidden.lower() not in captured.out.lower(), (
            f"迁移 CLI stdout 泄漏敏感 token:{forbidden}"
        )
