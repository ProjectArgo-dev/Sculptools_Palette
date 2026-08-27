# Changelog

All notable changes to **Sculptools: Palette** are listed here, newest first.

## 1.2.2 — 2026-08-27

### Added

- **"Add brush to Palette" now works from the toolbar as well.** Right-clicking one of
  the brush buttons at the top of the Sculpt toolbar offers the same entry as the asset
  shelf, and adds the brush that button stands for — Mask, Face Set Paint, and so on.
  Your active tool is left as you had it.

### Fixed

- **Startup gets faster every launch after the first.** The add-on now remembers which
  file each of your brushes lives in, and which files hold no brushes at all, so it goes
  straight to the few that matter instead of walking your Asset Libraries again. The
  first launch after updating still does the full pass — that is the one that builds the
  index — and the difference shows from the second onwards. The larger your libraries,
  the larger the saving. Reported in issue #3.
- **A brush no longer goes missing when you reorganise your Asset Library.** Moving or
  renaming the folder a brush lives in, or moving the brush to another `.blend`, could
  leave its slot showing *not found* for good. The add-on now falls back to a full search
  and relearns where the brush went.
- **A palette hotkey bound to a number key now works.** With Quick Numbers on, binding
  Open or Cycle Palette to a plain number did nothing: the key selected that slot
  instead. The hotkey you set now wins, and a note under the field points out that the
  number is no longer available to Quick Numbers — adding a modifier keeps both.
- **Hotkeys are shown the way they are printed on the key.** A palette opened with the
  number 6 read *"Six to open Palette"*; the backtick key read *"Accent Grave"*.
- **Backward palette cycling follows the cycle key.** After rebinding the cycle key,
  Shift + the *previous* key could keep cycling backwards until you next opened the wheel.

## 1.2.1 — 2026-08-24

### Fixed

- **Entering Sculpt Mode for the first time no longer freezes Blender.** The add-on
  prepares the thumbnails for every palette the first time you enter Sculpt Mode in a
  session. That work now runs in small slices between redraws instead of all in one go,
  so the viewport stays responsive while it finishes. Reported in issue #3.
- **Thumbnails load several times faster.** Reading the artwork for Blender's bundled
  brushes dropped to roughly a tenth of what it cost before, on Blender 4.5 and 5.x alike.
- **The wait no longer grows with the size of your Asset Libraries.** A palette entry that
  could not be found used to send the add-on through every `.blend` file in every
  configured library in a single uninterruptible pass.

## 1.2.0 — 2026-08-08

### Added

- **Fixed Sub-Slot Visibility**, a new toggle in *Palette Appearance* (off by default).
  With it on, every sub-slot stays open for as long as the wheel is, instead of appearing
  after the hover delay and fading out again. Flick selection still reaches main slots
  only, as before.

### Fixed

- The inner edge of slot thumbnails is smoother: the circular fade ended a fraction too
  far out, which left a faintly ragged rim that shifted around the circle.

## 1.1.0 — 2026-07-30

### Added

- **Custom hotkeys now survive a restart.** The Open Palette and Cycle Palette keys you
  set in the **Palette** sidebar tab are stored in your preferences instead of being
  rebuilt from the defaults every time Blender starts.
- **Hotkeys travel with presets.** Exporting a preset now records your hotkeys along with
  the palettes and their appearance; importing offers an **Import hotkeys** checkbox so a
  shared preset can bring the palettes without touching your own keys.
- **Reset Hotkeys** button in *Palette Utilities* — restores the three defaults
  (`\` to open, `Tab` to cycle, `Ctrl` for jump-to) and nothing else.
- **Warning when Blender's "Save on Exit" is off.** With that preference disabled, nothing
  the add-on stores — palettes, brush and tool assignments, hotkeys — ever reaches disk,
  and it all disappears on restart. The **Palette** panel now says so, with a
  **Save Preferences** button, instead of losing the work silently.
- **Hold to keep flick mode armed.** Keeping the open key held down keeps the quick-flick
  gesture alive for as long as you need, so you can pause and aim before committing.

### Changed

- While the open key is held, a flick commits once the cursor passes three quarters of the
  wheel radius rather than half. A tap followed by a flick behaves exactly as before.
- The extension's *Website* link now points to the listing on
  [extensions.blender.org](https://extensions.blender.org/add-ons/sculptools-palette/),
  and the extension carries the **3D View** tag.

### Fixed

- **Holding the open hotkey no longer closes the palette** after roughly half a second.
  The operating system's key auto-repeat was indistinguishable from a deliberate second
  press, so the wheel toggled itself shut while you were still deciding
  ([issue #1](https://github.com/ProjectArgo-dev/Sculptools_Palette/issues/1)).
- Clicking a slot could raise an error just after switching to a palette with fewer slots
  than the previous one.
- Opening the *Palette Utilities* panel could cancel a hotkey capture that was in
  progress.
- Reloading the add-on in the middle of a right-click drag left a stale slider overlay
  behind.

## 1.0.0 — 2026-07-23

First release on the Blender Extensions Platform: the radial palette for sculpt brushes
and tools, up to 8 palettes of 10 slots × 3 sub-slots, Quick Numbers, Jump-to, Dynamic
Brush Sliders, real Asset-library thumbnails, a live Preview Editor, and preset
import/export.
