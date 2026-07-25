// static/src/stores/nodeStore.js
//
// Pinia store for Vue-side node identity & type-registry mirror.
//
// Vue move 期 PR-V1 · Router + Pinia + useNodeFactory 骨架
// 承接方案 [[40 实施计划/Vue move 期节点承接方案 v1]] · 骨架层
//
// 单一职责(强):
//   1. `newId(type)`  → `${type}-${uuid16}`  · Vue side 生成节点 id 的唯一入口
//   2. `listRegisteredTypes()` → 从 window.NodeFactories.listSupportedTypes()
//      拉一次快照 · 只读镜像 · 缓存 · 不写回
//
// **不做**的事(硬约束 · 别越):
//   - 不持有节点数据(node data 归 CanvasPage / SmartCanvasPage 后续 store)
//   - 不复制 alias 表(alias 走 NodeConfigRegistry.normalizeAlias · useNodeFactory 桥接)
//   - 不调用 factory(生成 shape 归 useNodeFactory / NodeFactories.createByType)
//   - 不 fallback:seam 未挂载 → listRegisteredTypes 返回 []（明确 · 由调用方判空）
//
// GM-09 教训:静默 skip 反模式已禁 · 明确失败或空返回 · 不掩盖 seam 缺失

import { defineStore } from 'pinia'

// UUID16 生成:优先 crypto.randomUUID · 兜底 Math.random base36(node 环境 & 老浏览器)
function _uuid16() {
  if (typeof globalThis !== 'undefined'
      && globalThis.crypto
      && typeof globalThis.crypto.randomUUID === 'function') {
    // crypto.randomUUID 返回 36 字符 UUID · 截前 16 位十六进制便于日志阅读
    return globalThis.crypto.randomUUID().replace(/-/g, '').slice(0, 16)
  }
  return Math.random().toString(36).slice(2, 18).padEnd(16, '0').slice(0, 16)
}

export const useNodeStore = defineStore('node', {
  state: () => ({
    // 已注册 type 列表快照 · null = 未初始化 · [] = seam 缺失
    _registeredTypesCache: null,
  }),

  actions: {
    /**
     * 生成 Vue side 节点 id。
     *
     * @param {string} type - 节点类型(canonical · alias 由 useNodeFactory 前置 normalize)
     * @returns {string} `${type}-${uuid16}` 格式 · 与 legacy `uid(type)` 语义一致
     */
    newId(type) {
      if (!type || typeof type !== 'string') {
        throw new Error('nodeStore.newId: type must be a non-empty string')
      }
      return `${type}-${_uuid16()}`
    },

    /**
     * 从 window.NodeFactories.listSupportedTypes() 拉一次快照 · 缓存。
     *
     * @returns {string[]} 已注册 type 数组(只读 mirror) · seam 缺失时返回 []
     */
    listRegisteredTypes() {
      if (this._registeredTypesCache !== null) {
        return this._registeredTypesCache
      }
      const seam = (typeof globalThis !== 'undefined') ? globalThis.window : undefined
      const factories = seam && seam.NodeFactories
      if (!factories || typeof factories.listSupportedTypes !== 'function') {
        this._registeredTypesCache = []
        return this._registeredTypesCache
      }
      this._registeredTypesCache = Object.freeze([...factories.listSupportedTypes()])
      return this._registeredTypesCache
    },

    /**
     * 清空缓存 · 仅用于测试重置 · 生产代码不该调。
     */
    _resetForTests() {
      this._registeredTypesCache = null
    },
  },
})
