"""``app.services.files.file_variant`` — FileVariant + 预览缓存 key 契约骨架
(文件 PR-11)。

**承接**:[[40 实施计划/文件对象与 MinIO 治理实施计划与PR清单]] PR-11。

**定位**:纯 frozen dataclass · 描述 file_object 的 variant(缩略图 / 预览 / 转码)·
提供确定的 cache key · **不接** 生成流水线(归下游 PR)。

**骨架契约**:
- ``FileVariantKind``:Literal · thumbnail / preview / transcoded / original
- ``FileVariant``:frozen dataclass · 一个 variant 的描述
- ``compute_variant_key(file_object_id, variant, size?)``:纯函数 · 稳定 key
- ``FILE_VARIANT_CACHE_ENABLED``:env flag 默认关闭

**cache key 规则**:
- `variant/{kind}/{file_object_id}[/{width}x{height}]`
- 大小写敏感 · 目录分隔用 ``/``
- 严禁把 signed URL / secret 拼进 key
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Literal, Optional, Tuple


_TRUTHY = frozenset({"1", "true", "yes", "on"})
FILE_VARIANT_CACHE_ENABLED_ENV = "FILE_VARIANT_CACHE_ENABLED"


def is_variant_cache_enabled() -> bool:
    return os.environ.get(FILE_VARIANT_CACHE_ENABLED_ENV, "").strip().lower() in _TRUTHY


FileVariantKind = Literal["thumbnail", "preview", "transcoded", "original"]

VARIANT_KINDS: Tuple[FileVariantKind, ...] = ("thumbnail", "preview", "transcoded", "original")

# 允许的缩略图 preset 尺寸(短边 · 单位:像素)· 治理期基线
THUMBNAIL_PRESETS: Tuple[int, ...] = (64, 128, 256, 512)


@dataclass(frozen=True)
class FileVariant:
    """一个 file_object 的 variant 描述。"""

    kind: FileVariantKind
    width: Optional[int] = None
    height: Optional[int] = None
    format: Optional[str] = None  # 如 "webp" / "jpg" / "mp4"

    def __post_init__(self) -> None:
        if self.kind not in VARIANT_KINDS:
            raise ValueError(f"kind={self.kind!r} not in {VARIANT_KINDS}")
        if self.width is not None and self.width <= 0:
            raise ValueError("width must be > 0 or None")
        if self.height is not None and self.height <= 0:
            raise ValueError("height must be > 0 or None")
        if self.kind == "original":
            if self.width or self.height or self.format:
                raise ValueError("original variant must not carry width/height/format")


def compute_variant_key(file_object_id: str, variant: FileVariant) -> str:
    """稳定 cache key · 不含 secret / signed query。"""
    if not file_object_id:
        raise ValueError("file_object_id must not be empty")
    # 硬约束:file_object_id 里绝不允许出现凭据关键词或路径穿越
    lowered = file_object_id.lower()
    for kw in ("api_key", "authorization", "bearer", "secret", "..", "\\"):
        if kw in lowered:
            raise ValueError(f"file_object_id contains forbidden token {kw!r}")
    parts = ["variant", variant.kind, file_object_id]
    if variant.width or variant.height:
        w = variant.width or 0
        h = variant.height or 0
        parts.append(f"{w}x{h}")
    if variant.format:
        parts.append(variant.format)
    return "/".join(parts)


def suggest_thumbnail_size(long_edge_px: int) -> int:
    """根据原图长边推荐 preset 尺寸(最接近但不超过原图)。"""
    if long_edge_px <= 0:
        raise ValueError("long_edge_px must be > 0")
    picked = THUMBNAIL_PRESETS[0]
    for size in THUMBNAIL_PRESETS:
        if size <= long_edge_px:
            picked = size
    return picked
