"""``app.nodes.node_shapes`` — 节点 shape 契约冻结(节点 PR-4/5/6 骨架层)。

**承接**:[[40 实施计划/节点系统治理实施计划与PR清单]] PR-4 / PR-5 / PR-6 骨架侧。

**定位**:纯数据契约 · 描述 classic 12 类 + smart 4 类节点的**最小字段清单** + **legacy
write-preserve 清单**。**不接** canvas.js · 不改运行时。当未来 PR 真承接迁移到
registry factory 时,可用本模块的 shape 定义做字节等价断言。

**硬约束**(与 [[30 治理方案/节点系统治理契约 v1]] §"Legacy Write-Preserve 清单" 逐字对齐):
- 每个 type 的 required_fields 是**必须**由 factory 产出的字段
- legacy_fields 是**必须** read-tolerant + write-preserve 的字段(缺失时不填 · 存在时透传)
- 字段类型只是描述层 · 不做运行时校验

**不做**:
- 不导入 canvas.js
- 不接 registry factory
- 不改运行时 shape
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Mapping, Tuple


@dataclass(frozen=True)
class NodeShape:
    """一个 node type 的 shape 契约。"""

    type: str
    required_fields: Tuple[str, ...]        # factory 必须输出
    legacy_fields: Tuple[str, ...] = ()     # 读侧兼容 + 写侧透传
    facets: Tuple[str, ...] = ()            # smart-image 复合角色
    category: Literal["classic", "smart"] = "classic"

    def __post_init__(self) -> None:
        if not self.type:
            raise ValueError("NodeShape.type must not be empty")
        # 每个字段名不允许承载凭据关键词
        _forbidden = ("api_key", "authorization", "bearer", "secret", "signature")
        for f in self.required_fields + self.legacy_fields:
            lower = f.lower()
            for kw in _forbidden:
                if lower == kw or lower.endswith("_" + kw) or lower.startswith(kw + "_"):
                    raise ValueError(
                        f"NodeShape({self.type}): field {f!r} contains credential-like keyword {kw!r}"
                    )


# ---------------------------------------------------------------------------
# classic 12 类
# ---------------------------------------------------------------------------

_COMMON_REQUIRED = ("id", "type", "x", "y")


CLASSIC_SHAPES: Mapping[str, NodeShape] = {
    "prompt": NodeShape(
        type="prompt", category="classic",
        required_fields=_COMMON_REQUIRED + ("text",),
    ),
    "llm": NodeShape(
        type="llm", category="classic",
        required_fields=_COMMON_REQUIRED + (
            "llmProvider", "model", "mode", "systemPrompt", "chatInput",
            "messages", "outputText", "llmInputHeight", "llmOutputHeight", "running",
        ),
        legacy_fields=(),
    ),
    "image": NodeShape(
        type="image", category="classic",
        required_fields=_COMMON_REQUIRED + ("url", "name"),
        legacy_fields=("mediaKind", "natural_w", "natural_h"),
    ),
    "output": NodeShape(
        type="output", category="classic",
        required_fields=_COMMON_REQUIRED + ("images",),
        legacy_fields=("_pending",),
    ),
    "generator": NodeShape(
        type="generator", category="classic",
        required_fields=_COMMON_REQUIRED + (
            "apiProvider", "model", "ratio", "resolution",
            "customRatio", "customSize", "customRatioWidth", "customRatioHeight",
            "customWidth", "customHeight", "inputs",
        ),
        legacy_fields=("count", "fitImage"),
    ),
    "msgen": NodeShape(
        type="msgen", category="classic",
        required_fields=_COMMON_REQUIRED + (
            "msgenModel", "msWidth", "msHeight", "msCustomModel",
            "msRatio", "msResolution", "msCustomRatio", "msCustomSize",
            "msCustomRatioWidth", "msCustomRatioHeight", "msCustomWidth", "msCustomHeight",
            "count", "fitImage", "inputs", "running",
        ),
    ),
    "video": NodeShape(
        type="video", category="classic",
        required_fields=_COMMON_REQUIRED + (
            "apiProvider", "model", "duration", "aspectRatio", "resolution",
            "enhancePrompt", "enableUpsample", "watermark", "cameraFixed",
            "generateAudio", "useFrameRoles", "multimodal", "tempShLinks",
            "inputs", "running",
        ),
    ),
    "rh": NodeShape(
        type="rh", category="classic",
        required_fields=_COMMON_REQUIRED + (
            "w", "h", "rhMode", "rhPayment", "webappId", "workflowId",
            "instanceType", "rhAppInfo", "rhWorkflowInfo", "rhParams",
            "inputs", "running",
        ),
    ),
    "ltxDirector": NodeShape(
        type="ltxDirector", category="classic",
        required_fields=_COMMON_REQUIRED + (
            "w", "h", "globalPrompt", "durationFrames", "durationSeconds",
            "frameRate", "customWidth", "customHeight", "displayMode",
            "useCustomAudio", "imgCompression", "epsilon", "divisibleBy",
            "noiseSeed", "ltxTimelineData", "ltxLocalPrompts", "ltxSegmentLengths",
            "ltxGuideStrength", "ltxSegments", "ltxSelectedSegId", "inputs", "running",
        ),
    ),
    "comfy": NodeShape(
        type="comfy", category="classic",
        required_fields=_COMMON_REQUIRED + ("inputs",),
        legacy_fields=("workflowId", "workflowJson", "params"),
    ),
    "loop": NodeShape(
        type="loop", category="classic",
        required_fields=_COMMON_REQUIRED + (
            "count", "mode", "showPrompt", "imageInput", "videoInput",
            "loopStart", "imageBatchSize", "videoBatchSize",
            "variablePrompt", "fixedPrompt",
        ),
    ),
    "group": NodeShape(
        type="group", category="classic",
        required_fields=_COMMON_REQUIRED + ("w", "h", "items"),
    ),
}


# ---------------------------------------------------------------------------
# smart 4 类
# ---------------------------------------------------------------------------

SMART_SHAPES: Mapping[str, NodeShape] = {
    "smart-image": NodeShape(
        type="smart-image", category="smart",
        required_fields=_COMMON_REQUIRED + (
            "images", "scale", "runSettings",
            "pendingTasks", "jimengPending", "generatedOutputs",
            "manualInputRefs", "runInputRefs", "asset_uris",
        ),
        legacy_fields=("promptDraft", "promptDraftMeta", "inputNodeIds"),
        facets=("media-source", "generation-target", "media-output", "run-state-host"),
    ),
    "smart-prompt": NodeShape(
        type="smart-prompt", category="smart",
        required_fields=_COMMON_REQUIRED + ("text", "systemPrompt", "llmProvider", "model"),
    ),
    "smart-loop": NodeShape(
        type="smart-loop", category="smart",
        required_fields=_COMMON_REQUIRED + ("count", "mode", "showPrompt", "imageInput"),
    ),
    "smart-group": NodeShape(
        type="smart-group", category="smart",
        required_fields=_COMMON_REQUIRED + ("w", "h", "items"),
    ),
}


ALL_SHAPES: Mapping[str, NodeShape] = {**CLASSIC_SHAPES, **SMART_SHAPES}


def get_shape(node_type: str) -> NodeShape | None:
    """精确匹配 · 未命中返回 None(不做 alias 解析 · 由 registry 层负责)。"""
    return ALL_SHAPES.get(node_type)


def list_shapes() -> Tuple[NodeShape, ...]:
    """按 KNOWN_NODE_TYPES 冻结顺序返回。"""
    from app.nodes.registry import KNOWN_NODE_TYPES
    return tuple(ALL_SHAPES[t] for t in KNOWN_NODE_TYPES if t in ALL_SHAPES)


def validate_shape_snapshot(
    node: Mapping[str, object],
    *,
    strict: bool = False,
) -> Tuple[bool, Tuple[str, ...]]:
    """检查一个 node dict 是否满足其类型的 shape 契约。

    Args:
        node: 节点 dict(至少含 type / id / x / y)
        strict: True 时 legacy_fields 缺失也报错(默认 False · 允许 legacy 缺失)

    Returns:
        (ok, missing_fields)
    """
    node_type = str(node.get("type", ""))
    shape = get_shape(node_type)
    if shape is None:
        return (False, (f"unknown node type={node_type!r}",))
    missing: list[str] = []
    for field_name in shape.required_fields:
        if field_name not in node:
            missing.append(field_name)
    if strict:
        for field_name in shape.legacy_fields:
            if field_name not in node:
                missing.append(f"legacy:{field_name}")
    return (len(missing) == 0, tuple(missing))
