"""``app.services.files.legacy_url_sunset`` — legacy URL 下线判据脚本骨架
(文件 PR-9)。

**承接**:[[40 实施计划/文件对象与 MinIO 治理实施计划与PR清单]] PR-9 · 归 M2 结尾
判据。生成 legacy URL 下线报告(纯函数)· 由未来 PR-14 静态挂载下线消费。

**骨架契约**:
- ``LegacyUrlBucket``:一段 URL 前缀 → 判据(下线 / 保留 / 降级)
- ``SunsetJudgement``:frozen dataclass · 一个 bucket 的判定视图
- ``build_sunset_report(url_stats)``:纯函数
- ``FILE_LEGACY_URL_SUNSET_STRICT``:env flag 默认关闭

**判据(治理方案 §"legacy URL 长期过渡"):
- 若一段 URL 前缀 30 天内 0 访问 · 且 100% 已在 legacy_url_refs 中反查到
  file_object_id → **允许下线**
- 若 30 天内仍有访问 · 或存在未映射的 URL → **保留**
- 若已映射 ≥ 80% 且访问量 < 5/天 → **可降级**(WARN)

**不做**:
- 不接 SQL(需 access log + legacy_url_refs 联合查询 · 归下游 PR)
- 不改静态挂载(归 PR-14)
- 不发通知
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Iterable, Literal, Mapping, Sequence, Tuple


_TRUTHY = frozenset({"1", "true", "yes", "on"})
FILE_LEGACY_URL_SUNSET_STRICT_ENV = "FILE_LEGACY_URL_SUNSET_STRICT"


def is_legacy_url_sunset_strict() -> bool:
    return os.environ.get(FILE_LEGACY_URL_SUNSET_STRICT_ENV, "").strip().lower() in _TRUTHY


Verdict = Literal["retire", "downgrade", "retain"]

VERDICTS: Tuple[Verdict, ...] = ("retire", "downgrade", "retain")


@dataclass(frozen=True)
class LegacyUrlBucket:
    """一段 URL 前缀的统计快照(输入)。"""

    prefix: str  # 如 "/assets/library" / "/output"
    total_urls: int
    mapped_urls: int  # 已建立 legacy_url_refs
    accesses_last_30d: int

    def __post_init__(self) -> None:
        if not self.prefix:
            raise ValueError("prefix must not be empty")
        if self.total_urls < 0 or self.mapped_urls < 0 or self.accesses_last_30d < 0:
            raise ValueError("counts must be >= 0")
        if self.mapped_urls > self.total_urls:
            raise ValueError("mapped_urls > total_urls")


@dataclass(frozen=True)
class SunsetJudgement:
    """一个 bucket 的判定视图。"""

    prefix: str
    verdict: Verdict
    mapped_ratio: float  # 0..1
    accesses_per_day: float
    reasons: Tuple[str, ...] = field(default_factory=tuple)


def _judge_one(bucket: LegacyUrlBucket) -> SunsetJudgement:
    reasons: list[str] = []
    ratio = 0.0
    if bucket.total_urls > 0:
        ratio = bucket.mapped_urls / bucket.total_urls
    accesses_per_day = bucket.accesses_last_30d / 30.0

    if bucket.accesses_last_30d == 0 and ratio >= 1.0:
        reasons.append("0 accesses in last 30 days and 100% mapped")
        verdict: Verdict = "retire"
    elif ratio >= 0.8 and accesses_per_day < 5.0:
        reasons.append(f"mapped {ratio:.0%} >= 80% and traffic {accesses_per_day:.1f}/day < 5")
        verdict = "downgrade"
    else:
        if ratio < 0.8:
            reasons.append(f"mapped ratio {ratio:.0%} below 80% threshold")
        if accesses_per_day >= 5.0:
            reasons.append(f"traffic {accesses_per_day:.1f}/day above 5")
        verdict = "retain"

    return SunsetJudgement(
        prefix=bucket.prefix,
        verdict=verdict,
        mapped_ratio=ratio,
        accesses_per_day=accesses_per_day,
        reasons=tuple(reasons),
    )


def build_sunset_report(
    buckets: Iterable[LegacyUrlBucket],
) -> Tuple[SunsetJudgement, ...]:
    """扫描所有 bucket · 返回判定 view tuple(按 prefix 稳定排序)。"""
    return tuple(sorted((_judge_one(b) for b in buckets), key=lambda j: j.prefix))
