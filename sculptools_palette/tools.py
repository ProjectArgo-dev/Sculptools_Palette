# sculptools_palette/tools.py
#
# Catalogue of Sculpt Mode TOOLS and one-shot ACTIONS that a wheel slot can hold
# in addition to brushes (see brushes.py). A slot stores a bare brush name OR a
# "tool:<key>" sentinel; the key indexes TOOLS here. Pure data + pure helpers —
# NO bpy import, so it is unit-testable under the validation stubs.
#
# Row fields:
#   key            catalogue key used in the "tool:<key>" slot string
#   display        menu label / wheel text (e.g. "Box Mask")
#   kind           'TOOL' -> arm via wm.tool_set_by_id; 'OP' -> one-shot execute
#   target         'TOOL': the tool_set_by_id name ("builtin.box_mask")
#                  'OP'  : the operator path ("paint.mask_flood_fill")
#   params         operator kwargs dict (OP only; {} for TOOL)
#   exec_ctx       operator execution context (OP only; None for TOOL)
#   category       grouping for the "Assign Tool" menu
#   fallback_label short text drawn inside the wheel disc
#
# NOTE: every idname below must be confirmed against the running Blender build
# (see the plan's Blender-confirmation task). A wrong idname makes that one row a
# silent no-op; correcting it is a one-line edit.

from collections import namedtuple

TOOL_PREFIX = "tool:"

ToolEntry = namedtuple(
    "ToolEntry",
    "key display kind target params exec_ctx category fallback_label min_version",
)


def _tool(key, display, target, category, fallback_label, min_version=None):
    return ToolEntry(key, display, 'TOOL', target, {}, None, category,
                     fallback_label, min_version)


def _op(key, display, target, params, category, fallback_label,
        exec_ctx='EXEC_DEFAULT', min_version=None):
    return ToolEntry(key, display, 'OP', target, params, exec_ctx,
                     category, fallback_label, min_version)


CATEGORY_ORDER = ("Add", "Mask", "Face Sets", "Trim", "Project", "Filter")

TOOLS = [
    # ── Add — primitive tools (Blender 5.2+, gated via min_version) ──
    _tool("primitive_cube_add",       "Add Cube",       "builtin.primitive_cube_add",       "Add", "Cube",     min_version=(5, 2, 0)),
    _tool("primitive_cone_add",       "Add Cone",       "builtin.primitive_cone_add",       "Add", "Cone",     min_version=(5, 2, 0)),
    _tool("primitive_cylinder_add",   "Add Cylinder",   "builtin.primitive_cylinder_add",   "Add", "Cylinder", min_version=(5, 2, 0)),
    _tool("primitive_uv_sphere_add",  "Add UV Sphere",  "builtin.primitive_uv_sphere_add",  "Add", "UV Sph",   min_version=(5, 2, 0)),
    _tool("primitive_ico_sphere_add", "Add Ico Sphere", "builtin.primitive_ico_sphere_add", "Add", "Ico Sph",  min_version=(5, 2, 0)),
    # ── Mask — interactive gesture tools ──
    _tool("box_mask",       "Box Mask",       "builtin.box_mask",       "Mask", "Box Mask"),
    _tool("lasso_mask",     "Lasso Mask",     "builtin.lasso_mask",     "Mask", "Lasso Mask"),
    _tool("line_mask",      "Line Mask",      "builtin.line_mask",      "Mask", "Line Mask"),
    _tool("polyline_mask",  "Polyline Mask",  "builtin.polyline_mask",  "Mask", "Poly Mask"),
    _tool("mask_by_color",  "Mask by Color",  "builtin.mask_by_color",  "Mask", "Mask Col"),
    # ── Mask — one-shot actions ──
    _op("mask_clear",  "Clear Mask",  "paint.mask_flood_fill", {"mode": 'VALUE', "value": 0.0}, "Mask", "Clr Mask"),
    _op("mask_invert", "Invert Mask", "paint.mask_flood_fill", {"mode": 'INVERT'},              "Mask", "Inv Mask"),
    _op("mask_fill",   "Fill Mask",   "paint.mask_flood_fill", {"mode": 'VALUE', "value": 1.0}, "Mask", "Fill Mask"),
    # ── Face Sets — interactive ──
    _tool("box_face_set",   "Box Face Set",   "builtin.box_face_set",   "Face Sets", "Box FSet"),
    _tool("lasso_face_set", "Lasso Face Set", "builtin.lasso_face_set", "Face Sets", "Lasso FSet"),
    _tool("line_face_set",  "Line Face Set",  "builtin.line_face_set",  "Face Sets", "Line FSet"),
    _tool("polyline_face_set", "Polyline Face Set", "builtin.polyline_face_set", "Face Sets", "Poly FSet"),
    _tool("face_set_edit",  "Edit Face Set",  "builtin.face_set_edit",  "Face Sets", "Edit FSet"),
    # ── Face Sets — one-shot ──
    # "Face Set from Masked/Visible" = sculpt.face_sets_CREATE (NOT face_sets_init,
    # which has no MASKED/VISIBLE mode). Confirmed against the 4.5 API docs.
    _op("face_set_from_masked",  "Face Set from Masked",  "sculpt.face_sets_create", {"mode": 'MASKED'},  "Face Sets", "FSet Msk"),
    _op("face_set_from_visible", "Face Set from Visible", "sculpt.face_sets_create", {"mode": 'VISIBLE'}, "Face Sets", "FSet Vis"),
    # "Initialize Face Sets" opens Blender's native init submenu (By Loose Parts,
    # By Materials, By Normals, ...) instead of firing one fixed mode. INVOKE +
    # deferred one tick (see modal._activate_slot) so the popup opens after the
    # wheel modal releases the input grab. Menu idname confirmed in Blender.
    _op("face_sets_init",   "Initialize Face Sets", "wm.call_menu", {"name": "VIEW3D_MT_face_sets_init"}, "Face Sets", "Init FSet", exec_ctx='INVOKE_DEFAULT'),
    # "Reveal All" = paint.hide_show_all(SHOW); sculpt.reveal_all does not exist in 4.5.
    _op("face_sets_reveal", "Reveal All",     "paint.hide_show_all",   {"action": 'SHOW'}, "Face Sets", "Reveal"),
    # ── Trim — interactive ──
    _tool("box_trim",       "Box Trim",       "builtin.box_trim",       "Trim", "Box Trim"),
    _tool("lasso_trim",     "Lasso Trim",     "builtin.lasso_trim",     "Trim", "Lasso Trim"),
    _tool("line_trim",      "Line Trim",      "builtin.line_trim",      "Trim", "Line Trim"),
    _tool("polyline_trim",  "Polyline Trim",  "builtin.polyline_trim",  "Trim", "Poly Trim"),
    # ── Project ──
    _tool("line_project",   "Line Project",   "builtin.line_project",   "Project", "Line Proj"),
    # ── Filter ──
    _tool("mesh_filter",    "Mesh Filter",    "builtin.mesh_filter",    "Filter", "Mesh Filt"),
    _tool("cloth_filter",   "Cloth Filter",   "builtin.cloth_filter",   "Filter", "Cloth Filt"),
    _tool("color_filter",   "Color Filter",   "builtin.color_filter",   "Filter", "Color Filt"),
]

_BY_KEY = {e.key: e for e in TOOLS}


def is_tool_spec(spec):
    """True iff a slot string is a tool spec ('tool:<key>')."""
    return isinstance(spec, str) and spec.startswith(TOOL_PREFIX)


def _key_of(spec):
    return spec[len(TOOL_PREFIX):] if is_tool_spec(spec) else None


def get_tool(spec_or_key):
    """Look up a ToolEntry by full 'tool:<key>' spec OR bare key. None if unknown."""
    key = _key_of(spec_or_key) if is_tool_spec(spec_or_key) else spec_or_key
    return _BY_KEY.get(key)


def parse_spec(spec):
    """('brush', name) for a bare brush; ('tool', ToolEntry|None) for a tool spec
    (None when the key is unknown — caller no-ops gracefully)."""
    if is_tool_spec(spec):
        return ("tool", _BY_KEY.get(_key_of(spec)))
    return ("brush", spec)


def is_oneshot(spec):
    """True only for a KNOWN tool spec whose kind is 'OP'. Brushes, interactive
    tools, and unknown keys are all False (so nothing destructive is inferred)."""
    entry = get_tool(spec) if is_tool_spec(spec) else None
    return bool(entry) and entry.kind == 'OP'


def is_popup(spec):
    """True for a tool spec that opens a Blender popup (wm.call_menu / _pie /
    call_panel). Such specs must fire on mouse RELEASE, not PRESS, so the popup
    opens with the button up and stays open on a plain click (see modal)."""
    entry = get_tool(spec) if is_tool_spec(spec) else None
    return bool(entry) and entry.kind == 'OP' and entry.target.startswith("wm.call_")


def best_tool_label(spec):
    """Wheel/menu label for a tool spec: catalogue fallback_label (or display).
    For an unknown key, return the bare key so the slot still shows something."""
    entry = get_tool(spec) if is_tool_spec(spec) else None
    if entry:
        return entry.fallback_label or entry.display
    return _key_of(spec) or spec


def tool_available(entry, blender_version):
    """True se questo tool esiste sulla data versione Blender. Entry con
    min_version=None sono sempre disponibili; altrimenti serve
    tuple(blender_version) >= entry.min_version. Puro (no bpy) — il chiamante
    (operators.py) passa bpy.app.version."""
    mv = entry.min_version
    return mv is None or tuple(blender_version) >= tuple(mv)
