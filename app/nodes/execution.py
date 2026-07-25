"""``app.nodes.execution`` — 节点执行协议契约(节点 PR-3 · M2)。

**承接**:[[40 实施计划/节点系统治理实施计划与PR清单]] PR-3。

**契约字段**(与 [[30 治理方案/节点系统治理契约 v1]] 与
[[Provider 适配体系治理方案]] ``ProviderTaskView`` 对齐):

::

    NodeExecutionRequest {
        canvas_id: str,
        node_id: str,
        node_type: str,
        run_kind: str,               # "generate" / "poll" / "cancel" / "resume"
        input_snapshot: Mapping,
        settings_snapshot: Mapping,
        dependency_snapshot: Mapping,
        idempotency_key: str,
        trigger_source: str | None,  # "manual" / "loop" / "recovery"
    }

    NodeRunPlan {                    # 前端构造 · 后端消费(未来 PR-7)
        node_execution_request: NodeExecutionRequest,
        expected_outputs: int,       # 期望输出数(多图场景)
        deadline_ms: int | None,     # 前端软超时
    }

    NodeRunResultRef {               # NodeRun 事实的展示视图(不包含 provider raw)
        run_id: str,
        node_id: str,
        status: str,                 # 复用 TaskStatus
        outputs: Sequence[str],      # asset_ref id 列表
        error: NodeExecutionError | None,
        next_poll_after_ms: int | None,
    }

    NodeExecutionResult {            # 端到端一次返回
        run: NodeRunResultRef,
        capabilities: Sequence[str], # 允许前端做的下一步操作("cancel"/"retry"...)
    }

**硬约束**:
- 契约层不解析 provider raw payload
- 节点 ``pending`` 展示缓存与 NodeRun 事实的映射规则在契约测试里验证
- 契约字段禁止承载凭据 / 签名 URL query
- 复用 ``app.task.contracts.node_run.NodeRun`` · 不定义平行运行事实
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Optional, Sequence

from app.nodes.errors import NodeExecutionError


@dataclass(frozen=True)
class NodeExecutionRequest:
    """节点执行请求 · POST /api/node-runs 的 body 契约草案。"""

    canvas_id: str
    node_id: str
    node_type: str
    run_kind: str
    input_snapshot: Mapping[str, object]
    settings_snapshot: Mapping[str, object]
    dependency_snapshot: Mapping[str, object]
    idempotency_key: str
    trigger_source: Optional[str] = None

    def __post_init__(self) -> None:
        # 幂等键必须存在 · 防止重复扣费(Issue-N09 安全回归清单)
        if not self.idempotency_key:
            raise ValueError("idempotency_key must not be empty")
        _forbid_credential_leak(self.input_snapshot, path="input_snapshot")
        _forbid_credential_leak(self.settings_snapshot, path="settings_snapshot")
        _forbid_credential_leak(self.dependency_snapshot, path="dependency_snapshot")


@dataclass(frozen=True)
class NodeRunPlan:
    """前端构造 · 后端消费的 NodeRun 计划。"""

    node_execution_request: NodeExecutionRequest
    expected_outputs: int = 1
    deadline_ms: Optional[int] = None

    def __post_init__(self) -> None:
        if self.expected_outputs < 1:
            raise ValueError("expected_outputs must be >= 1")


@dataclass(frozen=True)
class NodeRunResultRef:
    """NodeRun 事实的展示视图 · 不包含 provider raw。"""

    run_id: str
    node_id: str
    status: str
    outputs: Sequence[str] = field(default_factory=tuple)
    error: Optional[NodeExecutionError] = None
    next_poll_after_ms: Optional[int] = None


@dataclass(frozen=True)
class NodeExecutionResult:
    """端到端一次返回的 view。"""

    run: NodeRunResultRef
    capabilities: Sequence[str] = field(default_factory=tuple)


# --- helpers -------------------------------------------------------------

_CREDENTIAL_KEYWORDS = (
    "api_key",
    "apikey",
    "access_key",
    "secret_access_key",
    "authorization",
    "bearer ",
    "sk-",
    "?x-amz-signature=",
    "&x-amz-signature=",
    "?signature=",
    "&signature=",
)


def _forbid_credential_leak(payload: Mapping[str, object], *, path: str) -> None:
    """浅扫描 · 检查 key 名与 value 前缀是否含凭据关键词。深层由契约测试兜底。"""
    for k, v in payload.items():
        lk = str(k).lower()
        # 允许 identifier 型字段("provider_id" / "workspace_id" 等)
        if lk in ("api_key", "authorization", "access_key", "secret", "bearer"):
            raise ValueError(
                f"{path}.{k}: credential-like key is forbidden in node execution snapshot"
            )
        if isinstance(v, str):
            lv = v.lower()
            for kw in _CREDENTIAL_KEYWORDS:
                if kw in lv:
                    raise ValueError(
                        f"{path}.{k}: value contains credential-like token {kw!r}; "
                        "signed URL query or raw credentials must not enter node snapshots"
                    )
