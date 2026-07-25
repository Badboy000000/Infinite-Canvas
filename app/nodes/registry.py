"""``app.nodes.registry`` — NodeTypeRegistry 后端等价元数据(节点 PR-2)。

**承接**:[[40 实施计划/节点系统治理实施计划与PR清单]] PR-2 · M1。

**决策边界(AR-N01)**:治理期 registry 落在前端 seam 层
(``static/js/shared/nodes/registry.js``);本模块仅提供**后端等价元数据**用于
契约测试与跨专题引用 · 后端**不做**校验也不接入路由。

**硬约束**:
- 类型集合等价于当前工具栏 + 右键菜单 + 运行分派并集(见治理契约 v1)
- ``smart-container`` 作为 legacy_alias 解析到 ``smart-image``
- 仅只读:``list_node_types()`` / ``get_node_type(t)`` / ``resolve_legacy_alias(a)``
- 不引入创建 / 渲染 / 保存 / 运行的行为
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Optional, Tuple


# ------------------------------------------------------------------
# 节点类型清单 · 与 [[30 治理方案/节点系统治理契约 v1]] §"NodeType v1" 逐字对齐。
# ------------------------------------------------------------------

CLASSIC_NODE_TYPES: Tuple[str, ...] = (
    "image",
    "prompt",
    "loop",
    "group",
    "llm",
    "generator",
    "msgen",
    "video",
    "rh",
    "ltxDirector",
    "output",
    "comfy",
)

SMART_NODE_TYPES: Tuple[str, ...] = (
    "smart-image",
    "smart-prompt",
    "smart-loop",
    "smart-group",
)

KNOWN_NODE_TYPES: Tuple[str, ...] = CLASSIC_NODE_TYPES + SMART_NODE_TYPES

# 长期 legacy alias · 见治理契约 v1 §"NodeType v1"。
LEGACY_NODE_ALIASES: Mapping[str, str] = {
    "smart-container": "smart-image",
}


@dataclass(frozen=True)
class NodeTypeDescriptor:
    """节点类型元信息描述(与前端 registry.js 保持字段名一致)。"""

    type: str
    display_name: str
    category: str  # classic / smart
    schema_version: int = 1
    capabilities: Tuple[str, ...] = field(default_factory=tuple)
    ports: Tuple[str, ...] = field(default_factory=tuple)
    legacy_aliases: Tuple[str, ...] = field(default_factory=tuple)
    facets: Tuple[str, ...] = field(default_factory=tuple)
    # renderer_ref / executor_ref 是字符串标识符 · 具体 renderer / executor 由
    # 前端组件化专题 / 任务专题实现;registry 只承载引用不承载实现。
    renderer_ref: Optional[str] = None
    executor_ref: Optional[str] = None


# --- 默认元数据表 --------------------------------------------------------

_DEFAULT_CAPABILITIES: Mapping[str, Tuple[str, ...]] = {
    "prompt": ("author_text",),
    "llm": ("chat",),
    "image": ("media-source",),
    "output": ("media-output",),
    "generator": ("generate_image",),
    "msgen": ("generate_image",),
    "video": ("generate_video",),
    "rh": ("run_workflow",),
    "ltxDirector": ("run_workflow",),
    "comfy": ("run_workflow",),
    "loop": ("orchestrate",),
    "group": ("group",),
    # smart · smart-image 复合 facet(见治理契约 v1 §"smart-image 治理")
    "smart-image": (
        "media-source",
        "generation-target",
        "media-output",
        "run-state-host",
    ),
    "smart-prompt": ("author_text", "chat"),
    "smart-loop": ("orchestrate",),
    "smart-group": ("group",),
}


def _descriptor_for(t: str) -> NodeTypeDescriptor:
    category = "classic" if t in CLASSIC_NODE_TYPES else "smart"
    aliases = tuple(k for k, v in LEGACY_NODE_ALIASES.items() if v == t)
    facets: Tuple[str, ...] = ()
    if t == "smart-image":
        facets = _DEFAULT_CAPABILITIES[t]
    return NodeTypeDescriptor(
        type=t,
        display_name=t,
        category=category,
        capabilities=_DEFAULT_CAPABILITIES.get(t, ()),
        legacy_aliases=aliases,
        facets=facets,
    )


_TYPE_TABLE: Mapping[str, NodeTypeDescriptor] = {t: _descriptor_for(t) for t in KNOWN_NODE_TYPES}


def list_node_types() -> Tuple[NodeTypeDescriptor, ...]:
    """返回全部节点类型描述符(冻结顺序:classic 后 smart)。"""
    return tuple(_TYPE_TABLE[t] for t in KNOWN_NODE_TYPES)


def get_node_type(type_or_alias: str) -> Optional[NodeTypeDescriptor]:
    """精确匹配 · 未命中先走 alias · 仍未命中返回 ``None``。"""
    if type_or_alias in _TYPE_TABLE:
        return _TYPE_TABLE[type_or_alias]
    resolved = LEGACY_NODE_ALIASES.get(type_or_alias)
    if resolved and resolved in _TYPE_TABLE:
        return _TYPE_TABLE[resolved]
    return None


def resolve_legacy_alias(alias: str) -> Optional[str]:
    """``smart-container -> smart-image``。未命中返回 ``None``(不抛异常)。"""
    return LEGACY_NODE_ALIASES.get(alias)
