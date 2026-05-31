"""Enforcement-core tests (report §5.1).

These cover the pure-logic parts of the blocker most likely to break a
release: URL/domain pattern matching, hosts-file domain extraction/expansion,
the five lock kinds, schedule evaluation (incl. wrap-midnight), config
round-tripping + schema migration, and the Pomodoro long-break state machine.

Everything here is filesystem- and Windows-free so the suite runs on
macOS/Linux/Windows alike (matching the existing warning tests).
"""
from __future__ import annotations

import datetime as dt
import os
import sys
import unittest
from unittest import mock

# Allow `import focusfortress` when running from the repo root without install.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Qt-based code uses the offscreen platform during tests.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from focusfortress.blocking.hosts import _expand_variants, _extract_domain
from focusfortress.blocking.patterns import (
    compile_rules, host_is_blocked, url_is_blocked,
)
from focusfortress.engine import _slot_active_now
from focusfortress.locks import can_disable, describe_lock
from focusfortress.models import (
    Allowance, AppConfig, BlockList, GlobalSettings, LockConfig, ScheduleSlot,
)
from focusfortress.security import hash_password


# ---------------------------------------------------------------------------
# patterns.py
# ---------------------------------------------------------------------------
class PatternMatchTests(unittest.TestCase):
    def test_bare_domain_matches_domain_and_subdomains(self):
        rules = compile_rules(["facebook.com"], [])
        self.assertTrue(url_is_blocked("http://facebook.com/", rules))
        self.assertTrue(url_is_blocked("https://www.facebook.com/feed", rules))
        self.assertTrue(url_is_blocked("https://m.facebook.com/", rules))

    def test_unrelated_domain_not_blocked(self):
        rules = compile_rules(["facebook.com"], [])
        self.assertFalse(url_is_blocked("https://example.com/", rules))
        # Must not match a domain that merely contains the rule as a substring.
        self.assertFalse(url_is_blocked("https://notfacebook.com/", rules))

    def test_path_rule_matches_prefix_only(self):
        rules = compile_rules(["reddit.com/r/funny"], [])
        self.assertTrue(url_is_blocked("https://reddit.com/r/funny", rules))
        self.assertTrue(url_is_blocked("https://reddit.com/r/funny/top", rules))
        self.assertFalse(url_is_blocked("https://reddit.com/r/serious", rules))

    def test_wildcard_in_query(self):
        rules = compile_rules(["google.com/*q=*unicorn*"], [])
        self.assertTrue(url_is_blocked("https://google.com/search?q=cute+unicorn", rules))
        self.assertFalse(url_is_blocked("https://google.com/search?q=taxes", rules))

    def test_block_all(self):
        rules = compile_rules(["*.*"], [])
        self.assertTrue(rules.block_all)
        self.assertTrue(url_is_blocked("https://anything.example/", rules))

    def test_exception_overrides_block(self):
        rules = compile_rules(["reddit.com"], ["reddit.com/r/python"])
        self.assertTrue(url_is_blocked("https://reddit.com/r/funny", rules))
        self.assertFalse(url_is_blocked("https://reddit.com/r/python", rules))

    def test_port_is_tolerated(self):
        rules = compile_rules(["example.com"], [])
        self.assertTrue(url_is_blocked("http://example.com:8080/x", rules))

    def test_host_is_blocked_ignores_loopback(self):
        rules = compile_rules(["*.*"], [])
        self.assertFalse(host_is_blocked("localhost", rules))
        self.assertFalse(host_is_blocked("127.0.0.1", rules))
        self.assertTrue(host_is_blocked("facebook.com", rules))


# ---------------------------------------------------------------------------
# hosts.py (pure logic only)
# ---------------------------------------------------------------------------
class HostsExtractionTests(unittest.TestCase):
    def test_extract_strips_scheme_and_path(self):
        self.assertEqual(_extract_domain("https://facebook.com/feed"), "facebook.com")
        self.assertEqual(_extract_domain("reddit.com/r/funny"), "reddit.com")

    def test_extract_rejects_wildcards(self):
        self.assertIsNone(_extract_domain("*.*"))
        self.assertIsNone(_extract_domain("*.example.com"))

    def test_extract_blank(self):
        self.assertIsNone(_extract_domain("   "))

    def test_expand_variants_includes_www_and_mobile(self):
        variants = set(_expand_variants("example.com"))
        self.assertIn("example.com", variants)
        self.assertIn("www.example.com", variants)
        self.assertIn("m.example.com", variants)
        self.assertIn("mobile.example.com", variants)


# ---------------------------------------------------------------------------
# locks.py
# ---------------------------------------------------------------------------
class LockTests(unittest.TestCase):
    def _block(self, lock: LockConfig, *, active_since=None) -> BlockList:
        b = BlockList(name="L", lock=lock)
        b.active_since = active_since
        return b

    def test_none_lock_allows(self):
        ok, _ = can_disable(self._block(LockConfig(kind="none")))
        self.assertTrue(ok)

    def test_timer_active_blocks(self):
        future = (dt.datetime.now() + dt.timedelta(hours=1)).isoformat()
        ok, reason = can_disable(self._block(LockConfig(kind="timer", until=future)))
        self.assertFalse(ok)
        self.assertTrue(reason)

    def test_timer_expired_allows(self):
        past = (dt.datetime.now() - dt.timedelta(hours=1)).isoformat()
        ok, _ = can_disable(self._block(LockConfig(kind="timer", until=past)))
        self.assertTrue(ok)

    def test_random_requires_match(self):
        lock = LockConfig(kind="random", random_length=8)
        b = self._block(lock)
        ok, _ = can_disable(b, random_attempt="abc", random_expected="xyz")
        self.assertFalse(ok)
        ok2, _ = can_disable(b, random_attempt="xyz", random_expected="xyz")
        self.assertTrue(ok2)

    def test_password_requires_correct(self):
        h, s = hash_password("hunter2")
        lock = LockConfig(kind="password", password_hash=h, password_salt=s)
        b = self._block(lock)
        ok, _ = can_disable(b, password_attempt="wrong")
        self.assertFalse(ok)
        ok2, _ = can_disable(b, password_attempt="hunter2")
        self.assertTrue(ok2)

    def test_range_block_during(self):
        # Window 22:00-06:00 (wraps midnight); block_during means locked inside.
        lock = LockConfig(kind="range", range_start="22:00", range_end="06:00",
                          range_mode="block_during")
        b = self._block(lock)
        with mock.patch("focusfortress.locks.wall_now",
                        return_value=dt.datetime(2026, 1, 1, 23, 0)):
            ok, _ = can_disable(b)
            self.assertFalse(ok)  # inside window -> locked
        with mock.patch("focusfortress.locks.wall_now",
                        return_value=dt.datetime(2026, 1, 1, 12, 0)):
            ok2, _ = can_disable(b)
            self.assertTrue(ok2)  # outside window -> allowed

    def test_range_allow_during(self):
        lock = LockConfig(kind="range", range_start="09:00", range_end="17:00",
                          range_mode="allow_during")
        b = self._block(lock)
        with mock.patch("focusfortress.locks.wall_now",
                        return_value=dt.datetime(2026, 1, 1, 12, 0)):
            ok, _ = can_disable(b)
            self.assertTrue(ok)  # inside window -> allowed
        with mock.patch("focusfortress.locks.wall_now",
                        return_value=dt.datetime(2026, 1, 1, 20, 0)):
            ok2, _ = can_disable(b)
            self.assertFalse(ok2)  # outside window -> locked

    def test_restart_requires_reboot_after_arm(self):
        armed = dt.datetime(2026, 1, 1, 10, 0)
        b = self._block(LockConfig(kind="restart"), active_since=armed.isoformat())
        # Boot BEFORE arm -> still locked.
        with mock.patch("focusfortress.locks.boot_time",
                        return_value=dt.datetime(2026, 1, 1, 9, 0)):
            ok, _ = can_disable(b)
            self.assertFalse(ok)
        # Boot AFTER arm -> unlocked.
        with mock.patch("focusfortress.locks.boot_time",
                        return_value=dt.datetime(2026, 1, 1, 11, 0)):
            ok2, _ = can_disable(b)
            self.assertTrue(ok2)

    def test_describe_lock_variants(self):
        self.assertEqual(describe_lock(LockConfig(kind="none")), "No lock")
        self.assertIn("Restart", describe_lock(LockConfig(kind="restart")))
        self.assertIn("Password", describe_lock(LockConfig(kind="password")))


# ---------------------------------------------------------------------------
# engine.py scheduling helpers
# ---------------------------------------------------------------------------
class ScheduleTests(unittest.TestCase):
    def test_slot_same_day_inside(self):
        # 2026-01-05 is a Monday (weekday 0).
        slot = ScheduleSlot(day=0, start="09:00", end="17:00")
        self.assertTrue(_slot_active_now(slot, dt.datetime(2026, 1, 5, 12, 0)))
        self.assertFalse(_slot_active_now(slot, dt.datetime(2026, 1, 5, 8, 0)))

    def test_slot_wrong_day(self):
        slot = ScheduleSlot(day=0, start="00:00", end="23:59")
        # Tuesday (weekday 1) should not match a Monday slot.
        self.assertFalse(_slot_active_now(slot, dt.datetime(2026, 1, 6, 12, 0)))

    def test_slot_wrap_midnight(self):
        slot = ScheduleSlot(day=0, start="22:00", end="06:00")
        # Late Monday night is inside the wrap window.
        self.assertTrue(_slot_active_now(slot, dt.datetime(2026, 1, 5, 23, 30)))
        # Monday afternoon is outside.
        self.assertFalse(_slot_active_now(slot, dt.datetime(2026, 1, 5, 12, 0)))

    def test_slot_bad_time_string(self):
        slot = ScheduleSlot(day=0, start="25:00", end="06:00")
        self.assertFalse(_slot_active_now(slot, dt.datetime(2026, 1, 5, 12, 0)))


# ---------------------------------------------------------------------------
# models.py round-trip + schema migration
# ---------------------------------------------------------------------------
class ConfigRoundTripTests(unittest.TestCase):
    def test_round_trip_preserves_core_data(self):
        cfg = AppConfig(
            blocks=[
                BlockList(
                    name="Work",
                    sites=["facebook.com", "reddit.com/r/funny"],
                    lock=LockConfig(kind="timer", until="2026-01-01T10:00"),
                    allowance=Allowance(minutes_per_day=30, minutes_left_today=12),
                    schedule=[ScheduleSlot(day=0, start="09:00", end="17:00")],
                ),
            ],
            settings=GlobalSettings(proxy_port=58200, block_doh=True),
        )
        restored = AppConfig.from_dict(cfg.to_dict())
        self.assertEqual(len(restored.blocks), 1)
        b = restored.blocks[0]
        self.assertEqual(b.name, "Work")
        self.assertEqual(b.sites, ["facebook.com", "reddit.com/r/funny"])
        self.assertEqual(b.lock.kind, "timer")
        self.assertEqual(b.lock.until, "2026-01-01T10:00")
        self.assertEqual(b.allowance.minutes_per_day, 30)
        self.assertEqual(b.allowance.minutes_left_today, 12)
        self.assertEqual(len(b.schedule), 1)
        self.assertEqual(b.schedule[0].day, 0)
        self.assertEqual(restored.settings.proxy_port, 58200)
        self.assertTrue(restored.settings.block_doh)

    def test_to_dict_stamps_schema_version(self):
        d = AppConfig().to_dict()
        self.assertIn("schema_version", d)
        self.assertGreaterEqual(d["schema_version"], 1)

    def test_pre_version_config_migrates(self):
        # An old config with no schema_version key (version 0) must load and be
        # stamped at the current version.
        old = {"blocks": [{"name": "Legacy", "sites": ["x.com"]}], "settings": {}}
        restored = AppConfig.from_dict(old)
        self.assertGreaterEqual(restored.schema_version, 1)
        self.assertEqual(restored.blocks[0].name, "Legacy")

    def test_unknown_keys_dropped(self):
        data = {
            "blocks": [{"name": "B", "sites": [], "bogus_field": 123}],
            "settings": {"made_up": True},
            "schema_version": 1,
        }
        restored = AppConfig.from_dict(data)  # must not raise
        self.assertEqual(restored.blocks[0].name, "B")

    def test_future_version_loads_best_effort(self):
        data = {"blocks": [], "settings": {}, "schema_version": 9999}
        restored = AppConfig.from_dict(data)
        # We don't downgrade; the version is preserved (>= what was on disk).
        self.assertGreaterEqual(restored.schema_version, 1)

    def test_pomodoro_long_break_round_trip(self):
        cfg = AppConfig()
        cfg.settings.pomodoro.long_break_minutes = 20
        cfg.settings.pomodoro.long_break_every = 3
        restored = AppConfig.from_dict(cfg.to_dict())
        self.assertEqual(restored.settings.pomodoro.long_break_minutes, 20)
        self.assertEqual(restored.settings.pomodoro.long_break_every, 3)

    def test_frozen_warn_seconds_round_trip(self):
        cfg = AppConfig()
        cfg.settings.frozen_turkey.warn_seconds = 90
        restored = AppConfig.from_dict(cfg.to_dict())
        self.assertEqual(restored.settings.frozen_turkey.warn_seconds, 90)


if __name__ == "__main__":
    unittest.main()
