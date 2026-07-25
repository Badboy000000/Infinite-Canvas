"""``app.security.backup_policy`` — 备份 & DR 策略骨架(部署 PR-13)。

**承接**:[[40 实施计划/部署与安全治理实施计划与PR清单]] PR-13 · 承接治理方案
M4 备份与灾难恢复。**不接** 实际备份工具 · 只描述策略层。

**骨架契约**:
- ``BackupKind``:Literal · full / incremental / snapshot
- ``BackupPolicy``:frozen dataclass · 一份策略
- ``build_default_policy(mode)``:三模式默认策略表
- ``compute_retention_series(policy)``:纯函数 · 返回 daily/weekly/monthly 保留矩阵
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Literal, Mapping, Tuple


DeploymentMode = Literal["local_personal", "intranet_team", "public_team"]
BackupKind = Literal["full", "incremental", "snapshot"]

BACKUP_KINDS: Tuple[BackupKind, ...] = ("full", "incremental", "snapshot")

_TRUTHY = frozenset({"1", "true", "yes", "on"})
BACKUP_POLICY_ENABLED_ENV = "BACKUP_POLICY_ENABLED"


def is_backup_policy_enabled() -> bool:
    return os.environ.get(BACKUP_POLICY_ENABLED_ENV, "").strip().lower() in _TRUTHY


@dataclass(frozen=True)
class BackupPolicy:
    """一份备份策略。"""

    mode: DeploymentMode
    full_backup_interval_hours: int  # 全备间隔
    incremental_backup_interval_hours: int  # 增量间隔
    daily_retention: int   # 保留几天的每日备份
    weekly_retention: int  # 保留几周的每周备份
    monthly_retention: int  # 保留几月的每月备份
    off_site_replica: bool  # 是否需要异地副本
    encryption_required: bool  # 是否强制加密

    def __post_init__(self) -> None:
        for k in (
            "full_backup_interval_hours",
            "incremental_backup_interval_hours",
            "daily_retention",
            "weekly_retention",
            "monthly_retention",
        ):
            if getattr(self, k) < 0:
                raise ValueError(f"{k} must be >= 0")
        if self.incremental_backup_interval_hours > self.full_backup_interval_hours:
            raise ValueError(
                "incremental interval must be <= full interval"
            )


def build_default_policy(mode: DeploymentMode) -> BackupPolicy:
    if mode == "local_personal":
        # dev · 最小策略 · 只保留 7 天日备
        return BackupPolicy(
            mode=mode,
            full_backup_interval_hours=24, incremental_backup_interval_hours=24,
            daily_retention=7, weekly_retention=0, monthly_retention=0,
            off_site_replica=False, encryption_required=False,
        )
    if mode == "intranet_team":
        return BackupPolicy(
            mode=mode,
            full_backup_interval_hours=24, incremental_backup_interval_hours=6,
            daily_retention=14, weekly_retention=4, monthly_retention=3,
            off_site_replica=True, encryption_required=True,
        )
    if mode == "public_team":
        return BackupPolicy(
            mode=mode,
            full_backup_interval_hours=12, incremental_backup_interval_hours=1,
            daily_retention=30, weekly_retention=12, monthly_retention=12,
            off_site_replica=True, encryption_required=True,
        )
    raise ValueError(f"unknown deployment mode={mode!r}")


def compute_retention_series(policy: BackupPolicy) -> Mapping[str, int]:
    """返回 daily/weekly/monthly 保留矩阵(便于运维仪表盘消费)。"""
    return {
        "daily": policy.daily_retention,
        "weekly": policy.weekly_retention,
        "monthly": policy.monthly_retention,
        "total": policy.daily_retention + policy.weekly_retention + policy.monthly_retention,
    }
