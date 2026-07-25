"""文件 PR-13 · 签名 URL 通道策略契约测试。"""
from __future__ import annotations

import pytest

from app.services.files.signed_url_policy import (
    SIGNED_URL_INTENTS,
    SIGNED_URL_MODE_AWARE_ENV,
    SignedUrlPolicy,
    build_default_policy,
    is_signed_url_mode_aware,
    is_ttl_within_limit,
)


def test_TD20_defaults_off(monkeypatch):
    monkeypatch.delenv(SIGNED_URL_MODE_AWARE_ENV, raising=False)
    assert is_signed_url_mode_aware() is False


def test_TD21_intents_frozen():
    assert SIGNED_URL_INTENTS == ("get", "put")


def test_TD22_put_disabled_all_modes():
    """Round-2 圆桌决议:PUT presigned 全模式默认关闭。"""
    for mode in ("local_personal", "intranet_team", "public_team"):
        p = build_default_policy(mode, "put")  # type: ignore[arg-type]
        assert p.enabled is False


def test_TD23_get_ttl_local_longest():
    local_ttl = build_default_policy("local_personal", "get").ttl_seconds
    intranet_ttl = build_default_policy("intranet_team", "get").ttl_seconds
    public_ttl = build_default_policy("public_team", "get").ttl_seconds
    assert local_ttl >= intranet_ttl >= public_ttl


def test_TD24_public_get_ttl_max_600s():
    """Round-2 圆桌决议:public_team GET presigned TTL <= 10min。"""
    p = build_default_policy("public_team", "get")
    assert p.ttl_seconds <= 600


def test_TD25_get_requires_auth_in_team_modes():
    for mode in ("intranet_team", "public_team"):
        p = build_default_policy(mode, "get")  # type: ignore[arg-type]
        assert p.require_auth is True


def test_TD26_get_local_no_auth_required():
    p = build_default_policy("local_personal", "get")
    assert p.require_auth is False


def test_TD27_ttl_limit_check():
    policy = build_default_policy("intranet_team", "get")  # 900s
    assert is_ttl_within_limit(policy, 300) is True
    assert is_ttl_within_limit(policy, 900) is True
    assert is_ttl_within_limit(policy, 901) is False
    assert is_ttl_within_limit(policy, 0) is False


def test_TD28_policy_invariants():
    with pytest.raises(ValueError, match="intent"):
        SignedUrlPolicy(
            mode="local_personal",
            intent="delete",  # type: ignore[arg-type]
            enabled=True, ttl_seconds=60, require_auth=False,
        )
    with pytest.raises(ValueError, match="ttl_seconds"):
        SignedUrlPolicy(
            mode="local_personal", intent="get",
            enabled=True, ttl_seconds=-1, require_auth=False,
        )


def test_TD29_unknown_mode_rejected():
    with pytest.raises(ValueError, match="unknown deployment mode"):
        build_default_policy("evil", "get")  # type: ignore[arg-type]


def test_TD30_module_does_not_import_main():
    import app.services.files.signed_url_policy as mod
    import inspect
    src = inspect.getsource(mod)
    assert "import main" not in src
    assert "from main" not in src
