"""节点 PR-4/5/6 · 前端 factories.js seam crossref 契约测试。

后端 `app.nodes.node_shapes` 定义了 shape 契约 · 前端
`static/js/shared/nodes/factories.js` 是构造工厂 · 两者的 type 集合必须一致
(未来 PR 真承接时 canvas.js 通过 factory 走 shape)。

用文本 grep 校验 · 不引入 Node runtime 依赖(seam 期零构建零依赖硬约束)。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.nodes.node_shapes import ALL_SHAPES
from app.nodes.registry import KNOWN_NODE_TYPES

REPO_ROOT = Path(__file__).resolve().parents[2]
JS_FACTORIES = REPO_ROOT / "static" / "js" / "shared" / "nodes" / "factories.js"


def _load_js() -> str:
    assert JS_FACTORIES.exists(), f"missing seam: {JS_FACTORIES}"
    return JS_FACTORIES.read_text(encoding="utf-8")


def _extract_factory_types(js_text: str) -> list[str]:
    """抓 `const FACTORY_BY_TYPE = Object.freeze({ ... });` 中的 key 列表。"""
    m = re.search(
        r"const\s+FACTORY_BY_TYPE\s*=\s*Object\.freeze\(\{([^}]*)\}\)",
        js_text,
        re.DOTALL,
    )
    assert m, "FACTORY_BY_TYPE not found"
    body = m.group(1)
    # key 可能是 `prompt:` (bareword) 或 `'smart-image':` (quoted)
    keys: list[str] = []
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        # bareword: identifier followed by :
        m1 = re.match(r"([a-zA-Z_][a-zA-Z0-9_]*)\s*:", line)
        m2 = re.match(r"'([^']+)'\s*:", line)
        if m1:
            keys.append(m1.group(1))
        elif m2:
            keys.append(m2.group(1))
    return keys


def test_TE60_frontend_seam_exists():
    assert JS_FACTORIES.exists()


def test_TE61_factory_types_cover_all_shapes():
    """factories.js 声明的 type 集合必须至少覆盖所有 shape。"""
    js_text = _load_js()
    js_types = set(_extract_factory_types(js_text))
    shape_types = set(ALL_SHAPES.keys())
    missing_in_js = shape_types - js_types
    assert not missing_in_js, (
        f"factories.js missing types present in node_shapes: {sorted(missing_in_js)}"
    )


def test_TE62_factory_types_subset_of_known_types():
    """factories.js 声明的 type 不允许出现在 KNOWN_NODE_TYPES 之外(除 legacy alias)。"""
    js_text = _load_js()
    js_types = set(_extract_factory_types(js_text))
    unknown = js_types - set(KNOWN_NODE_TYPES)
    assert not unknown, f"factories.js declares unknown types: {sorted(unknown)}"


def test_TE63_no_side_effects_in_factories():
    js_text = _load_js()
    forbidden = ["fetch(", "XMLHttpRequest", "document.write", "localStorage"]
    for token in forbidden:
        assert token not in js_text, (
            f"factories.js unexpectedly contains {token!r}; seam must be side-effect-free"
        )


def test_TE64_no_credentials_in_factories():
    js_text = _load_js().lower()
    for kw in ("api_key", "authorization", "bearer ", "secret", "sk-"):
        assert kw not in js_text, f"factories.js must not contain credential-like token {kw!r}"


def test_TE65_factories_do_not_generate_id():
    """factory 必须要求调用方传入 id · 不自己生成(uid 归 canvas.js)。"""
    js_text = _load_js()
    # 断言不含 crypto.randomUUID / Math.random 之类的 id 生成器
    assert "randomUUID" not in js_text
    # createByType helper 存在 · 便于未来 canvas.js 委托
    assert "createByType" in js_text
