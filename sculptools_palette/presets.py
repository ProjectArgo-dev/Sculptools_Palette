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


def build_preset_dict(palette_dicts, appearance, addon_version, blender_version):
    """Assemble the top-level file dict from already-read pieces."""
    return {
        "format": FORMAT_ID,
        "schema": SCHEMA_VERSION,
        "addon_version": addon_version,
        "blender_version": list(blender_version),
        "appearance": dict(appearance),
        "palettes": list(palette_dicts),
    }


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


def sanitize_appearance(raw, known_keys):
    """Keep only recognised appearance keys with float/bool values; drop the
    rest. The operator setattrs the result onto prefs (Blender clamps ranges)."""
    out = {}
    if not isinstance(raw, dict):
        return out
    for k in known_keys:
        if k in raw and isinstance(raw[k], (int, float, bool)):
            out[k] = raw[k]
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
