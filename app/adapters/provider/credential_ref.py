"""``app.adapters.provider.credential_ref`` — CredentialRef 分级抽象
(Provider PR-05 骨架层)。

**承接**:[[40 实施计划/Provider 适配体系治理实施计划与PR清单]] PR-05 · **CB-02
长期根治**([[70 开发过程跟踪/缺陷追踪/CB-02 - PUT providers 422 error
回显 request body 含密钥]] 的架构侧根治方案)。

**定位**:纯 frozen dataclass + 纯函数 · 描述 provider 凭据的**引用**(而非
明文本体)。凭据分为 3 级:

- ``L0_INLINE``:明文 · **禁止落盘 / 禁止入错误响应** · 只允许出现在 request → normalize → adapter dispatch 内的短暂内存中
- ``L1_ENV``:环境变量引用(``env://VAR_NAME``)· 允许持久化(仅名字 · 无明文)
- ``L2_SECRET_STORE``:vault 引用(``vault://path/to/secret``)· 允许持久化(仅路径)
- ``L3_FINGERPRINT``:只保留指纹(如 sha256[:8])· 展示层唯一允许持有的形态

**契约核心**:
- ``CredentialLevel``:Literal[L0..L3] 分级枚举
- ``CredentialRef``:frozen dataclass · 只承载 level + reference + fingerprint
- ``build_credential_ref_from_inline(secret)``:构造 L3 指纹 + 内存 L0
- ``strip_credential_from_error_body(body)``:剔除错误回显中的凭据(CB-02 长期根治)
- ``ProviderCredentialContract``:契约测试消费入口

**硬约束**(与 [[30 治理方案/Provider 适配体系治理方案]] §"凭据分级抽象" 对齐):
- L0 严禁进 JSON serialization / repr / log / str
- L1/L2 引用形态可持久化 · 但资源名(env var 名 / vault path)必须走 audit 白名单
- L3 指纹必须 sha256(secret)[:8] · 严禁承载原文
- 与 [[部署与安全治理方案]] `redaction` 层配合:redaction 是黑名单兜底 · 本层是白名单结构化

**不做**:
- 不改 ``normalize_provider()`` 中的 api_key 处理
- 不改 ``/api/providers`` GET/POST/PUT 路由
- 不接 vault client(vault path 只是标识符)
- 不做 rotation(归后续 PR)
"""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from typing import Literal, Mapping, Optional, Tuple


CredentialLevel = Literal["L0_INLINE", "L1_ENV", "L2_SECRET_STORE", "L3_FINGERPRINT"]

CREDENTIAL_LEVELS: Tuple[CredentialLevel, ...] = (
    "L0_INLINE",
    "L1_ENV",
    "L2_SECRET_STORE",
    "L3_FINGERPRINT",
)

# 可持久化的分级(L0 必须过滤掉)
PERSISTABLE_LEVELS: Tuple[CredentialLevel, ...] = (
    "L1_ENV",
    "L2_SECRET_STORE",
    "L3_FINGERPRINT",
)

# env var 名 whitelist 前缀(与 API/.env.example 命名规范一致)
_ENV_VAR_ALLOWED_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")
_VAULT_PATH_ALLOWED_PATTERN = re.compile(r"^[a-zA-Z0-9_\-/.]+$")


@dataclass(frozen=True)
class CredentialRef:
    """凭据引用 · 只承载分级 + 引用 + 指纹 · **不承载明文**。"""

    level: CredentialLevel
    reference: str  # env var name / vault path / fingerprint literal
    fingerprint: Optional[str] = None  # sha256(secret)[:8] · L1/L2 可能没有
    key_updated_at: Optional[str] = None  # ISO 8601

    def __post_init__(self) -> None:
        if self.level not in CREDENTIAL_LEVELS:
            raise ValueError(f"level={self.level!r} not in {CREDENTIAL_LEVELS}")
        if not self.reference:
            raise ValueError("reference must not be empty")
        # L0 严禁被构造出可持久化的 ref · 用非空 reference 就属于治理违规
        if self.level == "L0_INLINE":
            # 允许构造 · 但下游 to_persistable() 必须拒绝
            pass
        elif self.level == "L1_ENV":
            if not _ENV_VAR_ALLOWED_PATTERN.match(self.reference):
                raise ValueError(
                    f"L1_ENV reference must be UPPER_SNAKE_CASE env var name; got {self.reference!r}"
                )
        elif self.level == "L2_SECRET_STORE":
            if not _VAULT_PATH_ALLOWED_PATTERN.match(self.reference):
                raise ValueError(
                    f"L2_SECRET_STORE reference must be safe path; got {self.reference!r}"
                )

    # ---- 显式接口 · 拒绝把明文暴露到 __repr__ / __str__ / json -------
    def __repr__(self) -> str:  # pragma: no cover - 纯展示层
        return (
            f"CredentialRef(level={self.level!r}, "
            f"reference={self.reference!r}, fingerprint={self.fingerprint!r})"
        )

    def to_persistable(self) -> Mapping[str, str]:
        """返回可以落盘的 dict view · L0_INLINE 会抛错。"""
        if self.level == "L0_INLINE":
            raise ValueError(
                "L0_INLINE credentials must never be persisted; "
                "wrap the secret in an env / vault reference first"
            )
        payload = {"level": self.level, "reference": self.reference}
        if self.fingerprint:
            payload["fingerprint"] = self.fingerprint
        if self.key_updated_at:
            payload["key_updated_at"] = self.key_updated_at
        return payload


def compute_fingerprint(secret: str, *, length: int = 8) -> str:
    """sha256(secret)[:length] · 用于 L3 展示 + 幂等 dedup。"""
    if not secret:
        return ""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()[:length]


def build_credential_ref_from_inline(
    secret: str,
    *,
    key_updated_at: Optional[str] = None,
) -> CredentialRef:
    """从内存中的明文构造 L3 指纹 ref · 严禁把 secret 存进 reference 字段。"""
    fp = compute_fingerprint(secret)
    return CredentialRef(
        level="L3_FINGERPRINT",
        reference=f"fp_{fp}",
        fingerprint=fp,
        key_updated_at=key_updated_at,
    )


# ---------------------------------------------------------------------------
# CB-02 长期根治:错误回显剔除
# ---------------------------------------------------------------------------

# request body 中已知的 provider 密钥字段名(小写匹配)
_CREDENTIAL_FIELD_NAMES = frozenset({
    "api_key",
    "apikey",
    "access_key",
    "access_key_id",
    "secret_access_key",
    "wallet_api_key",
    "authorization",
    "bearer",
    "token",
    "refresh_token",
    "client_secret",
})


def strip_credential_from_error_body(
    body: Mapping[str, object],
    *,
    marker: str = "***REDACTED***",
) -> Mapping[str, object]:
    """深度剔除错误响应 body 中的凭据字段(CB-02 长期根治核心函数)。

    - 顶层 + 一层嵌套 dict/list 都会被扫描
    - 匹配到已知凭据字段名 → 替换为 marker
    - 未匹配的字段原样透传
    """
    def _scrub(obj):
        if isinstance(obj, dict):
            out = {}
            for k, v in obj.items():
                if str(k).lower() in _CREDENTIAL_FIELD_NAMES:
                    out[k] = marker
                else:
                    out[k] = _scrub(v)
            return out
        if isinstance(obj, list):
            return [_scrub(x) for x in obj]
        return obj
    return _scrub(body)  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# 契约测试消费入口
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProviderCredentialContract:
    """描述一个 provider 类型允许的凭据分级(契约测试消费入口)。"""

    protocol: str
    default_level: CredentialLevel = "L3_FINGERPRINT"
    persistable_only: bool = True  # 是否只允许 PERSISTABLE_LEVELS

    def is_level_allowed(self, level: CredentialLevel) -> bool:
        if self.persistable_only:
            return level in PERSISTABLE_LEVELS
        return level in CREDENTIAL_LEVELS
