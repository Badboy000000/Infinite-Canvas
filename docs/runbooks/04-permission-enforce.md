# Runbook 04 · 权限强制启用

**Flag**: `PERMISSION_ENFORCE`
**观察窗口**: 7 天
**回滚代价**: 5 分钟(flag off + 重启)
**骨架承接**: commit `ee1ce27`(PR-5 高风险接口 `require_permission` dep)+ commit `cc3ae4e`(PR-10 SqliteIdentityStore)

## 目的

从骨架层 `skeleton=off`(仅日志)切到 `enforce=on`(权限不足即 403)。

## 前置条件

- [ ] 02 identity-bridge 已启用 · 03 csrf+cors 已启用 · 05 audit 已启用
- [ ] `python tools/bootstrap_admin.py` 已跑 · admin 账号有 `admin` role
- [ ] 所有需要权限的 endpoint 已挂 `require_permission` dep(骨架层已完成)
- [ ] 用户已通过 UI 或 CLI 给业务账号分配了所需 role

## 分阶段 checklist

### Phase 0 · 准备

- [ ] 列出所有需要权限的 endpoint · 检查每个 dep 是否挂对
- [ ] 用普通账号(无 admin role)手动测:调 admin-only endpoint 应在 skeleton 期日志出现 `permission_denied_skeleton`
- [ ] 累计 `permission_denied_skeleton` 事件 ≥100 条(证明骨架已在跑)

### Phase 1 · 启用(D-day)

- [ ] `.env`:`PERMISSION_ENFORCE=on`
- [ ] 重启 · admin 账号所有操作应 200
- [ ] 普通账号调 admin-only endpoint · 应 403 + audit 事件 `permission_denied_enforced`
- [ ] 前 30 分钟:`permission_denied_enforced` <10 条/分钟 · 否则说明 role 分配漏

### Phase 2 · 观察(D → D+7)

- [ ] `observation_window_verify.py --flag PERMISSION_ENFORCE` 每日
- [ ] 关注:
  - `permission_denied_enforced` 数 · 应逐日下降(用户/运维补 role)
  - admin 相关操作成功率 · 应 100%
- [ ] 7 天末:denied <1 条/天 · 稳态

## 回滚 SOP

1. `.env`:`PERMISSION_ENFORCE=off`
2. 重启 · 权限退回 skeleton 模式(仅日志)
3. 排查缺失 role 后补齐 · 重试

## 常见故障

| 现象 | 处理 |
|---|---|
| admin 也 403 | admin role 未绑定 · 走 `bootstrap_admin.py` 重新给 |
| 普通账号大规模 403 | role 分配漏 · 通过 UI/CLI 补 role |
| CSRF 与 permission 双重 403 | 先修 CSRF · 再看 permission |

## 相关

- 骨架: commit `ee1ce27`(高风险接口保护)+ `cc3ae4e`(SqliteIdentityStore)
- 权限治理: [[40 实施计划/用户团队权限治理实施计划与PR清单]] PR-5, PR-10
