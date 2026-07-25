"""``app.services.files.minio_switchover`` — MinIO 灰度切换契约骨架
(文件 PR-12)。

**承接**:[[40 实施计划/文件对象与 MinIO 治理实施计划与PR清单]] PR-12。

**定位**:纯 frozen dataclass + 纯函数 · 描述 STORAGE_BACKEND=minio 灰度
切换过程 · **不接** MinIO client(已在 app/adapters/storage/minio_adapter.py)·
**不改** main.py storage bootstrap。

**骨架契约**:
- ``StorageBackend``:Literal · local / minio / hybrid
- ``MinioSwitchoverPhase``:Literal · shadow / dual_write / cutover / rollback
- ``SwitchoverPolicy``:frozen dataclass · 一次切换的策略描述
- ``build_switchover_plan(from_backend, to_backend, phase)``:纯函数

**硬约束**:
- 严禁在 dual_write 阶段之外触发 MinIO 主写
- rollback 阶段必须能 **不重启** 切回 local(env flag reload)
- 灰度过程不允许静默删除 local 数据

**不做**:
- 不接 MinIO client
- 不做实际 migration
- 不改 main.py 启动流程
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Literal, Mapping, Tuple


StorageBackend = Literal["local", "minio", "hybrid"]
MinioSwitchoverPhase = Literal["shadow", "dual_write", "cutover", "rollback"]

STORAGE_BACKENDS: Tuple[StorageBackend, ...] = ("local", "minio", "hybrid")
SWITCHOVER_PHASES: Tuple[MinioSwitchoverPhase, ...] = (
    "shadow", "dual_write", "cutover", "rollback",
)

_TRUTHY = frozenset({"1", "true", "yes", "on"})
MINIO_SWITCHOVER_ENABLED_ENV = "MINIO_SWITCHOVER_ENABLED"


def is_minio_switchover_enabled() -> bool:
    return os.environ.get(MINIO_SWITCHOVER_ENABLED_ENV, "").strip().lower() in _TRUTHY


@dataclass(frozen=True)
class SwitchoverPolicy:
    """一次 switchover 的策略描述。"""

    from_backend: StorageBackend
    to_backend: StorageBackend
    phase: MinioSwitchoverPhase
    write_targets: Tuple[StorageBackend, ...]  # 主写目标集合
    read_priority: Tuple[StorageBackend, ...]  # 读优先级顺序
    allow_delete_from: Tuple[StorageBackend, ...]  # 允许 delete 的后端集合

    def __post_init__(self) -> None:
        if self.from_backend not in STORAGE_BACKENDS:
            raise ValueError(f"from_backend={self.from_backend!r}")
        if self.to_backend not in STORAGE_BACKENDS:
            raise ValueError(f"to_backend={self.to_backend!r}")
        if self.phase not in SWITCHOVER_PHASES:
            raise ValueError(f"phase={self.phase!r}")
        for w in self.write_targets:
            if w not in STORAGE_BACKENDS:
                raise ValueError(f"invalid write_targets entry {w!r}")


def build_switchover_plan(
    *,
    from_backend: StorageBackend,
    to_backend: StorageBackend,
    phase: MinioSwitchoverPhase,
) -> SwitchoverPolicy:
    """按阶段构造策略。"""
    if phase == "shadow":
        # shadow:主写只走 from_backend;to_backend 只做 shadow write(旁路)
        return SwitchoverPolicy(
            from_backend=from_backend, to_backend=to_backend, phase=phase,
            write_targets=(from_backend,),
            read_priority=(from_backend,),
            allow_delete_from=(from_backend,),
        )
    if phase == "dual_write":
        return SwitchoverPolicy(
            from_backend=from_backend, to_backend=to_backend, phase=phase,
            write_targets=(from_backend, to_backend),
            read_priority=(from_backend, to_backend),
            allow_delete_from=(from_backend,),  # cutover 前不允许删旧
        )
    if phase == "cutover":
        return SwitchoverPolicy(
            from_backend=from_backend, to_backend=to_backend, phase=phase,
            write_targets=(to_backend,),
            read_priority=(to_backend, from_backend),  # 兜底读旧
            allow_delete_from=(),  # cutover 完成前保守 · 不删任何一侧
        )
    if phase == "rollback":
        # 回滚:主写立即回到 from_backend · 允许 delete-from-new 清理灰度数据
        return SwitchoverPolicy(
            from_backend=from_backend, to_backend=to_backend, phase=phase,
            write_targets=(from_backend,),
            read_priority=(from_backend,),
            allow_delete_from=(to_backend,),
        )
    raise ValueError(f"unknown phase={phase!r}")


def is_switchover_reversible(policy: SwitchoverPolicy) -> bool:
    """cutover 之后不允许静默回退(需 rollback plan)· 其他阶段可反向。"""
    return policy.phase != "cutover"
