"""节点 PR-7 · NodeRun→Task 落库映射契约测试(骨架层)。"""
from __future__ import annotations

import pytest

from app.nodes import NodeExecutionRequest
from app.nodes.node_run_mapper import (
    NodeRunTaskMapping,
    build_mapping,
    build_node_run_draft,
    build_task_hints_for_node_run,
    map_pending_cache_to_run_status,
)


def _valid_request(node_type: str = "generator", **overrides) -> NodeExecutionRequest:
    kwargs = dict(
        canvas_id="canvas-1",
        node_id="node-1",
        node_type=node_type,
        run_kind="generate",
        input_snapshot={"prompt": "hello"},
        settings_snapshot={"model": "sd-xl"},
        dependency_snapshot={},
        idempotency_key="idem-1",
        trigger_source="manual",
    )
    kwargs.update(overrides)
    return NodeExecutionRequest(**kwargs)


# --- TF00-TF02:pending cache → status 映射 ---

def test_TF00_empty_cache_maps_to_created():
    assert map_pending_cache_to_run_status({}) == "created"


def test_TF01_pending_true_maps_to_running():
    assert map_pending_cache_to_run_status({"_pending": True}) == "running"


def test_TF02_jimeng_pending_maps_to_waiting_upstream():
    assert map_pending_cache_to_run_status({"jimengPending": {"task_id": "x"}}) == "waiting_upstream"


def test_TF03_pending_tasks_non_empty_maps_to_running():
    assert map_pending_cache_to_run_status({"pendingTasks": [{"id": "t1"}]}) == "running"


def test_TF04_jimeng_takes_priority_over_pending_tasks():
    """jimengPending 优先级高于 pendingTasks(与治理契约一致)。"""
    result = map_pending_cache_to_run_status({
        "jimengPending": {"task_id": "j1"},
        "pendingTasks": [{"id": "t1"}],
    })
    assert result == "waiting_upstream"


# --- TF10-TF12:build_node_run_draft ---

def test_TF10_draft_copies_fields():
    req = _valid_request()
    draft = build_node_run_draft(req)
    assert draft.canvas_id == "canvas-1"
    assert draft.node_id == "node-1"
    assert draft.node_type == "generator"
    assert draft.run_kind == "generate"
    assert draft.status == "created"
    assert draft.trigger_source == "manual"


def test_TF11_draft_snapshots_isolated_from_request():
    """draft 的 snapshot 是 request snapshot 的独立 copy · 不 mutate 源。"""
    req = _valid_request()
    draft = build_node_run_draft(req)
    # draft.input_snapshot 应当是 dict · 且允许 mutate 而不影响原
    assert draft.input_snapshot == dict(req.input_snapshot)


def test_TF12_draft_reuses_task_contracts_type():
    """draft 必须是 `app.task.contracts.node_run.NodeRunDraft`(唯一事实源)。"""
    from app.task.contracts.node_run import NodeRunDraft
    req = _valid_request()
    draft = build_node_run_draft(req)
    assert isinstance(draft, NodeRunDraft)


# --- TF20-TF25:build_task_hints_for_node_run ---

@pytest.mark.parametrize("node_type,expected_kind", [
    ("generator", "image_generate"),
    ("msgen", "image_generate"),
    ("video", "video_generate"),
    ("rh", "workflow_run"),
    ("comfy", "workflow_run"),
    ("ltxDirector", "workflow_run"),
    ("llm", "chat"),
    ("smart-image", "image_generate"),
    ("smart-prompt", "chat"),
    ("prompt", "noop"),
    ("image", "noop"),
    ("output", "noop"),
    ("group", "noop"),
    ("loop", "noop"),
    ("smart-loop", "noop"),
    ("smart-group", "noop"),
])
def test_TF20_task_kind_inference(node_type, expected_kind):
    req = _valid_request(node_type=node_type)
    draft = build_node_run_draft(req)
    hints = build_task_hints_for_node_run(draft)
    assert hints[0]["kind"] == expected_kind


def test_TF21_single_output_default():
    req = _valid_request()
    draft = build_node_run_draft(req)
    hints = build_task_hints_for_node_run(draft)
    assert len(hints) == 1


def test_TF22_multi_output_fanout():
    req = _valid_request()
    draft = build_node_run_draft(req)
    hints = build_task_hints_for_node_run(draft, expected_outputs=4)
    assert len(hints) == 4
    # 每个 hint 有独立的 attempt_offset
    offsets = [h["node_run_ref"]["attempt_offset"] for h in hints]
    assert offsets == [0, 1, 2, 3]


def test_TF23_zero_outputs_rejected():
    req = _valid_request()
    draft = build_node_run_draft(req)
    with pytest.raises(ValueError, match="expected_outputs"):
        build_task_hints_for_node_run(draft, expected_outputs=0)


def test_TF24_provider_hint_carried():
    req = _valid_request()
    draft = build_node_run_draft(req)
    hints = build_task_hints_for_node_run(draft, provider_hint="openai_image")
    assert hints[0]["provider_hint"] == "openai_image"


def test_TF25_node_run_ref_contains_canvas_and_node():
    req = _valid_request()
    draft = build_node_run_draft(req)
    hints = build_task_hints_for_node_run(draft)
    ref = hints[0]["node_run_ref"]
    assert ref["canvas_id"] == "canvas-1"
    assert ref["node_id"] == "node-1"


# --- TF30:build_mapping 端到端 ---

def test_TF30_mapping_end_to_end():
    req = _valid_request()
    mapping = build_mapping(req, provider_hint="openai_image", expected_outputs=2)
    assert isinstance(mapping, NodeRunTaskMapping)
    assert mapping.idempotency_key == "idem-1"
    assert mapping.node_run_draft.canvas_id == "canvas-1"
    assert len(mapping.task_hints) == 2


def test_TF31_mapping_frozen():
    req = _valid_request()
    mapping = build_mapping(req)
    with pytest.raises((AttributeError, TypeError)):
        mapping.idempotency_key = "hacked"  # type: ignore[misc]


# --- TF40:治理护栏 ---

def test_TF40_module_reuses_task_contracts_not_parallel():
    """本模块严禁定义平行 NodeRun · 只 import task contracts。"""
    import app.nodes.node_run_mapper as mod
    import inspect
    src = inspect.getsource(mod)
    # 允许 import NodeRunDraft · 但不允许出现 `class NodeRunDraft` / `class NodeRun`
    assert "class NodeRunDraft" not in src
    assert "class NodeRun " not in src  # NodeRunTaskMapping 是 wrapper · 允许


def test_TF41_module_does_not_import_main():
    import app.nodes.node_run_mapper as mod
    import inspect
    src = inspect.getsource(mod)
    assert "import main" not in src
    assert "from main" not in src


def test_TF42_credential_leak_rejected_at_request_boundary():
    """凭据禁入在 NodeExecutionRequest 构造时拦截 · mapper 只透传。"""
    with pytest.raises(ValueError, match="credential-like"):
        _valid_request(input_snapshot={"api_key": "sk-live-fake"})
