import unittest

from focusfortress.engine import Engine
from focusfortress.models import BlockList, WarningConfig


class WarningEngineTests(unittest.TestCase):
    def _engine(self):
        engine = object.__new__(Engine)
        engine._previous_active_block_keys = set()
        engine._warning_handler = None
        engine._pending_warning_events = []
        return engine

    def _active_blocks(self, *blocks: BlockList):
        return {(index, block.name): block for index, block in enumerate(blocks)}

    def test_emits_warning_once_for_newly_active_block(self) -> None:
        events = []
        engine = self._engine()
        engine.set_warning_handler(events.append)
        block = BlockList(
            name="YouTube",
            warning=WarningConfig(enabled=True, message="Stop scrolling"),
        )

        engine._emit_newly_active_warnings(self._active_blocks(block))
        engine._emit_newly_active_warnings(self._active_blocks(block))

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].block_name, "YouTube")
        self.assertEqual(events[0].config.message, "Stop scrolling")

    def test_emits_again_after_block_becomes_inactive_then_active(self) -> None:
        events = []
        engine = self._engine()
        engine.set_warning_handler(events.append)
        block = BlockList(name="Focus", warning=WarningConfig(enabled=True))

        engine._emit_newly_active_warnings(self._active_blocks(block))
        engine._emit_newly_active_warnings({})
        engine._emit_newly_active_warnings(self._active_blocks(block))

        self.assertEqual(len(events), 2)

    def test_disabled_warning_is_tracked_without_emitting(self) -> None:
        events = []
        engine = self._engine()
        engine.set_warning_handler(events.append)
        block = BlockList(name="Quiet", warning=WarningConfig(enabled=False))

        engine._emit_newly_active_warnings(self._active_blocks(block))
        block.warning.enabled = True
        engine._emit_newly_active_warnings(self._active_blocks(block))

        self.assertEqual(events, [])

    def test_pending_warnings_flush_when_handler_is_registered(self) -> None:
        events = []
        engine = self._engine()
        block = BlockList(name="Queued", warning=WarningConfig(enabled=True))

        engine._emit_newly_active_warnings(self._active_blocks(block))
        self.assertEqual(len(engine._pending_warning_events), 1)

        engine.set_warning_handler(events.append)

        self.assertEqual(engine._pending_warning_events, [])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].block_name, "Queued")


if __name__ == "__main__":
    unittest.main()
