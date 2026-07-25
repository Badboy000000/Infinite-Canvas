"""Provider PR-11 · CLI Provider 强审计契约测试。"""
from __future__ import annotations

import pytest

from app.adapters.provider.cli_audit import (
    CLI_MODES,
    CLI_PROVIDERS,
    CliAuditSnapshot,
    build_cli_mode_matrix,
    resolve_effective_mode,
    sanitize_cli_argv,
)


def test_TB60_cli_providers_frozen():
    assert CLI_PROVIDERS == ("jimeng", "gemini_cli", "codex_cli")


def test_TB61_cli_modes_frozen():
    assert CLI_MODES == ("disabled", "shared_system", "per_user")


def test_TB62_local_all_per_user():
    matrix = build_cli_mode_matrix("local_personal")
    for p in CLI_PROVIDERS:
        assert matrix[p] == "per_user"


def test_TB63_public_disables_jimeng():
    """治理方案硬约束:public_team 模式 jimeng 必须 disabled。"""
    matrix = build_cli_mode_matrix("public_team")
    assert matrix["jimeng"] == "disabled"


def test_TB64_intranet_matrix():
    matrix = build_cli_mode_matrix("intranet_team")
    assert matrix["jimeng"] == "shared_system"
    assert matrix["gemini_cli"] == "shared_system"
    assert matrix["codex_cli"] == "per_user"


def test_TB65_resolve_effective_mode_shortcut():
    assert resolve_effective_mode("public_team", "jimeng") == "disabled"
    assert resolve_effective_mode("local_personal", "codex_cli") == "per_user"


def test_TB66_unknown_deployment_rejected():
    with pytest.raises(ValueError, match="unknown deployment mode"):
        build_cli_mode_matrix("evil")  # type: ignore[arg-type]


def test_TB67_snapshot_rejects_disabled_mode():
    """disabled 时不该被 dispatch · 也不该生成 snapshot。"""
    with pytest.raises(ValueError, match="mode=disabled"):
        CliAuditSnapshot(
            provider="jimeng", mode="disabled", caller_kind="user",
            caller_id="u1", argv_masked=(), exit_code=0, elapsed_ms=1000,
        )


def test_TB68_snapshot_rejects_bad_provider():
    with pytest.raises(ValueError, match="provider"):
        CliAuditSnapshot(
            provider="foo", mode="per_user", caller_kind="user",  # type: ignore[arg-type]
            caller_id="u1", argv_masked=("cmd",), exit_code=0, elapsed_ms=100,
        )


def test_TB69_snapshot_rejects_leaked_argv():
    with pytest.raises(ValueError, match="credential-like"):
        CliAuditSnapshot(
            provider="gemini_cli", mode="per_user", caller_kind="user",
            caller_id="u1",
            argv_masked=("--auth", "Bearer sk-live-secret"),
            exit_code=0, elapsed_ms=100,
        )


def test_TB70_sanitize_masks_apikey_arg():
    argv = ("cli", "--api-key=sk-live-abcdef-1234567890", "prompt")
    masked = sanitize_cli_argv(argv)
    assert "sk-live" not in masked[1]
    assert "***" in masked[1]


def test_TB71_sanitize_masks_bare_long_hex():
    argv = ("cli", "run", "abcdef1234567890abcdef1234567890abcdef")
    masked = sanitize_cli_argv(argv)
    assert masked[2] == "***"


def test_TB72_sanitize_preserves_short_tokens():
    argv = ("cli", "run", "hello")
    assert sanitize_cli_argv(argv) == argv


def test_TB73_module_does_not_import_main():
    import app.adapters.provider.cli_audit as mod
    import inspect
    src = inspect.getsource(mod)
    assert "import main" not in src
    assert "from main" not in src
