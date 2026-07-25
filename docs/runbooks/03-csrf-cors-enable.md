# Runbook 03 · CSRF + CORS 硬启用

**Flag**: `CSRF_ENABLED` + `CORS_STRICT_ENABLED`
**观察窗口**: 7 天
**回滚代价**: 5 分钟(两 flag off + 重启)
**骨架承接**: `app/security/csrf_policy.py`(commit `5687ae5`)· `app/security/csp.py`(commit `a133c6f`)

## 目的

- **CSRF**:在写请求(POST/PUT/PATCH/DELETE)启用 double-submit cookie 校验
- **CORS**:从 `*` 或 permissive 切到显式 allowlist

两个 flag 联动启用 · 因为 CORS 收紧会影响 CSRF token 的跨源获取。

## 前置条件

- [ ] 05 audit 已启用 · 06 rate-limit 已启用(需要 audit 记录 CSRF 拒绝 · rate-limit 兜底防 brute-force)
- [ ] `.env` 已列出所有合法 origin(`CORS_ALLOWLIST=https://...,https://...`)
- [ ] 前端已实装 CSRF token(读取 `Set-Cookie: csrf_token=...` 并回填 `X-CSRF-Token` header)

## 分阶段 checklist

### Phase 0 · 准备(D-day 前 1 天)

- [ ] `dry_run_flag_flip.py --flag CSRF_ENABLED,CORS_STRICT_ENABLED` 打印计划
- [ ] 收集所有会调用 API 的 origin:主域名 + 二级域名 + 本地 dev · 全部写入 `CORS_ALLOWLIST`
- [ ] 前端跑一次全流程 · 确认 `csrf_token` cookie 能拿到 · 写请求带 `X-CSRF-Token`

### Phase 1 · 启用(D-day)

- [ ] `.env`:`CSRF_ENABLED=on` + `CORS_STRICT_ENABLED=on` + `CORS_ALLOWLIST=<allowlist>`
- [ ] 重启 app · 立即测:
  - GET `/api/config` · 应 200(CSRF 不检 GET)
  - POST `/api/canvas` **不带** `X-CSRF-Token` · 应 403
  - POST `/api/canvas` 带 `X-CSRF-Token`(与 cookie 一致)· 应 200
  - 跨源 OPTIONS 请求 · 应 200 + `Access-Control-Allow-Origin` = 请求方(而非 `*`)
- [ ] 观察前 30 分钟:`csrf_reject` <5 条/分钟 · `cors_block` <5 条/分钟

### Phase 2 · 观察(D → D+7)

- [ ] 每天:`observation_window_verify.py --flag CSRF_ENABLED,CORS_STRICT_ENABLED`
- [ ] 关注指标:
  - `csrf_reject` 数(应逐日归零)
  - `cors_block` 数(应逐日归零)
  - 前端错误率(4xx / 5xx 比例)不应上升 >1%
- [ ] 7 天末:reject/block 都 <1 条/天 · 进入稳态

## 回滚 SOP

**回滚方向**:
- 只回 CSRF · 保 CORS:`CSRF_ENABLED=off` · 若 CORS 无异常
- 只回 CORS · 保 CSRF:`CORS_STRICT_ENABLED=off` · 若 CSRF 无异常但 origin 漏配
- 两个都回:`CSRF_ENABLED=off` + `CORS_STRICT_ENABLED=off`

每种方向都是 5 分钟内(改 env + 重启)。

## 常见故障

| 现象 | 可能原因 | 处理 |
|---|---|---|
| 前端所有写请求 403 | CSRF token 前端没实装 | 前端加代码读 cookie + 写 header |
| 部分 origin 被 block | `CORS_ALLOWLIST` 遗漏 | 补 allowlist + 重启 |
| `X-CSRF-Token` 与 cookie mismatch | 前端读了错误 cookie / 有多个 csrf_token | 排查 cookie path/domain |
| OPTIONS 依然是 `*` | CSP header 与 CORS 混淆 | 确认 `app/security/csp.py` 与 CORS middleware 各司其职 |

## 相关

- CSP 骨架: `app/security/csp.py`
- CSRF 骨架: `app/security/csrf_policy.py`
- 部署治理: [[40 实施计划/部署与安全治理实施计划与PR清单]] PR-5(高风险接口保护)
