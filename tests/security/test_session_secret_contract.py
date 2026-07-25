"""部署 PR-08 · SESSION_SECRET 启动强校验骨架契约测试。"""
from __future__ import annotations

import pytest

from app.security.session_secret import (
    SESSION_SECRET_STARTUP_ENFORCE_ENV,
    SecretValidationError,
    SessionSecretPolicy,
    build_policy,
    enforce_secret,
    is_session_secret_startup_enforce_enabled,
    validate_secret,
)


def test_TA30_defaults_off(monkeypatch):
    monkeypatch.delenv(SESSION_SECRET_STARTUP_ENFORCE_ENV, raising=False)
    assert is_session_secret_startup_enforce_enabled() is False


def test_TA31_build_policy_three_modes():
    for mode in ("local_personal", "intranet_team", "public_team"):
        p = build_policy(mode)  # type: ignore[arg-type]
        assert isinstance(p, SessionSecretPolicy)
    with pytest.raises(ValueError, match="unknown deployment mode"):
        build_policy("evil_mode")  # type: ignore[arg-type]


def test_TA32_local_personal_relaxed():
    p = build_policy("local_personal")
    assert p.min_length == 16
    assert p.reject_dummy_values is False


def test_TA33_intranet_team_stricter():
    p = build_policy("intranet_team")
    assert p.min_length == 32
    assert p.reject_dummy_values is True


def test_TA34_public_team_strictest():
    p = build_policy("public_team")
    assert p.min_length == 64
    assert p.reject_dummy_values is True
    assert p.entropy_check is True


def test_TA35_length_below_minimum_fails():
    r = validate_secret("shortsecret", mode="local_personal", kind="session")
    assert r.ok is False
    assert any("min_length" in reason for reason in r.reasons)


def test_TA36_long_enough_local_ok():
    secret = "a" * 20
    r = validate_secret(secret, mode="local_personal", kind="session")
    # local_personal 不做熵检查也不 reject dummy · 只看长度
    assert r.ok is True


@pytest.mark.parametrize("dummy", [
    "dev-secret-that-is-long-enough-32-chars",
    "changeme-again-yet-another-32chars",
    "test1234567890abcdefghijklmnop123",
    "default-secret-1234567890abcdefg1",
])
def test_TA37_intranet_rejects_dummy_substrings(dummy):
    assert len(dummy) >= 32
    r = validate_secret(dummy, mode="intranet_team", kind="csrf")
    assert r.ok is False
    assert any("dummy" in reason for reason in r.reasons)


def test_TA38_public_team_entropy_check_all_letters():
    secret = "a" * 70  # 长度够 · 但全字母
    r = validate_secret(secret, mode="public_team", kind="session")
    assert r.ok is False
    assert any("all-letters" in reason for reason in r.reasons)


def test_TA39_public_team_entropy_check_all_digits():
    secret = "1" * 70
    r = validate_secret(secret, mode="public_team", kind="session")
    assert r.ok is False
    assert any("all-digits" in reason for reason in r.reasons)


def test_TA40_public_team_mixed_ok():
    secret = "Xk7$" + "a1B2c3D4e5F6g7H8" * 4  # 长 · 混合 · 无 dummy
    assert len(secret) >= 64
    r = validate_secret(secret, mode="public_team", kind="session")
    assert r.ok is True, r.reasons


def test_TA41_enforce_raises_on_failure():
    with pytest.raises(SecretValidationError, match="session secret"):
        enforce_secret("short", mode="local_personal", kind="session")


def test_TA42_enforce_error_message_does_not_leak_secret():
    """异常消息严禁回显 secret 原文。"""
    # 长度足以过 min_length=32 · 但含 dummy 子串触发失败 · 用于验证错误消息不回显 secret 原文
    secret = "prod-changeme-32chars-abcdefghij"
    assert len(secret) >= 32
    with pytest.raises(SecretValidationError) as excinfo:
        enforce_secret(secret, mode="intranet_team", kind="session")
    msg = str(excinfo.value)
    assert secret not in msg
    assert "changeme" not in msg or msg.count("changeme") <= 1  # reason 提到 dummy 子串一次可容忍
    # 但绝对不许把完整 secret 拼接进消息
    assert "prod-changeme-32chars-abcdefghij" not in msg


def test_TA43_report_kind_and_mode_captured():
    r = validate_secret("x" * 100, mode="local_personal", kind="csrf")
    assert r.kind == "csrf"
    assert r.mode == "local_personal"


def test_TA44_module_does_not_import_main():
    import app.security.session_secret as mod
    import inspect
    src = inspect.getsource(mod)
    assert "import main" not in src
    assert "from main" not in src
