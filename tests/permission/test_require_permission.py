"""权限 PR-5 · require_permission FastAPI dependency 契约测试 (Wave 3-N.9 Batch 2)。

覆盖矩阵:
- `PERMISSION_ENFORCEMENT` 三档(off / shadow / enforce)
- principal_kind 四档(anonymous / session / user 匿名会话 / user 认证)
- allowed vs denied 决策
- 401 vs 403 分流(enforce 档)
- shadow 档 audit 记录 + `X-Auth-Shadow` header
- audit 事件白名单(P0 零泄漏)
- 幂等 attach_permission_guards

设计要点:
- 不 import main.py(减 fixture 复杂度)· 构造 mini FastAPI app + isolated
  AuditService buffer 隔离测试。
- 每个 test 通过 monkeypatch 显式设 PERMISSION_ENFORCEMENT · autouse fixture
  收尾清除。
"""
from __future__ import annotations

from typing import Optional

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.context import (
    RequestContextMiddleware,
    request_context_dependency,
)
from app.identity.request_context import RequestContext
from app.services.audit import AuditService
from app.services.permission import DEFAULT_PERMISSION_SERVICE, PermissionService
from app.services.permission.require import (
    HIGH_RISK_ROUTES,
    PERMISSION_ENFORCEMENT_ENV,
    SHADOW_RESPONSE_HEADER,
    attach_permission_guards,
    get_default_audit_service,
    get_permission_enforcement_mode,
    is_permission_enforcement_enabled,
    require_permission,
    set_default_audit_service_for_tests,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """每个测试独立清 PERMISSION_ENFORCEMENT · 保证测试无泄漏。"""
    monkeypatch.delenv(PERMISSION_ENFORCEMENT_ENV, raising=False)
    yield


@pytest.fixture
def isolated_audit_service():
    """替换全局 AuditService 为 buffered-only 实例 · 测试后自动清理。"""
    svc = AuditService(buffered_only=True)
    set_default_audit_service_for_tests(svc)
    yield svc
    set_default_audit_service_for_tests(None)


def _build_test_app(action: str = "provider:manage") -> FastAPI:
    """构造 mini FastAPI 用于测试 dep 行为(不触发 main.py)。"""
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)

    @app.put("/protected")
    def protected_endpoint(
        _guard: None = Depends(require_permission(action)),
    ) -> dict:
        return {"ok": True}

    @app.get("/whoami-lite")
    def whoami(ctx: RequestContext = Depends(request_context_dependency)) -> dict:
        return {"auth_mode": ctx.auth_mode}

    return app


# ---------------------------------------------------------------------------
# T520 - `off` 档:三种 principal 均直通(0 audit 事件)
# ---------------------------------------------------------------------------


def test_enforcement_off_allows_anonymous(isolated_audit_service, monkeypatch):
    """T520 · off 档 · 匿名请求也直通(等价旧行为)。"""
    monkeypatch.delenv(PERMISSION_ENFORCEMENT_ENV, raising=False)
    client = TestClient(_build_test_app())
    resp = client.put("/protected")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    # off 档不写 audit
    assert isolated_audit_service.buffered_events() == []


def test_enforcement_off_ignores_role_via_legacy_alias(
    isolated_audit_service, monkeypatch
):
    """T521 · off 档 + legacy_alias 请求依然直通。"""
    monkeypatch.setenv(PERMISSION_ENFORCEMENT_ENV, "off")
    client = TestClient(_build_test_app())
    resp = client.put("/protected", headers={"X-User-Id": "user-abc"})
    assert resp.status_code == 200
    assert isolated_audit_service.buffered_events() == []


# ---------------------------------------------------------------------------
# T522-524 - `shadow` 档:audit 记录但不拒绝
# ---------------------------------------------------------------------------


def test_enforcement_shadow_denied_writes_audit_and_header(
    isolated_audit_service, monkeypatch
):
    """T522 · shadow 档 · 匿名+privileged action(provider:manage) → 记 denied
    audit + 设 X-Auth-Shadow: 1 · 不 raise · 200 通过。"""
    monkeypatch.setenv(PERMISSION_ENFORCEMENT_ENV, "shadow")
    client = TestClient(_build_test_app("provider:manage"))
    resp = client.put("/protected")
    assert resp.status_code == 200
    assert resp.headers.get(SHADOW_RESPONSE_HEADER) == "1"
    events = isolated_audit_service.buffered_events()
    assert len(events) == 1
    assert events[0].action == "permission.check_denied"
    assert events[0].outcome == "denied"
    # P0 白名单 · audit event 不含 password / token
    dumped = events[0].to_dict()
    keys = set(dumped.keys())
    assert "password" not in keys and "token" not in keys and "api_key" not in keys


def test_enforcement_shadow_allowed_writes_success_audit(
    isolated_audit_service, monkeypatch
):
    """T523 · shadow 档 · 匿名+canvas:read(viewer 允许)→ 记 allowed audit ·
    不设 shadow header。"""
    monkeypatch.setenv(PERMISSION_ENFORCEMENT_ENV, "shadow")
    client = TestClient(_build_test_app("canvas:read"))
    resp = client.put("/protected")
    assert resp.status_code == 200
    assert SHADOW_RESPONSE_HEADER not in resp.headers
    events = isolated_audit_service.buffered_events()
    assert len(events) == 1
    assert events[0].action == "permission.check_allowed"
    assert events[0].outcome == "success"


def test_enforcement_shadow_never_returns_403(isolated_audit_service, monkeypatch):
    """T524 · shadow 档 · 即便决策拒绝也返回 200(等价旧行为的软护栏)。"""
    monkeypatch.setenv(PERMISSION_ENFORCEMENT_ENV, "shadow")
    client = TestClient(_build_test_app("workspace:admin"))
    for _ in range(3):
        resp = client.put("/protected")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# T525-528 - `enforce` 档:401/403 分流
# ---------------------------------------------------------------------------


def test_enforcement_enforce_anonymous_returns_401(
    isolated_audit_service, monkeypatch
):
    """T525 · enforce 档 · 匿名 → 401 authentication_required。"""
    monkeypatch.setenv(PERMISSION_ENFORCEMENT_ENV, "enforce")
    client = TestClient(_build_test_app("provider:manage"))
    resp = client.put("/protected")
    assert resp.status_code == 401
    body = resp.json()
    assert body["detail"]["code"] == "authentication_required"
    # 零消息泄漏 · 不透露 role/action/resource
    assert "provider" not in body["detail"]["message"].lower()


def test_enforcement_enforce_legacy_user_denied_returns_403(
    isolated_audit_service, monkeypatch
):
    """T526 · enforce 档 · legacy_alias (x_user_id) + provider:manage
    (member 不允许) → 403 permission_denied。"""
    monkeypatch.setenv(PERMISSION_ENFORCEMENT_ENV, "enforce")
    client = TestClient(_build_test_app("provider:manage"))
    resp = client.put("/protected", headers={"X-User-Id": "user-42"})
    assert resp.status_code == 403
    body = resp.json()
    assert body["detail"]["code"] == "permission_denied"
    assert "provider" not in body["detail"]["message"].lower()


def test_enforcement_enforce_allowed_action_passes(
    isolated_audit_service, monkeypatch
):
    """T527 · enforce 档 · member 拥有 canvas:read → 200 通过 + 记 allowed audit。"""
    monkeypatch.setenv(PERMISSION_ENFORCEMENT_ENV, "enforce")
    client = TestClient(_build_test_app("canvas:read"))
    resp = client.put("/protected", headers={"X-User-Id": "user-99"})
    assert resp.status_code == 200
    events = isolated_audit_service.buffered_events()
    assert len(events) == 1
    assert events[0].action == "permission.check_allowed"


def test_enforcement_enforce_records_audit_on_denied(
    isolated_audit_service, monkeypatch
):
    """T528 · enforce 档拒绝分支也写 audit(denied)。"""
    monkeypatch.setenv(PERMISSION_ENFORCEMENT_ENV, "enforce")
    client = TestClient(_build_test_app("workspace:admin"))
    resp = client.put("/protected", headers={"X-User-Id": "u-x"})
    assert resp.status_code == 403
    events = isolated_audit_service.buffered_events()
    assert len(events) == 1
    assert events[0].action == "permission.check_denied"
    assert events[0].outcome == "denied"


# ---------------------------------------------------------------------------
# T529-531 - 环境 flag 解析边界
# ---------------------------------------------------------------------------


def test_env_flag_defaults_to_off(monkeypatch):
    """T529 · env 未设 → 'off'(fail-open)。"""
    monkeypatch.delenv(PERMISSION_ENFORCEMENT_ENV, raising=False)
    assert get_permission_enforcement_mode() == "off"
    assert not is_permission_enforcement_enabled()


def test_env_flag_unknown_falls_back_to_off(monkeypatch):
    """T530 · 未知值 → 'off'(safe fallback)。"""
    monkeypatch.setenv(PERMISSION_ENFORCEMENT_ENV, "UNKNOWN")
    assert get_permission_enforcement_mode() == "off"


@pytest.mark.parametrize("value,expected", [
    ("off", "off"),
    ("shadow", "shadow"),
    ("enforce", "enforce"),
    ("SHADOW", "shadow"),
    ("Enforce ", "enforce"),
])
def test_env_flag_case_insensitive_and_trimmed(value, expected, monkeypatch):
    """T531 · 大小写不敏感 + 前后空白 trim。"""
    monkeypatch.setenv(PERMISSION_ENFORCEMENT_ENV, value)
    assert get_permission_enforcement_mode() == expected


# ---------------------------------------------------------------------------
# T532 - attach_permission_guards 幂等 & 匹配 HIGH_RISK_ROUTES
# ---------------------------------------------------------------------------


def test_attach_permission_guards_idempotent():
    """T532 · 重复挂载幂等 · sentinel 属性拦截。"""
    app = FastAPI()

    @app.put("/api/providers")
    def put_providers() -> dict:
        return {"ok": True}

    @app.delete("/api/canvases/{canvas_id}")
    def del_canvas(canvas_id: str) -> dict:
        return {"ok": True}

    first = attach_permission_guards(app)
    assert len(first) == 2
    # 第二次 skip
    second = attach_permission_guards(app)
    assert second == []


def test_attach_permission_guards_matches_high_risk_routes_only():
    """T533 · 不在清单内的路由不动。"""
    app = FastAPI()

    @app.post("/api/providers")  # POST 不在清单(只 PUT)
    def post_providers() -> dict:
        return {"ok": True}

    @app.put("/api/providers")
    def put_providers() -> dict:
        return {"ok": True}

    attached = attach_permission_guards(app)
    # 只 PUT /api/providers 应命中
    assert len(attached) == 1
    assert attached[0][0] == "PUT"


def test_high_risk_routes_registered_5_items():
    """T534 · 高风险清单 exactly 5 项(PR-5 契约冻结)。"""
    assert len(HIGH_RISK_ROUTES) == 5
    actions = {a for _, _, a in HIGH_RISK_ROUTES}
    assert actions == {"provider:manage", "canvas:delete", "workspace:admin"}


# ---------------------------------------------------------------------------
# T535 - 使用自定义 PermissionService 注入
# ---------------------------------------------------------------------------


def test_require_permission_uses_injected_service(
    isolated_audit_service, monkeypatch
):
    """T535 · 允许注入 PermissionService(测试专用 · 保留旧签名扩展性)。"""
    monkeypatch.setenv(PERMISSION_ENFORCEMENT_ENV, "enforce")
    # 全放行的自定义 service
    from app.services.permission import DEFAULT_ACTIONS, DEFAULT_ROLES

    custom = PermissionService(
        matrix={
            r: frozenset(DEFAULT_ACTIONS) for r in DEFAULT_ROLES
        }
    )

    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)

    @app.put("/inject")
    def endpoint(
        _guard: None = Depends(require_permission(
            "provider:manage", permission_service=custom
        )),
    ) -> dict:
        return {"ok": True}

    client = TestClient(app)
    # 即使匿名 · 自定义 service 让 viewer 也允许 provider:manage · 200
    resp = client.put("/inject")
    assert resp.status_code == 200
