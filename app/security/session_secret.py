"""``app.security.session_secret`` — SESSION_SECRET 启动强校验骨架(部署 PR-08)。

**承接**:[[40 实施计划/部署与安全治理实施计划与PR清单]] PR-08 · 承接治理方案 M1
`local_personal / intranet_team / public_team` 三模式启动强校验。

**定位**:纯函数库 · 校验 ``IC_SESSION_SECRET`` / ``IC_CSRF_SECRET`` 的强度 ·
**不接** startup hook(归下游 PR 承接接入 main.py 启动流程)。

**骨架契约**:
- ``SessionSecretPolicy``:frozen dataclass · 描述某模式下 secret 强度要求
- ``SecretValidationError``:异常类型
- ``validate_secret(secret, mode, kind)``:主入口 · 返回 SecretValidationReport
- ``build_policy(mode)``:纯函数 · 按 mode 返回 policy
- ``SESSION_SECRET_STARTUP_ENFORCE``:env flag 默认关闭

**校验规则**:
- ``local_personal``:长度 ≥ 16(dev 环境宽松)· 允许 dummy 值
- ``intranet_team``:长度 ≥ 32 · 拒绝 dummy 值(dev / test / xxx)
- ``public_team``:长度 ≥ 64 · 熵值检查(不可全字母 / 全数字)· 拒绝 dummy 值

**不做**:
- 不接 startup hook
- 不接 config loading(归下游 PR)
- 不生成 secret(需运维手工)
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Literal, Tuple


DeploymentMode = Literal["local_personal", "intranet_team", "public_team"]

SecretKind = Literal["session", "csrf"]


_TRUTHY = frozenset({"1", "true", "yes", "on"})
SESSION_SECRET_STARTUP_ENFORCE_ENV = "SESSION_SECRET_STARTUP_ENFORCE"


def is_session_secret_startup_enforce_enabled() -> bool:
    return os.environ.get(SESSION_SECRET_STARTUP_ENFORCE_ENV, "").strip().lower() in _TRUTHY


class SecretValidationError(ValueError):
    """secret 强度不达标。"""


# 弱值黑名单(小写子串匹配)· 治理期观察扩展
_DUMMY_SECRETS = (
    "dev",
    "test",
    "default",
    "changeme",
    "secret123",
    "password",
    "xxx",
    "example",
    "dummy",
    "placeholder",
)

_LETTERS_ONLY_RE = re.compile(r"^[A-Za-z]+$")
_DIGITS_ONLY_RE = re.compile(r"^[0-9]+$")


@dataclass(frozen=True)
class SessionSecretPolicy:
    """按部署模式的 secret 强度策略。"""

    mode: DeploymentMode
    min_length: int
    reject_dummy_values: bool
    entropy_check: bool  # 拒绝全字母 / 全数字


def build_policy(mode: DeploymentMode) -> SessionSecretPolicy:
    if mode == "local_personal":
        return SessionSecretPolicy(
            mode=mode, min_length=16, reject_dummy_values=False, entropy_check=False
        )
    if mode == "intranet_team":
        return SessionSecretPolicy(
            mode=mode, min_length=32, reject_dummy_values=True, entropy_check=False
        )
    if mode == "public_team":
        return SessionSecretPolicy(
            mode=mode, min_length=64, reject_dummy_values=True, entropy_check=True
        )
    raise ValueError(f"unknown deployment mode={mode!r}")


@dataclass(frozen=True)
class SecretValidationReport:
    """一次校验的结果 view · 不包含 secret 原文。"""

    kind: SecretKind
    mode: DeploymentMode
    ok: bool
    length: int
    reasons: Tuple[str, ...] = field(default_factory=tuple)


def validate_secret(
    secret: str,
    *,
    mode: DeploymentMode,
    kind: SecretKind,
) -> SecretValidationReport:
    """校验 secret · 返回 report(不抛异常 · 由调用方决定是否 raise)。"""
    policy = build_policy(mode)
    reasons: list[str] = []
    length = len(secret or "")

    if length < policy.min_length:
        reasons.append(
            f"length {length} < min_length {policy.min_length} for mode={mode}"
        )
    if policy.reject_dummy_values:
        lowered = (secret or "").lower()
        for dummy in _DUMMY_SECRETS:
            if dummy in lowered:
                reasons.append(f"contains dummy substring {dummy!r}")
                break
    if policy.entropy_check and secret:
        if _LETTERS_ONLY_RE.match(secret):
            reasons.append("all-letters is not sufficient entropy for public_team")
        elif _DIGITS_ONLY_RE.match(secret):
            reasons.append("all-digits is not sufficient entropy for public_team")

    return SecretValidationReport(
        kind=kind,
        mode=mode,
        ok=len(reasons) == 0,
        length=length,
        reasons=tuple(reasons),
    )


def enforce_secret(secret: str, *, mode: DeploymentMode, kind: SecretKind) -> None:
    """校验 + 抛异常 · 用于 startup fail-fast。"""
    report = validate_secret(secret, mode=mode, kind=kind)
    if not report.ok:
        # 严禁在异常消息里回显 secret 原文
        raise SecretValidationError(
            f"{kind} secret failed validation for mode={mode}: "
            f"length={report.length} · {'; '.join(report.reasons)}"
        )
