"""``app.security.audit_policy`` — Audit 落盘策略骨架(部署 PR-11)。

**承接**:[[40 实施计划/部署与安全治理实施计划与PR清单]] PR-11 · 承接治理方案
M4 审计基线。**不接** 落盘 · 只描述策略与白名单字段。

**关联**:与权限 PR-7 AuditService `_ALLOWED_AUDIT_FIELDS` 白名单互补 ·
本模块提供**策略层**(哪些事件必须审计 / 保留多久 / 是否 pii)· AuditService
提供**执行层**(实际 append)。

**骨架契约**:
- ``AuditEventKind``:分类枚举
- ``AuditPolicy``:frozen dataclass · 一类事件的策略
- ``build_default_policies(mode)``:三模式默认策略表
- ``AUDIT_POLICY_ENABLED``:env flag 默认关闭

**默认策略**(治理方案 M4):
- login / logout / permission_change:public+intranet 必留 90 天
- provider_credential_edit:必留 180 天 · pii=true(需权限)
- file_upload_rejected:public 保留 30 天 · intranet 保留 7 天
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Literal, Mapping, Tuple


DeploymentMode = Literal["local_personal", "intranet_team", "public_team"]

AuditEventKind = Literal[
    "auth.login",
    "auth.logout",
    "auth.session_expired",
    "permission.change",
    "provider.credential_edit",
    "provider.credential_delete",
    "file.upload_accepted",
    "file.upload_rejected",
    "task.submitted",
    "task.failed",
    "admin.action",
]

AUDIT_EVENT_KINDS: Tuple[AuditEventKind, ...] = (
    "auth.login",
    "auth.logout",
    "auth.session_expired",
    "permission.change",
    "provider.credential_edit",
    "provider.credential_delete",
    "file.upload_accepted",
    "file.upload_rejected",
    "task.submitted",
    "task.failed",
    "admin.action",
)


_TRUTHY = frozenset({"1", "true", "yes", "on"})
AUDIT_POLICY_ENABLED_ENV = "AUDIT_POLICY_ENABLED"


def is_audit_policy_enabled() -> bool:
    return os.environ.get(AUDIT_POLICY_ENABLED_ENV, "").strip().lower() in _TRUTHY


@dataclass(frozen=True)
class AuditPolicy:
    """单个事件类的审计策略。"""

    kind: AuditEventKind
    required: bool             # 是否强制审计
    retention_days: int        # 保留天数(0 = 不落盘)
    contains_pii: bool = False # 是否含 PII / 敏感数据 · 影响读权限
    high_priority: bool = False  # 是否需要即时告警

    def __post_init__(self) -> None:
        if self.kind not in AUDIT_EVENT_KINDS:
            raise ValueError(f"kind={self.kind!r} not in AUDIT_EVENT_KINDS")
        if self.retention_days < 0:
            raise ValueError("retention_days must be >= 0")


def build_default_policies(
    mode: DeploymentMode,
) -> Mapping[AuditEventKind, AuditPolicy]:
    """按部署模式返回默认审计策略表。"""
    if mode == "local_personal":
        # dev · 不做强制审计 · 允许运行时全跳过
        return {k: AuditPolicy(kind=k, required=False, retention_days=0) for k in AUDIT_EVENT_KINDS}

    common_pii = ("provider.credential_edit", "provider.credential_delete")

    if mode == "intranet_team":
        table = {
            "auth.login": AuditPolicy(kind="auth.login", required=True, retention_days=90),
            "auth.logout": AuditPolicy(kind="auth.logout", required=True, retention_days=90),
            "auth.session_expired": AuditPolicy(kind="auth.session_expired", required=False, retention_days=30),
            "permission.change": AuditPolicy(kind="permission.change", required=True, retention_days=90, high_priority=True),
            "provider.credential_edit": AuditPolicy(kind="provider.credential_edit", required=True, retention_days=180, contains_pii=True),
            "provider.credential_delete": AuditPolicy(kind="provider.credential_delete", required=True, retention_days=180, contains_pii=True),
            "file.upload_accepted": AuditPolicy(kind="file.upload_accepted", required=False, retention_days=7),
            "file.upload_rejected": AuditPolicy(kind="file.upload_rejected", required=True, retention_days=30),
            "task.submitted": AuditPolicy(kind="task.submitted", required=False, retention_days=7),
            "task.failed": AuditPolicy(kind="task.failed", required=True, retention_days=30),
            "admin.action": AuditPolicy(kind="admin.action", required=True, retention_days=180, high_priority=True),
        }
        return table

    if mode == "public_team":
        table = {
            "auth.login": AuditPolicy(kind="auth.login", required=True, retention_days=180, high_priority=True),
            "auth.logout": AuditPolicy(kind="auth.logout", required=True, retention_days=180),
            "auth.session_expired": AuditPolicy(kind="auth.session_expired", required=True, retention_days=90),
            "permission.change": AuditPolicy(kind="permission.change", required=True, retention_days=365, high_priority=True),
            "provider.credential_edit": AuditPolicy(kind="provider.credential_edit", required=True, retention_days=365, contains_pii=True, high_priority=True),
            "provider.credential_delete": AuditPolicy(kind="provider.credential_delete", required=True, retention_days=365, contains_pii=True, high_priority=True),
            "file.upload_accepted": AuditPolicy(kind="file.upload_accepted", required=True, retention_days=30),
            "file.upload_rejected": AuditPolicy(kind="file.upload_rejected", required=True, retention_days=90),
            "task.submitted": AuditPolicy(kind="task.submitted", required=True, retention_days=30),
            "task.failed": AuditPolicy(kind="task.failed", required=True, retention_days=90),
            "admin.action": AuditPolicy(kind="admin.action", required=True, retention_days=365, high_priority=True),
        }
        return table

    raise ValueError(f"unknown deployment mode={mode!r}")
