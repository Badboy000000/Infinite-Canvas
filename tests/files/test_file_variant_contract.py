"""文件 PR-11 · FileVariant + 预览缓存 key 契约测试。"""
from __future__ import annotations

import pytest

from app.services.files.file_variant import (
    FILE_VARIANT_CACHE_ENABLED_ENV,
    FileVariant,
    THUMBNAIL_PRESETS,
    VARIANT_KINDS,
    compute_variant_key,
    is_variant_cache_enabled,
    suggest_thumbnail_size,
)


def test_TB20_defaults_off(monkeypatch):
    monkeypatch.delenv(FILE_VARIANT_CACHE_ENABLED_ENV, raising=False)
    assert is_variant_cache_enabled() is False


def test_TB21_variant_kinds_frozen():
    assert VARIANT_KINDS == ("thumbnail", "preview", "transcoded", "original")


def test_TB22_thumbnail_presets_ascending():
    assert list(THUMBNAIL_PRESETS) == sorted(THUMBNAIL_PRESETS)


def test_TB23_variant_rejects_bad_kind():
    with pytest.raises(ValueError, match="kind"):
        FileVariant(kind="foo")  # type: ignore[arg-type]


def test_TB24_original_variant_must_have_no_geometry():
    with pytest.raises(ValueError, match="original variant"):
        FileVariant(kind="original", width=100)


def test_TB25_variant_rejects_nonpositive_geometry():
    with pytest.raises(ValueError, match="width"):
        FileVariant(kind="thumbnail", width=0)
    with pytest.raises(ValueError, match="height"):
        FileVariant(kind="thumbnail", height=-1)


def test_TB26_key_stable():
    v = FileVariant(kind="thumbnail", width=256, height=256, format="webp")
    key = compute_variant_key("file-abc", v)
    assert key == "variant/thumbnail/file-abc/256x256/webp"


def test_TB27_key_original_shape():
    v = FileVariant(kind="original")
    key = compute_variant_key("file-xyz", v)
    assert key == "variant/original/file-xyz"


def test_TB28_key_rejects_credential_in_id():
    v = FileVariant(kind="preview", width=128, height=128)
    for bad in ("has-api_key", "authorization-abc", "bearer-token", "../etc/passwd"):
        with pytest.raises(ValueError, match="forbidden token"):
            compute_variant_key(bad, v)


def test_TB29_key_rejects_empty_id():
    with pytest.raises(ValueError, match="file_object_id"):
        compute_variant_key("", FileVariant(kind="original"))


def test_TB30_suggest_thumbnail_picks_largest_below_edge():
    assert suggest_thumbnail_size(300) == 256
    assert suggest_thumbnail_size(64) == 64
    assert suggest_thumbnail_size(63) == THUMBNAIL_PRESETS[0]  # too small · fallback smallest
    assert suggest_thumbnail_size(2000) == 512


def test_TB31_suggest_thumbnail_rejects_zero():
    with pytest.raises(ValueError, match="long_edge_px"):
        suggest_thumbnail_size(0)


def test_TB32_module_does_not_import_main():
    import app.services.files.file_variant as mod
    import inspect
    src = inspect.getsource(mod)
    assert "import main" not in src
    assert "from main" not in src
