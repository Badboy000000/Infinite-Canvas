"""FastAPI middleware 集合(权限 PR-5 · Wave 3-N.9 Batch 2 主线 A)。

**当前成员**:
- `CSRFMiddleware`:双提交 token CSRF 校验(默认关闭 · `CSRF_ENABLED=false`)。

**GM-16 pre-flight**:`app.api.middleware` 目录为新建目录 · greenfield 确认。
"""
from __future__ import annotations

from .csrf import (
    CSRF_COOKIE_NAME,
    CSRF_HEADER_NAME,
    CSRFMiddleware,
    ensure_csrf_cookie,
    is_csrf_enabled,
)

__all__ = [
    "CSRFMiddleware",
    "CSRF_COOKIE_NAME",
    "CSRF_HEADER_NAME",
    "ensure_csrf_cookie",
    "is_csrf_enabled",
]
