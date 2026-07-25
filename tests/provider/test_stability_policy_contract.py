"""Provider PR-08 · StabilityPolicy 契约测试。"""
from __future__ import annotations

import pytest

from app.adapters.provider.stability_policy import (
    CANCEL_SCOPES,
    COST_CLASSES,
    StabilityPolicy,
    build_default_policy,
    known_protocols,
    suggest_poll_interval,
)


def test_T990_cost_classes_frozen():
    assert COST_CLASSES == ("low", "medium", "high", "very_high")


def test_T991_cancel_scopes_frozen():
    assert CANCEL_SCOPES == ("graceful", "hard", "unsupported")


def test_T992_policy_rejects_bad_cost_class():
    with pytest.raises(ValueError, match="cost_class"):
        StabilityPolicy(
            protocol="x", cost_class="ultra",  # type: ignore[arg-type]
            initial_poll_interval_ms=1000, max_poll_interval_ms=10_000,
            cancel_scope="graceful",
        )


def test_T993_policy_rejects_bad_intervals():
    with pytest.raises(ValueError, match="initial_poll_interval_ms"):
        StabilityPolicy(
            protocol="x", cost_class="medium",
            initial_poll_interval_ms=0, max_poll_interval_ms=1000,
            cancel_scope="graceful",
        )
    with pytest.raises(ValueError, match="max_poll_interval_ms"):
        StabilityPolicy(
            protocol="x", cost_class="medium",
            initial_poll_interval_ms=2000, max_poll_interval_ms=1000,
            cancel_scope="graceful",
        )


def test_T994_policy_rejects_bad_max_attempts_and_backoff():
    with pytest.raises(ValueError, match="max_attempts"):
        StabilityPolicy(
            protocol="x", cost_class="medium",
            initial_poll_interval_ms=1000, max_poll_interval_ms=10_000,
            cancel_scope="graceful", max_attempts=0,
        )
    with pytest.raises(ValueError, match="backoff_factor"):
        StabilityPolicy(
            protocol="x", cost_class="medium",
            initial_poll_interval_ms=1000, max_poll_interval_ms=10_000,
            cancel_scope="graceful", backoff_factor=0.5,
        )


def test_T995_known_protocols_present():
    protocols = known_protocols()
    for expected in (
        "openai_chat", "openai_image", "runninghub", "comfyui",
        "jimeng_cli", "gemini_cli", "codex_cli", "modelscope",
    ):
        assert expected in protocols


def test_T996_jimeng_cli_is_very_high_cost():
    p = build_default_policy("jimeng_cli")
    assert p.cost_class == "very_high"
    assert p.cancel_scope == "hard"


def test_T997_unknown_protocol_gets_conservative_fallback():
    p = build_default_policy("weird_new_provider")
    assert p.cost_class == "high"
    assert p.cancel_scope == "graceful"
    assert p.initial_poll_interval_ms == 3000


def test_T998_suggest_poll_interval_backoff_grows():
    policy = build_default_policy("openai_chat")  # 2000ms initial, 15000 max, backoff 1.5
    values = [suggest_poll_interval(policy, i) for i in range(6)]
    assert values[0] == 2000
    assert values[1] > values[0]
    assert values[2] > values[1]
    # 达到上限后不再增长
    assert values[-1] <= policy.max_poll_interval_ms
    assert max(values) <= policy.max_poll_interval_ms


def test_T999_suggest_poll_interval_negative_attempt_rejected():
    policy = build_default_policy("openai_chat")
    with pytest.raises(ValueError, match="attempt"):
        suggest_poll_interval(policy, -1)


def test_TA00_module_does_not_import_main():
    import app.adapters.provider.stability_policy as mod
    import inspect
    src = inspect.getsource(mod)
    assert "import main" not in src
    assert "from main" not in src
