# Runbook 01 · MinIO 灰度切换

**Flag**: `MINIO_SWITCHOVER_ENABLED` + `STORAGE_BACKEND`
**观察窗口**: 每 phase 7 天 · 4 phase 累计 28 天
**回滚代价**: shadow/dual_write 阶段 0 成本 · cutover 阶段需回滚 SOP(把 to_backend 数据搬回 from_backend)
**骨架承接**: `app/services/files/minio_switchover.py` · `SwitchoverPolicy` · `build_switchover_plan`

## 目的

把文件存储从 `local` 灰度切到 `minio` · 或反向 · 或 `hybrid`。

## 4 phase 定义(骨架层已冻结)

| Phase | 主写目标 | 读优先级 | 允许 delete 的后端 | 观察重点 |
|---|---|---|---|---|
| shadow | from_backend | from_backend | from_backend | to_backend 是否收到 shadow write(异步) |
| dual_write | from + to | from → to | from_backend(旧数据保留) | 两侧写延迟差异 · 一致性对账 |
| cutover | to_backend | to → from(兜底读旧) | 无(保守 · 双侧保留) | 应用能否只用 to_backend 完整读写 |
| rollback | from_backend | from_backend | to_backend(清理灰度) | 是否需要保留灰度期新增数据到 from_backend |

**cutover 硬约束**:`is_switchover_reversible(policy) == False` · 一旦 cutover · 不能静默回退 · 只能走 rollback plan。

## 前置条件

- [ ] MinIO 服务已运行(见 `deploy/production/docker-compose.production.yml` 里的 `minio` service)
- [ ] `python tools/minio_bootstrap.py` 已跑过 · bucket 已建 · 凭据已入 `.env`
- [ ] 前 5 个 flag(audit / identity-bridge / csrf / permission / rate-limit)已完成观察窗口 · 或明确接受它们仍 off
- [ ] KB `70 开发过程跟踪/生产切换日志/` 已建当次翻转日志

## 分阶段 checklist

### Phase 0 · 准备(D-day 前 1 天)

- [ ] 备份 `data/asset_library.json` + `data/canvas_*.json` + 本地文件目录快照 → `backups/pre-switchover-YYYYMMDD/`
- [ ] `python scripts/production/dry_run_flag_flip.py --flag MINIO_SWITCHOVER_ENABLED` 打印计划
- [ ] 用户确认切换方向:local → minio(常见)· minio → local(极少)· local → hybrid

### Phase 1 · shadow(D-day → D+7)

- [ ] `.env`:`MINIO_SWITCHOVER_ENABLED=on` + `STORAGE_BACKEND=local` + `MINIO_SHADOW_TARGET=minio`
- [ ] 重启 app · 观察日志无 `shadow_write_failed` warning
- [ ] 每天:`python scripts/production/observation_window_verify.py --flag MINIO_SWITCHOVER_ENABLED --phase shadow`
- [ ] 7 天末:MinIO 端文件数 ≥ local 端新增数 · shadow_write 成功率 ≥99.5%
- [ ] 若 shadow_write 成功率 <99.5% → 排查 MinIO 网络/凭据 · **不进入 dual_write**

### Phase 2 · dual_write(D+7 → D+14)

- [ ] `.env`:`MINIO_SWITCHOVER_PHASE=dual_write`
- [ ] 重启 app · 观察主写延迟增加应 <30ms
- [ ] 每天:`observation_window_verify.py --phase dual_write` · 检查两侧一致性
- [ ] 7 天末:local 与 minio 文件数对账 diff ≤ 0.1% · 无 `dual_write_partial` 告警
- [ ] 若 diff > 0.1% → 排查后修复 · 不进入 cutover

### Phase 3 · cutover(D+14 → D+21) **⚠️ 不可静默回退**

- [ ] 用户/运维**二次确认**:接受 cutover 后需要走 rollback plan 才能回退
- [ ] `.env`:`MINIO_SWITCHOVER_PHASE=cutover` + `STORAGE_BACKEND=minio`
- [ ] 重启 app · 观察读延迟(应主走 minio · 只在 minio 404 时兜底读 local)
- [ ] 每天:`observation_window_verify.py --phase cutover` · 检查 `read_from_local_fallback` 次数(应逐日归零)
- [ ] 7 天末:`read_from_local_fallback` = 0 · 应用只读 minio 也能完整工作 · 可考虑清理 local
- [ ] 若 `read_from_local_fallback` > 100/天 → 说明有文件未同步到 minio · 排查后决定 hold 或走 rollback

### Phase 4 · 稳态(D+21 之后)

- [ ] `.env`:保持 `MINIO_SWITCHOVER_PHASE=cutover` · **不删** `MINIO_SWITCHOVER_ENABLED` flag(以备 rollback)
- [ ] local 备份保留 ≥90 天 · 之后按数据保留策略清理

## 回滚 SOP

**shadow / dual_write 阶段**:直接 `.env` 把 `MINIO_SWITCHOVER_PHASE` 改回上一阶段 · 重启 · 5 分钟内完成。

**cutover 阶段**(需 rollback plan):
1. `.env`:`MINIO_SWITCHOVER_PHASE=rollback` + `STORAGE_BACKEND=local`
2. 重启 app · 主写立即回 local
3. 跑 `scripts/production/dry_run_flag_flip.py --flag MINIO_SWITCHOVER_ENABLED --rollback-plan` 打印需要从 minio 搬回 local 的文件清单
4. 用户确认清单后执行搬运(手动 · 因为搬运是数据操作 · Lead 不代执行)
5. 搬运完成后 `.env`:`MINIO_SWITCHOVER_ENABLED=off` · 重启 · 回到骨架期 default

## 日志模板

```markdown
# 生产切换日志 · MinIO 切换 YYYYMMDD

## 决策
- 方向: local → minio
- Phase 计划: 4 phase 顺序 · 每 phase 7 天
- 用户拍板日: YYYYMMDD

## Phase 1 · shadow
- 启用日: YYYYMMDD
- 观察记录:
  - D+1: shadow_write 成功率 = 99.8% · 无异常
  - D+2: ...
  - D+7: 成功率 = 99.9% · 进入 dual_write

## Phase 2 · dual_write
...
```

## 常见故障

| 现象 | 可能原因 | 处理 |
|---|---|---|
| `shadow_write_failed` 反复出现 | MinIO 凭据错 / 网络断 | 修 env / 排查 minio 网络 |
| dual_write 延迟激增 | MinIO 单节点 IO 瓶颈 | 加节点 / 升 SSD |
| cutover 阶段读兜底 local 次数不归零 | 有历史文件未同步到 minio | 跑一次性搬运脚本 |
| rollback 阶段发现 minio 独有文件未同步回 local | 灰度期新增数据 | 走 dry-run rollback-plan 手动搬 |

## 相关

- 骨架契约: `app/services/files/minio_switchover.py`
- 现状地图: [[20 现状地图/文件对象与 MinIO 现状]]
- 治理方案: [[30 治理方案/文件对象与 MinIO 治理方案]]
- MinIO bootstrap: `tools/minio_bootstrap.py`
