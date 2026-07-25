"""文件 PR-9 · legacy URL 下线判据契约测试。"""
from __future__ import annotations

import pytest

from app.services.files.legacy_url_sunset import (
    FILE_LEGACY_URL_SUNSET_STRICT_ENV,
    LegacyUrlBucket,
    SunsetJudgement,
    VERDICTS,
    build_sunset_report,
    is_legacy_url_sunset_strict,
)


def test_TB00_defaults_off(monkeypatch):
    monkeypatch.delenv(FILE_LEGACY_URL_SUNSET_STRICT_ENV, raising=False)
    assert is_legacy_url_sunset_strict() is False


def test_TB01_verdicts_frozen():
    assert VERDICTS == ("retire", "downgrade", "retain")


def test_TB02_bucket_invariants():
    with pytest.raises(ValueError, match="prefix"):
        LegacyUrlBucket(prefix="", total_urls=1, mapped_urls=0, accesses_last_30d=0)
    with pytest.raises(ValueError, match="counts"):
        LegacyUrlBucket(prefix="/x", total_urls=-1, mapped_urls=0, accesses_last_30d=0)
    with pytest.raises(ValueError, match="mapped_urls"):
        LegacyUrlBucket(prefix="/x", total_urls=5, mapped_urls=10, accesses_last_30d=0)


def test_TB03_zero_access_and_full_mapped_retire():
    bucket = LegacyUrlBucket(prefix="/assets/library", total_urls=100, mapped_urls=100, accesses_last_30d=0)
    report = build_sunset_report([bucket])
    assert len(report) == 1
    assert report[0].verdict == "retire"


def test_TB04_high_ratio_low_traffic_downgrade():
    bucket = LegacyUrlBucket(prefix="/output", total_urls=1000, mapped_urls=850, accesses_last_30d=60)
    report = build_sunset_report([bucket])
    assert report[0].verdict == "downgrade"


def test_TB05_low_ratio_retain():
    bucket = LegacyUrlBucket(prefix="/output", total_urls=1000, mapped_urls=500, accesses_last_30d=100)
    report = build_sunset_report([bucket])
    assert report[0].verdict == "retain"


def test_TB06_high_traffic_retain():
    bucket = LegacyUrlBucket(prefix="/assets", total_urls=1000, mapped_urls=1000, accesses_last_30d=1000)
    report = build_sunset_report([bucket])
    assert report[0].verdict == "retain"


def test_TB07_report_sorted_by_prefix():
    buckets = [
        LegacyUrlBucket(prefix="/z", total_urls=10, mapped_urls=0, accesses_last_30d=100),
        LegacyUrlBucket(prefix="/a", total_urls=10, mapped_urls=0, accesses_last_30d=100),
        LegacyUrlBucket(prefix="/m", total_urls=10, mapped_urls=0, accesses_last_30d=100),
    ]
    report = build_sunset_report(buckets)
    assert [j.prefix for j in report] == ["/a", "/m", "/z"]


def test_TB08_judgement_frozen():
    bucket = LegacyUrlBucket(prefix="/x", total_urls=1, mapped_urls=1, accesses_last_30d=0)
    j = build_sunset_report([bucket])[0]
    with pytest.raises((AttributeError, TypeError)):
        j.verdict = "hacked"  # type: ignore[misc]


def test_TB09_module_does_not_import_main():
    import app.services.files.legacy_url_sunset as mod
    import inspect
    src = inspect.getsource(mod)
    assert "import main" not in src
    assert "from main" not in src
