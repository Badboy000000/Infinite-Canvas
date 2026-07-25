"""``app.services.files.asset_item_ref`` — AssetItemFileRef 语义切换 helper
(文件 PR-10 骨架)。

**承接**:[[40 实施计划/文件对象与 MinIO 治理实施计划与PR清单]] PR-10 · 素材入库
「改引用」不改 legacy JSON 落盘。依赖数据 PR-9(AssetLibrary 主写)已合入。

**定位**:纯函数库 · 把 asset library item 的 legacy URL 引用**规范化为**
FileRef(subject_kind="asset_library_item"),同时把 AssetItemFileRef 序列化为
可持久化的 dict view。不接 SQL · 不改 legacy JSON 落盘 shape · 归下游 PR 承接。

**骨架契约**:
- ``AssetItemFileRef``:frozen dataclass · 描述素材条目引用 file_object 的关系
- ``build_asset_item_file_ref(...)``:纯函数 · 从 asset_library item + url resolve 结果构造
- ``ASSET_ITEM_REF_STRICT``:env flag(默认 false · 关闭时 legacy 优先)

**兼容策略**(与文件对象治理方案 §"素材入库改引用" 对齐):
- 老 asset_library.json 中 `items[].url` 保持不动
- 新增派生字段 `items[].file_object_id` / `items[].file_ref_id`(additive)
- 反向 lookup 需求走 [[app.services.files.legacy_url_ref]] · 本模块只描述关系

**不做**:
- 不改 asset_library.json 主写路径
- 不接 SQLAlchemy · 不接 AssetLibraryService
- 不做 migration(归数据 PR)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Literal, Mapping, Optional, Tuple


_TRUTHY = frozenset({"1", "true", "yes", "on"})
ASSET_ITEM_REF_STRICT_ENV = "ASSET_ITEM_REF_STRICT"


def is_asset_item_ref_strict() -> bool:
    """开启后 · 缺失 file_object_id 会被视为治理违规(默认 false)。"""
    return os.environ.get(ASSET_ITEM_REF_STRICT_ENV, "").strip().lower() in _TRUTHY


AssetKind = Literal["image", "video", "workflow", "audio", "other"]

ALLOWED_ASSET_KINDS: Tuple[AssetKind, ...] = ("image", "video", "workflow", "audio", "other")


@dataclass(frozen=True)
class AssetItemFileRef:
    """asset library item ↔ file_object 引用关系。"""

    asset_library_id: str
    asset_item_id: str
    asset_kind: AssetKind
    file_object_id: Optional[str]      # None → legacy-only(尚未接入 FileService)
    legacy_url: Optional[str]           # 老 url · 长期过渡
    file_ref_id: Optional[str] = None   # 未来 PR 承接:file_refs 表主键

    def __post_init__(self) -> None:
        if not self.asset_library_id:
            raise ValueError("asset_library_id must not be empty")
        if not self.asset_item_id:
            raise ValueError("asset_item_id must not be empty")
        if self.asset_kind not in ALLOWED_ASSET_KINDS:
            raise ValueError(
                f"asset_kind={self.asset_kind!r} not in {ALLOWED_ASSET_KINDS}"
            )
        # 严格模式:必须至少有一侧非空
        if not self.file_object_id and not self.legacy_url:
            raise ValueError(
                "at least one of file_object_id / legacy_url must be present"
            )

    def to_persistable(self) -> Mapping[str, object]:
        """dict view · 允许直接嵌入 asset_library.json items[] 的派生字段。"""
        out: dict[str, object] = {
            "asset_library_id": self.asset_library_id,
            "asset_item_id": self.asset_item_id,
            "asset_kind": self.asset_kind,
        }
        if self.file_object_id:
            out["file_object_id"] = self.file_object_id
        if self.file_ref_id:
            out["file_ref_id"] = self.file_ref_id
        if self.legacy_url:
            out["legacy_url"] = self.legacy_url
        return out


def build_asset_item_file_ref(
    *,
    asset_library_id: str,
    asset_item_id: str,
    asset_kind: AssetKind,
    file_object_id: Optional[str] = None,
    legacy_url: Optional[str] = None,
    file_ref_id: Optional[str] = None,
) -> AssetItemFileRef:
    """纯函数构造器 · 便于测试与未来 PR 迁移期消费。"""
    return AssetItemFileRef(
        asset_library_id=asset_library_id,
        asset_item_id=asset_item_id,
        asset_kind=asset_kind,
        file_object_id=file_object_id,
        legacy_url=legacy_url,
        file_ref_id=file_ref_id,
    )


def is_legacy_only(ref: AssetItemFileRef) -> bool:
    """尚未接入 FileService 的 legacy-only 状态判定。"""
    return ref.file_object_id is None and bool(ref.legacy_url)


def is_migrated(ref: AssetItemFileRef) -> bool:
    """已经接入 FileService 的状态判定。"""
    return ref.file_object_id is not None
