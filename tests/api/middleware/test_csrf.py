"""CSRF 双提交 token middleware 契约测试(权限 PR-5 · Wave 3-N.9 Batch 2 主线 A)。

覆盖:
- CSRF_ENABLED=false 全直通(默认)
- CSRF_ENABLED=true 时:
  * GET/HEAD/OPTIONS 直通
  * 写方法 + 白名单路径直通
  * 写方法 + 无 header → 403 csrf_missing_header
  * 写方法 + header 但无 cookie → 403 csrf_missing_cookie
  * 写方法 + 不匹配 → 403 csrf_mismatch
  * 写方法 + 匹配 → 200
- ensure_csrf_cookie 首次响应 SET-Cookie
- 首次 GET 后再拿 cookie · 用它构造合法 POST
- 错误响应零 token 泄漏
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.middleware.csrf import (
    CSRF_COOKIE_NAME,
    CSRF_ENV_FLAG,
    CSRF_HEADER_NAME,
    CSRFMiddleware,
    generate_csrf_token,
    is_csrf_enabled,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_csrf_env(monkeypatch):
    monkeypatch.delenv(CSRF_ENV_FLAG, raising=False)
    yield


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(CSRFMiddleware)

    @app.get("/ping")
    def ping() -> dict:
        return {"ok": True}

    @app.post("/write")
    def write() -> dict:
        return {"code": "ok"}

    @app.put("/api/providers")
    def put_providers() -> dict:
        return {"providers": []}

    @app.post("/api/auth/login")
    def login() -> dict:
        return {"code": "ok"}

    @app.post("/api/auth/logout")
    def logout() -> dict:
        return {"code": "ok"}

    @app.get("/api/whoami")
    def whoami() -> dict:
        return {"principal_kind": "anonymous"}

    return app


# ---------------------------------------------------------------------------
# T540 - flag off:全直通(即使不带 header)
# ---------------------------------------------------------------------------


def test_csrf_flag_off_passes_write_without_header(monkeypatch):
    """T540 · CSRF_ENABLED 未设 · 写方法直通(等价旧行为)。"""
    monkeypatch.delenv(CSRF_ENV_FLAG, raising=False)
    client = TestClient(_build_app())
    resp = client.post("/write")
    assert resp.status_code == 200
    # 但仍设 Cookie 便于前端渐进
    assert CSRF_COOKIE_NAME in resp.cookies or "set-cookie" in {
        k.lower() for k in resp.headers.keys()
    }


def test_is_csrf_enabled_defaults_false(monkeypatch):
    """T541 · env flag 默认值。"""
    monkeypatch.delenv(CSRF_ENV_FLAG, raising=False)
    assert not is_csrf_enabled()


# ---------------------------------------------------------------------------
# T542-544 - flag on · 读方法直通
# ---------------------------------------------------------------------------


def test_csrf_flag_on_get_passes_through(monkeypatch):
    """T542 · flag on + GET → 直通(不校验)· 并 SET-Cookie。"""
    monkeypatch.setenv(CSRF_ENV_FLAG, "true")
    client = TestClient(_build_app())
    resp = client.get("/ping")
    assert resp.status_code == 200
    # 首次响应带 Set-Cookie
    set_cookie = resp.headers.get("set-cookie", "")
    assert f"{CSRF_COOKIE_NAME}=" in set_cookie


def test_csrf_flag_on_head_passes_through(monkeypatch):
    """T543 · flag on + HEAD 直通(未注册 HEAD 路由返回 405 · 但不是 403 csrf)。"""
    monkeypatch.setenv(CSRF_ENV_FLAG, "true")
    monkeypatch.setenv("CSRF_COOKIE_SECURE", "false")
    client = TestClient(_build_app())
    resp = client.request("HEAD", "/ping")
    # HEAD 未注册 → 405 · 但不是 403(说明 CSRF middleware 未拦截)
    assert resp.status_code != 403


def test_csrf_flag_on_whitelist_path_bypasses_check(monkeypatch):
    """T544 · flag on + /api/auth/login 直通(登录本身要 SET Cookie)。"""
    monkeypatch.setenv(CSRF_ENV_FLAG, "true")
    client = TestClient(_build_app())
    resp = client.post("/api/auth/login")
    assert resp.status_code == 200
    resp2 = client.post("/api/auth/logout")
    assert resp2.status_code == 200


# ---------------------------------------------------------------------------
# T545-547 - flag on · 写方法拒绝分支
# ---------------------------------------------------------------------------


def test_csrf_write_no_header_rejects_403(monkeypatch):
    """T545 · flag on + POST 无 X-CSRF-Token → 403 csrf_missing_header。"""
    monkeypatch.setenv(CSRF_ENV_FLAG, "true")
    client = TestClient(_build_app())
    resp = client.post("/write")
    assert resp.status_code == 403
    body = resp.json()
    assert body["code"] == "csrf_missing_header"
    # 错误消息零 token 泄漏
    assert "token" not in body["message"].lower() or "CSRF" in body["message"]


def test_csrf_write_no_cookie_rejects_403(monkeypatch):
    """T546 · flag on + header 但无 cookie → 403 csrf_missing_cookie。"""
    monkeypatch.setenv(CSRF_ENV_FLAG, "true")
    client = TestClient(_build_app())
    resp = client.post("/write", headers={CSRF_HEADER_NAME: "some-token"})
    assert resp.status_code == 403
    body = resp.json()
    assert body["code"] == "csrf_missing_cookie"


def test_csrf_write_mismatch_rejects_403(monkeypatch):
    """T547 · flag on + cookie ≠ header → 403 csrf_mismatch。"""
    monkeypatch.setenv(CSRF_ENV_FLAG, "true")
    client = TestClient(_build_app())
    client.cookies.set(CSRF_COOKIE_NAME, "aaaa")
    resp = client.post(
        "/write", headers={CSRF_HEADER_NAME: "bbbb"}
    )
    assert resp.status_code == 403
    body = resp.json()
    assert body["code"] == "csrf_mismatch"
    # 零 token 泄漏 · 响应 body 不含 aaaa / bbbb 值
    text = resp.text
    assert "aaaa" not in text and "bbbb" not in text


# ---------------------------------------------------------------------------
# T548-549 - flag on · 匹配通过
# ---------------------------------------------------------------------------


def test_csrf_write_matching_token_passes(monkeypatch):
    """T548 · flag on + cookie==header → 通过。"""
    monkeypatch.setenv(CSRF_ENV_FLAG, "true")
    client = TestClient(_build_app())
    token = generate_csrf_token()
    client.cookies.set(CSRF_COOKIE_NAME, token)
    resp = client.post(
        "/write", headers={CSRF_HEADER_NAME: token}
    )
    assert resp.status_code == 200
    assert resp.json() == {"code": "ok"}


def test_csrf_full_flow_get_then_post_with_extracted_cookie(monkeypatch):
    """T549 · 真实前端流程:先 GET 拿到 cookie → 用它 POST 通过。"""
    monkeypatch.setenv(CSRF_ENV_FLAG, "true")
    monkeypatch.setenv("CSRF_COOKIE_SECURE", "false")
    client = TestClient(_build_app())
    # 步骤 1:GET 拿 cookie
    resp = client.get("/ping")
    token = resp.cookies.get(CSRF_COOKIE_NAME)
    assert token, f"expected {CSRF_COOKIE_NAME} cookie in GET response"
    # 步骤 2:POST 带上 header
    resp2 = client.post(
        "/write", headers={CSRF_HEADER_NAME: token}
    )
    assert resp2.status_code == 200


# ---------------------------------------------------------------------------
# T550 - 高风险路径(/api/providers PUT)也校验 CSRF
# ---------------------------------------------------------------------------


def test_csrf_put_providers_requires_token(monkeypatch):
    """T550 · flag on + PUT /api/providers 无 token → 403。"""
    monkeypatch.setenv(CSRF_ENV_FLAG, "true")
    client = TestClient(_build_app())
    resp = client.put("/api/providers", json=[])
    assert resp.status_code == 403


def test_csrf_cookie_secure_defaults_true(monkeypatch):
    """T551 · CSRF_COOKIE_SECURE 未显式设 → cookie 带 Secure(生产默认强)。"""
    monkeypatch.setenv(CSRF_ENV_FLAG, "true")
    monkeypatch.delenv("CSRF_COOKIE_SECURE", raising=False)
    client = TestClient(_build_app())
    resp = client.get("/ping")
    set_cookie = resp.headers.get("set-cookie", "")
    assert "Secure" in set_cookie
    assert "samesite=lax" in set_cookie.lower()


def test_csrf_token_generation_unique():
    """T552 · generate_csrf_token 每次唯一 · 长度 ≥ 32 字符。"""
    tokens = {generate_csrf_token() for _ in range(50)}
    assert len(tokens) == 50
    for t in tokens:
        assert len(t) >= 32
