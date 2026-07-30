# Changelog

All notable changes to **Sculptools: Palette** are listed here, newest first.

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
