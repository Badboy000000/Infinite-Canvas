// static/js/shared/nodes/factories.js
//
// 节点系统治理 PR-4/5/6:节点构造工厂 seam(Wave 3-N.10 Batch 9)。
//
// 硬约束(与 [[40 实施计划/节点系统治理实施计划与PR清单]] PR-4/5/6 一致):
//   1. 零依赖零构建 · seam 期不引入框架
//   2. 纯函数:输入 point + opts · 输出 node object(不生成 id · id 由调用方 uid() 注入)
//   3. **字节等价性硬约束**:与 canvas.js 中 addPromptNode / addLLMNode / addImageNode / …
//      现存构造出的 shape 完全一致 · legacy 字段 100% 保留 · 未知字段透传
//   4. 不接管 create / render / save / run 行为 · 只提供 shape 构造
//   5. 与 `app.nodes.registry` 后端契约字段名对齐
//
// 使用方式(未来 PR-4 真承接时):
//   function addPromptNode(point){
//     const p = point || defaultPoint(0, 0);
//     return addNode(NodeFactories.createPromptNode({point: p, id: uid('prompt')}));
//   }
//
// 骨架期本模块 **不被 canvas.js 引用**;契约测试验证 shape 等价即可。

(function attachNodeFactories(global) {
  'use strict';

  function _requirePoint(opts) {
    const p = (opts && opts.point) || null;
    if (!p || typeof p.x !== 'number' || typeof p.y !== 'number') {
      throw new Error('NodeFactories: point={x, y} required');
    }
    return p;
  }

  function _requireId(opts, kind) {
    const id = opts && opts.id;
    if (!id || typeof id !== 'string') {
      throw new Error(`NodeFactories(${kind}): opts.id required (caller must uid())`);
    }
    return id;
  }

  // ---------------- classic 文本类 (PR-4 · A 批) ----------------

  function createPromptNode(opts) {
    const p = _requirePoint(opts);
    const id = _requireId(opts, 'prompt');
    return { id, type: 'prompt', x: p.x, y: p.y, text: (opts.text || '') };
  }

  function createLlmNode(opts) {
    const p = _requirePoint(opts);
    const id = _requireId(opts, 'llm');
    // opts.providerId + opts.chatModel + opts.systemPrompt 由调用方(canvas.js)从
    // chatApiProviders() / resolveChatModel() 解析后传入 · factory 不做 provider 查询
    return {
      id,
      type: 'llm',
      x: p.x,
      y: p.y,
      llmProvider: opts.providerId || '',
      model: opts.chatModel || '',
      mode: opts.mode || 'node',
      systemPrompt: opts.systemPrompt || 'You are a helpful assistant. Rewrite the input into a concise image prompt.',
      chatInput: '',
      messages: [],
      outputText: '',
      llmInputHeight: 110,
      llmOutputHeight: 150,
      running: false,
    };
  }

  // ---------------- classic 图像类 (PR-5 · B 批) ----------------

  function createImageNode(opts) {
    const p = _requirePoint(opts);
    const id = _requireId(opts, 'image');
    return {
      id, type: 'image', x: p.x, y: p.y,
      url: opts.url || '',
      name: opts.name || '空白图片',
    };
  }

  function createOutputNode(opts) {
    const p = _requirePoint(opts);
    const id = _requireId(opts, 'output');
    // 与 canvas.js addOutputNode(如存在) shape 对齐;output 节点主要承载 images[] / _pending
    return {
      id, type: 'output', x: p.x, y: p.y,
      images: [],
    };
  }

  function createGeneratorNode(opts) {
    const p = _requirePoint(opts);
    const id = _requireId(opts, 'gen');
    return {
      id, type: 'generator', x: p.x, y: p.y,
      apiProvider: opts.providerId || '',
      model: opts.model || '',
      ratio: opts.ratio || 'square',
      resolution: opts.resolution || '',
      customRatio: '',
      customSize: '',
      customRatioWidth: '',
      customRatioHeight: '',
      customWidth: '',
      customHeight: '',
      inputs: [],
    };
  }

  function createMsGenNode(opts) {
    const p = _requirePoint(opts);
    const id = _requireId(opts, 'msgen');
    return {
      id, type: 'msgen', x: p.x, y: p.y,
      msgenModel: opts.msgenModel || 'zimage',
      msWidth: opts.msWidth || 1024,
      msHeight: opts.msHeight || 1024,
      msCustomModel: opts.msCustomModel || 'Tongyi-MAI/Z-Image-Turbo',
      msRatio: 'square',
      msResolution: '1k',
      msCustomRatio: '',
      msCustomSize: '',
      msCustomRatioWidth: '',
      msCustomRatioHeight: '',
      msCustomWidth: '',
      msCustomHeight: '',
      count: 1,
      fitImage: false,
      inputs: [],
      running: false,
    };
  }

  // ---------------- classic 视频/工作流类 (PR-5 · B 批扩展) ----------------

  function createVideoNode(opts) {
    const p = _requirePoint(opts);
    const id = _requireId(opts, 'vid');
    return {
      id, type: 'video', x: p.x, y: p.y,
      apiProvider: opts.providerId || '',
      model: opts.model || '',
      duration: 5,
      aspectRatio: '16:9',
      resolution: '',
      enhancePrompt: false,
      enableUpsample: false,
      watermark: false,
      cameraFixed: false,
      generateAudio: false,
      useFrameRoles: false,
      multimodal: false,
      tempShLinks: [],
      inputs: [],
      running: false,
    };
  }

  function createRhNode(opts) {
    const p = _requirePoint(opts);
    const id = _requireId(opts, 'rh');
    return {
      id, type: 'rh', x: p.x, y: p.y,
      w: 430, h: 0,
      rhMode: 'app',
      rhPayment: 'free',
      webappId: '',
      workflowId: '',
      instanceType: '',
      rhAppInfo: null,
      rhWorkflowInfo: null,
      rhParams: {},
      inputs: [],
      running: false,
    };
  }

  function createComfyNode(opts) {
    const p = _requirePoint(opts);
    const id = _requireId(opts, 'comfy');
    // comfy 节点 shape:与 canvas.js addComfyNode(如存在) 保持最小契约
    // 详细字段 legacy write-preserve · 见治理契约 v1
    return {
      id, type: 'comfy', x: p.x, y: p.y,
      inputs: [],
    };
  }

  function createLtxDirectorNode(opts) {
    const p = _requirePoint(opts);
    const id = _requireId(opts, 'ltxdir');
    return {
      id, type: 'ltxDirector', x: p.x, y: p.y,
      w: 1000, h: 800,
      globalPrompt: '',
      durationFrames: 120,
      durationSeconds: 5,
      frameRate: 24,
      customWidth: 0,
      customHeight: 0,
      displayMode: 'seconds',
      useCustomAudio: false,
      imgCompression: 18,
      epsilon: 0.001,
      divisibleBy: 32,
      noiseSeed: 12,
      ltxTimelineData: '',
      ltxLocalPrompts: '',
      ltxSegmentLengths: '',
      ltxGuideStrength: '',
      ltxSegments: [],
      ltxSelectedSegId: '',
      inputs: [],
      running: false,
    };
  }

  // ---------------- classic 循环/分组类 (PR-5 尾部) ----------------

  function createLoopNode(opts) {
    const p = _requirePoint(opts);
    const id = _requireId(opts, 'loop');
    return {
      id, type: 'loop', x: p.x, y: p.y,
      count: 3,
      mode: 'serial',
      showPrompt: false,
      imageInput: false,
      videoInput: false,
      loopStart: 1,
      imageBatchSize: 1,
      videoBatchSize: 1,
      variablePrompt: '',
      fixedPrompt: '',
    };
  }

  function createGroupNode(opts) {
    const p = _requirePoint(opts);
    const id = _requireId(opts, 'grp');
    return {
      id, type: 'group', x: p.x, y: p.y,
      w: opts.w || 300,
      h: opts.h || 220,
      items: [],
    };
  }

  // ---------------- smart 节点类 (PR-6) ----------------

  function createSmartImageNode(opts) {
    const p = _requirePoint(opts);
    const id = _requireId(opts, 'smartimg');
    return {
      id, type: 'smart-image', x: p.x, y: p.y,
      images: [],
      scale: 1,
      runSettings: opts.runSettings || {},
      promptDraft: '',
      promptDraftMeta: null,
      pendingTasks: [],
      jimengPending: null,
      generatedOutputs: [],
      manualInputRefs: [],
      runInputRefs: [],
      asset_uris: [],
      inputNodeIds: [],
    };
  }

  function createSmartPromptNode(opts) {
    const p = _requirePoint(opts);
    const id = _requireId(opts, 'smartprompt');
    return {
      id, type: 'smart-prompt', x: p.x, y: p.y,
      text: opts.text || '',
      systemPrompt: opts.systemPrompt || '',
      llmProvider: opts.providerId || '',
      model: opts.chatModel || '',
    };
  }

  function createSmartLoopNode(opts) {
    const p = _requirePoint(opts);
    const id = _requireId(opts, 'smartloop');
    return {
      id, type: 'smart-loop', x: p.x, y: p.y,
      count: 3,
      mode: 'serial',
      showPrompt: true,   // smart-loop 自动开启 · treatise 契约 v1
      imageInput: true,
    };
  }

  function createSmartGroupNode(opts) {
    const p = _requirePoint(opts);
    const id = _requireId(opts, 'smartgrp');
    return {
      id, type: 'smart-group', x: p.x, y: p.y,
      w: opts.w || 300,
      h: opts.h || 220,
      items: [],
    };
  }

  // ---------------- factory registry(按 type 查表) ----------------

  const FACTORY_BY_TYPE = Object.freeze({
    // classic
    prompt: createPromptNode,
    llm: createLlmNode,
    image: createImageNode,
    output: createOutputNode,
    generator: createGeneratorNode,
    msgen: createMsGenNode,
    video: createVideoNode,
    rh: createRhNode,
    comfy: createComfyNode,
    ltxDirector: createLtxDirectorNode,
    loop: createLoopNode,
    group: createGroupNode,
    // smart
    'smart-image': createSmartImageNode,
    'smart-prompt': createSmartPromptNode,
    'smart-loop': createSmartLoopNode,
    'smart-group': createSmartGroupNode,
  });

  function createByType(type, opts) {
    const factory = FACTORY_BY_TYPE[type];
    if (!factory) {
      throw new Error(`NodeFactories.createByType: unknown type ${JSON.stringify(type)}`);
    }
    return factory(opts);
  }

  function listSupportedTypes() {
    return Object.keys(FACTORY_BY_TYPE);
  }

  const NodeFactories = Object.freeze({
    // classic
    createPromptNode,
    createLlmNode,
    createImageNode,
    createOutputNode,
    createGeneratorNode,
    createMsGenNode,
    createVideoNode,
    createRhNode,
    createComfyNode,
    createLtxDirectorNode,
    createLoopNode,
    createGroupNode,
    // smart
    createSmartImageNode,
    createSmartPromptNode,
    createSmartLoopNode,
    createSmartGroupNode,
    // registry
    createByType,
    listSupportedTypes,
    FACTORY_BY_TYPE,
  });

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = NodeFactories;
  }
  if (global && !global.NodeFactories) {
    global.NodeFactories = NodeFactories;
  }
}(typeof window !== 'undefined' ? window : (typeof globalThis !== 'undefined' ? globalThis : this)));
