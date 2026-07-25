"""节点 PR-1 · Node config schema + UI schema 契约测试。

覆盖:
- 6 类 ConfigFieldCategory 冻结顺序
- NodeConfigField 凭据关键词禁入(硬约束)
- NodeConfigSchema.by_category / legacy_fields
- build_compatibility_table 输出结构
"""
from __future__ import annotations

import pytest

from app.nodes import (
    CONFIG_FIELD_CATEGORIES,
    ConfigFieldCategory,
    NodeConfigField,
    NodeConfigSchema,
)
from app.nodes.config_schema import (
    FORBIDDEN_FIELD_KEYWORDS,
    build_compatibility_table,
)


# --- T700-T705:类别顺序冻结与 field 约束 -----------------------------------

def test_T700_config_field_categories_frozen():
    """6 类别顺序冻结(与治理方案 §"config schema 字段分类" 逐字对齐)。"""
    assert CONFIG_FIELD_CATEGORIES == (
        "input", "settings", "dependency",
        "presentation", "runtime-cache", "legacy",
    )


def test_T701_forbidden_credential_keywords_listed():
    """凭据关键词禁入清单必须覆盖典型 provider 密钥字段名。"""
    required = {"api_key", "authorization", "bearer", "secret", "token"}
    assert required.issubset(set(FORBIDDEN_FIELD_KEYWORDS))


@pytest.mark.parametrize("bad_name", [
    "api_key",
    "apikey",
    "authorization",
    "user_secret",
    "bearer_token",
    "wallet_api_key",
])
def test_T702_node_config_field_rejects_credential_keywords(bad_name):
    """节点 config 字段名不允许包含凭据关键词。"""
    with pytest.raises(ValueError, match="credential-like"):
        NodeConfigField(name=bad_name, category="input", type_hint="string")


@pytest.mark.parametrize("ok_name", [
    "prompt",
    "model",
    "provider_id",  # identifier · 不含关键词
    "workflow_id",
    "chat_input",
    "run_settings",
])
def test_T703_node_config_field_accepts_identifier_style(ok_name):
    """标识符类字段名(不匹配关键词)允许通过。"""
    f = NodeConfigField(name=ok_name, category="settings", type_hint="string")
    assert f.name == ok_name


def test_T704_node_config_field_rejects_unknown_category():
    with pytest.raises(ValueError, match="category="):
        NodeConfigField(name="prompt", category="foo", type_hint="string")  # type: ignore[arg-type]


# --- T706-T709:NodeConfigSchema 结构 ---------------------------------------

def _schema_sample() -> NodeConfigSchema:
    return NodeConfigSchema(
        node_type="generator",
        schema_version=1,
        fields=(
            NodeConfigField(name="model", category="settings", type_hint="string"),
            NodeConfigField(name="ratio", category="settings", type_hint="string"),
            NodeConfigField(name="inputs", category="dependency", type_hint="asset_ref_list"),
            NodeConfigField(name="_pending", category="runtime-cache", type_hint="opaque", legacy=True),
            NodeConfigField(
                name="generatedOutputs",
                category="legacy",
                type_hint="opaque",
                legacy=True,
            ),
        ),
        allow_unknown_fields=True,
    )


def test_T706_schema_by_category_partitions_fields():
    schema = _schema_sample()
    settings = schema.by_category("settings")
    assert [f.name for f in settings] == ["model", "ratio"]
    legacy = schema.by_category("legacy")
    assert [f.name for f in legacy] == ["generatedOutputs"]


def test_T707_schema_legacy_fields_returns_only_legacy():
    schema = _schema_sample()
    lf = schema.legacy_fields()
    assert {f.name for f in lf} == {"_pending", "generatedOutputs"}


def test_T708_schema_allow_unknown_fields_default_true():
    schema = _schema_sample()
    assert schema.allow_unknown_fields is True, (
        "unknown field passthrough is a hard invariant of the node config schema contract"
    )


def test_T709_compatibility_table_has_all_categories():
    schema = _schema_sample()
    table = build_compatibility_table(schema)
    # 每个 category 都必须出现 · 空类别返回空 tuple 而非缺失键
    for cat in CONFIG_FIELD_CATEGORIES:
        assert cat in table
    assert table["input"] == ()
    assert set(table["settings"]) == {"model", "ratio"}


# --- T710:facets 声明 · smart-image capability ---------------------------

def test_T710_schema_allows_smart_image_facets():
    schema = NodeConfigSchema(
        node_type="smart-image",
        schema_version=1,
        fields=(
            NodeConfigField(
                name="scale",
                category="settings",
                type_hint="number",
                facets=("generation-target",),
            ),
        ),
        facets=("media-source", "generation-target", "media-output", "run-state-host"),
    )
    assert "generation-target" in schema.facets
