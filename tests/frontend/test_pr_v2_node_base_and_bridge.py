"""Wave 3-N.11 Vue move PR-V2 · 节点组件基类 + factory 桥接契约测试.

Editorial:
    Verifies the Vue-side node base component + createNodeInPage composable
    for the node-move era:
      - NodeBase.vue is a legal SFC (script setup + template + scoped style)
      - NodeBase defines props {node: Object, readonly: Boolean}
      - NodeBase template uses only {{ }} interpolation — no v-html
        (P0 credential-zero-leak defense)
      - NodeBase does NOT import useNodeFactory / useNodeStore
        (single responsibility — display shell only)
      - useCreateNode.js imports both useNodeStore and useNodeFactory
        (end-to-end bridge)
      - useCreateNode.js contains no literal 'smart-container' / 'smart-image'
        (alias delegation — single source of truth in NodeConfigRegistry)
      - useCreateNode.js validates point {x, y}

    Static-only assertions (regex + string search). Does NOT run npm install
    or start Vite / vitest / a Vue app — same posture as PR-V1 skeleton.

Covers T548-T554 (7 items):

    T548  NodeBase.vue exists with <script setup>, <template>, <style scoped>
    T549  NodeBase.vue defineProps signature: node: Object, readonly: Boolean
    T550  NodeBase.vue template uses interpolation only (no v-html)
    T551  NodeBase.vue does NOT import useNodeFactory / useNodeStore
    T552  useCreateNode.js imports useNodeStore AND useNodeFactory
    T553  useCreateNode.js has no literal 'smart-container' / 'smart-image'
    T554  useCreateNode.js validates point (x/y numeric checks)
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

NODE_BASE_PATH = ROOT / "static/src/components/nodes/NodeBase.vue"
USE_CREATE_NODE_PATH = ROOT / "static/src/composables/useCreateNode.js"


# --- T548 ---

def test_t548_node_base_component_exists():
    """T548 · NodeBase.vue exists as a legal SFC with three canonical sections."""
    assert NODE_BASE_PATH.is_file(), (
        f"static/src/components/nodes/NodeBase.vue not found at {NODE_BASE_PATH}"
    )
    text = NODE_BASE_PATH.read_text(encoding="utf-8")
    assert re.search(r"<script\s+setup\b", text), (
        "NodeBase.vue missing <script setup> block (Composition API idiom)"
    )
    assert "<template>" in text and "</template>" in text, (
        "NodeBase.vue missing <template> block"
    )
    assert re.search(r"<style\s+scoped\b", text), (
        "NodeBase.vue missing <style scoped> block (style isolation)"
    )


# --- T549 ---

def test_t549_node_base_props_signature():
    """T549 · NodeBase.vue defineProps includes node: Object, readonly: Boolean."""
    text = NODE_BASE_PATH.read_text(encoding="utf-8")
    assert "defineProps" in text, "NodeBase.vue missing defineProps call"
    # node: Object (allow full-form { type: Object, required: true, ... })
    assert re.search(r"node\s*:\s*(Object|\{[^}]*type\s*:\s*Object)", text), (
        "NodeBase.vue defineProps missing `node: Object`"
    )
    # readonly: Boolean (allow full-form { type: Boolean, default: false })
    assert re.search(r"readonly\s*:\s*(Boolean|\{[^}]*type\s*:\s*Boolean)", text), (
        "NodeBase.vue defineProps missing `readonly: Boolean`"
    )


# --- T550 ---

def test_t550_node_base_template_uses_interpolation_only():
    """T550 · NodeBase.vue template MUST NOT contain v-html
    (P0 credential-zero-leak defense — GM密钥保护线)."""
    text = NODE_BASE_PATH.read_text(encoding="utf-8")
    # Isolate the template block to only assert on rendered surface
    tmpl_match = re.search(r"<template>([\s\S]*?)</template>", text)
    assert tmpl_match, "NodeBase.vue template block not extractable"
    tmpl = tmpl_match.group(1)
    assert "v-html" not in tmpl, (
        "NodeBase.vue template uses v-html — forbidden for credential-zero-leak"
    )


# --- T551 ---

def test_t551_node_base_does_not_import_factory_seam():
    """T551 · NodeBase.vue MUST NOT import useNodeFactory or useNodeStore.
    Single responsibility: display shell only. Generation belongs in
    useCreateNode / SFC page code, not the base component."""
    text = NODE_BASE_PATH.read_text(encoding="utf-8")
    assert "useNodeFactory" not in text, (
        "NodeBase.vue references useNodeFactory — violation of display-only "
        "single-responsibility; generation must not leak into the base shell"
    )
    assert "useNodeStore" not in text, (
        "NodeBase.vue references useNodeStore — violation of display-only "
        "single-responsibility; identity/registry must not leak into the base shell"
    )


# --- T552 ---

def test_t552_use_create_node_composes_store_and_factory():
    """T552 · useCreateNode.js imports both useNodeStore and useNodeFactory
    (end-to-end bridge: id from store, shape from factory)."""
    assert USE_CREATE_NODE_PATH.is_file(), (
        f"static/src/composables/useCreateNode.js not found at {USE_CREATE_NODE_PATH}"
    )
    text = USE_CREATE_NODE_PATH.read_text(encoding="utf-8")
    assert re.search(
        r"import\s*\{\s*useNodeStore\s*\}\s*from\s*['\"][^'\"]*stores/nodeStore['\"]",
        text,
    ), "useCreateNode.js missing `import { useNodeStore } from '.../stores/nodeStore'`"
    assert re.search(
        r"import\s*\{\s*useNodeFactory\s*\}\s*from\s*['\"][^'\"]*composables/useNodeFactory['\"]",
        text,
    ), "useCreateNode.js missing `import { useNodeFactory } from '.../composables/useNodeFactory'`"
    # Compose call sites
    assert re.search(r"nodeStore\.newId\s*\(", text) or re.search(
        r"useNodeStore\s*\(\s*\)", text
    ), "useCreateNode.js has no call site for nodeStore / useNodeStore()"
    assert re.search(r"\.createByType\s*\(", text), (
        "useCreateNode.js has no call site for factory.createByType"
    )


# --- T553 ---

def test_t553_use_create_node_no_alias_literal_leak():
    """T553 · useCreateNode.js MUST NOT contain literal 'smart-container' /
    'smart-image'. Alias resolution is delegated to useNodeFactory →
    NodeConfigRegistry.normalizeAlias (single source of truth)."""
    text = USE_CREATE_NODE_PATH.read_text(encoding="utf-8")
    assert "'smart-container'" not in text and '"smart-container"' not in text, (
        "useCreateNode.js contains literal 'smart-container' — alias table "
        "must live only in NodeConfigRegistry (delegated via useNodeFactory)"
    )
    assert "'smart-image'" not in text and '"smart-image"' not in text, (
        "useCreateNode.js contains literal 'smart-image' — do not duplicate "
        "alias-target constants; delegate to useNodeFactory.createByType"
    )


# --- T554 ---

def test_t554_use_create_node_point_validation():
    """T554 · useCreateNode.js validates point {x:number, y:number} before
    dispatching to the seam (fail-fast, mirrors factories.js _requirePoint)."""
    text = USE_CREATE_NODE_PATH.read_text(encoding="utf-8")
    # Ensure point is inspected: reference to point.x AND point.y numeric checks
    assert "point.x" in text and "point.y" in text, (
        "useCreateNode.js does not read point.x / point.y — must validate "
        "before dispatch (fail-fast)"
    )
    assert "typeof point.x" in text and "typeof point.y" in text, (
        "useCreateNode.js does not check typeof point.x / point.y — "
        "numeric type guard missing"
    )
