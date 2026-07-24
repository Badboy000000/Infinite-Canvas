"""`IdentityBridge` — 权限 PR-9 生产切换骨架(Wave 3-N.9 Batch 2 主线 B)。

**定位**:legacy `owner` / `x_user_id` 弱语义 → `user_id` UUID 主键的**服务层解析器**;
是权限 PR-2 `legacy_mapper` 纯函数在运行时(middleware / CLI 迁移工具)的应用面。

**对齐**:
- [[40 实施计划/用户团队权限治理实施计划与PR清单]] PR-9 IdentityBridge 生产切换
- [[50 决策记录/决策 - 主键类型]] identity 全表 UUID + `legacy_owner_label` /
  `legacy_user_key`
- [[70 开发过程跟踪/治理机制/subagent 任务书回写义务清单#GM-22]] defaults-off 第 11 次复用

**当前 PR 交付**:
- `IdentityBridge.resolve(ctx) -> BridgeResolution` 单方法门面
- `BridgeResolution` frozen dataclass:`user_id / kind / matched_alias / fallback_reason`
- 4 种 kind 分支:`authenticated / legacy_bridged / legacy_unmatched / anonymous`
- 优先级:`x_user_id` (header/cookie) > `owner_hint` > `anonymous`

**明确不做**(承接边界):
- 不改路由行为(middleware 层只填充 `request.state.bridge_resolution`)
- 不实装 `enforce` 分支的下游路由改造(留给未来 PR)
- 不落盘、不 emit audit(audit 由 middleware 层调用 AuditService 承接)

**GM-16 pre-flight**(Lead 已确认):
- `IdentityBridge` / `BridgeResolution` / `BridgeKind` 全部为新公共符号 · greenfield
- 复用 `app/identity/legacy_mapper.py` (`resolve_legacy_owner` /
  `resolve_legacy_user_key`) · 不重造纯函数解析逻辑
- 复用 `app/identity/store.py` (`IdentityStore` protocol) · 依赖注入
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from .legacy_mapper import resolve_legacy_owner, resolve_legacy_user_key
from .request_context import RequestContext
from .schema import UserAliasRecord
from .store import IdentityStore

__all__ = [
    "BridgeKind",
    "BridgeResolution",
    "IdentityBridge",
]

# 4 种解析结果:
# - `authenticated`:PR-3 认证入口已产生 authenticated_user 会话(auth_mode ==
#   "authenticated_user") · 直取会话内 user_id · 未来 PR 落 session 表后写实。
#   本 PR 只暴露分类位;若 ctx.auth_mode == "authenticated_user" 但未拿到
#   `x_user_id` 则回退 anonymous 并记 fallback_reason。
# - `legacy_bridged`:通过 legacy signals (x_user_id / owner hint) 匹配到已
#   claim 的 UserAlias · 拿到 alias.user_id。
# - `legacy_unmatched`:legacy signals 存在但在 UserAlias 表内**未找到匹配**
#   · user_id = None · matched_alias = None · 供 shadow 模式 audit 消费。
# - `anonymous`:所有 legacy signals 均为空 · user_id = None。
BridgeKind = Literal[
    "authenticated",
    "legacy_bridged",
    "legacy_unmatched",
    "anonymous",
]


@dataclass(frozen=True)
class BridgeResolution:
    """`IdentityBridge.resolve` 返回结果(frozen · 可 hash · 可直接 audit)。

    - `user_id`:成功解析时为 UUID 字符串 · 否则 None。
    - `kind`:`authenticated / legacy_bridged / legacy_unmatched / anonymous` 4 态。
    - `matched_alias`:legacy_bridged 时为匹配到的 UserAliasRecord · 否则 None。
    - `fallback_reason`:未成功解析(legacy_unmatched / anonymous / authenticated
      无 user_id)时的可枚举原因字符串 · 供 audit consumer 分类统计。

    **frozen 语义**:该 dataclass 会被写入 `request.state.bridge_resolution`,
    下游消费(future enforce 分支 / audit sink)禁止修改 · 只读引用。
    """

    user_id: Optional[str]
    kind: BridgeKind
    matched_alias: Optional[UserAliasRecord] = None
    fallback_reason: Optional[str] = None


class IdentityBridge:
    """legacy 身份线索 → user_id 服务层门面。

    典型使用:
        bridge = IdentityBridge(store=JsonIdentityStore(Path("data/identity")))
        resolution = bridge.resolve(request_context)
        # resolution.kind ∈ {authenticated, legacy_bridged, legacy_unmatched, anonymous}
        # resolution.user_id 可能 None(未匹配 / 匿名)

    **优先级**(RequestContext 内多个字段并存时):
    1. `auth_mode == "authenticated_user"` → 尝试 `x_user_id` 直取(未来 PR 换
       session 表查询)· 拿不到则 fallback anonymous 记 reason
    2. `x_user_id` (header or 由 middleware 塞入的 cookie 值) 存在 → 精确匹配
       `kind="x_user_id"` alias
    3. `legacy_user_key` (由 middleware 从 cookie/query/x_user_id 派生) →
       fallback 到 `resolve_legacy_owner` (兼容 conversation_dir /
       cookie_user / ip_derived 三种 kind)
    4. 均无 → `anonymous`

    **线程安全**:`IdentityBridge` 本身无可变状态 · `store.list_user_aliases()`
    每次调用重读磁盘(JsonIdentityStore 语义) · 无缓存一致性问题。
    """

    def __init__(self, store: IdentityStore) -> None:
        self._store = store

    # ---- 主 API ----------------------------------------------------------

    def resolve(self, request_context: RequestContext) -> BridgeResolution:
        """从 RequestContext 三类来源解析 user_id。

        RequestContext 已存在字段(权限 PR-0 冻结):
        - `x_user_id`:header 原值
        - `legacy_user_key`:cookie / query / x_user_id 派生的最终 key
        - `auth_mode`:三态字面量

        注意:本 PR 不新增 `legacy_x_user_id` / `legacy_owner_hint` /
        `cookie_x_user_id` 三个"来源"字段(任务书标注为设计意图) · 因为
        `RequestContext` 冻结契约不许在旧 9 字段中间插入 · 只可尾附加。
        实际实现直接消费已有的 `x_user_id` + `legacy_user_key` 字段即可覆盖
        全部三来源(cookie / query 已在 middleware 层派生到 legacy_user_key)。
        """
        # 分支 1:authenticated_user(PR-3 认证入口路径)
        if request_context.auth_mode == "authenticated_user":
            if request_context.x_user_id:
                # PR-3 authenticated 路径应保证 x_user_id = user UUID
                return BridgeResolution(
                    user_id=request_context.x_user_id,
                    kind="authenticated",
                    matched_alias=None,
                    fallback_reason=None,
                )
            # 认证宣称但没有 user_id · 走降级 · 供 shadow audit 消费
            return BridgeResolution(
                user_id=None,
                kind="anonymous",
                matched_alias=None,
                fallback_reason="authenticated_mode_without_x_user_id",
            )

        aliases = self._store.list_user_aliases()

        # 分支 2:x_user_id 精确匹配 kind="x_user_id" alias
        if request_context.x_user_id:
            alias = resolve_legacy_user_key(request_context.x_user_id, aliases)
            if alias is not None:
                user_id = alias.get("user_id")
                if user_id:
                    return BridgeResolution(
                        user_id=user_id,
                        kind="legacy_bridged",
                        matched_alias=alias,
                        fallback_reason=None,
                    )
                # alias 存在但未 claim 到 user
                return BridgeResolution(
                    user_id=None,
                    kind="legacy_unmatched",
                    matched_alias=alias,
                    fallback_reason="alias_matched_but_no_user_id",
                )
            # x_user_id 有值但未匹配 alias
            return BridgeResolution(
                user_id=None,
                kind="legacy_unmatched",
                matched_alias=None,
                fallback_reason="x_user_id_no_alias_match",
            )

        # 分支 3:legacy_user_key fallback (owner hint from cookie / query /
        # conversation_dir · 走 resolve_legacy_owner 兼容多 kind)
        if request_context.legacy_user_key:
            alias = resolve_legacy_owner(
                request_context.legacy_user_key, aliases
            )
            if alias is not None:
                user_id = alias.get("user_id")
                if user_id:
                    return BridgeResolution(
                        user_id=user_id,
                        kind="legacy_bridged",
                        matched_alias=alias,
                        fallback_reason=None,
                    )
                return BridgeResolution(
                    user_id=None,
                    kind="legacy_unmatched",
                    matched_alias=alias,
                    fallback_reason="alias_matched_but_no_user_id",
                )
            return BridgeResolution(
                user_id=None,
                kind="legacy_unmatched",
                matched_alias=None,
                fallback_reason="legacy_user_key_no_alias_match",
            )

        # 分支 4:所有 legacy signals 均为空
        return BridgeResolution(
            user_id=None,
            kind="anonymous",
            matched_alias=None,
            fallback_reason=None,
        )
