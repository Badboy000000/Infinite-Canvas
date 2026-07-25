"""``app.security.csrf_policy`` — CSRF 前置策略骨架(部署 PR-12)。

**承接**:[[40 实施计划/部署与安全治理实施计划与PR清单]] PR-12 · 与权限 PR-5
CSRF middleware 互补 · 本模块提供**策略描述层**(哪些路由要求 CSRF · 什么 token
scope · 什么 lifetime)· middleware 归权限 PR-5。

**骨架契约**:
- ``CsrfTokenScope``:Literal · session_bound / request_bound
- ``CsrfPolicy``:frozen dataclass · 一份 policy 描述
- ``build_default_policy(mode)``:三模式默认策略
- ``CSRF_POLICY_ENABLED``:env flag 默认关闭

**默认策略**:
- local_personal:CSRF 默认关闭
- intranet_team:CSRF 开启 · session_bound · lifetime=session · 只对 POST/PUT/PATCH/DELETE 强制
- public_team:CSRF 开启 · request_bound(SameSite=Strict + 双 cookie 模式)· lifetime=15min
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Literal, Mapping, Tuple


DeploymentMode = Literal["local_personal", "intranet_team", "public_team"]
CsrfTokenScope = Literal["session_bound", "request_bound"]

CSRF_TOKEN_SCOPES: Tuple[CsrfTokenScope, ...] = ("session_bound", "request_bound")

# 需要 CSRF token 的 HTTP 方法(治理期基线)
STATE_MUTATING_METHODS: Tuple[str, ...] = ("POST", "PUT", "PATCH", "DELETE")

# 治理期 CSRF 豁免路径前缀(WebSocket / SSE / health check 等)
CSRF_EXEMPT_PATH_PREFIXES: Tuple[str, ...] = (
    "/api/_diag/",
    "/api/health",
    "/ws/",
)

_TRUTHY = frozenset({"1", "true", "yes", "on"})
CSRF_POLICY_ENABLED_ENV = "CSRF_POLICY_ENABLED"


def is_csrf_policy_enabled() -> bool:
    return os.environ.get(CSRF_POLICY_ENABLED_ENV, "").strip().lower() in _TRUTHY


@dataclass(frozen=True)
class CsrfPolicy:
    """一份部署模式下的 CSRF 策略描述。"""

    mode: DeploymentMode
    enabled: bool
    token_scope: CsrfTokenScope
    token_lifetime_seconds: int  # 0 = 与 session 生命周期一致
    require_double_cookie: bool  # 严格模式 · public_team
    same_site_cookie: Literal["Lax", "Strict", "None"] = "Lax"

    def __post_init__(self) -> None:
        if self.token_scope not in CSRF_TOKEN_SCOPES:
            raise ValueError(f"token_scope={self.token_scope!r} not in {CSRF_TOKEN_SCOPES}")
        if self.token_lifetime_seconds < 0:
            raise ValueError("token_lifetime_seconds must be >= 0")


def build_default_policy(mode: DeploymentMode) -> CsrfPolicy:
    if mode == "local_personal":
        return CsrfPolicy(
            mode=mode,
            enabled=False,
            token_scope="session_bound",
            token_lifetime_seconds=0,
            require_double_cookie=False,
            same_site_cookie="Lax",
        )
    if mode == "intranet_team":
        return CsrfPolicy(
            mode=mode,
            enabled=True,
            token_scope="session_bound",
            token_lifetime_seconds=0,
            require_double_cookie=False,
            same_site_cookie="Lax",
        )
    if mode == "public_team":
        return CsrfPolicy(
            mode=mode,
            enabled=True,
            token_scope="request_bound",
            token_lifetime_seconds=15 * 60,
            require_double_cookie=True,
            same_site_cookie="Strict",
        )
    raise ValueError(f"unknown deployment mode={mode!r}")


def is_method_state_mutating(method: str) -> bool:
    return method.upper() in STATE_MUTATING_METHODS


def is_path_csrf_exempt(path: str) -> bool:
    if not path:
        return False
    return any(path.startswith(prefix) for prefix in CSRF_EXEMPT_PATH_PREFIXES)


def should_check_csrf(policy: CsrfPolicy, method: str, path: str) -> bool:
    """便利函数 · 决定单次请求是否要走 CSRF 校验。"""
    if not policy.enabled:
        return False
    if not is_method_state_mutating(method):
        return False
    if is_path_csrf_exempt(path):
        return False
    return True
