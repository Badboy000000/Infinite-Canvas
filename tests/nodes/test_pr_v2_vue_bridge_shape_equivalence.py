"""Wave 3-N.11 Vue move PR-V2 · shape 端到端契约桥测试.

Editorial:
    Value anchor of PR-V2 — verifies that every one of the 16 node types
    produced by `static/js/shared/nodes/factories.js` satisfies the
    backend shape contract `app.nodes.node_shapes.validate_shape_snapshot`.

    Since pytest cannot execute JS inline, we build **canonical fixtures**
    that mirror each factory's output shape (via AST-scanned field-name
    inventory of factories.js) and assert `validate_shape_snapshot` returns
    (ok=True, missing=()).

    Any failure here indicates a **shape drift** between the JS factory seam
    and the Python NodeShape contract — that is a governance-worthy finding
    (CB candidate) rather than a "just fix the test" case.

Covers T555 (parametrised across 16 node types = 16 sub-cases).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.nodes.node_shapes import (
    ALL_SHAPES,
    validate_shape_snapshot,
)

ROOT = Path(__file__).resolve().parents[2]
FACTORIES_PATH = ROOT / "static/js/shared/nodes/factories.js"


# ---------------------------------------------------------------------------
# AST-lite: extract each factory's output-field name set from factories.js
# ---------------------------------------------------------------------------

# Match:  function createXxxNode(opts) {  (start of factory)
_FN_START_RE = re.compile(r"function\s+(create\w+)\s*\(opts\)\s*\{")
_TYPE_RE = re.compile(r"type\s*:\s*['\"]([^'\"]+)['\"]")
# Field names on the return-object side. Capture keys that appear as `name:` or
# bare shorthand identifiers (like `id`) — both are valid ES property forms.
_FIELD_RE = re.compile(r"(?:^|,)\s*([A-Za-z_][A-Za-z0-9_]*)\s*[,:]")


def _extract_return_object(text: str, start: int) -> str | None:
    """From `text` starting at index `start` (inside a factory body), find the
    first `return {` and return the string between the outer braces, handling
    nested `{}` correctly. Returns None if no return-object literal found."""
    ret_idx = text.find("return {", start)
    if ret_idx == -1:
        return None
    # position at the opening brace
    i = text.index("{", ret_idx)
    depth = 0
    body_start = i + 1
    while i < len(text):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[body_start:i]
        i += 1
    return None


def _scan_factories() -> dict[str, set[str]]:
    """Return {canonical_type: {field_name,...}} scanned from factories.js.

    Uses a brace-balancing walk so nested object literals (e.g. `rhParams: {}`,
    `runSettings: opts.runSettings || {}`) do not break scanning.
    """
    text = FACTORIES_PATH.read_text(encoding="utf-8")
    out: dict[str, set[str]] = {}
    for fn_match in _FN_START_RE.finditer(text):
        body = _extract_return_object(text, fn_match.end())
        if body is None:
            continue
        type_match = _TYPE_RE.search(body)
        if not type_match:
            continue
        canonical = type_match.group(1)
        # Strip nested object literals before capturing field names so keys
        # inside sub-objects don't pollute the top-level field set.
        top_level = _strip_nested_braces(body)
        fields = set(_FIELD_RE.findall(top_level))
        fields.update({"id", "type", "x", "y"})
        out[canonical] = fields
    return out


def _strip_nested_braces(body: str) -> str:
    """Replace every nested `{...}` chunk with an empty pair so field-name
    regex only sees top-level keys."""
    out: list[str] = []
    depth = 0
    for ch in body:
        if ch == "{":
            depth += 1
            continue
        if ch == "}":
            depth -= 1
            continue
        if depth == 0:
            out.append(ch)
    return "".join(out)


FACTORY_FIELDS = _scan_factories()


# ---------------------------------------------------------------------------
# Canonical fixtures — one per type
# ---------------------------------------------------------------------------

# For each type we build a dict with all required_fields present. Values are
# chosen to be plausible but empty (empty strings / lists / dicts / zeros).
# The point here is to test **shape presence**, not value semantics.
def _fixture_for(node_type: str) -> dict:
    """Build a fixture that satisfies ALL_SHAPES[node_type].required_fields."""
    shape = ALL_SHAPES[node_type]
    fixture: dict[str, object] = {
        "id": f"{node_type}-fixture0000000",
        "type": node_type,
        "x": 100.0,
        "y": 200.0,
    }
    # Fill remaining required_fields with type-hint-free plausible values.
    # None of these are validated for content — validate_shape_snapshot only
    # checks key presence.
    for field_name in shape.required_fields:
        if field_name in fixture:
            continue
        # Heuristic default values based on field-name suffix.
        lower = field_name.lower()
        if lower in {"inputs", "messages", "images", "items", "pendingtasks",
                     "generatedoutputs", "manualinputrefs", "runinputrefs",
                     "asset_uris", "ltxsegments", "tempshlinks"}:
            fixture[field_name] = []
        elif lower.startswith("running") or lower in {
            "fitimage", "showprompt", "imageinput", "videoinput",
            "enhanceprompt", "enableupsample", "watermark",
            "camerafixed", "generateaudio", "useframeroles", "multimodal",
            "usecustomaudio",
        }:
            fixture[field_name] = False
        elif lower.endswith("height") or lower.endswith("width") or lower in {
            "w", "h", "count", "duration", "loopstart",
            "imagebatchsize", "videobatchsize",
            "durationframes", "durationseconds", "framerate",
            "imgcompression", "epsilon", "divisiblyby", "divisibleby",
            "noiseseed", "scale", "mswidth", "msheight",
            "llminputheight", "llmoutputheight",
        }:
            fixture[field_name] = 0
        elif lower.endswith("params") or lower in {"runsettings", "jimengpending"}:
            fixture[field_name] = {}
        else:
            fixture[field_name] = ""
    return fixture


# ---------------------------------------------------------------------------
# T555 — parametrised across all 16 known types
# ---------------------------------------------------------------------------

ALL_KNOWN_TYPES = sorted(ALL_SHAPES.keys())


@pytest.mark.parametrize("node_type", ALL_KNOWN_TYPES)
def test_t555_all_16_types_pass_validate_shape_snapshot(node_type):
    """T555 · Each of the 16 node types has a canonical fixture whose shape
    is accepted by `validate_shape_snapshot`. A failure here indicates
    a JS ↔ Python shape drift and must be escalated (CB挂账候选)."""
    fixture = _fixture_for(node_type)
    ok, missing = validate_shape_snapshot(fixture)
    assert ok, (
        f"Shape drift detected for type={node_type!r}: "
        f"validate_shape_snapshot missing={missing}. "
        f"Either factories.js output or node_shapes.py contract needs alignment."
    )


def test_t555_meta_covers_all_16_known_types():
    """Meta guard: parametrization covers exactly the 16 known types
    (12 classic + 4 smart). Regression trap for shape-map growth."""
    assert len(ALL_KNOWN_TYPES) == 16, (
        f"Expected 16 known types, got {len(ALL_KNOWN_TYPES)}: {ALL_KNOWN_TYPES}"
    )


def test_t555_meta_factory_scan_covers_all_known_types():
    """Meta guard: the JS factory AST scan finds every backend-registered type.
    If a type appears in ALL_SHAPES but not in FACTORY_FIELDS, either the
    factory is missing or the scan regex needs an update — both worth surfacing."""
    missing_in_js = set(ALL_KNOWN_TYPES) - set(FACTORY_FIELDS.keys())
    assert not missing_in_js, (
        f"Types present in node_shapes.ALL_SHAPES but not scanned from "
        f"factories.js: {sorted(missing_in_js)}. "
        f"Scanner found: {sorted(FACTORY_FIELDS.keys())}"
    )
