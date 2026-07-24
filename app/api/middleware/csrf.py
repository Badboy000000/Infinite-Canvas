"""CSRF 双提交 token middleware(权限 PR-5 · Wave 3-N.9 Batch 2 主线 A)。

**定位**:防御 CSRF(跨站请求伪造)· 双提交 pattern:
- Cookie `ic_csrf_token=<opaque-token>` 由后端 SET · 前端 JS 需要读它(`HttpOnly=false`)
- Header `X-CSRF-Token: <same-token>` 由前端 JS 从 Cookie 读取后附加到写请求
- Middleware 校验:两者相等且非空 → 通过 · 否则 403 `{"code":"csrf_mismatch",...}`

**默认关闭**(GM-22 defaults-off pattern 第 10 次复用 · Wave 3-N.9):
- `CSRF_ENABLED=false`(默认)→ middleware 挂载但直通(等价旧行为)
- `CSRF_ENABLED=true`(生产)→ 校验写方法(POST/PUT/PATCH/DELETE)

**豁免**:
- 只对写方法 POST/PUT/PATCH/DELETE 生效 · GET/HEAD/OPTIONS 直通
- 认证入口白名单:`/api/auth/login` / `/api/auth/logout` / `/api/whoami`
  / `/api/auth/whoami`(登录本身要 SET Cookie · 会形成循环依赖)

**P0 密钥零泄漏**:token 不出现在 log / err msg / repr;错误响应 body 只回
`{"code":"csrf_mismatch","message":"CSRF token mismatch"}` 不含 token 值。

**GM-16 pre-flight**:`CSRFMiddleware` / `ensure_csrf_cookie` / `is_csrf_enabled`
全部为新公共符号 · greenfield 确认。
"""
from __future__ import annotations

import os
import secrets
from typing import FrozenSet, Iterable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

__all__ = [
    "CSRFMiddleware",
    "CSRF_COOKIE_NAME",
    "CSRF_HEADER_NAME",
    "CSRF_ENV_FLAG",
    "ensure_csrf_cookie",
    "is_csrf_enabled",
    "generate_csrf_token",
]

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

CSRF_COOKIE_NAME = "ic_csrf_token"
"""前端 JS 需读取的 CSRF token Cookie 名称(`HttpOnly=false`)。"""

CSRF_HEADER_NAME = "X-CSRF-Token"
"""前端 JS 附加到写请求的 CSRF token header 名称。"""

CSRF_ENV_FLAG = "CSRF_ENABLED"
CSRF_COOKIE_SECURE_ENV = "CSRF_COOKIE_SECURE"

_TRUTHY: FrozenSet[str] = frozenset({"1", "true", "yes", "on"})
_FALSY: FrozenSet[str] = frozenset({"0", "false", "no", "off"})

_WRITE_METHODS: FrozenSet[str] = frozenset({"POST", "PUT", "PATCH", "DELETE"})

_DEFAULT_EXEMPT_PATHS: FrozenSet[str] = frozenset(
    {
        "/api/auth/login",
        "/api/auth/logout",
        "/api/auth/whoami",
        "/api/whoami",
    }
)
"""认证入口白名单 · 登录本身要 SET Cookie · 不能强求携带 token(循环依赖)。"""


# ---------------------------------------------------------------------------
# 环境 flag
# ---------------------------------------------------------------------------


def is_csrf_enabled() -> bool:
    """读取 `CSRF_ENABLED` env flag(默认 false)。"""
    raw = os.environ.get(CSRF_ENV_FLAG, "").strip().lower()
    return raw in _TRUTHY


def _cookie_secure() -> bool:
    """`CSRF_COOKIE_SECURE` env flag(默认 true · 生产强制 HTTPS)。

    仅测试 / 开发场景下允许显式设 `false` 让 TestClient 的 http:// 走通。
    """
    raw = os.environ.get(CSRF_COOKIE_SECURE_ENV, "").strip().lower()
    if raw in _FALSY:
        return False
    return True


# ---------------------------------------------------------------------------
# Token 生成
# ---------------------------------------------------------------------------


def generate_csrf_token() -> str:
    """生成新的 CSRF token(32 字节随机 · URL-safe base64 编码)。

    使用 `secrets.token_urlsafe(32)` · 密码学安全随机源 · 长度 ~43 字符。
    """
    return secrets.token_urlsafe(32)


# ---------------------------------------------------------------------------
# Cookie helper
# ---------------------------------------------------------------------------


def ensure_csrf_cookie(request: Request, response: Response) -> str:
    """确保响应带 `ic_csrf_token` Cookie(若请求无 Cookie 则生成新的)。

    - 请求携带 Cookie 且非空 → 复用原值 · 不 SET-Cookie
    - 请求无 Cookie / 空 Cookie → 生成新 token · SET-Cookie
    - 返回值:最终 token(供 caller 记 log / 埋点使用 · 不许 log 到磁盘)

    P0 密钥零泄漏:token 值不出现在 log / err msg 中。
    """
    existing = request.cookies.get(CSRF_COOKIE_NAME)
    if existing and existing.strip():
        return existing
    new_token = generate_csrf_token()
    # HttpOnly=False 因为前端 JS 需要读取值放到 header;secure/SameSite 仍加强防御
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=new_token,
        httponly=False,
        secure=_cookie_secure(),
        samesite="lax",
        path="/",
    )
    return new_token


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


class CSRFMiddleware(BaseHTTPMiddleware):
    """CSRF 双提交 token 校验 middleware。

    行为:
    - `CSRF_ENABLED=false`(默认)→ 全直通 · 只在响应上确保 SET-Cookie(首访问)
    - `CSRF_ENABLED=true` 时:
      * 读方法(GET/HEAD/OPTIONS)→ 直通 · 只 ensure SET-Cookie
      * 写方法 + 豁免路径 → 直通 · 只 ensure SET-Cookie
      * 写方法 + 非豁免路径:
        - 无 header 或 header 空 → 403 `csrf_missing_header`
        - 无 cookie 或 cookie 空 → 403 `csrf_missing_cookie`
        - cookie != header → 403 `csrf_mismatch`
        - 匹配 → 直通

    错误响应格式:`{"code":"<code>","message":"CSRF token mismatch"}` · 不回显 token。
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        exempt_paths: Iterable[str] | None = None,
    ) -> None:
        super().__init__(app)
        # 允许注入自定义豁免路径(测试 / 未来扩展)· 默认取模块常量。
        self._exempt: FrozenSet[str] = (
            frozenset(exempt_paths)
            if exempt_paths is not None
            else _DEFAULT_EXEMPT_PATHS
        )

    async def dispatch(self, request: Request, call_next):
        # flag off:全直通 · 但仍 ensure SET-Cookie(便于前端渐进开启)
        if not is_csrf_enabled():
            response = await call_next(request)
            ensure_csrf_cookie(request, response)
            return response

        method = request.method.upper()
        path = request.url.path

        # 读方法直通(GET/HEAD/OPTIONS)+ 豁免路径直通
        if method not in _WRITE_METHODS or path in self._exempt:
            response = await call_next(request)
            ensure_csrf_cookie(request, response)
            return response

        # 写方法 + 非豁免:校验双提交 token
        cookie_token = request.cookies.get(CSRF_COOKIE_NAME) or ""
        header_token = request.headers.get(CSRF_HEADER_NAME) or ""

        if not header_token:
            return _csrf_reject("csrf_missing_header")
        if not cookie_token:
            return _csrf_reject("csrf_missing_cookie")
        # 常量时间比较 · 防时序攻击
        if not secrets.compare_digest(cookie_token, header_token):
            return _csrf_reject("csrf_mismatch")

        response = await call_next(request)
        # 匹配通过 · Cookie 已有 · 不 rotate(GET response 会重新 SET · rotate 由前端自主)
        return response


def _csrf_reject(code: str) -> JSONResponse:
    """构造 CSRF 拒绝响应 · 零 token 泄漏。"""
    return JSONResponse(
        status_code=403,
        content={
            "code": code,
            "message": "CSRF token mismatch",
        },
    )
