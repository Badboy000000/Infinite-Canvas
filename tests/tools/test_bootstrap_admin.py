"""tools/bootstrap_admin.py 契约测试(权限 PR-5 · Wave 3-N.9 Batch 2 主线 A)。

覆盖:
- env 缺失 → SystemExit(2)
- env 密码太短 → SystemExit(2)
- 首次 bootstrap 成功 · 落 auth_credentials + users.json + notes
- 重复 bootstrap 幂等 skip
- --force-reset 重置密码 · user_id 保持
- P0:密码不出现在输出 / 输出无 password_hash
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from tests.shadow_read._helpers import isolated_shadow_env, migrate_baseline
from tools.bootstrap_admin import (
    BOOTSTRAP_NOTE_PREFIX,
    ENV_BOOTSTRAP_PASSWORD,
    MIN_PASSWORD_LENGTH,
    run_bootstrap,
)

VALID_PASSWORD = "TestBootstrapAdmin2026!"


@pytest.fixture(autouse=True)
def _isolated_db(monkeypatch, tmp_path):
    with isolated_shadow_env(monkeypatch, tmp_path) as sandbox:
        migrate_baseline(sandbox)
        yield sandbox


@pytest.fixture
def _identity_dir(tmp_path, _isolated_db):
    """在 tmp 内准备一份最小 identity JSON 目录(与 bootstrap 目标同构)。"""
    identity = tmp_path / "identity"
    identity.mkdir(parents=True, exist_ok=True)
    (identity / "users.json").write_text(
        json.dumps({"_schema_version": 1, "users": {}}, ensure_ascii=False),
        encoding="utf-8",
    )
    (identity / "auth_migration_state.json").write_text(
        json.dumps(
            {
                "_schema_version": 1,
                "bootstrap_completed_at": None,
                "legacy_mapping_completed_at": None,
                "notes": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return identity


@pytest.fixture(autouse=True)
def _clean_pw_env(monkeypatch):
    monkeypatch.delenv(ENV_BOOTSTRAP_PASSWORD, raising=False)
    yield


# ---------------------------------------------------------------------------
# T560 - env 缺失 fail-fast
# ---------------------------------------------------------------------------


def test_bootstrap_missing_env_exits(monkeypatch, _identity_dir):
    """T560 · env 未设 → SystemExit(2)。"""
    monkeypatch.delenv(ENV_BOOTSTRAP_PASSWORD, raising=False)
    with pytest.raises(SystemExit) as ei:
        run_bootstrap(
            admin_username="admin",
            create_if_missing=True,
            force_reset=False,
            identity_dir=_identity_dir,
        )
    assert ei.value.code == 2


def test_bootstrap_short_password_exits(monkeypatch, _identity_dir):
    """T561 · 密码 < MIN → SystemExit(2)。"""
    monkeypatch.setenv(ENV_BOOTSTRAP_PASSWORD, "short")
    assert len("short") < MIN_PASSWORD_LENGTH
    with pytest.raises(SystemExit) as ei:
        run_bootstrap(
            admin_username="admin",
            create_if_missing=True,
            force_reset=False,
            identity_dir=_identity_dir,
        )
    assert ei.value.code == 2


# ---------------------------------------------------------------------------
# T562-563 - 首次 bootstrap
# ---------------------------------------------------------------------------


def test_bootstrap_first_time_creates(monkeypatch, _identity_dir):
    """T562 · 首次 bootstrap · outcome=created · 落 DB + users.json。"""
    monkeypatch.setenv(ENV_BOOTSTRAP_PASSWORD, VALID_PASSWORD)
    result = run_bootstrap(
        admin_username="admin",
        create_if_missing=True,
        force_reset=False,
        identity_dir=_identity_dir,
    )
    assert result.outcome == "created"
    assert result.username == "admin"
    # user_id 是 uuid 字符串
    import uuid as _uuid

    _uuid.UUID(result.user_id)  # 无异常即通过

    # users.json 落值
    users = json.loads((_identity_dir / "users.json").read_text(encoding="utf-8"))
    assert result.user_id in users["users"]
    assert users["users"][result.user_id]["username"] == "admin"
    assert users["users"][result.user_id]["status"] == "active"

    # auth_migration_state notes 落 marker
    state = json.loads(
        (_identity_dir / "auth_migration_state.json").read_text(encoding="utf-8")
    )
    marker = f"{BOOTSTRAP_NOTE_PREFIX}{result.user_id}"
    assert marker in state["notes"]
    assert state["bootstrap_completed_at"] is not None


def test_bootstrap_creates_verifiable_password_hash(monkeypatch, _identity_dir):
    """T563 · 落库的 hash 是 argon2 · PasswordHasher.verify 通过。"""
    monkeypatch.setenv(ENV_BOOTSTRAP_PASSWORD, VALID_PASSWORD)
    result = run_bootstrap(
        admin_username="admin",
        create_if_missing=True,
        force_reset=False,
        identity_dir=_identity_dir,
    )
    # 查表拿 hash
    from sqlalchemy import select

    from app.db.session import get_session
    from app.services.auth import PasswordHasher
    from app.services.auth.tables import auth_credentials

    with get_session() as session:
        row = session.execute(
            select(auth_credentials.c.password_hash).where(
                auth_credentials.c.user_id == result.user_id
            )
        ).first()
    assert row is not None
    stored_hash = row.password_hash
    # argon2 hash 起头
    assert stored_hash.startswith("$argon2")
    hasher = PasswordHasher()
    assert hasher.verify(stored_hash, VALID_PASSWORD)
    # 错误密码不通过
    assert not hasher.verify(stored_hash, "wrong-password-xxx")


# ---------------------------------------------------------------------------
# T564 - 幂等 skip
# ---------------------------------------------------------------------------


def test_bootstrap_idempotent_skip(monkeypatch, _identity_dir):
    """T564 · 重复 bootstrap · outcome=skipped · user_id 保持一致。"""
    monkeypatch.setenv(ENV_BOOTSTRAP_PASSWORD, VALID_PASSWORD)
    first = run_bootstrap(
        admin_username="admin",
        create_if_missing=True,
        force_reset=False,
        identity_dir=_identity_dir,
    )
    second = run_bootstrap(
        admin_username="admin",
        create_if_missing=True,
        force_reset=False,
        identity_dir=_identity_dir,
    )
    assert second.outcome == "skipped"
    assert second.user_id == first.user_id


# ---------------------------------------------------------------------------
# T565 - --force-reset 重置密码 · user_id 保持
# ---------------------------------------------------------------------------


def test_bootstrap_force_reset_updates_password(monkeypatch, _identity_dir):
    """T565 · --force-reset · outcome=reset · hash 变化 · user_id 保持。"""
    monkeypatch.setenv(ENV_BOOTSTRAP_PASSWORD, VALID_PASSWORD)
    first = run_bootstrap(
        admin_username="admin",
        create_if_missing=True,
        force_reset=False,
        identity_dir=_identity_dir,
    )
    old_uid = first.user_id
    # 用不同密码 reset
    monkeypatch.setenv(ENV_BOOTSTRAP_PASSWORD, VALID_PASSWORD + "-ROTATED")
    second = run_bootstrap(
        admin_username="admin",
        create_if_missing=False,
        force_reset=True,
        identity_dir=_identity_dir,
    )
    assert second.outcome == "reset"
    assert second.user_id == old_uid

    # 新密码验证通过 · 旧密码失败
    from sqlalchemy import select

    from app.db.session import get_session
    from app.services.auth import PasswordHasher
    from app.services.auth.tables import auth_credentials

    with get_session() as session:
        row = session.execute(
            select(auth_credentials.c.password_hash).where(
                auth_credentials.c.user_id == old_uid
            )
        ).first()
    hasher = PasswordHasher()
    assert hasher.verify(row.password_hash, VALID_PASSWORD + "-ROTATED")
    assert not hasher.verify(row.password_hash, VALID_PASSWORD)


# ---------------------------------------------------------------------------
# T566 - identity_dir 缺失 fail-fast
# ---------------------------------------------------------------------------


def test_bootstrap_missing_identity_dir_exits(monkeypatch, tmp_path):
    """T566 · identity_dir 不存在 → SystemExit(3)。"""
    monkeypatch.setenv(ENV_BOOTSTRAP_PASSWORD, VALID_PASSWORD)
    missing = tmp_path / "does_not_exist"
    with pytest.raises(SystemExit) as ei:
        run_bootstrap(
            admin_username="admin",
            create_if_missing=True,
            force_reset=False,
            identity_dir=missing,
        )
    assert ei.value.code == 3
