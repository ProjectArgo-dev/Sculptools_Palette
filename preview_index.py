# sculptools_palette/preview_index.py
"""Persistent index of where custom-library brush artwork lives.

Why this exists (GitHub issue #3). Resolving a brush that is not one of
Blender's Essentials means looking through the user's Asset Libraries, and the
only way to know whether a .blend holds a given brush is to open it. With a
large library that is brutal: a reporter profiled 2909 .blend files costing
11.1 s of an 11.3 s startup — and 2908 of them contained no brushes at all,
being ordinary models and materials. Worse, the add-on re-learned that from
scratch on every single launch.

So the index remembers two things across sessions:

  found  — which file each brush was located in, so the next lookup opens that
           one file instead of walking the library;
  empty  — which files were opened and turned out to hold NO brushes whatsoever,
           so they are never opened again while they stay unchanged.

"empty" deliberately means "zero brush assets in this file", never "none of the
brushes I happened to ask for" — the latter would make a later search for a
different brush skip a file that does contain it.

Pure logic: no bpy, no file I/O. The caller injects `stamp_of`, so this module
can be exercised by the validation stubs. Every entry is re-validated on load,
because the file on disk is user-writable and may be stale, truncated or edited.
"""

SCHEMA = 1


def new_index():
    """An empty, valid index."""
    return {"schema": SCHEMA, "found": {}, "empty": {}}


def validate(data):
    """Return a sane index from arbitrary parsed JSON, keeping whatever entries
    are well formed and dropping the rest. Never raises: a corrupt cache must
    cost a rescan, never a broken add-on."""
    index = new_index()
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        return index
    found = data.get("found")
    if isinstance(found, dict):
        for name, rec in found.items():
            if (isinstance(name, str) and isinstance(rec, (list, tuple))
                    and len(rec) == 3
                    and all(isinstance(x, str) for x in rec)):
                index["found"][name] = [rec[0], rec[1], rec[2]]
    empty = data.get("empty")
    if isinstance(empty, dict):
        for path, stamp in empty.items():
            if (isinstance(path, str) and isinstance(stamp, (list, tuple))
                    and len(stamp) == 2
                    and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                            for v in stamp)):
                index["empty"][path] = [float(stamp[0]), int(stamp[1])]
    return index


def known_source(index, asset_name):
    """(library_name, relative_asset_identifier, blend_path) for *asset_name*,
    or None if the index has never located it."""
    rec = (index.get("found") or {}).get(asset_name)
    if isinstance(rec, (list, tuple)) and len(rec) == 3:
        return (rec[0], rec[1], rec[2])
    return None


def record_found(index, asset_name, lib_name, rel_id, blend_path):
    """Remember that *asset_name* lives in *blend_path*."""
    index.setdefault("found", {})[asset_name] = [lib_name, rel_id, blend_path]
    # A file that yields a brush is by definition not one of the empty ones.
    index.setdefault("empty", {}).pop(blend_path, None)


def record_empty(index, blend_path, stamp):
    """Remember that *blend_path* holds no brush assets at all, as of *stamp*
    (an (mtime, size) pair). A stamp of None is not recorded: without one there
    is no way to notice the file changing later, and silently skipping a file
    forever is worse than reopening it."""
    if stamp is None:
        return
    try:
        index.setdefault("empty", {})[blend_path] = [float(stamp[0]), int(stamp[1])]
    except (TypeError, ValueError, IndexError):
        pass


def _same_stamp(recorded, stamp):
    if recorded is None or stamp is None:
        return False
    try:
        return (float(recorded[0]) == float(stamp[0])
                and int(recorded[1]) == int(stamp[1]))
    except (TypeError, ValueError, IndexError):
        return False


def plan_scan(index, remaining, entries, stamp_of):
    """Order the (library_name, library_root, blend_path) entries worth opening
    in order to resolve the asset names in *remaining*.

    Files the index has already located one of those names in come first, then
    the rest of the walk, minus any file recorded as holding no brushes whose
    stamp still matches. A file that cannot be stamped is never skipped: a false
    skip hides a brush that is really there, which is far worse than an
    unnecessary open.

    The known files being FIRST is what makes this fast, and it is deliberately
    the only mechanism: callers stop as soon as nothing is left to resolve, so
    the common case opens exactly one file and never touches the tail. Truncating
    the plan instead — returning only the known files — would be the same speed
    and quietly wrong, because a brush the user has since moved to a DIFFERENT
    .blend would be declared missing while sitting in the very library we
    stopped walking. The tail costs nothing when the index is right and is the
    only thing that repairs it when it is stale.
    """
    by_path = {}
    for entry in entries:
        by_path.setdefault(entry[2], entry)

    plan = []
    seen = set()
    for name in remaining:
        rec = known_source(index, name)
        entry = by_path.get(rec[2]) if rec is not None else None
        if entry is not None and rec[2] not in seen:
            seen.add(rec[2])
            plan.append(entry)

    empty = index.get("empty") or {}
    for entry in entries:
        path = entry[2]
        if path in seen:
            continue
        if _same_stamp(empty.get(path), stamp_of(path)):
            continue
        seen.add(path)
        plan.append(entry)
    return plan


# No pruning, deliberately. A record whose .blend is gone is inert: a missing
# path never turns up in the library walk, so it can never cause a skip, and it
# costs ~80 bytes. Dropping such records would mean deciding "gone" from a single
# os.path.exists, and asset libraries commonly live on drives that are simply not
# mounted right now — one save while the drive is offline would wipe the whole
# index and force a full rescan. Inert entries are the cheaper mistake.
