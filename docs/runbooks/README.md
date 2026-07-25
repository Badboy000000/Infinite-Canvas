# 生产切换 Runbook 集合

**Wave 3-N.11 Batch 10 交付** · 治理项目终局阶段 · 骨架期已在 Wave 3-N.9/10 全部完成(9 大专题 CLOSED),本目录承接**生产切换执行手册**。

## 定位

骨架层已把 6 个 env flag 落到代码,但 **defaults-off** — 用户 prod 未启用。本目录:

- 6 个 runbook · 每个对应 1 个 flag · 描述启用步骤 + 观察窗口 + 回滚 SOP
- 1 个 env 模板(`deploy/production/.env.template`)· 6 flag + 注释
- 1 个 docker-compose 生产模板(`deploy/production/docker-compose.production.yml`)
- 2 个 dry-run 脚本(`scripts/production/dry_run_flag_flip.py` / `observation_window_verify.py`)· 校验用 · **不执行真翻转**

## 硬约束

1. **Lead 不代执行 prod flag 翻转**(GM-14 边界)· 本目录是给用户/运维人员的手册
2. 每 flag 翻转后 **≥7 天观察窗口** · 除非在该窗口内发现回归,否则不进入下一 flag
3. 每 runbook 顶部有 **回滚 SOP** · 允许在 5 分钟内回到翻转前状态
4. dry-run 脚本 **禁止写数据库 / 禁止改 env / 禁止调 MinIO** · 只读 + print

## 目录

| # | Runbook | Flag | 观察窗口 | 回滚代价 |
|---|---|---|---|---|
| 01 | [minio-switchover](./01-minio-switchover.md) | `MINIO_SWITCHOVER_ENABLED` / `STORAGE_BACKEND` | 每 phase 7 天(4 phase 累计 28 天) | shadow/dual_write=0,cutover=需回滚 SOP |
| 02 | [identity-bridge-enforce](./02-identity-bridge-enforce.md) | `IDENTITY_BRIDGE_ENFORCE` | 7 天 | 5 分钟(flag off + 重启) |
| 03 | [csrf-cors-enable](./03-csrf-cors-enable.md) | `CSRF_ENABLED` + `CORS_STRICT_ENABLED` | 7 天 | 5 分钟(两 flag off + 重启) |
| 04 | [permission-enforce](./04-permission-enforce.md) | `PERMISSION_ENFORCE` | 7 天 | 5 分钟(flag off + 重启) |
| 05 | [audit-enable](./05-audit-enable.md) | `AUDIT_ENABLED` | 7 天(纯累加事件) | 立即(flag off · 已入库事件保留) |
| 06 | [rate-limit-enable](./06-rate-limit-enable.md) | `RATE_LIMIT_ENABLED` | 7 天 | 5 分钟(flag off + 重启) |

**推荐顺序**:05 → 02 → 03 → 04 → 06 → 01

**推荐顺序理由**:
1. **05 audit 优先**:纯累加事件 · 零回归风险 · 为后续 flag 的观察窗口提供审计底座
2. **02 identity-bridge**:骨架已默认 skeleton=off · 影响面小 · 只在 auth 路径生效
3. **03 csrf+cors**:与 02 联动 · 需要 audit 已启用以便追踪 403
4. **04 permission**:依赖 02+03 · 权限拒绝需要 audit 记录
5. **06 rate-limit**:依赖 05 · 需要 audit 记录 429
6. **01 minio-switchover 最后**:唯一涉及数据搬运 · 前 5 flag 稳定后再启

## 通用 SOP · 每个 runbook 都必须执行

**翻转前**:
1. `git log --oneline -5` 确认在最新 main
2. `python scripts/production/dry_run_flag_flip.py --flag <FLAG_NAME>` 打印翻转计划
3. 在 KB `70 开发过程跟踪/生产切换日志/` 建当次翻转日志(模板见 runbook 01 §日志模板)
4. 用户/运维确认后修改 prod `.env` · **不合并到仓库**

**翻转后**:
1. `docker compose -f deploy/production/docker-compose.production.yml up -d --force-recreate app`
2. 30 分钟内每 10 分钟跑一次 `python scripts/production/observation_window_verify.py --flag <FLAG_NAME>`
3. 7 天窗口每天一次同脚本 · 输出存入 KB 翻转日志
4. 窗口末尾无回归 → 进入下一 flag;有回归 → 执行该 runbook §回滚 SOP

## 治理项目终局标记

本目录合入之日 = 治理项目**骨架期完美收工 + 生产切换准备完成**。

- 骨架期(2026-07-24 完成):9 大专题 100% CLOSED · 代码可回滚 · 无生产影响
- **生产切换准备期**(本 Wave · 2026-07-25 完成):Lead 交付 runbook + 模板 + dry-run 脚本 · 用户自主启用节奏
- **生产切换执行期**(用户拍板节奏 · 每 flag 7 天):运维人员按 runbook 执行 · Lead 不代执行
- **节点真承接期**(依赖 Vue move):见 [[40 实施计划/Vue move 期节点承接方案 v1]] · 属新 wave · 不算治理任务

## 相关 KB

- [[00 索引与规范/Infinite Canvas 二开与架构治理项目知识库 Index]]
- [[40 实施计划/文件对象与 MinIO 治理实施计划与PR清单]]
- [[40 实施计划/部署与安全治理实施计划与PR清单]]
- [[40 实施计划/用户团队权限治理实施计划与PR清单]]
- [[70 开发过程跟踪/PR 状态总账/PR 状态总账索引]]
