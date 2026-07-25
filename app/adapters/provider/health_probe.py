"""``app.adapters.provider.health_probe`` — ProviderRegistryHealth 探针骨架
(Provider PR-09)。

**承接**:[[40 实施计划/Provider 适配体系治理实施计划与PR清单]] PR-09 ·
承接治理方案 §"provider metadata 端点 + 健康探针"。

**定位**:纯 frozen dataclass + 纯函数 · 描述一个 provider registry 的健康
状态视图 · **不接** 网络 · **不接** middleware · 由未来 PR 承接主动 probe。

**骨架契约**:
- ``ProviderHealth``:frozen dataclass · 一个 provider 的健康快照
- ``HealthKind``:Literal["ok", "degraded", "unreachable", "misconfigured", "unknown"]
- ``build_health_view(reports)``:纯函数 · 聚合成 registry-level view
- ``ProviderRegistryHealth``:聚合 view · counts + entries

**不做**:
- 不接主动 HTTP probe(需 metadata 端点承接 · 归下游 PR)
- 不做实时轮询
- 不改路由
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Literal, Mapping, Optional, Sequence, Tuple


HealthKind = Literal["ok", "degraded", "unreachable", "misconfigured", "unknown"]

HEALTH_KINDS: Tuple[HealthKind, ...] = ("ok", "degraded", "unreachable", "misconfigured", "unknown")


@dataclass(frozen=True)
class ProviderHealth:
    """一个 provider 的健康快照。"""

    provider_id: str
    protocol: str
    kind: HealthKind
    detail: str = ""
    latency_ms: Optional[int] = None
    checked_at: Optional[str] = None  # ISO 8601

    def __post_init__(self) -> None:
        if self.kind not in HEALTH_KINDS:
            raise ValueError(f"kind={self.kind!r} not in {HEALTH_KINDS}")
        if not self.provider_id:
            raise ValueError("provider_id must not be empty")
        # detail 严禁承载凭据关键词(与 Provider PR-05 credential_ref 一致)
        blob = (self.detail + " " + self.protocol).lower()
        for kw in ("api_key", "authorization", "bearer ", "secret", "sk-"):
            if kw in blob:
                raise ValueError(
                    f"ProviderHealth.detail must not contain credential-like keyword {kw!r}"
                )


@dataclass(frozen=True)
class ProviderRegistryHealth:
    """全 registry 层面的聚合健康视图。"""

    entries: Tuple[ProviderHealth, ...]
    ok_count: int
    degraded_count: int
    unreachable_count: int
    misconfigured_count: int
    unknown_count: int

    @property
    def total(self) -> int:
        return (
            self.ok_count
            + self.degraded_count
            + self.unreachable_count
            + self.misconfigured_count
            + self.unknown_count
        )

    def is_all_ok(self) -> bool:
        return self.ok_count == self.total and self.total > 0


def build_health_view(reports: Iterable[ProviderHealth]) -> ProviderRegistryHealth:
    """把 provider 级别的健康报告聚合为 registry 级 view(纯函数)。"""
    entries = tuple(sorted(reports, key=lambda h: h.provider_id))
    counts = {kind: 0 for kind in HEALTH_KINDS}
    for h in entries:
        counts[h.kind] += 1
    return ProviderRegistryHealth(
        entries=entries,
        ok_count=counts["ok"],
        degraded_count=counts["degraded"],
        unreachable_count=counts["unreachable"],
        misconfigured_count=counts["misconfigured"],
        unknown_count=counts["unknown"],
    )
