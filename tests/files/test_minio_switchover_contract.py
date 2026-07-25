"""文件 PR-12 · MinIO 灰度切换契约测试。"""
from __future__ import annotations

import pytest

from app.services.files.minio_switchover import (
    MINIO_SWITCHOVER_ENABLED_ENV,
    STORAGE_BACKENDS,
    SWITCHOVER_PHASES,
    SwitchoverPolicy,
    build_switchover_plan,
    is_minio_switchover_enabled,
    is_switchover_reversible,
)


def test_TD00_defaults_off(monkeypatch):
    monkeypatch.delenv(MINIO_SWITCHOVER_ENABLED_ENV, raising=False)
    assert is_minio_switchover_enabled() is False


def test_TD01_backends_frozen():
    assert STORAGE_BACKENDS == ("local", "minio", "hybrid")


def test_TD02_phases_frozen():
    assert SWITCHOVER_PHASES == ("shadow", "dual_write", "cutover", "rollback")


def test_TD03_shadow_only_writes_from():
    p = build_switchover_plan(from_backend="local", to_backend="minio", phase="shadow")
    assert p.write_targets == ("local",)
    assert p.read_priority == ("local",)


def test_TD04_dual_write_writes_both():
    p = build_switchover_plan(from_backend="local", to_backend="minio", phase="dual_write")
    assert set(p.write_targets) == {"local", "minio"}


def test_TD05_dual_write_does_not_delete_from_new():
    """dual_write 阶段严禁 delete from new · 避免灰度期数据丢失。"""
    p = build_switchover_plan(from_backend="local", to_backend="minio", phase="dual_write")
    assert "minio" not in p.allow_delete_from


def test_TD06_cutover_writes_only_new():
    p = build_switchover_plan(from_backend="local", to_backend="minio", phase="cutover")
    assert p.write_targets == ("minio",)
    # 读优先新 · 兜底旧
    assert p.read_priority[0] == "minio"
    assert "local" in p.read_priority


def test_TD07_rollback_writes_back_to_original():
    p = build_switchover_plan(from_backend="local", to_backend="minio", phase="rollback")
    assert p.write_targets == ("local",)
    # 允许清理灰度期数据
    assert "minio" in p.allow_delete_from


def test_TD08_cutover_not_silently_reversible():
    """cutover 不允许静默回退 · 需 rollback plan。"""
    p_cutover = build_switchover_plan(from_backend="local", to_backend="minio", phase="cutover")
    assert is_switchover_reversible(p_cutover) is False

    p_dual = build_switchover_plan(from_backend="local", to_backend="minio", phase="dual_write")
    assert is_switchover_reversible(p_dual) is True


def test_TD09_unknown_phase_rejected():
    with pytest.raises(ValueError, match="unknown phase"):
        build_switchover_plan(from_backend="local", to_backend="minio", phase="explode")  # type: ignore[arg-type]


def test_TD10_policy_invariants():
    with pytest.raises(ValueError, match="from_backend"):
        SwitchoverPolicy(
            from_backend="foo", to_backend="local", phase="shadow",  # type: ignore[arg-type]
            write_targets=(), read_priority=(), allow_delete_from=(),
        )


def test_TD11_module_does_not_import_main():
    import app.services.files.minio_switchover as mod
    import inspect
    src = inspect.getsource(mod)
    assert "import main" not in src
    assert "from main" not in src
