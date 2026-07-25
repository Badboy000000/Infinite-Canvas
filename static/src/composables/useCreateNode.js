// static/src/composables/useCreateNode.js
//
// Vue composable: createNodeInPage(type, point) — Vue side 生成节点的**唯一入口**。
//
// Vue move 期 PR-V2 · 节点组件基类 + factory 桥接
// 承接方案 [[40 实施计划/Vue move 期节点承接方案 v1]] · V2 端到端桥
//
// 端到端语义(硬约束 · 违反 = 交付作废):
//   1. 输入 (type, point) → 输出 shape
//   2. id 由 useNodeStore.newId(canonical) 产生(单一 id 生成入口)
//   3. shape 由 useNodeFactory.createByType(type, {point, id}) 产生
//      · alias(legacy 别名)由 useNodeFactory 内部 normalizeAlias 委托
//      · 本文件**不复制** alias 字面量(GM 单一真源原则)
//   4. seam 缺失 → NodeFactoryNotAvailable 冒泡(明确失败 · GM-09 教训)
//   5. unknown type → seam 抛出的 `unknown type ...` Error 冒泡
//   6. point 必须 {x:number, y:number} · 否则抛 Error(与 factories.js _requirePoint 语义一致)
//
// **不做**的事:
//   - 不 mutate seam 出的 shape · 不添加字段 · pass-through
//   - 不接管画布状态(V3+ 才有节点 store)
//   - 不 catch 错误 · 不 fallback · 不吞异常

import { useNodeStore } from '@/stores/nodeStore'
import { useNodeFactory } from '@/composables/useNodeFactory'

/**
 * 校验 point 参数 · 与 factories.js 内 `_requirePoint` 语义一致 · 快失败。
 *
 * @param {*} point - 期望 {x:number, y:number}
 * @throws {Error} point 缺失 / 类型错误时抛出
 */
function _validatePoint(point) {
  if (!point
      || typeof point.x !== 'number'
      || typeof point.y !== 'number'
      || Number.isNaN(point.x)
      || Number.isNaN(point.y)) {
    throw new Error('useCreateNode: point={x:number, y:number} required')
  }
}

/**
 * 校验 type 参数(非空字符串)· nodeStore.newId 已有硬校验 · 此处提前失败便于调试。
 */
function _validateType(type) {
  if (!type || typeof type !== 'string') {
    throw new Error('useCreateNode: type must be a non-empty string')
  }
}

/**
 * Vue composable · 返回 { createNodeInPage } · Vue side 页面生成节点唯一入口。
 *
 * @returns {{
 *   createNodeInPage: (type: string, point: {x:number,y:number}) => object
 * }}
 */
export function useCreateNode() {
  const nodeStore = useNodeStore()
  const factory = useNodeFactory()

  /**
   * 在页面上生成一个节点 shape。
   *
   * @param {string} type - 节点类型(可 legacy alias · 由 useNodeFactory 内 normalizeAlias 前置)
   * @param {{x:number,y:number}} point - 生成坐标
   * @returns {object} node shape · 与 window.NodeFactories 直调等价
   * @throws {NodeFactoryNotAvailable} seam 未挂载
   * @throws {Error} type / point 校验失败 · 或 seam 内部 unknown type
   */
  function createNodeInPage(type, point) {
    _validateType(type)
    _validatePoint(point)
    // id 用**原始 type**(alias 未 normalize)生成 · 与 legacy uid(rawType) 语义对齐
    // useNodeFactory 内会 normalize 再喂 seam · id 前缀和 shape.type 可能不同(alias 情况下)
    // 这与现网 canvas.js 行为一致 · 无破坏
    const id = nodeStore.newId(type)
    return factory.createByType(type, { point, id })
  }

  return { createNodeInPage }
}
