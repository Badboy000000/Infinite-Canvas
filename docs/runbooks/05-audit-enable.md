# Runbook 05 · Audit 事件启用

**Flag**: `AUDIT_ENABLED`
**观察窗口**: 7 天(纯累加事件 · 无回归风险)
**回滚代价**: 立即(flag off · 已入库事件保留)
**骨架承接**: `app/security/audit_policy.py`(commit `5687ae5`)· 11 event kind + 保留策略

## 目的

启用 audit 事件收集 · 为后续 flag 提供审计底座。

**推荐首个启用** · 因为:
- 纯累加事件 · 不改行为 · 零回归
- 后续 5 个 flag 都依赖 audit 记录拒绝事件
- 观察窗口 7 天只是形式 · 主要看事件是否正常入库

## 前置条件

- [ ] audit sink 目标已确认:sqlite(默认)/ 文件 / 外部 log 服务
- [ ] 磁盘剩余 ≥10 GB(audit 日均增量 ~100 MB 上限)
- [ ] `app.security.audit_policy` 已在代码中(骨架已合入)

## 分阶段 checklist

### Phase 0 · 准备

- [ ] `dry_run_flag_flip.py --flag AUDIT_ENABLED` 打印计划
- [ ] 检查 audit sink 目标空间

### Phase 1 · 启用(D-day)

- [ ] `.env`:`AUDIT_ENABLED=on`
- [ ] 重启 · 立即测:
  - 登录 · 应有 `auth_login` audit 事件
  - 触发一次 403(如无 permission)· 应有 `permission_denied` 事件(即使 permission enforce 未开 · skeleton 事件也会记)
- [ ] 前 30 分钟无 `audit_sink_failed` 告警

### Phase 2 · 观察(D → D+7)

- [ ] `observation_window_verify.py --flag AUDIT_ENABLED` 每日
- [ ] 关注:
  - 事件日增量 · 应在 100 MB 以下
  - `audit_sink_failed` 应 = 0
  - 磁盘剩余空间下降速率 · 应符合保留策略预期
- [ ] 7 天末:进入稳态 · 保留策略生效

## 回滚 SOP

1. `.env`:`AUDIT_ENABLED=off`
2. 重启 · audit 停止累加
3. 已入库事件保留 · 不删除

## 常见故障

| 现象 | 处理 |
|---|---|
| `audit_sink_failed` 大量出现 | 磁盘满 / sqlite 锁 · 排查 sink 目标 |
| 日增量激增(>500 MB) | 检查是否有异常 endpoint 触发大量事件 · 调 retention policy |
| audit 事件里出现凭据字段 | 骨架层 P0 零泄漏防线应已拦 · 若仍出现 → 立即 flag off + 报 lead |

## 相关

- 骨架: `app/security/audit_policy.py` · 11 event kind
- 保留策略: 默认 90 天 · 可通过 `AUDIT_RETENTION_DAYS` 调整
