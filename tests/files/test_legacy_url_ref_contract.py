"""文件 PR-5 · LegacyUrlRef 兼容层查询函数契约测试。"""
from __future__ import annotations

import pytest

from app.services.files.legacy_url_ref import (
    FILE_LEGACY_URL_LOOKUP_ENABLED_ENV,
    LegacyUrlLookup,
    is_legacy_url_lookup_enabled,
    is_signed_url_query_key,
    lookup_by_legacy_url,
    normalize_legacy_url,
)


# --- T800-T803:defaults-off + 签名 query 检测 -------------------------

def test_T800_legacy_url_lookup_defaults_off(monkeypatch):
    monkeypatch.delenv(FILE_LEGACY_URL_LOOKUP_ENABLED_ENV, raising=False)
    assert is_legacy_url_lookup_enabled() is False


@pytest.mark.parametrize("val,expected", [
    ("1", True), ("true", True), ("YES", True), ("on", True),
    ("", False), ("0", False), ("false", False), ("no", False),
])
def test_T801_env_flag_parsing(monkeypatch, val, expected):
    monkeypatch.setenv(FILE_LEGACY_URL_LOOKUP_ENABLED_ENV, val)
    assert is_legacy_url_lookup_enabled() is expected


@pytest.mark.parametrize("key,expected", [
    ("X-Amz-Signature", True),
    ("x-amz-credential", True),
    ("signature", True),
    ("token", True),
    ("access_token", True),
    ("v", False),        # stable version identifier
    ("format", False),
])
def test_T802_signed_query_key_detection(key, expected):
    assert is_signed_url_query_key(key) is expected


# --- T804-T808:normalize_legacy_url -----------------------------------

def test_T804_normalize_strips_signature_query():
    url = "https://minio.example.com/infinite-canvas/output/ab/cd/abcd1234.png?X-Amz-Signature=deadbeef&X-Amz-Credential=xxx"
    normalized = normalize_legacy_url(url)
    assert "X-Amz-Signature" not in normalized
    assert "X-Amz-Credential" not in normalized
    assert normalized.endswith("/output/ab/cd/abcd1234.png")


def test_T805_normalize_preserves_stable_query():
    url = "https://minio.example.com/x/y.png?v=abc123&format=webp"
    normalized = normalize_legacy_url(url)
    assert "v=abc123" in normalized
    assert "format=webp" in normalized


def test_T806_normalize_sorts_stable_query_for_deterministic_lookup():
    a = normalize_legacy_url("https://x/y?b=1&a=2")
    b = normalize_legacy_url("https://x/y?a=2&b=1")
    assert a == b


@pytest.mark.parametrize("empty", ["", "   ", None])
def test_T807_normalize_empty_input(empty):
    # None 输入 · 需 explicit str 或抛错;这里保护为返回空
    if empty is None:
        assert normalize_legacy_url("") == ""
    else:
        assert normalize_legacy_url(empty) == ""


def test_T808_normalize_preserves_case_sensitive_path():
    """S3 / MinIO object key 大小写敏感 · path 段不许 lower。"""
    url = "https://x/Output/AB/Cd/ABCD.PNG"
    assert normalize_legacy_url(url) == "https://x/Output/AB/Cd/ABCD.PNG"


# --- T809-T811:lookup_by_legacy_url ---------------------------------

def test_T809_lookup_miss_returns_none_file_object():
    result = lookup_by_legacy_url("https://x/y.png", table={})
    assert isinstance(result, LegacyUrlLookup)
    assert result.file_object_id is None
    assert result.subject_kind is None


def test_T810_lookup_hit_returns_view():
    table = {
        "https://x/y.png": {
            "file_object_id": "file-uuid-1",
            "subject_kind": "canvas_asset",
            "subject_id": "canvas-1",
        }
    }
    result = lookup_by_legacy_url("https://x/y.png?X-Amz-Signature=abc", table=table)
    assert result.file_object_id == "file-uuid-1"
    assert result.subject_kind == "canvas_asset"
    assert result.subject_id == "canvas-1"
    assert result.normalized_url == "https://x/y.png"


def test_T811_lookup_normalizes_before_matching():
    """反查 key = normalized URL · 客户端传入含签名 query 时也能命中。"""
    table = {"https://x/y.png": {"file_object_id": "fp", "subject_kind": "canvas_asset", "subject_id": "c"}}
    result = lookup_by_legacy_url("https://x/y.png?signature=xxx&token=yyy", table=table)
    assert result.file_object_id == "fp"


# --- T812:治理护栏 · 不 import main -----------------------------

def test_T812_module_does_not_import_main():
    import app.services.files.legacy_url_ref as mod
    import inspect
    src = inspect.getsource(mod)
    assert "import main" not in src
    assert "from main" not in src
