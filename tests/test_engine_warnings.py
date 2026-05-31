import unittest

import focusfortress.models as models
from focusfortress.engine import Engine


class EngineWarningEventTests(unittest.TestCase):
    def _new_engine_shell(self) -> Engine:
        engine = Engine.__new__(Engine)
        engine._active_warning_blocks = set()
        engine._warning_listeners = []
        return engine

    def test_active_block_warning_fires_once_until_block_reactivates(self) -> None:
        WarningConfig = getattr(models, "WarningConfig", None)
        if WarningConfig is None:
            self.skipTest("WarningConfig is not implemented yet")

        engine = self._new_engine_shell()
        emit = getattr(engine, "_emit_block_activation_warnings", None)
        self.assertIsNotNone(
            emit,
            "Engine should expose a small helper for active-block warning events",
        )
        if emit is None:
            return

        events: list[tuple[str, str]] = []
        engine.add_warning_listener(
            lambda block_name, warning: events.append((block_name, warning.message))
        )
        block = models.BlockList(
            name="YouTube",
            warning=WarningConfig(enabled=True, message="Get off YouTube"),
        )

        emit([block])
        emit([block])
        emit([])
        emit([block])

        self.assertEqual(
            events,
            [
                ("YouTube", "Get off YouTube"),
                ("YouTube", "Get off YouTube"),
            ],
        )

    def test_multiple_blocks_activating_together_emit_first_warning_only(self) -> None:
        WarningConfig = getattr(models, "WarningConfig", None)
        if WarningConfig is None:
            self.skipTest("WarningConfig is not implemented yet")

        engine = self._new_engine_shell()
        emit = getattr(engine, "_emit_block_activation_warnings", None)
        self.assertIsNotNone(
            emit,
            "Engine should expose a small helper for active-block warning events",
        )
        if emit is None:
            return

        events: list[str] = []
        engine.add_warning_listener(lambda block_name, warning: events.append(block_name))
        first = models.BlockList(
            name="First",
            warning=WarningConfig(enabled=True, message="First warning"),
        )
        second = models.BlockList(
            name="Second",
            warning=WarningConfig(enabled=True, message="Second warning"),
        )

        emit([first, second])
        emit([first, second])

        self.assertEqual(events, ["First"])


if __name__ == "__main__":
    unittest.main()
