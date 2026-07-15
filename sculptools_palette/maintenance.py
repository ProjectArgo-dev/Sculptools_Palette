# sculptools_palette/maintenance.py
#
# Palette hygiene: drop slot/sub-slot assignments whose brush can no longer be
# resolved — e.g. after the user removes the custom asset library the brush came
# from. Runs (deferred) on file load. Clearing an assignment is what makes the
# sub-slot go invisible again and the main slot fall back to showing its number.
#
# SAFETY: this deletes stored assignments, so it is deliberately conservative.
# The footgun we guard against is an *unplugged drive*: if a custom library
# lives on an external/network volume that isn't mounted right now, its brushes
# look unresolvable but aren't really gone — wiping the palette in that case
# would be nasty. So while any configured library sits on an *offline volume* we
# do nothing.
#
# Crucially we check the drive/mount ROOT, not the folder. A library whose
# folder is simply missing while its drive exists (e.g. Blender's default
# "User Library" at C:\Users\...\Documents\Blender\Assets, a path the user never
# created) is NOT offline — it's deleted/never-created, and we must be free to
# prune around it. Only a missing drive root (F:\ unplugged, \\server down)
# counts as offline. Getting this wrong is exactly what previously blocked all
# pruning forever, because that default library folder rarely exists.

import os
import bpy


def _drive_is_available(path):
    """True unless the volume/mount `path` lives on is currently unreachable.
    A missing *folder* on a present drive returns True (not offline); only a
    missing drive/mount ROOT returns False."""
    if not path:
        return True
    try:
        drive, _ = os.path.splitdrive(os.path.abspath(path))
    except Exception:
        return True
    if not drive:
        return True
    root = drive + os.sep
    return os.path.exists(root)


def _offline_library_present():
    """True if any configured asset library lives on a drive/mount that is
    currently unavailable. While that holds, prune_orphaned_brushes refuses to
    touch anything (a brush may just be waiting on that volume to come back)."""
    try:
        libs = bpy.context.preferences.filepaths.asset_libraries
    except Exception:
        return False
    for lib in libs:
        root = getattr(lib, "path", "") or ""
        if root and not _drive_is_available(root):
            return True
    return False


def _is_essentials(name):
    from .brushes import BRUSHES
    for display, bpy_data_name, asset_name, _icon in BRUSHES:
        if name in (display, bpy_data_name, asset_name):
            return True
    return False


def _is_resolvable(name):
    """A brush name is resolvable if it is a live datablock, one of Blender's
    Essentials, or found in a currently-configured custom asset library. A tool
    spec ('tool:<key>') is ALWAYS kept — it is not a brush and must survive a
    file reload (pruning here was silently wiping tool assignments on open)."""
    from .tools import is_tool_spec
    if is_tool_spec(name):
        return True
    if bpy.data.brushes.get(name) is not None:
        return True
    if _is_essentials(name):
        return True
    from .gpu_draw import resolve_asset_source
    return resolve_asset_source(name) is not None


def prune_orphaned_brushes(context):
    """Clear palette assignments whose brush can't be resolved. Returns the
    number cleared. No-ops (returns 0) when a library is on an offline drive."""
    from .prefs import (get_slot, get_sub, set_slot, set_sub,
                        NUM_SUBSLOTS, MAX_SLOTS)
    from .tools import is_tool_spec

    if _offline_library_present():
        return 0

    # One batched custom-library scan for all candidate names (not live, not
    # Essentials), so each name isn't scanned against every .blend separately.
    candidates = set()
    for i in range(MAX_SLOTS):
        names = [get_slot(context, i)] + [get_sub(context, i, j)
                                          for j in range(NUM_SUBSLOTS)]
        for name in names:
            if (name and not is_tool_spec(name)
                    and bpy.data.brushes.get(name) is None
                    and not _is_essentials(name)):
                candidates.add(name)
    if candidates:
        try:
            from .gpu_draw import _load_custom_previews
            _load_custom_previews(candidates)
        except Exception:
            pass

    cleared = 0
    for i in range(MAX_SLOTS):
        s = get_slot(context, i)
        if s and not _is_resolvable(s):
            set_slot(context, i, "")
            cleared += 1
        for j in range(NUM_SUBSLOTS):
            sub = get_sub(context, i, j)
            if sub and not _is_resolvable(sub):
                set_sub(context, i, j, "")
                cleared += 1

    if cleared:
        print(f"Sculptools: removed {cleared} orphaned brush assignment(s) "
              f"(source library no longer available)")
    return cleared
