"""`tools/bridge_migrate.py` 单元测试(权限 PR-9 · Wave 3-N.9 Batch 2 主线 B)。

覆盖 T566-T570(≥5 tests · CLI 行为):

- scan_resources 从画布 + 素材库正确提取 owner
- run_dry_run 返回 matrix + summary · 不写盘
- run_apply 幂等(重复调用 3 次结果字节相同)
- run_report 从 state.json 生成对账
- write_bridge_state 稳定序列化(sort_keys + indent=2 + 尾换行)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from app.identity.bridge import IdentityBridge
from app.identity.schema import UserAliasRecord
from tools.bridge_migrate import (
    apply_matrix_to_state,
    build_report_from_state,
    build_resolution_matrix,
    read_bridge_state,
    run_apply,
    run_dry_run,
    run_report,
    scan_resources,
    write_bridge_state,
)

TS = "2026-07-24T00:00:00+00:00"
WS = "ws-default-00000000-0000-0000-0000-000000000000"


def _alias(kind: str, key: str, alias_id: str, user_id: str) -> UserAliasRecord:
    return {
        "id": alias_id,
        "user_id": user_id,
        "kind": kind,  # type: ignore[typeddict-item]
        "legacy_user_key": key,
        "workspace_id": WS,
        "created_at": TS,
    }


class _FakeStore:
    def __init__(self, aliases: List[UserAliasRecord]) -> None:
        self._aliases = aliases

    def list_user_aliases(self) -> List[UserAliasRecord]:
        return list(self._aliases)

    def __getattr__(self, item: str) -> Any:
        raise AttributeError(item)


@pytest.fixture()
def sample_env(tmp_path: Path) -> Dict[str, Path]:
    """在临时目录构造 canvas / asset library / identity dir 结构。"""
    canvas_dir = tmp_path / "canvases"
    canvas_dir.mkdir()
    # canvas 1:owner="Alice"
    (canvas_dir / "c1.json").write_text(
        json.dumps({"id": "c1", "owner": "Alice"}, ensure_ascii=False),
        encoding="utf-8",
    )
    # canvas 2:owner="conv-c"
    (canvas_dir / "c2.json").write_text(
        json.dumps({"id": "c2", "owner": "conv-c"}, ensure_ascii=False),
        encoding="utf-8",
    )
    # canvas 3:owner="unknown-user"(不会匹配)
    (canvas_dir / "c3.json").write_text(
        json.dumps({"id": "c3", "owner": "unknown-user"}, ensure_ascii=False),
        encoding="utf-8",
    )
    # asset library:list 语义 · 一条 owner=Alice
    asset_file = tmp_path / "asset_library.json"
    asset_file.write_text(
        json.dumps(
            {"assets": [{"id": "a1", "owner": "Alice"}]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    state_file = tmp_path / "bridge_state.json"
    identity_dir = tmp_path / "identity"
    identity_dir.mkdir()
    return {
        "canvas_dir": canvas_dir,
        "asset_file": asset_file,
        "state_file": state_file,
        "identity_dir": identity_dir,
    }


# ---------------------------------------------------------------------------
# T566: scan_resources 正确扫描画布 + 素材
# ---------------------------------------------------------------------------


def test_T566_scan_resources(sample_env: Dict[str, Path]) -> None:
    got = scan_resources(
        canvas_dir=sample_env["canvas_dir"],
        asset_file=sample_env["asset_file"],
    )
    keys = sorted((rtype, rid) for rtype, rid, _ in got)
    assert keys == [
        ("asset", "a1"),
        ("canvas", "c1"),
        ("canvas", "c2"),
        ("canvas", "c3"),
    ]
    # owner 提取
    owners_by_key = {(rt, rid): owner for rt, rid, owner in got}
    assert owners_by_key[("canvas", "c1")] == "Alice"
    assert owners_by_key[("canvas", "c2")] == "conv-c"
    assert owners_by_key[("canvas", "c3")] == "unknown-user"
    assert owners_by_key[("asset", "a1")] == "Alice"


# ---------------------------------------------------------------------------
# T567: build_resolution_matrix + summarize
# ---------------------------------------------------------------------------


def test_T567_build_resolution_matrix(sample_env: Dict[str, Path]) -> None:
    aliases = [
        _alias("cookie_user", "Alice", "alias-1", user_id="uuid-alice"),
        _alias("conversation_dir", "conv-c", "alias-2", user_id="uuid-conv"),
    ]
    bridge = IdentityBridge(_FakeStore(aliases))  # type: ignore[arg-type]
    resources = scan_resources(
        canvas_dir=sample_env["canvas_dir"],
        asset_file=sample_env["asset_file"],
    )
    matrix = build_resolution_matrix(bridge, resources)
    assert matrix["canvas:c1"]["user_id"] == "uuid-alice"
    assert matrix["canvas:c1"]["kind"] == "legacy_bridged"
    assert matrix["canvas:c2"]["user_id"] == "uuid-conv"
    assert matrix["canvas:c3"]["user_id"] is None
    assert matrix["canvas:c3"]["kind"] == "legacy_unmatched"
    assert matrix["asset:a1"]["user_id"] == "uuid-alice"


# ---------------------------------------------------------------------------
# T568: run_dry_run 不写盘
# ---------------------------------------------------------------------------


def test_T568_dry_run_does_not_write(sample_env: Dict[str, Path], tmp_path: Path) -> None:
    # 构造 identity dir 内的最小 user_aliases.json
    _seed_identity_dir(sample_env["identity_dir"])
    state_file = sample_env["state_file"]
    assert not state_file.exists()
    result = run_dry_run(
        identity_dir=sample_env["identity_dir"],
        canvas_dir=sample_env["canvas_dir"],
        asset_file=sample_env["asset_file"],
    )
    assert not state_file.exists()  # 不写盘
    assert "matrix" in result
    assert "summary" in result
    assert result["summary"]["total"] == 4


# ---------------------------------------------------------------------------
# T569: run_apply 幂等(重复 3 次字节相同)
# ---------------------------------------------------------------------------


def test_T569_apply_idempotent(sample_env: Dict[str, Path]) -> None:
    _seed_identity_dir(sample_env["identity_dir"])
    # 第一次
    run_apply(
        identity_dir=sample_env["identity_dir"],
        canvas_dir=sample_env["canvas_dir"],
        asset_file=sample_env["asset_file"],
        state_file=sample_env["state_file"],
        timestamp="2026-07-24T00:00:00+00:00",
    )
    first_bytes = sample_env["state_file"].read_bytes()
    # 第二次(相同 timestamp)
    run_apply(
        identity_dir=sample_env["identity_dir"],
        canvas_dir=sample_env["canvas_dir"],
        asset_file=sample_env["asset_file"],
        state_file=sample_env["state_file"],
        timestamp="2026-07-24T00:00:00+00:00",
    )
    second_bytes = sample_env["state_file"].read_bytes()
    # 第三次(不同 timestamp · 已有条目应保持不动 · 结果字节相同)
    run_apply(
        identity_dir=sample_env["identity_dir"],
        canvas_dir=sample_env["canvas_dir"],
        asset_file=sample_env["asset_file"],
        state_file=sample_env["state_file"],
        timestamp="2027-01-01T00:00:00+00:00",  # 换 timestamp
    )
    third_bytes = sample_env["state_file"].read_bytes()
    assert first_bytes == second_bytes
    assert second_bytes == third_bytes  # 幂等 · 相同 user_id 不刷新 matched_at


# ---------------------------------------------------------------------------
# T570: run_report 从 state.json 正确读
# ---------------------------------------------------------------------------


def test_T570_run_report(sample_env: Dict[str, Path]) -> None:
    _seed_identity_dir(sample_env["identity_dir"])
    run_apply(
        identity_dir=sample_env["identity_dir"],
        canvas_dir=sample_env["canvas_dir"],
        asset_file=sample_env["asset_file"],
        state_file=sample_env["state_file"],
    )
    report = run_report(sample_env["state_file"])
    assert report["schema_version"] == "v1_bridge"
    # 3 条匹配成功(Alice x2, conv-c x1;unknown-user 未写入)
    assert report["total_resolutions"] == 3


# ---------------------------------------------------------------------------
# T571: read_bridge_state 缺失文件返回空模板
# ---------------------------------------------------------------------------


def test_T571_read_missing_state(tmp_path: Path) -> None:
    state = read_bridge_state(tmp_path / "nowhere.json")
    assert state["_schema_version"] == "v1_bridge"
    assert state["resolutions"] == {}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _seed_identity_dir(identity_dir: Path) -> None:
    """写入最小 identity JSON 文件集 · 供 JsonIdentityStore.list_user_aliases 使用。"""
    aliases_file = identity_dir / "user_aliases.json"
    aliases_file.write_text(
        json.dumps(
            {
                "_schema_version": 1,
                "aliases": [
                    {
                        "id": "alias-1",
                        "user_id": "uuid-alice",
                        "kind": "cookie_user",
                        "legacy_user_key": "Alice",
                        "workspace_id": WS,
                        "created_at": TS,
                    },
                    {
                        "id": "alias-2",
                        "user_id": "uuid-conv",
                        "kind": "conversation_dir",
                        "legacy_user_key": "conv-c",
                        "workspace_id": WS,
                        "created_at": TS,
                    },
                ],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
