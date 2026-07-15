# sculptools_palette/quick_numbers.py
#
# "Quick Numbers": press a number key (1..9, 0) in Sculpt Mode to activate a
# slot's brush WITHOUT opening the wheel — complementary to the flick shortcut.
# Repeating the SAME key within a short window cycles through that slot's
# assigned brushes: main -> Sub 1 -> Sub 2 -> Sub 3 -> (wrap), visiting the
# sub-slots in prefs.SUB_CYCLE_ORDER (the two side subs first, then the
# collinear/outward one LAST). This lets you group similar brushes under one
# key instead of spending a separate hotkey on each. Example: tap "1" for Grab
# (slot 1 main), again for Elastic Grab (Sub 1), again for Elastic Snake Hook
# (Sub 2), again for Grab Silhouette (Sub 3, the outward sub).
#
# Key -> slot: 1..9 -> slots 1..9, 0 -> slot 10. Keys past the active slot
# count (num_slots) are passed through untouched.

import time
from bpy.types import Operator
from bpy.props import IntProperty

from .prefs import (get_prefs, get_num_slots, get_slot, get_sub,
                    NUM_SUBSLOTS, SUB_CYCLE_ORDER)
from .tools import is_oneshot

QUICK_NUMBER_WINDOW = 0.6   # seconds within which a same-key repeat keeps cycling

# 0-based slot index -> keyboard key type. Index 9 (slot 10) is the '0' key.
_QN_KEYS = ["ONE", "TWO", "THREE", "FOUR", "FIVE",
            "SIX", "SEVEN", "EIGHT", "NINE", "ZERO"]

# Cross-invocation cycle state: which slot was last quick-selected, at which
# position in its group, and when — so a fast repeat advances and a slow one
# restarts from the main brush.
_qn_state = {'slot': None, 'index': 0, 'time': 0.0}


# ── pure logic (unit-tested in run_functional_tests.py) ───────────────────────

def _slot_group(main, sub0, sub1, sub2):
    """Ordered list of the ASSIGNED entries for one slot: the main first, then the
    sub-slots in SUB_CYCLE_ORDER (= (2, 0, 1) for 3 subs). Empty targets are
    skipped, AND one-shot tool actions are skipped so repeating the key can never
    fire a destructive op (e.g. Clear Mask) mid-cycle — one-shots are reachable
    only by a deliberate wheel flick. Interactive tools stay (arming is safe)."""
    subs = (sub0, sub1, sub2)
    ordered = [main] + [subs[k] for k in SUB_CYCLE_ORDER]
    return [n for n in ordered if n and not is_oneshot(n)]


def _cycle_index(same_key, last_index, group_len):
    """Next position in a slot's group: advance when the same key was pressed
    within the window (`same_key`), otherwise restart at the main brush (0)."""
    if group_len <= 0:
        return 0
    return (last_index + 1) % group_len if same_key else 0


# ── operator ──────────────────────────────────────────────────────────────────

class SCULPTOOLS_OT_quick_number(Operator):
    bl_idname  = "sculptools.quick_number"
    bl_label   = "Sculptools Quick Number"
    bl_options = {'REGISTER'}

    slot_index: IntProperty(default=0)  # type: ignore  # 0-based (key 1 -> 0)

    @classmethod
    def poll(cls, context):
        return context.mode == 'SCULPT'

    def invoke(self, context, event):
        prefs = get_prefs(context)
        if not getattr(prefs, 'quick_numbers_enabled', True):
            return {'PASS_THROUGH'}

        slot = self.slot_index
        if slot < 0 or slot >= get_num_slots(context):
            # Key beyond the active slot count → leave it to Blender.
            return {'PASS_THROUGH'}

        group = _slot_group(
            get_slot(context, slot),
            get_sub(context, slot, 0),
            get_sub(context, slot, 1) if NUM_SUBSLOTS > 1 else "",
            get_sub(context, slot, 2) if NUM_SUBSLOTS > 2 else "",
        )
        if not group:
            # Nothing assigned to this slot → don't swallow the key.
            return {'PASS_THROUGH'}

        now      = time.time()
        same_key = (_qn_state['slot'] == slot and
                    (now - _qn_state['time']) < QUICK_NUMBER_WINDOW)
        index    = _cycle_index(same_key, _qn_state['index'], len(group))

        name = group[index]
        from .modal import _activate_slot
        _activate_slot(name)

        _qn_state['slot']  = slot
        _qn_state['index'] = index
        _qn_state['time']  = now

        self.report({'INFO'}, f"Sculptools: '{name}' (slot {slot + 1})")
        return {'FINISHED'}


all_quick_number_classes = [SCULPTOOLS_OT_quick_number]
