"""``app.nodes.errors`` — 节点执行错误映射(节点 PR-3 骨架层)。

**承接**:[[40 实施计划/节点系统治理实施计划与PR清单]] PR-3 · M2。

**决策边界**:错误分类**复用**任务专题的 ``TaskErrorCategory`` 语义 · 节点侧只
定义节点执行阶段的错误 kind(input 解析失败 / dependency 解析失败 /
plan 构造失败 / adapter 转派失败 / 未知)· 具体 provider raw 解析归
``app.adapters.provider.classifiers``。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Mapping, Optional


NodeExecutionErrorKind = Literal[
    "input_snapshot_missing",
    "dependency_snapshot_missing",
    "plan_construction_failed",
    "adapter_dispatch_failed",
    "idempotency_conflict",
    "unknown",
]


@dataclass(frozen=True)
class NodeExecutionError:
    """节点执行错误 view · 严禁包含 provider raw / 凭据。"""

    kind: NodeExecutionErrorKind
    message: str
    task_error_category: Optional[str] = None  # 复用 TaskErrorCategory · 由 Provider 层填
    recoverable: bool = False
    context: Mapping[str, str] = field(default_factory=dict)  # 只允许字面量字符串

    def __post_init__(self) -> None:
        # 硬约束:context / message 不允许承载凭据关键词
        forbidden = ("api_key", "authorization", "bearer", "secret", "signature")
        blob = (self.message + " " + " ".join(f"{k}={v}" for k, v in self.context.items())).lower()
        for kw in forbidden:
            if kw in blob:
                raise ValueError(
                    "NodeExecutionError message / context must not contain "
                    f"credential-like keyword {kw!r}"
                )
