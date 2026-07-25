"""节点 PR-2 前端 seam registry crossref 契约测试。

后端 `app/nodes/registry.py` 与前端 `static/js/shared/nodes/registry.js` 必须保持
类型清单与 legacy alias 逐字一致(治理契约 v1 硬约束)。用简单文本 grep 校验 ·
无 Node runtime 依赖(seam 期零构建零依赖硬约束)。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.nodes.registry import (
    CLASSIC_NODE_TYPES,
    KNOWN_NODE_TYPES,
    LEGACY_NODE_ALIASES,
    SMART_NODE_TYPES,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
JS_REGISTRY = REPO_ROOT / "static" / "js" / "shared" / "nodes" / "registry.js"


def _extract_string_array(text: str, var_name: str) -> list[str]:
    """从 JS 源里抓 `const VAR = Object.freeze([...]);` 中的字符串列表。"""
    # 匹配 var_name 到分号之间;跨行;取 [] 里全部单引号字符串
    m = re.search(
        rf"const\s+{re.escape(var_name)}\s*=\s*Object\.freeze\(\[([^\]]*)\]\)",
        text,
        re.DOTALL,
    )
    if not m:
        raise AssertionError(f"variable {var_name!r} not found in {JS_REGISTRY}")
    body = m.group(1)
    # 抓每一个单引号字面量
    return re.findall(r"'([^']+)'", body)


def _load_js() -> str:
    assert JS_REGISTRY.exists(), f"missing front-end seam: {JS_REGISTRY}"
    return JS_REGISTRY.read_text(encoding="utf-8")


def test_T770_frontend_seam_file_exists():
    assert JS_REGISTRY.exists()


def test_T771_classic_types_match_frontend():
    js_text = _load_js()
    js_classic = tuple(_extract_string_array(js_text, "CLASSIC_NODE_TYPES"))
    assert js_classic == CLASSIC_NODE_TYPES


def test_T772_smart_types_match_frontend():
    js_text = _load_js()
    js_smart = tuple(_extract_string_array(js_text, "SMART_NODE_TYPES"))
    assert js_smart == SMART_NODE_TYPES


def test_T773_known_types_union_matches_frontend():
    """前端 KNOWN_NODE_TYPES 由 spread 拼接 · 用类型清单等价性验证。"""
    js_text = _load_js()
    js_classic = tuple(_extract_string_array(js_text, "CLASSIC_NODE_TYPES"))
    js_smart = tuple(_extract_string_array(js_text, "SMART_NODE_TYPES"))
    assert js_classic + js_smart == KNOWN_NODE_TYPES
    # 交叉验证:前端源码里确实使用 `...CLASSIC_NODE_TYPES, ...SMART_NODE_TYPES` 拼接
    assert re.search(
        r"const\s+KNOWN_NODE_TYPES\s*=\s*Object\.freeze\(\[\s*\.\.\.CLASSIC_NODE_TYPES\s*,\s*\.\.\.SMART_NODE_TYPES\s*\]\)",
        js_text,
    ), "KNOWN_NODE_TYPES must be `Object.freeze([...CLASSIC_NODE_TYPES, ...SMART_NODE_TYPES])`"


def test_T774_legacy_aliases_match_frontend():
    """`smart-container -> smart-image` 前后端一致(治理契约 v1 硬约束)。"""
    js_text = _load_js()
    # 找 `LEGACY_NODE_ALIASES = Object.freeze({ ... })`
    m = re.search(
        r"const\s+LEGACY_NODE_ALIASES\s*=\s*Object\.freeze\(\{([^}]*)\}\)",
        js_text,
        re.DOTALL,
    )
    assert m, "LEGACY_NODE_ALIASES not found in frontend registry.js"
    body = m.group(1)
    pairs = re.findall(r"'([^']+)'\s*:\s*'([^']+)'", body)
    js_aliases = dict(pairs)
    assert js_aliases == dict(LEGACY_NODE_ALIASES)


def test_T775_frontend_registry_has_no_module_side_effects():
    """seam 骨架必须 IIFE 装载 · 不做 fetch / 不做 DOM 副作用。"""
    js_text = _load_js()
    forbidden = ["fetch(", "XMLHttpRequest", "document.write", "localStorage"]
    for token in forbidden:
        assert token not in js_text, (
            f"frontend registry.js unexpectedly contains {token!r}; seam must be side-effect-free"
        )


def test_T776_no_credentials_in_frontend_registry():
    """registry.js 是元信息层 · 严禁承载凭据。"""
    js_text = _load_js().lower()
    for kw in ("api_key", "authorization", "bearer ", "secret", "sk-"):
        assert kw not in js_text, f"frontend registry.js must not contain credential-like token {kw!r}"
