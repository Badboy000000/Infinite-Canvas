"""部署 PR-09 · RateLimit 前置策略骨架契约测试。"""
from __future__ import annotations

import pytest

from app.security.rate_limit_policy import (
    RATE_LIMIT_POLICY_ENABLED_ENV,
    ROUTE_GROUPS,
    RateLimitPolicy,
    build_default_policies,
    estimate_next_available_ms,
    is_rate_limit_policy_enabled,
)


def test_TA50_defaults_off(monkeypatch):
    monkeypatch.delenv(RATE_LIMIT_POLICY_ENABLED_ENV, raising=False)
    assert is_rate_limit_policy_enabled() is False


def test_TA51_route_groups_frozen():
    assert ROUTE_GROUPS == ("public", "user", "admin", "heavy")


def test_TA52_local_personal_all_unlimited():
    policies = build_default_policies("local_personal")
    for g in ROUTE_GROUPS:
        assert policies[g].unlimited


def test_TA53_intranet_team_heavy_restricted():
    policies = build_default_policies("intranet_team")
    assert policies["heavy"].tokens_per_minute == 20
    assert policies["heavy"].burst == 5
    assert policies["heavy"].scope == "user"


def test_TA54_public_team_stricter_than_intranet():
    intranet = build_default_policies("intranet_team")
    public = build_default_policies("public_team")
    for g in ("public", "user", "heavy"):
        assert public[g].tokens_per_minute <= intranet[g].tokens_per_minute, g


def test_TA55_unknown_mode_rejected():
    with pytest.raises(ValueError, match="unknown deployment mode"):
        build_default_policies("evil")  # type: ignore[arg-type]


def test_TA56_policy_invariants():
    with pytest.raises(ValueError, match="group"):
        RateLimitPolicy(group="foo", tokens_per_minute=60, burst=10)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="tokens_per_minute"):
        RateLimitPolicy(group="user", tokens_per_minute=-1, burst=10)
    with pytest.raises(ValueError, match="burst"):
        RateLimitPolicy(group="user", tokens_per_minute=60, burst=-1)


def test_TA57_estimate_next_available_unlimited():
    policies = build_default_policies("local_personal")
    ms = estimate_next_available_ms(policies["public"], current_tokens=0, tokens_needed=1)
    assert ms == 0


def test_TA58_estimate_next_available_sufficient():
    policies = build_default_policies("intranet_team")
    ms = estimate_next_available_ms(policies["public"], current_tokens=5, tokens_needed=1)
    assert ms == 0


def test_TA59_estimate_next_available_deficit_scales_with_rate():
    # intranet public: 60/min = 1 token / 1000ms
    policies = build_default_policies("intranet_team")
    ms = estimate_next_available_ms(
        policies["public"], current_tokens=0, tokens_needed=1
    )
    # 1 token @ 60/min → 约 1000ms(+1 舍入)
    assert 900 <= ms <= 1100


def test_TA60_public_stricter_takes_longer_to_refill():
    intranet = build_default_policies("intranet_team")  # 60/min
    public = build_default_policies("public_team")      # 30/min
    ms_intranet = estimate_next_available_ms(intranet["public"], current_tokens=0, tokens_needed=1)
    ms_public = estimate_next_available_ms(public["public"], current_tokens=0, tokens_needed=1)
    assert ms_public > ms_intranet


def test_TA61_policy_frozen():
    p = RateLimitPolicy(group="user", tokens_per_minute=60, burst=10)
    with pytest.raises((AttributeError, TypeError)):
        p.tokens_per_minute = 999  # type: ignore[misc]


def test_TA62_module_does_not_import_main():
    import app.security.rate_limit_policy as mod
    import inspect
    src = inspect.getsource(mod)
    assert "import main" not in src
    assert "from main" not in src
