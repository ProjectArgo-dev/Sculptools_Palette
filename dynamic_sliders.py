# sculptools_palette/dynamic_sliders.py
#
# "Dynamic Sliders": right-click + drag in Sculpt Mode to adjust the active
# brush's Radius (horizontal drag) or Strength (vertical drag), RadialZ-style,
# with a small live value overlay. A quick right-click (tap, no drag) still
# opens Blender's native sculpt context panel.
#
# Why we bind to RIGHTMOUSE *PRESS* (not CLICK_DRAG): the default Sculpt keymap
# opens its context menu with `wm.call_panel` on RIGHTMOUSE PRESS. A CLICK_DRAG
# item would be pre-empted by that PRESS and never fire. So we take over plain
# RIGHTMOUSE PRESS in the addon keyconfig (higher priority), start a modal, and:
#   - if the cursor drags past a threshold  -> engage the slider;
#   - if it is released without dragging     -> re-open the native panel ourselves.
# Modified right-clicks (Ctrl/Alt/Shift: stencil, mask lasso, pivot) are left
# untouched because our keymap item matches plain RIGHTMOUSE only.

import bpy
import blf
from bpy.types import Operator

from .prefs import get_prefs

# ── interaction tuning (kept as module constants — easy to expose later) ──────
DRAG_THRESHOLD = 8.0            # px of travel before the axis locks / slider engages
RADIUS_SENS    = 1.0           # brush-size px per px of horizontal drag
STRENGTH_SENS  = 1.0 / 200.0   # full 0..1 sweep over ~200px of vertical drag
SIZE_MAX       = 5000          # generous hard cap for brush size in px
CONTEXT_PANEL  = "VIEW3D_PT_sculpt_context_menu"  # native sculpt RMB panel


# ── pure logic (unit-tested in run_functional_tests.py) ───────────────────────

def _axis_lock(dx, dy, threshold=DRAG_THRESHOLD):
    """Decide which slider a drag controls, from its delta off the press point.
    Returns 'RADIUS' (horizontal dominates), 'STRENGTH' (vertical dominates) or
    None while still under the engage threshold."""
    if (dx * dx + dy * dy) < (threshold * threshold):
        return None
    return 'RADIUS' if abs(dx) >= abs(dy) else 'STRENGTH'


def _clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


# ── brush value access (honours Unified Paint Settings) ───────────────────────
# Module-level so both this operator AND the pie-wheel modal (which offers the
# same right-drag adjustment while the wheel is open) can share one code path.

def _unified_paint_settings(ts):
    """Locate the UnifiedPaintSettings, whose home moved between versions:
      • Blender ≤ 4.x : on ToolSettings itself (`ts.unified_paint_settings`);
      • Blender ≥ 5.0 : on the per-mode Paint (`ts.sculpt.unified_paint_settings`)
        — reading `ts.unified_paint_settings` there raises AttributeError, which
        is exactly the crash the right-drag sliders hit on 5.1.
    Return the UPS or None if neither exists. All four accessors below route
    through this so they work on both."""
    if ts is None:
        return None
    ups = getattr(ts, "unified_paint_settings", None)   # 4.x
    if ups is not None:
        return ups
    sc = getattr(ts, "sculpt", None)                    # 5.x
    return getattr(sc, "unified_paint_settings", None) if sc else None


def read_brush_size(context):
    ts = getattr(context, "tool_settings", None)
    if ts is None:
        return 0
    ups = _unified_paint_settings(ts)
    if ups is not None and ups.use_unified_size:
        return ups.size
    sc = getattr(ts, "sculpt", None)
    b = sc.brush if sc else None
    return b.size if b else 0


def read_brush_strength(context):
    ts = getattr(context, "tool_settings", None)
    if ts is None:
        return 0.0
    ups = _unified_paint_settings(ts)
    if ups is not None and ups.use_unified_strength:
        return ups.strength
    sc = getattr(ts, "sculpt", None)
    b = sc.brush if sc else None
    return b.strength if b else 0.0


def write_brush_size(context, val):
    val = int(round(_clamp(val, 1, SIZE_MAX)))
    ts = getattr(context, "tool_settings", None)
    ups = _unified_paint_settings(ts)
    if ups is not None and ups.use_unified_size:
        ups.size = val
    else:
        sc = getattr(ts, "sculpt", None)
        if sc and sc.brush:
            sc.brush.size = val
    return val


def write_brush_strength(context, val):
    val = _clamp(val, 0.0, 1.0)
    ts = getattr(context, "tool_settings", None)
    ups = _unified_paint_settings(ts)
    if ups is not None and ups.use_unified_strength:
        ups.strength = val
    else:
        sc = getattr(ts, "sculpt", None)
        if sc and sc.brush:
            sc.brush.strength = val
    return val


# ── live value overlay ────────────────────────────────────────────────────────
# Module-level so the POST_PIXEL draw callback (which takes no args) can read it.
_overlay = {'active': False, 'mode': None, 'x': 0, 'y': 0,
            'radius': 0, 'strength': 0.0}
_overlay_handle = None


def _draw_overlay_cb():
    if not _overlay['active']:
        return
    font = 0
    x = _overlay['x'] + 18
    y = _overlay['y'] + 18
    blf.size(font, 14)
    rows = (
        ("Radius: %d px"   % _overlay['radius'],   _overlay['mode'] == 'RADIUS'),
        ("Strength: %.2f"  % _overlay['strength'], _overlay['mode'] == 'STRENGTH'),
    )
    yy = y
    for text, is_active in rows:
        if is_active:
            blf.color(font, 0.95, 0.62, 0.13, 1.0)   # highlight the active axis
        else:
            blf.color(font, 0.65, 0.65, 0.65, 1.0)
        blf.position(font, x, yy, 0)
        blf.draw(font, text)
        yy -= 20


def _enable_overlay():
    global _overlay_handle
    if _overlay_handle is None:
        _overlay_handle = bpy.types.SpaceView3D.draw_handler_add(
            _draw_overlay_cb, (), 'WINDOW', 'POST_PIXEL')


def _disable_overlay():
    global _overlay_handle
    if _overlay_handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_overlay_handle, 'WINDOW')
        _overlay_handle = None


def _tag_redraw(context):
    area = getattr(context, 'area', None)
    if area:
        area.tag_redraw()


# ── operator ──────────────────────────────────────────────────────────────────

class SCULPTOOLS_OT_dynamic_sliders(Operator):
    bl_idname  = "sculptools.dynamic_sliders"
    bl_label   = "Sculptools Dynamic Sliders"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'SCULPT'

    def invoke(self, context, event):
        prefs = get_prefs(context)
        if not getattr(prefs, 'dynamic_sliders_enabled', True):
            return {'PASS_THROUGH'}   # feature off → let native RMB happen

        ts = context.tool_settings
        sculpt = getattr(ts, 'sculpt', None)
        brush  = sculpt.brush if sculpt else None
        if brush is None:
            return {'PASS_THROUGH'}

        self._start_x = event.mouse_region_x
        self._start_y = event.mouse_region_y
        self._start_size     = read_brush_size(context)
        self._start_strength = read_brush_strength(context)
        self._mode     = None
        self._finished = False

        _overlay.update(active=False, mode=None,
                        x=event.mouse_region_x, y=event.mouse_region_y,
                        radius=int(round(self._start_size)),
                        strength=float(self._start_strength))
        _enable_overlay()
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    # ── modal ─────────────────────────────────────────────────────────────────

    def modal(self, context, event):
        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            dx = event.mouse_region_x - self._start_x
            dy = event.mouse_region_y - self._start_y
            _overlay['x'] = event.mouse_region_x
            _overlay['y'] = event.mouse_region_y

            if self._mode is None:
                self._mode = _axis_lock(dx, dy)
                if self._mode is not None:
                    _overlay['active'] = True
                    _overlay['mode']   = self._mode

            if self._mode == 'RADIUS':
                _overlay['radius'] = write_brush_size(
                    context, self._start_size + dx * RADIUS_SENS)
            elif self._mode == 'STRENGTH':
                _overlay['strength'] = write_brush_strength(
                    context, self._start_strength + dy * STRENGTH_SENS)

            _tag_redraw(context)
            return {'RUNNING_MODAL'}

        if event.type == 'RIGHTMOUSE' and event.value == 'RELEASE':
            was_drag = self._mode is not None
            self._finish(context)
            if not was_drag:
                # Tap (no drag) → reproduce Blender's native sculpt context panel.
                try:
                    bpy.ops.wm.call_panel('INVOKE_DEFAULT',
                                          name=CONTEXT_PANEL, keep_open=False)
                except Exception:
                    pass
            return {'FINISHED'}

        if event.type == 'ESC' and event.value == 'PRESS':
            self._finish(context)
            return {'CANCELLED'}

        return {'RUNNING_MODAL'}

    def _finish(self, context):
        if getattr(self, '_finished', False):
            return
        self._finished = True
        _overlay['active'] = False
        _disable_overlay()
        _tag_redraw(context)


all_dynamic_slider_classes = [SCULPTOOLS_OT_dynamic_sliders]
