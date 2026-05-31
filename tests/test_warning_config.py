import unittest

import focusfortress.models as models


class WarningConfigTests(unittest.TestCase):
    def test_warning_config_model_exists(self) -> None:
        self.assertIsNotNone(
            getattr(models, "WarningConfig", None),
            "WarningConfig should be a persisted per-block settings model",
        )

    def test_old_block_config_gets_default_warning_settings(self) -> None:
        WarningConfig = getattr(models, "WarningConfig", None)
        if WarningConfig is None:
            self.skipTest("WarningConfig is not implemented yet")

        cfg = models.AppConfig.from_dict({
            "blocks": [
                {
                    "name": "Legacy block",
                    "enabled": False,
                    "sites": ["youtube.com"],
                }
            ],
            "settings": {},
        })

        self.assertIsInstance(cfg.blocks[0].warning, WarningConfig)
        self.assertFalse(cfg.blocks[0].warning.enabled)
        self.assertEqual(cfg.blocks[0].warning.volume, 80)
        self.assertEqual(cfg.blocks[0].warning.popup_duration_seconds, 8)
        self.assertTrue(cfg.blocks[0].warning.fade_enabled)
        self.assertEqual(cfg.blocks[0].warning.fade_seconds, 2)
        self.assertTrue(cfg.blocks[0].warning.always_on_top)

    def test_warning_settings_round_trip(self) -> None:
        WarningConfig = getattr(models, "WarningConfig", None)
        if WarningConfig is None:
            self.skipTest("WarningConfig is not implemented yet")

        cfg = models.AppConfig(blocks=[
            models.BlockList(
                name="Gaming",
                warning=WarningConfig(
                    enabled=True,
                    message="Time is up",
                    sound_path=r"C:\Sounds\alarm.mp3",
                    volume=65,
                    popup_duration_seconds=12,
                    fade_enabled=False,
                    fade_seconds=0,
                    always_on_top=False,
                ),
            )
        ])

        loaded = models.AppConfig.from_dict(cfg.to_dict())

        warning = loaded.blocks[0].warning
        self.assertTrue(warning.enabled)
        self.assertEqual(warning.message, "Time is up")
        self.assertEqual(warning.sound_path, r"C:\Sounds\alarm.mp3")
        self.assertEqual(warning.volume, 65)
        self.assertEqual(warning.popup_duration_seconds, 12)
        self.assertFalse(warning.fade_enabled)
        self.assertEqual(warning.fade_seconds, 0)
        self.assertFalse(warning.always_on_top)


if __name__ == "__main__":
    unittest.main()
