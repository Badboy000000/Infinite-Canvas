"""``app.services.files.orphan_scan`` — orphan_scan CLI 骨架(文件 PR-7)。

**承接**:[[40 实施计划/文件对象与 MinIO 治理实施计划与PR清单]] PR-7 · M2 加固。

**定位**:纯函数库 · 消费 `file_objects` / `file_refs` 表快照 · 计算孤儿 file_object
候选列表 · **不接** SQL 事务 · **不接** MinIO delete(生产切换归 PR-12+)。

**骨架契约**:
- ``OrphanCandidate``:frozen dataclass · 描述一条孤儿候选
- ``compute_orphan_candidates(file_objects, refs, ...)``:纯函数
- ``format_orphan_report(candidates, ...)``:文本/JSON 报表(纯函数)
- ``ORPHAN_SCAN_MIN_AGE_HOURS``:安全窗口(默认 24h · 只报告更旧的 orphan)
- ``FILE_ORPHAN_SCAN_ENABLED``:env flag 默认关闭

**硬约束**:
- 骨架层只**报告** · 不实际删除
- 只把 (reference_count == 0 AND last_referenced_at older than min_age) 报为候选
- 输出保序:file_object_id 升序 · 便于二次跑一致
- 审计埋点保留字段名与文件治理方案 §"回收任务" 对齐

**不做**:
- 不接 SQLAlchemy session
- 不接 audit 落盘
- 不发 MinIO delete
- 不接 CLI dispatch(需 main.py 承接 · 归下游 PR)
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, List, Mapping, Optional, Sequence, Tuple


_TRUTHY = frozenset({"1", "true", "yes", "on"})
FILE_ORPHAN_SCAN_ENABLED_ENV = "FILE_ORPHAN_SCAN_ENABLED"

# 默认安全窗口:只对 last_referenced_at > 24h 前的对象报告 orphan
ORPHAN_SCAN_MIN_AGE_HOURS = 24


def is_orphan_scan_enabled() -> bool:
    return os.environ.get(FILE_ORPHAN_SCAN_ENABLED_ENV, "").strip().lower() in _TRUTHY


@dataclass(frozen=True)
class OrphanCandidate:
    """一个孤儿候选 · **不含** 密钥字段。"""

    file_object_id: str
    reference_count: int
    last_referenced_at: Optional[str]  # ISO 8601 or None
    key: str                            # object key(如 output/ab/cd/xxx.png)
    sha256: str

    def __post_init__(self) -> None:
        if self.reference_count != 0:
            raise ValueError(
                f"OrphanCandidate.reference_count must be 0 (got {self.reference_count})"
            )
        if not self.file_object_id:
            raise ValueError("file_object_id must not be empty")


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        # 支持 `Z` 与 `+00:00`
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def compute_orphan_candidates(
    file_objects: Iterable[Mapping[str, object]],
    *,
    now_utc: datetime,
    min_age_hours: int = ORPHAN_SCAN_MIN_AGE_HOURS,
) -> Tuple[OrphanCandidate, ...]:
    """扫描 file_objects 表快照 · 返回孤儿候选(升序稳定)。

    Args:
        file_objects: iterable of dict with keys ``id / reference_count /
            last_referenced_at / key / sha256``
        now_utc: 当前时间(UTC)· 显式注入便于测试
        min_age_hours: 安全窗口(小时)· 默认 24

    Returns:
        Tuple[OrphanCandidate, ...] · file_object_id 升序稳定
    """
    if min_age_hours < 0:
        raise ValueError("min_age_hours must be >= 0")
    cutoff = now_utc.timestamp() - min_age_hours * 3600
    out: List[OrphanCandidate] = []
    for row in file_objects:
        ref_count = int(row.get("reference_count", 0) or 0)
        if ref_count != 0:
            continue
        last_ref_iso = row.get("last_referenced_at")
        last_ref_dt = _parse_iso(str(last_ref_iso) if last_ref_iso else None)
        # 缺失 last_referenced_at 视为"很久没有引用"· 属于候选
        if last_ref_dt is not None and last_ref_dt.timestamp() > cutoff:
            continue
        cand = OrphanCandidate(
            file_object_id=str(row.get("id", "")),
            reference_count=0,
            last_referenced_at=str(last_ref_iso) if last_ref_iso else None,
            key=str(row.get("key", "")),
            sha256=str(row.get("sha256", "")),
        )
        out.append(cand)
    out.sort(key=lambda c: c.file_object_id)
    return tuple(out)


def format_orphan_report(
    candidates: Sequence[OrphanCandidate],
    *,
    output_format: str = "text",
) -> str:
    """返回易读文本或 JSON 报表(纯函数)。"""
    if output_format not in ("text", "json"):
        raise ValueError(f"output_format must be 'text' or 'json' (got {output_format!r})")
    if output_format == "json":
        payload = [
            {
                "file_object_id": c.file_object_id,
                "reference_count": c.reference_count,
                "last_referenced_at": c.last_referenced_at,
                "key": c.key,
                "sha256": c.sha256,
            }
            for c in candidates
        ]
        return json.dumps({"orphan_count": len(candidates), "candidates": payload}, indent=2)
    # text
    if not candidates:
        return "orphan_scan: 0 candidates"
    lines = [f"orphan_scan: {len(candidates)} candidate(s)"]
    for c in candidates:
        lines.append(
            f"  - {c.file_object_id}  key={c.key}  last_ref={c.last_referenced_at or '<never>'}"
        )
    return "\n".join(lines)
