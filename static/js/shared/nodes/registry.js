// static/js/shared/nodes/registry.js
//
// 节点系统治理 PR-2:前端 NodeTypeRegistry seam 骨架(Wave 3-N.9 Batch 4)。
//
// 硬约束(与 [[40 实施计划/节点系统治理实施计划与PR清单]] PR-2 一致):
//   1. 零依赖零构建 · seam 期不引入 Vue / TS / Vite / registry 框架
//   2. 只读元数据:listTypes() / getType(type) / resolveLegacyAlias(alias)
//   3. 不接管创建 / 渲染 / 保存 / 运行行为(工具栏 / 右键菜单 / add*Node / renderNode 均不改)
//   4. legacy alias `smart-container` -> `smart-image` 显式可查
//   5. 与后端 `app.nodes.registry` 字段名对齐 · 未来 PR 承接 crossref 校验
//
// 使用者:
//   - 后续 PR-4/5/6 分批节点承接时 · `add*Node()` 内部先从 registry 拿元信息
//   - 前端渲染 registry(PR-8)只在 registry.renderers 缺失时 fallback 旧路径

(function attachNodeRegistry(global) {
  'use strict';

  const CLASSIC_NODE_TYPES = Object.freeze([
    'image', 'prompt', 'loop', 'group', 'llm', 'generator',
    'msgen', 'video', 'rh', 'ltxDirector', 'output', 'comfy',
  ]);
  const SMART_NODE_TYPES = Object.freeze([
    'smart-image', 'smart-prompt', 'smart-loop', 'smart-group',
  ]);
  const KNOWN_NODE_TYPES = Object.freeze([...CLASSIC_NODE_TYPES, ...SMART_NODE_TYPES]);

  // legacy alias · 与 app/nodes/registry.py LEGACY_NODE_ALIASES 逐字对齐
  const LEGACY_NODE_ALIASES = Object.freeze({
    'smart-container': 'smart-image',
  });

  // 默认 capabilities 与 facets · 与后端 registry.py `_DEFAULT_CAPABILITIES` 对齐
  const DEFAULT_CAPABILITIES = Object.freeze({
    prompt: ['author_text'],
    llm: ['chat'],
    image: ['media-source'],
    output: ['media-output'],
    generator: ['generate_image'],
    msgen: ['generate_image'],
    video: ['generate_video'],
    rh: ['run_workflow'],
    ltxDirector: ['run_workflow'],
    comfy: ['run_workflow'],
    loop: ['orchestrate'],
    group: ['group'],
    'smart-image': ['media-source', 'generation-target', 'media-output', 'run-state-host'],
    'smart-prompt': ['author_text', 'chat'],
    'smart-loop': ['orchestrate'],
    'smart-group': ['group'],
  });

  function _descriptorFor(type) {
    const category = CLASSIC_NODE_TYPES.indexOf(type) >= 0 ? 'classic' : 'smart';
    const aliases = Object.keys(LEGACY_NODE_ALIASES)
      .filter((k) => LEGACY_NODE_ALIASES[k] === type);
    const facets = (type === 'smart-image') ? DEFAULT_CAPABILITIES[type].slice() : [];
    return Object.freeze({
      type,
      display_name: type,
      category,
      schema_version: 1,
      capabilities: Object.freeze((DEFAULT_CAPABILITIES[type] || []).slice()),
      ports: Object.freeze([]),
      legacy_aliases: Object.freeze(aliases),
      facets: Object.freeze(facets),
      renderer_ref: null,
      executor_ref: null,
    });
  }

  const _TABLE = Object.freeze(
    KNOWN_NODE_TYPES.reduce((acc, t) => {
      acc[t] = _descriptorFor(t);
      return acc;
    }, {})
  );

  function listTypes() {
    return KNOWN_NODE_TYPES.map((t) => _TABLE[t]);
  }

  function getType(typeOrAlias) {
    if (typeof typeOrAlias !== 'string' || !typeOrAlias) return null;
    if (_TABLE[typeOrAlias]) return _TABLE[typeOrAlias];
    const resolved = LEGACY_NODE_ALIASES[typeOrAlias];
    if (resolved && _TABLE[resolved]) return _TABLE[resolved];
    return null;
  }

  function resolveLegacyAlias(alias) {
    if (typeof alias !== 'string') return null;
    return LEGACY_NODE_ALIASES[alias] || null;
  }

  const NodeRegistry = Object.freeze({
    KNOWN_NODE_TYPES,
    CLASSIC_NODE_TYPES,
    SMART_NODE_TYPES,
    LEGACY_NODE_ALIASES,
    listTypes,
    getType,
    resolveLegacyAlias,
  });

  // CommonJS export (Node · pytest 场景) + 浏览器 window 挂载
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = NodeRegistry;
  }
  if (global && !global.NodeRegistry) {
    global.NodeRegistry = NodeRegistry;
  }
}(typeof window !== 'undefined' ? window : (typeof globalThis !== 'undefined' ? globalThis : this)));
