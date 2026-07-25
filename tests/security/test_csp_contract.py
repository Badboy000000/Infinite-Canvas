"""部署 PR-06 · Content-Security-Policy 契约测试。"""
from __future__ import annotations

import pytest

from app.security.csp import (
    CSP_DIRECTIVE_ORDER,
    CSP_MODE_AWARE_ENABLED_ENV,
    CspPolicy,
    build_csp_policy,
    csp_header_name,
    format_csp_header,
    is_csp_mode_aware_enabled,
)


# --- T900:defaults-off + 冻结指令顺序 ---------------------------

def test_T900_defaults_off(monkeypatch):
    monkeypatch.delenv(CSP_MODE_AWARE_ENABLED_ENV, raising=False)
    assert is_csp_mode_aware_enabled() is False


@pytest.mark.parametrize("val,expected", [
    ("1", True), ("true", True), ("on", True),
    ("", False), ("0", False), ("false", False),
])
def test_T901_env_flag_parsing(monkeypatch, val, expected):
    monkeypatch.setenv(CSP_MODE_AWARE_ENABLED_ENV, val)
    assert is_csp_mode_aware_enabled() is expected


def test_T902_directive_order_stable():
    assert CSP_DIRECTIVE_ORDER[:5] == (
        "default-src", "script-src", "style-src", "img-src", "font-src",
    )
    assert "frame-ancestors" in CSP_DIRECTIVE_ORDER


# --- T903-T905:build_csp_policy 三模式 ---------------------------

def test_T903_local_personal_allows_unsafe_inline_and_eval():
    policy = build_csp_policy("local_personal")
    script_src = policy.directives.get("script-src", ())
    assert "'unsafe-inline'" in script_src
    assert "'unsafe-eval'" in script_src


def test_T904_intranet_team_drops_unsafe_eval_but_keeps_unsafe_inline():
    policy = build_csp_policy("intranet_team")
    script_src = policy.directives.get("script-src", ())
    assert "'unsafe-inline'" in script_src
    assert "'unsafe-eval'" not in script_src


def test_T905_public_team_strict_script_src():
    policy = build_csp_policy("public_team")
    script_src = policy.directives.get("script-src", ())
    assert "'unsafe-inline'" not in script_src
    assert "'unsafe-eval'" not in script_src
    assert "'self'" in script_src
    # public_team 也要求 frame-ancestors 'none' 防夹带
    assert policy.directives.get("frame-ancestors") == ("'none'",)


# --- T906:asset / output 路径允许 img/media -------------------

def test_T906_img_src_includes_assets_and_output():
    for mode in ("local_personal", "intranet_team", "public_team"):
        p = build_csp_policy(mode)
        img = p.directives.get("img-src", ())
        assert "/assets" in img
        assert "/output" in img


# --- T907-T909:extra_directives + frozen ------------------------

def test_T907_extra_directives_override_default():
    policy = build_csp_policy(
        "local_personal",
        extra_directives={"connect-src": ("'self'", "https://cdn.example.com")},
    )
    assert policy.directives["connect-src"] == ("'self'", "https://cdn.example.com")


def test_T908_extra_directives_unknown_key_rejected():
    with pytest.raises(ValueError, match="unknown CSP directive"):
        build_csp_policy(
            "local_personal",
            extra_directives={"foo-src": ("'self'",)},  # type: ignore[dict-item]
        )


def test_T909_policy_frozen():
    p = build_csp_policy("local_personal")
    with pytest.raises((AttributeError, TypeError)):
        p.mode = "hacked"  # type: ignore[misc]


# --- T910-T912:format_csp_header + csp_header_name -------------

def test_T910_header_string_contains_semicolons():
    p = build_csp_policy("intranet_team")
    header = format_csp_header(p)
    assert "default-src 'self'" in header
    assert "script-src 'self' 'unsafe-inline'" in header
    assert "; " in header


def test_T911_header_string_preserves_directive_order():
    """header string 按 CSP_DIRECTIVE_ORDER 冻结顺序输出。"""
    p = build_csp_policy("public_team")
    header = format_csp_header(p)
    idx_default = header.index("default-src")
    idx_script = header.index("script-src")
    idx_style = header.index("style-src")
    assert idx_default < idx_script < idx_style


def test_T912_report_only_header_name():
    p_report = build_csp_policy("public_team", report_only=True)
    p_enforce = build_csp_policy("public_team")
    assert csp_header_name(p_report) == "Content-Security-Policy-Report-Only"
    assert csp_header_name(p_enforce) == "Content-Security-Policy"


# --- T913:治理护栏 · 不 import main --------------------------

def test_T913_module_does_not_import_main():
    import app.security.csp as mod
    import inspect
    src = inspect.getsource(mod)
    assert "import main" not in src
    assert "from main" not in src


# --- T914:unknown mode rejected ---------------------------

def test_T914_unknown_mode_rejected():
    with pytest.raises(ValueError, match="unknown deployment mode"):
        build_csp_policy("foobar")  # type: ignore[arg-type]
