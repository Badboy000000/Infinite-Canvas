"""``app.security.rate_limit_policy`` — RateLimit 前置策略骨架(部署 PR-09)。

**承接**:[[40 实施计划/部署与安全治理实施计划与PR清单]] PR-09 · 承接治理方案
M3 rate limit 分层策略。

**定位**:纯 frozen dataclass + 纯函数 · 描述路由分组的 rate-limit 策略 ·
**不接** middleware · 由未来 PR 承接接入 FastAPI middleware。

**骨架契约**:
- ``RouteGroup``:Literal · 路由分组枚举 · public / user / admin / heavy
- ``RateLimitPolicy``:frozen dataclass · 每分组的 rate 策略
- ``build_default_policies(mode)``:纯函数 · 按部署模式返回策略表
- ``estimate_next_available_ms(policy, current_tokens, elapsed_ms)``:纯函数

**默认策略**(治理期基线):
- local_personal:全 unlimited(dev 环境)
- intranet_team:public=60/min · user=300/min · admin=60/min · heavy=20/min
- public_team:public=30/min · user=120/min · admin=60/min · heavy=10/min

**不做**:
- 不接 middleware
- 不接 Redis / distributed rate limit
- 不做真实计数(骨架层只描述策略)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Literal, Mapping, Tuple


DeploymentMode = Literal["local_personal", "intranet_team", "public_team"]
RouteGroup = Literal["public", "user", "admin", "heavy"]

ROUTE_GROUPS: Tuple[RouteGroup, ...] = ("public", "user", "admin", "heavy")


_TRUTHY = frozenset({"1", "true", "yes", "on"})
RATE_LIMIT_POLICY_ENABLED_ENV = "RATE_LIMIT_POLICY_ENABLED"


def is_rate_limit_policy_enabled() -> bool:
    return os.environ.get(RATE_LIMIT_POLICY_ENABLED_ENV, "").strip().lower() in _TRUTHY


@dataclass(frozen=True)
class RateLimitPolicy:
    """单个路由分组的 rate-limit 策略。"""

    group: RouteGroup
    tokens_per_minute: int  # 0 = unlimited
    burst: int              # 令牌桶容量上限
    scope: Literal["ip", "user", "session"] = "ip"

    def __post_init__(self) -> None:
        if self.group not in ROUTE_GROUPS:
            raise ValueError(f"group={self.group!r} not in {ROUTE_GROUPS}")
        if self.tokens_per_minute < 0:
            raise ValueError("tokens_per_minute must be >= 0")
        if self.burst < 0:
            raise ValueError("burst must be >= 0")

    @property
    def unlimited(self) -> bool:
        return self.tokens_per_minute == 0


def build_default_policies(mode: DeploymentMode) -> Mapping[RouteGroup, RateLimitPolicy]:
    """按部署模式返回默认策略表。"""
    if mode == "local_personal":
        return {g: RateLimitPolicy(group=g, tokens_per_minute=0, burst=0) for g in ROUTE_GROUPS}
    if mode == "intranet_team":
        return {
            "public": RateLimitPolicy(group="public", tokens_per_minute=60, burst=30, scope="ip"),
            "user": RateLimitPolicy(group="user", tokens_per_minute=300, burst=100, scope="user"),
            "admin": RateLimitPolicy(group="admin", tokens_per_minute=60, burst=20, scope="user"),
            "heavy": RateLimitPolicy(group="heavy", tokens_per_minute=20, burst=5, scope="user"),
        }
    if mode == "public_team":
        return {
            "public": RateLimitPolicy(group="public", tokens_per_minute=30, burst=15, scope="ip"),
            "user": RateLimitPolicy(group="user", tokens_per_minute=120, burst=40, scope="user"),
            "admin": RateLimitPolicy(group="admin", tokens_per_minute=60, burst=20, scope="user"),
            "heavy": RateLimitPolicy(group="heavy", tokens_per_minute=10, burst=3, scope="user"),
        }
    raise ValueError(f"unknown deployment mode={mode!r}")


def estimate_next_available_ms(
    policy: RateLimitPolicy,
    *,
    current_tokens: float,
    tokens_needed: float = 1.0,
) -> int:
    """给定剩余 token 数 · 估算距离下次可用的毫秒数(纯函数)。

    tokens_per_minute → tokens_per_ms = tpm / 60000
    需要补齐 (tokens_needed - current_tokens) 个 token
    """
    if policy.unlimited:
        return 0
    if current_tokens >= tokens_needed:
        return 0
    deficit = tokens_needed - current_tokens
    tokens_per_ms = policy.tokens_per_minute / 60_000.0
    if tokens_per_ms <= 0:
        return 0
    return int(deficit / tokens_per_ms) + 1
