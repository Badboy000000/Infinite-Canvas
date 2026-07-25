"""节点 PR-8 · NodeUiBinding renderer registry 契约测试。

覆盖:
- 5-slot 白名单(header / body / ports / toolbar / badges)
- renderer 引用只允许标识符 · 拒绝 URL / 签名 query
- allow_fallback 默认 True(硬约束)
- renderer_for(slot) 缺失返回 None
"""
from __future__ import annotations

import pytest

from app.nodes import NODE_UI_SLOTS, NodeUiBinding, NodeUiSlot


def test_T760_ui_slots_frozen():
    """5-slot 顺序冻结(与治理方案 PR-8 契约一致)。"""
    assert NODE_UI_SLOTS == ("header", "body", "ports", "toolbar", "badges")


def test_T761_binding_default_allow_fallback():
    """allow_fallback 默认 True · 缺失 renderer 允许 fallback 旧路径。"""
    b = NodeUiBinding(node_type="generator", renderers={})
    assert b.allow_fallback is True


def test_T762_binding_stores_slot_refs():
    b = NodeUiBinding(
        node_type="generator",
        renderers={
            "header": "classic/generator/header",
            "body": "classic/generator/body",
        },
    )
    assert b.renderer_for("header") == "classic/generator/header"
    assert b.renderer_for("body") == "classic/generator/body"


def test_T763_renderer_for_missing_slot_returns_none():
    b = NodeUiBinding(node_type="prompt", renderers={"body": "classic/prompt/body"})
    assert b.renderer_for("toolbar") is None


@pytest.mark.parametrize("bad_slot", ["footer", "avatar", "context-menu", ""])
def test_T764_unknown_slot_rejected(bad_slot):
    with pytest.raises(ValueError, match="unknown slot"):
        NodeUiBinding(node_type="x", renderers={bad_slot: "classic/x/body"})  # type: ignore[dict-item]


@pytest.mark.parametrize("bad_ref", [
    "https://evil.example.com/renderer.js",
    "http://x/y?token=abc",
    "classic/body?signature=xyz",
    "classic/body&admin=1",
])
def test_T765_url_or_query_in_renderer_ref_rejected(bad_ref):
    """renderer 引用只允许标识符 · 拒绝 URL / signed query。"""
    with pytest.raises(ValueError, match="identifier"):
        NodeUiBinding(node_type="x", renderers={"body": bad_ref})


def test_T766_binding_frozen_dataclass():
    b = NodeUiBinding(node_type="generator")
    with pytest.raises((AttributeError, TypeError)):
        b.node_type = "hacked"  # type: ignore[misc]


def test_T767_all_slots_can_be_populated():
    b = NodeUiBinding(
        node_type="generator",
        renderers={
            "header": "classic/generator/header",
            "body": "classic/generator/body",
            "ports": "classic/generator/ports",
            "toolbar": "classic/generator/toolbar",
            "badges": "classic/generator/badges",
        },
    )
    for slot in NODE_UI_SLOTS:
        assert b.renderer_for(slot) is not None
