"""``app.nodes.ui_binding`` — 前端渲染 registry 契约(节点 PR-8)。

**承接**:[[40 实施计划/节点系统治理实施计划与PR清单]] PR-8 · 与前端组件化专题联席。

**决策边界**:本模块仅定义 renderer registry 的**契约字段**;实际 renderer
实现属于前端组件化专题(seam 期零构建零依赖;move 期后可考虑 Vue 承接)。

**5-slot 契约**:节点 UI 分为 ``header / body / ports / toolbar / badges`` 五个 slot
· registry 只声明 renderer 引用 · 缺失时 fallback 到旧 ``renderNode()`` /
``render()`` 路径 · 严禁强制替换。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Mapping, Optional, Tuple


NodeUiSlot = Literal["header", "body", "ports", "toolbar", "badges"]

NODE_UI_SLOTS: Tuple[NodeUiSlot, ...] = (
    "header",
    "body",
    "ports",
    "toolbar",
    "badges",
)


@dataclass(frozen=True)
class NodeUiBinding:
    """节点 UI slot renderer 引用绑定。

    renderer 引用是字符串标识符(例如 ``classic/generator/body``),前端 registry
    根据引用查找具体 renderer;缺失即 fallback。renderer 引用只是标识符不承载
    凭据也不承载 URL(Issue-N09 安全回归清单)。
    """

    node_type: str
    # 每 slot 的 renderer 引用 · 缺失 = fallback 旧路径
    renderers: Mapping[NodeUiSlot, str] = field(default_factory=dict)
    # slot 的 fallback 语义显式化(True 允许 fallback 旧路径 · False 硬绑 registry)
    allow_fallback: bool = True

    def __post_init__(self) -> None:
        # 校验:slot key 必须在 NODE_UI_SLOTS 白名单内
        for slot in self.renderers.keys():
            if slot not in NODE_UI_SLOTS:
                raise ValueError(
                    f"NodeUiBinding.renderers has unknown slot={slot!r}; "
                    f"allowed slots = {NODE_UI_SLOTS}"
                )
        # 硬约束:renderer 引用只允许标识符字符 · 拒绝 URL / 签名 query
        for slot, ref in self.renderers.items():
            if "://" in ref or "?" in ref or "&" in ref:
                raise ValueError(
                    f"NodeUiBinding.renderers[{slot!r}] must be an identifier, "
                    f"not a URL or query string; got {ref!r}"
                )

    def renderer_for(self, slot: NodeUiSlot) -> Optional[str]:
        return self.renderers.get(slot)
