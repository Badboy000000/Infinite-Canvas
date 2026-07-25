"""Provider PR-09 · ProviderRegistryHealth 探针骨架契约测试。"""
from __future__ import annotations

import pytest

from app.adapters.provider.health_probe import (
    HEALTH_KINDS,
    ProviderHealth,
    ProviderRegistryHealth,
    build_health_view,
)


def test_TA10_health_kinds_frozen():
    assert HEALTH_KINDS == ("ok", "degraded", "unreachable", "misconfigured", "unknown")


def test_TA11_health_rejects_bad_kind():
    with pytest.raises(ValueError, match="kind"):
        ProviderHealth(provider_id="p", protocol="openai_chat", kind="bad")  # type: ignore[arg-type]


def test_TA12_health_rejects_empty_provider_id():
    with pytest.raises(ValueError, match="provider_id"):
        ProviderHealth(provider_id="", protocol="x", kind="ok")


@pytest.mark.parametrize("bad_detail", [
    "api_key rotated",
    "authorization header missing",
    "Bearer token expired",
    "sk-live-abc detected in payload",
])
def test_TA13_health_detail_rejects_credential_keywords(bad_detail):
    with pytest.raises(ValueError, match="credential-like"):
        ProviderHealth(
            provider_id="p", protocol="openai_chat", kind="degraded", detail=bad_detail,
        )


def test_TA14_health_detail_allows_operational_message():
    h = ProviderHealth(
        provider_id="p", protocol="openai_chat", kind="degraded",
        detail="latency exceeds 5000ms",
    )
    assert h.detail == "latency exceeds 5000ms"


def test_TA15_build_view_empty():
    view = build_health_view([])
    assert view.entries == ()
    assert view.total == 0
    assert view.is_all_ok() is False


def test_TA16_build_view_counts_and_sorts():
    reports = [
        ProviderHealth(provider_id="p3", protocol="x", kind="ok"),
        ProviderHealth(provider_id="p1", protocol="x", kind="degraded"),
        ProviderHealth(provider_id="p2", protocol="x", kind="ok"),
        ProviderHealth(provider_id="p5", protocol="x", kind="unreachable"),
        ProviderHealth(provider_id="p4", protocol="x", kind="misconfigured"),
    ]
    view = build_health_view(reports)
    assert [h.provider_id for h in view.entries] == ["p1", "p2", "p3", "p4", "p5"]
    assert view.ok_count == 2
    assert view.degraded_count == 1
    assert view.unreachable_count == 1
    assert view.misconfigured_count == 1
    assert view.unknown_count == 0
    assert view.total == 5
    assert view.is_all_ok() is False


def test_TA17_all_ok_view():
    reports = [
        ProviderHealth(provider_id="p1", protocol="x", kind="ok"),
        ProviderHealth(provider_id="p2", protocol="x", kind="ok"),
    ]
    view = build_health_view(reports)
    assert view.is_all_ok() is True


def test_TA18_view_frozen():
    view = build_health_view([])
    with pytest.raises((AttributeError, TypeError)):
        view.ok_count = 999  # type: ignore[misc]


def test_TA19_module_does_not_import_main():
    import app.adapters.provider.health_probe as mod
    import inspect
    src = inspect.getsource(mod)
    assert "import main" not in src
    assert "from main" not in src
