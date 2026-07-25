"""文件 PR-6 · FileHold 引用计数契约测试。"""
from __future__ import annotations

import pytest

from app.services.files.file_hold import (
    ALLOWED_SUBJECT_KINDS,
    FILE_HOLD_TRACKING_ENABLED_ENV,
    FileHold,
    FileHoldDelta,
    ReferenceCountViolation,
    clamp_reference_count,
    compute_hold_delta,
    is_file_hold_tracking_enabled,
)


# --- T820:defaults-off + subject_kind 白名单 ---------------------------

def test_T820_defaults_off(monkeypatch):
    monkeypatch.delenv(FILE_HOLD_TRACKING_ENABLED_ENV, raising=False)
    assert is_file_hold_tracking_enabled() is False


def test_T821_subject_kinds_frozen():
    assert ALLOWED_SUBJECT_KINDS == (
        "canvas_node",
        "task_artifact",
        "history_entry",
        "asset_library_item",
        "workflow_import",
    )


# --- T822-T824:FileHold 构造约束 -----------------------------

def test_T822_file_hold_rejects_empty_ids():
    with pytest.raises(ValueError, match="file_object_id"):
        FileHold(file_object_id="", subject_kind="canvas_node", subject_id="x")
    with pytest.raises(ValueError, match="subject_id"):
        FileHold(file_object_id="f", subject_kind="canvas_node", subject_id="")


def test_T823_file_hold_rejects_unknown_subject_kind():
    with pytest.raises(ValueError, match="subject_kind"):
        FileHold(file_object_id="f", subject_kind="foobar", subject_id="x")  # type: ignore[arg-type]


def test_T824_file_hold_frozen():
    h = FileHold(file_object_id="f", subject_kind="canvas_node", subject_id="n1")
    with pytest.raises((AttributeError, TypeError)):
        h.file_object_id = "hacked"  # type: ignore[misc]


# --- T825-T828:compute_hold_delta acquire / release -----------------

def test_T825_acquire_new_hold_returns_plus_one():
    h = FileHold(file_object_id="f1", subject_kind="canvas_node", subject_id="n1")
    delta = compute_hold_delta([], h, operation="acquire")
    assert delta.delta == 1
    assert delta.file_object_id == "f1"


def test_T826_acquire_dedup_returns_zero():
    h = FileHold(file_object_id="f1", subject_kind="canvas_node", subject_id="n1")
    delta = compute_hold_delta([h], h, operation="acquire")
    assert delta.delta == 0
    assert "dedup" in delta.reason


def test_T827_release_existing_returns_minus_one():
    h = FileHold(file_object_id="f1", subject_kind="canvas_node", subject_id="n1")
    delta = compute_hold_delta([h], h, operation="release")
    assert delta.delta == -1


def test_T828_release_missing_raises():
    h = FileHold(file_object_id="f1", subject_kind="canvas_node", subject_id="n1")
    with pytest.raises(ReferenceCountViolation):
        compute_hold_delta([], h, operation="release")


# --- T829:FileHoldDelta invariant ---------------------------------

def test_T829_delta_must_be_minus_one_zero_or_one():
    with pytest.raises(ValueError, match="delta"):
        FileHoldDelta(file_object_id="f", delta=2, reason="bad")
    with pytest.raises(ValueError, match="delta"):
        FileHoldDelta(file_object_id="f", delta=-2, reason="bad")


# --- T830-T831:clamp_reference_count -----------------------------

@pytest.mark.parametrize("current,delta,expected", [
    (0, 1, 1),
    (5, -1, 4),
    (1, 0, 1),
    (10, -3, 7),
])
def test_T830_clamp_ok(current, delta, expected):
    assert clamp_reference_count(current, delta) == expected


def test_T831_clamp_negative_raises():
    with pytest.raises(ReferenceCountViolation, match="negative"):
        clamp_reference_count(0, -1)


# --- T832:治理护栏 · 不 import main / SQL --------------------

def test_T832_module_does_not_import_main_or_sqlalchemy():
    import app.services.files.file_hold as mod
    import inspect
    src = inspect.getsource(mod)
    assert "import main" not in src
    assert "from main" not in src
    # 骨架层禁止 import sqlalchemy · 只检查 import 语句而不是文档里的字面量
    for line in src.splitlines():
        stripped = line.strip()
        if stripped.startswith("import ") or stripped.startswith("from "):
            assert "sqlalchemy" not in stripped.lower(), (
                f"file_hold skeleton must not import sqlalchemy; got: {line!r}"
            )
