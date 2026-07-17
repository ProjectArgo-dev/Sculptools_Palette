# sculptools_palette/gpu_draw.py

import bpy
import os
import math
import time
import zlib
import blf
import gpu
from gpu_extras.batch import batch_for_shader

# numpy ships with Blender; used for the CPU-side circular alpha mask that
# gives thumbnails a round crop (see _build_texture). Guarded so the addon
# still loads — falling back to an un-masked square thumbnail — in the
# extremely unlikely case it is unavailable.
try:
    import numpy as _np
except Exception:
    _np = None

# ── colours ───────────────────────────────────────────────────────────────────
C_BG         = (0.12, 0.12, 0.12, 0.88)
C_BG_HOVER   = (0.20, 0.20, 0.20, 0.96)
C_RING_HOVER = (0.90, 0.55, 0.10, 1.00)
C_RING_EMPTY = (0.22, 0.22, 0.22, 0.55)
C_TEXT       = (1.00, 1.00, 1.00, 1.00)
C_TEXT_EMPTY = (0.38, 0.38, 0.38, 1.00)
C_SPOKE      = (0.28, 0.28, 0.28, 0.35)
C_CENTER     = (0.30, 0.30, 0.30, 0.50)

# Resting outline (Fixed Slot Outline OFF, element NOT hovered): a thin neutral
# 1px grey (#808080) ring. Fixed by design — not user-configurable.
RESTING_OUTLINE_COLOUR = (0.5, 0.5, 0.5)
RESTING_OUTLINE_WIDTH  = 1.0
C_SUB_RIM    = (0.50, 0.50, 0.50, 1.00)
C_DIM        = (0.00, 0.00, 0.00, 0.52)

# Created at import time in a GUI session. In `blender --background`, shader
# creation is NOT available (SystemError) and without this guard the module import
# — and therefore the registration of the whole add-on — would fail headless
# (render farm, batch scripts, validate/build from the CLI). With the guard they
# stay None: harmless, because the draw callbacks never run in background.
try:
    UNIFORM = gpu.shader.from_builtin('UNIFORM_COLOR')
    # Per-vertex colour shader, used only for the soft radial hover glow
    # (_draw_radial_glow). Built-in — same Vulkan-safe class as UNIFORM_COLOR.
    SMOOTH  = gpu.shader.from_builtin('SMOOTH_COLOR')
except SystemError as _exc:
    print(f"Sculptools: GPU shaders unavailable (background mode?): {_exc}")
    UNIFORM = None
    SMOOTH  = None

# ── thumbnail shader ───────────────────────────────────────────────────────────
# Uses Blender's own built-in 'IMAGE_COLOR' shader (attributes: pos, texCoord;
# uniforms: image, color) instead of a hand-written GPUShaderCreateInfo shader.
# Two earlier custom-shader attempts caused real problems: raw GLSL source
# creation (gpu.types.GPUShader(vert, frag)) silently fails to compile under
# the Vulkan backend, and even after switching to GPUShaderCreateInfo, brush
# thumbnails rendered as flat grey — that turned out to be an unrelated
# generation-pipeline issue (see _load_previews_from_file below), but using the
# built-in here still removes an entire class of custom-shader risk.
#
# The thumbnail is now given a round crop by baking a circular alpha mask
# into the texture's pixels on the CPU (see _build_texture) — NOT with a
# stencil buffer. An earlier stencil-based circular clip was tried and
# reverted because manipulating raw stencil/colour-mask GPU state inside a
# POST_PIXEL draw handler corrupted the rest of the viewport. Masking the
# pixel buffer instead touches no framebuffer state at all, so it is both
# round AND safe.
_IMAGE_SHADER = None


def _get_image_shader():
    global _IMAGE_SHADER
    if _IMAGE_SHADER is None:
        try:
            _IMAGE_SHADER = gpu.shader.from_builtin('IMAGE_COLOR')
        except Exception as e:
            print(f"Sculptools: builtin shader error: {e}")
    return _IMAGE_SHADER


# ── bundled thumbnail loader ───────────────────────────────────────────────────
# bpy.ops.ed.lib_id_generate_preview() renders a *generic* placeholder-style
# preview for Brush IDs — a plain flat-shaded sphere render — not Blender's
# actual curated, hand-styled brush-stroke artwork. That generic render is
# what was producing the flat grey squares even once "generation" reported
# as finished: the pipeline was working exactly as designed, it just wasn't
# asking for the right thing. The real artwork is authored once and saved
# directly inside the shipped Essentials .blend file as that ID's own
# .preview — this reads it from there directly, bypassing the render job
# (and its generic result) entirely.
_ESSENTIALS_BLEND_PATH = None
_bundled_preview_cache: dict = {}   # asset_name → (w, h, raw_floats) | None
_bundled_preload_done  = False     # whole Essentials set loaded once already?
# Where a custom-library brush's asset lives, so the modal can ACTIVATE it (not
# just show its icon): brush name → (asset_library_identifier, relative_id).
# Recorded during the custom-library preview scan (_load_custom_previews).
_asset_source: dict = {}
_custom_scan_active = False   # re-entrancy guard for _load_custom_previews


def _get_essentials_blend_path():
    global _ESSENTIALS_BLEND_PATH
    if _ESSENTIALS_BLEND_PATH is None:
        try:
            base = bpy.utils.system_resource('DATAFILES', path="assets")
            _ESSENTIALS_BLEND_PATH = os.path.join(
                base, "brushes", "essentials_brushes-mesh_sculpt.blend")
        except Exception:
            _ESSENTIALS_BLEND_PATH = ""
    return _ESSENTIALS_BLEND_PATH


def _asset_name_for_brush(brush_name):
    try:
        from .brushes import BRUSHES
    except Exception:
        return brush_name
    for display, bpy_data_name, asset_name, _icon in BRUSHES:
        if brush_name in (display, bpy_data_name, asset_name):
            return asset_name
    return brush_name


def _snapshot_active_sculpt_brush():
    """Return the name of the current active sculpt brush (or None). Used to
    put it back if a library link/unlink knocks it loose (see below)."""
    try:
        sc = bpy.context.scene.tool_settings.sculpt
        return sc.brush.name if (sc and sc.brush) else None
    except Exception:
        return None


def _restore_active_sculpt_brush(name):
    """Re-activate *name* iff the active sculpt brush was lost. Linking the
    Essentials library to read previews can deactivate the currently active
    brush (the sculpt cursor then vanishes and the user has to re-pick the
    brush — handoff §6.5). Reading it back and re-activating only when it
    actually went missing makes that invisible."""
    if not name:
        return
    try:
        sc = bpy.context.scene.tool_settings.sculpt
    except Exception:
        sc = None
    if sc is None or sc.brush is not None:
        return  # still active — nothing to restore
    try:
        from .modal import _activate_brush
        _activate_brush(name)
    except Exception as exc:
        print(f"Sculptools: could not restore active brush '{name}': {exc}")


def _extract_preview_pixels(brush):
    """Copy a brush's baked-in preview into (w, h, raw_floats), or None if it
    has no usable (non-transparent) image/icon preview. Prefers the full
    "image" preview (Asset Browser thumbnail) over the small "icon". Shared by
    the Essentials loader and the custom asset-library loader."""
    prev = getattr(brush, "preview", None) if brush else None
    if not prev:
        return None
    try:
        w, h = prev.image_size
        attr = 'image_pixels_float'
        if w <= 0 or h <= 0:
            w, h = prev.icon_size
            attr = 'icon_pixels_float'
        if w <= 0 or h <= 0:
            return None
        raw = list(getattr(prev, attr))
    except Exception:
        return None
    if len(raw) >= w * h * 4 and any(a > 0.01 for a in raw[3::4]):
        return (w, h, raw)
    return None


def _remove_linked_library(path):
    """Remove the linked library whose filepath resolves to *path* (and, with
    it, every ID linked from it), so nothing accumulates and a later link is
    clean instead of warning 'already linked'."""
    try:
        target = os.path.normpath(path)
        for candidate in list(bpy.data.libraries):
            try:
                if os.path.normpath(bpy.path.abspath(candidate.filepath)) == target:
                    bpy.data.libraries.remove(candidate)
                    return
            except Exception:
                pass
    except Exception:
        pass


def _load_previews_from_file(path, names):
    """Link the requested brush *names* from a single .blend, copy out each
    brush's baked preview into _bundled_preview_cache, then remove the linked
    library and restore the active sculpt brush if the link dropped it. Returns
    the set of names actually found+cached in this file. Off-draw only (I/O).

    *names* may be None → load EVERY brush present in the file (used to preload
    all Essentials brushes, catalogued or not — see preload_bundled_previews)."""
    found = set()
    if not (path and os.path.exists(path)):
        return found
    active_snapshot = _snapshot_active_sculpt_brush()
    try:
        with bpy.data.libraries.load(path, link=True, assets_only=True) as (data_from, data_to):
            present = (list(data_from.brushes) if names is None
                       else [n for n in names if n in data_from.brushes])
            data_to.brushes = present
        for brush in (data_to.brushes or []):
            if brush is None:
                continue
            _bundled_preview_cache[brush.name] = _extract_preview_pixels(brush)
            found.add(brush.name)
    except Exception as exc:
        print(f"Sculptools: preview batch load error ({path}): {exc}")
    finally:
        _remove_linked_library(path)
        _restore_active_sculpt_brush(active_snapshot)
    return found


def _iter_asset_library_blend_files():
    """Yield (library_name, library_root, blend_path) for every .blend file
    under the user's configured Asset Libraries (Preferences → File Paths →
    Asset Libraries), de-duplicated. Used both to read a custom brush's curated
    preview AND to record where its asset lives so the modal can activate it."""
    try:
        libs = bpy.context.preferences.filepaths.asset_libraries
    except Exception:
        return
    seen = set()
    for lib in libs:
        root = getattr(lib, "path", "") or ""
        name = getattr(lib, "name", "") or ""
        try:
            if not root or not os.path.isdir(root):
                continue
            for dirpath, _dirs, files in os.walk(root):
                for f in files:
                    if f.lower().endswith(".blend"):
                        p = os.path.join(dirpath, f)
                        if p not in seen:
                            seen.add(p)
                            yield name, root, p
        except Exception:
            continue


def _load_custom_previews(names):
    """Generalise the Essentials fast path to ANY custom brush library: for the
    given brush *names* not already cached, scan the .blend files under the
    configured Asset Libraries, link each in turn, copy out the brush's baked
    preview into _bundled_preview_cache, and record each brush's activation
    source (library + relative asset identifier) in _asset_source. Stops once
    all names are found. Off-draw only (file I/O); runs via the timer."""
    global _custom_scan_active
    if _custom_scan_active:
        # Re-entrant call — e.g. the active-brush restore inside a link cycle
        # asked to resolve a custom source mid-scan. Don't recurse.
        return
    remaining = {n for n in names if n not in _bundled_preview_cache}
    if not remaining:
        return
    _custom_scan_active = True
    try:
        for lib_name, lib_root, blend in _iter_asset_library_blend_files():
            if not remaining:
                break
            found = _load_previews_from_file(blend, remaining)
            for n in found:
                try:
                    rel = os.path.relpath(blend, lib_root).replace(os.sep, "/")
                    _asset_source[n] = (lib_name, f"{rel}/Brush/{n}")
                except Exception:
                    pass
            remaining -= found
    finally:
        _custom_scan_active = False
    # Names not found in any library → mark as a miss so we don't rescan forever.
    for n in names:
        _bundled_preview_cache.setdefault(n, None)


def resolve_asset_source(name):
    """Return (asset_library_identifier, relative_asset_identifier) for a
    custom-library brush so it can be activated via brush.asset_activate, or
    None. Scans the asset libraries if the source isn't recorded yet. Off-draw
    only (may do file I/O) — call from the modal operator, never a draw
    callback."""
    if name not in _asset_source:
        _load_custom_previews({name})
    return _asset_source.get(name)


def preload_bundled_previews():
    """Load EVERY catalogued Essentials brush's baked preview in one pass, up
    front, so that assigning a brush to a slot later never has to touch the
    Essentials library (which was dropping the active sculpt brush and
    delaying icons). Idempotent; runs off the draw callback via the timer."""
    global _bundled_preload_done
    if _bundled_preload_done:
        return
    _bundled_preload_done = True
    # Load previews for EVERY brush present in the Essentials sculpt file
    # (names=None), not just the hardcoded BRUSHES catalogue: newer Blender
    # versions ship extra default sculpt brushes (e.g. 5.2's "Scene Project",
    # "Blur", the Paint/Blend set) that aren't catalogued but must still get
    # thumbnails. One link/unlink cycle; future-proof against later additions.
    _load_previews_from_file(_get_essentials_blend_path(), None)
    # Mark any catalogued asset name absent from THIS Blender's Essentials file as
    # a miss, so it isn't retried against the file every frame (prior behaviour).
    try:
        from .brushes import BRUSHES
        for _d, _b, asset_name, _i in BRUSHES:
            _bundled_preview_cache.setdefault(asset_name, None)
    except Exception:
        pass


# ── thumbnail cache ───────────────────────────────────────────────────────────
# Successful textures are cached permanently (until clear_texture_cache()).
# Failed/pending lookups are NOT cached so we retry on later frames, since
# Blender may still be generating the asset preview render.
_tex_cache: dict            = {}   # brush_name → GPUTexture
_tex_masked: dict           = {}   # brush_name → bool (circular crop applied?)
_preview_requested: set     = set()  # brush_name → generation already queued
_preview_requested_at: dict = {}     # brush_name → time.time() when queued
_pending_preview_names: set = set()  # brush_name → waiting to be processed
_queue_timer_running        = False
_last_reject_reason: dict   = {}     # brush_name → why _get_brush_texture returned None last time
_tool_icon_missing: set     = set()  # tool spec → ships no bundled icon (draw text)

# Per-size circular alpha masks, cached so the (small) cost is paid once per
# preview resolution rather than once per brush.
_mask_cache: dict           = {}   # (w, h) → flat float32 alpha mask


def clear_texture_cache():
    global _bundled_preload_done
    _tex_cache.clear()
    _tex_masked.clear()
    _preview_requested.clear()
    _preview_requested_at.clear()
    _bundled_preview_cache.clear()
    _asset_source.clear()
    _tool_icon_missing.clear()
    _icon_tex_cache.clear()
    _bundled_preload_done = False


# ── circular thumbnail edge softening (CPU-side alpha mask) ────────────────────
# The round SHAPE of a thumbnail is guaranteed by geometry in
# _draw_textured_disc (the corners are never rasterised). The alpha mask
# below is applied ON TOP of that purely to soften/antialias the disc edge;
# it is no longer load-bearing for the crop, so a numpy-less environment (or
# any mask failure) can only cost a slightly harder edge, never a square.
def _circular_alpha_mask(w, h):
    """Return a flat (w*h,) alpha mask: 1.0 inside the inscribed circle, 0.0
    outside, with a ~1px antialiased edge. numpy fast path with a pure-Python
    fallback. Cached per (w, h)."""
    key = (w, h)
    cached = _mask_cache.get(key)
    if cached is not None:
        return cached
    cx = (w - 1) / 2.0
    cy = (h - 1) / 2.0
    radius = min(w, h) / 2.0
    if _np is not None:
        yy, xx = _np.mgrid[0:h, 0:w]
        dist = _np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
        mask = _np.clip(radius - dist + 0.5, 0.0, 1.0).astype(_np.float32).ravel()
    else:
        mask = [0.0] * (w * h)
        for y in range(h):
            dy2 = (y - cy) ** 2
            row = y * w
            for x in range(w):
                d = math.sqrt((x - cx) ** 2 + dy2)
                v = radius - d + 0.5
                mask[row + x] = 0.0 if v <= 0.0 else (1.0 if v >= 1.0 else v)
    _mask_cache[key] = mask
    return mask


# Decode display-referred (sRGB) preview/icon pixels to linear BEFORE upload?
# This depends on whether the viewport re-applies linear→sRGB to POST_PIXEL
# GPU draws, and that behaviour CHANGED across Blender versions:
#   • Blender ≤ 4.x  — the framebuffer re-encodes linear→sRGB on output, so
#     uploading raw sRGB values encodes them TWICE → washed-out/desaturated
#     thumbnails vs. the Asset Shelf (user-reported in add-on v2.7.0 on 4.5).
#     Decoding sRGB→linear here makes the round-trip an identity → correct.
#   • Blender ≥ 5.0  — POST_PIXEL draws land in display space as-is (no
#     re-encode). The very same decode then only DARKENS the thumbnails, which
#     is what the user saw on 5.1 (verified live via MCP: skipping the decode
#     makes the wheel thumbnails match the Asset Shelf again).
# So gate the decode on the Blender version. NB: the 4.5→5.1 boundary was
# bisected only to "somewhere in (4.5, 5.1]"; 5.0.0 is the pragmatic split. If
# a specific 5.0.x build ever shows washed-out thumbnails, widen this bound.
_DECODE_SRGB_PREVIEWS = bpy.app.version < (5, 0, 0)


def _srgb_to_linear(v):
    """Display sRGB value (0..1) → linear (piecewise EOTF, IEC 61966-2-1).
    Used by the pure-Python fallback of _build_texture; the numpy path vectorizes
    the same formula inline."""
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def _build_texture(w, h, raw):
    """Build a GPUTexture from a flat RGBA float buffer, multiplying the alpha
    channel by the circular mask so the disc edge is soft. Returns
    (GPUTexture, masked: bool) or (None, False) on failure. Shared by the
    bundled-artwork fast path and the generic-generation fallback.

    The RGB channels are conditionally converted sRGB → LINEAR before upload
    (see _DECODE_SRGB_PREVIEWS above): preview pixels (image_pixels_float) and
    the bundled tool-icon PNGs are display-referred (sRGB-encoded). On Blender
    ≤ 4.x the viewport re-encodes linear→sRGB on output, so we must decode here
    to keep the round-trip an identity (else washed-out); on Blender ≥ 5.0 the
    POST_PIXEL draw lands in display space as-is, so decoding would only darken
    them (the bug this gate fixes)."""
    n = w * h * 4
    masked = False
    mask = _circular_alpha_mask(w, h)
    if _np is not None:
        try:
            arr = _np.asarray(raw[:n], dtype=_np.float32)
            if arr.size >= n:
                arr = arr[:n]
                if _DECODE_SRGB_PREVIEWS:
                    rgb = arr.reshape(-1, 4)[:, :3]   # view: writes into arr
                    low = rgb <= 0.04045
                    rgb[low]  = rgb[low] / 12.92
                    rgb[~low] = ((rgb[~low] + 0.055) / 1.055) ** 2.4
                arr[3::4] *= mask           # alpha = every 4th float
                raw = arr.tolist()
                masked = True
        except Exception as exc:
            print(f"Sculptools: circular mask skipped ({exc})")
            masked = False
    else:
        try:
            data = list(raw[:n])
            for i in range(w * h):
                b = i * 4
                if _DECODE_SRGB_PREVIEWS:
                    data[b]     = _srgb_to_linear(data[b])
                    data[b + 1] = _srgb_to_linear(data[b + 1])
                    data[b + 2] = _srgb_to_linear(data[b + 2])
                data[b + 3] *= mask[i]
            raw = data
            masked = True
        except Exception as exc:
            print(f"Sculptools: circular mask skipped ({exc})")
            masked = False
    try:
        data = raw if (isinstance(raw, list) and len(raw) == n) else list(raw)[:n]
        buf = gpu.types.Buffer('FLOAT', n, data)
        tex = gpu.types.GPUTexture((w, h), format='RGBA16F', data=buf)
        return tex, masked
    except Exception as exc:
        print(f"Sculptools: texture build failed: {exc}")
        return None, False


# ── bundled tool-icon textures ────────────────────────────────────────────────
# Tools (Mask/Face Sets/Trim/Filter gestures) have no brush thumbnail, but we
# ship a PNG of Blender's own icon per tool (sculptools_palette/icons/<key>.png,
# extracted from Blender's vector tool icons). We decode the PNG ourselves (pure
# Python, no bpy datablock churn during draw), composite the monochrome glyph
# over a dark disc so it reads like the brush "coins", and build a GPUTexture via
# the SAME _build_texture path as thumbnails. One-shot ops ship no icon → miss →
# text label. No new GPU state; the circular crop/soft edge is unchanged.

_TOOL_ICON_BG = (0.16, 0.16, 0.18)   # dark disc behind the white glyph

GEAR_CENTER_DY = 84   # px below the centre where the gear sits (modal: 2 hint lines)
# The Preview Editor shows a single hint line ("Preview Only", at cy-33) instead of
# the modal's two, so the eye icon has a SMALLER offset to stay compact with the
# rest of the central block (tuned by eye in Blender).
EYE_CENTER_DY = 60
GEAR_RADIUS    = 14   # gear draw radius (px)
# Ring around the gear so it reads as a pressable button (user request v2.7.0).
# Only the modal's gear (clickable) — NOT the Preview Editor's eye, which is
# decorative. Tint and alpha follow the gear (hover = slot colour).
GEAR_RING_RADIUS = 17.33   # 15.75 * 1.10 — successive user tunings (+5%, +10%)
GEAR_RING_WIDTH  = 2.0


def _read_png_rgba(path):
    """Minimal PNG decoder → (w, h, floats) with floats a flat RGBA list in
    0..1, rows BOTTOM-UP to match the ImBuf convention _build_texture /
    _draw_textured_disc expect (golden rule #8). Handles 8-bit RGBA (colour
    type 6) with all five scanline filters. Returns None on any problem."""
    try:
        with open(path, 'rb') as f:
            data = f.read()
        if data[:8] != b'\x89PNG\r\n\x1a\n':
            return None
        i, w, h, bitdepth, colortype = 8, 0, 0, None, None
        idat = b''
        while i < len(data):
            ln  = int.from_bytes(data[i:i+4], 'big')
            typ = data[i+4:i+8]
            chunk = data[i+8:i+8+ln]
            if typ == b'IHDR':
                w = int.from_bytes(chunk[0:4], 'big')
                h = int.from_bytes(chunk[4:8], 'big')
                bitdepth, colortype = chunk[8], chunk[9]
            elif typ == b'IDAT':
                idat += chunk
            elif typ == b'IEND':
                break
            i += 12 + ln
        if bitdepth != 8 or colortype != 6:
            return None
        raw = zlib.decompress(idat)
        stride = w * 4
        rows, prev, pos = [], bytearray(stride), 0
        for _y in range(h):
            ft = raw[pos]; pos += 1
            line = bytearray(raw[pos:pos + stride]); pos += stride
            if ft == 1:      # Sub
                for x in range(4, stride):
                    line[x] = (line[x] + line[x-4]) & 0xff
            elif ft == 2:    # Up
                for x in range(stride):
                    line[x] = (line[x] + prev[x]) & 0xff
            elif ft == 3:    # Average
                for x in range(stride):
                    a = line[x-4] if x >= 4 else 0
                    line[x] = (line[x] + ((a + prev[x]) >> 1)) & 0xff
            elif ft == 4:    # Paeth
                for x in range(stride):
                    a = line[x-4] if x >= 4 else 0
                    b = prev[x]
                    c = prev[x-4] if x >= 4 else 0
                    p = a + b - c
                    pa, pb, pc = abs(p-a), abs(p-b), abs(p-c)
                    pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                    line[x] = (line[x] + pr) & 0xff
            rows.append(line)
            prev = line
        floats = []
        for y in range(h - 1, -1, -1):        # bottom-up
            floats.extend(v / 255.0 for v in rows[y])
        return w, h, floats
    except Exception as exc:
        print(f"Sculptools: tool icon PNG read failed ({path}): {exc}")
        return None


def _tool_icon_path(spec):
    from .tools import is_tool_spec, TOOL_PREFIX
    if not is_tool_spec(spec):
        return None
    key = spec[len(TOOL_PREFIX):]
    return os.path.join(os.path.dirname(__file__), "icons", key + ".png")


def _get_tool_icon_texture(spec):
    """Cached GPUTexture for a tool spec's bundled icon, or None (→ text label).
    Specs with no shipped PNG (one-shot ops) are recorded as misses so we don't
    re-stat the file every frame."""
    if spec in _tex_cache:
        return _tex_cache[spec]
    if spec in _tool_icon_missing:
        return None
    path = _tool_icon_path(spec)
    if not path or not os.path.exists(path):
        _tool_icon_missing.add(spec)
        return None
    decoded = _read_png_rgba(path)
    if decoded is None:
        _tool_icon_missing.add(spec)
        return None
    w, h, floats = decoded
    # composite the white glyph over an opaque dark disc so the slot looks like
    # the brush thumbnail coins (rather than a bare floating glyph)
    br, bg_, bb = _TOOL_ICON_BG
    for p in range(w * h):
        a = floats[p*4 + 3]
        floats[p*4 + 0] = floats[p*4 + 0] * a + br  * (1 - a)
        floats[p*4 + 1] = floats[p*4 + 1] * a + bg_ * (1 - a)
        floats[p*4 + 2] = floats[p*4 + 2] * a + bb  * (1 - a)
        floats[p*4 + 3] = 1.0
    tex, masked = _build_texture(w, h, floats)
    if tex is None:
        _tool_icon_missing.add(spec)
        return None
    _tex_cache[spec] = tex
    _tex_masked[spec] = masked
    return tex


# ── centre block (counter, name, wordmark, hints, gear/eye) ───────────────────
_icon_tex_cache: dict = {}   # name -> GPUTexture, oppure False se mancante/rotta


def _get_icon_texture(name):
    """GPUTexture di icons/<name>.png, cache per nome. NON applica maschera
    circolare (sono glifi, non coin)."""
    cached = _icon_tex_cache.get(name)
    if cached is not None:
        return cached or None
    path = os.path.join(os.path.dirname(__file__), "icons", f"{name}.png")
    if not os.path.exists(path):
        _icon_tex_cache[name] = False
        return None
    decoded = _read_png_rgba(path)
    if decoded is None:
        _icon_tex_cache[name] = False
        return None
    w, h, floats = decoded
    try:
        buf = gpu.types.Buffer('FLOAT', w * h * 4, floats)
        tex = gpu.types.GPUTexture((w, h), format='RGBA16F', data=buf)
    except Exception as exc:
        print(f"Sculptools: {name} texture build failed: {exc}")
        _icon_tex_cache[name] = False
        return None
    _icon_tex_cache[name] = tex
    return tex


def _draw_textured_quad(cx, cy, r, tex, colour, alpha=1.0):
    """Draw *tex* as a QUAD (not cropped) tinted by *colour*, via IMAGE_COLOR
    (multiplies texture × colour → tints a white glyph). No persistent GPU state
    touched."""
    shader = _get_image_shader()
    if shader is None:
        return
    pos = [(cx - r, cy - r), (cx + r, cy - r), (cx + r, cy + r), (cx - r, cy + r)]
    uv  = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    gpu.state.blend_set('ALPHA')
    batch = batch_for_shader(shader, 'TRI_FAN', {"pos": pos, "texCoord": uv})
    shader.bind()
    shader.uniform_sampler("image", tex)
    shader.uniform_float("color", (colour[0], colour[1], colour[2], alpha))
    batch.draw(shader)
    UNIFORM.bind()


def _draw_center(state):
    """Central block: n/N counter, palette name, wordmark, two hint lines, gear
    (tinted with the active palette's slot colour on hover). Reaffirms ALPHA before
    each text/icon (golden rule #5)."""
    cx = state['cx']; cy = state['cy']
    a = state.get('alpha', 1.0)
    idx = state.get('palette_index', 1)
    tot = state.get('palette_total', 1)
    name = state.get('palette_name', '')
    okl = state.get('open_key_label', '\\')
    ckl = state.get('cycle_key_label', 'Tab')
    gear_hov = state.get('gear_hovered', False)
    gear_col = state.get('gear_colour', (0.8, 0.8, 0.8))
    is_preview = state.get('is_preview', False)

    gpu.state.blend_set('ALPHA')
    txt = (*C_TEXT[:3], a)
    hint = (*C_TEXT[:3], a * 0.8)
    # Wordmark enlarged by 50% (30 -> 45); name and hints moved closer to the
    # wordmark to halve the empty space (offsets tuned by eye in Blender).
    _draw_text_centered(f"{idx}/{tot}", cx, cy + 68, 13, txt)
    if name:
        _draw_text_centered(name, cx, cy + 46, 15, txt)
    _draw_text_centered("PA\\ETTE", cx, cy + 10, 45, txt)
    if is_preview:
        _draw_text_centered("Preview Only", cx, cy - 33, 11, hint)
    else:
        _draw_text_centered(f"{okl} to open Palette", cx, cy - 26, 11, hint)
        _draw_text_centered(f"{ckl} to cycle through Palettes", cx, cy - 41, 11, hint)

    icon_name = 'eye' if is_preview else 'gear'
    tex = _get_icon_texture(icon_name)
    if tex is not None:
        if is_preview:
            col = (0.8, 0.8, 0.8)
        else:
            col = gear_col if gear_hov else (0.8, 0.8, 0.8)
        gpu.state.blend_set('ALPHA')
        dy = EYE_CENTER_DY if is_preview else GEAR_CENTER_DY
        gy = cy - dy
        # Button ring around the gear (not around the preview's eye): same
        # tint/alpha as the glyph so it reads as a single button.
        if not is_preview:
            _draw_ring(cx, gy, GEAR_RING_RADIUS, GEAR_RING_WIDTH,
                       (col[0], col[1], col[2], a))
        _draw_textured_quad(cx, gy, GEAR_RADIUS, tex, col, a)
    gpu.state.blend_set('ALPHA')


def _process_preview_queue():
    """Runs via bpy.app.timers — NOT inside a draw callback — so it is safe
    to call operators (or do file I/O) here. Blender forbids running
    operators while GPU drawing is in progress (a draw_handler callback);
    doing so silently fails, which is why thumbnails previously never
    appeared.

    The whole pending set is drained in one pass: first a single batched
    read of real, curated artwork straight from Blender's shipped Essentials
    library file (see preload_bundled_previews), then — only for brushes that
    aren't one of Blender's own (a custom user brush, for instance) — a
    per-brush fallback to lib_id_generate_preview(), which for Brush IDs only
    ever produces a generic placeholder-style render rather than real stroke
    artwork, but is the best available option for something outside
    Essentials."""
    global _queue_timer_running

    # Always ensure the WHOLE Essentials preview set is loaded in one pass the
    # first time anything is processed. After this, no per-slot assignment
    # ever has to touch the Essentials library again (which was dropping the
    # active brush and delaying icons until the wheel was reopened).
    preload_bundled_previews()

    if not _pending_preview_names:
        _queue_timer_running = False
        return None  # unregister the timer

    names = list(_pending_preview_names)
    _pending_preview_names.clear()

    asset_map = {n: _asset_name_for_brush(n) for n in names}

    # Custom asset-library artwork: any pending name the Essentials preload
    # didn't resolve may belong to a user's custom brush library — read its
    # curated preview straight from the library's .blend (same mechanism as
    # Essentials, generalised). This also covers names with no live datablock
    # yet (e.g. after reopening a file), which the generic fallback below can't.
    unresolved = {asset_map[n] for n in names
                  if asset_map[n] not in _bundled_preview_cache}
    if unresolved:
        _load_custom_previews(unresolved)

    # Generic fallback (lib_id_generate_preview) only for brushes still without
    # curated artwork AND that are plain local brushes. Skipped for curated
    # brushes (asset / linked from a library): they already carry a real
    # preview, and regenerating one for a Brush ID only ever yields a generic
    # grey placeholder — overwriting the real artwork (custom-library grey bug).
    for n in names:
        if _bundled_preview_cache.get(asset_map[n]) is not None:
            continue
        brush = bpy.data.brushes.get(n)
        if not brush:
            continue
        if getattr(brush, "library", None) or getattr(brush, "asset_data", None):
            continue
        try:
            with bpy.context.temp_override(id=brush):
                bpy.ops.ed.lib_id_generate_preview()
        except Exception as exc:
            print(f"Sculptools: preview generation failed for '{n}': {exc}")

    _queue_timer_running = False
    return None  # done — unregister until something new is queued


def _ensure_preview_timer():
    """Start the background queue timer if it isn't already running. Running
    the timer runs preload_bundled_previews() (off the draw callback), so this
    lets us trigger the bundled preload even when there is NO live brush to
    queue — e.g. right after reopening a file where every assigned brush is an
    Essentials asset that hasn't been instantiated in bpy.data.brushes yet.
    Only schedules a timer; safe to call from inside a draw callback."""
    global _queue_timer_running
    if not _queue_timer_running:
        _queue_timer_running = True
        bpy.app.timers.register(_process_preview_queue, first_interval=0.01)


def _request_external_preview(name):
    """Queue *name* for background preview resolution (Essentials preload, then
    custom asset-library scan, then generic generation), by brush NAME so it
    works even when there is no live datablock yet (e.g. an assigned brush from
    a custom library that hasn't been instantiated after reopening the file).
    Only schedules work via the timer; safe from inside a draw callback."""
    if name in _preview_requested:
        return
    _preview_requested.add(name)
    _preview_requested_at[name] = time.time()
    _pending_preview_names.add(name)
    _ensure_preview_timer()


def _queue_preview_generation(brush):
    """Queue *brush* for asset-preview resolution. Safe to call from a draw
    callback: only schedules background work via bpy.app.timers."""
    _request_external_preview(brush.name)


def stop_preview_queue():
    """Called on addon unregister to avoid a dangling timer after reload."""
    global _queue_timer_running
    if _queue_timer_running:
        try:
            bpy.app.timers.unregister(_process_preview_queue)
        except Exception:
            pass
        _queue_timer_running = False
    _pending_preview_names.clear()


def request_preview_by_name(brush_name: str) -> bool:
    """Ensure a preview struct exists and queue a (re)generation for the
    named brush — the actual work _get_brush_texture() does, but callable
    independently of it. _get_brush_texture() only ever runs while the pie
    palette's draw callback is active (i.e. the wheel is open), so a
    'Refresh Thumbnails' button that only cleared the cache and reported
    status — without calling this — would do nothing for brushes that had
    never actually been drawn yet. Returns True if a brush with that name
    was found."""
    brush = bpy.data.brushes.get(brush_name)
    if not brush:
        return False
    try:
        brush.preview_ensure()
    except Exception:
        pass
    _queue_preview_generation(brush)
    return True


def warm_palette_previews(names):
    """Pre-richiedi le preview per un iterabile di nomi brush, OFF-DRAW, così
    aprire la ruota / switchare su una palette 'fredda' mostra le thumbnail già
    pronte, senza pop-in di più frame. Usa il path by-name della coda
    (_request_external_preview), che risolve l'artwork Essentials/custom SENZA
    bisogno di un datablock vivo — funziona anche subito dopo il caricamento di
    un file, prima che i brush assegnati siano istanziati in bpy.data.brushes.
    Idempotente: _request_external_preview deduplica via _preview_requested.
    Non tocca la library Essentials oltre il preload esistente (regola d'oro #3)."""
    for name in names:
        if name:
            _request_external_preview(name)


def diagnose_brush_preview(brush_name: str) -> str:
    """Return a human-readable diagnostic string for one brush's preview
    state — used by the 'Refresh Thumbnails' button so problems can be
    reported precisely instead of just 'it doesn't work'.

    This actually calls _get_brush_texture() (the same function the pie
    wheel uses while drawing) so the report reflects reality — including
    the exact reason a texture wasn't produced — rather than raw state
    that doesn't say whether a texture would actually be built right now.
    This makes the report self-contained: it doesn't require the wheel to
    have ever been opened."""
    # Call the same function the wheel uses first, so the report reflects what
    # would actually render — including the bundled fast path that works even
    # without a live brush datablock.
    tex = _get_brush_texture(brush_name)
    brush = bpy.data.brushes.get(brush_name)

    asset_name = _asset_name_for_brush(brush_name)
    if asset_name not in _bundled_preview_cache:
        bundled_status = "not attempted yet"
    elif _bundled_preview_cache[asset_name] is not None:
        bw, bh, _ = _bundled_preview_cache[asset_name]
        bundled_status = f"SUCCESS ({bw}x{bh} from shipped Essentials file)"
    else:
        bundled_status = "failed / not found in Essentials — using fallback pipeline"

    if tex is not None:
        result = "TEXTURE READY (should be visible in the wheel now)"
    else:
        reason = _last_reject_reason.get(brush_name, "unknown")
        result = f"NOT ready — {reason}"

    if brush is None:
        # No live datablock — typically an Essentials asset assigned in a
        # previous session and not yet reactivated. The icon can still come
        # from bundled artwork, so report that instead of a bare "not found".
        return (f"'{brush_name}': {result} | bundled artwork: {bundled_status} | "
                f"live brush: NOT in bpy.data.brushes (asset not instantiated)")

    prev = brush.preview
    try:
        img_w, img_h = prev.image_size if prev else (0, 0)
    except Exception:
        img_w, img_h = -1, -1
    try:
        icon_w, icon_h = prev.icon_size if prev else (0, 0)
    except Exception:
        icon_w, icon_h = -1, -1

    job_running = "yes" if bpy.app.is_job_running('RENDER_PREVIEW') else "no"
    queued_at = _preview_requested_at.get(brush_name)
    age = f"{time.time() - queued_at:.2f}s ago" if queued_at else "never queued"

    return (f"'{brush_name}': {result} | bundled artwork: {bundled_status} | "
            f"image_size={img_w}x{img_h}, icon_size={icon_w}x{icon_h}, "
            f"RENDER_PREVIEW job running={job_running}, requested {age}")



def brush_name_available(name):
    """True if this brush name resolves to real artwork right now: a cached
    texture, a live datablock, or curated Essentials/custom artwork already in
    the bundled cache. Used by the import counter (best-effort diagnostic;
    Essentials count as present once preload_bundled_previews has run)."""
    if name in _tex_cache:
        return True
    if bpy.data.brushes.get(name) is not None:
        return True
    return _bundled_preview_cache.get(_asset_name_for_brush(name)) is not None


def slot_shows_not_found(name):
    """True when a non-empty slot's assignment is CONCLUSIVELY unresolvable in
    this session, so the wheel draws 'not found' instead of the raw name.

    - Tool spec: the key is unknown, or the tool is gated out on this Blender.
    - Brush: resolution has run and found no artwork (its asset name is present
      in the bundled cache with a None value) and it is not otherwise available.
      A brush still resolving (asset name not yet in the bundled cache) returns
      False, so it shows its label transiently rather than a false 'not found'."""
    from .tools import is_tool_spec, get_tool, tool_available
    if is_tool_spec(name):
        entry = get_tool(name)
        return entry is None or not tool_available(entry, bpy.app.version)
    if brush_name_available(name):
        return False
    asset = _asset_name_for_brush(name)
    return asset in _bundled_preview_cache and _bundled_preview_cache[asset] is None


def _get_brush_texture(brush_name: str):
    """Return a cached GPUTexture matching the brush's Asset Browser
    thumbnail, or None (caller falls back to a text label; we'll keep
    retrying on subsequent frames until the preview is ready)."""
    from .tools import is_tool_spec
    if is_tool_spec(brush_name):
        # tools have no asset thumbnail; use the bundled icon PNG if we ship one
        # (else None -> text label, e.g. for one-shot ops)
        return _get_tool_icon_texture(brush_name)
    if brush_name in _tex_cache:
        _last_reject_reason.pop(brush_name, None)
        return _tex_cache[brush_name]

    asset_name = _asset_name_for_brush(brush_name)

    # ── fast path: real curated artwork from the shipped Essentials library ──
    # Keyed by ASSET NAME, so it must run BEFORE requiring a live
    # bpy.data.brushes entry. A brush assigned in a previous session may no
    # longer exist as a datablock after the file is reopened — Essentials asset
    # brushes are only instantiated on activation — yet its artwork is already
    # in the bundled cache after preload. Requiring the live ID first (the old
    # behaviour) was exactly why such icons went missing on reopen and Refresh
    # couldn't recover them (the brush was simply "not found in
    # bpy.data.brushes"). Reading the thumbnail off the asset name instead
    # makes it survive a restart, whether or not the brush is instantiated.
    if asset_name in _bundled_preview_cache:
        bundled = _bundled_preview_cache[asset_name]
        if bundled is not None:
            w, h, raw = bundled
            tex, masked = _build_texture(w, h, raw)
            if tex is not None:
                _tex_cache[brush_name] = tex
                _tex_masked[brush_name] = masked
                _last_reject_reason.pop(brush_name, None)
                return tex
            _last_reject_reason[brush_name] = "bundled texture build failed"
        # else: known miss (not an Essentials brush) — fall through to the
        # generic pipeline below, which needs a live brush ID.

    brush = bpy.data.brushes.get(brush_name)
    if not brush:
        # No live datablock (an Essentials or custom-library asset assigned in a
        # previous session and not yet reactivated). Request background
        # resolution by name — this runs the Essentials preload AND scans the
        # user's custom asset libraries for the brush's curated preview — then
        # retry on a later frame once the bundled cache is populated.
        if asset_name not in _bundled_preview_cache:
            _request_external_preview(brush_name)
            _last_reject_reason[brush_name] = (
                "brush not in bpy.data.brushes yet — resolving preview from library")
        else:
            _last_reject_reason[brush_name] = (
                "brush not in bpy.data.brushes and no library artwork available")
        return None

    # ── curated asset brush present locally/linked (e.g. from a custom brush
    # library): its own .preview already holds the real thumbnail, exactly like
    # the Essentials fast path. Read it directly and DO NOT queue a
    # regeneration — lib_id_generate_preview would overwrite this real artwork
    # with a generic grey placeholder (the custom-library grey-circle bug). ──
    if getattr(brush, "library", None) or getattr(brush, "asset_data", None):
        pix = _extract_preview_pixels(brush)
        if pix is not None:
            w, h, raw = pix
            tex, masked = _build_texture(w, h, raw)
            if tex is not None:
                _tex_cache[brush_name] = tex
                _tex_masked[brush_name] = masked
                _last_reject_reason.pop(brush_name, None)
                return tex
        # Live preview not usable yet — fall back to reading it from the source
        # library file (handles the case where the linked ID's preview isn't
        # populated), then retry next frame.
        if asset_name not in _bundled_preview_cache:
            _request_external_preview(brush_name)
        _last_reject_reason[brush_name] = "curated brush preview not ready — resolving from library"
        return None

    # brush.preview can be None entirely (not just empty) for a brush that
    # was just locally activated from the Essentials asset library — the
    # local ID copy starts with no preview struct at all until something
    # forces one into existence. preview_ensure() creates (and returns) the
    # ImagePreview struct without rendering it; we still need to queue the
    # actual render separately. Bailing out on `prev is None` without ever
    # calling preview_ensure() meant we never asked Blender to create the
    # struct in the first place — this was blocking thumbnails entirely.
    try:
        prev = brush.preview_ensure()
    except Exception:
        prev = brush.preview
    if not prev:
        _queue_preview_generation(brush)
        _last_reject_reason[brush_name] = "preview_ensure() returned nothing"
        return None

    # Always (idempotently) request a render — even if a preview struct
    # already exists with a "valid" size, that size may just be the flat
    # grey placeholder Blender allocates immediately when the struct is
    # created, before the actual render job has run. Queuing is a no-op
    # after the first call per brush (gated by _preview_requested), and
    # this guarantees every brush has a request timestamp for the cooldown
    # check below.
    _queue_preview_generation(brush)

    try:
        # Prefer the full "image" preview — this is the same render used
        # by the Asset Browser thumbnail grid. The small "icon" preview
        # (icon_pixels) is a different, lower-detail representation used
        # for toolbar/list icons and does not match the Asset Browser look.
        w, h = prev.image_size
        raw_attr = 'image_pixels_float'
        int_attr = 'image_pixels'

        if w <= 0 or h <= 0:
            # No image-preview yet — fall back to the icon preview so
            # something shows immediately, but keep asking for the real
            # asset preview in the background.
            w, h = prev.icon_size
            raw_attr = 'icon_pixels_float'
            int_attr = 'icon_pixels'

        if w <= 0 or h <= 0:
            _queue_preview_generation(brush)
            _last_reject_reason[brush_name] = "image_size and icon_size are both 0x0"
            return None  # nothing usable yet — retry next frame

        try:
            raw = list(getattr(prev, raw_attr))
        except Exception:
            raw = []

        if len(raw) < w * h * 4:
            try:
                px_int = list(getattr(prev, int_attr))
                raw = []
                for v in px_int:
                    raw.append(((v)       & 0xFF) / 255.0)
                    raw.append(((v >> 8)  & 0xFF) / 255.0)
                    raw.append(((v >> 16) & 0xFF) / 255.0)
                    raw.append(((v >> 24) & 0xFF) / 255.0)
            except Exception:
                raw = []

        if len(raw) < w * h * 4:
            _queue_preview_generation(brush)
            _last_reject_reason[brush_name] = (
                f"pixel buffer too short ({len(raw)} floats, expected {w*h*4})")
            return None  # still not ready — retry next frame

        # Blender allocates the preview buffer at its final size as soon as
        # the render job STARTS, filling it with a flat grey placeholder
        # (a generic sphere-icon grey) until the background render job
        # finishes. A valid width/height therefore does NOT mean the pixel
        # content is final — checking is_job_running('RENDER_PREVIEW') is
        # the actual, documented way to know whether that job is still in
        # flight. While it's running, we refuse to cache anything and keep
        # retrying — this is what prevented the flat-grey circles.
        if bpy.app.is_job_running('RENDER_PREVIEW'):
            _last_reject_reason[brush_name] = "a RENDER_PREVIEW job is currently running"
            return None

        # Guard against the narrow race where we ask Blender to generate a
        # preview (queued via bpy.app.timers) but the background job hasn't
        # actually started yet by the time we check is_job_running() above
        # — in that split-second window the placeholder would read as
        # "finished" (no job running) even though generation hasn't begun.
        # Requiring a short cooldown since the request gives the job
        # scheduler time to pick it up.
        queued_at = _preview_requested_at.get(brush_name)
        if queued_at is not None and (time.time() - queued_at) < 0.3:
            remaining = 0.3 - (time.time() - queued_at)
            _last_reject_reason[brush_name] = (
                f"cooldown active, {remaining:.2f}s remaining since request")
            return None

        # Reject a buffer that is genuinely blank (every pixel alpha == 0)
        # — a real placeholder/uninitialised buffer, as opposed to a real
        # thumbnail that merely has a transparent BACKGROUND (which is how
        # Blender's official brush thumbnails are authored: some pixels
        # opaque, most transparent). Scanning the whole alpha channel (not
        # just a few centred pixels, which was the earlier, buggy check)
        # tells the two apart reliably, and also prevents permanently
        # caching a transient garbage/blank texture if this function runs
        # mid-render.
        if not any(a > 0.01 for a in raw[3::4]):
            _queue_preview_generation(brush)
            _last_reject_reason[brush_name] = (
                f"buffer is fully transparent ({w}x{h} pixels, all alpha <= 0.01)")
            return None

        buf_tex, masked = _build_texture(w, h, raw)
        if buf_tex is None:
            _last_reject_reason[brush_name] = "texture build failed"
            return None
        _tex_cache[brush_name] = buf_tex
        _tex_masked[brush_name] = masked
        _last_reject_reason.pop(brush_name, None)
        return buf_tex

    except Exception as exc:
        print(f"Sculptools: thumbnail error for '{brush_name}': {exc}")
        _last_reject_reason[brush_name] = f"exception: {exc}"
        return None


# ── geometry ──────────────────────────────────────────────────────────────────
def _slot_angle(i, n=8):
    return math.pi / 2 - (2 * math.pi * i / n)


def _sub_positions(cx, cy, R, sr, slot_i, sub_sr=None, gap=60.0, n=8):
    if sub_sr is None:
        sub_sr = sr * 0.9
    slot_a = _slot_angle(slot_i, n)
    bx = cx + math.cos(slot_a) * R
    by = cy + math.sin(slot_a) * R
    out_x, out_y   = math.cos(slot_a), math.sin(slot_a)
    side_x, side_y = -out_y, out_x
    D = sr + sub_sr + gap
    top   = (bx + out_x * D,             by + out_y * D)
    left  = (bx + out_x * D * 0.5 - side_x * D * 0.5,
             by + out_y * D * 0.5 - side_y * D * 0.5)
    right = (bx + out_x * D * 0.5 + side_x * D * 0.5,
             by + out_y * D * 0.5 + side_y * D * 0.5)
    return [left, top, right]


# Cache of effective layouts: _effective_layout is called every frame by the
# modal's and the preview's draw callback; the parameters only change when the
# user moves a slider, so a small memo zeroes out the cost.
_LAYOUT_CACHE = {}


def _effective_layout(R, sr, sub_sf, gap, n, margin=4.0):
    """Anti-overlap (v2.7.1): from the USER parameters compute EFFECTIVE wheel
    radius and sub gap such that no circle of the wheel can touch another:
    slot-slot, sub-siblings, sub vs parent slot, and every pair between different
    slot families (so it holds for the preview too, which shows all subs at once).
    Growth only (R_eff >= R, gap_eff >= gap): never shrink what the user has
    sized. With the defaults it is the identity. Pure (no bpy/gpu) — unit-tested.

    Geometric NB: increasing D (= sr + sub_sr + gap) separates siblings and parent
    but BRINGS CLOSER the facing subs of adjacent slots (they converge to
    D ~ sqrt(2)*R with n=8): therefore the pairs between different families are
    resolved by growing R, which at fixed D separates them all (the inter-family
    distances are |u*R + w| with u fixed non-zero -> they diverge)."""
    key = (round(R, 3), round(sr, 3), round(sub_sf, 4),
           round(gap, 3), n, round(margin, 3))
    hit = _LAYOUT_CACHE.get(key)
    if hit is not None:
        return hit

    sub_sr = sr * sub_sf
    # 1. Minimum D (independent of R): the closest sibling pair
    #    (top<->left/right) is D/sqrt(2) apart; left/right are D/sqrt(2)
    #    from the parent slot's centre too.
    D_eff = max(sr + sub_sr + gap,
                math.sqrt(2.0) * (2.0 * sub_sr + margin),
                math.sqrt(2.0) * (sr + sub_sr + margin))
    gap_eff = D_eff - sr - sub_sr

    # 2. Minimum R for the chord between adjacent slots: 2*R*sin(pi/n) >= 2*sr+margin.
    R_eff = max(R, (2.0 * sr + margin) / (2.0 * math.sin(math.pi / n)))

    # 3. Clearance between slot 0's family (slot + 3 subs) and EVERY other
    #    family: by rotational symmetry this covers all pairs of the wheel.
    #    Geometric growth until everything is clear (always terminates, see NB
    #    above; the guard is pure paranoia).
    def _families_clear(Rt):
        fams = []
        for i in range(n):
            a = _slot_angle(i, n)
            fam = [((math.cos(a) * Rt, math.sin(a) * Rt), sr)]
            fam += [((x, y), sub_sr) for (x, y) in
                    _sub_positions(0.0, 0.0, Rt, sr, i, sub_sr, gap_eff, n)]
            fams.append(fam)
        for j in range(1, n):
            for (pa, ra) in fams[0]:
                for (pb, rb) in fams[j]:
                    if math.hypot(pb[0] - pa[0], pb[1] - pa[1]) < ra + rb + margin:
                        return False
        return True

    guard = 0
    while not _families_clear(R_eff) and guard < 512:
        R_eff *= 1.02
        guard += 1

    if len(_LAYOUT_CACHE) > 256:
        _LAYOUT_CACHE.clear()
    _LAYOUT_CACHE[key] = (R_eff, gap_eff)
    return R_eff, gap_eff


# ── GPU primitives ────────────────────────────────────────────────────────────
def _circle_verts(cx, cy, r, n=56):
    return [(cx + math.cos(2 * math.pi * i / n) * r,
             cy + math.sin(2 * math.pi * i / n) * r) for i in range(n + 1)]


def _draw_filled_circle(cx, cy, r, color, n=56):
    verts = [(cx, cy)] + _circle_verts(cx, cy, r, n)
    idx   = [(0, i, i + 1) for i in range(1, n + 1)]
    # Re-assert ALPHA blend before drawing: blf text rendering (used for the
    # hovered slot label) leaves the GPU blend state changed, which otherwise
    # makes translucent fills — and, before this, the transparent parts of
    # thumbnails — composite wrongly on slots drawn afterwards.
    gpu.state.blend_set('ALPHA')
    UNIFORM.bind()
    UNIFORM.uniform_float("color", color)
    batch_for_shader(UNIFORM, 'TRIS', {"pos": verts}, indices=idx).draw(UNIFORM)


def _glow_alpha(t, alpha_center, falloff):
    """Alpha of the hover glow at normalised radius t (0=centre, 1=edge).
    falloff=1 is a linear fade; >1 concentrates the glow near the centre,
    <1 spreads it toward the edge. Pure — unit-tested."""
    return alpha_center * (1.0 - t) ** falloff


def _draw_radial_glow(cx, cy, r, color, alpha_center, falloff=1.0,
                      rings=12, n=40):
    """Soft radial halo (RadialZ-style) for a slot: concentric rings of the
    built-in SMOOTH_COLOR shader whose per-vertex alpha follows a `falloff`
    curve from `alpha_center` at the centre to 0 at radius r. Concentric rings
    (rather than a single fan) are what let the fade be non-linear. ALPHA blend,
    no framebuffer state touched — golden rules respected. Drawn BEFORE the
    slot's filled circle so it reads as a glow around/under the slot."""
    if alpha_center <= 0.0 or r <= 0.0:
        return
    rgb = color[:3]
    # ring 0 is the single centre vertex; rings 1..rings each have n points
    pos  = [(cx, cy)]
    cols = [(rgb[0], rgb[1], rgb[2], alpha_center)]
    for ri in range(1, rings + 1):
        t  = ri / rings
        rr = r * t
        a  = _glow_alpha(t, alpha_center, falloff)
        for i in range(n):
            ang = 2 * math.pi * i / n
            pos.append((cx + math.cos(ang) * rr, cy + math.sin(ang) * rr))
            cols.append((rgb[0], rgb[1], rgb[2], a))
    idx = []
    # inner fan: centre (0) to first ring (indices 1..n)
    for i in range(n):
        idx.append((0, 1 + i, 1 + (i + 1) % n))
    # annuli between successive rings
    for ri in range(1, rings):
        s0 = 1 + (ri - 1) * n
        s1 = 1 + ri * n
        for i in range(n):
            i_n = (i + 1) % n
            idx.append((s0 + i, s1 + i, s1 + i_n))
            idx.append((s0 + i, s1 + i_n, s0 + i_n))
    gpu.state.blend_set('ALPHA')
    SMOOTH.bind()
    batch_for_shader(SMOOTH, 'TRIS', {"pos": pos, "color": cols},
                     indices=idx).draw(SMOOTH)
    UNIFORM.bind()


def _ring_band_radii(r, width, feather=1.0):
    """Four concentric radii (inner→outer) of the antialiased ring band: a solid
    core bounded by a `feather`-wide alpha ramp that STRADDLES each nominal edge
    (half inside, half outside), so coverage crosses 50% exactly at r±width/2 —
    the geometric equivalent of edge antialiasing. Degrades gracefully on thin
    rims: when the core would invert (width <= feather) both middle radii
    collapse to r, leaving a soft ~feather-wide line instead of a broken band.
    Pure — unit-tested."""
    half = width * 0.5
    ri = r - half
    ro = r + half
    f2 = max(feather, 0.0) * 0.5
    r0 = max(0.0, ri - f2)
    r1 = min(ri + f2, r)
    r2 = max(ro - f2, r)
    r3 = ro + f2
    return (r0, r1, r2, r3)


def _draw_ring(cx, cy, r, width, color, n=128, feather=1.0):
    """Filled circular outline (annulus) with an ANTIALIASED (feathered) edge.
    Replaces the old GL LINE_STRIP outline (line width is unreliable/clamped on
    the Vulkan backend) and the later hard-edged TRI_STRIP (whose inner/outer
    circular boundaries had no coverage AA → visible stair-stepping on the
    slot/sub rims). The band is now four concentric rings — a solid core plus a
    `feather`-wide (~1px) alpha ramp on each edge — drawn with the built-in
    SMOOTH_COLOR shader so per-vertex alpha fades the border to transparent.
    This is coverage AA done in GEOMETRY: no MSAA request, no custom shader, no
    framebuffer/stencil state touched (golden rules #1). Same technique as
    `_draw_radial_glow`. `n` is the angular segment count (raised from 64 to
    remove residual faceting). Leaves UNIFORM re-bound for subsequent draws."""
    r0, r1, r2, r3 = _ring_band_radii(r, width, feather)
    rgb = color[:3]
    a = color[3] if len(color) > 3 else 1.0
    radii  = (r0, r1, r2, r3)
    alphas = (0.0, a, a, 0.0)
    pos = []
    cols = []
    for rr, al in zip(radii, alphas):
        for i in range(n + 1):
            ang = 2 * math.pi * i / n
            c, s = math.cos(ang), math.sin(ang)
            pos.append((cx + c * rr, cy + s * rr))
            cols.append((rgb[0], rgb[1], rgb[2], al))
    idx = []
    stride = n + 1
    for band in range(3):        # three annuli: inner feather, core, outer feather
        s0 = band * stride
        s1 = (band + 1) * stride
        for i in range(n):
            idx.append((s0 + i, s0 + i + 1, s1 + i + 1))
            idx.append((s0 + i, s1 + i + 1, s1 + i))
    gpu.state.blend_set('ALPHA')
    SMOOTH.bind()
    batch_for_shader(SMOOTH, 'TRIS', {"pos": pos, "color": cols},
                     indices=idx).draw(SMOOTH)
    UNIFORM.bind()


def _draw_line(x0, y0, x1, y1, color, width=1.0):
    UNIFORM.bind()
    UNIFORM.uniform_float("color", color)
    gpu.state.line_width_set(width)
    batch_for_shader(UNIFORM, 'LINES',
                     {"pos": [(x0, y0), (x1, y1)]}).draw(UNIFORM)


def _draw_textured_disc(cx, cy, r, tex, alpha=1.0, masked=True, n=48):
    """Draw *tex* as a filled DISC (triangle fan) of radius ~0.92r centred at
    (cx, cy), using Blender's built-in IMAGE_COLOR shader, sampling the
    texture's inscribed circle.

    Why a disc and not a textured quad: the round crop is produced by the
    GEOMETRY here — the corner regions of the thumbnail are simply never
    rasterised — so a square corner is structurally impossible regardless of
    the texture's alpha channel, the current GPU blend state, or whether the
    CPU-side alpha mask (see _build_texture) was applied. The previous
    quad-plus-alpha-mask approach depended on all three of those being right
    at once, and in practice they were not (blf text drawing disturbs the
    blend state; without that, transparent corners rendered as opaque
    squares on the non-hovered slots). The CPU alpha mask is still applied on
    top when available, which softens/antialiases the disc edge, but it is no
    longer what guarantees the round shape.

    A stencil-buffer circular clip was tried in an earlier version and
    reverted because manipulating raw stencil/colour-mask state inside a
    POST_PIXEL draw handler corrupted the whole viewport. Drawing a disc
    touches no framebuffer state at all, so that failure mode cannot recur."""
    shader = _get_image_shader()
    if shader is None:
        return
    rad = r * 0.92
    # Fan: centre vertex + outline. texCoord maps the disc onto the texture's
    # inscribed circle (centre 0.5,0.5, radius 0.5) so the centred brush
    # artwork fills the slot and only the outer square margin is cropped.
    pos = [(cx, cy)]
    uv  = [(0.5, 0.5)]
    for i in range(n + 1):
        a = 2 * math.pi * i / n
        ca, sa = math.cos(a), math.sin(a)
        pos.append((cx + ca * rad, cy + sa * rad))
        uv.append((0.5 + 0.5 * ca, 0.5 + 0.5 * sa))
    gpu.state.blend_set('ALPHA')
    batch = batch_for_shader(shader, 'TRI_FAN', {"pos": pos, "texCoord": uv})
    shader.bind()
    shader.uniform_sampler("image", tex)
    shader.uniform_float("color", (1.0, 1.0, 1.0, alpha))
    batch.draw(shader)
    UNIFORM.bind()


# ── text helpers ──────────────────────────────────────────────────────────────
def _fit_text(text, font, max_width, min_size=8, max_size=11):
    for size in range(max_size, min_size - 1, -1):
        blf.size(font, size)
        w, _ = blf.dimensions(font, text)
        if w <= max_width:
            return text, size
    blf.size(font, min_size)
    while len(text) > 1:
        text = text[:-1]
        w, _ = blf.dimensions(font, text + "…")
        if w <= max_width:
            return text + "…", min_size
    return text, min_size


def _draw_text_centered(text, cx, cy, size, color, max_width=None, font=0):
    if max_width:
        text, size = _fit_text(text, font, max_width)
    blf.size(font, size)
    w, h = blf.dimensions(font, text)
    blf.color(font, *color)
    blf.position(font, cx - w / 2, cy - h / 2, 0)
    blf.draw(font, text)


def _best_label(name):
    if not name:
        return ""
    from .tools import is_tool_spec, best_tool_label
    if is_tool_spec(name):
        return best_tool_label(name)
    for prefix in ("Cloth ", "Elastic ", "Multires "):
        if name.startswith(prefix) and len(name) > len(prefix):
            return name[len(prefix):]
    return name


def _slot_label_text(name):
    """(label, missing) for a slot with no thumbnail: ('not found', True) for a
    conclusively-unresolvable assignment, else (short label, False)."""
    missing = slot_shows_not_found(name)
    return ("not found" if missing else _best_label(name)), missing


# ── unified slot drawing ──────────────────────────────────────────────────────
def _draw_slot_contents(sx, sy, r, name, is_hov, alpha, fallback_label=None):
    if name:
        tex = _get_brush_texture(name)
        if tex:
            _draw_textured_disc(sx, sy, r, tex, alpha=alpha,
                                masked=_tex_masked.get(name, True))
            if is_hov:
                _draw_filled_circle(sx, sy, r,
                                    (*C_DIM[:3], alpha * C_DIM[3]))
                label = _best_label(name)
                _draw_text_centered(label, sx, sy, 11,
                                    (*C_TEXT[:3], alpha),
                                    max_width=r * 1.8)
        else:
            label, missing = _slot_label_text(name)
            col = C_TEXT_EMPTY if missing else C_TEXT
            _draw_text_centered(label, sx, sy, 11,
                                (*col[:3], alpha * (0.6 if missing else 1.0)),
                                max_width=r * 1.8)
    elif fallback_label:
        _draw_text_centered(fallback_label, sx, sy, 10,
                            (*C_TEXT_EMPTY[:3], alpha * 0.6))


def _outline_appearance(is_hovered, fixed, cfg_colour, cfg_width):
    """Return (rgb, width) for a slot/sub-slot outline ring.

    fixed=True  -> always the configured colour/width (legacy behaviour).
    fixed=False -> configured colour/width only while hovered; at rest, the thin
                   grey resting outline (RESTING_OUTLINE_COLOUR / _WIDTH).
    Pure: no GPU calls. Unit-tested by test_resting_outline."""
    if fixed or is_hovered:
        return cfg_colour, cfg_width
    return RESTING_OUTLINE_COLOUR, RESTING_OUTLINE_WIDTH


# ── main entry point ──────────────────────────────────────────────────────────
def draw_palette(state):
    cx        = state['cx'];          cy        = state['cy']
    R         = state['radius'];      sr        = state['slot_r']
    slots     = state['slots'];       sub_slots = state['sub_slots']
    hov_slot  = state['hovered_slot']
    hov_sub   = state['hovered_sub']
    sub_vis   = state['sub_visible']
    sub_alpha = state.get('sub_alpha', {})
    alpha     = state.get('alpha', 1.0)
    sub_sf    = state.get('sub_size_factor', 0.9)
    sub_sr    = sr * sub_sf
    sep       = state.get('sub_separation', 60.0)
    glow_sz   = state.get('glow_size', 1.6)
    glow_in   = state.get('glow_intensity', 0.35)
    glow_fo   = state.get('glow_falloff', 1.0)
    glow_all  = state.get('glow_all', False)   # preview: glow on every slot
    # Per-category outline width + colour (colour also drives that category's glow)
    slot_outline_w  = state.get('slot_outline_width', 4.8)
    sub_outline_w   = state.get('subslot_outline_width', 3.3)
    slot_outline_c  = tuple(state.get('slot_outline_colour', (0.90, 0.90, 0.90)))[:3]
    sub_outline_c   = tuple(state.get('subslot_outline_colour', (0.60, 0.60, 0.60)))[:3]
    fixed       = state.get('fixed_slot_outline', True)
    n_slots   = state.get('num_slots', len(slots) if slots else 8)

    gpu.state.blend_set('ALPHA')

    _draw_filled_circle(cx, cy, 5, (*C_CENTER[:3], alpha * C_CENTER[3]))
    _draw_center(state)

    for i in range(n_slots):
        a = _slot_angle(i, n_slots)
        _draw_line(cx, cy,
                   cx + math.cos(a) * R, cy + math.sin(a) * R,
                   (*C_SPOKE[:3], alpha * C_SPOKE[3]))

    for i in sub_vis:
        sa = sub_alpha.get(i, 1.0) * alpha
        if sa <= 0.01:
            continue
        positions = _sub_positions(cx, cy, R, sr, i, sub_sr, sep, n_slots)
        subs_i    = sub_slots[i] if i < len(sub_slots) else []

        for k, (sx, sy) in enumerate(positions):
            name = subs_i[k] if k < len(subs_i) else ""
            if not name:
                continue

            is_hov  = (hov_sub == (i, k))
            bg_col  = (*C_BG_HOVER[:3], sa) if is_hov else (*C_BG[:3], sa * 0.88)
            # Outline colour/width from the Fixed Slot Outline rule: configured
            # sub-slot colour/width, or the thin grey resting outline at rest when
            # the toggle is off. Hover full alpha, non-hover slightly dimmer.
            o_rgb, o_w = _outline_appearance(is_hov, fixed, sub_outline_c, sub_outline_w)
            outline_col = (*o_rgb, sa) if is_hov else (*o_rgb, sa * 0.85)

            if is_hov or glow_all:
                _draw_radial_glow(sx, sy, sub_sr * glow_sz, sub_outline_c,
                                  glow_in * sa, glow_fo)
            _draw_filled_circle(sx, sy, sub_sr, bg_col)
            _draw_slot_contents(sx, sy, sub_sr, name, is_hov, sa)
            _draw_ring(sx, sy, sub_sr, o_w, outline_col)

    for i in range(n_slots):
        a    = _slot_angle(i, n_slots)
        sx   = cx + math.cos(a) * R
        sy   = cy + math.sin(a) * R
        name     = slots[i] if i < len(slots) else ""
        is_hov   = (hov_slot == i)
        is_empty = not name

        bg_col = (*C_BG_HOVER[:3], alpha) if is_hov else (*C_BG[:3], alpha * 0.88)

        # Empty slots keep their dim neutral ring. Assigned slots follow the Fixed
        # Slot Outline rule: configured slot colour/width, or the thin grey resting
        # outline at rest when the toggle is off (see _outline_appearance).
        if is_empty:
            outline_col = (*C_RING_EMPTY[:3], alpha * 0.55)
            outline_w   = slot_outline_w
        else:
            o_rgb, outline_w = _outline_appearance(is_hov, fixed, slot_outline_c, slot_outline_w)
            outline_col = (*o_rgb, alpha)

        # In the settings preview (glow_all) show the glow on every main slot so
        # the user can judge Gradient Size/Intensity/Falloff across the wheel.
        if is_hov or glow_all:
            _draw_radial_glow(sx, sy, sr * glow_sz, slot_outline_c,
                              glow_in * alpha, glow_fo)
        _draw_filled_circle(sx, sy, sr, bg_col)
        _draw_slot_contents(sx, sy, sr, name, is_hov, alpha,
                            fallback_label=str(i + 1))
        _draw_ring(sx, sy, sr, outline_w, outline_col)

    gpu.state.blend_set('NONE')
    gpu.state.line_width_set(1.0)
