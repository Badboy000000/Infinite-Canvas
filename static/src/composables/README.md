# Vue Composables

Vue move 期 seam bridges · 骨架层(PR-V1 起立)。

## Contract

- `useNodeFactory` — bridge to `window.NodeFactories.createByType` + alias via `NodeConfigRegistry.normalizeAlias`. **No** fallback: seam missing → `NodeFactoryNotAvailable`. Pass-through semantics; byte-equivalent to direct seam call after alias normalize.
- Composables **must not** duplicate seam logic; they mediate, not reimplement.
