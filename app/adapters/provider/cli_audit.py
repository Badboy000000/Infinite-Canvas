"""``app.adapters.provider.cli_audit`` — CLI Provider 强审计模式契约
(Provider PR-11 骨架)。

**承接**:[[40 实施计划/Provider 适配体系治理实施计划与PR清单]] PR-11 · 承接
治理方案 M3 CLI Provider 契约化 + 强审计。

**定位**:纯 frozen dataclass + 纯函数 · 描述 CLI Provider 调用的**审计快照** ·
**不接** subprocess · **不接** audit 落盘(归下游 PR)。

**契约**:
- ``CliProviderMode``:Literal · disabled / shared_system / per_user
- ``CliAuditSnapshot``:frozen dataclass · 每次调用的审计视图
- ``build_cli_mode_matrix(deployment_mode)``:纯函数 · 三部署模式 × 3 provider
- ``sanitize_cli_argv(argv)``:纯函数 · 掩码可能敏感的 CLI 参数

**部署模式 × Provider 矩阵**(治理方案硬约束):

- local_personal:全 per_user 允许(dev 便利)
- intranet_team:jimeng=shared_system / gemini=shared_system / codex=per_user
- public_team:jimeng=disabled(高风险)· gemini=shared_system · codex=shared_system
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Literal, Mapping, Optional, Sequence, Tuple


DeploymentMode = Literal["local_personal", "intranet_team", "public_team"]
CliProviderMode = Literal["disabled", "shared_system", "per_user"]
CliProvider = Literal["jimeng", "gemini_cli", "codex_cli"]

CLI_PROVIDERS: Tuple[CliProvider, ...] = ("jimeng", "gemini_cli", "codex_cli")
CLI_MODES: Tuple[CliProviderMode, ...] = ("disabled", "shared_system", "per_user")


@dataclass(frozen=True)
class CliAuditSnapshot:
    """一次 CLI Provider 调用的审计视图。"""

    provider: CliProvider
    mode: CliProviderMode
    caller_kind: str  # "user" / "background_task" / "system"
    caller_id: Optional[str]
    argv_masked: Tuple[str, ...]
    exit_code: Optional[int]
    elapsed_ms: Optional[int]

    def __post_init__(self) -> None:
        if self.provider not in CLI_PROVIDERS:
            raise ValueError(f"provider={self.provider!r} not in {CLI_PROVIDERS}")
        if self.mode not in CLI_MODES:
            raise ValueError(f"mode={self.mode!r} not in {CLI_MODES}")
        if self.mode == "disabled":
            raise ValueError(
                "CliAuditSnapshot must not be produced when mode=disabled "
                "(caller should refuse before dispatch)"
            )
        # argv 严禁承载敏感 raw token
        for token in self.argv_masked:
            lowered = token.lower()
            if "authorization" in lowered or "bearer " in lowered:
                raise ValueError("argv_masked leaked credential-like token")


def build_cli_mode_matrix(
    deployment_mode: DeploymentMode,
) -> Mapping[CliProvider, CliProviderMode]:
    """按部署模式返回 CLI provider 模式表。"""
    if deployment_mode == "local_personal":
        return {
            "jimeng": "per_user",
            "gemini_cli": "per_user",
            "codex_cli": "per_user",
        }
    if deployment_mode == "intranet_team":
        return {
            "jimeng": "shared_system",
            "gemini_cli": "shared_system",
            "codex_cli": "per_user",
        }
    if deployment_mode == "public_team":
        return {
            "jimeng": "disabled",       # 高风险 · 治理方案硬约束
            "gemini_cli": "shared_system",
            "codex_cli": "shared_system",
        }
    raise ValueError(f"unknown deployment mode={deployment_mode!r}")


# 掩码规则:与 argv 中疑似 token 的字符串统一替换
_TOKEN_RE = re.compile(r"(?i)(--?(?:api[_-]?key|token|authorization|secret|key)[=\s]+)(\S+)")
_LONG_HEX_RE = re.compile(r"[A-Za-z0-9_\-]{24,}")


def sanitize_cli_argv(argv: Sequence[str], *, marker: str = "***") -> Tuple[str, ...]:
    """扫描 argv · 掩码疑似密钥参数。"""
    out: list[str] = []
    for token in argv:
        # 完全命中 `--api-key=xxx` 或 `--token xxx`
        replaced = _TOKEN_RE.sub(lambda m: f"{m.group(1)}{marker}", token)
        # 独立的长哈希/十六进制字符串
        if replaced == token and len(token) >= 24 and _LONG_HEX_RE.fullmatch(token):
            replaced = marker
        out.append(replaced)
    return tuple(out)


def resolve_effective_mode(
    deployment_mode: DeploymentMode,
    provider: CliProvider,
) -> CliProviderMode:
    """便捷入口 · 部署模式 + provider → 实际模式。"""
    return build_cli_mode_matrix(deployment_mode)[provider]
