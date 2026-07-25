"""Wave 3-N.11 Vue move PR-V1 · Router + Pinia + useNodeFactory 骨架契约测试.

Editorial:
    Verifies the Vue-side skeleton for the node-move era:
      - Pinia dependency in package.json
      - main.js installs createPinia after router, before mount
      - useNodeFactory composable delegates alias to NodeConfigRegistry (no duplication)
      - useNodeFactory calls window.NodeFactories.createByType (bridge, not reimplement)
      - useNodeFactory throws NodeFactoryNotAvailable when seam missing (no silent skip)
      - nodeStore.newId(type) produces `${type}-...` template
      - useNodeFactory does NOT duplicate the alias table (single source of truth
        in NodeConfigRegistry)
      - useNodeFactory uses listSupportedTypes (not listTypes)

    Static-only assertions (AST/regex). Does NOT run npm install or start Vite /
    vitest / a Vue app — same posture as PR-10~16 skeleton contract tests.

Covers T540-T547 (8 items):

    T540  static/package.json dependencies contains "pinia": "^2.1.0"
    T541  static/src/main.js installs createPinia after app.use(router) and
          before app.mount('#app')
    T542  useNodeFactory.js delegates alias to NodeConfigRegistry.normalizeAlias
    T543  useNodeFactory.js calls NodeFactories.createByType (seam bridge)
    T544  useNodeFactory.js throws NodeFactoryNotAvailable when seam missing
    T545  useNodeFactory.js does NOT contain literal 'smart-container' /
          'smart-image' (no duplicate alias table)
    T546  nodeStore.js newId produces `${type}-...` template
    T547  useNodeFactory.js uses listSupportedTypes (canonical seam method name),
          not listTypes
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

PKG_PATH = ROOT / "static/package.json"
MAIN_PATH = ROOT / "static/src/main.js"
COMPOSABLE_PATH = ROOT / "static/src/composables/useNodeFactory.js"
STORE_PATH = ROOT / "static/src/stores/nodeStore.js"


# --- T540 ---

def test_t540_pinia_dependency_in_package_json():
    """T540 · static/package.json dependencies contains pinia@^2.1.0."""
    assert PKG_PATH.is_file(), f"static/package.json not found at {PKG_PATH}"
    data = json.loads(PKG_PATH.read_text(encoding="utf-8"))
    deps = data.get("dependencies", {})
    assert "pinia" in deps, "dependencies missing 'pinia'"
    spec = deps["pinia"]
    assert re.match(r"\^2\.1\.", spec), (
        f"pinia dependency should be ^2.1.x, got {spec!r}"
    )
    # PR-10 baseline invariants preserved
    assert "vue" in deps, "dependencies regression: vue removed"
    assert "vue-router" in deps, "dependencies regression: vue-router removed"


# --- T541 ---

def test_t541_main_js_installs_pinia_after_router_before_mount():
    """T541 · main.js: createPinia is installed after app.use(router) and
    before app.mount('#app'). Import order also verified."""
    assert MAIN_PATH.is_file(), f"static/src/main.js not found at {MAIN_PATH}"
    text = MAIN_PATH.read_text(encoding="utf-8")

    # Imports present
    assert re.search(r"import\s*\{\s*createPinia\s*\}\s*from\s*['\"]pinia['\"]", text), (
        "main.js missing createPinia import from 'pinia'"
    )
    assert re.search(r"import\s*\{\s*createApp\s*\}\s*from\s*['\"]vue['\"]", text), (
        "main.js regression: createApp import lost"
    )
    assert re.search(r"import\s+router\s+from\s+['\"]\.?/router['\"]", text), (
        "main.js regression: router import lost"
    )

    # Order:  app.use(router)  <  app.use(createPinia())  <  app.mount('#app')
    idx_router = text.find("app.use(router)")
    idx_pinia = text.find("createPinia()")
    idx_mount = text.find("app.mount")
    assert idx_router != -1, "main.js missing app.use(router)"
    assert idx_pinia != -1, "main.js missing createPinia() invocation"
    assert idx_mount != -1, "main.js missing app.mount"
    assert idx_router < idx_pinia < idx_mount, (
        "Order broken: expected router.use → createPinia → mount, got positions "
        f"router={idx_router} pinia={idx_pinia} mount={idx_mount}"
    )


# --- T542 ---

def test_t542_use_node_factory_delegates_alias_to_config_registry():
    """T542 · useNodeFactory.js delegates alias handling to
    NodeConfigRegistry.normalizeAlias (single source of truth)."""
    assert COMPOSABLE_PATH.is_file(), (
        f"static/src/composables/useNodeFactory.js not found at {COMPOSABLE_PATH}"
    )
    text = COMPOSABLE_PATH.read_text(encoding="utf-8")
    assert "NodeConfigRegistry" in text, (
        "useNodeFactory.js missing NodeConfigRegistry reference"
    )
    assert "normalizeAlias" in text, (
        "useNodeFactory.js does not call normalizeAlias — alias handling "
        "must be delegated to NodeConfigRegistry.normalizeAlias"
    )
    # Import path assertion (static ES module import from seam)
    assert re.search(
        r"import\s+NodeConfigRegistry\s+from\s+['\"]/static/js/modules/node/registry/NodeConfigRegistry\.js['\"]",
        text,
    ), (
        "useNodeFactory.js missing static ES module import of "
        "NodeConfigRegistry from /static/js/modules/node/registry/NodeConfigRegistry.js"
    )


# --- T543 ---

def test_t543_use_node_factory_calls_create_by_type():
    """T543 · useNodeFactory.js calls window.NodeFactories.createByType
    (bridge to the seam, not a reimplementation)."""
    text = COMPOSABLE_PATH.read_text(encoding="utf-8")
    assert "createByType" in text, (
        "useNodeFactory.js does not reference createByType — must bridge "
        "to window.NodeFactories.createByType"
    )
    # A call site (invocation), not just an identifier mention
    assert re.search(r"factories\.createByType\s*\(", text) or re.search(
        r"NodeFactories\.createByType\s*\(", text
    ), (
        "useNodeFactory.js has no call site for createByType"
    )


# --- T544 ---

def test_t544_use_node_factory_throws_when_seam_missing():
    """T544 · useNodeFactory.js throws NodeFactoryNotAvailable when seam missing
    (no silent skip — GM-09 lesson)."""
    text = COMPOSABLE_PATH.read_text(encoding="utf-8")
    assert "NodeFactoryNotAvailable" in text, (
        "useNodeFactory.js missing NodeFactoryNotAvailable error class"
    )
    # A throw statement exists
    assert re.search(r"throw\s+new\s+NodeFactoryNotAvailable\b", text), (
        "useNodeFactory.js does not throw NodeFactoryNotAvailable — seam "
        "missing must fail loudly, not silently skip"
    )


# --- T545 ---

def test_t545_use_node_factory_does_not_duplicate_alias_table():
    """T545 · useNodeFactory.js does NOT contain a literal 'smart-container' /
    'smart-image' alias table. Alias is delegated to NodeConfigRegistry."""
    text = COMPOSABLE_PATH.read_text(encoding="utf-8")
    assert "'smart-container'" not in text and '"smart-container"' not in text, (
        "useNodeFactory.js contains literal 'smart-container' — alias table "
        "must live only in NodeConfigRegistry (single source of truth)"
    )
    assert "'smart-image'" not in text and '"smart-image"' not in text, (
        "useNodeFactory.js contains literal 'smart-image' — do not duplicate "
        "alias-target constants; delegate to NodeConfigRegistry.normalizeAlias"
    )


# --- T546 ---

def test_t546_node_store_new_id_prefixes_with_type():
    """T546 · nodeStore.js newId produces `${type}-...` template."""
    assert STORE_PATH.is_file(), (
        f"static/src/stores/nodeStore.js not found at {STORE_PATH}"
    )
    text = STORE_PATH.read_text(encoding="utf-8")
    assert "defineStore" in text, "nodeStore.js missing defineStore call"
    assert re.search(r"defineStore\s*\(\s*['\"]node['\"]", text), (
        "nodeStore.js should defineStore('node', ...)"
    )
    assert "newId" in text, "nodeStore.js missing newId action"
    # Template literal `${type}-...`
    assert re.search(r"`\$\{type\}-", text), (
        "nodeStore.js newId does not produce `${type}-...` prefix"
    )


# --- T547 ---

def test_t547_use_node_factory_uses_listsupportedtypes_not_listtypes():
    """T547 · useNodeFactory.js uses listSupportedTypes (canonical seam method
    name from factories.js), not the (nonexistent) listTypes."""
    text = COMPOSABLE_PATH.read_text(encoding="utf-8")
    assert "listSupportedTypes" in text, (
        "useNodeFactory.js should reference listSupportedTypes "
        "(the canonical NodeFactories seam method)"
    )
    # Guard: no accidental 'listTypes(' call (word-boundary sensitive)
    assert not re.search(r"\.listTypes\s*\(", text), (
        "useNodeFactory.js uses .listTypes(...) — the canonical name is "
        "listSupportedTypes (see static/js/shared/nodes/factories.js:339)"
    )
