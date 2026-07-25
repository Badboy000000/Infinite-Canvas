"""``app.adapters.provider.stability_policy`` — Provider stability policy 骨架
(Provider PR-08)。

**承接**:[[40 实施计划/Provider 适配体系治理实施计划与PR清单]] PR-08 ·
承接治理方案 M4 `capability / cost_class / cancel_scope / poll_interval` 全量声明。

**定位**:纯 frozen dataclass + 纯函数 · 描述 provider 的**稳定性画像** ·
不接 registry · 不改 provider 运行时行为。

**骨架契约**:
- ``StabilityPolicy``:frozen dataclass · 描述一个 provider 的稳定性画像
- ``COST_CLASSES``:成本档位枚举 · low / medium / high / very_high
- ``build_default_policy(protocol)``:纯函数 · 返回协议默认策略
- ``suggest_poll_interval(policy, attempt)``:纯函数 · 指数退避建议

**默认策略**(经验值 · 治理期基线):
- openai_chat:cost=medium · poll=2s · cancel=graceful
- openai_image:cost=high · poll=3s · cancel=graceful
- runninghub:cost=high · poll=5s · cancel=graceful
- comfyui:cost=medium · poll=2s · cancel=hard
- jimeng_cli:cost=very_high · poll=10s · cancel=hard
- gemini_cli:cost=high · poll=3s · cancel=hard

**不做**:
- 不接 Adapter registry
- 不改 provider 运行时行为
- 不做实时监控 · 只做描述层
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Mapping, Tuple


CostClass = Literal["low", "medium", "high", "very_high"]

COST_CLASSES: Tuple[CostClass, ...] = ("low", "medium", "high", "very_high")

CancelScope = Literal["graceful", "hard", "unsupported"]

CANCEL_SCOPES: Tuple[CancelScope, ...] = ("graceful", "hard", "unsupported")


@dataclass(frozen=True)
class StabilityPolicy:
    """一个 provider 类型的稳定性画像。"""

    protocol: str
    cost_class: CostClass
    initial_poll_interval_ms: int
    max_poll_interval_ms: int
    cancel_scope: CancelScope
    max_attempts: int = 20
    backoff_factor: float = 1.5

    def __post_init__(self) -> None:
        if self.cost_class not in COST_CLASSES:
            raise ValueError(f"cost_class={self.cost_class!r} not in {COST_CLASSES}")
        if self.cancel_scope not in CANCEL_SCOPES:
            raise ValueError(f"cancel_scope={self.cancel_scope!r} not in {CANCEL_SCOPES}")
        if self.initial_poll_interval_ms <= 0:
            raise ValueError("initial_poll_interval_ms must be > 0")
        if self.max_poll_interval_ms < self.initial_poll_interval_ms:
            raise ValueError(
                "max_poll_interval_ms must be >= initial_poll_interval_ms"
            )
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if self.backoff_factor < 1.0:
            raise ValueError("backoff_factor must be >= 1.0")


# 默认策略表(治理期基线 · 经验值)
_DEFAULTS: Mapping[str, StabilityPolicy] = {
    "openai_chat": StabilityPolicy(
        protocol="openai_chat",
        cost_class="medium",
        initial_poll_interval_ms=2000,
        max_poll_interval_ms=15_000,
        cancel_scope="graceful",
    ),
    "openai_image": StabilityPolicy(
        protocol="openai_image",
        cost_class="high",
        initial_poll_interval_ms=3000,
        max_poll_interval_ms=30_000,
        cancel_scope="graceful",
    ),
    "runninghub": StabilityPolicy(
        protocol="runninghub",
        cost_class="high",
        initial_poll_interval_ms=5000,
        max_poll_interval_ms=60_000,
        cancel_scope="graceful",
    ),
    "comfyui": StabilityPolicy(
        protocol="comfyui",
        cost_class="medium",
        initial_poll_interval_ms=2000,
        max_poll_interval_ms=15_000,
        cancel_scope="hard",
    ),
    "jimeng_cli": StabilityPolicy(
        protocol="jimeng_cli",
        cost_class="very_high",
        initial_poll_interval_ms=10_000,
        max_poll_interval_ms=120_000,
        cancel_scope="hard",
    ),
    "gemini_cli": StabilityPolicy(
        protocol="gemini_cli",
        cost_class="high",
        initial_poll_interval_ms=3000,
        max_poll_interval_ms=30_000,
        cancel_scope="hard",
    ),
    "codex_cli": StabilityPolicy(
        protocol="codex_cli",
        cost_class="high",
        initial_poll_interval_ms=3000,
        max_poll_interval_ms=30_000,
        cancel_scope="hard",
    ),
    "modelscope": StabilityPolicy(
        protocol="modelscope",
        cost_class="medium",
        initial_poll_interval_ms=2000,
        max_poll_interval_ms=15_000,
        cancel_scope="graceful",
    ),
}


def known_protocols() -> Tuple[str, ...]:
    return tuple(sorted(_DEFAULTS.keys()))


def build_default_policy(protocol: str) -> StabilityPolicy:
    """返回协议的默认稳定性策略;未知协议返回一个保守 fallback。"""
    if protocol in _DEFAULTS:
        return _DEFAULTS[protocol]
    # 保守 fallback:high cost · 慢 poll · graceful cancel
    return StabilityPolicy(
        protocol=protocol,
        cost_class="high",
        initial_poll_interval_ms=3000,
        max_poll_interval_ms=30_000,
        cancel_scope="graceful",
    )


def suggest_poll_interval(policy: StabilityPolicy, attempt: int) -> int:
    """给定 policy + 当前尝试次数 · 返回建议下一次 poll 的毫秒数(带上限)。"""
    if attempt < 0:
        raise ValueError("attempt must be >= 0")
    proposed = policy.initial_poll_interval_ms * (policy.backoff_factor ** attempt)
    return int(min(proposed, policy.max_poll_interval_ms))
