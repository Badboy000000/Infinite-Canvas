"""Provider PR-05 · CredentialRef 分级抽象契约测试(CB-02 长期根治骨架)。"""
from __future__ import annotations

import json

import pytest

from app.adapters.provider.credential_ref import (
    CREDENTIAL_LEVELS,
    PERSISTABLE_LEVELS,
    CredentialRef,
    ProviderCredentialContract,
    build_credential_ref_from_inline,
    compute_fingerprint,
    strip_credential_from_error_body,
)


# --- T840-T843:分级 + 冻结顺序 ---------------------------------

def test_T840_credential_levels_frozen():
    assert CREDENTIAL_LEVELS == (
        "L0_INLINE",
        "L1_ENV",
        "L2_SECRET_STORE",
        "L3_FINGERPRINT",
    )


def test_T841_persistable_levels_excludes_l0():
    assert "L0_INLINE" not in PERSISTABLE_LEVELS
    assert set(PERSISTABLE_LEVELS) == {"L1_ENV", "L2_SECRET_STORE", "L3_FINGERPRINT"}


def test_T842_env_var_reference_must_be_upper_snake():
    CredentialRef(level="L1_ENV", reference="OPENAI_API_KEY")
    with pytest.raises(ValueError, match="UPPER_SNAKE_CASE"):
        CredentialRef(level="L1_ENV", reference="openai_api_key")
    with pytest.raises(ValueError, match="UPPER_SNAKE_CASE"):
        CredentialRef(level="L1_ENV", reference="OPENAI KEY")


def test_T843_vault_reference_path_safe():
    CredentialRef(level="L2_SECRET_STORE", reference="providers/openai/prod")
    with pytest.raises(ValueError, match="safe path"):
        CredentialRef(level="L2_SECRET_STORE", reference="providers openai; drop table")


# --- T844-T846:to_persistable 拒绝 L0 ---------------------------

def test_T844_l0_inline_cannot_be_persisted():
    ref = CredentialRef(level="L0_INLINE", reference="sk-live-secret")
    with pytest.raises(ValueError, match="never be persisted"):
        ref.to_persistable()


def test_T845_l1_env_persistable_view():
    ref = CredentialRef(level="L1_ENV", reference="OPENAI_API_KEY", fingerprint="ab12cd34")
    view = ref.to_persistable()
    assert view["level"] == "L1_ENV"
    assert view["reference"] == "OPENAI_API_KEY"
    assert view["fingerprint"] == "ab12cd34"


def test_T846_l3_persistable_view_stores_only_fingerprint():
    ref = build_credential_ref_from_inline("sk-live-abc-def-1234567890")
    view = ref.to_persistable()
    assert view["level"] == "L3_FINGERPRINT"
    # reference 应当只承载 fingerprint 前缀 · 不含原文
    assert "sk-live" not in view["reference"]
    assert view["reference"].startswith("fp_")


# --- T847-T849:P0 密钥零泄漏 · str/repr/json 三层扫描 -----------

def test_T847_credential_ref_repr_no_secret_leak():
    ref = build_credential_ref_from_inline("sk-INJECT-secret-abcdef")
    text = repr(ref)
    assert "sk-INJECT-secret" not in text
    assert "abcdef" not in text or "abcdef" in ref.fingerprint  # 允许指纹字面量


def test_T848_credential_ref_str_no_secret_leak():
    ref = build_credential_ref_from_inline("Bearer XXX-token-live-abc123")
    text = str(ref)
    assert "XXX-token-live-abc123" not in text


def test_T849_credential_ref_json_dumps_no_secret_leak():
    """to_persistable() 返回 dict 可以安全 JSON 序列化。"""
    ref = build_credential_ref_from_inline("sk-secret-value")
    view = ref.to_persistable()
    blob = json.dumps(view)
    assert "sk-secret-value" not in blob


# --- T850:build_credential_ref_from_inline · L3 指纹稳定 -----------

def test_T850_fingerprint_is_deterministic():
    ref1 = build_credential_ref_from_inline("sk-live-abc")
    ref2 = build_credential_ref_from_inline("sk-live-abc")
    assert ref1.fingerprint == ref2.fingerprint
    # 不同 secret 必须不同指纹
    ref3 = build_credential_ref_from_inline("sk-live-xyz")
    assert ref1.fingerprint != ref3.fingerprint


def test_T851_fingerprint_length_default_eight():
    fp = compute_fingerprint("sk-abc")
    assert len(fp) == 8


def test_T852_empty_secret_returns_empty_fingerprint():
    assert compute_fingerprint("") == ""


# --- T853-T857:CB-02 长期根治 · strip_credential_from_error_body ---

def test_T853_strip_flat_dict():
    body = {"api_key": "sk-live-abc", "model": "gpt-4"}
    scrubbed = strip_credential_from_error_body(body)
    assert scrubbed["api_key"] == "***REDACTED***"
    assert scrubbed["model"] == "gpt-4"


def test_T854_strip_nested_dict():
    body = {
        "provider": {
            "api_key": "sk-live-secret",
            "name": "openai",
        },
        "workspace": "ws-1",
    }
    scrubbed = strip_credential_from_error_body(body)
    assert scrubbed["provider"]["api_key"] == "***REDACTED***"
    assert scrubbed["provider"]["name"] == "openai"
    assert scrubbed["workspace"] == "ws-1"


def test_T855_strip_list_of_dicts():
    body = {
        "providers": [
            {"api_key": "sk-1", "name": "a"},
            {"api_key": "sk-2", "name": "b"},
        ],
    }
    scrubbed = strip_credential_from_error_body(body)
    assert scrubbed["providers"][0]["api_key"] == "***REDACTED***"
    assert scrubbed["providers"][1]["api_key"] == "***REDACTED***"
    assert scrubbed["providers"][0]["name"] == "a"


def test_T856_strip_covers_all_known_credential_fields():
    body = {
        "api_key": "sk-1",
        "access_key": "AKIA1",
        "secret_access_key": "aws-secret",
        "wallet_api_key": "wallet-abc",
        "authorization": "Bearer xyz",
        "token": "t1",
        "refresh_token": "rt1",
        "client_secret": "cs1",
    }
    scrubbed = strip_credential_from_error_body(body)
    for k in body:
        assert scrubbed[k] == "***REDACTED***", f"{k} not scrubbed"


def test_T857_strip_ignores_identifier_fields():
    """`provider_id` / `workspace_id` 不是凭据 · 保留原样。"""
    body = {"provider_id": "prov_openai_01", "workspace_id": "ws-1"}
    scrubbed = strip_credential_from_error_body(body)
    assert scrubbed["provider_id"] == "prov_openai_01"
    assert scrubbed["workspace_id"] == "ws-1"


# --- T858:ProviderCredentialContract -----------------------------

def test_T858_contract_persistable_only_default():
    c = ProviderCredentialContract(protocol="openai")
    assert c.is_level_allowed("L1_ENV") is True
    assert c.is_level_allowed("L2_SECRET_STORE") is True
    assert c.is_level_allowed("L3_FINGERPRINT") is True
    assert c.is_level_allowed("L0_INLINE") is False


def test_T859_contract_relax_persistable_only():
    c = ProviderCredentialContract(protocol="dev-echo", persistable_only=False)
    for level in CREDENTIAL_LEVELS:
        assert c.is_level_allowed(level) is True


# --- T860:治理护栏 · 不 import main -----------------------------

def test_T860_module_does_not_import_main():
    import app.adapters.provider.credential_ref as mod
    import inspect
    src = inspect.getsource(mod)
    assert "import main" not in src
    assert "from main" not in src
