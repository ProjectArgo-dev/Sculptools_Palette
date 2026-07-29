# sculptools_palette/presets.py
#
# Pure serialize / validate / sanitize / count logic for the palette-preset
# Import/Export feature. NO bpy calls and NO file I/O here — the operators in
# operators.py read prefs, read/write the file, and delegate to these helpers.
# Importable and fully unit-testable under the validation stubs.

from .prefs import (MAX_SLOTS, NUM_SUBSLOTS, DEFAULT_NUM_SLOTS,
                    NEW_SLOT_COLOUR, NEW_SUB_COLOUR)
from .tools import is_tool_spec, get_tool, tool_available

FORMAT_ID = "sculptools_palette_preset"
SCHEMA_VERSION = 1


def build_preset_dict(palette_dicts, appearance, addon_version, blender_version,
                      hotkeys=None):
    """Assemble the top-level file dict from already-read pieces.

    `hotkeys` is a keyword with a default so the signature stays compatible with
    existing callers and tests. When None the "hotkeys" key is omitted entirely,
    which is exactly what an older add-on reading the file would expect."""
    out = {
        "format": FORMAT_ID,
        "schema": SCHEMA_VERSION,
        "addon_version": addon_version,
        "blender_version": list(blender_version),
        "appearance": dict(appearance),
        "palettes": list(palette_dicts),
    }
    if hotkeys:
        out["hotkeys"] = dict(hotkeys)
    return out


def validate_preset(data):
    """Return (ok, error_message). Structural gate only."""
    if not isinstance(data, dict):
        return False, "File is not a Sculptools palette preset"
    if data.get("format") != FORMAT_ID:
        return False, "Not a Sculptools palette preset file"
    schema = data.get("schema")
    if not isinstance(schema, int):
        return False, "Preset is missing a valid schema version"
    if schema > SCHEMA_VERSION:
        return False, "This preset was made with a newer version of the add-on"
    pals = data.get("palettes")
    if not isinstance(pals, list) or len(pals) == 0:
        return False, "Preset contains no palettes"
    return True, ""


def _coerce_colour(value, default):
    try:
        c = [float(value[0]), float(value[1]), float(value[2])]
        return tuple(c)
    except (TypeError, ValueError, IndexError, KeyError):
        return tuple(default)


def sanitize_palette_dict(raw):
    """Coerce one raw palette entry into the _apply_palette_dict schema. Pad or
    truncate slots to MAX_SLOTS and subs to MAX_SLOTS x NUM_SUBSLOTS, filling
    gaps with ''. Return None only when raw is not a dict, or its "slots"/
    "subs" are missing or not lists — an entry with e.g. empty slots/subs
    lists is still sanitized (into a blank palette), not dropped."""
    if not isinstance(raw, dict):
        return None
    slots_in = raw.get("slots")
    subs_in = raw.get("subs")
    if not isinstance(slots_in, list) or not isinstance(subs_in, list):
        return None

    def _s(v):
        return v if isinstance(v, str) else ""

    slots = [(_s(slots_in[i]) if i < len(slots_in) else "")
             for i in range(MAX_SLOTS)]
    subs = []
    for i in range(MAX_SLOTS):
        row_in = subs_in[i] if i < len(subs_in) and isinstance(subs_in[i], list) else []
        subs.append([(_s(row_in[j]) if j < len(row_in) else "")
                     for j in range(NUM_SUBSLOTS)])

    num = raw.get("num_slots", DEFAULT_NUM_SLOTS)
    if not isinstance(num, int) or not (2 <= num <= MAX_SLOTS):
        num = DEFAULT_NUM_SLOTS

    return {
        "name": str(raw.get("name", "-Palette Name-")),
        "num_slots": num,
        "slots": slots,
        "subs": subs,
        "slot_colour": _coerce_colour(raw.get("slot_colour"), NEW_SLOT_COLOUR),
        "sub_colour": _coerce_colour(raw.get("sub_colour"), NEW_SUB_COLOUR),
    }


def sanitize_appearance(raw, known_keys, enum_choices=None):
    """Keep only recognised keys with numeric/bool values; drop the rest. The
    operator setattrs the result onto prefs (Blender clamps ranges).

    `enum_choices` maps a key to the tuple of identifiers its EnumProperty
    accepts. Those keys take a STRING instead, and only when it is one of the
    listed identifiers — setattr with an unknown enum id raises, so an edited or
    corrupted file must not reach prefs."""
    out = {}
    if not isinstance(raw, dict):
        return out
    enum_choices = enum_choices or {}
    for k in known_keys:
        if k not in raw:
            continue
        v = raw[k]
        if k in enum_choices:
            if isinstance(v, str) and v in enum_choices[k]:
                out[k] = v
        elif isinstance(v, (int, float, bool)):
            out[k] = v
    return out


# The two hotkeys a preset can carry. Kept in their own top-level block rather
# than inside "appearance" for two reasons: a chord is a free-form string that
# needs parse_chord validation (sanitize_appearance only takes numbers, bools and
# declared enum identifiers), and hotkeys are the ONLY preset data applied
# conditionally — the import operator's "Import hotkeys" checkbox.
HOTKEY_KEYS = ("open", "cycle")


def sanitize_hotkeys(raw):
    """Keep only recognised hotkey entries whose value is a readable chord, and
    return them re-encoded in canonical form. Anything else — a non-dict, an
    unknown key, a non-string, an unparseable chord — is dropped silently, so a
    corrupt or hand-edited file can never reach the keymap. Pure; no bpy."""
    from .prefs import parse_chord, format_chord
    out = {}
    if not isinstance(raw, dict):
        return out
    for key in HOTKEY_KEYS:
        chord = parse_chord(raw.get(key))
        if chord is not None:
            out[key] = format_chord(chord)
    return out


def entry_is_available(entry, available_brush_names, blender_version):
    """One slot/sub string. '' -> None (not counted). Tool spec -> resolvable +
    version-available. Brush name -> present in the available set."""
    if not entry:
        return None
    if is_tool_spec(entry):
        te = get_tool(entry)
        return te is not None and tool_available(te, blender_version)
    return entry in available_brush_names


def count_available_entries(palette_dicts, available_brush_names, blender_version):
    """Walk every non-empty slot & sub across all palettes. Return (found, total)."""
    found = total = 0
    for p in palette_dicts:
        entries = list(p.get("slots", []))
        for row in p.get("subs", []):
            entries.extend(row)
        for e in entries:
            avail = entry_is_available(e, available_brush_names, blender_version)
            if avail is None:
                continue
            total += 1
            if avail:
                found += 1
    return found, total


def build_import_plan(data, max_palettes, known_appearance_keys,
                      enum_choices=None):
    """From a preset dict (validate_preset assumed already passed), produce the
    ready-to-apply import plan: (sanitized_palettes, appearance, skipped, clamped).

    - sanitized_palettes: each raw entry through sanitize_palette_dict, dropping
      the unusable ones, then truncated to max_palettes.
    - appearance: sanitize_appearance over the recognised keys.
    - skipped: count of malformed entries dropped by sanitize_palette_dict.
    - clamped: count of entries removed by the max_palettes truncation.

    Pure — no bpy, no I/O. The caller does the atomic swap and decides what an
    empty sanitized list means (CANCELLED)."""
    sanitized, skipped = [], 0
    for raw in data.get("palettes", []):
        s = sanitize_palette_dict(raw)
        if s is None:
            skipped += 1
        else:
            sanitized.append(s)
    clamped = 0
    if len(sanitized) > max_palettes:
        clamped = len(sanitized) - max_palettes
        sanitized = sanitized[:max_palettes]
    appearance = sanitize_appearance(data.get("appearance", {}),
                                     known_appearance_keys, enum_choices)
    return sanitized, appearance, skipped, clamped
