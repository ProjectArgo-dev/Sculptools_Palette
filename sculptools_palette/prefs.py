# sculptools_palette/prefs.py

import bpy
from bpy.types import AddonPreferences
from bpy.props import (StringProperty, FloatProperty, FloatVectorProperty,
                       IntProperty, BoolProperty, CollectionProperty,
                       EnumProperty)

MAX_SLOTS    = 10   # hard storage ceiling (property slots exist for all 10)
NUM_SUBSLOTS = 3

MAX_PALETTES = 8   # palette ceiling (memory/perf are not the constraint — only the
                   # UX of cycle/jump; v2.7.0 raised 4->8 at the user's request)

# DEFAULT colours of a NEW palette (the migrated one uses the current globals).
NEW_SLOT_COLOUR = (1.0, 1.0, 1.0)                       # #FFFFFF
NEW_SUB_COLOUR  = (0.7372549, 0.7372549, 0.7372549)     # #BCBCBC

# Colours of the DEFAULT palette (the first/migrated/factory-reset one).
# Different from a NEW palette's colours (NEW_*): light-blue slot, cyan sub.
DEFAULT_SLOT_COLOUR = (0.5921569, 0.9058824, 1.0)        # #97E7FF
DEFAULT_SUB_COLOUR  = (0.3882353, 0.9215686, 0.9215686)  # #63EBEB

_KEY_LABELS = {
    'BACK_SLASH': '\\', 'GRAVE': '`', 'TAB': 'Tab', 'SPACE': 'Space',
    'PAGE_UP': 'Page Up', 'PAGE_DOWN': 'Page Down',
    'LEFT_BRACKET': '[', 'RIGHT_BRACKET': ']',
}


def key_label(key_type):
    """Simbolo/etichetta mostrata negli hint centrali per un event.type."""
    if key_type in _KEY_LABELS:
        return _KEY_LABELS[key_type]
    if len(key_type) == 1:
        return key_type
    return key_type.replace('_', ' ').title()


def key_chord_label(key_type, ctrl=False, alt=False, shift=False, oskey=False):
    """Etichetta di una chord (tipo + modificatori), es. 'Ctrl + Tab'."""
    parts = []
    if ctrl:  parts.append("Ctrl")
    if alt:   parts.append("Alt")
    if shift: parts.append("Shift")
    if oskey: parts.append("OS")
    parts.append(key_label(key_type))
    return " + ".join(parts)


def keys_conflict(a, b):
    """True se due chord (type, ctrl, alt, shift, oskey) sono identiche."""
    if a is None or b is None:
        return False
    return tuple(a) == tuple(b)


def wrap_index(i, n, delta):
    """Indice successivo con wrap; 0 se n<=0."""
    if n <= 0:
        return 0
    return (i + delta) % n


def clamp_index(i, n):
    """Vincola i in [0, n-1]; 0 se n<=0."""
    if n <= 0:
        return 0
    return max(0, min(i, n - 1))


def can_add(n):
    return n < MAX_PALETTES


def can_delete(n):
    return n > 1


def _empty_slots():
    return ["" for _ in range(MAX_SLOTS)]


def _empty_subs():
    return [["" for _ in range(NUM_SUBSLOTS)] for _ in range(MAX_SLOTS)]


DEFAULT_NUM_SLOTS = 6   # slot count of a new palette (num_slots is per-palette)


def build_new_palette(name="New Palette"):
    """Dict of an empty palette with the NEW palette's default colours."""
    return {
        'name': name,
        'num_slots': DEFAULT_NUM_SLOTS,
        'slots': _empty_slots(),
        'subs': _empty_subs(),
        'slot_colour': tuple(NEW_SLOT_COLOUR),
        'sub_colour': tuple(NEW_SUB_COLOUR),
    }


def build_duplicate_palette(src):
    """DEEP copy of a palette dict; name + ' copy'."""
    return {
        'name': f"{src['name']} copy",
        'num_slots': src.get('num_slots', DEFAULT_NUM_SLOTS),
        'slots': list(src['slots']),
        'subs': [list(row) for row in src['subs']],
        'slot_colour': tuple(src['slot_colour']),
        'sub_colour': tuple(src['sub_colour']),
    }


def build_migrated_palette(name, slots, subs, slot_colour, sub_colour,
                           num_slots=DEFAULT_NUM_SLOTS):
    """Palette dict from the old flat fields, padded up to MAX_SLOTS/NUM_SUBSLOTS."""
    out_slots = [(slots[i] if i < len(slots) else "") for i in range(MAX_SLOTS)]
    out_subs = [
        [(subs[i][j] if i < len(subs) and j < len(subs[i]) else "")
         for j in range(NUM_SUBSLOTS)]
        for i in range(MAX_SLOTS)
    ]
    return {
        'name': name,
        'num_slots': num_slots,
        'slots': out_slots,
        'subs': out_subs,
        'slot_colour': tuple(slot_colour),
        'sub_colour': tuple(sub_colour),
    }


def build_default_palette(name="-Palette Name-"):
    """Dict of the DEFAULT (empty) palette with the default-palette colours
    (#ACECFF / #63EBEB). Used by the factory reset and as the conceptual source
    of the migrated palette."""
    return {
        'name': name,
        'num_slots': DEFAULT_NUM_SLOTS,
        'slots': _empty_slots(),
        'subs': _empty_subs(),
        'slot_colour': tuple(DEFAULT_SLOT_COLOUR),
        'sub_colour': tuple(DEFAULT_SUB_COLOUR),
    }

# Sub-slots are STORED by index (0..NUM_SUBSLOTS-1) but PRESENTED and VISITED in
# the order below — the Quick Numbers cycle (main -> Sub 1 -> Sub 2 -> Sub 3),
# the "Sub N" labels and the assign popup all derive from this single tuple.
#
# Physical layout: gpu_draw._sub_positions returns [left, top, right] and the
# wheel maps position k -> stored index k, so stored 0 = "left", 1 = "top"
# (the one collinear/outward from the main slot), 2 = "right".
#
# Order chosen by the user (v2.7.0): visit the two side subs first, then the
# collinear "top" sub LAST — so tap 4 (the final tap of the numeric cycle)
# always lands on the outward sub. That is stored order (2, 0, 1):
#   tap 2 = stored 2 (Sub 1),  tap 3 = stored 0 (Sub 2),  tap 4 = stored 1 (Sub 3).
SUB_CYCLE_ORDER = (2, 0, 1)


def sub_display_number(j):
    """1-based number shown to the user for a stored sub index `j`: its position
    within SUB_CYCLE_ORDER (so labels always follow the visit order, whatever
    that order is). stored 2 -> 1, stored 0 -> 2, stored 1 -> 3."""
    return SUB_CYCLE_ORDER.index(j) + 1


def _preview_redraw(self, context):
    """Update callback for Appearance sliders & the preview toggle: keeps
    the live wheel preview (drawn in the 'Palette' sidebar tab) in sync
    while the user drags a slider, without redrawing needlessly when the
    preview is off."""
    if not getattr(self, 'show_preview', False):
        return
    wm = getattr(context, 'window_manager', None) or bpy.context.window_manager
    for window in wm.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


def _dynamic_sliders_toggle(self, context):
    """When Dynamic Sliders is switched off, deactivate our RIGHTMOUSE keymap
    item so right-click falls back 100% to Blender's native sculpt context
    menu; re-activate it when switched on. Looking the item up from the addon
    keyconfig avoids importing __init__ (circular)."""
    try:
        kc = bpy.context.window_manager.keyconfigs.addon
        if not kc:
            return
        km = kc.keymaps.get("Sculpt")
        if not km:
            return
        for kmi in km.keymap_items:
            if kmi.idname == "sculptools.dynamic_sliders":
                kmi.active = self.dynamic_sliders_enabled
                break
    except Exception:
        pass


def _quick_numbers_toggle(self, context):
    """Enable/disable all Quick Numbers keymap items (one per number key) so
    that, when the feature is off, the number keys fall back to their native
    Sculpt behaviour. Same addon-keyconfig lookup pattern as the sliders."""
    try:
        kc = bpy.context.window_manager.keyconfigs.addon
        if not kc:
            return
        km = kc.keymaps.get("Sculpt")
        if not km:
            return
        for kmi in km.keymap_items:
            if kmi.idname == "sculptools.quick_number":
                kmi.active = self.quick_numbers_enabled
    except Exception:
        pass


def _jump_modifier_update(self, context):
    """When the user changes the Jump modifier from the dropdown, propagate the
    choice to the 8 real keymap items. sync_jump_bindings is defined further down:
    resolution happens at runtime, so ordering is not a problem."""
    try:
        sync_jump_bindings(context)
    except Exception:
        pass


from bpy.types import PropertyGroup


def _palette_colour_update(self, context):
    """Update callback for per-palette colours: the live preview lives on
    AddonPreferences, not on the PaletteItem — so we reach prefs.show_preview via
    context (reusing _preview_redraw would always see self.show_preview=False)."""
    try:
        prefs = get_prefs(context)
    except Exception:
        return
    if not getattr(prefs, 'show_preview', False):
        return
    _preview_redraw(prefs, context)


class PaletteItem(PropertyGroup):
    name: StringProperty(default="Palette") # type: ignore

    # num_slots is PER-PALETTE (each palette can have a different slot count).
    num_slots: IntProperty(
        name="Number of Slots", default=DEFAULT_NUM_SLOTS, min=2, max=10,
        description="Number of main slots in this palette's pie",
        update=_palette_colour_update) # type: ignore

    slot_0: StringProperty(default="") # type: ignore
    slot_1: StringProperty(default="") # type: ignore
    slot_2: StringProperty(default="") # type: ignore
    slot_3: StringProperty(default="") # type: ignore
    slot_4: StringProperty(default="") # type: ignore
    slot_5: StringProperty(default="") # type: ignore
    slot_6: StringProperty(default="") # type: ignore
    slot_7: StringProperty(default="") # type: ignore
    slot_8: StringProperty(default="") # type: ignore
    slot_9: StringProperty(default="") # type: ignore

    sub_0_0: StringProperty(default="") # type: ignore
    sub_0_1: StringProperty(default="") # type: ignore
    sub_0_2: StringProperty(default="") # type: ignore
    sub_1_0: StringProperty(default="") # type: ignore
    sub_1_1: StringProperty(default="") # type: ignore
    sub_1_2: StringProperty(default="") # type: ignore
    sub_2_0: StringProperty(default="") # type: ignore
    sub_2_1: StringProperty(default="") # type: ignore
    sub_2_2: StringProperty(default="") # type: ignore
    sub_3_0: StringProperty(default="") # type: ignore
    sub_3_1: StringProperty(default="") # type: ignore
    sub_3_2: StringProperty(default="") # type: ignore
    sub_4_0: StringProperty(default="") # type: ignore
    sub_4_1: StringProperty(default="") # type: ignore
    sub_4_2: StringProperty(default="") # type: ignore
    sub_5_0: StringProperty(default="") # type: ignore
    sub_5_1: StringProperty(default="") # type: ignore
    sub_5_2: StringProperty(default="") # type: ignore
    sub_6_0: StringProperty(default="") # type: ignore
    sub_6_1: StringProperty(default="") # type: ignore
    sub_6_2: StringProperty(default="") # type: ignore
    sub_7_0: StringProperty(default="") # type: ignore
    sub_7_1: StringProperty(default="") # type: ignore
    sub_7_2: StringProperty(default="") # type: ignore
    sub_8_0: StringProperty(default="") # type: ignore
    sub_8_1: StringProperty(default="") # type: ignore
    sub_8_2: StringProperty(default="") # type: ignore
    sub_9_0: StringProperty(default="") # type: ignore
    sub_9_1: StringProperty(default="") # type: ignore
    sub_9_2: StringProperty(default="") # type: ignore

    slot_rim_colour: FloatVectorProperty(
        name="Slot Outline Colour", subtype='COLOR_GAMMA', size=3,
        default=NEW_SLOT_COLOUR, min=0.0, max=1.0,
        update=_palette_colour_update) # type: ignore
    subslot_rim_colour: FloatVectorProperty(
        name="Sub-slot Outline Colour", subtype='COLOR_GAMMA', size=3,
        default=NEW_SUB_COLOUR, min=0.0, max=1.0,
        update=_palette_colour_update) # type: ignore


class SculptoolsPreferences(AddonPreferences):
    bl_idname = __package__

    palettes: CollectionProperty(type=PaletteItem) # type: ignore
    active_palette_index: IntProperty(default=0) # type: ignore

    # "Cycle palette" hotkey: a "holder" keymap item (sculptools.cycle_palette_holder,
    # created in __init__.register, ACTIVE since v2.7.1) edited by the native keymap
    # widget. Outside the preview the operator does PASS_THROUGH; with the Preview
    # Editor open it cycles the palettes. The modal reads its chord at invoke
    # (get_cycle_key_binding). No property here.

    # 8 main slots
    slot_0: StringProperty(name="Slot 1", default="") # type: ignore
    slot_1: StringProperty(name="Slot 2", default="") # type: ignore
    slot_2: StringProperty(name="Slot 3", default="") # type: ignore
    slot_3: StringProperty(name="Slot 4", default="") # type: ignore
    slot_4: StringProperty(name="Slot 5", default="") # type: ignore
    slot_5: StringProperty(name="Slot 6", default="") # type: ignore
    slot_6: StringProperty(name="Slot 7", default="") # type: ignore
    slot_7: StringProperty(name="Slot 8", default="") # type: ignore
    slot_8: StringProperty(name="Slot 9", default="") # type: ignore
    slot_9: StringProperty(name="Slot 10", default="") # type: ignore

    # 8x3 sub-slots
    sub_0_0: StringProperty(name="Slot 1 / Sub 1", default="") # type: ignore
    sub_0_1: StringProperty(name="Slot 1 / Sub 2", default="") # type: ignore
    sub_0_2: StringProperty(name="Slot 1 / Sub 3", default="") # type: ignore
    sub_1_0: StringProperty(name="Slot 2 / Sub 1", default="") # type: ignore
    sub_1_1: StringProperty(name="Slot 2 / Sub 2", default="") # type: ignore
    sub_1_2: StringProperty(name="Slot 2 / Sub 3", default="") # type: ignore
    sub_2_0: StringProperty(name="Slot 3 / Sub 1", default="") # type: ignore
    sub_2_1: StringProperty(name="Slot 3 / Sub 2", default="") # type: ignore
    sub_2_2: StringProperty(name="Slot 3 / Sub 3", default="") # type: ignore
    sub_3_0: StringProperty(name="Slot 4 / Sub 1", default="") # type: ignore
    sub_3_1: StringProperty(name="Slot 4 / Sub 2", default="") # type: ignore
    sub_3_2: StringProperty(name="Slot 4 / Sub 3", default="") # type: ignore
    sub_4_0: StringProperty(name="Slot 5 / Sub 1", default="") # type: ignore
    sub_4_1: StringProperty(name="Slot 5 / Sub 2", default="") # type: ignore
    sub_4_2: StringProperty(name="Slot 5 / Sub 3", default="") # type: ignore
    sub_5_0: StringProperty(name="Slot 6 / Sub 1", default="") # type: ignore
    sub_5_1: StringProperty(name="Slot 6 / Sub 2", default="") # type: ignore
    sub_5_2: StringProperty(name="Slot 6 / Sub 3", default="") # type: ignore
    sub_6_0: StringProperty(name="Slot 7 / Sub 1", default="") # type: ignore
    sub_6_1: StringProperty(name="Slot 7 / Sub 2", default="") # type: ignore
    sub_6_2: StringProperty(name="Slot 7 / Sub 3", default="") # type: ignore
    sub_7_0: StringProperty(name="Slot 8 / Sub 1", default="") # type: ignore
    sub_7_1: StringProperty(name="Slot 8 / Sub 2", default="") # type: ignore
    sub_7_2: StringProperty(name="Slot 8 / Sub 3", default="") # type: ignore
    sub_8_0: StringProperty(name="Slot 9 / Sub 1", default="") # type: ignore
    sub_8_1: StringProperty(name="Slot 9 / Sub 2", default="") # type: ignore
    sub_8_2: StringProperty(name="Slot 9 / Sub 3", default="") # type: ignore
    sub_9_0: StringProperty(name="Slot 10 / Sub 1", default="") # type: ignore
    sub_9_1: StringProperty(name="Slot 10 / Sub 2", default="") # type: ignore
    sub_9_2: StringProperty(name="Slot 10 / Sub 3", default="") # type: ignore

    # Appearance — edited from the "Palette" sidebar tab in Sculpt Mode
    # (see panel.py); kept here since AddonPreferences is where the modal
    # operator reads them from.
    num_slots: IntProperty(
        name="Number of Slots", default=6, min=2, max=10,
        description="Number of main slots in the pie palette",
        update=_preview_redraw) # type: ignore
    palette_radius: FloatProperty(
        name="Palette Radius", default=200.0, min=180.0, max=300.0,
        update=_preview_redraw) # type: ignore
    slot_radius: FloatProperty(
        name="Slot Radius", default=50.0, min=30.0, max=60.0,
        update=_preview_redraw) # type: ignore
    hover_delay: FloatProperty(
        name="Hover Delay (s)", default=0.1, min=0.05, max=1.0,
        description="Time the cursor must hover a slot before sub-slots appear",
        update=_preview_redraw) # type: ignore
    fade_out_duration: FloatProperty(
        name="Sub-slot Fade Out (s)", default=0.20, min=0.02, max=2.0,
        description="How quickly sub-slots disappear after moving the cursor away",
        update=_preview_redraw) # type: ignore
    slot_rim_width: FloatProperty(
        name="Slot Outline Width", default=3.0, min=1.0, max=8.0,
        description="Thickness in pixels of the outline around main slots",
        update=_preview_redraw) # type: ignore
    slot_rim_colour: FloatVectorProperty(
        name="Slot Outline Colour", subtype='COLOR_GAMMA', size=3,
        # hex #97E7FF -> (151, 231, 255) / 255 (the default-palette default; it is
        # the migration source, so the first freshly-migrated palette inherits this)
        default=(0.5921569, 0.9058824, 1.0), min=0.0, max=1.0,
        description="Colour of the main-slot outline and of its hover glow",
        update=_preview_redraw) # type: ignore

    # Hover glow (radial gradient behind the hovered slot/sub-slot)
    glow_size: FloatProperty(
        name="Gradient Size", default=1.6, min=1.0, max=3.0,
        description="Radius of the hover glow, as a multiple of the slot radius",
        update=_preview_redraw) # type: ignore
    glow_intensity: FloatProperty(
        name="Gradient Intensity", default=1.0, min=0.0, max=1.0,
        description="Opacity of the hover glow at its centre",
        update=_preview_redraw) # type: ignore
    glow_falloff: FloatProperty(
        name="Gradient Falloff", default=2.5, min=0.2, max=5.0,
        description="Shape of the glow fade: 1.0 is linear, higher values "
                    "concentrate the glow near the centre, lower values spread "
                    "it out toward the edge",
        update=_preview_redraw) # type: ignore

    # Sub-slot positioning
    sub_size_factor: FloatProperty(
        name="Sub-slot Size", default=0.70, min=0.3, max=1.5,
        description="Size of sub-slots relative to Slot Radius",
        update=_preview_redraw) # type: ignore
    sub_separation: FloatProperty(
        name="Sub-slot Distance", default=55.0, min=40.0, max=250.0,
        description="Extra gap in pixels between slot and sub-slot circles. "
                    "Higher values push the sub-slots further out along the "
                    "vector from their parent slot",
        update=_preview_redraw) # type: ignore
    subslot_rim_width: FloatProperty(
        name="Sub-slot Outline Width", default=2.0, min=1.0, max=4.0,
        description="Thickness in pixels of the outline around sub-slots",
        update=_preview_redraw) # type: ignore
    subslot_rim_colour: FloatVectorProperty(
        name="Sub-slot Outline Colour", subtype='COLOR_GAMMA', size=3,
        # hex #63EBEB -> (99, 235, 235) / 255
        default=(0.3882353, 0.9215686, 0.9215686), min=0.0, max=1.0,
        description="Colour of the sub-slot outline and of its hover glow",
        update=_preview_redraw) # type: ignore

    # Dynamic Brush Sliders: right-click + drag to adjust brush Radius/Strength
    dynamic_sliders_enabled: BoolProperty(
        name="Dynamic Brush Sliders", default=True,
        description="Right-click + drag in the viewport to adjust brush Radius "
                    "(horizontal) and Strength (vertical). A quick right-click "
                    "still opens the native context menu",
        update=_dynamic_sliders_toggle) # type: ignore

    # Fixed Slot Outline: when on (default) slot & sub-slot outlines are always
    # visible with their configured colour/width; when off, an outline is drawn
    # only on hover and elements at rest show a thin 1px grey (#808080) outline.
    fixed_slot_outline: BoolProperty(
        name="Fixed Slot Outline", default=True,
        description="When on, slot and sub-slot outlines are always visible with "
                    "their configured colour and width. When off, outlines appear "
                    "only on hover; at rest slots and sub-slots show a thin 1px "
                    "grey outline",
        update=_preview_redraw) # type: ignore

    # Quick Numbers: number keys select/cycle slot brushes without the wheel
    quick_numbers_enabled: BoolProperty(
        name="Quick Numbers", default=True,
        description="Press a number key (1-9, 0) in Sculpt Mode to activate a "
                    "slot's brush without opening the wheel. Repeat the same "
                    "key to cycle through that slot's sub-slot brushes",
        update=_quick_numbers_toggle) # type: ignore

    # Jump-to-Palette: ONLY the modifier is chosen here (Ctrl/Alt/Shift); the
    # number is fixed 1..8, one per palette. A dropdown instead of the native
    # keymap widget so the user can't assign arbitrary keys (which would clash
    # with Quick Numbers or with Sculpt). The update propagates the choice to the
    # 8 `sculptools.jump_palette` kmis via sync_jump_bindings.
    jump_modifier: EnumProperty(
        name="Jump Modifier",
        description="Modifier held with a number key (1-8) to jump straight to "
                    "that palette in Sculpt Mode. A modifier is required so the "
                    "shortcut never clashes with Quick Numbers (plain number keys)",
        items=[
            ('CTRL',  "Ctrl",  "Ctrl + number (1-8) jumps to that palette"),
            ('ALT',   "Alt",   "Alt + number (1-8) jumps to that palette"),
            ('SHIFT', "Shift", "Shift + number (1-8) jumps to that palette"),
        ],
        default='CTRL',
        update=_jump_modifier_update) # type: ignore

    # Live preview toggle (drawn from the "Palette" sidebar tab)
    show_preview: BoolProperty(
        name="Show Preview", default=False,
        description="Temporarily display the pie palette in the viewport "
                    "while adjusting these settings",
        update=_preview_redraw) # type: ignore

    def draw(self, context):
        layout = self.layout

        layout.label(
            text="All settings live in the dedicated 'Palette' tab of the 3D "
                 "Viewport sidebar (press N while in Sculpt Mode).",
            icon="INFO")
        layout.label(
            text="Edit palette slots there, or right-click a brush in Sculpt "
                 "Mode and choose 'Add brush to Palette'.")


def get_prefs(context):
    return context.preferences.addons[__package__].preferences

def get_num_slots(context):
    # num_slots is now PER-PALETTE: read the active palette's value. The global
    # prefs.num_slots remains only as a migration source.
    return get_active_palette(context).num_slots

def _protect_brush(name):
    """Our slot storage is a plain string (the brush's name), not a real
    RNA/ID pointer property — which means Blender's own reference-counting
    system does NOT see a palette-slot assignment as a genuine 'use' of
    that Brush ID. A brush kept alive only by our string can be silently
    purged by Blender at points we don't control (e.g. during unrelated
    ID-management operations, like the library link/unlink our thumbnail
    loader does), causing it to vanish from a slot with no warning. Setting
    use_fake_user=True is the standard, correct way to tell Blender "keep
    this data around regardless of whether anything formally references
    it" — exactly our situation."""
    if not name:
        return
    brush = bpy.data.brushes.get(name)
    if brush is not None:
        brush.use_fake_user = True


_prefs_save_pending = False


def request_prefs_save():
    """Persist AddonPreferences so slot assignments survive a file reload.

    Palette slots live in AddonPreferences (userpref.blend). File > Open
    RESTORES AddonPreferences from the last-saved userpref, so an assignment
    made in-session but never written to userpref is silently reverted to its
    saved value on reopen (this is why tool/brush assignments "didn't persist").

    We therefore save the preferences after a slot mutation, but:
      • debounced via a one-shot timer so a burst (e.g. Clear All writing 40
        slots) collapses into a single save;
      • only when the user's own "Auto-Save Preferences" is enabled, so we never
        override someone who deliberately manages preferences by hand.
    """
    global _prefs_save_pending
    try:
        prefs = bpy.context.preferences
        if not getattr(prefs, "use_preferences_save", True):
            return  # user manages preferences manually — don't force a save
    except Exception:
        return
    if _prefs_save_pending:
        return
    _prefs_save_pending = True

    def _do():
        global _prefs_save_pending
        _prefs_save_pending = False
        try:
            bpy.ops.wm.save_userpref()
        except Exception as exc:
            print(f"Sculptools: could not save preferences: {exc}")
        return None

    try:
        bpy.app.timers.register(_do, first_interval=0.2)
    except Exception:
        _prefs_save_pending = False


def _apply_palette_dict(pitem, d):
    """Write a palette dict (Task 1 schema) into a PaletteItem."""
    pitem.name = d['name']
    pitem.num_slots = d.get('num_slots', DEFAULT_NUM_SLOTS)
    for i in range(MAX_SLOTS):
        setattr(pitem, f"slot_{i}", d['slots'][i])
        for j in range(NUM_SUBSLOTS):
            setattr(pitem, f"sub_{i}_{j}", d['subs'][i][j])
    pitem.slot_rim_colour = d['slot_colour']
    pitem.subslot_rim_colour = d['sub_colour']


def _read_palette_dict(pitem):
    """Read a PaletteItem into a palette dict (Task 1 schema)."""
    return {
        'name': pitem.name,
        'num_slots': pitem.num_slots,
        'slots': [getattr(pitem, f"slot_{i}", "") for i in range(MAX_SLOTS)],
        'subs': [[getattr(pitem, f"sub_{i}_{j}", "") for j in range(NUM_SUBSLOTS)]
                 for i in range(MAX_SLOTS)],
        'slot_colour': tuple(pitem.slot_rim_colour),
        'sub_colour': tuple(pitem.subslot_rim_colour),
    }


def ensure_palettes(context):
    """Guarantee >=1 palette. On the first call with an empty collection, migrate
    the old flat fields into the first '-Palette Name-' palette (colours = current
    globals). Always clamps active_palette_index. Returns prefs."""
    prefs = get_prefs(context)
    if len(prefs.palettes) == 0:
        pit = prefs.palettes.add()
        d = build_migrated_palette(
            "-Palette Name-",
            [getattr(prefs, f"slot_{i}", "") for i in range(MAX_SLOTS)],
            [[getattr(prefs, f"sub_{i}_{j}", "") for j in range(NUM_SUBSLOTS)]
             for i in range(MAX_SLOTS)],
            tuple(getattr(prefs, "slot_rim_colour", NEW_SLOT_COLOUR)),
            tuple(getattr(prefs, "subslot_rim_colour", NEW_SUB_COLOUR)),
            num_slots=int(getattr(prefs, "num_slots", DEFAULT_NUM_SLOTS)),
        )
        _apply_palette_dict(pit, d)
        prefs.active_palette_index = 0
        request_prefs_save()
    prefs.active_palette_index = clamp_index(prefs.active_palette_index, len(prefs.palettes))
    return prefs


def get_active_palette(context):
    prefs = ensure_palettes(context)
    return prefs.palettes[prefs.active_palette_index]


def get_open_key_binding(context):
    """Chord of the keymap item that opens the wheel, or None if not found."""
    try:
        kc = context.window_manager.keyconfigs.addon
        km = kc.keymaps.get("Sculpt") if kc else None
        if km:
            for kmi in km.keymap_items:
                if kmi.idname == "sculptools.radial_palette":
                    return (kmi.type, kmi.ctrl, kmi.alt, kmi.shift, kmi.oskey)
    except Exception:
        pass
    return None


def get_cycle_key_binding(context):
    """Chord of the palette-cycle 'holder' keymap item (active since v2.7.1, edited
    by the native widget). Falls back to ('TAB', ...) if not found, so that
    key_chord_label and the match in the modal never fail."""
    try:
        kc = context.window_manager.keyconfigs.addon
        km = kc.keymaps.get("Sculpt") if kc else None
        if km:
            for kmi in km.keymap_items:
                if kmi.idname == "sculptools.cycle_palette_holder":
                    return (kmi.type, kmi.ctrl, kmi.alt, kmi.shift, kmi.oskey)
    except Exception:
        pass
    return ('TAB', False, False, False, False)


def cycle_back_binding(cycle_chord):
    """Given the FORWARD cycle chord (type, ctrl, alt, shift, oskey), return
    (type, ctrl, alt, shift=True, oskey, active) for the BACKWARD cycle keymap
    item. `active` is False when the forward chord already uses Shift: there is no
    extra modifier to add → backward not available (a design choice). Pure —
    tested with the stubs."""
    ctype, cctrl, calt, cshift, coskey = cycle_chord
    return (ctype, cctrl, calt, True, coskey, not cshift)


def _apply_back_binding_to_kmi(kmi, desired):
    """Apply the desired binding (type, ctrl, alt, shift, oskey, active) to the
    backward-cycle keymap item. Returns the number of writes performed (0 =
    already correct, so the sync is zero-write at steady state).

    Two pitfalls learned live on Blender 5.1 (via MCP):
    - the modifiers/`active` are INT (0/1), not bool → compare by truthiness with
      bool(), or you would write on every call (keymap churn);
    - the palette cycle is ALWAYS a keyboard key, but the kmi could end up on
      map_type MOUSE (bug 2026-07-10: the old sync copied the forward holder's
      transient state during the native widget's capture). With map_type MOUSE the
      `type` enum does not contain keyboard keys and writing `type='TAB'` RAISES.
      So we force map_type='KEYBOARD' BEFORE `type`: self-heal."""
    ctype, cctrl, calt, cshift, coskey, active = desired
    writes = 0
    if getattr(kmi, 'map_type', 'KEYBOARD') != 'KEYBOARD':
        kmi.map_type = 'KEYBOARD';            writes += 1
    if kmi.type != ctype:                     kmi.type = ctype;    writes += 1
    if bool(kmi.ctrl) != bool(cctrl):         kmi.ctrl = cctrl;    writes += 1
    if bool(kmi.alt) != bool(calt):           kmi.alt = calt;      writes += 1
    if not bool(kmi.shift):                   kmi.shift = True;    writes += 1
    if bool(kmi.oskey) != bool(coskey):       kmi.oskey = coskey;  writes += 1
    if bool(kmi.active) != bool(active):      kmi.active = active;  writes += 1
    return writes


def sync_cycle_back_binding(context):
    """Keeps the BACKWARD-cycle keymap item
    (sculptools.cycle_palette_back_holder) aligned with the forward cycle: copies
    type/ctrl/alt/oskey from the forward holder (get_cycle_key_binding), forces
    shift=True, and activates it only when the forward one does NOT already use
    Shift (cycle_back_binding).

    IMPORTANT: do NOT call it from the N-panel draw. Mutating a keymap item while
    the native capture widget (Open/Cycle hotkey) is active CANCELS the capture
    ('Press a key' reverting) and can copy the forward holder's transient state
    into the back holder (bug 2026-07-10). Call it only OUTSIDE the draw: deferred
    timer in register(), the wheel's invoke, toggle preview.
    Defensive: no-op without keyconfig/keymap (stub)."""
    try:
        desired = cycle_back_binding(get_cycle_key_binding(context))
        kc = context.window_manager.keyconfigs.addon
        km = kc.keymaps.get("Sculpt") if kc else None
        if not km:
            return
        for kmi in km.keymap_items:
            if kmi.idname == "sculptools.cycle_palette_back_holder":
                _apply_back_binding_to_kmi(kmi, desired)
                break
    except Exception:
        pass


# Maps the dropdown choice (prefs.jump_modifier) to the flags (ctrl, alt, shift).
# oskey is always False: we don't offer it (unreliable cross-platform). The chord
# number is fixed 1..8, one per palette (created in __init__.register).
_JUMP_MOD_FLAGS = {
    'CTRL':  (True,  False, False),
    'ALT':   (False, True,  False),
    'SHIFT': (False, False, True),
}


def jump_modifier_flags(modifier):
    """(ctrl, alt, shift) for a modifier string ('CTRL'/'ALT'/'SHIFT'); falls back
    to Ctrl for unknown values. Pure — tested with the stubs."""
    return _JUMP_MOD_FLAGS.get(modifier, (True, False, False))


def sync_jump_bindings(context):
    """Propagate the MODIFIER chosen in the dropdown (prefs.jump_modifier) to all
    8 real `sculptools.jump_palette` keymap items (fixed number 1..8). Writes only
    when they differ (zero writes at steady state). Called from the dropdown's
    update, from the panel draw, and deferred from register() (after Blender has
    reapplied the saved keyconfig customizations)."""
    try:
        prefs = get_prefs(context)
        ctrl, alt, shift = jump_modifier_flags(getattr(prefs, 'jump_modifier', 'CTRL'))
        kc = context.window_manager.keyconfigs.addon
        km = kc.keymaps.get("Sculpt") if kc else None
        if not km:
            return
        for kmi in km.keymap_items:
            if kmi.idname == "sculptools.jump_palette":
                if (kmi.ctrl, kmi.alt, kmi.shift, kmi.oskey) != (ctrl, alt, shift, False):
                    kmi.ctrl  = ctrl
                    kmi.alt   = alt
                    kmi.shift = shift
                    kmi.oskey = False
    except Exception:
        pass


def factory_reset_palettes(context):
    """Empty ALL palettes and leave a single default one ('-Palette Name-' empty,
    default-palette colours). Does not touch the Universal parameters (the caller
    resets those). Returns prefs."""
    prefs = get_prefs(context)
    prefs.palettes.clear()
    pit = prefs.palettes.add()
    _apply_palette_dict(pit, build_default_palette())
    prefs.active_palette_index = 0
    request_prefs_save()
    return prefs


def get_num_palettes(context):
    return len(get_prefs(context).palettes)


def _redraw_live_preview(context):
    """Tag every VIEW_3D area so the live wheel preview refreshes IMMEDIATELY
    after a slot/sub assignment. Assignments made through the open wheel already
    redraw as part of the modal's own event handling, but ones triggered from a
    popup OUTSIDE the viewport event stream — the Asset Shelf right-click
    "Add brush to Palette", the assign-to-slot popup — otherwise leave the
    preview stale until the next unrelated viewport event (an orbit, a click).
    Centralising it here covers every assignment path (assign, paste, tool,
    clear, remove, cut). No-op when the preview is off."""
    try:
        prefs = get_prefs(context)
    except Exception:
        return
    if not getattr(prefs, 'show_preview', False):
        return
    wm = getattr(context, 'window_manager', None) or bpy.context.window_manager
    if not wm:
        return
    for window in wm.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


def get_slot(context, i):
    return getattr(get_active_palette(context), f"slot_{i}", "")


def set_slot(context, i, name):
    _protect_brush(name)
    setattr(get_active_palette(context), f"slot_{i}", name)
    request_prefs_save()
    _redraw_live_preview(context)


def get_sub(context, i, j):
    return getattr(get_active_palette(context), f"sub_{i}_{j}", "")


def set_sub(context, i, j, name):
    _protect_brush(name)
    setattr(get_active_palette(context), f"sub_{i}_{j}", name)
    request_prefs_save()
    _redraw_live_preview(context)


def collect_assigned_brush_names(palettes):
    """Pure: dato un iterabile di oggetti palette-like (ognuno con attributi
    .num_slots, .slot_i, .sub_i_j), ritorna i nomi BRUSH assegnati su TUTTE le
    palette, deduplicati in ordine first-seen. Tool spec (tool:<key>) e stringhe
    vuote sono esclusi — solo brush reali, gli unici la cui preview va scaldata.
    Testabile senza bpy."""
    from .tools import is_tool_spec
    seen = {}
    for pit in palettes:
        n = int(getattr(pit, "num_slots", DEFAULT_NUM_SLOTS))
        for i in range(min(n, MAX_SLOTS)):
            names = [getattr(pit, f"slot_{i}", "")]
            names += [getattr(pit, f"sub_{i}_{j}", "") for j in range(NUM_SUBSLOTS)]
            for name in names:
                if name and not is_tool_spec(name):
                    seen.setdefault(name, None)
    return list(seen.keys())


def iter_all_assigned_brush_names(context):
    """Tutti i nomi brush assegnati su ogni palette (glue su
    collect_assigned_brush_names). ensure_palettes garantisce >=1 palette e
    clampa l'indice attivo. Ritorna una lista deduplicata."""
    prefs = ensure_palettes(context)
    return collect_assigned_brush_names(prefs.palettes)
