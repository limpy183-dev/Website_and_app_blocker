import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QTabWidget

from focusfortress.models import AppConfig, BlockList
from focusfortress.ui.tabs.blocks_tab import BlocksTab


class DummyEngine:
    def __init__(self) -> None:
        self.config = AppConfig(blocks=[BlockList(name="Distractions")])
        self.save_count = 0

    def save(self) -> None:
        self.save_count += 1

    def set_block_enabled(self, name: str, enabled: bool) -> bool:
        self.config.blocks[0].enabled = enabled
        return True

    def grant_allowance(self, block_name: str, minutes: int) -> bool:
        return True


class WarningUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_warning_tab_exists_and_saves_config(self) -> None:
        engine = DummyEngine()
        tab = BlocksTab(engine)
        tab.list.setCurrentRow(0)

        sub_tabs = tab.findChild(QTabWidget)
        labels = [sub_tabs.tabText(i) for i in range(sub_tabs.count())]
        self.assertIn("Warning", labels)

        tab.warning_enabled.setChecked(True)
        tab.warning_message.setPlainText("GET OFF YOUTUBE AND GO REVISE")
        tab.warning_sound_path.setText("C:/Sounds/scream.mp3")
        tab.warning_volume.setValue(85)
        tab.warning_duration.setValue(8)
        tab.warning_fade_enabled.setChecked(True)
        tab.warning_fade_seconds.setValue(2)
        tab.warning_dismiss_mode.setCurrentData("click_to_close")

        tab._save_warning()

        warning = engine.config.blocks[0].warning
        self.assertTrue(warning.enabled)
        self.assertEqual(warning.message, "GET OFF YOUTUBE AND GO REVISE")
        self.assertEqual(warning.sound_path, "C:/Sounds/scream.mp3")
        self.assertEqual(warning.volume, 85)
        self.assertEqual(warning.popup_duration_seconds, 8)
        self.assertTrue(warning.fade_enabled)
        self.assertEqual(warning.fade_seconds, 2)
        self.assertEqual(warning.dismiss_mode, "click_to_close")
        self.assertGreater(engine.save_count, 0)


if __name__ == "__main__":
    unittest.main()
