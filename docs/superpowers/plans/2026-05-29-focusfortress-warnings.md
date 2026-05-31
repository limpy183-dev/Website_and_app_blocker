# FocusFortress Warnings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a native warning and alarm layer to FocusFortress blocks.

**Architecture:** Add `WarningConfig` to block persistence, emit data-only warning events from the engine when blocks become active, and render popup/audio warnings in PyQt on the main thread.

**Tech Stack:** Python dataclasses, `unittest`, PyQt6 Widgets, PyQt6 QtMultimedia.

---

### Task 1: Model And Engine Warning Events

**Files:**
- Modify: `focusfortress/models.py`
- Modify: `focusfortress/engine.py`
- Create: `tests/test_warnings.py`

- [ ] **Step 1: Write failing model tests**

```python
from focusfortress.models import AppConfig, BlockList, WarningConfig

def test_block_list_has_default_disabled_warning():
    block = BlockList(name="YouTube")
    assert isinstance(block.warning, WarningConfig)
    assert block.warning.enabled is False
    assert block.warning.volume == 80

def test_old_config_without_warning_loads_default_warning():
    cfg = AppConfig.from_dict({"blocks": [{"name": "Legacy"}], "settings": {}})
    assert cfg.blocks[0].warning == WarningConfig()
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m unittest tests.test_warnings -v`

Expected: import or attribute failure because `WarningConfig` and `BlockList.warning` do not exist.

- [ ] **Step 3: Implement model**

Add `WarningConfig` and a `warning` field to `BlockList`. Update `AppConfig.from_dict()` to parse `warning` separately and default it when absent.

- [ ] **Step 4: Write failing engine tests**

```python
import datetime as dt
import unittest
from unittest.mock import patch

from focusfortress.engine import Engine
from focusfortress.models import AppConfig, BlockList, WarningConfig

class EngineWarningTests(unittest.TestCase):
    def make_engine(self, block):
        with patch("focusfortress.engine.load_config", return_value=AppConfig(blocks=[block])):
            engine = Engine()
        engine._proxy = _FakeProxy()
        engine._apps = _FakeApps()
        return engine

    def test_apply_emits_warning_once_when_block_becomes_active(self):
        block = BlockList(
            name="YouTube",
            enabled=True,
            warning=WarningConfig(enabled=True, message="Stop"),
        )
        engine = self.make_engine(block)
        events = []
        engine.add_warning_listener(events.append)
        engine._apply()
        engine._apply()
        self.assertEqual([event.block_name for event in events], ["YouTube"])
```

- [ ] **Step 5: Run tests and verify failure**

Run: `python -m unittest tests.test_warnings -v`

Expected: failure because warning listener/event APIs do not exist.

- [ ] **Step 6: Implement engine event support**

Add a `WarningEvent` dataclass, listener registration, active block tracking, and `_emit_warning_events()` called from `_apply()` after effective active blocks are known.

- [ ] **Step 7: Run tests and verify pass**

Run: `python -m unittest tests.test_warnings -v`

Expected: all warning model and engine tests pass.

### Task 2: PyQt Popup And Audio Manager

**Files:**
- Create: `focusfortress/ui/warning_popup.py`
- Modify: `focusfortress/ui/main_window.py`

- [ ] **Step 1: Implement `WarningPopup` and `WarningManager`**

Create a centered styled `QDialog`, optional `QMediaPlayer`/`QAudioOutput` playback, auto-close timer, click-to-close button, and fade-out animation.

- [ ] **Step 2: Wire MainWindow to engine warnings**

Register a listener with `engine.add_warning_listener()` and bridge events to a `pyqtSignal` so UI display happens on the Qt thread.

### Task 3: Blocks Warning Tab

**Files:**
- Modify: `focusfortress/ui/tabs/blocks_tab.py`

- [ ] **Step 1: Add Warning tab widgets**

Add enable checkbox, message editor, sound path picker, volume slider, duration spin box, fade controls, always-on-top checkbox, dismiss-mode combo, Test warning button, and Save button.

- [ ] **Step 2: Bind selected block data**

Populate widgets from `self._current.warning`, save changes back to the block, and refresh when selection changes.

- [ ] **Step 3: Test warning**

Use `WarningManager` or a local manager instance to preview the selected warning config without changing block state.

### Task 4: Verification

**Files:**
- No new files.

- [ ] **Step 1: Run unit tests**

Run: `python -m unittest tests.test_warnings -v`

Expected: all tests pass.

- [ ] **Step 2: Import-check UI modules**

Run: `python -m compileall focusfortress tests`

Expected: all project Python files compile.

- [ ] **Step 3: Launch smoke test if possible**

Run: `python _test_launch.py`

Expected: app creates a main window and exits after printing diagnostics.
