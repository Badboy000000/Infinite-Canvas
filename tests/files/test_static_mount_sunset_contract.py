"""文件 PR-14 · 静态挂载下线判据契约测试。"""
from __future__ import annotations

import pytest

from app.services.files.static_mount_sunset import (
    STATIC_MOUNT_SUNSET_STRICT_ENV,
    StaticMountReadiness,
    VERDICTS,
    is_static_mount_sunset_strict,
    judge_static_mount_readiness,
)


def test_TD40_defaults_off(monkeypatch):
    monkeypatch.delenv(STATIC_MOUNT_SUNSET_STRICT_ENV, raising=False)
    assert is_static_mount_sunset_strict() is False


def test_TD41_verdicts_frozen():
    assert VERDICTS == ("ready_to_unmount", "hold", "blocked")


def test_TD42_all_criteria_satisfied_ready():
    r = judge_static_mount_readiness(
        mount_path="/output",
        cutover_stable_days=14,
        all_buckets_retired=True,
        legacy_access_last_30d=0,
        unmapped_urls=0,
    )
    assert r.verdict == "ready_to_unmount"


def test_TD43_buckets_not_all_retired_blocked():
    r = judge_static_mount_readiness(
        mount_path="/output",
        cutover_stable_days=14,
        all_buckets_retired=False,
        legacy_access_last_30d=0,
        unmapped_urls=0,
    )
    assert r.verdict == "blocked"


def test_TD44_recent_legacy_access_blocked():
    r = judge_static_mount_readiness(
        mount_path="/assets",
        cutover_stable_days=14,
        all_buckets_retired=True,
        legacy_access_last_30d=5,
        unmapped_urls=0,
    )
    assert r.verdict == "blocked"


def test_TD45_unmapped_urls_blocked():
    r = judge_static_mount_readiness(
        mount_path="/assets",
        cutover_stable_days=14,
        all_buckets_retired=True,
        legacy_access_last_30d=0,
        unmapped_urls=3,
    )
    assert r.verdict == "blocked"


def test_TD46_cutover_too_recent_hold():
    """cutover 稳定 < 7 天 · 不阻塞 · 但需等(hold)。"""
    r = judge_static_mount_readiness(
        mount_path="/output",
        cutover_stable_days=3,
        all_buckets_retired=True,
        legacy_access_last_30d=0,
        unmapped_urls=0,
    )
    assert r.verdict == "hold"


def test_TD47_custom_min_cutover_days():
    r = judge_static_mount_readiness(
        mount_path="/output",
        cutover_stable_days=3,
        all_buckets_retired=True,
        legacy_access_last_30d=0,
        unmapped_urls=0,
        min_cutover_days=3,
    )
    assert r.verdict == "ready_to_unmount"


def test_TD48_reasons_populated():
    r = judge_static_mount_readiness(
        mount_path="/output",
        cutover_stable_days=1,
        all_buckets_retired=False,
        legacy_access_last_30d=10,
        unmapped_urls=5,
    )
    assert r.verdict == "blocked"
    assert len(r.reasons) >= 3


def test_TD49_invariants():
    with pytest.raises(ValueError, match="mount_path"):
        StaticMountReadiness(
            mount_path="", cutover_stable_days=0,
            all_buckets_retired=True, legacy_access_last_30d=0, unmapped_urls=0,
        )


def test_TD50_module_does_not_import_main():
    import app.services.files.static_mount_sunset as mod
    import inspect
    src = inspect.getsource(mod)
    assert "import main" not in src
    assert "from main" not in src
