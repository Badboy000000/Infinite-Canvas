"""`IdentityBridgeMiddleware` — 权限 PR-9(Wave 3-N.9 Batch 2 主线 B)。

**定位**:HTTP 请求栈的**影子层** · 消费 `RequestContext`(由 PR-BE-02
`RequestContextMiddleware` 已 set 的 ContextVar 或 request.state)· 调用
`IdentityBridge.resolve` 得到 `BridgeResolution` · 写入
`request.state.bridge_resolution` 供下游只读消费。

**三档语义**(env `IDENTITY_BRIDGE_ENFORCE` · defaults-off · GM-22 第 11 次复用):
- `off`(默认):完全不注册 middleware(挂载点在 main.py 尾部 guard) ·
  等价旧行为 · 零副作用。
- `shadow`:注册 middleware · 每请求 resolve · 写 `request.state` · 未匹配 /
  authenticated 与 legacy_bridged 不一致时 emit audit log · **不改路由行为**。
- `enforce`:注册 middleware · 语义同 shadow · 未来 PR 会在下游路由改造
  阶段消费 `bridge_resolution.user_id` 主导授权决策 · **本 PR 不落这条分支
  的行为差异**(下游路由不消费 = enforce 等价 shadow · 但 flag 位已就位)。

**P0 密钥零泄漏**:
- audit context 只用 whitelist 字段(request_id / user_id / principal_kind /
  reason 等) · legacy_user_key 长度 >= 40 时中间 mask 为 `xxx...xxx`。
- 不直接把 password / token / secret 字段落入 audit(RequestContext 本身
  不含此类字段 · 但 mask 逻辑作为半敏感兜底)。

**中间件顺序**(与主线 A 权限 PR-5 CSRF 协作):
- CSRF 挂在**外层**(先跑) · IdentityBridge 挂在**内层**(后跑 · 拿到已
  CSRF 通过的 request 再 resolve)。
- 顺序在 main.py 挂载点由 Lead 序列化时保证:
    app.add_middleware(RequestContextMiddleware)   # 最外层(PR-BE-02)
    app.add_middleware(IdentityBridgeMiddleware)   # 中(本 PR)
    app.add_middleware(CSRFMiddleware)             # 内(主线 A)
    ↑ Starlette 语义:后 add 者靠外 · 所以 CSRF add 顺序应在 IdentityBridge
      **之后** · 具体 Lead 侧序列化 rebase 时处理。
"""
from __future__ import annotations

import logging
import os
from typing import FrozenSet, Optional

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from starlette.types import ASGIApp

from app.api.context import get_request_context
from app.services.audit import AuditService, make_event

from .bridge import BridgeResolution, IdentityBridge
from .request_context import RequestContext

__all__ = [
    "ENFORCE_MODE_OFF",
    "ENFORCE_MODE_SHADOW",
    "ENFORCE_MODE_ENFORCE",
    "IDENTITY_BRIDGE_ENFORCE_ENV",
    "IdentityBridgeMiddleware",
    "get_bridge_enforce_mode",
    "is_identity_bridge_enabled",
    "mask_sensitive_key",
]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Env flag(GM-22 defaults-off pattern · 第 11 次复用)
# ---------------------------------------------------------------------------

IDENTITY_BRIDGE_ENFORCE_ENV = "IDENTITY_BRIDGE_ENFORCE"

ENFORCE_MODE_OFF = "off"
ENFORCE_MODE_SHADOW = "shadow"
ENFORCE_MODE_ENFORCE = "enforce"

_VALID_MODES: FrozenSet[str] = frozenset(
    {ENFORCE_MODE_OFF, ENFORCE_MODE_SHADOW, ENFORCE_MODE_ENFORCE}
)


def get_bridge_enforce_mode() -> str:
    """读取 `IDENTITY_BRIDGE_ENFORCE` env · 默认 `off` · 非法值降级 `off`。

    大小写不敏感 · trim 空白 · 未识别值(拼错 / 老配置遗留)恒回退到 `off`
    保证升级过程零副作用。
    """
    raw = os.environ.get(IDENTITY_BRIDGE_ENFORCE_ENV, "").strip().lower()
    if raw not in _VALID_MODES:
        return ENFORCE_MODE_OFF
    return raw


def is_identity_bridge_enabled() -> bool:
    """middleware 是否应挂载 · 只在 shadow / enforce 下返回 True。"""
    return get_bridge_enforce_mode() in (ENFORCE_MODE_SHADOW, ENFORCE_MODE_ENFORCE)


# ---------------------------------------------------------------------------
# 敏感字段脱敏(legacy_user_key 长度 >= 40 视为半敏感)
# ---------------------------------------------------------------------------

_MASK_THRESHOLD = 40


def mask_sensitive_key(value: Optional[str]) -> Optional[str]:
    """半敏感字符串中间 mask:`abc...xyz` 保留首尾各 3 字符。

    - `value is None` → None
    - `len(value) < _MASK_THRESHOLD` → 原样返回(短串通常是明文用户名 · 无脱敏必要)
    - 否则 → `头 3 + '...' + 尾 3`
    """
    if value is None:
        return None
    if len(value) < _MASK_THRESHOLD:
        return value
    return f"{value[:3]}...{value[-3:]}"


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


class IdentityBridgeMiddleware(BaseHTTPMiddleware):
    """在 HTTP 请求栈内解析 legacy 身份 · 写 `request.state.bridge_resolution`。

    本 middleware **零副作用**(off / shadow 两档):
    - 不改 RequestContext 已有字段(冻结契约)
    - 不改路由行为(下游没有消费 `bridge_resolution` 的分支)
    - 不改错误 / 响应格式

    shadow 模式副效应:
    - 若 `resolution.kind == "legacy_unmatched"` → emit audit
      `permission.check_denied` w/ reason
    - 若 `resolution.kind == "authenticated"` 与 legacy signals(x_user_id /
      legacy_user_key)存在但派生的 `legacy_bridged` 结果不一致 → emit audit
      提示 identity mismatch(未来 PR 演进的观测埋点)

    构造签名:
    - `bridge`:预先构造好的 `IdentityBridge` 实例(依赖注入 store)
    - `audit_service`:可选 · None 时使用 buffered-only fallback(不落盘)
      避免测试意外写 audit_logs.jsonl。
    """

    def __init__(
        self,
        app: ASGIApp,
        bridge: IdentityBridge,
        audit_service: Optional[AuditService] = None,
    ) -> None:
        super().__init__(app)
        self._bridge = bridge
        # audit_service 默认 buffered-only(不写盘) · 生产切换时 caller 传入
        # 挂载真实落盘的 AuditService。
        self._audit = audit_service if audit_service is not None else AuditService(
            buffered_only=True
        )

    async def dispatch(self, request: Request, call_next):
        # RequestContext 来源:PR-BE-02 middleware 已 set 到 ContextVar
        # (本 middleware 位于其**内层** · Starlette 语义先后 add 靠内 · 但
        # 由于 PR-BE-02 是最后 add 的最外层 · 本 middleware 在 dispatch
        # 时 ContextVar 已就绪)。fallback ctx 兜底保证测试路径不 KeyError。
        ctx: RequestContext = get_request_context()

        resolution: BridgeResolution = self._bridge.resolve(ctx)

        # 只读挂载到 request.state · 下游路由 / 依赖可通过
        # `request.state.bridge_resolution` 访问。字段名冻结。
        request.state.bridge_resolution = resolution

        # shadow 模式副效应:audit 未匹配 / mismatch
        mode = get_bridge_enforce_mode()
        if mode in (ENFORCE_MODE_SHADOW, ENFORCE_MODE_ENFORCE):
            self._maybe_emit_audit(ctx, resolution, mode)

        response: Response = await call_next(request)
        return response

    # ---- 内部 helpers ----------------------------------------------------

    def _maybe_emit_audit(
        self,
        ctx: RequestContext,
        resolution: BridgeResolution,
        mode: str,
    ) -> None:
        """shadow / enforce 模式下 · 针对未匹配 / 不一致 emit audit event。"""
        should_emit = False
        outcome = "success"
        action = "permission.check_allowed"
        reason: Optional[str] = None

        if resolution.kind == "legacy_unmatched":
            should_emit = True
            outcome = "denied"
            action = "permission.check_denied"
            reason = resolution.fallback_reason or "legacy_unmatched"
        elif resolution.kind == "authenticated" and (
            ctx.legacy_user_key and not resolution.user_id
        ):
            # authenticated 宣称但 legacy signals 存在且未 map · 观测点
            should_emit = True
            outcome = "error"
            action = "permission.check_denied"
            reason = "authenticated_mode_legacy_mismatch"

        if not should_emit:
            return

        # legacy_user_key 半敏感 mask
        masked_key = mask_sensitive_key(ctx.legacy_user_key)

        context = {
            "request_id": ctx.request_id,
            "user_id": resolution.user_id,
            "principal_kind": ctx.principal_kind,
            "session_id": ctx.session_id,
            "workspace_id": ctx.workspace_id,
            "project_id": ctx.project_id,
            "reason": reason,
            "ip": ctx.ip,
            "user_agent": ctx.user_agent,
        }
        # legacy_user_key 不在 audit whitelist 内 · 自动 drop · 但把 mask
        # 版本写进 logger 供调试(debug 级别 · 生产不打)。
        try:
            event = make_event(action, outcome, context=context)  # type: ignore[arg-type]
            self._audit.append(event)
        except Exception:  # pragma: no cover - audit 失败绝不阻塞主路径
            logger.exception("IdentityBridgeMiddleware audit emit failed")

        logger.debug(
            "IdentityBridge shadow mode: kind=%s reason=%s legacy_key=%s mode=%s",
            resolution.kind,
            reason,
            masked_key,
            mode,
        )
