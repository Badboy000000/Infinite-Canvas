"""部署 PR-13 · 备份 & DR 策略骨架契约测试。"""
from __future__ import annotations

import pytest

from app.security.backup_policy import (
    BACKUP_KINDS,
    BACKUP_POLICY_ENABLED_ENV,
    BackupPolicy,
    build_default_policy,
    compute_retention_series,
    is_backup_policy_enabled,
)


def test_TD60_defaults_off(monkeypatch):
    monkeypatch.delenv(BACKUP_POLICY_ENABLED_ENV, raising=False)
    assert is_backup_policy_enabled() is False


def test_TD61_backup_kinds_frozen():
    assert BACKUP_KINDS == ("full", "incremental", "snapshot")


def test_TD62_local_personal_minimal():
    p = build_default_policy("local_personal")
    assert p.encryption_required is False
    assert p.off_site_replica is False
    assert p.daily_retention == 7


def test_TD63_intranet_encrypted_offsite():
    p = build_default_policy("intranet_team")
    assert p.encryption_required is True
    assert p.off_site_replica is True


def test_TD64_public_strictest():
    intranet = build_default_policy("intranet_team")
    public = build_default_policy("public_team")
    assert public.daily_retention >= intranet.daily_retention
    assert public.weekly_retention >= intranet.weekly_retention
    assert public.monthly_retention >= intranet.monthly_retention
    assert public.full_backup_interval_hours <= intranet.full_backup_interval_hours


def test_TD65_incremental_le_full():
    for mode in ("local_personal", "intranet_team", "public_team"):
        p = build_default_policy(mode)  # type: ignore[arg-type]
        assert p.incremental_backup_interval_hours <= p.full_backup_interval_hours


def test_TD66_retention_series_total():
    p = build_default_policy("public_team")
    series = compute_retention_series(p)
    assert series["total"] == p.daily_retention + p.weekly_retention + p.monthly_retention


def test_TD67_policy_invariants():
    with pytest.raises(ValueError):
        BackupPolicy(
            mode="local_personal",
            full_backup_interval_hours=-1, incremental_backup_interval_hours=1,
            daily_retention=0, weekly_retention=0, monthly_retention=0,
            off_site_replica=False, encryption_required=False,
        )


def test_TD68_incremental_greater_than_full_rejected():
    with pytest.raises(ValueError, match="incremental interval"):
        BackupPolicy(
            mode="intranet_team",
            full_backup_interval_hours=6, incremental_backup_interval_hours=24,
            daily_retention=7, weekly_retention=0, monthly_retention=0,
            off_site_replica=True, encryption_required=True,
        )


def test_TD69_unknown_mode_rejected():
    with pytest.raises(ValueError, match="unknown deployment mode"):
        build_default_policy("evil")  # type: ignore[arg-type]


def test_TD70_module_does_not_import_main():
    import app.security.backup_policy as mod
    import inspect
    src = inspect.getsource(mod)
    assert "import main" not in src
    assert "from main" not in src
