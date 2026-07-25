"""文件 PR-7 · orphan_scan 契约测试。"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.services.files.orphan_scan import (
    FILE_ORPHAN_SCAN_ENABLED_ENV,
    ORPHAN_SCAN_MIN_AGE_HOURS,
    OrphanCandidate,
    compute_orphan_candidates,
    format_orphan_report,
    is_orphan_scan_enabled,
)


def _now():
    return datetime(2026, 7, 25, 12, 0, 0, tzinfo=timezone.utc)


def test_T950_defaults_off(monkeypatch):
    monkeypatch.delenv(FILE_ORPHAN_SCAN_ENABLED_ENV, raising=False)
    assert is_orphan_scan_enabled() is False


def test_T951_min_age_hours_default():
    assert ORPHAN_SCAN_MIN_AGE_HOURS == 24


def test_T952_candidate_rejects_nonzero_reference_count():
    with pytest.raises(ValueError, match="reference_count"):
        OrphanCandidate(
            file_object_id="f1", reference_count=1,
            last_referenced_at=None, key="output/k", sha256="abc",
        )


def test_T953_zero_ref_and_old_last_ref_is_orphan():
    now = _now()
    old_ts = (now - timedelta(hours=48)).isoformat()
    rows = [
        {"id": "f1", "reference_count": 0, "last_referenced_at": old_ts,
         "key": "output/f1.png", "sha256": "sha1"},
    ]
    result = compute_orphan_candidates(rows, now_utc=now)
    assert len(result) == 1
    assert result[0].file_object_id == "f1"


def test_T954_zero_ref_but_recent_not_orphan():
    """引用计数 0 但 last_referenced_at 在安全窗口内 · 不列入 orphan。"""
    now = _now()
    recent_ts = (now - timedelta(hours=1)).isoformat()
    rows = [
        {"id": "f1", "reference_count": 0, "last_referenced_at": recent_ts,
         "key": "output/f1.png", "sha256": "sha1"},
    ]
    result = compute_orphan_candidates(rows, now_utc=now)
    assert len(result) == 0


def test_T955_nonzero_ref_never_orphan():
    now = _now()
    old_ts = (now - timedelta(hours=48)).isoformat()
    rows = [
        {"id": "f1", "reference_count": 3, "last_referenced_at": old_ts,
         "key": "output/f1.png", "sha256": "sha1"},
    ]
    result = compute_orphan_candidates(rows, now_utc=now)
    assert len(result) == 0


def test_T956_missing_last_ref_is_orphan():
    """last_referenced_at 缺失 · 视为很久没引用 · 属于候选。"""
    now = _now()
    rows = [
        {"id": "f1", "reference_count": 0, "last_referenced_at": None,
         "key": "output/f1.png", "sha256": "sha1"},
    ]
    result = compute_orphan_candidates(rows, now_utc=now)
    assert len(result) == 1


def test_T957_result_sorted_by_file_object_id():
    now = _now()
    old_ts = (now - timedelta(hours=48)).isoformat()
    rows = [
        {"id": "z1", "reference_count": 0, "last_referenced_at": old_ts, "key": "", "sha256": ""},
        {"id": "a1", "reference_count": 0, "last_referenced_at": old_ts, "key": "", "sha256": ""},
        {"id": "m1", "reference_count": 0, "last_referenced_at": old_ts, "key": "", "sha256": ""},
    ]
    result = compute_orphan_candidates(rows, now_utc=now)
    assert [c.file_object_id for c in result] == ["a1", "m1", "z1"]


def test_T958_min_age_hours_zero_no_safety_window():
    now = _now()
    just_now = now.isoformat()
    rows = [
        {"id": "f1", "reference_count": 0, "last_referenced_at": just_now,
         "key": "output/f1.png", "sha256": "sha1"},
    ]
    result = compute_orphan_candidates(rows, now_utc=now, min_age_hours=0)
    assert len(result) == 1


def test_T959_negative_min_age_hours_rejected():
    with pytest.raises(ValueError, match="min_age_hours"):
        compute_orphan_candidates([], now_utc=_now(), min_age_hours=-1)


def test_T960_report_text_empty():
    assert format_orphan_report([]).startswith("orphan_scan: 0 candidates")


def test_T961_report_json_structure():
    now = _now()
    old_ts = (now - timedelta(hours=48)).isoformat()
    rows = [
        {"id": "f1", "reference_count": 0, "last_referenced_at": old_ts,
         "key": "output/ab/cd/xxx.png", "sha256": "abc"},
    ]
    candidates = compute_orphan_candidates(rows, now_utc=now)
    report_json = format_orphan_report(candidates, output_format="json")
    parsed = json.loads(report_json)
    assert parsed["orphan_count"] == 1
    assert parsed["candidates"][0]["file_object_id"] == "f1"
    assert parsed["candidates"][0]["key"] == "output/ab/cd/xxx.png"


def test_T962_report_unknown_format_rejected():
    with pytest.raises(ValueError, match="output_format"):
        format_orphan_report([], output_format="xml")


def test_T963_module_does_not_import_main():
    import app.services.files.orphan_scan as mod
    import inspect
    src = inspect.getsource(mod)
    assert "import main" not in src
    assert "from main" not in src
