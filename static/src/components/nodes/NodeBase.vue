<script setup>
// static/src/components/nodes/NodeBase.vue
//
// Vue move 期 PR-V2 · 节点组件基类(SFC · pure display shell)
//
// 承接 [[40 实施计划/Vue move 期节点承接方案 v1]] · V2 = 节点组件基类 + factory 桥接
//
// 单一职责(强 · 违反 = 交付作废):
//   - 只做 slot 展示 · 挂 data-node-id / data-node-type 便于选择器 + a11y
//   - **不消费**任何生成层 composable / store(避免展示层耦合生成层 · 单一职责)
//   - **不做** v-html · 全部 {{ }} interpolate(P0 密钥零泄漏防线)
//   - **不做** 拖拽 / 连线 / 编辑面板(V3+ 才引入)
//
// 使用方式(V4+ SFC 内 wrap):
//   <NodeBase :node="node" :readonly="isReadonly">
//     <PromptNodeBody :node="node" />
//   </NodeBase>

defineProps({
  node: {
    type: Object,
    required: true,
  },
  readonly: {
    type: Boolean,
    default: false,
  },
})
</script>

<template>
  <div
    class="node-base"
    :data-node-id="node.id"
    :data-node-type="node.type"
    :aria-readonly="readonly ? 'true' : 'false'"
    role="group"
  >
    <slot />
  </div>
</template>

<style scoped>
.node-base {
  position: relative;
  padding: 4px;
  outline: 1px solid transparent;
  box-sizing: border-box;
}
</style>
