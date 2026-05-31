# FocusFortress Warnings Design

## Scope

Implement the Version 1 warning layer from `report.txt`: per-block warning settings, custom message and sound, volume, centered always-on-top popup, duration, fade-out, test warning, persistence, and a trigger when a block becomes active.

## Architecture

`focusfortress.models` owns a new `WarningConfig` dataclass attached to each `BlockList`. `AppConfig.from_dict()` accepts old config files by defaulting missing warning data.

`focusfortress.engine.Engine` continues to decide which blocks are effective. After applying rules, it compares the current active block-name set with the previous set and emits warning events only for newly active blocks with enabled warning settings. The engine exposes callback registration and emits data-only events; it does not construct PyQt widgets or play audio.

`focusfortress.ui.warning_popup` owns the PyQt warning presentation. It shows one centered popup at a time, uses the app theme, plays optional audio through QtMultimedia, stops audio when the popup closes, supports auto-close and click-to-close dismiss modes, and fades out when configured.

`focusfortress.ui.tabs.blocks_tab` adds a Warning sub-tab to the existing block editor. The tab edits the selected block's `WarningConfig`, supports browsing for `.mp3`, `.wav`, and `.ogg`, and provides a Test warning button.

## Data Flow

1. User edits warning settings in Blocks > Warning.
2. Settings are saved with the selected block.
3. Engine ticks or manual toggles call `_apply()`.
4. `_apply()` computes active blocks and emits each newly active warning once.
5. MainWindow receives the event on the Qt thread and asks WarningManager to show it.

## Error Handling

Missing, moved, or unsupported audio files must not block the popup. Test sound failures are reported through the existing error dialog. Runtime warning playback failures are ignored after showing the popup.

If multiple blocks activate in the same engine pass, only the first enabled warning is emitted to avoid popup spam.

## Testing

Tests cover:

- Default and backward-compatible `WarningConfig` loading.
- Warning event emission for inactive-to-active transitions only.
- Manual enable emitting a warning through the same engine path.
- Warning event suppression when warning is disabled.
