"""``app.services.files.file_hold`` — FileHold 引用计数抽象(文件 PR-6 骨架)。

**承接**:[[40 实施计划/文件对象与 MinIO 治理实施计划与PR清单]] PR-6。

**定位**:纯 dataclass + 纯函数 · 引用计数增减规则契约层 · **不接 DB 事务**
(生产切换归后续 PR-7 orphan_scan)。

**契约核心**:
- ``FileHold``:frozen dataclass · 描述一次引用(哪个 subject 引用了哪个 file_object)
- ``FileHoldDelta``:引用计数变更 view · +1 / -1 / 0(dedup 命中)
- ``compute_hold_delta(current, new)``:纯函数 · 计算差值
- ``ReferenceCountViolation``:抛出条件 · reference_count 不得为负

**硬约束**:
- 每次 hold acquire 都必须携带 (subject_kind, subject_id) 二元组
- reference_count 减到 0 前必须由 orphan_scan 独立扫描(PR-7 承接)
- 骨架层不接 SQL · 由未来 PR-7 或 PR-12 承接落表

**不做**:
- 不接 SQLAlchemy session
- 不接 audit(归 PR-7)
- 不接 orphan cleanup(归 PR-7)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Literal, Mapping, Optional, Sequence, Tuple


_TRUTHY = frozenset({"1", "true", "yes", "on", "TRUE"})
FILE_HOLD_TRACKING_ENABLED_ENV = "FILE_HOLD_TRACKING_ENABLED"


def is_file_hold_tracking_enabled() -> bool:
    """``FILE_HOLD_TRACKING_ENABLED`` 是否已开启(默认 false · 生产切换归 PR-7)。"""
    return os.environ.get(FILE_HOLD_TRACKING_ENABLED_ENV, "").strip() in _TRUTHY


SubjectKind = Literal[
    "canvas_node",
    "task_artifact",
    "history_entry",
    "asset_library_item",
    "workflow_import",
]

ALLOWED_SUBJECT_KINDS: Tuple[SubjectKind, ...] = (
    "canvas_node",
    "task_artifact",
    "history_entry",
    "asset_library_item",
    "workflow_import",
)


class ReferenceCountViolation(ValueError):
    """引用计数越界(< 0 或试图 release 未 acquire 的 hold)。"""


@dataclass(frozen=True)
class FileHold:
    """引用记录:哪个 subject 引用了哪个 file_object。"""

    file_object_id: str
    subject_kind: SubjectKind
    subject_id: str
    # additive:后续 PR 可以扩展 acquired_at / released_at / actor_kind 等
    role: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.file_object_id:
            raise ValueError("file_object_id must not be empty")
        if not self.subject_id:
            raise ValueError("subject_id must not be empty")
        if self.subject_kind not in ALLOWED_SUBJECT_KINDS:
            raise ValueError(
                f"subject_kind={self.subject_kind!r} not in {ALLOWED_SUBJECT_KINDS}"
            )


@dataclass(frozen=True)
class FileHoldDelta:
    """一次 hold 操作对 file_objects.reference_count 的净变化。"""

    file_object_id: str
    delta: int  # +1 acquire · -1 release · 0 dedup
    reason: str

    def __post_init__(self) -> None:
        if self.delta not in (-1, 0, 1):
            raise ValueError(f"delta={self.delta!r} must be one of {{-1, 0, 1}}")


def compute_hold_delta(
    current_holds: Sequence[FileHold],
    new_hold: FileHold,
    *,
    operation: Literal["acquire", "release"] = "acquire",
) -> FileHoldDelta:
    """给定 subject 当前持有的 hold 集合 · 计算新增/释放操作的净变化。

    Rules:
    - acquire:如果 (subject_kind, subject_id) 已经引用该 file_object · delta=0(dedup)
    - acquire:如果未引用 · delta=+1
    - release:如果未引用 · 抛 ReferenceCountViolation(严格模式)
    - release:如果存在引用 · delta=-1
    """
    match = any(
        h.file_object_id == new_hold.file_object_id
        and h.subject_kind == new_hold.subject_kind
        and h.subject_id == new_hold.subject_id
        for h in current_holds
    )
    if operation == "acquire":
        if match:
            return FileHoldDelta(
                file_object_id=new_hold.file_object_id,
                delta=0,
                reason="dedup: hold already exists",
            )
        return FileHoldDelta(
            file_object_id=new_hold.file_object_id,
            delta=1,
            reason="acquire: new hold recorded",
        )
    # release
    if not match:
        raise ReferenceCountViolation(
            f"cannot release: no existing hold for "
            f"file_object={new_hold.file_object_id!r} "
            f"subject=({new_hold.subject_kind}, {new_hold.subject_id})"
        )
    return FileHoldDelta(
        file_object_id=new_hold.file_object_id,
        delta=-1,
        reason="release: hold removed",
    )


def clamp_reference_count(current: int, delta: int) -> int:
    """安全应用 delta · < 0 时抛 ReferenceCountViolation。"""
    new_count = current + delta
    if new_count < 0:
        raise ReferenceCountViolation(
            f"reference_count would become negative "
            f"(current={current}, delta={delta})"
        )
    return new_count
