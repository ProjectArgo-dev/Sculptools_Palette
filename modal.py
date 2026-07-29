# sculptools_palette/modal.py

import math
import time
import bpy
from bpy.types import Operator

from .gpu_draw import (draw_palette, _slot_angle, _sub_positions, _effective_layout,
                       GEAR_CENTER_DY, GEAR_RADIUS)
from .prefs import (get_prefs, get_slot, get_sub, get_num_slots, NUM_SUBSLOTS,
                    get_active_palette, ensure_palettes, key_label, wrap_index,
                    request_prefs_save, get_cycle_key_binding, get_open_key_binding,
                    keys_conflict, key_chord_label, jump_modifier_flags,
                    sync_cycle_back_binding, MAX_PALETTES)
from .quick_numbers import _QN_KEYS

ASSET_FILE = "brushes/essentials_brushes-mesh_sculpt.blend"

# Number → palette index for the jump INSIDE the wheel. The global keymap item
# `sculptools.jump_palette` does not fire while the modal holds the grab, so the
# jump with the wheel open is handled directly by modal() with this map (same
# keys as the global binding: ONE..EIGHT → palette 0..MAX_PALETTES-1).
_JUMP_KEY_INDEX = {key: i for i, key in enumerate(_QN_KEYS[:MAX_PALETTES])}

FADE_IN = 0.10   # seconds to fade sub-slots in

QUICK_FLICK_WINDOW = 0.18   # seconds after opening during which a fast, decisive
                            # mouse flick toward a slot will instantly select it
QUICK_FLICK_DIST_FACTOR = 0.5  # fraction of palette radius the cursor must
                                # travel from the press point to count as a flick

# ── module-level state shared with operators ──────────────────────────────────
_slot_clipboard      = {'brush': ''}      # copy/paste between slots
_slot_context_target = {'slot': -1, 'sub': -1}  # set before opening context menu
# True while a wheel modal is running (set in invoke/_finish). Lets the slot
# context-menu assign operators tell whether there is an open wheel to close.
_wheel_active        = {'on': False}
# Set True by the assign operators (Add Active Brush / Assign Tool) after they
# write a slot WHILE the wheel is open. The modal polls it at the top of modal()
# and finishes, so assigning from the slot context menu auto-closes the wheel.
_close_after_assign  = {'pending': False}


# ── brush activation ──────────────────────────────────────────────────────────

def _activate_brush(brush_name):
    from .brushes import BRUSHES
    for display, bpy_data_name, asset_name, _icon in BRUSHES:
        if brush_name in (display, bpy_data_name, asset_name):
            _do_activate(bpy_data_name, asset_name)
            return
    # Not one of Blender's Essentials → a custom asset-library brush (or a plain
    # local brush). Activating it from ESSENTIALS would fail ("No asset found"),
    # which is exactly why custom brushes stayed on Draw after reopening a file.
    _do_activate_custom(brush_name)


def _activate_slot(spec):
    """Dispatch a slot's stored value. Brush specs (no prefix) go to the
    existing brush path unchanged. 'tool:<key>' specs arm an interactive tool
    (wm.tool_set_by_id) or fire a one-shot operator. Unknown key / operator
    failure = logged no-op, never an exception (mirrors the custom-brush
    fallback). Called at modal confirm/flick, never inside the POST_PIXEL
    draw callback (golden rule #4)."""
    from .tools import parse_spec
    kind, payload = parse_spec(spec)
    if kind != 'tool':
        _activate_brush(spec)
        return
    entry = payload
    if entry is None:
        print(f"Sculptools: unknown tool key in '{spec}'")
        return
    try:
        if entry.kind == 'TOOL':
            bpy.ops.wm.tool_set_by_id(name=entry.target)
        else:  # 'OP'
            module, func = entry.target.split(".", 1)
            op = getattr(getattr(bpy.ops, module), func)
            ctx = entry.exec_ctx or 'INVOKE_DEFAULT'
            if entry.target.startswith("wm.call_"):
                # A popup (call_menu/call_menu_pie/call_panel) cannot open while
                # this radial modal still holds the input grab and is about to
                # return FINISHED. Defer one tick: by then the wheel has closed
                # and the menu pops under the cursor (golden rule #4 async).
                _defer_popup(op, ctx, dict(entry.params), spec)
            else:
                op(ctx, **entry.params)
    except Exception as exc:
        print(f"Sculptools: tool '{spec}' activation failed: {exc}")


def _defer_popup(op, ctx, params, spec):
    """Schedule a menu/popup operator on the next timer tick (outside the modal)."""
    def _later():
        try:
            op(ctx, **params)
        except Exception as exc:
            print(f"Sculptools: menu '{spec}' failed to open: {exc}")
        return None
    try:
        bpy.app.timers.register(_later, first_interval=0.01)
    except Exception as exc:
        print(f"Sculptools: could not schedule menu '{spec}': {exc}")


def _do_activate_custom(name):
    """Activate a brush that is NOT one of Blender's Essentials: a brush from a
    user's custom asset library, or a plain local brush. Order:
      1. a live local copy (LOCAL activation for an asset, else set it active);
      2. the custom asset library it came from — resolved (and cached) by the
         thumbnail scan (gpu_draw.resolve_asset_source), activated as CUSTOM.
    This is what lets custom-library brushes activate after the file is reopened
    (when they are not yet instantiated in bpy.data.brushes)."""
    brush = bpy.data.brushes.get(name)
    if brush is not None:
        if getattr(brush, "asset_data", None) is not None:
            try:
                r = bpy.ops.brush.asset_activate(
                    asset_library_type='LOCAL',
                    relative_asset_identifier=brush.name)
                if 'FINISHED' in r:
                    return
            except Exception:
                pass
        try:
            sc = bpy.context.tool_settings.sculpt
            if sc is not None:
                sc.brush = brush
                return
        except Exception:
            pass

    # Not instantiated locally → activate straight from the custom asset library
    # the thumbnail scan found it in.
    try:
        from .gpu_draw import resolve_asset_source
        src = resolve_asset_source(name)
    except Exception:
        src = None
    if src:
        lib_name, rel_id = src
        try:
            bpy.ops.brush.asset_activate(
                asset_library_type='CUSTOM',
                asset_library_identifier=lib_name,
                relative_asset_identifier=rel_id)
        except Exception:
            pass

def _do_activate(bpy_data_name, asset_name):
    brush = bpy.data.brushes.get(bpy_data_name) or bpy.data.brushes.get(asset_name)
    # Only try LOCAL activation when the brush actually exists locally AND is
    # marked as an asset — otherwise the LOCAL attempt is doomed and Blender
    # prints a "No asset found at path '…'" warning before we fall back to
    # ESSENTIALS (handoff §6.3). The identifier for a LOCAL asset is the bare
    # brush name, NOT "Brush/<name>" (that path-style form is only for the
    # ESSENTIALS library file below) — the old "Brush/" prefix was itself the
    # source of the 'Brush/…' text in that warning.
    if brush is not None and getattr(brush, "asset_data", None) is not None:
        try:
            r = bpy.ops.brush.asset_activate(
                asset_library_type='LOCAL',
                relative_asset_identifier=brush.name)
            if 'FINISHED' in r:
                return
        except Exception:
            pass
    try:
        bpy.ops.brush.asset_activate(
            asset_library_type='ESSENTIALS',
            relative_asset_identifier=f"{ASSET_FILE}/Brush/{asset_name}")
    except Exception:
        pass


# ── geometry helpers ──────────────────────────────────────────────────────────

def _dist(ax, ay, bx, by):
    return math.sqrt((ax - bx)**2 + (ay - by)**2)

def _slot_pos(cx, cy, R, i, n=8):
    a = _slot_angle(i, n)
    return cx + math.cos(a) * R, cy + math.sin(a) * R

def _nearest_slot(angle, n=8):
    """Return the index of the main slot whose angle is closest to `angle`."""
    best_i, best_d = 0, None
    for i in range(n):
        a = _slot_angle(i, n)
        d = abs(math.atan2(math.sin(angle - a), math.cos(angle - a)))  # shortest angular distance
        if best_d is None or d < best_d:
            best_i, best_d = i, d
    return best_i




# ── modal operator ────────────────────────────────────────────────────────────

class SCULPTOOLS_OT_radial_palette(Operator):
    bl_idname  = "sculptools.radial_palette"
    bl_label   = "Sculptools Palette"
    # NO 'UNDO' — on purpose. 'UNDO' makes Blender push a global (memfile) undo
    # step when this modal finishes. In Sculpt Mode, once strokes have dirtied the
    # mesh, that push serialises the WHOLE mesh into the undo memfile: O(vertices),
    # ~2 s on dense meshes. That was the "wheel freezes for ~2 s after sculpting,
    # then switches brush" lag — and only after sculpting, because with a clean
    # mesh there is nothing new to serialise. The wheel needs no undo of its own:
    # brush activation carries its own undo and the strokes stay undoable. This
    # matches the other in-sculpt interactive operators (Quick Numbers, Dynamic
    # Sliders), which are 'REGISTER'-only for the same reason.
    bl_options = {'REGISTER'}

    def _refresh_layout(self, context):
        """Recompute num_slots (per-palette), the EFFECTIVE values of wheel radius
        and sub distance (anti-overlap, gpu_draw._effective_layout) AND the cached
        slot/sub contents. Called at invoke, on palette reload (cycle/jump:
        num_slots changes) and on every draw frame: draw and hit-test read the same
        self._*, so they coincide by construction.

        The slot caches are refreshed HERE, in the same place as _num_slots, and
        nowhere else: the hit-test indexes _slots by a value bounded only by
        _num_slots, so letting the two drift apart made a click land past the end of
        the list (IndexError). That is exactly what happened when this method was
        called from _draw_cb — which updated _num_slots alone — right after the
        active palette changed to one with MORE slots (deleting a palette from the
        gear menu clamps onto a neighbour, and the wheel stays open behind it).
        Deriving both from one call makes the desync structurally impossible."""
        prefs = get_prefs(context)
        self._num_slots = get_num_slots(context)
        self._R, self._sub_separation = _effective_layout(
            prefs.palette_radius, prefs.slot_radius,
            prefs.sub_size_factor, prefs.sub_separation,
            self._num_slots)
        self._slots = [get_slot(context, i) for i in range(self._num_slots)]
        self._sub_slots = [[get_sub(context, i, j) for j in range(NUM_SUBSLOTS)]
                           for i in range(self._num_slots)]

    def _slot_name(self, i):
        """Cached name of main slot *i*, or "" when out of range. Belt-and-braces
        over the invariant _refresh_layout now guarantees (len(_slots) ==
        _num_slots): an out-of-range click must degrade to "empty slot", never
        raise inside the modal. Mirrors the same guard _hit_sub and
        gpu_draw.draw_palette already apply on their side."""
        return self._slots[i] if 0 <= i < len(self._slots) else ""

    def invoke(self, context, event):
        prefs = get_prefs(context)
        self._refresh_layout(context)   # num_slots + EFFECTIVE R/sub_separation
        self._sr         = prefs.slot_radius
        self._hover_del  = prefs.hover_delay
        self._fade_out   = prefs.fade_out_duration
        self._slot_outline_w      = prefs.slot_outline_width
        self._sub_outline_w       = prefs.subslot_outline_width
        self._slot_outline_c      = tuple(prefs.slot_outline_colour)
        self._sub_outline_c       = tuple(prefs.subslot_outline_colour)
        self._sub_size_factor = prefs.sub_size_factor
        self._glow_size       = prefs.glow_size
        self._glow_intensity  = prefs.glow_intensity
        self._glow_falloff    = prefs.glow_falloff
        self._fixed_slot_outline = prefs.fixed_slot_outline

        # Remember which key opened the wheel so "press the same key again to
        # close" works with any binding the user chooses (default is now '\',
        # BACK_SLASH — the open hotkey is configurable, see panel.py/__init__).
        self._open_key = getattr(event, "type", "BACK_SLASH")
        self._open_binding  = get_open_key_binding(context)
        self._cycle_binding = get_cycle_key_binding(context)  # (type,ctrl,alt,shift,oskey)
        # Realign the back holder (Shift+<cycle key>) when the wheel opens, outside
        # the draw path: so a rebind of the cycle key propagates to backward cycling
        # without mutating the keymap during the native capture widget.
        sync_cycle_back_binding(context)
        self._gear_hov  = False

        self._cx = event.mouse_region_x
        self._cy = event.mouse_region_y
        self._mx = self._cx
        self._my = self._cy

        self._hov_slot    = None
        self._hov_sub     = None
        self._hover_since = {}   # slot_i → time when cursor entered
        self._leave_time  = {}   # slot_i → time when cursor left
        self._sub_alpha   = {}   # slot_i → 0..1
        self._sub_vis     = set()

        self._start_time  = time.time()
        self._quick_resolved = False   # becomes True once the quick-flick
                                        # window has been used up or consumed
        self._finished    = False      # guards _finish() against double-call
        self._pending_popup = None     # a menu-opener slot clicked on PRESS is
                                        # fired on RELEASE (so the popup opens
                                        # with the mouse button up = persistent)
        self._pending_palette_menu = False   # gear clicked: open the menu on RELEASE

        # Right-drag brush adjust (Dynamic Sliders) while the wheel is open:
        # a right-click TAP still opens the slot menu / closes the wheel, but a
        # right-press + drag adjusts Radius (horizontal) / Strength (vertical).
        self._rmb_down    = False
        self._rmb_dragged = False
        self._rmb_mode    = None
        self._rmb_start   = (self._cx, self._cy)
        self._rmb_start_size     = 0
        self._rmb_start_strength = 0.0

        # (slot/sub caches were already filled by _refresh_layout above)
        pit = get_active_palette(context)
        self._slot_outline_c = tuple(pit.slot_outline_colour)
        self._sub_outline_c  = tuple(pit.subslot_outline_colour)

        self._draw_handle = bpy.types.SpaceView3D.draw_handler_add(
            self._draw_cb, (context,), 'WINDOW', 'POST_PIXEL')
        self._timer = context.window_manager.event_timer_add(
            0.016, window=context.window)

        # Mark a wheel as open and clear any leftover close request, so a stale
        # flag can never auto-close a freshly opened wheel.
        _wheel_active['on'] = True
        _close_after_assign['pending'] = False

        context.window_manager.modal_handler_add(self)
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}

    def _open_palette_menu(self):
        """Open the gear's palette menu on a timer tick (outside the modal), so the
        popup is born with the button already released and is not dismissed by the
        press-drag-release semantics (like _defer_popup for the slot popups)."""
        def _later():
            try:
                bpy.ops.wm.call_menu('INVOKE_DEFAULT',
                                     name='SCULPTOOLS_MT_palette_context')
            except Exception as exc:
                print(f"Sculptools: palette menu failed to open: {exc}")
            return None
        try:
            bpy.app.timers.register(_later, first_interval=0.01)
        except Exception as exc:
            print(f"Sculptools: could not schedule palette menu: {exc}")

    def _reload_active_palette(self, context):
        pit = get_active_palette(context)
        # num_slots is per-palette: update it BEFORE re-reading the slots, so that
        # switching palette makes the geometry (including the EFFECTIVE anti-overlap
        # values) adapt to its slot count.
        self._refresh_layout(context)   # slot/sub caches included
        self._slot_outline_c = tuple(pit.slot_outline_colour)
        self._sub_outline_c  = tuple(pit.subslot_outline_colour)

    # ── draw ──────────────────────────────────────────────────────────────────

    def _draw_cb(self, context):
        # Always read current prefs so palette reflects changes made by
        # the context menu operators while the modal is still running.
        # num_slots is per-palette → refresh it live so create/switch/delete
        # reflect the active palette's slot count without reopening.
        # This also refreshes the slot caches below, so what is DRAWN and what the
        # hit-test reads are the very same lists (they used to be two separate
        # reads, which is how they could disagree).
        self._refresh_layout(context)
        slots     = self._slots
        sub_slots = self._sub_slots
        elapsed = time.time() - self._start_time
        prefs = get_prefs(context)
        pit = get_active_palette(context)
        pal_total = len(prefs.palettes)
        pal_index = prefs.active_palette_index + 1
        draw_palette({
            'cx':            self._cx,
            'cy':            self._cy,
            'radius':        self._R,
            'slot_r':        self._sr,
            'slots':         slots,
            'sub_slots':     sub_slots,
            'num_slots':     self._num_slots,
            'hovered_slot':  self._hov_slot,
            'hovered_sub':   self._hov_sub,
            'sub_visible':   self._sub_vis,
            'sub_alpha':     self._sub_alpha,
            'alpha':         min(1.0, elapsed / 0.08),
            'slot_outline_width':   self._slot_outline_w,
            'subslot_outline_width': self._sub_outline_w,
            # Read colours LIVE from the active palette every frame (like
            # gear_colour below) so create/duplicate/delete/cycle reflect
            # immediately — the cached self._slot_outline_c/_sub_outline_c only updated
            # on open/Tab, leaving new/deleted palettes showing stale colours
            # until the wheel was reopened.
            'slot_outline_colour':  tuple(pit.slot_outline_colour),
            'subslot_outline_colour': tuple(pit.subslot_outline_colour),
            'sub_size_factor':  self._sub_size_factor,
            'sub_separation':   self._sub_separation,
            'glow_size':        self._glow_size,
            'glow_intensity':   self._glow_intensity,
            'glow_falloff':     self._glow_falloff,
            'fixed_slot_outline': self._fixed_slot_outline,
            'palette_index':  pal_index,
            'palette_total':  pal_total,
            'palette_name':   pit.name,
            'open_key_label':  key_label(self._open_key),
            'cycle_key_label': key_chord_label(*self._cycle_binding),
            'gear_hovered':   self._gear_hov,
            # The gear (glyph + ring) inherits the SUB-slot colour, not the slot
            # colour (user request).
            'gear_colour':    tuple(pit.subslot_outline_colour),
        })
        # Live Radius/Strength readout while right-dragging (reuses the Dynamic
        # Sliders overlay, which reads its own module-level state).
        if self._rmb_dragged:
            from .dynamic_sliders import _draw_overlay_cb
            _draw_overlay_cb()

    # ── right-drag brush adjust (Dynamic Sliders inside the wheel) ───────────────

    def _rmb_begin(self, context):
        from .dynamic_sliders import read_brush_size, read_brush_strength
        self._rmb_down    = True
        self._rmb_dragged = False
        self._rmb_mode    = None
        self._rmb_start   = (self._mx, self._my)
        self._rmb_start_size     = read_brush_size(context)
        self._rmb_start_strength = read_brush_strength(context)

    def _rmb_update(self, context):
        from .dynamic_sliders import (_axis_lock, write_brush_size,
                                      write_brush_strength, _overlay,
                                      RADIUS_SENS, STRENGTH_SENS)
        dx = self._mx - self._rmb_start[0]
        dy = self._my - self._rmb_start[1]
        if self._rmb_mode is None:
            self._rmb_mode = _axis_lock(dx, dy)
            if self._rmb_mode is not None:
                self._rmb_dragged = True
                _overlay['active'] = True
                _overlay['mode']   = self._rmb_mode
        if self._rmb_mode == 'RADIUS':
            _overlay['radius'] = write_brush_size(
                context, self._rmb_start_size + dx * RADIUS_SENS)
        elif self._rmb_mode == 'STRENGTH':
            _overlay['strength'] = write_brush_strength(
                context, self._rmb_start_strength + dy * STRENGTH_SENS)
        _overlay['x'] = self._mx
        _overlay['y'] = self._my

    def _rmb_end_overlay(self):
        from .dynamic_sliders import _overlay
        _overlay['active'] = False

    def _rmb_tap_action(self, context):
        """Original right-click TAP behaviour: open the slot context menu when
        over a slot/sub-slot, otherwise close the palette."""
        sub  = self._hit_sub(self._mx, self._my)
        slot = self._hit_slot(self._mx, self._my) if sub is None else None
        if sub is not None or slot is not None:
            _slot_context_target['slot'] = sub[0] if sub else slot
            _slot_context_target['sub']  = sub[1] if sub else -1
            bpy.ops.wm.call_menu('INVOKE_DEFAULT',
                                 name='SCULPTOOLS_MT_slot_context')
            return {'RUNNING_MODAL'}
        self._finish(context)
        return {'CANCELLED'}

    # ── hit testing ───────────────────────────────────────────────────────────

    def _hit_slot(self, mx, my):
        for i in range(self._num_slots):
            sx, sy = _slot_pos(self._cx, self._cy, self._R, i, self._num_slots)
            if _dist(mx, my, sx, sy) <= self._sr:
                return i
        return None

    def _hit_gear(self, mx, my):
        gx, gy = self._cx, self._cy - GEAR_CENTER_DY
        return _dist(mx, my, gx, gy) <= (GEAR_RADIUS + 6)

    def _hit_sub(self, mx, my):
        sub_sr = self._sr * self._sub_size_factor
        for i in self._sub_vis:
            positions = _sub_positions(
                self._cx, self._cy, self._R, self._sr, i,
                sub_sr, self._sub_separation, self._num_slots)
            for j, (sx, sy) in enumerate(positions):
                # skip empty sub-slots — they're not drawn and not selectable
                if not (i < len(self._sub_slots) and
                        j < len(self._sub_slots[i]) and
                        self._sub_slots[i][j]):
                    continue
                if _dist(mx, my, sx, sy) <= sub_sr:
                    return (i, j)
        return None

    # ── hover / fade logic ────────────────────────────────────────────────────

    def _update_hover(self, mx, my):
        now      = time.time()
        new_slot = self._hit_slot(mx, my)
        new_sub  = self._hit_sub(mx, my) if new_slot is None else None

        # detect slot enter / leave
        if new_slot != self._hov_slot:
            if self._hov_slot is not None:
                # record leave time only if sub-slots were actually visible
                if self._hov_slot in self._sub_vis or \
                   self._hov_slot in self._hover_since:
                    self._leave_time[self._hov_slot] = now
            if new_slot is not None and new_slot not in self._hover_since:
                self._hover_since[new_slot] = now
            self._hov_slot = new_slot

        self._hov_sub = new_sub

        new_vis = set()

        for i in list(self._hover_since.keys()):
            is_hov     = (i == self._hov_slot)
            sub_hov    = (new_sub is not None and new_sub[0] == i)

            if is_hov or sub_hov:
                # cancel any pending fade-out
                self._leave_time.pop(i, None)
                hover_elapsed = now - self._hover_since[i]
                if hover_elapsed >= self._hover_del:
                    t = (hover_elapsed - self._hover_del) / FADE_IN
                    self._sub_alpha[i] = min(1.0, t)
                    new_vis.add(i)
            else:
                leave_t = self._leave_time.get(i)
                if leave_t is None:
                    # just left — start fade-out now
                    if i in self._sub_vis:
                        self._leave_time[i] = now
                        leave_t = now

                if leave_t is not None:
                    t = (now - leave_t) / max(self._fade_out, 0.01)
                    if t < 1.0:
                        self._sub_alpha[i] = max(0.0, 1.0 - t)
                        new_vis.add(i)
                    else:
                        # fully gone — clean up
                        self._sub_alpha.pop(i, None)
                        self._hover_since.pop(i, None)
                        self._leave_time.pop(i, None)

        self._gear_hov = self._hit_gear(mx, my)
        self._sub_vis = new_vis

    # ── quick flick selection (Blender/Maya-style pie shortcut) ─────────────

    def _check_quick_flick(self, context, mx, my):
        """If the cursor has moved decisively toward a main slot within the
        opening window, activate that slot's brush immediately and close —
        mirroring the Blender/Maya pie-menu 'flick' shortcut. Only main slots
        are eligible; sub-slots are intentionally never quick-selected."""
        elapsed = time.time() - self._start_time
        if elapsed > QUICK_FLICK_WINDOW:
            self._quick_resolved = True
            return False

        dx = mx - self._cx
        dy = my - self._cy
        dist = math.hypot(dx, dy)
        if dist < self._R * QUICK_FLICK_DIST_FACTOR:
            return False

        angle = math.atan2(dy, dx)
        slot  = _nearest_slot(angle, self._num_slots)
        self._quick_resolved = True

        name = self._slot_name(slot)
        if name:
            _activate_slot(name)
        self._finish(context)
        return True

    # ── modal ─────────────────────────────────────────────────────────────────

    def modal(self, context, event):
        # Close automatically if the user leaves Sculpt Mode
        if context.mode != 'SCULPT':
            self._finish(context)
            return {'CANCELLED'}

        # Assigning a brush/tool from the slot context menu requests an auto-close:
        # the assign operator ran while the menu was up; now that the modal has
        # resumed (menu dismissed on the click), finish the wheel. Checked before
        # any per-event branch so it fires on the very next event (TIMER/MOUSEMOVE).
        if _close_after_assign['pending']:
            _close_after_assign['pending'] = False
            self._finish(context)
            return {'FINISHED'}

        context.area.tag_redraw()

        # ── middle mouse button: close the palette AND start viewport nav ─────
        # We must FINISH the modal here (not PASS_THROUGH): PASS_THROUGH keeps
        # this operator running, so it would linger as a zombie with its draw
        # torn down and swallow the NEXT hotkey press (the '\' re-open was being
        # eaten). Finishing consumes the MMB press, so we can't rely on Blender's
        # keymap to start navigation — we launch the matching nav operator
        # ourselves. One MMB+drag then both closes the wheel and orbits/pans/
        # zooms. Modifiers follow Blender's defaults: Shift = pan, Ctrl = zoom,
        # otherwise orbit.
        if event.type == 'MIDDLEMOUSE' and event.value == 'PRESS':
            self._finish(context)
            try:
                if event.shift:
                    bpy.ops.view3d.move('INVOKE_DEFAULT')
                elif event.ctrl:
                    bpy.ops.view3d.zoom('INVOKE_DEFAULT')
                else:
                    bpy.ops.view3d.rotate('INVOKE_DEFAULT')
            except Exception:
                pass
            return {'FINISHED'}

        # ── brush size: forward scroll wheel / F key to brush size system ────
        # Pass through scroll events so native brush size (F drag) still works
        if event.type == 'WHEELUPMOUSE' and event.ctrl:
            bpy.ops.brush.scale_size(scalar=1.10)
            return {'RUNNING_MODAL'}
        if event.type == 'WHEELDOWNMOUSE' and event.ctrl:
            bpy.ops.brush.scale_size(scalar=0.90)
            return {'RUNNING_MODAL'}

        # ── F key: let Blender handle brush size drag natively ────────────────
        if event.type == 'F' and event.value == 'PRESS':
            # Temporarily finish, let F run, then re-open would be complex.
            # Instead we just pass it through — Blender intercepts F globally.
            return {'PASS_THROUGH'}

        # ── the open hotkey (default '\') closes the palette ─────────────────
        # Uses the key that actually opened the wheel, captured in invoke(),
        # so it tracks whatever binding the user set for the operator.
        if event.type == self._open_key and event.value == 'PRESS':
            self._finish(context)
            return {'CANCELLED'}

        # ── palette cycle (configurable chord; Open wins the conflict) ─────────
        cb = self._cycle_binding
        if (event.value == 'PRESS' and event.type == cb[0]
                and event.ctrl == cb[1] and event.alt == cb[2]
                and event.shift == cb[3] and event.oskey == cb[4]
                and not keys_conflict(cb, self._open_binding)):
            prefs = ensure_palettes(context)
            n = len(prefs.palettes)
            prefs.active_palette_index = wrap_index(prefs.active_palette_index, n, +1)
            request_prefs_save()
            self._reload_active_palette(context)
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        # ── BACKWARD palette cycle (Shift + cycle key) ───────────────────────
        # Available only if the base chord does NOT already use Shift (cb[3] False):
        # we add Shift to the same chord. The two branches (forward/backward) are
        # mutually exclusive on the Shift bit. Open wins the conflict.
        if (not cb[3] and event.value == 'PRESS' and event.type == cb[0]
                and event.ctrl == cb[1] and event.alt == cb[2]
                and event.shift and event.oskey == cb[4]
                and not keys_conflict((cb[0], cb[1], cb[2], True, cb[4]),
                                      self._open_binding)):
            prefs = ensure_palettes(context)
            n = len(prefs.palettes)
            prefs.active_palette_index = wrap_index(
                prefs.active_palette_index, n, -1)
            request_prefs_save()
            self._reload_active_palette(context)
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        # ── jump-to-palette (modifier + number) with the wheel OPEN ───────────
        # The global keymap item does not fire while the modal has the grab: here
        # we recognize the configured modifier (prefs.jump_modifier) + number 1..N
        # and jump DIRECTLY to that palette, updating the wheel. Out of range
        # (number > existing palettes) = consumed no-op (does not close).
        if event.value == 'PRESS' and event.type in _JUMP_KEY_INDEX:
            j_ctrl, j_alt, j_shift = jump_modifier_flags(
                getattr(get_prefs(context), 'jump_modifier', 'CTRL'))
            if (event.ctrl == j_ctrl and event.alt == j_alt
                    and event.shift == j_shift and not event.oskey):
                target = _JUMP_KEY_INDEX[event.type]
                prefs = ensure_palettes(context)
                if 0 <= target < len(prefs.palettes):
                    if target != prefs.active_palette_index:
                        prefs.active_palette_index = target
                        request_prefs_save()
                        self._reload_active_palette(context)
                    context.area.tag_redraw()
                return {'RUNNING_MODAL'}

        # ── N closes the palette and toggles the native sidebar ──────────────
        # Same reasoning as MIDDLEMOUSE above: PASS_THROUGH would leave this modal
        # running as a zombie that eats the next '\' press, so we FINISH instead
        # and toggle the sidebar ourselves (finishing consumes the N press, so we
        # can't rely on Blender's own N keymap firing afterwards).
        if event.type == 'N' and event.value == 'PRESS':
            self._finish(context)
            try:
                bpy.ops.wm.context_toggle(
                    'INVOKE_DEFAULT', data_path='space_data.show_region_ui')
            except Exception:
                pass
            return {'FINISHED'}

        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            self._mx = event.mouse_region_x
            self._my = event.mouse_region_y
            # Waiting for the click-release that fires a menu-opener slot: ignore
            # flick/hover so a small drag before release can't change the target.
            if self._pending_popup is not None or self._pending_palette_menu:
                return {'RUNNING_MODAL'}
            # While the right button is held, drag = brush Radius/Strength adjust
            # (no flick, no hover selection).
            if self._rmb_down:
                self._rmb_update(context)
                return {'RUNNING_MODAL'}
            if not self._quick_resolved:
                if self._check_quick_flick(context, self._mx, self._my):
                    return {'FINISHED'}
            self._update_hover(self._mx, self._my)
            return {'RUNNING_MODAL'}

        if event.type == 'TIMER':
            # Keep cached slot data in sync with prefs (may have changed via
            # the context menu while the modal is still running). num_slots is
            # per-palette and the EFFECTIVE layout depends on n → recompute
            # everything (R/sub_separation AND the slot caches) so the hit-test
            # below always matches the drawn wheel.
            self._refresh_layout(context)
            self._update_hover(self._mx, self._my)
            return {'RUNNING_MODAL'}

        # Release fires a menu-opener that was armed on the matching PRESS, so
        # the popup opens with the button already up (a plain click keeps it
        # open, instead of the press-drag-release semantics that dismiss it).
        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            if self._pending_palette_menu:
                self._pending_palette_menu = False
                # The wheel stays OPEN behind the gear menu (user request): the
                # modal keeps running (RUNNING_MODAL) and its central block
                # (name/counter/colours) updates live after
                # rename/new/duplicate/delete. The menu is deferred by one tick
                # (_open_palette_menu) so it is born with the button already
                # released. NB: with the modal's grab still active, the items'
                # popups must use invoke_props_dialog (holds up over the modal), NOT
                # invoke_confirm (transient popup, would be discarded) — see
                # SCULPTOOLS_OT_delete_palette.
                self._open_palette_menu()
                return {'RUNNING_MODAL'}
            if self._pending_popup is not None:
                name = self._pending_popup
                self._pending_popup = None
                _activate_slot(name)      # schedules the popup (see _defer_popup)
                self._finish(context)
                return {'FINISHED'}
            return {'RUNNING_MODAL'}

        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            if self._hit_gear(self._mx, self._my):
                self._pending_palette_menu = True   # open on RELEASE (button up)
                return {'RUNNING_MODAL'}

            from .tools import is_popup

            sub  = self._hit_sub(self._mx, self._my)
            if sub:
                name = self._sub_slots[sub[0]][sub[1]]
                if name and is_popup(name):
                    self._pending_popup = name   # fire on RELEASE
                    return {'RUNNING_MODAL'}
                if name:
                    _activate_slot(name)
                self._finish(context)
                return {'FINISHED'}

            slot = self._hit_slot(self._mx, self._my)
            if slot is not None:
                name = self._slot_name(slot)
                if name and is_popup(name):
                    self._pending_popup = name   # fire on RELEASE
                    return {'RUNNING_MODAL'}
                if name:
                    _activate_slot(name)
                self._finish(context)
                return {'FINISHED'}

            # click outside → close
            self._finish(context)
            return {'CANCELLED'}

        if event.type == 'ESC':
            self._finish(context)
            return {'CANCELLED'}

        if event.type == 'RIGHTMOUSE':
            sliders_on = getattr(get_prefs(context),
                                 'dynamic_sliders_enabled', True)
            if event.value == 'PRESS':
                if sliders_on:
                    # Defer the decision: a TAP opens the menu / closes the
                    # wheel; a DRAG adjusts the brush. Resolved on RELEASE.
                    self._rmb_begin(context)
                    return {'RUNNING_MODAL'}
                return self._rmb_tap_action(context)
            if event.value == 'RELEASE' and self._rmb_down:
                self._rmb_down = False
                if self._rmb_dragged:
                    # Was a right-drag brush adjust → end it, keep wheel open.
                    self._rmb_dragged = False
                    self._rmb_mode    = None
                    self._rmb_end_overlay()
                    context.area.tag_redraw()
                    return {'RUNNING_MODAL'}
                return self._rmb_tap_action(context)
            return {'RUNNING_MODAL'}

        # Let scroll wheel pass through for brush size even without Ctrl
        if event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
            return {'PASS_THROUGH'}

        # Anything not handled above (stray keystrokes, window (de)activate, …)
        # PASSES THROUGH rather than being swallowed. A popup opened over the
        # wheel (the Rename dialog) delivers its keystrokes to this modal too;
        # consuming them with RUNNING_MODAL made Blender drop REPEATED identical
        # keys to the text field — typing "Tools" produced "Tols", and holding
        # Backspace skipped deletions. Passing through hands each key cleanly to
        # the dialog. The wheel's own keys (\, Tab-cycle, N, F, ESC, jump+mod)
        # are all consumed by the branches above, so this only releases keys the
        # wheel never used; all mouse/timer events are handled above too, so the
        # wheel keeps full control of its own interaction.
        return {'PASS_THROUGH'}

    def _finish(self, context):
        # Guard against being called twice (e.g. a quick-flick that finishes
        # in the same event that another branch would also finish) — removing
        # an already-removed timer or draw handler raises.
        if getattr(self, "_finished", False):
            return
        self._finished = True
        _wheel_active['on'] = False   # no open wheel for the assign ops to close
        # Clear the right-drag readout overlay in case the wheel closed mid-drag.
        try:
            self._rmb_end_overlay()
        except Exception:
            pass
        try:
            context.window_manager.event_timer_remove(self._timer)
        except Exception:
            pass
        try:
            bpy.types.SpaceView3D.draw_handler_remove(self._draw_handle, 'WINDOW')
        except Exception:
            pass
        if context.area:
            context.area.tag_redraw()
