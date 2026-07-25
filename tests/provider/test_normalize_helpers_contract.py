"""Provider PR-06 · normalize_provider helper 契约测试。"""
from __future__ import annotations

import pytest

from app.adapters.provider.normalize_helpers import (
    ensure_provider_id,
    mask_api_key_for_display,
    normalize_base_url,
    sanitize_display_name,
    split_capabilities,
)


# --- T870:sanitize_display_name ---------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("OpenAI", "OpenAI"),
    ("  padded  ", "padded"),
    ("bad\x00chars\x1fhere", "badcharshere"),
    (None, ""),
    ("", ""),
    (123, "123"),
])
def test_T870_display_name_sanitization(raw, expected):
    assert sanitize_display_name(raw) == expected


def test_T871_display_name_truncated_over_limit():
    raw = "x" * 500
    result = sanitize_display_name(raw)
    assert len(result) == 120


def test_T872_display_name_custom_max():
    result = sanitize_display_name("abcdef", max_length=3)
    assert result == "abc"


# --- T873-T876:normalize_base_url --------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("https://api.openai.com/v1/", "https://api.openai.com/v1"),
    ("https://api.openai.com/v1", "https://api.openai.com/v1"),
    ("HTTPS://x.com/", "HTTPS://x.com/"),  # scheme 大小写保留 · lower 判断
    ("", ""),
    (None, ""),
    ("ftp://x/y", ""),   # 非 http(s) 拒绝
    ("javascript:alert(1)", ""),
])
def test_T873_base_url_normalization(raw, expected):
    result = normalize_base_url(raw)
    # 允许长度差异一个 slash 的容忍
    if expected == "HTTPS://x.com/":
        assert result in ("HTTPS://x.com", "HTTPS://x.com/")
    else:
        assert result == expected


def test_T874_https_base_url_preserved():
    assert normalize_base_url("https://x.com/api") == "https://x.com/api"


def test_T875_http_base_url_preserved():
    assert normalize_base_url("http://internal.local:8080") == "http://internal.local:8080"


def test_T876_trailing_slashes_stripped():
    result = normalize_base_url("https://api.example.com/v1////")
    assert result == "https://api.example.com/v1"


# --- T877-T880:ensure_provider_id ---------------------------------

@pytest.mark.parametrize("raw", [
    "prov_openai_01",
    "openai",
    "Provider-1",
    "P1",
])
def test_T877_valid_ids_accepted(raw):
    assert ensure_provider_id(raw) == raw


@pytest.mark.parametrize("raw", [
    "1starts-with-digit",
    "has space",
    "with;semicolon",
    "包含中文",
    "",
])
def test_T878_invalid_ids_rejected(raw):
    with pytest.raises(ValueError, match="invalid"):
        ensure_provider_id(raw)


def test_T879_invalid_id_falls_back_to_valid_fallback():
    assert ensure_provider_id("1bad", fallback="prov_fallback_01") == "prov_fallback_01"


def test_T880_both_invalid_raises():
    with pytest.raises(ValueError, match="invalid"):
        ensure_provider_id("1bad", fallback="2also-bad")


# --- T881-T883:split_capabilities ---------------------------------

@pytest.mark.parametrize("raw,expected", [
    (["chat", "generate_image"], ("chat", "generate_image")),
    ("chat,generate_image,generate_video", ("chat", "generate_image", "generate_video")),
    ("chat, ,generate_image", ("chat", "generate_image")),  # 空段落被剔除
    ({"chat": True, "generate_image": True, "video": False}, ("chat", "generate_image")),
    (None, ()),
    ("", ()),
    ([], ()),
])
def test_T881_capabilities_splitting(raw, expected):
    result = split_capabilities(raw)
    # dict order 在 Python 3.7+ 保证 · 排序断言避免 dict path 顺序敏感
    assert set(result) == set(expected)
    if not isinstance(raw, dict):
        assert result == expected


# --- T884-T886:mask_api_key_for_display ---------------------------

def test_T884_mask_long_key():
    result = mask_api_key_for_display("sk-abcdef1234567890xyz")
    assert result == "sk-a...0xyz"
    # 严禁泄漏中间段
    assert "abcdef" not in result
    assert "1234567890" not in result


def test_T885_mask_short_key_all_stars():
    assert mask_api_key_for_display("short") == "***"
    assert mask_api_key_for_display("") == ""


def test_T886_mask_none_returns_empty():
    assert mask_api_key_for_display(None) == ""


def test_T887_mask_custom_keep():
    result = mask_api_key_for_display("sk-abcdef1234567890xyz", keep=2)
    assert result == "sk...yz"


# --- T888:治理护栏 · 不 import main -----------------------------

def test_T888_module_does_not_import_main():
    import app.adapters.provider.normalize_helpers as mod
    import inspect
    src = inspect.getsource(mod)
    assert "import main" not in src
    assert "from main" not in src
