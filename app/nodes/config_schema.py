"""``app.nodes.config_schema`` — 节点 config schema + UI schema 契约(节点 PR-1)。

**承接**:[[40 实施计划/节点系统治理实施计划与PR清单]] PR-1 · M0。

**决策边界(AR-N02)**:治理期采用**轻量自定义 schema**(字段分类 + 类型标签 + legacy
兼容)· 不引入 JSON Schema 依赖 · 未来 move 期评估 JSON Schema 迁移。

**契约核心**:节点 config schema 字段被划分为 6 大类别(``ConfigFieldCategory``),
每一类明确「运行输入 / 展示 / 持久缓存 / legacy」的分工:

- ``input``    → 节点运行时的显式输入(NodeExecutionRequest.input_snapshot)
- ``settings`` → 生成参数(NodeExecutionRequest.settings_snapshot 中除依赖以外)
- ``dependency`` → 依赖引用(上游节点、外部 workflow、asset 引用)
- ``presentation`` → UI 层展示字段(不作为 NodeRun 事实源)
- ``runtime-cache`` → pending 展示缓存(``_pending`` / ``pendingTasks`` / ``jimengPending``)
- ``legacy``   → 兼容字段(读侧解释 · 写侧透传 · 不列入白名单删除)

**硬约束**:
- UI schema 允许「未知字段透传」· 未列入 schema 的字段读侧保留 · 写侧透传
- ``credentials`` / ``api_key`` / ``authorization`` / 签名 URL 严禁承载
- schema 只是描述性契约 · 不做运行时校验(校验层归下游 PR)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Mapping, Sequence, Tuple


ConfigFieldCategory = Literal[
    "input",
    "settings",
    "dependency",
    "presentation",
    "runtime-cache",
    "legacy",
]

# 冻结类别顺序 · 与治理方案 §"config schema 字段分类"逐字对齐。
CONFIG_FIELD_CATEGORIES: Tuple[ConfigFieldCategory, ...] = (
    "input",
    "settings",
    "dependency",
    "presentation",
    "runtime-cache",
    "legacy",
)

# 凭据 / 密钥关键词禁入清单(小写)· 与 provider schema_v2 `_V1_SECRET_FIELDS` 语义
# 对齐;节点字段名匹配任一关键词时应当被视为治理违规。
FORBIDDEN_FIELD_KEYWORDS: Tuple[str, ...] = (
    "api_key",
    "apikey",
    "access_key",
    "secret",
    "secret_access_key",
    "authorization",
    "bearer",
    "wallet_api_key",
    "token",
    "signature",
)


@dataclass(frozen=True)
class NodeConfigField:
    """描述节点 config schema 中的单个字段(纯声明 · 不做运行时校验)。"""

    name: str
    category: ConfigFieldCategory
    type_hint: str  # e.g. "string" / "number" / "asset_ref" / "provider_id"
    required: bool = False
    description: str = ""
    legacy: bool = False  # legacy 字段读侧解释 · 写侧透传
    facets: Tuple[str, ...] = field(default_factory=tuple)  # smart-image facet 声明

    def __post_init__(self) -> None:  # 只做描述层不变量断言 · 不校验业务字段
        if self.category not in CONFIG_FIELD_CATEGORIES:
            raise ValueError(
                f"category={self.category!r} must be one of {CONFIG_FIELD_CATEGORIES}"
            )
        lowered = self.name.lower()
        for kw in FORBIDDEN_FIELD_KEYWORDS:
            # `provider_id` / `provider_config_id` / `apiProvider` 只保存标识符
            # (不含关键词) · 精确关键词匹配防止误伤 identifier 字段。
            if kw == lowered or lowered.endswith("_" + kw) or lowered.startswith(kw + "_"):
                raise ValueError(
                    f"node config field name={self.name!r} contains forbidden "
                    f"credential-like keyword {kw!r}; node fields must not carry secrets"
                )


@dataclass(frozen=True)
class NodeConfigSchema:
    """节点类型的 config schema 声明。"""

    node_type: str
    schema_version: int
    fields: Tuple[NodeConfigField, ...]
    facets: Tuple[str, ...] = field(default_factory=tuple)  # smart-image capability facets
    allow_unknown_fields: bool = True  # 硬约束:未知字段透传

    def by_category(self, category: ConfigFieldCategory) -> Tuple[NodeConfigField, ...]:
        return tuple(f for f in self.fields if f.category == category)

    def legacy_fields(self) -> Tuple[NodeConfigField, ...]:
        return tuple(f for f in self.fields if f.legacy)


def build_compatibility_table(
    schema: NodeConfigSchema,
) -> Mapping[ConfigFieldCategory, Sequence[str]]:
    """构造「Node config schema 兼容表」(PR-2 / PR-3 契约测试消费入口)。"""

    table: dict[ConfigFieldCategory, list[str]] = {c: [] for c in CONFIG_FIELD_CATEGORIES}
    for f in schema.fields:
        table[f.category].append(f.name)
    return {k: tuple(v) for k, v in table.items()}
