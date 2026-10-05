# Changelog

All notable changes to **Sculptools: Palette** are listed here, newest first.

## 1.3.2
### Changed

- **A number key closes the wheel.** With the wheel open, pressing a slot's number
  (Quick Numbers) switched brush but left the wheel on screen. It now closes, as it does
  after a click. A number with nothing assigned leaves the wheel open.
- **The Rename dialog is ready to type.** *Rename Palette* — and *New* / *Duplicate
  Palette*, which open it — now start with the name field active, like Blender's own
  rename. Before, typing did nothing until the field was clicked, and the keys could
  trigger shortcuts underneath it. Press `Enter` to confirm the name, then `Enter` again
  for OK.
- **A slot that cannot be activated now says so.** If the brush or tool in a slot cannot
  be activated — its library is missing, or the tool does not exist in this version of
  Blender — a warning names it, instead of nothing happening.
- **Messages carry the add-on's full name.** Status-bar messages, console lines and the
  add-on's entries in the Keymap editor now start with "Sculptools: Palette", so it is
  always clear which add-on they come from.

### Fixed

- **Custom hotkeys are no longer lost when Blender is opened from a `.blend` file.**
  Opening Blender by double-clicking a `.blend` left the wheel on its default hotkey for
  that session, and opening the Palette tab then saved the default over your own choice.
  Your hotkeys are now restored however Blender is started. If you lost one this way, set
  it once more. Palette thumbnails are also prepared again in such a session.
- **Every Essentials brush can be selected from the wheel.** Brushes newer than the
  add-on's own list — the Paint set (*Paint Blend*, *Paint Hard*…), *Scene Project* and
  others — could be assigned and showed their thumbnail, but choosing them did not change
  the brush. They all work now, including those future Blender versions will add.
  Reported in issue #4.
- **The wheel no longer stacks when its hotkey is `F`.** With Open Palette bound to `F`,
  each press opened another wheel on top of the last instead of closing it. `F` now opens
  and closes the wheel, and a Cycle Palette hotkey on `F` works too.
- **Refreshing thumbnails keeps your brush changes.** *Refresh Thumbnails*, and the
  thumbnail scan of your Asset Libraries, could drop the active brush or undo changes made
  in this session to Essentials brushes (strength, radius…). They are now left alone.
- **Opening a file with the wheel open no longer floods the console.** `Ctrl+N` or
  `Ctrl+O` with the wheel open left an error printed at every redraw until Blender was
  restarted.
- **No more "No asset found" errors in the console** when switching back to a brush you
  had already used.
- **Brushes saved as assets in the current file now activate** from the wheel (Blender
  5.1 and newer).

## 1.3.1
### Changed

- **The Preview Editor appears only in the viewport you are working in.** It used to be
  drawn in every 3D viewport, and four times in Quad View. It now shows where you switched
  it on, and moves to another viewport when you adjust one of its settings or cycle
  palettes from there. In Quad View it uses the main view. Closing that viewport's sidebar
  turns it off.
- **`Esc` cancels a Dynamic Brush Sliders drag.** Pressing `Esc` while right-dragging puts
  the brush Radius or Strength back to what it was. With the wheel open, the first `Esc`
  cancels the drag and keeps the wheel open; a second one closes it.

### Fixed

- **The wheel can no longer get stuck on screen.** Maximising the viewport (`Ctrl+Space`)
  or switching workspace while the wheel was open left it drawn and frozen until Blender
  was restarted. It now simply closes.
- **The wheel and the Radius / Strength readout stay in their own viewport.** With several
  viewports open, or in Quad View, they were drawn in all of them while responding in only
  one.
- **Smoother wheel and Preview Editor.** Drawing them takes a fraction of the time it did,
  which shows most when sculpting with the Preview Editor open.
- **Messages name tools properly.** Quick Numbers, assigning, cut / copy / paste messages
  and the *Paste* menu entry read "Box Mask" instead of `tool:box_mask`.
- **A damaged preset file can no longer break the wheel.** Invalid numbers in a preset
  could leave the wheel's size unusable, and saved that way; they are now ignored on
  import.

## 1.3.0
### Added

- **Show Wordmark**, a new toggle in *Palette Appearance* (on by default). Turning it
  off hides the PA\ETTE lettering at the centre of the wheel: the palette counter, name,
  hints and gear then close up and re-centre, leaving the middle of the wheel clearer.
  Left on, the wheel looks exactly as it did before.
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

## 1.2.1
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

## 1.2.0
### Added

- **Fixed Sub-Slot Visibility**, a new toggle in *Palette Appearance* (off by default).
  With it on, every sub-slot stays open for as long as the wheel is, instead of appearing
  after the hover delay and fading out again. Flick selection still reaches main slots
  only, as before.

### Fixed

- The inner edge of slot thumbnails is smoother: the circular fade ended a fraction too
  far out, which left a faintly ragged rim that shifted around the circle.

## 1.1.0
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

## 1.0.0
First release on the Blender Extensions Platform: the radial palette for sculpt brushes
and tools, up to 8 palettes of 10 slots × 3 sub-slots, Quick Numbers, Jump-to, Dynamic
Brush Sliders, real Asset-library thumbnails, a live Preview Editor, and preset
import/export.
