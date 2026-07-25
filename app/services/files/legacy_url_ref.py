"""``app.services.files.legacy_url_ref`` — LegacyUrlRef 兼容层查询函数骨架
(文件 PR-5)。

**承接**:[[40 实施计划/文件对象与 MinIO 治理实施计划与PR清单]] PR-5 · M2 加固。

**定位**:纯函数 · 消费 `legacy_url_refs` DDL 表(数据 PR-18 已就位) · 提供
从 legacy URL → FileObject / FileRef 的反向查询能力 · **不接入 FastAPI 路由**
(生产切换归后续 PR-12+ MinIO 灰度承接)。

**骨架契约**:
- ``normalize_legacy_url(url)``:URL 规范化 · 剥离 signed query · 大小写归一
- ``lookup_by_legacy_url(url)``:反查 · 返回 ``LegacyUrlLookup`` frozen dataclass
- ``FILE_LEGACY_URL_LOOKUP_ENABLED``:env flag 默认关闭

**签名 URL 剥离规则**(与文件对象治理方案 §"legacy URL 长期过渡" 对齐):
- 剥离 ``X-Amz-Signature`` / ``X-Amz-Credential`` / ``X-Amz-Date`` / ``X-Amz-Expires``
- 剥离 ``token`` / ``signature`` / ``access_token`` / ``sig``
- 保留 stable identifier query(如 ``v=hash``)
- 反查基于 stripped URL · 与 `_normalize_legacy_url_stored_form()` 逐字对齐

**不做**:
- 不接入 ``/api/files/{id}`` 路由
- 不改 ``main.py`` 中现有 static file serving
- 不做 MinIO 迁移写入(归后续 PR)
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Mapping, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


_TRUTHY = frozenset({"1", "true", "yes", "on"})
FILE_LEGACY_URL_LOOKUP_ENABLED_ENV = "FILE_LEGACY_URL_LOOKUP_ENABLED"


def is_legacy_url_lookup_enabled() -> bool:
    """``FILE_LEGACY_URL_LOOKUP_ENABLED`` 是否已开启(默认 false)。"""
    return os.environ.get(FILE_LEGACY_URL_LOOKUP_ENABLED_ENV, "").strip().lower() in _TRUTHY


# 签名 URL query key 黑名单(小写匹配)
_SIGNED_QUERY_KEYS = frozenset({
    "x-amz-signature",
    "x-amz-credential",
    "x-amz-date",
    "x-amz-expires",
    "x-amz-security-token",
    "x-amz-signedheaders",
    "signature",
    "sig",
    "token",
    "access_token",
    "oss_signature",
})


@dataclass(frozen=True)
class LegacyUrlLookup:
    """反查结果 view · 不携带凭据。"""

    normalized_url: str
    file_object_id: Optional[str]  # None 表示未找到
    subject_kind: Optional[str]    # "canvas_asset" / "workflow_import" / "manual_upload"
    subject_id: Optional[str]


def normalize_legacy_url(url: str) -> str:
    """签名 URL query 剥离 + 大小写归一 · 返回稳定 lookup key。

    - 剥离 `_SIGNED_QUERY_KEYS` 中的 query
    - 保留 stable query(如 `v=hash` 版本参数)· 按 key 排序
    - Path 保留原样(大小写敏感 · S3 / MinIO 语义)
    """
    if not url:
        return ""
    parts = urlsplit(url.strip())
    if not parts.scheme and not parts.netloc and not parts.path:
        return ""
    # 拆 query · 剔除签名字段
    kept_query: list[Tuple[str, str]] = []
    for k, v in parse_qsl(parts.query, keep_blank_values=True):
        if k.lower() in _SIGNED_QUERY_KEYS:
            continue
        kept_query.append((k, v))
    kept_query.sort()
    new_query = urlencode(kept_query, doseq=True) if kept_query else ""
    # 归一化 host(去 port 默认值不做 · 与 MinIO endpoint host:port 保持敏感)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, ""))


def lookup_by_legacy_url(
    url: str,
    *,
    table: Mapping[str, Mapping[str, object]] = {},
) -> LegacyUrlLookup:
    """反查 legacy URL 对应的 FileObject。

    Args:
        url: 客户端 legacy URL(可能含签名 query)
        table: `legacy_url_refs` 表快照(测试注入 · 生产走 DB session)

    Returns:
        LegacyUrlLookup(normalized_url, file_object_id?, subject_kind?, subject_id?)
    """
    normalized = normalize_legacy_url(url)
    if not normalized:
        return LegacyUrlLookup(
            normalized_url="",
            file_object_id=None,
            subject_kind=None,
            subject_id=None,
        )
    hit = table.get(normalized)
    if not hit:
        return LegacyUrlLookup(
            normalized_url=normalized,
            file_object_id=None,
            subject_kind=None,
            subject_id=None,
        )
    return LegacyUrlLookup(
        normalized_url=normalized,
        file_object_id=str(hit.get("file_object_id")) if hit.get("file_object_id") else None,
        subject_kind=str(hit.get("subject_kind")) if hit.get("subject_kind") else None,
        subject_id=str(hit.get("subject_id")) if hit.get("subject_id") else None,
    )


def is_signed_url_query_key(key: str) -> bool:
    """helper · 便于契约测试断言。"""
    return key.lower() in _SIGNED_QUERY_KEYS
