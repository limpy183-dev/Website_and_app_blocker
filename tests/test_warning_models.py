import unittest

from focusfortress.models import AppConfig, WarningConfig


class WarningModelTests(unittest.TestCase):
    def test_old_block_config_gets_default_warning_config(self) -> None:
        cfg = AppConfig.from_dict(
            {
                "blocks": [
                    {
                        "name": "Legacy block",
                        "enabled": True,
                        "sites": ["youtube.com"],
                    }
                ],
                "settings": {},
            }
        )

        self.assertEqual(len(cfg.blocks), 1)
        warning = cfg.blocks[0].warning
        self.assertIsInstance(warning, WarningConfig)
        self.assertFalse(warning.enabled)
        self.assertEqual(warning.message, "")
        self.assertEqual(warning.volume, 80)
        self.assertEqual(warning.popup_duration_seconds, 8)
        self.assertTrue(warning.fade_enabled)
        self.assertEqual(warning.fade_seconds, 2)
        self.assertTrue(warning.always_on_top)
        self.assertEqual(warning.dismiss_mode, "auto_close")

    def test_warning_config_round_trips_through_app_config(self) -> None:
        raw = {
            "blocks": [
                {
                    "name": "YouTube",
                    "warning": {
                        "enabled": True,
                        "message": "GET OFF YOUTUBE AND GO REVISE",
                        "sound_path": "C:/Sounds/scream.mp3",
                        "volume": 85,
                        "popup_duration_seconds": 9,
                        "fade_enabled": False,
                        "fade_seconds": 3,
                        "always_on_top": False,
                        "dismiss_mode": "click_to_close",
                    },
                }
            ],
            "settings": {},
        }

        cfg = AppConfig.from_dict(raw)
        warning = cfg.blocks[0].warning

        self.assertTrue(warning.enabled)
        self.assertEqual(warning.message, "GET OFF YOUTUBE AND GO REVISE")
        self.assertEqual(warning.sound_path, "C:/Sounds/scream.mp3")
        self.assertEqual(warning.volume, 85)
        self.assertEqual(warning.popup_duration_seconds, 9)
        self.assertFalse(warning.fade_enabled)
        self.assertEqual(warning.fade_seconds, 3)
        self.assertFalse(warning.always_on_top)
        self.assertEqual(warning.dismiss_mode, "click_to_close")
        self.assertEqual(cfg.to_dict()["blocks"][0]["warning"], raw["blocks"][0]["warning"])


if __name__ == "__main__":
    unittest.main()
