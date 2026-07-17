# sculptools_palette/__init__.py

# NB: no `bl_info`. Since v2.7.0 the add-on ships as an EXTENSION (Blender 4.2+):
# all metadata (name, version, min Blender, license, tags) lives in
# `blender_manifest.toml`, which Blender reads instead of bl_info.

import bpy
persistent = bpy.app.handlers.persistent
from .prefs    import SculptoolsPreferences, PaletteItem, MAX_PALETTES
from .operators import (all_operator_classes, brush_context_menu,
                       toolbar_tool_context_menu,
                       SCULPTOOLS_OT_jump_palette)
from .modal    import SCULPTOOLS_OT_radial_palette
from .dynamic_sliders import (SCULPTOOLS_OT_dynamic_sliders,
                              all_dynamic_slider_classes)
from .quick_numbers import (SCULPTOOLS_OT_quick_number,
                            all_quick_number_classes, _QN_KEYS)
from .gpu_draw import clear_texture_cache, stop_preview_queue
from .panel    import all_panel_classes, enable_preview_handler, disable_preview_handler

_all_classes = (
    [PaletteItem, SculptoolsPreferences]
    + all_operator_classes
    + [SCULPTOOLS_OT_radial_palette]
    + all_dynamic_slider_classes
    + all_quick_number_classes
    + all_panel_classes
)

_addon_keymaps = []

# Mode-gated palette warm-up: pre-carica le preview di TUTTE le palette (non solo
# l'attiva) così switch/jump/cycle non hanno pop-in. DEVE girare in Sculpt mode:
# il preload Essentials linka una library che sgancia transitoriamente il brush di
# sculpt attivo, e il restore riesce SOLO in Sculpt mode (in Blender 5.x
# `tool_settings.sculpt.brush` è READ-ONLY → si riattiva solo via operatore, che
# richiede sculpt mode). Fuori da Sculpt mode la ruota non può nemmeno aprirsi,
# quindi scaldare lì è insieme inutile e pericoloso (azzererebbe il brush).
# `_warmup_poll_active` evita timer accatastati; `_warmup_stop` lo ferma su
# unregister.
_warmup_poll_active = False
_warmup_stop        = False


def _schedule_palette_warmup():
    """Arma un timer leggero che, appena il contesto è in Sculpt mode, scalda una
    volta le preview di tutte le palette e poi si spegne. Finché non sei in sculpt
    (o mai) fa solo un check ~1s, no-op. Idempotente lato coda
    (warm_palette_previews deduplica via _preview_requested)."""
    global _warmup_poll_active
    if _warmup_poll_active:
        return
    _warmup_poll_active = True

    def _tick():
        global _warmup_poll_active
        if _warmup_stop:
            _warmup_poll_active = False
            return None
        try:
            if bpy.context.mode != 'SCULPT':
                return 1.0  # non ancora in sculpt — ricontrolla tra 1s
            from .prefs import iter_all_assigned_brush_names
            from .gpu_draw import warm_palette_previews
            warm_palette_previews(iter_all_assigned_brush_names(bpy.context))
        except Exception as exc:
            print(f"Sculptools: palette preview warm-up skipped: {exc}")
        _warmup_poll_active = False
        return None  # fatto (o errore) — disarma il timer

    try:
        bpy.app.timers.register(_tick, first_interval=1.0)
    except Exception:
        _warmup_poll_active = False


@persistent
def _sculptools_load_post(_dummy):
    """On file load, validate the palette (deferred so the asset system has
    settled and custom-library scans can run off-load): drop assignments whose
    brush can no longer be resolved, e.g. because the user removed the custom
    library it came from. See maintenance.prune_orphaned_brushes for the safety
    rules (it no-ops if any configured library is offline)."""
    def _run():
        try:
            from .maintenance import prune_orphaned_brushes
            prune_orphaned_brushes(bpy.context)
        except Exception as exc:
            print(f"Sculptools: palette validation error: {exc}")
        # Arma il warm-up di TUTTE le palette, ma differito all'ingresso in Sculpt
        # mode (vedi _schedule_palette_warmup): lì il preload è sicuro per il brush
        # attivo ed è il primo momento in cui le palette servono davvero.
        _schedule_palette_warmup()
        return None
    bpy.app.timers.register(_run, first_interval=1.0)


def register():
    global _warmup_stop
    _warmup_stop = False
    for cls in _all_classes:
        bpy.utils.register_class(cls)

    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon
    if kc:
        km  = kc.keymaps.new(name="Sculpt", space_type="EMPTY")
        kmi = km.keymap_items.new(
            SCULPTOOLS_OT_radial_palette.bl_idname,
            type="BACK_SLASH", value="PRESS")
        _addon_keymaps.append((km, kmi))

        # Palette-cycle keymap item: hosts the native keymap widget (default Tab)
        # AND, since v2.7.1, is ACTIVE — the operator cycles the palettes when the
        # Preview Editor is open and does PASS_THROUGH otherwise, so outside the
        # preview the key keeps its native behaviour. The wheel modal still reads
        # its chord (prefs.get_cycle_key_binding) for the in-wheel cycle.
        kmi_cycle = km.keymap_items.new(
            "sculptools.cycle_palette_holder",
            type="TAB", value="PRESS")
        _addon_keymaps.append((km, kmi_cycle))

        # BACKWARD palette cycle: a twin keymap item Shift+<cycle key>. NOT edited
        # by the user — synced to the forward holder by prefs.sync_cycle_back_binding
        # (type/ctrl/alt/oskey copied, shift forced True, active only if the forward
        # one does not already use Shift). Created on the Shift+Tab default; the sync
        # realigns it as soon as the keyconfig is ready.
        kmi_cycle_back = km.keymap_items.new(
            "sculptools.cycle_palette_back_holder",
            type="TAB", value="PRESS", shift=True)
        _addon_keymaps.append((km, kmi_cycle_back))

        # Dynamic Sliders: plain right-click (PRESS). We override the native
        # RMB context panel here on purpose (see dynamic_sliders.py); a tap is
        # re-forwarded to that panel, a drag drives the sliders. Modified
        # right-clicks are left alone (this item matches plain RMB only). Start
        # active/inactive per the saved preference.
        kmi_ds = km.keymap_items.new(
            SCULPTOOLS_OT_dynamic_sliders.bl_idname,
            type="RIGHTMOUSE", value="PRESS")
        try:
            prefs = bpy.context.preferences.addons[__package__].preferences
            kmi_ds.active = bool(getattr(prefs, "dynamic_sliders_enabled", True))
        except Exception:
            pass
        _addon_keymaps.append((km, kmi_ds))

        # Quick Numbers: one keymap item per number key (1..9 -> slots 1..9,
        # 0 -> slot 10). Start active/inactive per the saved preference.
        try:
            qn_prefs = bpy.context.preferences.addons[__package__].preferences
            qn_active = bool(getattr(qn_prefs, "quick_numbers_enabled", True))
        except Exception:
            qn_active = True
        for idx, key in enumerate(_QN_KEYS):
            kmi_qn = km.keymap_items.new(
                SCULPTOOLS_OT_quick_number.bl_idname,
                type=key, value="PRESS")
            kmi_qn.properties.slot_index = idx
            kmi_qn.active = qn_active
            _addon_keymaps.append((km, kmi_qn))

        # Jump-to-Palette: MODIFIER + number (1..MAX_PALETTES) jumps straight to
        # that palette, GLOBAL in Sculpt Mode. One ACTIVE keymap item per number
        # (default Ctrl+1..8); the shared modifier is chosen from the dropdown
        # prefs.jump_modifier and propagated to the kmis by prefs.sync_jump_bindings.
        # The modifier is what keeps them separate from Quick Numbers (bare numbers).
        for idx in range(MAX_PALETTES):
            kmi_jump = km.keymap_items.new(
                SCULPTOOLS_OT_jump_palette.bl_idname,
                type=_QN_KEYS[idx], value="PRESS", ctrl=True)
            kmi_jump.properties.palette_index = idx
            _addon_keymaps.append((km, kmi_jump))

    bpy.types.VIEW3D_MT_brush_context_menu.append(brush_context_menu)
    bpy.types.UI_MT_button_context_menu.append(toolbar_tool_context_menu)
    if _sculptools_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_sculptools_load_post)
    enable_preview_handler()

    # Run the one-shot palette migration OFF the draw path. ensure_palettes()
    # is lazy and would otherwise first fire from a draw callback (POST_PIXEL or
    # a panel draw) the very first time slots are read — writing to the new
    # PaletteItem during draw is unreliable in Blender (colour writes can be
    # dropped while the palette is still created, which is exactly how a migrated
    # palette can end up with default colours). A deferred timer guarantees the
    # migration happens in a normal (writable) context on a fresh session.
    def _ensure_palettes_startup():
        try:
            from .prefs import ensure_palettes
            ensure_palettes(bpy.context)
        except Exception as exc:
            print(f"Sculptools: deferred palette init skipped: {exc}")
        return None
    try:
        bpy.app.timers.register(_ensure_palettes_startup, first_interval=0.5)
    except Exception:
        pass

    # Deferred jump-binding sync: at register() the 8 jump keymap items are
    # freshly created at the default modifier (Ctrl); Blender re-applies the
    # user's saved keyconfig customisations (which may have changed the holder's
    # modifier) only AFTER this. A one-shot timer re-reads the holder once things
    # have settled and propagates its modifier to the 8 items. The panel draw
    # syncs too, so this only matters if the user jumps before ever opening the
    # 'Palette' sidebar tab in a session.
    def _sync_jump_startup():
        try:
            from .prefs import sync_jump_bindings, sync_cycle_back_binding
            sync_jump_bindings(bpy.context)
            sync_cycle_back_binding(bpy.context)
        except Exception as exc:
            print(f"Sculptools: deferred binding sync skipped: {exc}")
        return None
    try:
        bpy.app.timers.register(_sync_jump_startup, first_interval=0.6)
    except Exception:
        pass

    # Arma il warm-up mode-gated anche qui, per l'enable dell'add-on a sessione già
    # avviata (nessun load_post in quel caso). Se sei già in Sculpt mode scalda a
    # breve; altrimenti resta in attesa dell'ingresso in sculpt.
    _schedule_palette_warmup()


def unregister():
    global _warmup_stop
    _warmup_stop = True   # ferma il timer di warm-up mode-gated se in attesa
    if _sculptools_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_sculptools_load_post)
    disable_preview_handler()
    stop_preview_queue()
    clear_texture_cache()
    bpy.types.VIEW3D_MT_brush_context_menu.remove(brush_context_menu)
    bpy.types.UI_MT_button_context_menu.remove(toolbar_tool_context_menu)
    for km, kmi in _addon_keymaps:
        km.keymap_items.remove(kmi)
    _addon_keymaps.clear()
    for cls in reversed(_all_classes):
        bpy.utils.unregister_class(cls)
