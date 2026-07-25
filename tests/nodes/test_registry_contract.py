"""节点 PR-2 · NodeTypeRegistry 契约测试。

覆盖:
- KNOWN_NODE_TYPES 集合与治理契约 v1 逐字一致
- classic + smart 分类正确
- smart-container legacy alias 解析
- list_node_types / get_node_type / resolve_legacy_alias 只读语义
- smart-image facet 齐备
"""
from __future__ import annotations

import pytest

from app.nodes import (
    KNOWN_NODE_TYPES,
    LEGACY_NODE_ALIASES,
    NodeTypeDescriptor,
    get_node_type,
    list_node_types,
    resolve_legacy_alias,
)
from app.nodes.registry import CLASSIC_NODE_TYPES, SMART_NODE_TYPES


# --- T720-T722:节点类型集合冻结 --------------------------------------------

def test_T720_classic_node_types_frozen():
    """classic 类型清单与治理契约 v1 §"NodeType v1" 逐字一致。"""
    assert CLASSIC_NODE_TYPES == (
        "image", "prompt", "loop", "group", "llm", "generator",
        "msgen", "video", "rh", "ltxDirector", "output", "comfy",
    )


def test_T721_smart_node_types_frozen():
    """smart 类型清单与治理契约 v1 逐字一致。"""
    assert SMART_NODE_TYPES == (
        "smart-image", "smart-prompt", "smart-loop", "smart-group",
    )


def test_T722_known_node_types_count_matches_governance_v1():
    """治理契约 v1 §"NodeType v1":classic 12 + smart 4 = 16 类型。"""
    assert len(KNOWN_NODE_TYPES) == 16
    assert len(set(KNOWN_NODE_TYPES)) == 16  # 无重复


# --- T723-T726:legacy alias --------------------------------------------

def test_T723_smart_container_alias_present():
    """`smart-container -> smart-image` legacy alias 硬约束。"""
    assert LEGACY_NODE_ALIASES.get("smart-container") == "smart-image"


def test_T724_resolve_legacy_alias_smart_container():
    assert resolve_legacy_alias("smart-container") == "smart-image"


def test_T725_resolve_legacy_alias_returns_none_for_unknown():
    assert resolve_legacy_alias("nonexistent-type") is None
    assert resolve_legacy_alias("") is None


def test_T726_get_node_type_resolves_alias_transparently():
    """get_node_type 对 alias 透明解析(返回目标类型的描述符)。"""
    descriptor = get_node_type("smart-container")
    assert descriptor is not None
    assert descriptor.type == "smart-image"


# --- T727-T730:list_node_types / get_node_type 语义 -----------------------

def test_T727_list_node_types_returns_all():
    descriptors = list_node_types()
    types = tuple(d.type for d in descriptors)
    assert types == KNOWN_NODE_TYPES


def test_T728_list_node_types_preserves_classic_before_smart():
    """冻结顺序:classic 12 个在前 · smart 4 个在后。"""
    descriptors = list_node_types()
    first_smart = next(i for i, d in enumerate(descriptors) if d.category == "smart")
    for d in descriptors[:first_smart]:
        assert d.category == "classic"
    for d in descriptors[first_smart:]:
        assert d.category == "smart"


def test_T729_get_node_type_returns_none_for_unknown():
    assert get_node_type("foo") is None
    assert get_node_type("") is None


def test_T730_get_node_type_returns_frozen_descriptor():
    d = get_node_type("generator")
    assert isinstance(d, NodeTypeDescriptor)
    assert d.category == "classic"
    # frozen dataclass 不可修改
    with pytest.raises((AttributeError, TypeError)):
        d.type = "hacked"  # type: ignore[misc]


# --- T731:smart-image facet ---------------------------------------------

def test_T731_smart_image_declares_four_facets():
    """smart-image 复合 facet 声明 · 治理契约 v1 §"smart-image 治理"。"""
    d = get_node_type("smart-image")
    assert d is not None
    assert set(d.facets) == {
        "media-source",
        "generation-target",
        "media-output",
        "run-state-host",
    }


def test_T732_non_smart_image_has_no_facets():
    """只有 smart-image 声明 facets(第一阶段不拆节点)。"""
    for d in list_node_types():
        if d.type == "smart-image":
            continue
        assert d.facets == (), f"{d.type} unexpectedly declares facets={d.facets}"


# --- T733:registry 治理护栏 · 不引入路由 --------------------------------

def test_T733_registry_module_does_not_import_main():
    """`app.nodes.registry` 骨架层禁止导入 `main` · 避免循环依赖。"""
    import app.nodes.registry as reg_mod
    import inspect
    src = inspect.getsource(reg_mod)
    assert "import main" not in src
    assert "from main" not in src
