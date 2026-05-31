"""Tests for the extended warning behaviours (repeat, lock, pomodoro,
config round-trip, built-in sounds)."""
from __future__ import annotations

import datetime as dt
import tempfile
import time
import unittest

from focusfortress.engine import Engine
from focusfortress.models import AppConfig, BlockList, WarningConfig
from focusfortress.sounds import builtin_sound_names, ensure_builtin_sounds


def _shell() -> Engine:
    e = Engine.__new__(Engine)
    e._active_block_names = set()
    e._last_warning_at = {}
    e._locked_block_names = set()
    e._previous_active_block_keys = set()
    e._active_warning_blocks = set()
    e._warning_listeners = []
    e._warning_handler = None
    e._warning_callback = None
    e._pending_warning_events = []
    return e


class RepeatWarningTests(unittest.TestCase):
    def test_repeat_fires_when_interval_elapsed(self) -> None:
        e = _shell()
        events = []
        e.set_warning_handler(events.append)
        block = BlockList(
            name="YouTube",
            warning=WarningConfig(enabled=True, message="again", repeat_minutes=1),
        )
        e._active_block_names = {"YouTube"}                 # already active
        e._last_warning_at = {"YouTube": time.time() - 120}  # 2 min ago

        e._dispatch_block_warnings([block])

        self.assertEqual([ev.block_name for ev in events], ["YouTube"])

    def test_repeat_suppressed_before_interval(self) -> None:
        e = _shell()
        events = []
        e.set_warning_handler(events.append)
        block = BlockList(
            name="YouTube",
            warning=WarningConfig(enabled=True, message="again", repeat_minutes=5),
        )
        e._active_block_names = {"YouTube"}
        e._last_warning_at = {"YouTube": time.time()}  # just now

        e._dispatch_block_warnings([block])

        self.assertEqual(events, [])


class LockWarningTests(unittest.TestCase):
    def _timer_block(self, on_unlock: bool) -> BlockList:
        block = BlockList(
            name="Locked",
            warning=WarningConfig(enabled=True, message="lock done", on_lock_unlock=on_unlock),
        )
        block.lock.kind = "timer"
        block.lock.until = dt.datetime(2020, 1, 1, 12, 0).isoformat()
        return block

    def test_lock_unlock_warns_once(self) -> None:
        e = _shell()
        events = []
        e.set_warning_handler(events.append)
        block = self._timer_block(on_unlock=True)
        e._locked_block_names = {"Locked"}
        after = dt.datetime(2020, 1, 1, 13, 0)

        e._dispatch_lock_warnings([block], after)
        e._dispatch_lock_warnings([block], after)

        self.assertEqual([ev.block_name for ev in events], ["Locked"])

    def test_lock_unlock_disabled_does_not_warn(self) -> None:
        e = _shell()
        events = []
        e.set_warning_handler(events.append)
        block = self._timer_block(on_unlock=False)
        e._locked_block_names = {"Locked"}

        e._dispatch_lock_warnings([block], dt.datetime(2020, 1, 1, 13, 0))

        self.assertEqual(events, [])

    def test_report_unlock_blocked_emits_when_enabled(self) -> None:
        e = _shell()
        events = []
        e.set_warning_handler(events.append)
        block = BlockList(
            name="Focus",
            warning=WarningConfig(enabled=True, message="nope", on_early_unlock=True),
        )
        e.config = AppConfig(blocks=[block])

        e.report_unlock_blocked("Focus")

        self.assertEqual([ev.message for ev in events], ["nope"])

    def test_report_unlock_blocked_silent_when_disabled(self) -> None:
        e = _shell()
        events = []
        e.set_warning_handler(events.append)
        block = BlockList(name="Focus", warning=WarningConfig(enabled=True))
        e.config = AppConfig(blocks=[block])

        e.report_unlock_blocked("Focus")

        self.assertEqual(events, [])


class PomodoroWarningTests(unittest.TestCase):
    def test_phase_warning_emits_when_enabled(self) -> None:
        e = _shell()
        e.config = AppConfig()
        e.config.settings.pomodoro.phase_warnings = True
        events = []
        e.set_warning_handler(events.append)

        e._fire_pomodoro_warning("Focus time.")

        self.assertEqual([ev.message for ev in events], ["Focus time."])

    def test_phase_warning_silent_when_disabled(self) -> None:
        e = _shell()
        e.config = AppConfig()
        e.config.settings.pomodoro.phase_warnings = False
        events = []
        e.set_warning_handler(events.append)

        e._fire_pomodoro_warning("Focus time.")

        self.assertEqual(events, [])


class ExtendedConfigRoundTripTests(unittest.TestCase):
    def test_new_fields_round_trip(self) -> None:
        cfg = AppConfig(blocks=[
            BlockList(
                name="X",
                warning=WarningConfig(
                    enabled=True,
                    popup_mode="fullscreen",
                    repeat_minutes=10,
                    loop_sound=True,
                    sound_max_seconds=5,
                    close_delay_seconds=3,
                    hold_seconds=4,
                    on_lock_unlock=True,
                    on_early_unlock=True,
                    image_path="a.png",
                    theme="red_alert",
                    messages=["a", "b"],
                ),
            )
        ])

        loaded = AppConfig.from_dict(cfg.to_dict()).blocks[0].warning

        self.assertEqual(loaded.popup_mode, "fullscreen")
        self.assertEqual(loaded.repeat_minutes, 10)
        self.assertTrue(loaded.loop_sound)
        self.assertEqual(loaded.sound_max_seconds, 5)
        self.assertEqual(loaded.close_delay_seconds, 3)
        self.assertEqual(loaded.hold_seconds, 4)
        self.assertTrue(loaded.on_lock_unlock)
        self.assertTrue(loaded.on_early_unlock)
        self.assertEqual(loaded.image_path, "a.png")
        self.assertEqual(loaded.theme, "red_alert")
        self.assertEqual(loaded.messages, ["a", "b"])

    def test_default_extended_fields_are_pruned(self) -> None:
        # A warning with only core fields set must serialise to exactly the
        # nine documented keys (no popup_mode/loop_sound/etc. noise).
        cfg = AppConfig(blocks=[BlockList(name="Y", warning=WarningConfig(enabled=True))])
        warning_dict = cfg.to_dict()["blocks"][0]["warning"]
        self.assertEqual(
            set(warning_dict),
            {
                "enabled", "message", "sound_path", "volume",
                "popup_duration_seconds", "fade_enabled", "fade_seconds",
                "always_on_top", "dismiss_mode",
            },
        )


class BuiltinSoundTests(unittest.TestCase):
    def test_sounds_are_generated(self) -> None:
        got = ensure_builtin_sounds(tempfile.mkdtemp())
        self.assertEqual(set(got), set(builtin_sound_names()))
        for path in got.values():
            with open(path, "rb") as fh:
                self.assertEqual(fh.read(4), b"RIFF")  # WAV header


if __name__ == "__main__":
    unittest.main()
