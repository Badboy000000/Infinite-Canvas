"""节点 PR-3 · 执行协议契约测试(M2 骨架)。

覆盖:
- NodeExecutionRequest 硬约束:idempotency_key 非空 · 凭据禁入
- NodeRunPlan.expected_outputs >= 1
- NodeRunResultRef / NodeExecutionResult 结构
- NodeExecutionError 凭据关键词禁入
- 与 `app.task.contracts.node_run.NodeRun` 复用契约(不定义平行运行事实)
"""
from __future__ import annotations

import pytest

from app.nodes import (
    NodeExecutionError,
    NodeExecutionErrorKind,
    NodeExecutionRequest,
    NodeExecutionResult,
    NodeRunPlan,
    NodeRunResultRef,
)


def _valid_request(**overrides) -> NodeExecutionRequest:
    kwargs = dict(
        canvas_id="canvas-1",
        node_id="node-1",
        node_type="generator",
        run_kind="generate",
        input_snapshot={"prompt": "hello"},
        settings_snapshot={"model": "sd-xl", "ratio": "1:1"},
        dependency_snapshot={"upstream": ["node-0"]},
        idempotency_key="abc-123",
        trigger_source="manual",
    )
    kwargs.update(overrides)
    return NodeExecutionRequest(**kwargs)


# --- T740-T744:NodeExecutionRequest 硬约束 --------------------------------

def test_T740_empty_idempotency_key_rejected():
    with pytest.raises(ValueError, match="idempotency_key"):
        _valid_request(idempotency_key="")


@pytest.mark.parametrize("bad_key", [
    "api_key",
    "authorization",
    "access_key",
    "secret",
    "bearer",
])
def test_T741_credential_like_keys_rejected_in_snapshot(bad_key):
    """input/settings/dependency snapshot 不允许承载凭据键。"""
    with pytest.raises(ValueError, match="credential-like key"):
        _valid_request(input_snapshot={bad_key: "sk-live-fake"})


@pytest.mark.parametrize("bad_value", [
    "sk-INJECT-live-abc",
    "Bearer XXX-token",
    "https://example.com/img?X-Amz-Signature=deadbeef",
    "https://example.com/x?signature=abc",
])
def test_T742_credential_like_values_rejected(bad_value):
    """签名 URL query / provider raw token 不许进入 snapshot。"""
    with pytest.raises(ValueError, match="credential-like"):
        _valid_request(settings_snapshot={"model": bad_value})


def test_T743_identifier_style_fields_allowed():
    """`provider_id` / `workspace_id` 等标识符字段允许通过。"""
    req = _valid_request(
        settings_snapshot={
            "provider_id": "prov_openai_01",
            "workspace_id": "ws-42",
            "model": "gpt-4o",
        },
    )
    assert req.settings_snapshot["provider_id"] == "prov_openai_01"


def test_T744_valid_request_roundtrip():
    req = _valid_request()
    assert req.canvas_id == "canvas-1"
    assert req.node_type == "generator"
    assert req.trigger_source == "manual"


# --- T745-T747:NodeRunPlan --------------------------------------------

def test_T745_node_run_plan_defaults():
    plan = NodeRunPlan(node_execution_request=_valid_request())
    assert plan.expected_outputs == 1
    assert plan.deadline_ms is None


def test_T746_node_run_plan_expected_outputs_positive():
    with pytest.raises(ValueError, match="expected_outputs"):
        NodeRunPlan(node_execution_request=_valid_request(), expected_outputs=0)


def test_T747_node_run_plan_multi_output_supported():
    plan = NodeRunPlan(
        node_execution_request=_valid_request(),
        expected_outputs=4,
        deadline_ms=30_000,
    )
    assert plan.expected_outputs == 4


# --- T748-T749:NodeRunResultRef / NodeExecutionResult -------------------

def test_T748_run_result_ref_has_defaults():
    ref = NodeRunResultRef(run_id="run-1", node_id="node-1", status="running")
    assert ref.outputs == ()
    assert ref.error is None
    assert ref.next_poll_after_ms is None


def test_T749_execution_result_wraps_run_ref():
    ref = NodeRunResultRef(run_id="r", node_id="n", status="succeeded")
    result = NodeExecutionResult(run=ref, capabilities=("cancel", "retry"))
    assert result.run.run_id == "r"
    assert "cancel" in result.capabilities


# --- T750:NodeExecutionError 凭据禁入 ---------------------------------

@pytest.mark.parametrize("kind", [
    "input_snapshot_missing",
    "dependency_snapshot_missing",
    "plan_construction_failed",
    "adapter_dispatch_failed",
    "idempotency_conflict",
    "unknown",
])
def test_T750_execution_error_kind_whitelist(kind):
    err = NodeExecutionError(kind=kind, message="failed")  # type: ignore[arg-type]
    assert err.kind == kind


def test_T751_execution_error_rejects_credential_in_message():
    with pytest.raises(ValueError, match="credential-like"):
        NodeExecutionError(kind="unknown", message="failed with api_key sk-live")


def test_T752_execution_error_rejects_credential_in_context():
    with pytest.raises(ValueError, match="credential-like"):
        NodeExecutionError(
            kind="adapter_dispatch_failed",
            message="upstream error",
            context={"header": "authorization: Bearer sk-x"},
        )


# --- T753:与 app.task.contracts.node_run.NodeRun 复用契约 ---------------

def test_T753_reuses_task_contracts_node_run():
    """节点专题不重定义 NodeRun · 唯一事实源为 `app.task.contracts.node_run`。"""
    from app.task.contracts.node_run import NodeRun as TaskNodeRun

    # NodeRunResultRef 是 view · 与 NodeRun snapshot 不重叠;确认没有平行定义。
    import app.nodes as nodes_pkg
    exported = getattr(nodes_pkg, "__all__", ())
    assert "NodeRun" not in exported, (
        "app.nodes must not re-export a parallel NodeRun; task专题拥有唯一事实源"
    )
    # 显式引用一次 · 防止 dead-import
    _ = TaskNodeRun


# --- T754:治理护栏 · 骨架层不 import main -----------------------------

def test_T754_execution_module_does_not_import_main():
    import app.nodes.execution as exec_mod
    import inspect
    src = inspect.getsource(exec_mod)
    assert "import main" not in src and "from main" not in src
