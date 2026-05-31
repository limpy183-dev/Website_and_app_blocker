from __future__ import annotations

import unittest
from unittest.mock import patch

from focusfortress import engine as engine_module
from focusfortress.engine import Engine
from focusfortress.models import AppConfig, BlockList


class _FakeProxy:
    def set_rules(self, *_args) -> None:
        pass

    def set_block_page(self, *_args) -> None:
        pass


class _FakeApps:
    def set_rules(self, *_args) -> None:
        pass


def _quiet_engine(config: AppConfig) -> Engine:
    with patch.object(engine_module, "load_config", return_value=config):
        eng = Engine()
    eng.config = config
    eng._proxy = _FakeProxy()
    eng._apps = _FakeApps()
    return eng


class WarningConfigModelTests(unittest.TestCase):
    def test_block_warning_settings_round_trip_with_defaults(self) -> None:
        block = BlockList(
            name="Gaming Limit",
            warning_enabled=True,
            warning_message="Time is up. Close the game and go revise.",
            warning_sound_path=r"C:\Sounds\alarm.mp3",
            warning_volume=80,
            warning_popup_duration_seconds=10,
            warning_fade_enabled=True,
            warning_fade_seconds=2,
            warning_always_on_top=True,
            warning_dismiss_mode="click_to_close",
        )

        restored = AppConfig.from_dict(AppConfig(blocks=[block]).to_dict()).blocks[0]

        self.assertTrue(restored.warning_enabled)
        self.assertEqual(restored.warning_message, "Time is up. Close the game and go revise.")
        self.assertEqual(restored.warning_sound_path, r"C:\Sounds\alarm.mp3")
        self.assertEqual(restored.warning_volume, 80)
        self.assertEqual(restored.warning_popup_duration_seconds, 10)
        self.assertTrue(restored.warning_fade_enabled)
        self.assertEqual(restored.warning_fade_seconds, 2)
        self.assertTrue(restored.warning_always_on_top)
        self.assertEqual(restored.warning_dismiss_mode, "click_to_close")

        legacy = AppConfig.from_dict({"blocks": [{"name": "Legacy"}], "settings": {}}).blocks[0]
        self.assertFalse(legacy.warning_enabled)
        self.assertEqual(legacy.warning_message, "")
        self.assertEqual(legacy.warning_sound_path, "")
        self.assertEqual(legacy.warning_volume, 80)
        self.assertEqual(legacy.warning_popup_duration_seconds, 10)
        self.assertTrue(legacy.warning_fade_enabled)
        self.assertEqual(legacy.warning_fade_seconds, 2)
        self.assertTrue(legacy.warning_always_on_top)
        self.assertEqual(legacy.warning_dismiss_mode, "auto_close")


class WarningTriggerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.patchers = [
            patch.object(engine_module, "write_block_section"),
            patch.object(engine_module, "clear_block_section"),
            patch.object(engine_module, "flush_dns"),
            patch.object(engine_module, "set_task_manager_blocked"),
            patch.object(engine_module, "set_time_change_blocked"),
            patch.object(engine_module, "force_protect"),
            patch.object(engine_module, "selfprotect"),
            patch.object(engine_module, "_watchdog"),
        ]
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in reversed(self.patchers):
            patcher.stop()

    def test_warning_emits_once_per_active_transition(self) -> None:
        block = BlockList(
            name="Gaming Limit",
            enabled=True,
            warning_enabled=True,
            warning_message="Close the game.",
        )
        eng = _quiet_engine(AppConfig(blocks=[block]))
        events = []
        eng.set_warning_handler(events.append)

        eng._apply()
        eng._apply()
        block.enabled = False
        eng._apply()
        block.enabled = True
        eng._apply()

        self.assertEqual([event.block_name for event in events], ["Gaming Limit", "Gaming Limit"])
        self.assertEqual(events[0].message, "Close the game.")

    def test_allowance_expiry_emits_when_block_resumes(self) -> None:
        block = BlockList(
            name="YouTube",
            enabled=True,
            warning_enabled=True,
            warning_message="Your YouTube allowance is finished.",
        )
        block.allowance.minutes_per_day = 5
        block.allowance.minutes_left_today = 5
        eng = _quiet_engine(AppConfig(blocks=[block]))
        events = []
        eng.set_warning_handler(events.append)

        eng._apply()
        block.allowance.minutes_left_today = 0
        eng._apply()
        eng._apply()

        self.assertEqual([event.block_name for event in events], ["YouTube"])
        self.assertEqual(events[0].message, "Your YouTube allowance is finished.")

    def test_disabled_warning_does_not_emit(self) -> None:
        block = BlockList(name="Quiet", enabled=True, warning_enabled=False)
        eng = _quiet_engine(AppConfig(blocks=[block]))
        events = []
        eng.set_warning_handler(events.append)

        eng._apply()

        self.assertEqual(events, [])


if __name__ == "__main__":
    unittest.main()
