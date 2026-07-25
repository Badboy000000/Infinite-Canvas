"""部署 PR-11 · Audit 落盘策略骨架契约测试。"""
from __future__ import annotations

import pytest

from app.security.audit_policy import (
    AUDIT_EVENT_KINDS,
    AUDIT_POLICY_ENABLED_ENV,
    AuditPolicy,
    build_default_policies,
    is_audit_policy_enabled,
)


def test_TB80_defaults_off(monkeypatch):
    monkeypatch.delenv(AUDIT_POLICY_ENABLED_ENV, raising=False)
    assert is_audit_policy_enabled() is False


def test_TB81_event_kinds_present():
    for expected in (
        "auth.login", "auth.logout", "permission.change",
        "provider.credential_edit", "provider.credential_delete",
        "file.upload_rejected", "task.failed", "admin.action",
    ):
        assert expected in AUDIT_EVENT_KINDS


def test_TB82_policy_invariants():
    with pytest.raises(ValueError, match="kind"):
        AuditPolicy(kind="foo", required=True, retention_days=30)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="retention_days"):
        AuditPolicy(kind="auth.login", required=True, retention_days=-1)


def test_TB83_local_personal_all_optional_zero_retention():
    policies = build_default_policies("local_personal")
    for kind in AUDIT_EVENT_KINDS:
        assert policies[kind].required is False
        assert policies[kind].retention_days == 0


def test_TB84_intranet_login_required():
    policies = build_default_policies("intranet_team")
    login = policies["auth.login"]
    assert login.required is True
    assert login.retention_days == 90


def test_TB85_public_team_stricter():
    intranet = build_default_policies("intranet_team")
    public = build_default_policies("public_team")
    for kind in ("auth.login", "permission.change", "provider.credential_edit"):
        assert public[kind].retention_days >= intranet[kind].retention_days, kind


def test_TB86_credential_events_marked_pii():
    for mode in ("intranet_team", "public_team"):
        p = build_default_policies(mode)
        assert p["provider.credential_edit"].contains_pii is True
        assert p["provider.credential_delete"].contains_pii is True


def test_TB87_permission_and_admin_high_priority():
    p = build_default_policies("public_team")
    assert p["permission.change"].high_priority is True
    assert p["admin.action"].high_priority is True


def test_TB88_unknown_mode_rejected():
    with pytest.raises(ValueError, match="unknown deployment mode"):
        build_default_policies("evil")  # type: ignore[arg-type]


def test_TB89_module_does_not_import_main():
    import app.security.audit_policy as mod
    import inspect
    src = inspect.getsource(mod)
    assert "import main" not in src
    assert "from main" not in src
