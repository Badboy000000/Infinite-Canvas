"""``app.adapters.provider.normalize_helpers`` — normalize_provider 拆解 helper
(Provider PR-06 骨架层)。

**承接**:[[40 实施计划/Provider 适配体系治理实施计划与PR清单]] PR-06 ·
配合 Provider PR-05 CredentialRef · 未来 PR 把 ``main.py::normalize_provider``
拆解为可测试的纯函数。

**定位**:纯函数库 · **不 wrap** ``main.py`` 现有 ``normalize_provider`` ·
只提供**等价语义**的小函数便于契约测试 + 未来切换。

**骨架契约**:
- ``sanitize_display_name(raw)``:剥离控制字符 + 长度限制
- ``normalize_base_url(raw)``:trailing slash 归一 + scheme 校验
- ``ensure_provider_id(raw, fallback)``:合法 id 检查 + fallback 生成
- ``split_capabilities(raw)``:capabilities 展平 · 与 schema_v2 对齐
- ``mask_api_key_for_display(raw)``:前 4 + 后 4 掩码(与 UI 展示层一致)

**不做**:
- 不改 ``main.py::normalize_provider`` 主体逻辑
- 不改 ``/api/providers`` 路由
- 不接入 CredentialRef 落盘(需要 Provider PR-05 + 数据 PR 联合)

见 [[30 治理方案/Provider 适配体系治理方案]] §"配置 Schema v2"。
"""
from __future__ import annotations

import re
from typing import Iterable, Optional, Sequence, Tuple


_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")
_DISPLAY_NAME_MAX = 120
_VALID_PROVIDER_ID_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_\-]{0,63}$")


def sanitize_display_name(raw: object, *, max_length: int = _DISPLAY_NAME_MAX) -> str:
    """剥离控制字符 + trim + 长度上限 · 保持 UTF-8 语义。"""
    if raw is None:
        return ""
    text = str(raw).strip()
    text = _CONTROL_CHAR_RE.sub("", text)
    if len(text) > max_length:
        text = text[:max_length]
    return text


def normalize_base_url(raw: object) -> str:
    """trim + trailing slash 剥离 + scheme whitelist(http/https)。"""
    if raw is None:
        return ""
    text = str(raw).strip()
    if not text:
        return ""
    # scheme 白名单
    lower = text.lower()
    if not (lower.startswith("http://") or lower.startswith("https://")):
        # 治理期允许 file:// 之类的非 http 前缀 · 但主流 provider 只允许 http(s)
        # 骨架层保守拒绝(未来 PR 可扩展)
        return ""
    # 剥掉一个 trailing slash(与 main.py 中 base_url 归一化行为一致)
    while text.endswith("/") and len(text) > 8:  # 保留 https://x 的 slash
        text = text[:-1]
    return text


def ensure_provider_id(raw: object, *, fallback: str = "") -> str:
    """检查 provider id 合法性 · 非法则回退到 fallback(必须也合法)。"""
    if raw is not None:
        text = str(raw).strip()
        if _VALID_PROVIDER_ID_RE.match(text):
            return text
    if fallback and _VALID_PROVIDER_ID_RE.match(fallback):
        return fallback
    raise ValueError(
        f"provider id={raw!r} is invalid and no valid fallback provided "
        f"(fallback={fallback!r}); expected `^[a-zA-Z][a-zA-Z0-9_\\-]{{0,63}}$`"
    )


def split_capabilities(raw: object) -> Tuple[str, ...]:
    """将 capabilities 字段(可能是 list / comma-str / dict)展平为 tuple。"""
    if raw is None:
        return ()
    if isinstance(raw, str):
        parts = [p.strip() for p in raw.split(",")]
        return tuple(p for p in parts if p)
    if isinstance(raw, (list, tuple)):
        return tuple(str(p).strip() for p in raw if str(p).strip())
    if isinstance(raw, dict):
        # 兼容 {cap_name: bool} 形态
        return tuple(k for k, v in raw.items() if v)
    return ()


def mask_api_key_for_display(raw: object, *, keep: int = 4) -> str:
    """前 keep + 后 keep 掩码 · 长度不足则全部掩码。

    Examples:
        >>> mask_api_key_for_display("sk-abcdef1234567890xyz")
        'sk-a...0xyz'
        >>> mask_api_key_for_display("short")
        '***'
    """
    if raw is None:
        return ""
    text = str(raw)
    if len(text) <= keep * 2 + 3:
        return "***" if text else ""
    return f"{text[:keep]}...{text[-keep:]}"
