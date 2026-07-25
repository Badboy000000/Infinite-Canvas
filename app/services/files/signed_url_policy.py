"""``app.services.files.signed_url_policy`` — 签名 URL 通道策略骨架
(文件 PR-13)。

**承接**:[[40 实施计划/文件对象与 MinIO 治理实施计划与PR清单]] PR-13。

**定位**:纯 frozen dataclass + 纯函数 · 描述签名 URL 生成/校验的**策略层** ·
**不接** MinIO client · **不签发** 真实 URL(下游 PR 承接)。

**骨架契约**:
- ``SignedUrlIntent``:Literal · get / put(PUT presigned URL 生产默认关闭)
- ``SignedUrlPolicy``:frozen dataclass · 一份策略
- ``build_default_policy(mode, intent)``:三模式 × 2 intent 默认策略
- ``SIGNED_URL_MODE_AWARE``:env flag 默认关闭

**默认策略(与 MinIO Round-2 圆桌决议对齐)**:
- GET presigned TTL:local=60min / intranet=15min / public=10min · 全部开启
- PUT presigned:local=禁 / intranet=禁 / public=禁(Round-2 决议默认关闭)
- 严禁在 URL query 之外的地方拼接 secret
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Literal, Mapping, Tuple


DeploymentMode = Literal["local_personal", "intranet_team", "public_team"]
SignedUrlIntent = Literal["get", "put"]

SIGNED_URL_INTENTS: Tuple[SignedUrlIntent, ...] = ("get", "put")

_TRUTHY = frozenset({"1", "true", "yes", "on"})
SIGNED_URL_MODE_AWARE_ENV = "SIGNED_URL_MODE_AWARE"


def is_signed_url_mode_aware() -> bool:
    return os.environ.get(SIGNED_URL_MODE_AWARE_ENV, "").strip().lower() in _TRUTHY


@dataclass(frozen=True)
class SignedUrlPolicy:
    """一份签名 URL 策略。"""

    mode: DeploymentMode
    intent: SignedUrlIntent
    enabled: bool
    ttl_seconds: int
    require_auth: bool  # 生成签名 URL 前是否要求已认证

    def __post_init__(self) -> None:
        if self.intent not in SIGNED_URL_INTENTS:
            raise ValueError(f"intent={self.intent!r}")
        if self.ttl_seconds < 0:
            raise ValueError("ttl_seconds must be >= 0")


def build_default_policy(mode: DeploymentMode, intent: SignedUrlIntent) -> SignedUrlPolicy:
    if intent == "put":
        # Round-2 圆桌决议:PUT presigned 全模式默认关闭 · 需管理员显式开启
        return SignedUrlPolicy(
            mode=mode, intent=intent, enabled=False, ttl_seconds=15 * 60, require_auth=True,
        )
    # GET
    if mode == "local_personal":
        return SignedUrlPolicy(
            mode=mode, intent="get", enabled=True, ttl_seconds=60 * 60, require_auth=False,
        )
    if mode == "intranet_team":
        return SignedUrlPolicy(
            mode=mode, intent="get", enabled=True, ttl_seconds=15 * 60, require_auth=True,
        )
    if mode == "public_team":
        return SignedUrlPolicy(
            mode=mode, intent="get", enabled=True, ttl_seconds=10 * 60, require_auth=True,
        )
    raise ValueError(f"unknown deployment mode={mode!r}")


def is_ttl_within_limit(policy: SignedUrlPolicy, requested_ttl: int) -> bool:
    """判定请求的 TTL 是否 <= 策略上限。"""
    return 0 < requested_ttl <= policy.ttl_seconds
