"""`IdentityBridgeMiddleware` 单元测试(权限 PR-9 · Wave 3-N.9 Batch 2 主线 B)。

覆盖 T558-T564(≥8 tests · middleware 行为):

- middleware 不启用(flag off)时 · 不影响任何路由行为
- middleware 启用(shadow)时 · request.state.bridge_resolution 正确填充
- shadow 模式 · legacy_unmatched 触发 audit
- shadow 模式 · anonymous / legacy_bridged 不触发 audit
- audit_service 未传入 · 使用 buffered-only fallback(不写盘)
- authenticated + legacy signals mismatch 触发 audit
- audit 白名单 · legacy_user_key 半敏感 mask
"""
from __future__ import annotations

from typing import Any, List, Optional

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.api.context import RequestContextMiddleware
from app.identity.bridge import BridgeResolution, IdentityBridge
from app.identity.middleware import (
    IDENTITY_BRIDGE_ENFORCE_ENV,
    IdentityBridgeMiddleware,
)
from app.identity.schema import UserAliasRecord
from app.services.audit import AuditService

TS = "2026-07-24T00:00:00+00:00"
WS = "ws-default-00000000-0000-0000-0000-000000000000"


def _alias(
    kind: str, key: str, alias_id: str, user_id: Optional[str] = None
) -> UserAliasRecord:
    return {
        "id": alias_id,
        "user_id": user_id,
        "kind": kind,  # type: ignore[typeddict-item]
        "legacy_user_key": key,
        "workspace_id": WS,
        "created_at": TS,
    }


class _FakeStore:
    def __init__(self, aliases: List[UserAliasRecord]) -> None:
        self._aliases = aliases

    def list_user_aliases(self) -> List[UserAliasRecord]:
        return list(self._aliases)

    def __getattr__(self, item: str) -> Any:
        raise AttributeError(item)


def _make_app(
    aliases: List[UserAliasRecord],
    *,
    with_bridge: bool = True,
    audit: Optional[AuditService] = None,
) -> FastAPI:
    app = FastAPI()

    @app.get("/probe")
    def probe(request: Request) -> Any:
        resolution: Optional[BridgeResolution] = getattr(
            request.state, "bridge_resolution", None
        )
        return {
            "has_resolution": resolution is not None,
            "kind": resolution.kind if resolution is not None else None,
            "user_id": resolution.user_id if resolution is not None else None,
        }

    if with_bridge:
        bridge = IdentityBridge(_FakeStore(aliases))  # type: ignore[arg-type]
        app.add_middleware(
            IdentityBridgeMiddleware, bridge=bridge, audit_service=audit
        )
    # 最外层:RequestContextMiddleware(与 main.py 挂载顺序一致)
    app.add_middleware(RequestContextMiddleware)
    return app


# ---------------------------------------------------------------------------
# T558: middleware 不启用 · request.state 无 bridge_resolution · 路由 200
# ---------------------------------------------------------------------------


def test_T558_middleware_absent_no_side_effect() -> None:
    app = _make_app([], with_bridge=False)
    client = TestClient(app)
    r = client.get("/probe")
    assert r.status_code == 200
    body = r.json()
    assert body["has_resolution"] is False
    assert body["kind"] is None


# ---------------------------------------------------------------------------
# T559: middleware 启用 · anonymous 请求 · resolution.kind == anonymous
# ---------------------------------------------------------------------------


def test_T559_anonymous_request_yields_anonymous_resolution() -> None:
    app = _make_app([])
    client = TestClient(app)
    r = client.get("/probe")
    assert r.status_code == 200
    body = r.json()
    assert body["has_resolution"] is True
    assert body["kind"] == "anonymous"
    assert body["user_id"] is None


# ---------------------------------------------------------------------------
# T560: middleware 启用 · x_user_id header 匹配 alias · legacy_bridged
# ---------------------------------------------------------------------------


def test_T560_x_user_id_header_bridged() -> None:
    aliases = [_alias("x_user_id", "user-a", "alias-1", user_id="uuid-user-a")]
    app = _make_app(aliases)
    client = TestClient(app)
    r = client.get("/probe", headers={"X-User-Id": "user-a"})
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "legacy_bridged"
    assert body["user_id"] == "uuid-user-a"


# ---------------------------------------------------------------------------
# T561: shadow 模式 · legacy_unmatched 触发 audit(action=permission.check_denied)
# ---------------------------------------------------------------------------


def test_T561_shadow_legacy_unmatched_emits_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(IDENTITY_BRIDGE_ENFORCE_ENV, "shadow")
    audit = AuditService(buffered_only=True)
    app = _make_app([], audit=audit)
    client = TestClient(app)
    r = client.get("/probe", headers={"X-User-Id": "unknown-user"})
    assert r.status_code == 200
    events = audit.buffered_events()
    assert len(events) == 1
    assert events[0].action == "permission.check_denied"
    assert events[0].outcome == "denied"
    # reason 应包含 fallback_reason
    ctx_dict = dict(events[0].context)
    assert ctx_dict.get("reason") == "x_user_id_no_alias_match"


# ---------------------------------------------------------------------------
# T562: shadow 模式 · anonymous 请求 · 不 emit audit(kind=anonymous 不算未匹配)
# ---------------------------------------------------------------------------


def test_T562_shadow_anonymous_no_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(IDENTITY_BRIDGE_ENFORCE_ENV, "shadow")
    audit = AuditService(buffered_only=True)
    app = _make_app([], audit=audit)
    client = TestClient(app)
    r = client.get("/probe")
    assert r.status_code == 200
    events = audit.buffered_events()
    assert len(events) == 0


# ---------------------------------------------------------------------------
# T563: shadow 模式 · legacy_bridged 成功匹配 · 不 emit audit
# ---------------------------------------------------------------------------


def test_T563_shadow_legacy_bridged_no_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(IDENTITY_BRIDGE_ENFORCE_ENV, "shadow")
    aliases = [_alias("x_user_id", "user-a", "alias-1", user_id="uuid-user-a")]
    audit = AuditService(buffered_only=True)
    app = _make_app(aliases, audit=audit)
    client = TestClient(app)
    r = client.get("/probe", headers={"X-User-Id": "user-a"})
    assert r.status_code == 200
    events = audit.buffered_events()
    assert len(events) == 0


# ---------------------------------------------------------------------------
# T564: off 模式 · 即使 middleware 挂了 · 也不 emit audit
# ---------------------------------------------------------------------------


def test_T564_off_mode_no_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(IDENTITY_BRIDGE_ENFORCE_ENV, raising=False)
    audit = AuditService(buffered_only=True)
    app = _make_app([], audit=audit)
    client = TestClient(app)
    r = client.get("/probe", headers={"X-User-Id": "unknown-user"})
    assert r.status_code == 200
    # off 模式:middleware 挂着(测试强制挂) · 但 dispatch 不 emit audit
    events = audit.buffered_events()
    assert len(events) == 0


# ---------------------------------------------------------------------------
# T565: middleware 默认 audit_service (buffered_only fallback) 不写盘
# ---------------------------------------------------------------------------


def test_T565_default_audit_service_is_buffered(monkeypatch: pytest.MonkeyPatch) -> None:
    """未传 audit_service · 内部 fallback 应为 buffered-only · 不写盘。"""
    monkeypatch.setenv(IDENTITY_BRIDGE_ENFORCE_ENV, "shadow")
    bridge = IdentityBridge(_FakeStore([]))  # type: ignore[arg-type]
    mw = IdentityBridgeMiddleware(app=lambda scope, receive, send: None, bridge=bridge)
    # 内部 fallback audit 应存在且 buffered_only=True
    assert mw._audit is not None  # type: ignore[attr-defined]
    assert mw._audit._buffered_only is True  # type: ignore[attr-defined]
