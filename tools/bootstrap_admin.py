"""Bootstrap `system_admin` 用户 CLI(权限 PR-5 · Wave 3-N.9 Batch 2 主线 A)。

**定位**:一次性(或幂等重跑)脚本 · 在治理期把首任 `system_admin` 用户落库,
供 `AUTH_ENABLED=true` 环境登录。

**运行前提**:
- `IC_BOOTSTRAP_ADMIN_PASSWORD` 环境变量已设(≥12 字符)· 明文只在内存 · 用完
  即清 · **绝不落 config / log / repr**。
- Alembic 已 `python main.py migrate head` · `auth_credentials` 表已存在。
- `data/identity/users.json` / `auth_migration_state.json` 已 bootstrap 完成
  (由 `tools/migrate_identity_bootstrap.py` 完成)。

**用法**::

    export IC_BOOTSTRAP_ADMIN_PASSWORD='<>=12chars-random-secret>'
    python tools/bootstrap_admin.py --admin-username admin --create-if-missing
    unset IC_BOOTSTRAP_ADMIN_PASSWORD   # 立即清空!

**幂等**:
- 首次:落 `auth_credentials` + `users.json` + `auth_migration_state.notes`
  内记 `bootstrap:system_admin:<user_id>`;`bootstrap_completed_at` 若未设则 set。
- 重复:检测到用户已存在 → 打印 `admin already bootstrapped` 并 exit 0
  (除非 `--force-reset`)。
- `--force-reset`:重置密码 hash + 清 failed_attempts / locked_until。
  **不重新生成 user_id**(保留稳定 UUID)。

**P0 密钥零泄漏**:
- 密码只从 env 读 · 不接受 argv 传入 · 不打印 · 不 log
- Exception 消息中不含明文密码 / hash
- 完成后提示用户从 env 清空

**GM-16 pre-flight**:`bootstrap_admin_password` / `run_bootstrap` /
`BootstrapResult` 全部为新公共符号 · greenfield 确认。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ---- 环境常量 --------------------------------------------------------------

ENV_BOOTSTRAP_PASSWORD = "IC_BOOTSTRAP_ADMIN_PASSWORD"

MIN_PASSWORD_LENGTH = 12  # 与 app.services.auth.MIN_PASSWORD_LENGTH 对齐

BOOTSTRAP_NOTE_PREFIX = "bootstrap:system_admin:"


# ---- 结果对象 --------------------------------------------------------------


@dataclass(frozen=True)
class BootstrapResult:
    """bootstrap 幂等结果 · 供测试断言与调用方消费。

    - `outcome`:`"created"` / `"skipped"` / `"reset"` 三态
    - `user_id`:目标用户 UUID(创建时新生成 · 幂等 skip 时读原值 · 从不返回 None)
    - `username`:管理员用户名
    - `notes`:可选可读注释(如"env cleared reminder shown")
    """

    outcome: str  # "created" | "skipped" | "reset"
    user_id: str
    username: str
    notes: str = ""


# ---- 核心逻辑 --------------------------------------------------------------


def _load_password_from_env() -> str:
    """从 env 读密码 · 缺失 / 空字符串 / 太短 → SystemExit(2)。"""
    raw = os.environ.get(ENV_BOOTSTRAP_PASSWORD, "")
    if not raw:
        print(
            json.dumps(
                {
                    "error": "missing_password_env",
                    "hint": f"请先设置 env {ENV_BOOTSTRAP_PASSWORD} 后重试",
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        sys.exit(2)
    if len(raw) < MIN_PASSWORD_LENGTH:
        print(
            json.dumps(
                {
                    "error": "password_too_weak",
                    "min_length": MIN_PASSWORD_LENGTH,
                    "hint": "请使用强随机密码(至少 12 字符)",
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        sys.exit(2)
    return raw


def _find_existing_admin(username: str) -> Optional[str]:
    """在 `auth_credentials` 表内查找 username · 返回 user_id 或 None。"""
    from sqlalchemy import select

    from app.db.session import get_session
    from app.services.auth.tables import auth_credentials

    with get_session() as session:
        row = session.execute(
            select(auth_credentials.c.user_id).where(
                auth_credentials.c.username == username
            )
        ).first()
        return row.user_id if row is not None else None


def _insert_user_row(user_id: str, username: str) -> None:
    """在 `user` 基础表插入一行(若不存在)· 幂等。"""
    from sqlalchemy import text

    from app.db.session import get_session

    now = datetime.now(timezone.utc)
    with get_session() as session:
        row = session.execute(
            text("SELECT id FROM user WHERE id = :id"), {"id": user_id}
        ).first()
        if row is None:
            session.execute(
                text(
                    "INSERT INTO user (id, legacy_user_key, display_name, "
                    "avatar_url, created_at, updated_at) "
                    "VALUES (:id, :key, :name, NULL, :now, :now)"
                ),
                {"id": user_id, "key": username, "name": username, "now": now},
            )
            session.commit()


def _insert_auth_credentials(user_id: str, username: str, password_hash: str) -> None:
    """插入 `auth_credentials` 行(caller 已确认不存在)。"""
    from app.db.session import get_session
    from app.services.auth.tables import auth_credentials

    now = datetime.now(timezone.utc)
    with get_session() as session:
        session.execute(
            auth_credentials.insert().values(
                user_id=user_id,
                username=username,
                password_hash=password_hash,
                must_change_password=0,
                failed_attempts=0,
                locked_until=None,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()


def _reset_auth_credentials(user_id: str, password_hash: str) -> None:
    """`--force-reset`:覆盖 password_hash + 清失败计数/锁定 · 保留 user_id。"""
    from sqlalchemy import text

    from app.db.session import get_session

    now = datetime.now(timezone.utc)
    with get_session() as session:
        session.execute(
            text(
                "UPDATE auth_credentials SET password_hash = :ph, "
                "failed_attempts = 0, locked_until = NULL, "
                "must_change_password = 0, updated_at = :now "
                "WHERE user_id = :uid"
            ),
            {"ph": password_hash, "now": now, "uid": user_id},
        )
        session.commit()


def _write_users_json_entry(base_dir: Path, user_id: str, username: str) -> None:
    """把 admin 用户写入 `data/identity/users.json`(schema-safe · 幂等)。"""
    users_path = base_dir / "users.json"
    payload = json.loads(users_path.read_text(encoding="utf-8"))
    users = payload.setdefault("users", {})
    now = datetime.now(timezone.utc).isoformat()
    if user_id in users:
        # 幂等:字段就位则不动
        entry = users[user_id]
        entry.setdefault("id", user_id)
        entry.setdefault("username", username)
        entry.setdefault("status", "active")
        entry.setdefault("created_at", now)
    else:
        users[user_id] = {
            "id": user_id,
            "username": username,
            "status": "active",
            "created_at": now,
        }
    # 稳定序列化(与 JsonIdentityStore._write_json 对齐)
    _atomic_write_json(users_path, payload)


def _record_bootstrap_note(base_dir: Path, user_id: str) -> None:
    """在 `auth_migration_state.json` 的 notes 追加 bootstrap marker(去重)。

    并把 `bootstrap_completed_at` 从 null 首次落值。
    """
    state_path = base_dir / "auth_migration_state.json"
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    notes = payload.setdefault("notes", [])
    marker = f"{BOOTSTRAP_NOTE_PREFIX}{user_id}"
    if marker not in notes:
        notes.append(marker)
    if not payload.get("bootstrap_completed_at"):
        payload["bootstrap_completed_at"] = datetime.now(timezone.utc).isoformat()
    _atomic_write_json(state_path, payload)


def _atomic_write_json(path: Path, payload) -> None:
    """稳定序列化 + 原子替换 · 幂等:同内容多次写入产生字节相同文件。"""
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
        fh.write("\n")
    tmp.replace(path)


def run_bootstrap(
    *,
    admin_username: str,
    create_if_missing: bool,
    force_reset: bool,
    identity_dir: Optional[Path] = None,
) -> BootstrapResult:
    """执行 bootstrap 主流程(可测试单元 · 不依赖 argparse)。

    参数:
    - `admin_username`:管理员用户名(唯一)
    - `create_if_missing`:目标用户不存在时是否创建(默认 True · CLI 层传入)
    - `force_reset`:强制重置密码 hash(幂等 skip 分支)
    - `identity_dir`:`data/identity/` 目录路径(默认 `Path("data/identity")`)

    返回 `BootstrapResult` · outcome 三态。密码从 env 读 · 不作参数传入。
    """
    base_dir = identity_dir if identity_dir is not None else Path("data/identity")
    if not base_dir.is_dir():
        print(
            json.dumps(
                {
                    "error": "identity_dir_missing",
                    "path": str(base_dir),
                    "hint": "先跑 tools/migrate_identity_bootstrap.py",
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        sys.exit(3)

    # 密码从 env 读(SystemExit if missing/weak)
    password = _load_password_from_env()

    # 惰性 import(避免顶部循环 · argon2 依赖)
    from app.services.auth import PasswordHasher

    hasher = PasswordHasher()
    password_hash = hasher.hash(password)
    # 消除内存中明文密码引用(尽量减少内存暴露 · 不能保证 GC)
    del password

    existing_user_id = _find_existing_admin(admin_username)

    if existing_user_id is not None:
        if force_reset:
            _reset_auth_credentials(existing_user_id, password_hash)
            _record_bootstrap_note(base_dir, existing_user_id)
            return BootstrapResult(
                outcome="reset",
                user_id=existing_user_id,
                username=admin_username,
                notes="password reset; existing user_id preserved",
            )
        return BootstrapResult(
            outcome="skipped",
            user_id=existing_user_id,
            username=admin_username,
            notes="admin already bootstrapped",
        )

    if not create_if_missing:
        print(
            json.dumps(
                {
                    "error": "admin_missing_and_no_create_flag",
                    "hint": "pass --create-if-missing to create",
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        sys.exit(4)

    # 创建新 admin
    user_id = str(uuid.uuid4())
    _insert_user_row(user_id, admin_username)
    _insert_auth_credentials(user_id, admin_username, password_hash)
    _write_users_json_entry(base_dir, user_id, admin_username)
    _record_bootstrap_note(base_dir, user_id)

    return BootstrapResult(
        outcome="created",
        user_id=user_id,
        username=admin_username,
        notes="new system_admin bootstrapped",
    )


# ---- CLI 入口 --------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bootstrap_admin",
        description=(
            "Bootstrap first system_admin. "
            "Password read from env IC_BOOTSTRAP_ADMIN_PASSWORD only."
        ),
    )
    parser.add_argument(
        "--admin-username",
        default="admin",
        help="管理员用户名(默认 'admin')",
    )
    parser.add_argument(
        "--create-if-missing",
        action="store_true",
        help="用户不存在时创建(推荐首次执行传入)",
    )
    parser.add_argument(
        "--force-reset",
        action="store_true",
        help="用户存在时强制重置密码 hash(user_id 不变)",
    )
    parser.add_argument(
        "--identity-dir",
        default="data/identity",
        help="identity JSON 目录路径(默认 data/identity)",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    result = run_bootstrap(
        admin_username=args.admin_username,
        create_if_missing=args.create_if_missing,
        force_reset=args.force_reset,
        identity_dir=Path(args.identity_dir),
    )

    # 输出结果 JSON(不含密码 hash · 不含 password)
    print(
        json.dumps(
            {
                "outcome": result.outcome,
                "user_id": result.user_id,
                "username": result.username,
                "notes": result.notes,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )

    # 完成后提示清 env(即使 skipped/reset 也提示)
    print(
        f"[reminder] please immediately: unset {ENV_BOOTSTRAP_PASSWORD}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover — CLI entry
    sys.exit(main())
