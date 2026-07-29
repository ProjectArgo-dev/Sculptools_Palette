# sculptools_palette/__init__.py

# NB: no `bl_info`. Since v2.7.0 the add-on ships as an EXTENSION (Blender 4.5+):
# all metadata (name, version, min Blender, license, tags) lives in
# `blender_manifest.toml`, which Blender reads instead of bl_info.

import bpy
persistent = bpy.app.handlers.persistent
from .prefs    import (SculptoolsPreferences, PaletteItem, MAX_PALETTES,
                       DEFAULT_HOTKEY_CHORDS, chord_kmi_kwargs,
                       cycle_back_binding)
from .operators import (all_operator_classes, brush_context_menu,
                       toolbar_tool_context_menu,
                       SCULPTOOLS_OT_jump_palette)
from .modal    import SCULPTOOLS_OT_radial_palette
from .dynamic_sliders import (SCULPTOOLS_OT_dynamic_sliders,
                              all_dynamic_slider_classes,
                              _disable_overlay as _disable_slider_overlay)
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

# Mode-gated palette warm-up: preloads the previews of ALL palettes (not just the
# active one) so switching/jumping/cycling has no pop-in. It MUST run in Sculpt
# mode: the Essentials preload links a library, which transiently unsets the
# active sculpt brush, and restoring it only succeeds in Sculpt mode (on Blender
# 5.x `tool_settings.sculpt.brush` is READ-ONLY, so it can only be re-activated
# through an operator, which requires sculpt mode). Outside Sculpt mode the wheel
# cannot even open, so warming up there is both pointless and dangerous (it would
# clear the brush). `_warmup_poll_active` prevents stacked timers; `_warmup_stop`
# stops it on unregister.
_warmup_poll_active = False
_warmup_stop        = False


def _schedule_palette_warmup():
    """Arm a light timer that, as soon as the context is in Sculpt mode, warms up
    every palette's previews once and then disarms itself. Until sculpt mode is
    entered (or forever, if it never is) it only costs a ~1s no-op check.
    Idempotent on the queue side (warm_palette_previews deduplicates through
    _preview_requested)."""
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
                return 1.0  # not in sculpt yet — re-check in 1s
            from .prefs import iter_all_assigned_brush_names
            from .gpu_draw import warm_palette_previews
            warm_palette_previews(iter_all_assigned_brush_names(bpy.context))
        except Exception as exc:
            print(f"Sculptools: palette preview warm-up skipped: {exc}")
        _warmup_poll_active = False
        return None  # done (or errored) — disarm the timer

    try:
        bpy.app.timers.register(_tick, first_interval=1.0)
    except Exception:
        _warmup_poll_active = False


@persistent
def _sculptools_load_post(_dummy):
    """On file load, warm the palette thumbnails.

    It does NOT prune unresolvable assignments any more (2026-07-21, with the
    whole maintenance.py module removed): a library folder that merely moved is
    indistinguishable from one that is gone, so the automatic prune silently
    emptied palettes in that case. An unresolvable slot now renders as
    "not found" while KEEPING its stored name, so it stays visible, heals itself
    when the library comes back, and the user can reassign it by hand."""
    def _run():
        # Warm up ALL palettes, deferred until Sculpt mode is entered (see
        # _schedule_palette_warmup): there the preload is safe for the active
        # brush, and it is the first moment the palettes are actually needed.
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
        # The two editable hotkeys are created from prefs.DEFAULT_HOTKEY_CHORDS,
        # not from literals: "Reset Hotkeys" restores the very same values, and a
        # second copy of them here would eventually drift out of sync.
        kmi = km.keymap_items.new(
            SCULPTOOLS_OT_radial_palette.bl_idname, value="PRESS",
            **chord_kmi_kwargs(DEFAULT_HOTKEY_CHORDS["open_key_chord"]))
        _addon_keymaps.append((km, kmi))

        # Palette-cycle keymap item: hosts the native keymap widget (default Tab)
        # AND, since v2.7.1, is ACTIVE — the operator cycles the palettes when the
        # Preview Editor is open and does PASS_THROUGH otherwise, so outside the
        # preview the key keeps its native behaviour. The wheel modal still reads
        # its chord (prefs.get_cycle_key_binding) for the in-wheel cycle.
        kmi_cycle = km.keymap_items.new(
            "sculptools.cycle_palette_holder", value="PRESS",
            **chord_kmi_kwargs(DEFAULT_HOTKEY_CHORDS["cycle_key_chord"]))
        _addon_keymaps.append((km, kmi_cycle))

        # BACKWARD palette cycle: a twin keymap item Shift+<cycle key>. NOT edited
        # by the user — synced to the forward holder by prefs.sync_cycle_back_binding
        # (type/ctrl/alt/oskey copied, shift forced True, active only if the forward
        # one does not already use Shift). Created on the Shift+Tab default; the sync
        # realigns it as soon as the keyconfig is ready.
        # Derived from the forward chord (same helper the sync uses), so there is
        # no third copy of the default key either. [:5] drops the trailing
        # `active` flag that cycle_back_binding returns.
        kmi_cycle_back = km.keymap_items.new(
            "sculptools.cycle_palette_back_holder", value="PRESS",
            **chord_kmi_kwargs(
                cycle_back_binding(DEFAULT_HOTKEY_CHORDS["cycle_key_chord"])[:5]))
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
            from .prefs import ensure_palettes, migrate_settings
            ensure_palettes(bpy.context)
            # Same writable, off-draw context: bring the settings layout up to
            # date and stamp it (see prefs.SETTINGS_SCHEMA).
            migrate_settings(bpy.context)
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
    # have settled and propagates its modifier to the 8 items. Together with the
    # jump_modifier dropdown's own update callback this is now the ONLY place the
    # jump items are synced — the panel draw used to do it too, until that was
    # removed for mutating a keymap item next to a live capture widget.
    #
    # It also restores the two persisted hotkey chords (prefs.open_key_chord /
    # cycle_key_chord) for the same timing reason: Blender re-applies saved
    # keyconfig customisations after register() returns, so writing the keymap
    # here — rather than in register()'s body — is what makes the restore stick.
    def _sync_jump_startup():
        try:
            from .prefs import (sync_jump_bindings, sync_cycle_back_binding,
                                apply_stored_bindings)
            # ORDER MATTERS. Restore the user's customised Open/Cycle chords FIRST:
            # sync_cycle_back_binding derives the Shift+<cycle key> item from the
            # forward cycle chord, so if it ran first it would derive from the
            # default TAB that the keymap_items.new() call above just created, and
            # backward cycling would be bound to the wrong key all session.
            apply_stored_bindings(bpy.context)
            sync_jump_bindings(bpy.context)
            sync_cycle_back_binding(bpy.context)
        except Exception as exc:
            print(f"Sculptools: deferred binding sync skipped: {exc}")
        return None
    try:
        bpy.app.timers.register(_sync_jump_startup, first_interval=0.6)
    except Exception:
        pass

    # Arm the mode-gated warm-up here too, to cover enabling the add-on in an
    # already-running session (no load_post fires in that case). If Sculpt mode is
    # already active it warms up shortly; otherwise it waits for sculpt mode.
    _schedule_palette_warmup()


def unregister():
    global _warmup_stop
    _warmup_stop = True   # stop the mode-gated warm-up timer if it is waiting
    if _sculptools_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_sculptools_load_post)
    disable_preview_handler()
    # The Dynamic Sliders value overlay is a SECOND draw handler, added on its
    # modal's invoke and removed on its _finish. If the add-on is unregistered
    # while a right-drag is still in flight (a reload during development is the
    # realistic case), _finish never runs and the handler survives, pointing at a
    # module that is being torn down — Blender then errors on every redraw.
    _disable_slider_overlay()
    stop_preview_queue()
    clear_texture_cache()
    bpy.types.VIEW3D_MT_brush_context_menu.remove(brush_context_menu)
    bpy.types.UI_MT_button_context_menu.remove(toolbar_tool_context_menu)
    # Each removal is guarded: an already-freed keymap item (a keyconfig reset, a
    # half-finished earlier unregister) raises, and an exception escaping here used
    # to abort the rest of unregister — leaving the add-on half-torn-down (handlers
    # gone, classes still registered) and needing a Blender restart to recover.
    for km, kmi in _addon_keymaps:
        try:
            km.keymap_items.remove(kmi)
        except Exception:
            pass
    _addon_keymaps.clear()
    for cls in reversed(_all_classes):
        bpy.utils.unregister_class(cls)
