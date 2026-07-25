"""``app.nodes.node_run_mapper`` — 节点执行 → NodeRun/Task 落库映射(节点 PR-7 骨架层)。

**承接**:[[40 实施计划/节点系统治理实施计划与PR清单]] PR-7 · M2/M3 桥接。

**定位**:纯函数库 · 把节点侧 ``NodeExecutionRequest`` 映射到任务专题的
``NodeRunDraft`` + ``TaskDraft``(未来 PR 承接实端点接入)· **不接** TaskStore ·
**不接** SQL。仅提供**契约层映射**。

**契约核心**:
- ``build_node_run_draft(request)``:``NodeExecutionRequest`` → ``NodeRunDraft``
- ``build_task_draft_for_node_run(node_run, provider_hint)``:``NodeRunDraft`` → 1..n ``TaskDraft``
- ``map_pending_cache_to_run_status(pending_cache)``:节点 pending 展示缓存 → NodeRun 状态
- ``NodeRunTaskMapping``:frozen dataclass · 一次映射结果

**硬约束**:
- 复用 ``app.task.contracts.node_run.NodeRunDraft``(唯一事实源)
- 严禁引入平行 NodeRun / Task 类型
- 严禁承载凭据 / provider raw payload
- pending 缓存(_pending / pendingTasks / jimengPending)只映射为 NodeRun 状态 · 不入 snapshot

**不做**:
- 不接 TaskStore.submit_task
- 不接 POST /api/node-runs
- 不改现有 CANVAS_TASKS 影子登记
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Mapping, Optional, Sequence, Tuple

from app.nodes.execution import NodeExecutionRequest
from app.task.contracts.node_run import NodeRunDraft
from app.task.contracts.task import TaskStatus


# ---------------------------------------------------------------------------
# NodeRunTaskMapping
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NodeRunTaskMapping:
    """一次映射的结果视图。"""

    node_run_draft: NodeRunDraft
    task_hints: Tuple[Mapping[str, Any], ...]  # 待未来 PR 转成 TaskDraft
    idempotency_key: str


# ---------------------------------------------------------------------------
# pending cache → NodeRun status 映射
# ---------------------------------------------------------------------------

# 治理契约 v1 §"Legacy Write-Preserve" · 三种展示缓存字段
_PENDING_CACHE_FIELDS: Tuple[str, ...] = ("_pending", "pendingTasks", "jimengPending")


def map_pending_cache_to_run_status(
    pending_cache: Mapping[str, Any],
) -> TaskStatus:
    """把节点 pending 展示缓存映射为 NodeRun status。

    映射规则(治理方案 §"NodeRun 与 pending 展示缓存映射"):
    - `_pending == True` 或 `pendingTasks[]` 非空 → "running"
    - `jimengPending != None` → "waiting_upstream"
    - 全部空 → "created"

    严格按只读语义 · 不 mutate pending_cache。
    """
    jimeng_pending = pending_cache.get("jimengPending")
    if jimeng_pending is not None:
        return "waiting_upstream"

    pending_tasks = pending_cache.get("pendingTasks") or []
    if pending_tasks:
        return "running"

    if pending_cache.get("_pending"):
        return "running"

    return "created"


# ---------------------------------------------------------------------------
# NodeExecutionRequest → NodeRunDraft
# ---------------------------------------------------------------------------


def build_node_run_draft(
    request: NodeExecutionRequest,
    *,
    now_utc: Optional[datetime] = None,
) -> NodeRunDraft:
    """把节点执行请求映射为 NodeRunDraft(骨架层 · 纯函数)。

    - 字段名严格对齐 `app.task.contracts.node_run.NodeRunDraft`
    - `input_snapshot / settings_snapshot / dependency_snapshot` 直接透传
      (`NodeExecutionRequest` 构造时已通过 `_forbid_credential_leak` 拦截凭据)
    - `attempt` 默认 0 · 由 TaskService 侧递增
    """
    # NodeRunDraft.created_at 是必需字段 · 由调用方 / TaskService 侧填 · 骨架期允许注入
    # (骨架层不真实提交)· 保持契约完整
    return NodeRunDraft(
        canvas_id=request.canvas_id,
        node_id=request.node_id,
        node_type=request.node_type,
        run_kind=request.run_kind,
        status="created",
        trigger_source=request.trigger_source,
        input_snapshot=dict(request.input_snapshot),
        settings_snapshot=dict(request.settings_snapshot),
        dependency_snapshot=dict(request.dependency_snapshot),
    )


# ---------------------------------------------------------------------------
# NodeRunDraft → TaskDraft hints
# ---------------------------------------------------------------------------


def build_task_hints_for_node_run(
    node_run: NodeRunDraft,
    *,
    provider_hint: Optional[str] = None,
    expected_outputs: int = 1,
) -> Tuple[Mapping[str, Any], ...]:
    """给定 NodeRunDraft · 返回 1..n 个 TaskDraft 提示 dict(骨架层)。

    Task 边界规则(治理方案 §"任务模型 · Task 拆分"):
    - image / video generation:1 NodeRun → 1 Task(简单场景)· expected_outputs 决定 fan-out
    - workflow_run:1 NodeRun → 1 Task(workflow 由 provider 内部处理多 artifact)
    - chat/llm:1 NodeRun → 1 Task
    - 复合 smart-image(pending Tasks 多)· 由未来 PR-7 真实端点承接

    骨架层只输出 hint · 未来 PR 承接时把 hint 转成真 TaskDraft。
    """
    if expected_outputs < 1:
        raise ValueError("expected_outputs must be >= 1")
    kind = _infer_task_kind(node_run.node_type)
    hints: list[Mapping[str, Any]] = []
    for i in range(expected_outputs):
        hints.append({
            "kind": kind,
            "provider_hint": provider_hint or "",
            "node_run_ref": {
                "canvas_id": node_run.canvas_id,
                "node_id": node_run.node_id,
                "attempt_offset": i,
            },
            "run_kind": node_run.run_kind,
        })
    return tuple(hints)


def _infer_task_kind(node_type: str) -> str:
    """节点类型 → task kind(与任务专题 Task.kind 字段对齐)。"""
    if node_type in ("generator", "msgen"):
        return "image_generate"
    if node_type == "video":
        return "video_generate"
    if node_type in ("rh", "comfy", "ltxDirector"):
        return "workflow_run"
    if node_type == "llm":
        return "chat"
    if node_type == "smart-image":
        return "image_generate"  # smart-image 默认走图像 generation(facet 决定实际)
    if node_type == "smart-prompt":
        return "chat"
    # smart-loop / smart-group / group / prompt / image / output 不直接产生 task
    return "noop"


# ---------------------------------------------------------------------------
# 端到端 · 组装 NodeRunTaskMapping
# ---------------------------------------------------------------------------


def build_mapping(
    request: NodeExecutionRequest,
    *,
    provider_hint: Optional[str] = None,
    expected_outputs: int = 1,
) -> NodeRunTaskMapping:
    draft = build_node_run_draft(request)
    hints = build_task_hints_for_node_run(
        draft,
        provider_hint=provider_hint,
        expected_outputs=expected_outputs,
    )
    return NodeRunTaskMapping(
        node_run_draft=draft,
        task_hints=hints,
        idempotency_key=request.idempotency_key,
    )
