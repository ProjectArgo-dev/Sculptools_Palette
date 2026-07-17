# sculptools_palette/panel.py
#
# Sidebar (N-panel) tab, "Palette", visible only in Sculpt Mode. Hosts the
# pie-palette Appearance sliders (moved out of Add-on Preferences) plus a
# "Preview" toggle that draws a static, non-interactive render of the wheel
# in the viewport so the user can see the effect of a slider while dragging
# it, without having to actually open the palette (Q).

import bpy
from bpy.types import Panel, Operator

from .prefs import (get_prefs, get_slot, get_sub, get_num_slots, NUM_SUBSLOTS,
                    get_active_palette, ensure_palettes, can_delete)
from .gpu_draw import (draw_palette, clear_texture_cache, diagnose_brush_preview,
                       request_preview_by_name, _effective_layout)

_preview_handle = None


def _draw_preview_cb():
    """POST_PIXEL draw callback for the static settings preview. Reads
    current prefs fresh every frame so slider drags are reflected live."""
    context = bpy.context
    if context.mode != 'SCULPT':
        return
    try:
        prefs = get_prefs(context)
    except Exception:
        return
    if not prefs.show_preview:
        return
    region = context.region
    if not region:
        return

    n = get_num_slots(context)
    # EFFECTIVE anti-overlap geometry: same values as the modal, so the preview
    # shows exactly what the wheel will draw.
    R_eff, sep_eff = _effective_layout(
        prefs.palette_radius, prefs.slot_radius,
        prefs.sub_size_factor, prefs.sub_separation, n)
    slots     = [get_slot(context, i) for i in range(n)]
    sub_slots = [[get_sub(context, i, j) for j in range(NUM_SUBSLOTS)]
                 for i in range(n)]

    cx, cy = region.width / 2, region.height / 2

    prefs_e = ensure_palettes(context)
    pit = prefs_e.palettes[prefs_e.active_palette_index]

    draw_palette({
        'cx':             cx,
        'cy':             cy,
        'radius':         R_eff,
        'slot_r':         prefs.slot_radius,
        'slots':          slots,
        'sub_slots':      sub_slots,
        'num_slots':      n,
        'hovered_slot':   None,
        'hovered_sub':    None,
        # Show every slot's sub-slots at once (no hover in a static preview)
        # so the user can check spacing/size across the whole wheel.
        'sub_visible':    set(range(n)),
        'sub_alpha':      {i: 1.0 for i in range(n)},
        'alpha':          1.0,
        'slot_outline_width':   prefs.slot_outline_width,
        'subslot_outline_width': prefs.subslot_outline_width,
        'slot_outline_colour':  tuple(get_active_palette(context).slot_outline_colour),
        'subslot_outline_colour': tuple(get_active_palette(context).subslot_outline_colour),
        'sub_size_factor':  prefs.sub_size_factor,
        'sub_separation':   sep_eff,
        'glow_size':        prefs.glow_size,
        'glow_intensity':   prefs.glow_intensity,
        'glow_falloff':     prefs.glow_falloff,
        'fixed_slot_outline': prefs.fixed_slot_outline,
        # Settings preview: show the glow on every slot/sub-slot so the user can
        # judge the gradient params across the whole wheel, not just on hover.
        'glow_all':         True,
        'is_preview':     True,
        'palette_index':  prefs_e.active_palette_index + 1,
        'palette_total':  len(prefs_e.palettes),
        'palette_name':   pit.name,
    })


def enable_preview_handler():
    """Register the draw handler once at addon register-time. The handler
    itself checks prefs.show_preview every frame and no-ops when off, so we
    don't need to add/remove it dynamically when the user toggles Preview."""
    global _preview_handle
    if _preview_handle is None:
        _preview_handle = bpy.types.SpaceView3D.draw_handler_add(
            _draw_preview_cb, (), 'WINDOW', 'POST_PIXEL')


def disable_preview_handler():
    global _preview_handle
    if _preview_handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_preview_handle, 'WINDOW')
        _preview_handle = None


def _tag_redraw_view3d(context):
    wm = context.window_manager
    for window in wm.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


# UNIVERSAL parameters (shared by all palettes) reset by "Reset All Palettes".
# num_slots and the colours are NOT here: they are per-palette.
_APPEARANCE_PROPS = [
    "palette_radius", "slot_radius",
    "slot_outline_width",
    "glow_size", "glow_intensity", "glow_falloff",
    "sub_size_factor", "sub_separation",
    "subslot_outline_width",
    "fixed_slot_outline",
]

# PER-PALETTE parameters (custom for each palette): slot count + the 2 colours.
# They live on the active PaletteItem. "Reset This Palette" restores num_slots to
# the default and the colours like this: the FIRST palette (index 0, the default
# "-Palette Name-") reverts to the default-palette colours (#97E7FF / #63EBEB);
# the others to the "new" colours (#FFFFFF / #BCBCBC, the PaletteItem default).


class SCULPTOOLS_OT_reset_palette_appearance(Operator):
    bl_idname   = "sculptools.reset_palette_appearance"
    bl_label    = "Reset This Palette"
    bl_description = ("Reset THIS palette completely: clear every slot/sub-slot "
                      "and restore its number of slots and the two outline colours "
                      "to defaults. Does not touch universal settings or other "
                      "palettes")
    bl_options  = {'INTERNAL'}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        from .prefs import (set_slot, set_sub, MAX_SLOTS, NUM_SUBSLOTS,
                            get_active_palette, DEFAULT_SLOT_COLOUR,
                            DEFAULT_SUB_COLOUR)
        pit = get_active_palette(context)
        pit.property_unset("num_slots")
        # Colours: the FIRST palette (index 0) reverts to the default-palette
        # colours; the others to the PaletteItem default ("new" colours).
        if get_prefs(context).active_palette_index == 0:
            pit.slot_outline_colour    = DEFAULT_SLOT_COLOUR
            pit.subslot_outline_colour = DEFAULT_SUB_COLOUR
        else:
            pit.property_unset("slot_outline_colour")
            pit.property_unset("subslot_outline_colour")
        for i in range(MAX_SLOTS):
            set_slot(context, i, "")
            for j in range(NUM_SUBSLOTS):
                set_sub(context, i, j, "")
        _tag_redraw_view3d(context)
        self.report({'INFO'}, "Sculptools: this palette reset")
        return {'FINISHED'}


class SCULPTOOLS_OT_reset_all_palettes(Operator):
    bl_idname   = "sculptools.reset_all_palettes"
    bl_label    = "Reset All Palettes"
    bl_description = ("Factory reset: reset the universal Appearance settings AND "
                      "delete every palette, leaving a single empty default "
                      "palette. This clears all brush/tool assignments")
    bl_options  = {'INTERNAL'}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        from .prefs import factory_reset_palettes
        prefs = get_prefs(context)
        for name in _APPEARANCE_PROPS:
            try:
                prefs.property_unset(name)
            except Exception:
                pass
        factory_reset_palettes(context)
        _tag_redraw_view3d(context)
        self.report({'INFO'}, "Sculptools: all palettes reset to defaults")
        return {'FINISHED'}


class SCULPTOOLS_OT_cycle_palette_holder(Operator):
    """Hosts the palette-cycle keymap item (chord editable with the native widget,
    like Open) and — since v2.7.1 — ACTUALLY cycles the palettes when the Preview
    Editor is open. With the preview closed it does PASS_THROUGH: the chord
    (default Tab) keeps Blender's native behaviour. With the wheel open it never
    fires (the modal has the grab and handles cycling itself); if the chord matches
    Open, Open wins because its kmi is registered first in the same keymap."""
    bl_idname   = "sculptools.cycle_palette_holder"
    bl_label    = "Cycle Palette (Preview)"
    bl_options  = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'SCULPT'

    def invoke(self, context, event):
        from .prefs import wrap_index, ensure_palettes, request_prefs_save
        prefs = get_prefs(context)
        if not prefs.show_preview:
            return {'PASS_THROUGH'}
        prefs_e = ensure_palettes(context)
        prefs_e.active_palette_index = wrap_index(
            prefs_e.active_palette_index, len(prefs_e.palettes), +1)
        request_prefs_save()
        _tag_redraw_view3d(context)
        return {'FINISHED'}

    def execute(self, context):
        # Only reachable from scripts (the keymap goes through invoke): no-op.
        return {'CANCELLED'}


class SCULPTOOLS_OT_cycle_palette_back_holder(Operator):
    """BACKWARD twin of SCULPTOOLS_OT_cycle_palette_holder: hosts the
    Shift+<cycle key> keymap item (kept in sync by prefs.sync_cycle_back_binding,
    NOT edited by the user) and cycles the palettes by -1 when the Preview Editor
    is open. With the preview closed it does PASS_THROUGH (preserves the native
    Shift+<key>). A distinct idname from the forward holder so the N-panel's keymap
    widget stays unambiguously pointed at the forward holder."""
    bl_idname   = "sculptools.cycle_palette_back_holder"
    bl_label    = "Cycle Palette Backwards (Preview)"
    bl_options  = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'SCULPT'

    def invoke(self, context, event):
        from .prefs import (wrap_index, ensure_palettes, request_prefs_save,
                            get_cycle_key_binding)
        prefs = get_prefs(context)
        if not prefs.show_preview:
            return {'PASS_THROUGH'}
        # If the FORWARD cycle already uses Shift, then Shift+<key> IS the forward
        # cycle key (backward not available): hand off to the forward holder
        # instead of cycling backward. Decided HERE at runtime, NOT via the kmi's
        # `active` flag — so it is correct even before the sync (register / wheel
        # invoke / toggle preview) has updated `active`, and it is independent of
        # the order of the two holders in the keymap.
        if get_cycle_key_binding(context)[3]:
            return {'PASS_THROUGH'}
        prefs_e = ensure_palettes(context)
        prefs_e.active_palette_index = wrap_index(
            prefs_e.active_palette_index, len(prefs_e.palettes), -1)
        request_prefs_save()
        _tag_redraw_view3d(context)
        return {'FINISHED'}

    def execute(self, context):
        # Only reachable from scripts (the keymap goes through invoke): no-op.
        return {'CANCELLED'}


class SCULPTOOLS_OT_toggle_preview(Operator):
    bl_idname   = "sculptools.toggle_preview"
    bl_label    = "Toggle Palette Preview"
    bl_description = "Temporarily show the pie palette in the viewport"
    bl_options  = {'INTERNAL'}

    def execute(self, context):
        from .prefs import sync_cycle_back_binding
        prefs = get_prefs(context)
        prefs.show_preview = not prefs.show_preview
        # Realign the back holder (Shift+<cycle key>) outside the draw path, so
        # backward cycling in the preview reflects any rebind of the cycle hotkey.
        # (Syncing in the draw would cancel the native capture widget — see
        # sync_cycle_back_binding.)
        if prefs.show_preview:
            sync_cycle_back_binding(context)
        _tag_redraw_view3d(context)
        return {'FINISHED'}


class SCULPTOOLS_OT_refresh_thumbnails(Operator):
    bl_idname   = "sculptools.refresh_thumbnails"
    bl_label    = "Refresh Thumbnails"
    bl_description = ("Clear the thumbnail cache and re-request previews for "
                      "every brush currently assigned to a slot. Also prints "
                      "a diagnostic report to the System Console (Window > "
                      "Toggle System Console) — useful if thumbnails still "
                      "don't appear after this")
    bl_options  = {'INTERNAL'}

    def execute(self, context):
        from .tools import is_tool_spec
        clear_texture_cache()
        n = get_num_slots(context)
        names = sorted({
            name
            for i in range(n)
            for name in (
                [get_slot(context, i)]
                + [get_sub(context, i, j) for j in range(NUM_SUBSLOTS)]
            )
            if name and not is_tool_spec(name)
        })

        # Actually kick off generation here — this used to only report
        # status, relying on the pie wheel having been opened at least once
        # (which is the only other place preview generation gets triggered
        # from). That meant Refresh did nothing for brushes assigned while
        # the wheel was never opened in the current session.
        for name in names:
            request_preview_by_name(name)

        def _print_report(label):
            print(f"── Sculptools: thumbnail diagnostic ({label}) ──────────────")
            if not names:
                print("  (no brushes assigned to any slot)")
            for name in names:
                print("  " + diagnose_brush_preview(name))
            print("──────────────────────────────────────────────────────────────")

        # Immediate report — right after (re)queuing, so it will usually
        # show "cooldown active" or "job running"; that's expected, not a
        # bug. A second, delayed report follows once generation has had
        # time to actually finish, giving a conclusive answer from a single
        # button click instead of requiring the user to click twice and
        # mentally account for timing.
        _print_report("immediate")

        def _delayed_report():
            _print_report("0.8s later — should be conclusive")
            _tag_redraw_view3d(bpy.context)
            return None  # run once

        bpy.app.timers.register(_delayed_report, first_interval=0.8)

        _tag_redraw_view3d(context)
        self.report({'INFO'},
                   f"Sculptools: requested previews for {len(names)} brush(es) "
                   f"— see System Console for details")
        return {'FINISHED'}


class SCULPTOOLS_PT_palette(Panel):
    """Sidebar tab, Sculpt Mode only, hosting the pie-palette appearance
    settings. Restricted via poll() rather than bl_context, since bl_context
    string-matching for VIEW_3D 'UI' region sidebar tabs is unreliable for
    third-party categories — poll() is the standard, dependable approach."""
    bl_idname      = "SCULPTOOLS_PT_palette"
    bl_label       = "Palette Appearance"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = "Palette"

    @classmethod
    def poll(cls, context):
        return context.mode == 'SCULPT'

    def draw(self, context):
        layout = self.layout
        prefs  = get_prefs(context)

        # ── This palette (per-palette settings; also hosts the palette name) ─
        prefs_ensured = ensure_palettes(context)
        pit = prefs_ensured.palettes[prefs_ensured.active_palette_index]
        box_this = layout.box()
        box_this.label(text="This Palette", icon="RESTRICT_SELECT_OFF")
        colp = box_this.column(align=True)
        colp.prop(pit, "name",                text="Name")
        colp.separator()
        colp.prop(pit, "num_slots",           slider=True)
        colp.prop(pit, "slot_outline_colour",     text="Slot Outline Colour")
        colp.prop(pit, "subslot_outline_colour",  text="Sub-slot Outline Colour")
        colp.separator()
        colp.operator("sculptools.reset_palette_appearance",
                      text="Reset This Palette", icon="LOOP_BACK")
        rowd = colp.row()
        rowd.enabled = can_delete(len(prefs_ensured.palettes))
        rowd.operator("sculptools.delete_palette",
                      text="Delete This Palette", icon="TRASH")

        # ── Universal (shared by every palette) ──────────────────────────────
        box = layout.box()
        box.label(text="Universal  (all palettes)", icon="PREFERENCES")
        col = box.column(align=True)
        col.prop(prefs, "palette_radius",     slider=True)
        col.prop(prefs, "slot_radius",        slider=True)
        col.prop(prefs, "slot_outline_width",     slider=True)
        col.prop(prefs, "subslot_outline_width",  slider=True)
        col.separator()
        col.prop(prefs, "glow_intensity",     slider=True)
        col.prop(prefs, "fixed_slot_outline")
        # Gradient Size/Falloff, Sub-slot Size and Sub-slot Distance are NO longer
        # exposed in the panel (user request): they remain active properties with
        # their defaults (1.6 / 2.5 / 0.70 / 55.0) and are still read by
        # modal/preview and by _effective_layout. Do not remove the properties.

        col.separator()
        row = col.row(align=True)
        row.scale_y = 1.3
        icon = 'HIDE_OFF' if prefs.show_preview else 'HIDE_ON'
        row.operator("sculptools.toggle_preview",
                     text="Hide Preview Editor" if prefs.show_preview else "Show Preview Editor",
                     icon=icon, depress=prefs.show_preview)
        col.operator("sculptools.refresh_thumbnails",
                     text="Refresh Thumbnails", icon="FILE_REFRESH")
        col.separator()
        col.operator("sculptools.reset_all_palettes",
                     text="Reset All Palettes", icon="TRASH")
        col.separator()
        col.operator("sculptools.export_palettes", text="Export Palettes…",
                     icon="EXPORT")
        col.operator("sculptools.import_palettes", text="Import Palettes…",
                     icon="IMPORT")


class SCULPTOOLS_PT_palette_utils(Panel):
    """Second panel under the 'Palette' tab: hotkeys (open + cycle) and sculpt
    interaction. Kept separate from Appearance to avoid crowding it."""
    bl_idname      = "SCULPTOOLS_PT_palette_utils"
    bl_label       = "Palette Utilities"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = "Palette"
    bl_options     = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'SCULPT'

    @staticmethod
    def _draw_hotkey_box(layout, context, title, kmi_idname, conflict_msg, conflict):
        """A box with the native keymap widget (full_event) for the keymap item
        `kmi_idname`, plus the conflict message below it when needed. Used for both
        Open and Cycle (both keymap items)."""
        box = layout.box()
        box.label(text=title, icon="KEYINGSET")
        col = box.column()
        try:
            kc = context.window_manager.keyconfigs.addon
            kmi_drawn = False
            if kc:
                km = kc.keymaps.get("Sculpt")
                if km:
                    for kmi in km.keymap_items:
                        if kmi.idname == kmi_idname:
                            col.prop(kmi, "type", text="", full_event=True)
                            kmi_drawn = True
                            break
            if not kmi_drawn:
                col.label(text="Keymap not found", icon="ERROR")
        except Exception:
            col.label(text="Hotkey editor unavailable here", icon="ERROR")
        if conflict:
            col.label(text=conflict_msg, icon="ERROR")

    def draw(self, context):
        from .prefs import (get_open_key_binding, get_cycle_key_binding,
                            keys_conflict, sync_jump_bindings, key_chord_label)
        layout = self.layout
        prefs  = get_prefs(context)

        # Both hotkeys (Open + Cycle) are keymap items edited by the native keymap
        # widget. The conflict (same key) is reported SYMMETRICALLY with the message
        # below each box; neither prevents it inline (the native widget can't be
        # intercepted). At runtime Open has priority (see modal.py: it closes on the
        # open key before cycling + the keys_conflict guard).
        cycle_b  = get_cycle_key_binding(context)
        open_b   = get_open_key_binding(context)
        conflict = keys_conflict(cycle_b, open_b)

        self._draw_hotkey_box(layout, context, "Open Palette Hotkey",
                              "sculptools.radial_palette",
                              "Conflicts with Cycle Palette hotkey", conflict)
        self._draw_hotkey_box(layout, context, "Cycle Palette Hotkey",
                              "sculptools.cycle_palette_holder",
                              "Conflicts with Open Palette hotkey", conflict)

        # BACKWARD palette cycle: an info line clarifies the usage and the edge
        # case (backward unavailable if the key already uses Shift). NB: the sync of
        # the back-holder keymap item is NOT done here — mutating the keymap in the
        # draw cancels the hotkey's native capture widget (bug 2026-07-10). The sync
        # happens outside the draw (deferred register, wheel invoke, toggle preview).
        if cycle_b[3]:
            layout.label(
                text="Backwards cycling unavailable — the cycle key already uses Shift.",
                icon="INFO")
        else:
            back_label = key_chord_label(cycle_b[0], cycle_b[1], cycle_b[2],
                                         True, cycle_b[4])
            layout.label(text=f"{back_label} cycles palettes backwards.",
                         icon="INFO")

        # Jump-to-Palette: MODIFIER + number (1..8) jumps straight to that palette,
        # global in Sculpt Mode. The modifier is chosen from a dropdown (only
        # Ctrl/Alt/Shift): a closed menu, instead of the native keymap widget,
        # prevents assigning arbitrary keys that would clash with Quick Numbers. The
        # draw resyncs the modifier onto the 8 real keymap items.
        sync_jump_bindings(context)
        box_jump = layout.box()
        box_jump.label(text="Jump-to Palette Hotkey", icon="KEYINGSET")
        box_jump.prop(prefs, "jump_modifier", text="Modifier")
        layout.label(text="Modifier + number (1–8) jumps straight to that palette.",
                     icon="INFO")

        # ── Sculpt Interaction ───────────────────────────────────────────────
        box_ds = layout.box()
        box_ds.label(text="Sculpt Interaction", icon="BRUSH_DATA")
        box_ds.prop(prefs, "dynamic_sliders_enabled")
        box_ds.prop(prefs, "quick_numbers_enabled")

        layout.separator()
        layout.label(text="Press your hotkey (default \\) in Sculpt Mode to open the palette.",
                     icon="INFO")


all_panel_classes = [
    SCULPTOOLS_OT_reset_palette_appearance,
    SCULPTOOLS_OT_reset_all_palettes,
    SCULPTOOLS_OT_cycle_palette_holder,
    SCULPTOOLS_OT_cycle_palette_back_holder,
    SCULPTOOLS_OT_toggle_preview,
    SCULPTOOLS_OT_refresh_thumbnails,
    SCULPTOOLS_PT_palette,
    SCULPTOOLS_PT_palette_utils,
]
