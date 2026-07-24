"""`IdentityBridge` 单元测试(权限 PR-9 · Wave 3-N.9 Batch 2 主线 B)。

覆盖 T540-T551(12 tests · IdentityBridge.resolve 4 kind 分支矩阵):

- 3 档 flag 语义(off / shadow / enforce)读取
- 4 种 BridgeResolution.kind 分支
- 优先级:x_user_id > owner_hint > anonymous
- authenticated / legacy_bridged / legacy_unmatched / anonymous 各 3+ cases

不落盘 · 不 import middleware · 只测服务层门面。
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest

from app.identity.bridge import (
    BridgeResolution,
    IdentityBridge,
)
from app.identity.middleware import (
    ENFORCE_MODE_ENFORCE,
    ENFORCE_MODE_OFF,
    ENFORCE_MODE_SHADOW,
    IDENTITY_BRIDGE_ENFORCE_ENV,
    get_bridge_enforce_mode,
    is_identity_bridge_enabled,
    mask_sensitive_key,
)
from app.identity.request_context import RequestContext
from app.identity.schema import UserAliasRecord

TS = "2026-07-24T00:00:00+00:00"
WS = "ws-default-00000000-0000-0000-0000-000000000000"


def _alias(
    kind: str,
    key: str,
    alias_id: str = "alias-a",
    user_id: Optional[str] = None,
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
    """轻量 store · 只实现 list_user_aliases。"""

    def __init__(self, aliases: List[UserAliasRecord]) -> None:
        self._aliases = aliases

    def list_user_aliases(self) -> List[UserAliasRecord]:
        return list(self._aliases)

    # 其它方法 · 本测试不消费 · 未实现即可
    def __getattr__(self, item: str) -> Any:
        raise AttributeError(item)


def _ctx(
    *,
    x_user_id: Optional[str] = None,
    legacy_user_key: Optional[str] = None,
    auth_mode: str = "anonymous_or_legacy",
) -> RequestContext:
    return RequestContext(
        request_id="test-rid",
        legacy_user_key=legacy_user_key,
        x_user_id=x_user_id,
        workspace_id=None,
        project_id=None,
        client_id=None,
        ip=None,
        user_agent=None,
        auth_mode=auth_mode,  # type: ignore[arg-type]
    )


@pytest.fixture()
def sample_aliases() -> List[UserAliasRecord]:
    return [
        _alias("x_user_id", "user-a", "alias-1", user_id="uuid-user-a"),
        _alias("x_user_id", "user-b", "alias-2", user_id=None),  # 未 claim
        _alias("conversation_dir", "conv-c", "alias-3", user_id="uuid-user-c"),
        _alias("cookie_user", "Alice", "alias-4", user_id="uuid-user-alice"),
    ]


# ---------------------------------------------------------------------------
# T540: authenticated_user 分支 · x_user_id set
# ---------------------------------------------------------------------------


def test_T540_authenticated_mode_returns_authenticated(sample_aliases: List[UserAliasRecord]) -> None:
    bridge = IdentityBridge(_FakeStore(sample_aliases))  # type: ignore[arg-type]
    ctx = _ctx(x_user_id="uuid-user-a", auth_mode="authenticated_user")
    got = bridge.resolve(ctx)
    assert isinstance(got, BridgeResolution)
    assert got.kind == "authenticated"
    assert got.user_id == "uuid-user-a"
    assert got.fallback_reason is None


# ---------------------------------------------------------------------------
# T541: authenticated_user 分支 · 无 x_user_id → fallback anonymous
# ---------------------------------------------------------------------------


def test_T541_authenticated_mode_without_x_user_id_falls_back(sample_aliases: List[UserAliasRecord]) -> None:
    bridge = IdentityBridge(_FakeStore(sample_aliases))  # type: ignore[arg-type]
    ctx = _ctx(auth_mode="authenticated_user")
    got = bridge.resolve(ctx)
    assert got.kind == "anonymous"
    assert got.user_id is None
    assert got.fallback_reason == "authenticated_mode_without_x_user_id"


# ---------------------------------------------------------------------------
# T542: legacy_bridged · x_user_id 精确匹配 · alias claimed
# ---------------------------------------------------------------------------


def test_T542_x_user_id_matches_claimed_alias(sample_aliases: List[UserAliasRecord]) -> None:
    bridge = IdentityBridge(_FakeStore(sample_aliases))  # type: ignore[arg-type]
    ctx = _ctx(x_user_id="user-a", legacy_user_key="user-a", auth_mode="legacy_alias")
    got = bridge.resolve(ctx)
    assert got.kind == "legacy_bridged"
    assert got.user_id == "uuid-user-a"
    assert got.matched_alias is not None
    assert got.matched_alias["id"] == "alias-1"


# ---------------------------------------------------------------------------
# T543: legacy_unmatched · x_user_id alias 存在但 user_id=None
# ---------------------------------------------------------------------------


def test_T543_x_user_id_alias_exists_but_no_user_id(sample_aliases: List[UserAliasRecord]) -> None:
    bridge = IdentityBridge(_FakeStore(sample_aliases))  # type: ignore[arg-type]
    ctx = _ctx(x_user_id="user-b", legacy_user_key="user-b", auth_mode="legacy_alias")
    got = bridge.resolve(ctx)
    assert got.kind == "legacy_unmatched"
    assert got.user_id is None
    assert got.matched_alias is not None
    assert got.matched_alias["id"] == "alias-2"
    assert got.fallback_reason == "alias_matched_but_no_user_id"


# ---------------------------------------------------------------------------
# T544: legacy_unmatched · x_user_id 无匹配 alias
# ---------------------------------------------------------------------------


def test_T544_x_user_id_no_alias_match(sample_aliases: List[UserAliasRecord]) -> None:
    bridge = IdentityBridge(_FakeStore(sample_aliases))  # type: ignore[arg-type]
    ctx = _ctx(x_user_id="user-unknown", legacy_user_key="user-unknown", auth_mode="legacy_alias")
    got = bridge.resolve(ctx)
    assert got.kind == "legacy_unmatched"
    assert got.user_id is None
    assert got.matched_alias is None
    assert got.fallback_reason == "x_user_id_no_alias_match"


# ---------------------------------------------------------------------------
# T545: legacy_bridged · legacy_user_key 匹配 conversation_dir alias
# ---------------------------------------------------------------------------


def test_T545_legacy_user_key_matches_conversation_dir(sample_aliases: List[UserAliasRecord]) -> None:
    bridge = IdentityBridge(_FakeStore(sample_aliases))  # type: ignore[arg-type]
    ctx = _ctx(legacy_user_key="conv-c", auth_mode="legacy_alias")
    got = bridge.resolve(ctx)
    assert got.kind == "legacy_bridged"
    assert got.user_id == "uuid-user-c"


# ---------------------------------------------------------------------------
# T546: legacy_bridged · legacy_user_key 匹配 cookie_user alias
# ---------------------------------------------------------------------------


def test_T546_legacy_user_key_matches_cookie_user(sample_aliases: List[UserAliasRecord]) -> None:
    bridge = IdentityBridge(_FakeStore(sample_aliases))  # type: ignore[arg-type]
    ctx = _ctx(legacy_user_key="Alice", auth_mode="legacy_alias")
    got = bridge.resolve(ctx)
    assert got.kind == "legacy_bridged"
    assert got.user_id == "uuid-user-alice"


# ---------------------------------------------------------------------------
# T547: legacy_unmatched · legacy_user_key 无匹配
# ---------------------------------------------------------------------------


def test_T547_legacy_user_key_no_alias(sample_aliases: List[UserAliasRecord]) -> None:
    bridge = IdentityBridge(_FakeStore(sample_aliases))  # type: ignore[arg-type]
    ctx = _ctx(legacy_user_key="unknown-key", auth_mode="anonymous_or_legacy")
    got = bridge.resolve(ctx)
    assert got.kind == "legacy_unmatched"
    assert got.user_id is None
    assert got.fallback_reason == "legacy_user_key_no_alias_match"


# ---------------------------------------------------------------------------
# T548: anonymous · 全部 signals 为空
# ---------------------------------------------------------------------------


def test_T548_all_signals_empty_returns_anonymous(sample_aliases: List[UserAliasRecord]) -> None:
    bridge = IdentityBridge(_FakeStore(sample_aliases))  # type: ignore[arg-type]
    ctx = _ctx()
    got = bridge.resolve(ctx)
    assert got.kind == "anonymous"
    assert got.user_id is None
    assert got.fallback_reason is None
    assert got.matched_alias is None


# ---------------------------------------------------------------------------
# T549: 优先级 · x_user_id > legacy_user_key(即使 legacy_user_key 有更好匹配)
# ---------------------------------------------------------------------------


def test_T549_priority_x_user_id_over_legacy_user_key(sample_aliases: List[UserAliasRecord]) -> None:
    # x_user_id 走 kind="x_user_id" 精确匹配路径 · legacy_user_key 走 owner
    # fallback · 即使后者匹配到 cookie_user "Alice" · x_user_id 优先
    bridge = IdentityBridge(_FakeStore(sample_aliases))  # type: ignore[arg-type]
    ctx = _ctx(x_user_id="user-a", legacy_user_key="Alice", auth_mode="legacy_alias")
    got = bridge.resolve(ctx)
    assert got.kind == "legacy_bridged"
    assert got.user_id == "uuid-user-a"  # x_user_id 路径 · 不是 Alice 的 uuid


# ---------------------------------------------------------------------------
# T550: BridgeResolution 是 frozen dataclass · 不可修改
# ---------------------------------------------------------------------------


def test_T550_bridge_resolution_is_frozen() -> None:
    res = BridgeResolution(user_id="x", kind="anonymous")
    with pytest.raises(Exception):
        res.user_id = "y"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# T551: 空 alias 列表 · x_user_id 存在 → legacy_unmatched(without alias match)
# ---------------------------------------------------------------------------


def test_T551_empty_alias_store_x_user_id_unmatched() -> None:
    bridge = IdentityBridge(_FakeStore([]))  # type: ignore[arg-type]
    ctx = _ctx(x_user_id="user-a", legacy_user_key="user-a", auth_mode="legacy_alias")
    got = bridge.resolve(ctx)
    assert got.kind == "legacy_unmatched"
    assert got.user_id is None
    assert got.fallback_reason == "x_user_id_no_alias_match"


# ---------------------------------------------------------------------------
# T552-T555: env flag 三档语义
# ---------------------------------------------------------------------------


def _clear_env() -> Dict[str, Optional[str]]:
    """Return env snapshot for the flag."""
    return {IDENTITY_BRIDGE_ENFORCE_ENV: os.environ.get(IDENTITY_BRIDGE_ENFORCE_ENV)}


def test_T552_flag_default_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(IDENTITY_BRIDGE_ENFORCE_ENV, raising=False)
    assert get_bridge_enforce_mode() == ENFORCE_MODE_OFF
    assert is_identity_bridge_enabled() is False


def test_T553_flag_shadow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(IDENTITY_BRIDGE_ENFORCE_ENV, "shadow")
    assert get_bridge_enforce_mode() == ENFORCE_MODE_SHADOW
    assert is_identity_bridge_enabled() is True


def test_T554_flag_enforce(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(IDENTITY_BRIDGE_ENFORCE_ENV, "ENFORCE")  # case-insensitive
    assert get_bridge_enforce_mode() == ENFORCE_MODE_ENFORCE
    assert is_identity_bridge_enabled() is True


def test_T555_flag_unknown_value_falls_back_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(IDENTITY_BRIDGE_ENFORCE_ENV, "totally-wrong")
    assert get_bridge_enforce_mode() == ENFORCE_MODE_OFF
    assert is_identity_bridge_enabled() is False


# ---------------------------------------------------------------------------
# T556-T557: mask_sensitive_key 边界
# ---------------------------------------------------------------------------


def test_T556_mask_short_string_untouched() -> None:
    assert mask_sensitive_key("Alice") == "Alice"
    assert mask_sensitive_key(None) is None


def test_T557_mask_long_string_middle_mask() -> None:
    long_key = "A" * 50
    masked = mask_sensitive_key(long_key)
    assert masked is not None
    assert masked.startswith("AAA")
    assert masked.endswith("AAA")
    assert "..." in masked
    assert len(masked) < len(long_key)
