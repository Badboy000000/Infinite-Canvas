"""``app.nodes`` — 节点系统治理骨架包(Wave 3-N.9 Batch 4 · 五合一)。

**定位**:节点系统治理契约层 · 与 `app.task.contracts` 平行 · 不定义 NodeRun(唯一
事实源为 ``app.task.contracts.node_run.NodeRun``)。本包只承担:

- ``config_schema``:节点 config schema 字段分类 + UI schema 契约(PR-1)
- ``registry``:NodeTypeRegistry 后端等价元数据契约(PR-2)
- ``execution``:节点执行协议 NodeExecutionRequest / NodeRunPlan / NodeRunResult(PR-3)
- ``errors``:NodeExecutionError 错误映射(PR-3 · 复用 TaskErrorCategory)
- ``ui_binding``:节点渲染 registry 5-slot 契约与 fallback 语义(PR-8)

**硬约束**(与 [[40 实施计划/节点系统治理实施计划与PR清单]] 一致):
1. 不接入 FastAPI 路由 · 不改 ``main.py`` · 不改 ``CanvasSaveRequest``
2. 不定义平行 NodeRun / 平行状态机 · 复用任务专题
3. Provider 差异走 ``app.adapters.provider`` · 节点层不写 ``if provider == xxx``
4. 节点字段禁止承载凭据 / 签名 URL query / provider raw payload
5. 骨架期契约文档 · 未来 PR 承接实际迁移(M3 分批)

详见 [[30 治理方案/节点系统治理契约 v1]] 与
[[40 实施计划/节点系统治理实施计划与PR清单]]。
"""
from __future__ import annotations

# 显式 re-export · 保持 flat 引用面。
from app.nodes.config_schema import (  # noqa: F401
    CONFIG_FIELD_CATEGORIES,
    ConfigFieldCategory,
    NodeConfigSchema,
    NodeConfigField,
)
from app.nodes.errors import (  # noqa: F401
    NodeExecutionError,
    NodeExecutionErrorKind,
)
from app.nodes.execution import (  # noqa: F401
    NodeExecutionRequest,
    NodeExecutionResult,
    NodeRunPlan,
    NodeRunResultRef,
)
from app.nodes.registry import (  # noqa: F401
    KNOWN_NODE_TYPES,
    LEGACY_NODE_ALIASES,
    NodeTypeDescriptor,
    resolve_legacy_alias,
    list_node_types,
    get_node_type,
)
from app.nodes.ui_binding import (  # noqa: F401
    NODE_UI_SLOTS,
    NodeUiBinding,
    NodeUiSlot,
)

__all__ = [
    # config_schema (PR-1)
    "CONFIG_FIELD_CATEGORIES",
    "ConfigFieldCategory",
    "NodeConfigSchema",
    "NodeConfigField",
    # errors (PR-3)
    "NodeExecutionError",
    "NodeExecutionErrorKind",
    # execution (PR-3)
    "NodeExecutionRequest",
    "NodeExecutionResult",
    "NodeRunPlan",
    "NodeRunResultRef",
    # registry (PR-2)
    "KNOWN_NODE_TYPES",
    "LEGACY_NODE_ALIASES",
    "NodeTypeDescriptor",
    "resolve_legacy_alias",
    "list_node_types",
    "get_node_type",
    # ui_binding (PR-8)
    "NODE_UI_SLOTS",
    "NodeUiBinding",
    "NodeUiSlot",
]
