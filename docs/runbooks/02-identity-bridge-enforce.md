# Runbook 02 · IdentityBridge 硬启用

**Flag**: `IDENTITY_BRIDGE_ENFORCE`
**观察窗口**: 7 天
**回滚代价**: 5 分钟(flag off + 重启)
**骨架承接**: `IdentityBridgeMiddleware`(commit f9a346a 挂载点 · commit 8c72dd3 生产切换骨架)

## 目的

从骨架层的 `skeleton=off`(仅日志)切到 `enforce=on`(拒绝无 identity 的请求)。

## 前置条件

- [ ] 5 · audit 已启用(需要 audit 记录 identity_bridge 拒绝事件)
- [ ] `/api/auth/login` 全流程可用 · admin 已 bootstrap(`python tools/bootstrap_admin.py`)
- [ ] 已确认所有前端页面都通过 login 拿到 session token
- [ ] KB `70 开发过程跟踪/生产切换日志/` 已建当次翻转日志

## 分阶段 checklist

### Phase 0 · 准备(D-day 前 1 天)

- [ ] `python scripts/production/dry_run_flag_flip.py --flag IDENTITY_BRIDGE_ENFORCE` 打印计划
- [ ] 确认 audit sink 已收到 `identity_bridge_skeleton_pass` 事件(说明骨架已在跑)· 至少累计 100 条
- [ ] 用户/运维确认接受 7 天窗口内可能出现的旧 client 401 反馈

### Phase 1 · 启用(D-day)

- [ ] `.env`:`IDENTITY_BRIDGE_ENFORCE=on`
- [ ] 重启 app · 立即用 admin 账号 login 一次 · 确认能进主页
- [ ] 观察前 30 分钟 audit 事件:`identity_bridge_reject` 应 <10 条/分钟 · 否则说明有大量旧 client
- [ ] 若 >10 条/分钟 → 立即回滚 · 排查原因

### Phase 2 · 观察(D → D+7)

- [ ] 每天:`python scripts/production/observation_window_verify.py --flag IDENTITY_BRIDGE_ENFORCE`
- [ ] 关注指标:
  - `identity_bridge_reject` 数量(应逐日下降)
  - `/api/auth/login` 成功率(应 ≥99%)
  - 用户 401 反馈(应 0)
- [ ] 7 天末:reject <1 条/天 · 进入稳态

## 回滚 SOP

1. `.env`:`IDENTITY_BRIDGE_ENFORCE=off`
2. 重启 app · 5 分钟内完成
3. audit 事件回到 `identity_bridge_skeleton_pass`(仅日志)
4. 在 KB 翻转日志里记录回滚原因 · 排查后再重试

## 常见故障

| 现象 | 可能原因 | 处理 |
|---|---|---|
| 大量 `identity_bridge_reject` 事件 | 旧 client 没走 login · 直接命中 API | 排查前端 · 补 login 流程 |
| admin 也被拒 | admin session 未创建 / cookie 未续 | 走 `tools/bootstrap_admin.py` 重新拿 session |
| 部分 API 依然放行无 identity | 中间件挂载点漏 · 或有 exempt route | 检查 `main.py` middleware 顺序 · 检查 exempt list |

## 相关

- 骨架: commit `8c72dd3` `f9a346a`(IdentityBridge 生产切换骨架 + 挂载点)
- 权限治理: [[40 实施计划/用户团队权限治理实施计划与PR清单]] PR-9
- Audit: [[docs/runbooks/05-audit-enable]]
