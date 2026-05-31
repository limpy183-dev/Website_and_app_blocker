import unittest
from unittest.mock import patch

from focusfortress.engine import Engine
from focusfortress.models import AppConfig, BlockList, WarningConfig
from focusfortress.warnings import (
    WARNING_PRESETS,
    apply_warning_preset,
    resolve_warning_message,
)


class WarningConfigTests(unittest.TestCase):
    def test_legacy_configs_load_with_default_warning_config(self) -> None:
        cfg = AppConfig.from_dict(
            {
                "blocks": [
                    {
                        "name": "Legacy",
                        "enabled": False,
                        "sites": ["youtube.com"],
                        "future_block_key": "ignored",
                    }
                ],
                "settings": {"future_setting_key": "ignored"},
            }
        )

        self.assertEqual(cfg.blocks[0].name, "Legacy")
        self.assertEqual(cfg.blocks[0].sites, ["youtube.com"])
        self.assertIsInstance(cfg.blocks[0].warning, WarningConfig)
        self.assertFalse(cfg.blocks[0].warning.enabled)

    def test_preset_populates_warning_config_but_remains_editable(self) -> None:
        cfg = WarningConfig()

        apply_warning_preset(cfg, "red_alert")
        cfg.messages.append("CUSTOM LINE")

        self.assertIn("red_alert", WARNING_PRESETS)
        self.assertTrue(cfg.enabled)
        self.assertEqual(cfg.theme, "red_alert")
        self.assertIn("CUSTOM LINE", cfg.messages)

    def test_random_warning_message_uses_configured_lines(self) -> None:
        cfg = WarningConfig(
            enabled=True,
            message="fallback",
            messages=["GET OFF YOUTUBE.", "LOCK IN."],
        )

        with patch("focusfortress.warnings.random.choice", return_value="LOCK IN."):
            self.assertEqual(resolve_warning_message(cfg), "LOCK IN.")


class EngineWarningTriggerTests(unittest.TestCase):
    def test_apply_requests_first_newly_active_warning_once(self) -> None:
        engine = Engine.__new__(Engine)
        engine.config = AppConfig(
            blocks=[
                BlockList(
                    name="First",
                    enabled=True,
                    sites=["first.example"],
                    warning=WarningConfig(enabled=True, messages=["First warning"]),
                ),
                BlockList(
                    name="Second",
                    enabled=True,
                    sites=["second.example"],
                    warning=WarningConfig(enabled=True, messages=["Second warning"]),
                ),
            ]
        )
        engine._proxy = _FakeProxy()
        engine._apps = _FakeApps()
        engine._active_block_names = set()
        engine._last_warning_at = {}
        events: list[tuple[str, str]] = []
        engine.set_warning_callback(lambda block, reason: events.append((block.name, reason)))

        with _patched_engine_side_effects():
            engine._apply()
            engine._apply()

        self.assertEqual(events, [("First", "activated")])


class _FakeProxy:
    def set_rules(self, *_args) -> None:
        pass

    def set_block_page(self, *_args) -> None:
        pass


class _FakeApps:
    def set_rules(self, *_args) -> None:
        pass


def _patched_engine_side_effects():
    patches = [
        patch("focusfortress.engine.write_block_section"),
        patch("focusfortress.engine.clear_block_section"),
        patch("focusfortress.engine.flush_dns"),
        patch("focusfortress.engine.set_task_manager_blocked"),
        patch("focusfortress.engine.set_time_change_blocked"),
        patch("focusfortress.engine.force_protect.disable"),
        patch("focusfortress.engine.selfprotect.disable_kill_protection"),
        patch("focusfortress.engine._watchdog.stop_watchdog"),
    ]

    class _Patcher:
        def __enter__(self):
            for p in patches:
                p.start()

        def __exit__(self, exc_type, exc, tb):
            for p in reversed(patches):
                p.stop()
            return False

    return _Patcher()


if __name__ == "__main__":
    unittest.main()
