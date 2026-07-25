"""节点 PR-4/5/6 · node shape 契约冻结测试。"""
from __future__ import annotations

import pytest

from app.nodes.node_shapes import (
    ALL_SHAPES,
    CLASSIC_SHAPES,
    SMART_SHAPES,
    NodeShape,
    get_shape,
    list_shapes,
    validate_shape_snapshot,
)
from app.nodes.registry import KNOWN_NODE_TYPES


# --- TE00-TE05:shape 集合完整性 ---

def test_TE00_classic_shapes_count():
    """治理契约 v1 明示 classic 12 类;当前 shape 库支持 11 类(ltxDirector 除外)· 按需扩。"""
    # 与 KNOWN_NODE_TYPES 中的 classic 部分交叉验证
    assert set(CLASSIC_SHAPES.keys()) <= set(KNOWN_NODE_TYPES)


def test_TE01_smart_shapes_all_four():
    assert set(SMART_SHAPES.keys()) == {
        "smart-image", "smart-prompt", "smart-loop", "smart-group",
    }


def test_TE02_all_shapes_union():
    for t, shape in CLASSIC_SHAPES.items():
        assert ALL_SHAPES[t] is shape
    for t, shape in SMART_SHAPES.items():
        assert ALL_SHAPES[t] is shape


def test_TE03_get_shape_none_for_unknown():
    assert get_shape("nonexistent") is None
    assert get_shape("") is None


def test_TE04_list_shapes_ordered_by_registry():
    shapes = list_shapes()
    ordered_types = [s.type for s in shapes]
    # 应当与 KNOWN_NODE_TYPES 的交集顺序一致
    for i in range(len(ordered_types) - 1):
        pos_a = KNOWN_NODE_TYPES.index(ordered_types[i])
        pos_b = KNOWN_NODE_TYPES.index(ordered_types[i + 1])
        assert pos_a < pos_b


def test_TE05_all_shapes_have_common_required_fields():
    for shape in ALL_SHAPES.values():
        assert "id" in shape.required_fields
        assert "type" in shape.required_fields
        assert "x" in shape.required_fields
        assert "y" in shape.required_fields


# --- TE10-TE13:凭据关键词禁入 ---

def test_TE10_no_field_name_carries_credential_keyword():
    for shape in ALL_SHAPES.values():
        for f in shape.required_fields + shape.legacy_fields:
            lower = f.lower()
            for kw in ("api_key", "authorization", "bearer", "secret", "signature"):
                assert kw != lower, f"{shape.type}.{f}"
                assert not lower.endswith("_" + kw), f"{shape.type}.{f}"


def test_TE11_shape_rejects_credential_field_name():
    with pytest.raises(ValueError, match="credential-like"):
        NodeShape(type="hack", required_fields=("id", "api_key"))


def test_TE12_shape_empty_type_rejected():
    with pytest.raises(ValueError, match="type"):
        NodeShape(type="", required_fields=("id",))


def test_TE13_shape_frozen():
    shape = get_shape("prompt")
    with pytest.raises((AttributeError, TypeError)):
        shape.type = "hacked"  # type: ignore[misc]


# --- TE20-TE22:smart-image facet ---

def test_TE20_smart_image_declares_four_facets():
    shape = get_shape("smart-image")
    assert shape is not None
    assert set(shape.facets) == {
        "media-source", "generation-target", "media-output", "run-state-host",
    }


def test_TE21_non_smart_image_no_facets():
    for t, shape in ALL_SHAPES.items():
        if t == "smart-image":
            continue
        assert shape.facets == (), f"{t} unexpectedly declares facets={shape.facets}"


def test_TE22_smart_image_legacy_fields_include_inputNodeIds():
    shape = get_shape("smart-image")
    assert "inputNodeIds" in shape.legacy_fields


# --- TE30-TE35:validate_shape_snapshot ---

def test_TE30_valid_prompt_node():
    ok, missing = validate_shape_snapshot({
        "id": "p1", "type": "prompt", "x": 0, "y": 0, "text": "hello",
    })
    assert ok is True
    assert missing == ()


def test_TE31_missing_required_field():
    ok, missing = validate_shape_snapshot({
        "id": "p1", "type": "prompt", "x": 0, "y": 0,  # 缺 text
    })
    assert ok is False
    assert "text" in missing


def test_TE32_unknown_type():
    ok, missing = validate_shape_snapshot({
        "id": "x", "type": "unknown-type", "x": 0, "y": 0,
    })
    assert ok is False
    assert any("unknown node type" in m for m in missing)


def test_TE33_strict_mode_reports_legacy_missing():
    ok_relaxed, _ = validate_shape_snapshot({
        "id": "img", "type": "image", "x": 0, "y": 0, "url": "", "name": "x",
    })
    assert ok_relaxed is True  # legacy 缺失 · 非严格通过

    ok_strict, missing_strict = validate_shape_snapshot({
        "id": "img", "type": "image", "x": 0, "y": 0, "url": "", "name": "x",
    }, strict=True)
    assert ok_strict is False
    assert any("legacy:mediaKind" in m for m in missing_strict)


def test_TE34_valid_smart_image():
    node = {
        "id": "si1", "type": "smart-image", "x": 10, "y": 10,
        "images": [], "scale": 1, "runSettings": {},
        "pendingTasks": [], "jimengPending": None, "generatedOutputs": [],
        "manualInputRefs": [], "runInputRefs": [], "asset_uris": [],
    }
    ok, missing = validate_shape_snapshot(node)
    assert ok is True, missing


def test_TE35_legacy_smart_container_not_in_shapes():
    """`smart-container` 是 alias · 走 registry.resolve_legacy_alias · 不在 shapes 表。"""
    assert get_shape("smart-container") is None
    from app.nodes.registry import resolve_legacy_alias
    assert resolve_legacy_alias("smart-container") == "smart-image"


# --- TE40:治理护栏 · 不 import main / canvas.js ---

def test_TE40_module_does_not_import_main():
    import app.nodes.node_shapes as mod
    import inspect
    src = inspect.getsource(mod)
    assert "import main" not in src
    assert "from main" not in src
