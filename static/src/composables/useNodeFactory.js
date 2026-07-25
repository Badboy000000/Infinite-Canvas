// static/src/composables/useNodeFactory.js
//
// Vue composable: bridge to `window.NodeFactories.createByType` + alias normalize.
//
// Vue move 期 PR-V1 · Router + Pinia + useNodeFactory 骨架
// 承接方案 [[40 实施计划/Vue move 期节点承接方案 v1]] · §硬约束 1 & 5
//
// 硬约束(违反 = 交付作废):
//   1. Vue side 生成节点 shape 的**唯一入口**必须走这里 · 禁止在 SFC 里自行 new dict
//   2. alias 处理**委托** NodeConfigRegistry.normalizeAlias · 不复制 alias 表
//      · alias 单一真源:`static/js/modules/node/registry/NodeConfigRegistry.js`
//      · legacy alias(如 smartContainer -> smartImage)由 seam 处理 · 本文件不列名
//   3. **不 fallback** · window.NodeFactories 未挂载 → 抛 NodeFactoryNotAvailable
//      · 明确失败 · 别静默 skip(GM-09 autoBind 静默 skip 反模式教训)
//   4. **pass-through 语义** · 不 mutate seam 出的 shape · 不添加字段 · 保字节等价
//
// 使用方式(V2 起 SFC 内):
//   import { useNodeFactory } from '@/composables/useNodeFactory'
//   const { createByType } = useNodeFactory()
//   const node = createByType('prompt', { point: {x, y}, id: nodeStore.newId('prompt') })

import NodeConfigRegistry from '/static/js/modules/node/registry/NodeConfigRegistry.js'

/**
 * seam 缺失时抛出的错误类型 · 便于上层 catch 区分。
 */
export class NodeFactoryNotAvailable extends Error {
  constructor(message) {
    super(message || 'window.NodeFactories seam is not mounted')
    this.name = 'NodeFactoryNotAvailable'
  }
}

/**
 * Vue composable · 返回 { createByType, listSupportedTypes } bridge。
 *
 * @returns {{
 *   createByType: (type: string, opts: object) => object,
 *   listSupportedTypes: () => string[],
 * }}
 */
export function useNodeFactory() {
  function _getSeam() {
    const seam = (typeof globalThis !== 'undefined') ? globalThis.window : undefined
    const factories = seam && seam.NodeFactories
    if (!factories || typeof factories.createByType !== 'function') {
      throw new NodeFactoryNotAvailable(
        'useNodeFactory: window.NodeFactories.createByType is not available. '
        + 'Ensure static/js/shared/nodes/factories.js is loaded before Vue mount.'
      )
    }
    return factories
  }

  /**
   * 通过 seam factory 生成节点 shape。
   *
   * alias 由 NodeConfigRegistry.normalizeAlias 前置转换后再交给 seam · 保证:
   *   - Vue side 传 legacy alias · seam 收到 canonical type
   *   - 输出 shape 与 window.NodeFactories.createByType(canonical, opts) 字节等价
   *
   * @param {string} type - 节点类型(可 legacy alias)
   * @param {{ point: {x:number,y:number}, id: string }} opts - factory 输入
   * @returns {object} node shape · 与 window.NodeFactories 直调等价
   */
  function createByType(type, opts) {
    const factories = _getSeam()
    const canonical = NodeConfigRegistry.normalizeAlias(type)
    return factories.createByType(canonical, opts)
  }

  /**
   * 已支持 type 快照 · 走 seam · 不缓存(缓存归 nodeStore)。
   *
   * @returns {string[]}
   */
  function listSupportedTypes() {
    const factories = _getSeam()
    if (typeof factories.listSupportedTypes !== 'function') {
      throw new NodeFactoryNotAvailable(
        'useNodeFactory: window.NodeFactories.listSupportedTypes is not available.'
      )
    }
    return factories.listSupportedTypes()
  }

  return { createByType, listSupportedTypes }
}
