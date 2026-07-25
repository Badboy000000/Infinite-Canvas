"""``app.security.csp`` — Content-Security-Policy header 构造骨架(部署 PR-06)。

**承接**:[[40 实施计划/部署与安全治理实施计划与PR清单]] PR-06 · 承接治理方案 M2 前端安全强化。

**定位**:纯 frozen dataclass + 纯函数 · env flag ``CSP_MODE_AWARE_ENABLED`` 默认关闭 ·
**不接** FastAPI middleware(生产切换归后续 PR)。

**骨架契约**:
- ``CspPolicy``:frozen dataclass · 描述一份 CSP 策略
- ``build_csp_policy(mode)``:纯函数 · 三模式返回策略
- ``format_csp_header(policy)``:纯函数 · dataclass → header string
- ``is_csp_mode_aware_enabled()``:env flag 判据

**默认策略**(治理方案 M2):
- ``local_personal``:允许 ``'unsafe-inline'`` + ``'unsafe-eval'``(前端 seam 期兼容旧代码)
- ``intranet_team``:允许 ``'unsafe-inline'``(去掉 unsafe-eval)+ 加 ``img-src 'self' data: /assets /output``
- ``public_team``:严格 · script-src 'self' + nonce 化 + 无 unsafe-inline

**不做**:
- 不接 middleware(生产切换归后续 PR)
- 不做 nonce 生成(需求架构评审)
- 不改现有 static file serving
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Literal, Mapping, Tuple


DeploymentMode = Literal["local_personal", "intranet_team", "public_team"]


_TRUTHY = frozenset({"1", "true", "yes", "on", "TRUE"})
CSP_MODE_AWARE_ENABLED_ENV = "CSP_MODE_AWARE_ENABLED"


def is_csp_mode_aware_enabled() -> bool:
    """``CSP_MODE_AWARE_ENABLED`` 是否已开启(默认 false)。"""
    return os.environ.get(CSP_MODE_AWARE_ENABLED_ENV, "").strip() in _TRUTHY


# 冻结指令顺序(与 CSP Level 3 常见顺序一致)
CSP_DIRECTIVE_ORDER: Tuple[str, ...] = (
    "default-src",
    "script-src",
    "style-src",
    "img-src",
    "font-src",
    "connect-src",
    "frame-src",
    "media-src",
    "object-src",
    "base-uri",
    "form-action",
    "frame-ancestors",
)


@dataclass(frozen=True)
class CspPolicy:
    """CSP 策略 · directive → source list(dict view)。"""

    mode: DeploymentMode
    directives: Mapping[str, Tuple[str, ...]] = field(default_factory=dict)
    report_only: bool = False

    def __post_init__(self) -> None:
        for k in self.directives.keys():
            if k not in CSP_DIRECTIVE_ORDER:
                raise ValueError(
                    f"unknown CSP directive {k!r}; allowed = {CSP_DIRECTIVE_ORDER}"
                )


def _local_personal() -> Mapping[str, Tuple[str, ...]]:
    """本地个人模式 · 保活兼容 · 允许 unsafe-inline / unsafe-eval。"""
    return {
        "default-src": ("'self'",),
        "script-src": ("'self'", "'unsafe-inline'", "'unsafe-eval'"),
        "style-src": ("'self'", "'unsafe-inline'"),
        "img-src": ("'self'", "data:", "blob:", "/assets", "/output"),
        "connect-src": ("'self'",),
        "media-src": ("'self'", "blob:", "/assets", "/output"),
        "object-src": ("'none'",),
        "base-uri": ("'self'",),
        "form-action": ("'self'",),
        "frame-ancestors": ("'self'",),
    }


def _intranet_team() -> Mapping[str, Tuple[str, ...]]:
    """内网团队模式 · 去掉 unsafe-eval · 保留 unsafe-inline 兼容旧 HTML onclick。"""
    return {
        "default-src": ("'self'",),
        "script-src": ("'self'", "'unsafe-inline'"),
        "style-src": ("'self'", "'unsafe-inline'"),
        "img-src": ("'self'", "data:", "blob:", "/assets", "/output"),
        "connect-src": ("'self'",),
        "media-src": ("'self'", "blob:", "/assets", "/output"),
        "object-src": ("'none'",),
        "base-uri": ("'self'",),
        "form-action": ("'self'",),
        "frame-ancestors": ("'self'",),
    }


def _public_team() -> Mapping[str, Tuple[str, ...]]:
    """公开团队模式 · 严格 · script-src 只允许 'self' · 需 nonce/hash 后续 PR 承接。"""
    return {
        "default-src": ("'self'",),
        "script-src": ("'self'",),
        "style-src": ("'self'",),
        "img-src": ("'self'", "data:", "/assets", "/output"),
        "connect-src": ("'self'",),
        "media-src": ("'self'", "/assets", "/output"),
        "object-src": ("'none'",),
        "base-uri": ("'self'",),
        "form-action": ("'self'",),
        "frame-ancestors": ("'none'",),
    }


_BUILDERS = {
    "local_personal": _local_personal,
    "intranet_team": _intranet_team,
    "public_team": _public_team,
}


def build_csp_policy(
    mode: DeploymentMode,
    *,
    report_only: bool = False,
    extra_directives: Mapping[str, Tuple[str, ...]] = {},
) -> CspPolicy:
    """按部署模式构造 CSP 策略。extra_directives 可覆盖默认值(治理期扩展点)。"""
    if mode not in _BUILDERS:
        raise ValueError(f"unknown deployment mode={mode!r}")
    directives = dict(_BUILDERS[mode]())
    for k, v in extra_directives.items():
        if k not in CSP_DIRECTIVE_ORDER:
            raise ValueError(f"unknown CSP directive {k!r}")
        directives[k] = tuple(v)
    return CspPolicy(mode=mode, directives=directives, report_only=report_only)


def format_csp_header(policy: CspPolicy) -> str:
    """按 CSP_DIRECTIVE_ORDER 冻结顺序输出 header string。"""
    parts: list[str] = []
    for directive in CSP_DIRECTIVE_ORDER:
        sources = policy.directives.get(directive)
        if not sources:
            continue
        parts.append(f"{directive} {' '.join(sources)}")
    return "; ".join(parts)


def csp_header_name(policy: CspPolicy) -> str:
    """report_only=True 返回 Report-Only header 名字。"""
    return "Content-Security-Policy-Report-Only" if policy.report_only else "Content-Security-Policy"
