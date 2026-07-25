"""``app.services.files.static_mount_sunset`` — 静态挂载下线判据骨架
(文件 PR-14 骨架 · 最终形态归 MinIO 灰度收尾)。

**承接**:[[40 实施计划/文件对象与 MinIO 治理实施计划与PR清单]] PR-14 · 文件对象
专题骨架**最终 PR**。

**定位**:纯函数 · 承接文件 PR-9 sunset judgement + 文件 PR-12 switchover cutover
· 判定何时可以下线 `/assets` / `/output` 静态挂载。**不实际 unmount** ·
只描述判据。

**判据(治理方案硬门槛)**:
- MinIO switchover phase = cutover 且已稳定 ≥ 7 天
- legacy_url_sunset 三个 bucket(/assets / /output / /output/**) 全部 verdict=retire
- 30 天 access log 无 legacy URL 命中
- 无未解析的 legacy_url_refs(mapped_ratio=100%)

**不做**:
- 不接 access log(需下游 PR)
- 不改 main.py static mount
- 不发通知
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Iterable, Literal, Sequence, Tuple


_TRUTHY = frozenset({"1", "true", "yes", "on"})
STATIC_MOUNT_SUNSET_STRICT_ENV = "STATIC_MOUNT_SUNSET_STRICT"


def is_static_mount_sunset_strict() -> bool:
    return os.environ.get(STATIC_MOUNT_SUNSET_STRICT_ENV, "").strip().lower() in _TRUTHY


StaticMountVerdict = Literal["ready_to_unmount", "hold", "blocked"]

VERDICTS: Tuple[StaticMountVerdict, ...] = ("ready_to_unmount", "hold", "blocked")


@dataclass(frozen=True)
class StaticMountReadiness:
    """一次判定的输入 + 结论。"""

    mount_path: str  # 如 "/assets" / "/output"
    cutover_stable_days: int  # cutover 状态稳定天数
    all_buckets_retired: bool  # 关联 buckets 全部 verdict=retire
    legacy_access_last_30d: int  # 最近 30 天 access log 命中数
    unmapped_urls: int  # 未映射的 legacy URL 数

    verdict: StaticMountVerdict = "hold"
    reasons: Tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.mount_path:
            raise ValueError("mount_path must not be empty")
        for k in ("cutover_stable_days", "legacy_access_last_30d", "unmapped_urls"):
            if getattr(self, k) < 0:
                raise ValueError(f"{k} must be >= 0")


def judge_static_mount_readiness(
    *,
    mount_path: str,
    cutover_stable_days: int,
    all_buckets_retired: bool,
    legacy_access_last_30d: int,
    unmapped_urls: int,
    min_cutover_days: int = 7,
) -> StaticMountReadiness:
    """按判据返回 StaticMountReadiness view。"""
    reasons: list[str] = []
    verdict: StaticMountVerdict = "hold"

    if not all_buckets_retired:
        reasons.append("not all buckets retired")
        verdict = "blocked"
    if unmapped_urls > 0:
        reasons.append(f"{unmapped_urls} unmapped legacy URLs remain")
        verdict = "blocked"
    if legacy_access_last_30d > 0:
        reasons.append(f"{legacy_access_last_30d} legacy accesses in last 30 days")
        verdict = "blocked" if verdict != "blocked" else "blocked"
    if cutover_stable_days < min_cutover_days:
        reasons.append(
            f"cutover stable for {cutover_stable_days}d < min {min_cutover_days}d"
        )
        if verdict != "blocked":
            verdict = "hold"

    if not reasons:
        verdict = "ready_to_unmount"
        reasons = ("all sunset criteria satisfied",)

    return StaticMountReadiness(
        mount_path=mount_path,
        cutover_stable_days=cutover_stable_days,
        all_buckets_retired=all_buckets_retired,
        legacy_access_last_30d=legacy_access_last_30d,
        unmapped_urls=unmapped_urls,
        verdict=verdict,
        reasons=tuple(reasons),
    )
