"""`require_permission` FastAPI dependency(权限 PR-5 · Wave 3-N.9 Batch 2 主线 A)。

**定位**:高风险接口保护的挂点·统一 `role → action → bool` 决策入口·
`PERMISSION_ENFORCEMENT` env flag 三档语义:
- `off`(默认):dep 恒 return None · 等价旧行为(GM-22 defaults-off pattern
  第 11 次复用 · Wave 3-N.9 Batch 2)
- `shadow`:未授权只 log audit + 响应头 `X-Auth-Shadow: 1` · 不拒绝
- `enforce`:未授权 401(anonymous)/ 403(有身份无权)拒绝

**零错误消息泄漏**(P0 契约):
- 错误响应统一 `{"code":"permission_denied"}` / `{"code":"authentication_required"}`
- 不透露 resource 存在性 · 不透露 role 名 · 不透露 action 名(通过统一 message)

**GM-16 pre-flight**:`require_permission` / `attach_permission_guards` /
`is_permission_enforcement_enabled` / `PermissionEnforcementMode` 全部为新公共
符号 · greenfield 确认。

**消费方**:
- FastAPI 路由:`Depends(require_permission("provider:manage"))`(推荐)
- main.py 尾部 `attach_permission_guards(app)`:遍历已注册路由 · 匹配 5 个高风险
  接口 · dependant.dependencies.insert 挂 dep(方案 A)
- 若方案 A 在特定 FastAPI 版本不稳定 → 退方案 B:middleware 层包装(未实现)
"""
from __future__ import annotations

import logging
import os
from typing import Callable, FrozenSet, Iterable, List, Literal, Optional

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.params import Depends as DependsParam

from app.api.context import request_context_dependency
from app.identity.request_context import RequestContext, derive_principal_kind
from app.services.audit import (
    AuditService,
    make_event,
)
from app.services.permission import (
    DEFAULT_PERMISSION_SERVICE,
    PermissionService,
)

__all__ = [
    "require_permission",
    "attach_permission_guards",
    "is_permission_enforcement_enabled",
    "get_permission_enforcement_mode",
    "PermissionEnforcementMode",
    "PERMISSION_ENFORCEMENT_ENV",
    "HIGH_RISK_ROUTES",
    "SHADOW_RESPONSE_HEADER",
    "get_default_audit_service",
    "set_default_audit_service_for_tests",
]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 环境 flag(GM-22 defaults-off pattern 第 11 次复用)
# ---------------------------------------------------------------------------

PermissionEnforcementMode = Literal["off", "shadow", "enforce"]

PERMISSION_ENFORCEMENT_ENV = "PERMISSION_ENFORCEMENT"
SHADOW_RESPONSE_HEADER = "X-Auth-Shadow"

_VALID_MODES: FrozenSet[str] = frozenset({"off", "shadow", "enforce"})


def get_permission_enforcement_mode() -> PermissionEnforcementMode:
    """读取 `PERMISSION_ENFORCEMENT` env flag(默认 `"off"`)。

    - 未设置 / 未知值 → `"off"`(fail-open 至等价旧行为)
    - `"off"` / `"shadow"` / `"enforce"` → 逐字返回
    """
    raw = os.environ.get(PERMISSION_ENFORCEMENT_ENV, "").strip().lower()
    if raw in _VALID_MODES:
        return raw  # type: ignore[return-value]
    return "off"


def is_permission_enforcement_enabled() -> bool:
    """`PERMISSION_ENFORCEMENT` 是否非 `"off"`(shadow 或 enforce)。"""
    return get_permission_enforcement_mode() != "off"


# ---------------------------------------------------------------------------
# AuditService 单例(可被测试替换)
# ---------------------------------------------------------------------------

_default_audit_service: Optional[AuditService] = None


def get_default_audit_service() -> AuditService:
    """获取进程内 AuditService 单例(懒初始化)。

    测试可通过 `set_default_audit_service_for_tests(...)` 注入 buffered_only 实例。
    """
    global _default_audit_service
    if _default_audit_service is None:
        _default_audit_service = AuditService()
    return _default_audit_service


def set_default_audit_service_for_tests(svc: Optional[AuditService]) -> None:
    """测试专用:注入自定义 AuditService(或传 None 重置)。"""
    global _default_audit_service
    _default_audit_service = svc


# ---------------------------------------------------------------------------
# require_permission
# ---------------------------------------------------------------------------


def require_permission(
    action: str,
    *,
    permission_service: Optional[PermissionService] = None,
) -> Callable[..., None]:
    """构造 FastAPI dependency:强制 principal 拥有 `action` 权限点。

    行为矩阵(`PERMISSION_ENFORCEMENT` × principal_kind × allow):
    - `off` → return · 等价旧行为(不认证 · 不写 audit · 不改响应)
    - `shadow`:
      * allow=True → 写 `permission.check_allowed` audit · return
      * allow=False → 写 `permission.check_denied` audit · 设响应头
        `X-Auth-Shadow: 1` · **不 raise**
    - `enforce`:
      * allow=True → 写 `permission.check_allowed` audit · return
      * anonymous 拒绝 → 401 `authentication_required`
      * 有身份拒绝 → 403 `permission_denied`

    错误响应契约:`HTTPException(status, detail={"code":"...","message":"..."})` ·
    统一 message · 不透露 resource / role / action 名称(P0 零泄漏)。

    参数:
    - `action`:action key(必须在 `DEFAULT_ACTIONS` 白名单内 · 未知 action →
      恒拒绝 · 视为编码 bug)
    - `permission_service`:可选注入 PermissionService(测试用 · 默认取全局单例)
    """
    svc = permission_service or DEFAULT_PERMISSION_SERVICE

    def _dep(
        request: Request,
        response: Response,
        ctx: RequestContext = Depends(request_context_dependency),
    ) -> None:
        mode = get_permission_enforcement_mode()

        # off 档:等价旧行为 · 直接放行
        if mode == "off":
            return None

        role = svc.resolve_role(ctx)
        principal_kind = ctx.principal_kind or derive_principal_kind(ctx)
        allowed = svc.allow(role, action)

        # audit:无论 allow/deny · 都记录(shadow/enforce 相同)
        audit = get_default_audit_service()
        try:
            audit.append(
                make_event(
                    "permission.check_allowed" if allowed else "permission.check_denied",
                    "success" if allowed else "denied",
                    context={
                        "request_id": ctx.request_id,
                        "principal_kind": principal_kind,
                        "role": role,
                        "permission": action,
                        "user_id": ctx.x_user_id,
                        "session_id": ctx.session_id,
                        "workspace_id": ctx.workspace_id,
                        "project_id": ctx.project_id,
                        "reason": None if allowed else "role_action_not_allowed",
                    },
                )
            )
        except Exception:  # pragma: no cover — audit 失败不该阻塞请求
            logger.warning("audit append failed for action=%s", action)

        if allowed:
            return None

        # shadow 档:设响应头 · 不 raise
        if mode == "shadow":
            response.headers[SHADOW_RESPONSE_HEADER] = "1"
            return None

        # enforce 档:根据 principal 类型分 401 / 403
        if principal_kind == "anonymous":
            raise HTTPException(
                status_code=401,
                detail={
                    "code": "authentication_required",
                    "message": "Authentication required",
                },
            )
        raise HTTPException(
            status_code=403,
            detail={
                "code": "permission_denied",
                "message": "Permission denied",
            },
        )

    return _dep


# ---------------------------------------------------------------------------
# 高风险路由清单 + attach_permission_guards
# ---------------------------------------------------------------------------

# (method, path, action) · 与 [[30 治理方案/用户团队权限治理方案]]
# §"高风险接口优先保护"对齐 · 5 个 P0 接口。
HIGH_RISK_ROUTES: List[tuple[str, str, str]] = [
    ("PUT", "/api/providers", "provider:manage"),
    ("DELETE", "/api/canvases/{canvas_id}", "canvas:delete"),
    ("PATCH", "/api/storage-settings", "workspace:admin"),
    ("POST", "/api/update-from-github", "workspace:admin"),
    ("POST", "/api/update-rollback", "workspace:admin"),
]


def attach_permission_guards(
    app: FastAPI,
    *,
    routes: Optional[Iterable[tuple[str, str, str]]] = None,
    permission_service: Optional[PermissionService] = None,
) -> List[tuple[str, str, str]]:
    """遍历 `app.routes` · 对匹配的高风险路由挂 `require_permission` dep。

    - 幂等:同一 (method, path) 只挂一次 · 通过 sentinel 属性
      `__ic_permission_action__` 标记已挂 · 重复调用 skip。
    - 无副作用 for miss:未匹配路由不动。
    - 返回:实际挂上的 (method, path, action) 列表(供 caller 记 log 用)。

    **默认关闭承接**:caller 应在 `is_permission_enforcement_enabled()` 为 True
    时才调用本函数(避免 `off` 档下把 dep 挂上导致响应头 / audit 意外产生)。
    - 但 dep 自身在 `off` 档也 fail-open · 挂了也不影响响应契约(次要防线)。

    参数:
    - `app`:FastAPI 应用实例。
    - `routes`:可选自定义清单(测试用)· 默认取 `HIGH_RISK_ROUTES`。
    - `permission_service`:可选注入 PermissionService(测试用)。
    """
    target = list(routes if routes is not None else HIGH_RISK_ROUTES)
    attached: List[tuple[str, str, str]] = []

    # 惰性 import:避免顶部循环
    from fastapi.routing import APIRoute

    # 构造一个 method → {path → action} 索引 · O(1) 匹配
    index: dict[tuple[str, str], str] = {
        (method.upper(), path): action for method, path, action in target
    }

    for route in list(app.routes):
        if not isinstance(route, APIRoute):
            continue
        path = route.path
        methods = {m.upper() for m in (route.methods or set())}
        for method in methods:
            action = index.get((method, path))
            if action is None:
                continue
            # 幂等 sentinel
            if getattr(route, "__ic_permission_action__", None) == action:
                continue
            # 方案 A:route.dependant.dependencies.insert dep
            dep_callable = require_permission(
                action, permission_service=permission_service
            )
            _insert_dep_into_route(route, dep_callable)
            setattr(route, "__ic_permission_action__", action)
            attached.append((method, path, action))
    return attached


def _insert_dep_into_route(route, dep_callable: Callable[..., None]) -> None:
    """向已注册 route 的 dependant 链头插入一个 FastAPI Depends(dep_callable)。

    实现细节:
    - FastAPI 路由 dependant 是通过 `get_dependant()` 分析签名构造的树。
    - 直接改 dependant 结构比重建路由更稳:
      1. 复用 `get_parameterless_sub_dependant(...)` 构造 sub-dependant
      2. `route.dependant.dependencies.insert(0, sub_dependant)`
    - 兼容 FastAPI 0.100+ / 0.115.4(项目锁定版本)· API 稳定。
    """
    from fastapi.dependencies.utils import get_parameterless_sub_dependant

    depends = Depends(dep_callable)
    # DependsParam 是 Depends 返回类型 · 确保是标记
    assert isinstance(depends, DependsParam), "Depends() must return DependsParam"
    sub_dep = get_parameterless_sub_dependant(depends=depends, path=route.path)
    route.dependant.dependencies.insert(0, sub_dep)
