"""部署 PR-12 · CSRF 前置策略骨架契约测试。"""
from __future__ import annotations

import pytest

from app.security.csrf_policy import (
    CSRF_EXEMPT_PATH_PREFIXES,
    CSRF_POLICY_ENABLED_ENV,
    CSRF_TOKEN_SCOPES,
    CsrfPolicy,
    STATE_MUTATING_METHODS,
    build_default_policy,
    is_csrf_policy_enabled,
    is_method_state_mutating,
    is_path_csrf_exempt,
    should_check_csrf,
)


def test_TC00_defaults_off(monkeypatch):
    monkeypatch.delenv(CSRF_POLICY_ENABLED_ENV, raising=False)
    assert is_csrf_policy_enabled() is False


def test_TC01_state_mutating_methods_frozen():
    assert STATE_MUTATING_METHODS == ("POST", "PUT", "PATCH", "DELETE")


def test_TC02_token_scopes_frozen():
    assert CSRF_TOKEN_SCOPES == ("session_bound", "request_bound")


def test_TC03_exempt_prefixes_include_health_and_ws():
    assert "/api/health" in CSRF_EXEMPT_PATH_PREFIXES
    assert any(p.startswith("/ws") for p in CSRF_EXEMPT_PATH_PREFIXES)


def test_TC04_local_personal_disabled():
    p = build_default_policy("local_personal")
    assert p.enabled is False


def test_TC05_intranet_enabled_session_bound():
    p = build_default_policy("intranet_team")
    assert p.enabled is True
    assert p.token_scope == "session_bound"
    assert p.require_double_cookie is False


def test_TC06_public_strict():
    p = build_default_policy("public_team")
    assert p.enabled is True
    assert p.token_scope == "request_bound"
    assert p.require_double_cookie is True
    assert p.same_site_cookie == "Strict"
    assert p.token_lifetime_seconds == 15 * 60


def test_TC07_policy_invariants():
    with pytest.raises(ValueError, match="token_scope"):
        CsrfPolicy(
            mode="public_team", enabled=True,
            token_scope="forever",  # type: ignore[arg-type]
            token_lifetime_seconds=60, require_double_cookie=True,
        )
    with pytest.raises(ValueError, match="token_lifetime_seconds"):
        CsrfPolicy(
            mode="public_team", enabled=True, token_scope="request_bound",
            token_lifetime_seconds=-1, require_double_cookie=True,
        )


@pytest.mark.parametrize("method,expected", [
    ("GET", False), ("HEAD", False), ("OPTIONS", False),
    ("POST", True), ("PUT", True), ("PATCH", True), ("DELETE", True),
    ("post", True), ("delete", True),
])
def test_TC08_method_state_mutating(method, expected):
    assert is_method_state_mutating(method) is expected


@pytest.mark.parametrize("path,expected", [
    ("/api/health", True),
    ("/api/_diag/x", True),
    ("/ws/canvas", True),
    ("/api/providers", False),
    ("", False),
])
def test_TC09_path_csrf_exempt(path, expected):
    assert is_path_csrf_exempt(path) is expected


def test_TC10_should_check_csrf_flow():
    p_local = build_default_policy("local_personal")
    p_public = build_default_policy("public_team")

    # local_personal 全部不检查
    assert should_check_csrf(p_local, "POST", "/api/providers") is False

    # public_team + POST + 非豁免路径 → 检查
    assert should_check_csrf(p_public, "POST", "/api/providers") is True

    # public_team + GET → 不检查
    assert should_check_csrf(p_public, "GET", "/api/providers") is False

    # public_team + POST + 豁免路径 → 不检查
    assert should_check_csrf(p_public, "POST", "/api/health") is False


def test_TC11_unknown_mode_rejected():
    with pytest.raises(ValueError, match="unknown deployment mode"):
        build_default_policy("evil")  # type: ignore[arg-type]


def test_TC12_module_does_not_import_main():
    import app.security.csrf_policy as mod
    import inspect
    src = inspect.getsource(mod)
    assert "import main" not in src
    assert "from main" not in src
