"""文件 PR-10 · AssetItemFileRef 语义切换契约测试。"""
from __future__ import annotations

import pytest

from app.services.files.asset_item_ref import (
    ALLOWED_ASSET_KINDS,
    ASSET_ITEM_REF_STRICT_ENV,
    AssetItemFileRef,
    build_asset_item_file_ref,
    is_asset_item_ref_strict,
    is_legacy_only,
    is_migrated,
)


def test_T970_defaults_off(monkeypatch):
    monkeypatch.delenv(ASSET_ITEM_REF_STRICT_ENV, raising=False)
    assert is_asset_item_ref_strict() is False


def test_T971_allowed_asset_kinds():
    assert ALLOWED_ASSET_KINDS == ("image", "video", "workflow", "audio", "other")


def test_T972_ref_requires_at_least_one_side():
    with pytest.raises(ValueError, match="at least one"):
        AssetItemFileRef(
            asset_library_id="lib-1",
            asset_item_id="item-1",
            asset_kind="image",
            file_object_id=None,
            legacy_url=None,
        )


def test_T973_ref_legacy_only_state():
    ref = build_asset_item_file_ref(
        asset_library_id="lib-1",
        asset_item_id="item-1",
        asset_kind="image",
        legacy_url="/assets/library/xxx.png",
    )
    assert is_legacy_only(ref) is True
    assert is_migrated(ref) is False


def test_T974_ref_migrated_state():
    ref = build_asset_item_file_ref(
        asset_library_id="lib-1",
        asset_item_id="item-1",
        asset_kind="image",
        file_object_id="f-1",
        legacy_url="/assets/library/xxx.png",
    )
    assert is_migrated(ref) is True
    assert is_legacy_only(ref) is False


def test_T975_unknown_asset_kind_rejected():
    with pytest.raises(ValueError, match="asset_kind"):
        build_asset_item_file_ref(
            asset_library_id="lib-1",
            asset_item_id="item-1",
            asset_kind="foo",  # type: ignore[arg-type]
            file_object_id="f",
        )


def test_T976_empty_ids_rejected():
    with pytest.raises(ValueError, match="asset_library_id"):
        build_asset_item_file_ref(
            asset_library_id="", asset_item_id="i", asset_kind="image", file_object_id="f",
        )
    with pytest.raises(ValueError, match="asset_item_id"):
        build_asset_item_file_ref(
            asset_library_id="l", asset_item_id="", asset_kind="image", file_object_id="f",
        )


def test_T977_to_persistable_omits_none_fields():
    ref = build_asset_item_file_ref(
        asset_library_id="lib-1",
        asset_item_id="item-1",
        asset_kind="video",
        file_object_id="fo-1",
    )
    view = ref.to_persistable()
    assert view["file_object_id"] == "fo-1"
    assert "legacy_url" not in view
    assert "file_ref_id" not in view


def test_T978_to_persistable_includes_all_when_present():
    ref = build_asset_item_file_ref(
        asset_library_id="lib-1",
        asset_item_id="item-1",
        asset_kind="workflow",
        file_object_id="fo-1",
        legacy_url="/assets/library/wf.zip",
        file_ref_id="fr-1",
    )
    view = ref.to_persistable()
    assert view["file_object_id"] == "fo-1"
    assert view["legacy_url"] == "/assets/library/wf.zip"
    assert view["file_ref_id"] == "fr-1"


def test_T979_ref_is_frozen():
    ref = build_asset_item_file_ref(
        asset_library_id="l", asset_item_id="i", asset_kind="image", file_object_id="f",
    )
    with pytest.raises((AttributeError, TypeError)):
        ref.asset_library_id = "hacked"  # type: ignore[misc]


def test_T980_module_does_not_import_main():
    import app.services.files.asset_item_ref as mod
    import inspect
    src = inspect.getsource(mod)
    assert "import main" not in src
    assert "from main" not in src
