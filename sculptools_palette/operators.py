# sculptools_palette/operators.py

import json
import os

import bpy
from bpy.types import Operator, Menu
from bpy.props import StringProperty, IntProperty, BoolProperty
from bpy_extras.io_utils import ExportHelper, ImportHelper

ASSET_FILE = "brushes/essentials_brushes-mesh_sculpt.blend"


# ── helpers ───────────────────────────────────────────────────────────────────

def _resolve_target(op_slot, op_sub):
    """Return (slot, sub) resolving -1 sentinels through _slot_context_target."""
    from .modal import _slot_context_target
    slot = op_slot if op_slot >= 0 else _slot_context_target.get('slot', -1)
    sub  = op_sub  if op_sub  >= -1 else _slot_context_target.get('sub',  -1)
    return slot, sub


# Exact (slot, sub) the "Assign Tool" submenu writes to. Set at draw time by
# _draw_slot_actions, because Blender submenus (layout.menu) cannot carry
# per-target operator args the way the flat action operators do.
_assign_target = {'slot': -1, 'sub': -1}


# ── Slot assignment popup ─────────────────────────────────────────────────────

class SCULPTOOLS_OT_assign_to_slot(Operator):
    bl_idname   = "sculptools.assign_to_slot"
    bl_label    = "Add brush to Palette"
    bl_description = "Assign this brush to a slot in the active palette"
    bl_options  = {'REGISTER'}

    brush_name: StringProperty() # type: ignore

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=260)

    def draw(self, context):
        from .prefs import (get_slot, get_sub, get_num_slots,
                            SUB_CYCLE_ORDER, sub_display_number,
                            get_active_palette)
        from .tools import is_tool_spec, best_tool_label
        def _disp(n):
            return best_tool_label(n) if is_tool_spec(n) else n
        layout = self.layout
        layout.label(text=f'Assign  "{self.brush_name}"  to:', icon="BRUSHES_ALL")
        # Show WHICH palette the slots/subs listed below belong to, so it is
        # clear where we are assigning the brush (these are the active palette's slots).
        layout.label(text=f'Palette:  {get_active_palette(context).name}',
                     icon="RESTRICT_SELECT_OFF")
        layout.separator()
        for i in range(get_num_slots(context)):
            main = get_slot(context, i)
            box  = layout.box()
            row = box.row()
            lbl = f"Slot {i+1}  —  {_disp(main)}" if main else f"Slot {i+1}  —  empty"
            op  = row.operator("sculptools.confirm_assign", text=lbl,
                               icon="RADIOBUT_ON" if main else "RADIOBUT_OFF")
            op.slot_index = i
            op.sub_index  = -1
            op.brush_name = self.brush_name
            for j in SUB_CYCLE_ORDER:
                sub = get_sub(context, i, j)
                row2 = box.row()
                row2.separator()
                num  = sub_display_number(j)
                lbl2 = f"  Sub {num}  —  {_disp(sub)}" if sub else f"  Sub {num}  —  empty"
                op2  = row2.operator("sculptools.confirm_assign", text=lbl2,
                                     icon="DOT")
                op2.slot_index = i
                op2.sub_index  = j
                op2.brush_name = self.brush_name

    def execute(self, context):
        return {'FINISHED'}


class SCULPTOOLS_OT_confirm_assign(Operator):
    bl_idname = "sculptools.confirm_assign"
    bl_label  = "Confirm Assignment"
    bl_options = {'REGISTER'}

    slot_index: IntProperty(default=0)  # type: ignore
    sub_index:  IntProperty(default=-1) # type: ignore
    brush_name: StringProperty()        # type: ignore

    def execute(self, context):
        from .prefs import set_slot, set_sub, sub_display_number
        if self.sub_index < 0:
            set_slot(context, self.slot_index, self.brush_name)
            self.report({'INFO'}, f"Sculptools: '{self.brush_name}' → Slot {self.slot_index+1}")
        else:
            set_sub(context, self.slot_index, self.sub_index, self.brush_name)
            self.report({'INFO'}, f"Sculptools: '{self.brush_name}' → Slot {self.slot_index+1} / Sub {sub_display_number(self.sub_index)}")
        return {'FINISHED'}


class SCULPTOOLS_OT_clear_slot(Operator):
    bl_idname  = "sculptools.clear_slot"
    bl_label   = "Clear Slot"
    bl_options = {'REGISTER'}

    slot_index: IntProperty(default=0)  # type: ignore
    sub_index:  IntProperty(default=-1) # type: ignore

    def execute(self, context):
        from .prefs import set_slot, set_sub
        if self.sub_index < 0:
            set_slot(context, self.slot_index, "")
        else:
            set_sub(context, self.slot_index, self.sub_index, "")
        return {'FINISHED'}


# ── Shelf right-click hook ────────────────────────────────────────────────────

class SCULPTOOLS_OT_shelf_add(Operator):
    bl_idname   = "sculptools.shelf_add_to_palette"
    bl_label    = "Add brush to Palette"
    bl_description = "Assign this brush to a slot in the active palette"
    bl_options  = {'REGISTER'}

    def execute(self, context):
        brush = context.tool_settings.sculpt.brush if context.tool_settings.sculpt else None
        if not brush:
            self.report({'WARNING'}, "No active brush")
            return {'CANCELLED'}
        bpy.ops.sculptools.assign_to_slot('INVOKE_DEFAULT', brush_name=brush.name)
        return {'FINISHED'}


def brush_context_menu(self, context):
    if context.mode == 'SCULPT':
        self.layout.separator()
        self.layout.operator("sculptools.shelf_add_to_palette",
                             text="Add brush to Palette",
                             icon="BRUSHES_ALL")


# ── Palette slot right-click context menu ─────────────────────────────────────
#
# Design: right-clicking a MAIN slot shows a compact 4-row picker
# (Main / Sub 1 / Sub 2 / Sub 3), each opening a small flyout submenu with
# the actual actions (Add Active / Cut / Copy / Paste / Remove) for that
# exact target. This keeps the top-level menu short and makes every
# sub-slot reachable — including empty ones that aren't drawn in the wheel
# and can't be right-clicked directly (needed so Paste can target them).
#
# Right-clicking a SUB-slot directly skips the picker and jumps straight
# to its action list.

def _draw_slot_actions(layout, context, slot, sub):
    """Shared action list (Add Active / Cut / Copy / Paste / Remove) for one
    exact (slot, sub) target. Used both as the top-level menu body (direct
    sub-slot click) and inside each per-target flyout submenu."""
    from .modal import _slot_clipboard

    op = layout.operator("sculptools.slot_add_active",
                         text="Add Active Brush", icon="BRUSH_DATA")
    op.slot_index = slot
    op.sub_index  = sub

    _assign_target['slot'] = slot
    _assign_target['sub']  = sub
    layout.menu("SCULPTOOLS_MT_assign_tool", text="Assign Tool", icon="TOOL_SETTINGS")

    layout.separator()

    op_cut = layout.operator("sculptools.slot_cut",
                             text="Cut", icon="PASTEDOWN")
    op_cut.slot_index = slot
    op_cut.sub_index  = sub

    op_copy = layout.operator("sculptools.slot_copy",
                              text="Copy", icon="COPYDOWN")
    op_copy.slot_index = slot
    op_copy.sub_index  = sub

    paste_name = _slot_clipboard.get('brush', '')
    row_p = layout.row()
    row_p.enabled = bool(paste_name)
    op_paste = row_p.operator("sculptools.slot_paste",
                              text=f'Paste  “{paste_name}”' if paste_name
                                   else "Paste Brush",
                              icon="DUPLICATE")
    op_paste.slot_index = slot
    op_paste.sub_index  = sub

    layout.separator()

    op_rem = layout.operator("sculptools.slot_remove",
                             text="Remove Brush", icon="X")
    op_rem.slot_index = slot
    op_rem.sub_index  = sub


def _target_label(name):
    if not name:
        return "empty"
    from .tools import is_tool_spec, best_tool_label
    return best_tool_label(name) if is_tool_spec(name) else name


class SCULPTOOLS_MT_slot_actions_main(Menu):
    bl_idname = "SCULPTOOLS_MT_slot_actions_main"
    bl_label  = "Main Slot"

    def draw(self, context):
        from .modal import _slot_context_target
        slot = _slot_context_target.get('slot', -1)
        _draw_slot_actions(self.layout, context, slot, -1)


class SCULPTOOLS_MT_slot_actions_sub0(Menu):
    bl_idname = "SCULPTOOLS_MT_slot_actions_sub0"
    bl_label  = "Sub 2"   # stored index 0 -> 2nd sub in SUB_CYCLE_ORDER

    def draw(self, context):
        from .modal import _slot_context_target
        slot = _slot_context_target.get('slot', -1)
        _draw_slot_actions(self.layout, context, slot, 0)


class SCULPTOOLS_MT_slot_actions_sub1(Menu):
    bl_idname = "SCULPTOOLS_MT_slot_actions_sub1"
    bl_label  = "Sub 3"   # stored index 1 (collinear/outward) -> visited LAST

    def draw(self, context):
        from .modal import _slot_context_target
        slot = _slot_context_target.get('slot', -1)
        _draw_slot_actions(self.layout, context, slot, 1)


class SCULPTOOLS_MT_slot_actions_sub2(Menu):
    bl_idname = "SCULPTOOLS_MT_slot_actions_sub2"
    bl_label  = "Sub 1"   # stored index 2 -> 1st sub in SUB_CYCLE_ORDER

    def draw(self, context):
        from .modal import _slot_context_target
        slot = _slot_context_target.get('slot', -1)
        _draw_slot_actions(self.layout, context, slot, 2)


_SUB_ACTION_MENUS = [
    SCULPTOOLS_MT_slot_actions_sub0,
    SCULPTOOLS_MT_slot_actions_sub1,
    SCULPTOOLS_MT_slot_actions_sub2,
]


class SCULPTOOLS_MT_slot_context(Menu):
    """Top-level context menu shown on right-click over a palette slot."""
    bl_idname = "SCULPTOOLS_MT_slot_context"
    bl_label  = "Palette Slot"

    def draw(self, context):
        from .modal import _slot_context_target
        from .prefs import (get_slot, get_sub,
                            SUB_CYCLE_ORDER, sub_display_number)
        layout = self.layout
        slot = _slot_context_target.get('slot', -1)
        sub  = _slot_context_target.get('sub',  -1)
        if slot < 0:
            layout.label(text="No slot selected", icon="INFO")
            return

        if sub >= 0:
            # Right-clicked a sub-slot directly → show its actions right away
            layout.label(text=f"Slot {slot + 1}  /  Sub {sub_display_number(sub)}", icon="RADIOBUT_ON")
            layout.separator()
            _draw_slot_actions(layout, context, slot, sub)
            return

        # Right-clicked the main slot → compact target picker
        layout.label(text=f"Slot {slot + 1}", icon="RADIOBUT_ON")
        layout.separator()

        main = get_slot(context, slot)
        layout.menu(SCULPTOOLS_MT_slot_actions_main.bl_idname,
                   text=f"Main  —  {_target_label(main)}",
                   icon="RADIOBUT_ON" if main else "RADIOBUT_OFF")

        for j in SUB_CYCLE_ORDER:
            sub_name = get_sub(context, slot, j)
            layout.menu(_SUB_ACTION_MENUS[j].bl_idname,
                       text=f"Sub {sub_display_number(j)}  —  {_target_label(sub_name)}",
                       icon="DOT")


# ── Add Active Brush to slot/sub ─────────────────────────────────────────────

class SCULPTOOLS_OT_slot_add_active(Operator):
    bl_idname   = "sculptools.slot_add_active"
    bl_label    = "Add Active Brush to Slot"
    bl_description = "Assign the currently active brush to this palette slot"
    bl_options  = {'REGISTER', 'UNDO'}

    # -1 → resolve from _slot_context_target
    slot_index: IntProperty(default=-1)  # type: ignore
    # -2 → resolve from target; -1 = main slot; ≥0 = sub-slot index
    sub_index:  IntProperty(default=-2)  # type: ignore

    def execute(self, context):
        from .prefs import set_slot, set_sub, sub_display_number
        slot, sub = _resolve_target(self.slot_index, self.sub_index)
        if slot < 0:
            return {'CANCELLED'}
        sculpt = context.tool_settings.sculpt
        brush  = sculpt.brush if sculpt else None
        if not brush:
            self.report({'WARNING'}, "No active sculpt brush")
            return {'CANCELLED'}
        if sub >= 0:
            set_sub(context, slot, sub, brush.name)
            self.report({'INFO'}, f"Sculptools: '{brush.name}' → Slot {slot+1} / Sub {sub_display_number(sub)}")
        else:
            set_slot(context, slot, brush.name)
            self.report({'INFO'}, f"Sculptools: '{brush.name}' → Slot {slot+1}")
        return {'FINISHED'}


# ── Cut ──────────────────────────────────────────────────────────────────────

class SCULPTOOLS_OT_slot_cut(Operator):
    bl_idname   = "sculptools.slot_cut"
    bl_label    = "Cut from Slot"
    bl_description = "Copy this slot's content to the Sculptools clipboard and clear the slot"
    bl_options  = {'REGISTER', 'UNDO'}

    slot_index: IntProperty(default=-1) # type: ignore
    sub_index:  IntProperty(default=-2) # type: ignore

    def execute(self, context):
        from .modal import _slot_clipboard
        from .prefs import get_slot, get_sub, set_slot, set_sub
        slot, sub = _resolve_target(self.slot_index, self.sub_index)
        if slot < 0:
            return {'CANCELLED'}
        name = get_sub(context, slot, sub) if sub >= 0 else get_slot(context, slot)
        _slot_clipboard['brush'] = name or ''
        if sub >= 0:
            set_sub(context, slot, sub, '')
        else:
            set_slot(context, slot, '')
        if name:
            self.report({'INFO'}, f"Sculptools: cut '{name}'")
        return {'FINISHED'}


# ── Copy ─────────────────────────────────────────────────────────────────────

class SCULPTOOLS_OT_slot_copy(Operator):
    bl_idname   = "sculptools.slot_copy"
    bl_label    = "Copy from Slot"
    bl_description = "Copy this slot's content to the Sculptools clipboard"
    bl_options  = {'REGISTER'}

    slot_index: IntProperty(default=-1) # type: ignore
    sub_index:  IntProperty(default=-2) # type: ignore

    def execute(self, context):
        from .modal import _slot_clipboard
        from .prefs import get_slot, get_sub
        slot, sub = _resolve_target(self.slot_index, self.sub_index)
        if slot < 0:
            return {'CANCELLED'}
        name = get_sub(context, slot, sub) if sub >= 0 else get_slot(context, slot)
        _slot_clipboard['brush'] = name or ''
        self.report({'INFO'}, f"Sculptools: copied '{name}'" if name
                    else "Sculptools: slot empty — clipboard cleared")
        return {'FINISHED'}


# ── Paste ─────────────────────────────────────────────────────────────────────

class SCULPTOOLS_OT_slot_paste(Operator):
    bl_idname   = "sculptools.slot_paste"
    bl_label    = "Paste Brush to Slot"
    bl_description = "Paste the brush from the Sculptools clipboard into this slot"
    bl_options  = {'REGISTER', 'UNDO'}

    slot_index: IntProperty(default=-1) # type: ignore
    sub_index:  IntProperty(default=-2) # type: ignore

    def execute(self, context):
        from .modal import _slot_clipboard
        from .prefs import set_slot, set_sub, sub_display_number
        slot, sub = _resolve_target(self.slot_index, self.sub_index)
        brush = _slot_clipboard.get('brush', '')
        if slot < 0:
            return {'CANCELLED'}
        if not brush:
            self.report({'WARNING'}, "Sculptools clipboard is empty")
            return {'CANCELLED'}
        if sub >= 0:
            set_sub(context, slot, sub, brush)
            self.report({'INFO'}, f"Sculptools: pasted '{brush}' → Slot {slot+1} / Sub {sub_display_number(sub)}")
        else:
            set_slot(context, slot, brush)
            self.report({'INFO'}, f"Sculptools: pasted '{brush}' → Slot {slot+1}")
        return {'FINISHED'}


# ── Remove ────────────────────────────────────────────────────────────────────

class SCULPTOOLS_OT_slot_remove(Operator):
    bl_idname   = "sculptools.slot_remove"
    bl_label    = "Remove Brush from Slot"
    bl_description = "Clear the brush assignment from this palette slot"
    bl_options  = {'REGISTER', 'UNDO'}

    slot_index: IntProperty(default=-1) # type: ignore
    sub_index:  IntProperty(default=-2) # type: ignore

    def execute(self, context):
        from .prefs import set_slot, set_sub
        slot, sub = _resolve_target(self.slot_index, self.sub_index)
        if slot < 0:
            return {'CANCELLED'}
        if sub >= 0:
            set_sub(context, slot, sub, '')
        else:
            set_slot(context, slot, '')
        return {'FINISHED'}


class SCULPTOOLS_OT_assign_tool_to_slot(Operator):
    bl_idname   = "sculptools.assign_tool_to_slot"
    bl_label    = "Assign Tool to Slot"
    bl_description = "Assign this Sculpt tool/action to the palette slot"
    bl_options  = {'REGISTER', 'UNDO'}

    tool_key: StringProperty()  # type: ignore

    def execute(self, context):
        from .prefs import set_slot, set_sub, sub_display_number
        from .tools import TOOL_PREFIX, get_tool, is_oneshot
        slot = _assign_target.get('slot', -1)
        sub  = _assign_target.get('sub', -1)
        if slot < 0 or not self.tool_key:
            return {'CANCELLED'}
        spec  = f"{TOOL_PREFIX}{self.tool_key}"
        entry = get_tool(self.tool_key)
        label = entry.display if entry else self.tool_key
        if sub >= 0:
            set_sub(context, slot, sub, spec)
            self.report({'INFO'}, f"Sculptools: '{label}' → Slot {slot+1} / Sub {sub_display_number(sub)}")
        else:
            set_slot(context, slot, spec)
            self.report({'INFO'}, f"Sculptools: '{label}' → Slot {slot+1}")
        # Activate the tool right away on assign — but NOT one-shot ops, which
        # would fire their (possibly destructive) action just from being assigned.
        if not is_oneshot(spec):
            from .modal import _activate_slot
            _activate_slot(spec)
        return {'FINISHED'}


class SCULPTOOLS_MT_assign_tool(Menu):
    bl_idname = "SCULPTOOLS_MT_assign_tool"
    bl_label  = "Assign Tool"

    def draw(self, context):
        import bpy
        from .tools import TOOLS, CATEGORY_ORDER, tool_available
        layout = self.layout
        ver = bpy.app.version
        for cat in CATEGORY_ORDER:
            entries = [e for e in TOOLS
                       if e.category == cat and tool_available(e, ver)]
            if not entries:
                continue  # es. "Add" su Blender < 5.2 → niente header
            layout.label(text=cat)
            for e in entries:
                op = layout.operator("sculptools.assign_tool_to_slot", text=e.display)
                op.tool_key = e.key
            layout.separator()


# ── Palette management (gear menu) ────────────────────────────────────────────

def _tag_view3d(context):
    wm = context.window_manager
    for window in wm.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


class SCULPTOOLS_OT_rename_palette(Operator):
    bl_idname   = "sculptools.rename_palette"
    bl_label    = "Rename Palette"
    bl_description = "Rename the current palette"
    # REGISTER+UNDO is MANDATORY here: without REGISTER, an invoke_props_dialog
    # invoked DIRECTLY from a menu item (gear) does not appear at all
    # (regression 2026-07; the bpy.ops path from new/duplicate holds up instead).
    # The "ghost rename" risk (redo/F9/Repeat Last re-execute execute() without
    # invoke() with the stored properties) is neutralized BY CONSTRUCTION:
    # new_name has SKIP_SAVE, so every re-execution starts from "" and execute
    # ignores empty names (no-op).
    bl_options  = {'REGISTER', 'UNDO'}

    # SKIP_SAVE: never reuse the last typed name; the pre-fill comes ONLY from
    # invoke (the active palette's name).
    new_name: StringProperty(name="Name", default="", options={'SKIP_SAVE'}) # type: ignore

    def invoke(self, context, event):
        from .prefs import get_active_palette
        self.new_name = get_active_palette(context).name
        return context.window_manager.invoke_props_dialog(self, width=260)

    def draw(self, context):
        self.layout.prop(self, "new_name", text="")

    def execute(self, context):
        from .prefs import get_active_palette, request_prefs_save
        pit = get_active_palette(context)
        name = self.new_name.strip()
        if name:
            pit.name = name
        request_prefs_save()
        _tag_view3d(context)
        return {'FINISHED'}


class SCULPTOOLS_OT_new_palette(Operator):
    bl_idname   = "sculptools.new_palette"
    bl_label    = "New Palette"
    bl_description = "Create a new palette with empty slots"
    bl_options  = {'INTERNAL'}   # no re-execution from redo/F9 (see rename)

    def execute(self, context):
        from .prefs import (ensure_palettes, build_new_palette,
                            _apply_palette_dict, can_add, request_prefs_save)
        prefs = ensure_palettes(context)
        if not can_add(len(prefs.palettes)):
            self.report({'WARNING'}, "Sculptools: maximum number of palettes reached")
            return {'CANCELLED'}
        pit = prefs.palettes.add()
        _apply_palette_dict(pit, build_new_palette())
        prefs.active_palette_index = len(prefs.palettes) - 1
        request_prefs_save()
        _tag_view3d(context)
        # Pre-filled rename popup on the just-created palette (design 2026-07-06):
        # Esc leaves the default name, the creation is NEVER cancelled. If the
        # dialog failed to appear from the wheel's gear (the history of popups
        # dismissed on the wrong tick), the known fallback is to defer it with
        # bpy.app.timers like modal._defer_popup.
        try:
            bpy.ops.sculptools.rename_palette('INVOKE_DEFAULT')
        except Exception as exc:
            print(f"Sculptools: rename dialog failed to open: {exc}")
        return {'FINISHED'}


class SCULPTOOLS_OT_duplicate_palette(Operator):
    bl_idname   = "sculptools.duplicate_palette"
    bl_label    = "Duplicate Palette"
    bl_description = "Duplicate the current palette"
    bl_options  = {'INTERNAL'}   # no re-execution from redo/F9 (see rename)

    def execute(self, context):
        from .prefs import (ensure_palettes, build_duplicate_palette,
                            _read_palette_dict, _apply_palette_dict, can_add,
                            request_prefs_save)
        prefs = ensure_palettes(context)
        if not can_add(len(prefs.palettes)):
            self.report({'WARNING'}, "Sculptools: maximum number of palettes reached")
            return {'CANCELLED'}
        src = prefs.palettes[prefs.active_palette_index]
        d = build_duplicate_palette(_read_palette_dict(src))
        pit = prefs.palettes.add()
        _apply_palette_dict(pit, d)
        prefs.active_palette_index = len(prefs.palettes) - 1
        request_prefs_save()
        _tag_view3d(context)
        # Pre-filled rename popup on the duplicate (see new_palette).
        try:
            bpy.ops.sculptools.rename_palette('INVOKE_DEFAULT')
        except Exception as exc:
            print(f"Sculptools: rename dialog failed to open: {exc}")
        return {'FINISHED'}


class SCULPTOOLS_OT_delete_palette(Operator):
    bl_idname   = "sculptools.delete_palette"
    bl_label    = "Delete This Palette"
    bl_description = "Delete the current palette"
    # REGISTER+UNDO mandatory for the dialog-from-menu (see rename). The guard
    # against re-execution without the dialog (redo/F9/Repeat Last → direct
    # execute(), which here WOULD DELETE a palette without confirmation) is
    # 'confirmed': default False, SKIP_SAVE (never stored), set to True only by
    # invoke — the only path that shows the dialog.
    bl_options  = {'REGISTER', 'UNDO'}

    confirmed: BoolProperty(default=False, options={'SKIP_SAVE', 'HIDDEN'}) # type: ignore

    def invoke(self, context, event):
        # invoke_props_dialog (NOT invoke_confirm): from the gear menu the modal
        # wheel stays OPEN and holds the input grab. invoke_confirm is a transient
        # popup and would be discarded instantly by the grab (the confirmation
        # popup did not appear); invoke_props_dialog is a block-dialog that holds
        # up over the modal, like the Rename dialog. From the N-panel button (no
        # modal) it works just as well. The draw below shows the prompt;
        # confirm_text renames the OK button to "Delete".
        from .prefs import get_active_palette
        self._del_name = get_active_palette(context).name
        self.confirmed = True   # only the dialog path may delete
        return context.window_manager.invoke_props_dialog(
            self, width=240, title="Delete This Palette", confirm_text="Delete")

    def draw(self, context):
        col = self.layout.column()
        col.label(text=f"Delete palette \"{self._del_name}\"?", icon='TRASH')
        col.label(text="This cannot be undone.")

    def execute(self, context):
        from .prefs import ensure_palettes, can_delete, clamp_index, request_prefs_save
        if not self.confirmed:
            # execute() reached WITHOUT going through the invoke dialog (redo, F9,
            # Repeat Last, a script call without 'INVOKE_DEFAULT'): never delete
            # silently.
            return {'CANCELLED'}
        prefs = ensure_palettes(context)
        if not can_delete(len(prefs.palettes)):
            self.report({'WARNING'}, "Sculptools: cannot delete the only palette")
            return {'CANCELLED'}
        prefs.palettes.remove(prefs.active_palette_index)
        prefs.active_palette_index = clamp_index(prefs.active_palette_index,
                                                len(prefs.palettes))
        request_prefs_save()
        _tag_view3d(context)
        return {'FINISHED'}


class SCULPTOOLS_OT_jump_palette(Operator):
    """Jump straight to the palette with a given number, GLOBALLY in Sculpt Mode
    (no wheel needed). One active keymap item per number (modifier + 1..8) points
    here with its palette_index; the modifier keeps them from clashing with Quick
    Numbers' plain number keys (see prefs.sync_jump_bindings / __init__)."""
    bl_idname   = "sculptools.jump_palette"
    bl_label    = "Jump to Palette"
    bl_description = "Switch directly to the palette with this number"
    bl_options  = {'INTERNAL'}   # no re-execution from redo/F9 (see rename)

    palette_index: IntProperty(default=0)  # type: ignore  # 0-based (key 1 -> 0)

    @classmethod
    def poll(cls, context):
        return context.mode == 'SCULPT'

    def execute(self, context):
        from .prefs import ensure_palettes, request_prefs_save
        prefs = ensure_palettes(context)
        n = len(prefs.palettes)
        if self.palette_index < 0 or self.palette_index >= n:
            # Number beyond the palettes that exist → no-op (silent). The key is
            # only ever bound WITH a modifier, so consuming it here never steals
            # a plain number key from Quick Numbers.
            return {'CANCELLED'}
        if prefs.active_palette_index != self.palette_index:
            prefs.active_palette_index = self.palette_index
            request_prefs_save()
            _tag_view3d(context)
        self.report({'INFO'}, f"Sculptools: palette {self.palette_index + 1}")
        return {'FINISHED'}


class SCULPTOOLS_OT_rename_palette_menu(Operator):
    """Launcher for the Rename dialog from the gear menu. execute-only, NO
    invoke: a menu item that DIRECTLY invokes an operator with invoke_props_dialog,
    while the wheel modal holds the input grab, does not open the dialog (Rename
    ended up in the redo panel at the bottom left; Delete did nothing). By
    delegating to bpy.ops.<dialog>('INVOKE_DEFAULT') from execute — the same
    pattern as New/Duplicate, which works — the dialog opens correctly and the
    wheel stays open behind it. The real dialog (sculptools.rename_palette) remains
    reachable via bpy.ops / N-panel."""
    bl_idname   = "sculptools.rename_palette_menu"
    bl_label    = "Rename Palette"
    bl_options  = {'INTERNAL'}

    def execute(self, context):
        try:
            bpy.ops.sculptools.rename_palette('INVOKE_DEFAULT')
        except Exception as exc:
            print(f"Sculptools: rename dialog failed to open: {exc}")
        return {'FINISHED'}


class SCULPTOOLS_OT_delete_palette_menu(Operator):
    """Launcher for the Delete confirmation dialog from the gear menu. Same
    indirection (and same reason) as SCULPTOOLS_OT_rename_palette_menu."""
    bl_idname   = "sculptools.delete_palette_menu"
    bl_label    = "Delete This Palette"
    bl_options  = {'INTERNAL'}

    def execute(self, context):
        try:
            bpy.ops.sculptools.delete_palette('INVOKE_DEFAULT')
        except Exception as exc:
            print(f"Sculptools: delete dialog failed to open: {exc}")
        return {'FINISHED'}


class SCULPTOOLS_MT_palette_context(Menu):
    """Context menu of the central gear (left click). Rename and Delete go
    through the execute-only *_menu wrappers: launched directly from here while
    the wheel (modal) holds the grab, their invoke_props_dialog would not open the
    dialog. New/Duplicate are already execute-only and are fine."""
    bl_idname = "SCULPTOOLS_MT_palette_context"
    bl_label  = "Palette"

    def draw(self, context):
        from .prefs import get_prefs, can_add, can_delete
        n = len(get_prefs(context).palettes)
        layout = self.layout
        layout.operator("sculptools.rename_palette_menu", text="Rename Palette…",
                       icon="GREASEPENCIL")
        row = layout.row(); row.enabled = can_add(n)
        row.operator("sculptools.new_palette", text="New Palette", icon="ADD")
        row2 = layout.row(); row2.enabled = can_add(n)
        row2.operator("sculptools.duplicate_palette", text="Duplicate Palette",
                     icon="DUPLICATE")
        layout.separator()
        row3 = layout.row(); row3.enabled = can_delete(n)
        row3.operator("sculptools.delete_palette_menu", text="Delete This Palette",
                     icon="TRASH")
        layout.separator()
        layout.operator("sculptools.export_palettes_menu", text="Export Palettes…",
                       icon="EXPORT")
        layout.operator("sculptools.import_palettes_menu", text="Import Palettes…",
                       icon="IMPORT")


# ── Palette preset Import / Export ────────────────────────────────────────────

def _addon_version_string():
    """Read version from blender_manifest.toml (source of truth). Diagnostic
    only in the export file; never enforced on import."""
    try:
        import tomllib
        path = os.path.join(os.path.dirname(__file__), "blender_manifest.toml")
        with open(path, "rb") as f:
            return str(tomllib.load(f).get("version", "unknown"))
    except Exception:
        return "unknown"


def _read_appearance(prefs):
    from .panel import _APPEARANCE_PROPS
    out = {}
    for k in _APPEARANCE_PROPS:
        try:
            v = getattr(prefs, k)
            out[k] = bool(v) if isinstance(v, bool) else float(v)
        except Exception:
            pass
    return out


def _available_brush_names(context):
    """Best-effort set of brush names resolvable now. Runs the one allowed
    Essentials preload so bundled brushes count as present (Golden Rule #3:
    this is the designated load, guarded to run once)."""
    from . import gpu_draw
    try:
        gpu_draw.preload_bundled_previews()
    except Exception:
        pass
    names = set(bpy.data.brushes.keys())
    from .prefs import get_prefs
    for pit in get_prefs(context).palettes:
        from .prefs import _read_palette_dict
        d = _read_palette_dict(pit)
        for n in d['slots']:
            if n and gpu_draw.brush_name_available(n):
                names.add(n)
        for row in d['subs']:
            for n in row:
                if n and gpu_draw.brush_name_available(n):
                    names.add(n)
    return names


class SCULPTOOLS_OT_export_palettes(Operator, ExportHelper):
    bl_idname   = "sculptools.export_palettes"
    bl_label    = "Export Palettes"
    bl_description = "Save all palettes and appearance settings to a .json preset file"
    bl_options  = {'INTERNAL'}
    filename_ext = ".json"
    filter_glob: StringProperty(default="*.json", options={'HIDDEN'}) # type: ignore

    def invoke(self, context, event):
        if not self.filepath:
            self.filepath = "sculptools_palettes.json"
        return ExportHelper.invoke(self, context, event)

    def execute(self, context):
        from .prefs import ensure_palettes, get_prefs, _read_palette_dict
        from . import presets
        ensure_palettes(context)
        prefs = get_prefs(context)
        palette_dicts = [_read_palette_dict(p) for p in prefs.palettes]
        data = presets.build_preset_dict(
            palette_dicts, _read_appearance(prefs),
            _addon_version_string(), tuple(bpy.app.version))
        try:
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except OSError as exc:
            self.report({'ERROR'}, f"Could not write file: {exc}")
            return {'CANCELLED'}
        self.report({'INFO'},
                    f"Exported {len(palette_dicts)} palettes to "
                    f"{os.path.basename(self.filepath)}")
        return {'FINISHED'}


class SCULPTOOLS_OT_import_palettes(Operator, ImportHelper):
    bl_idname   = "sculptools.import_palettes"
    bl_label    = "Import Palettes"
    bl_description = "Replace ALL palettes with those from a .json preset file"
    bl_options  = {'INTERNAL'}
    filter_glob: StringProperty(default="*.json", options={'HIDDEN'}) # type: ignore

    def draw(self, context):
        col = self.layout.column()
        col.label(text="Replaces ALL current palettes", icon='ERROR')

    def execute(self, context):
        from .prefs import (ensure_palettes, get_prefs, _apply_palette_dict,
                            request_prefs_save, MAX_PALETTES)
        from .panel import _APPEARANCE_PROPS, _tag_redraw_view3d
        from . import presets, gpu_draw

        # 1. read + parse (non-destructive)
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as exc:
            self.report({'ERROR'}, f"Not a valid preset file: {exc}")
            return {'CANCELLED'}

        # 2. validate
        ok, err = presets.validate_preset(data)
        if not ok:
            self.report({'ERROR'}, err)
            return {'CANCELLED'}

        # 3. build fully in memory (still non-destructive)
        sanitized, skipped = [], 0
        for raw in data["palettes"]:
            s = presets.sanitize_palette_dict(raw)
            if s is None:
                skipped += 1
            else:
                sanitized.append(s)
        if not sanitized:
            self.report({'ERROR'}, "No usable palettes to import")
            return {'CANCELLED'}
        clamped = 0
        if len(sanitized) > MAX_PALETTES:
            clamped = len(sanitized) - MAX_PALETTES
            sanitized = sanitized[:MAX_PALETTES]
        appearance = presets.sanitize_appearance(data.get("appearance", {}),
                                                 _APPEARANCE_PROPS)

        # 4. atomic swap
        ensure_palettes(context)
        prefs = get_prefs(context)
        prefs.palettes.clear()
        for s in sanitized:
            _apply_palette_dict(prefs.palettes.add(), s)
        for k, v in appearance.items():
            try:
                setattr(prefs, k, v)
            except Exception:
                pass
        prefs.active_palette_index = 0

        # 5. count availability + persist + redraw
        found, total = presets.count_available_entries(
            sanitized, _available_brush_names(context), tuple(bpy.app.version))
        request_prefs_save()
        _tag_redraw_view3d(context)

        msg = (f"Imported {len(sanitized)} palettes — "
               f"{found}/{total} brushes & tools available")
        self.report({'INFO'}, msg)
        if skipped or clamped:
            self.report({'WARNING'},
                        f"Skipped {skipped} malformed and {clamped} over-limit palettes")
        return {'FINISHED'}


class SCULPTOOLS_OT_export_palettes_menu(Operator):
    """Gear-menu launcher for Export (execute-only, INVOKE_DEFAULT delegate) —
    same pattern as rename/delete so the file browser opens while the wheel
    modal holds the input grab."""
    bl_idname   = "sculptools.export_palettes_menu"
    bl_label    = "Export Palettes"
    bl_options  = {'INTERNAL'}

    def execute(self, context):
        try:
            bpy.ops.sculptools.export_palettes('INVOKE_DEFAULT')
        except Exception as exc:
            print(f"Sculptools: export browser failed to open: {exc}")
        return {'FINISHED'}


class SCULPTOOLS_OT_import_palettes_menu(Operator):
    """Gear-menu launcher for Import. Same indirection as export_palettes_menu."""
    bl_idname   = "sculptools.import_palettes_menu"
    bl_label    = "Import Palettes"
    bl_options  = {'INTERNAL'}

    def execute(self, context):
        try:
            bpy.ops.sculptools.import_palettes('INVOKE_DEFAULT')
        except Exception as exc:
            print(f"Sculptools: import browser failed to open: {exc}")
        return {'FINISHED'}


# ── All classes ───────────────────────────────────────────────────────────────

all_operator_classes = [
    SCULPTOOLS_OT_assign_to_slot,
    SCULPTOOLS_OT_confirm_assign,
    SCULPTOOLS_OT_clear_slot,
    SCULPTOOLS_OT_shelf_add,
    SCULPTOOLS_MT_slot_actions_main,
    SCULPTOOLS_MT_slot_actions_sub0,
    SCULPTOOLS_MT_slot_actions_sub1,
    SCULPTOOLS_MT_slot_actions_sub2,
    SCULPTOOLS_MT_slot_context,
    SCULPTOOLS_OT_slot_add_active,
    SCULPTOOLS_OT_slot_cut,
    SCULPTOOLS_OT_slot_copy,
    SCULPTOOLS_OT_slot_paste,
    SCULPTOOLS_OT_slot_remove,
    SCULPTOOLS_OT_assign_tool_to_slot,
    SCULPTOOLS_MT_assign_tool,
    SCULPTOOLS_OT_rename_palette,
    SCULPTOOLS_OT_rename_palette_menu,
    SCULPTOOLS_OT_new_palette,
    SCULPTOOLS_OT_duplicate_palette,
    SCULPTOOLS_OT_delete_palette,
    SCULPTOOLS_OT_delete_palette_menu,
    SCULPTOOLS_OT_jump_palette,
    SCULPTOOLS_OT_export_palettes,
    SCULPTOOLS_OT_export_palettes_menu,
    SCULPTOOLS_OT_import_palettes,
    SCULPTOOLS_OT_import_palettes_menu,
    SCULPTOOLS_MT_palette_context,
]
