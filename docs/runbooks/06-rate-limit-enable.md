# Runbook 06 · Rate Limit 启用

**Flag**: `RATE_LIMIT_ENABLED`
**观察窗口**: 7 天
**回滚代价**: 5 分钟(flag off + 重启)
**骨架承接**: `app/security/rate_limit_policy.py`(commit `5265191`)· 4 route group × 3 mode

## 目的

按 route group 启用 rate limit · 防 brute-force / abuse。

## 前置条件

- [ ] 05 audit 已启用 · 需要 audit 记录 429
- [ ] 04 permission 已启用 · 因为 rate-limit 需要按 identity 分桶
- [ ] 确认 rate-limit 后端:in-memory(单实例)/ redis(多实例)
- [ ] `.env` 已列出 4 route group 的阈值(骨架层已给默认)

## 4 route group 骨架默认

| Group | 默认阈值(local_personal) | 默认阈值(intranet_team) | 默认阈值(public_team) |
|---|---|---|---|
| auth(login/reset) | 60 req/min/ip | 30 req/min/ip | 10 req/min/ip |
| generation(image/video) | 无限 | 60 req/min/user | 30 req/min/user |
| read(canvas/list) | 无限 | 无限 | 300 req/min/user |
| admin(bootstrap/config) | 无限 | 60 req/min/user | 30 req/min/user |

## 分阶段 checklist

### Phase 0 · 准备

- [ ] `dry_run_flag_flip.py --flag RATE_LIMIT_ENABLED` 打印计划
- [ ] 确认 deploy mode(`DEPLOY_MODE=local_personal|intranet_team|public_team`)· 决定默认阈值
- [ ] 若 public_team · 确认 auth 阈值 10/min 足够(否则先调大)

### Phase 1 · 启用(D-day)

- [ ] `.env`:`RATE_LIMIT_ENABLED=on` · `DEPLOY_MODE` 已正确设置
- [ ] 重启 · 立即测:
  - 快速 POST `/api/auth/login` 20 次(不同错密码)· 第 11 次起应 429 + audit `rate_limit_exceeded`
  - 正常 GET `/api/canvas/list` 100 次 · 应全 200(阈值 300)
- [ ] 前 30 分钟:`rate_limit_exceeded` <100 条/分钟

### Phase 2 · 观察(D → D+7)

- [ ] `observation_window_verify.py --flag RATE_LIMIT_ENABLED` 每日
- [ ] 关注:
  - 429 数量 · 分 route group 看
  - 合法用户被 429 的反馈(应 0)
  - 阈值是否合适 · 可按 audit 数据调整
- [ ] 7 天末:429 主要来自异常 ip · 合法用户无 429 · 稳态

## 回滚 SOP

1. `.env`:`RATE_LIMIT_ENABLED=off`
2. 重启 · rate limit 停用
3. 调阈值后重试

## 常见故障

| 现象 | 处理 |
|---|---|
| 合法用户大量 429 | 阈值太严 · 调 `.env` group 阈值 |
| 多实例部署 rate limit 不生效 | 切 redis 后端 |
| generation group 429 影响业务 | 若付费用户 · 考虑按 role 差异化阈值 |

## 相关

- 骨架: `app/security/rate_limit_policy.py` · 4 group × 3 mode
- 部署治理: [[40 实施计划/部署与安全治理实施计划与PR清单]]
