"""Command-line interface: `focusfortress cli start|stop|toggle|lock|status|list`.

Every command accepts a global ``--json`` flag that switches its output to a
single machine-readable JSON object, so the tool is scriptable from
schedulers, Stream Deck macros and automation setups.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json as _json
import sys

from .clock import wall_now
from .config_store import load_config, save_config
from .engine import Engine, LockedError
from .locks import can_disable, describe_lock
from .models import BlockList, LockConfig
from .security import hash_password


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="focusfortress cli")
    p.add_argument("--json", action="store_true",
                   help="emit machine-readable JSON instead of human text")
    sub = p.add_subparsers(dest="cmd", required=True)

    for name in ("start", "stop", "toggle"):
        sp = sub.add_parser(name, help=f"{name} a block")
        sp.add_argument("block", help="name of the block list")
        sp.add_argument("--password", default=None,
                        help="password to satisfy a password lock")
        sp.add_argument("--unlock-text", dest="unlock_text", default=None,
                        help="random unlock string to satisfy a random lock")

    lp = sub.add_parser("lock", help="arm a lock method on a block")
    lp.add_argument("block")
    g = lp.add_mutually_exclusive_group(required=True)
    g.add_argument("--timer", metavar="HH:MM",
                   help="lock until N hours:minutes from now (duration, e.g. 02:30)")
    g.add_argument("--until", metavar="YYYY-MM-DDTHH:MM",
                   help="lock until an absolute ISO datetime")
    g.add_argument("--random", type=int, metavar="N",
                   help="require an N-character random string to unlock")
    g.add_argument("--restart", action="store_true",
                   help="require a reboot to unlock")
    g.add_argument("--password", metavar="PASSWORD",
                   help="require a password to unlock")
    g.add_argument("--range", dest="time_range", metavar="HH:MM-HH:MM",
                   help="only allow changes outside this range")

    sub.add_parser("list", help="list all blocks")
    sub.add_parser("status", help="show what is active right now and why")
    return p


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _emit(as_json: bool, payload: dict, human: str, *, stream=None) -> None:
    """Print either the JSON payload or the human-readable string."""
    out = stream or sys.stdout
    if as_json:
        print(_json.dumps(payload, indent=2), file=out)
    elif human:
        print(human, file=out)


def _format_duration(delta: dt.timedelta) -> str:
    secs = int(delta.total_seconds())
    if secs <= 0:
        return "0m"
    h, rem = divmod(secs, 3600)
    m, _ = divmod(rem, 60)
    if h and m:
        return f"{h}h {m}m"
    if h:
        return f"{h}h"
    return f"{m}m"


def _block_status(engine: Engine, b: BlockList) -> dict:
    """Build the status record for one block."""
    now = wall_now()
    effective = engine._effective_enabled(b, now)
    allowed, reason = can_disable(b)

    record: dict = {
        "name": b.name,
        "enabled": bool(b.enabled),
        "effective_active": bool(effective),
        "lock_kind": b.lock.kind or "none",
        "lock_description": describe_lock(b.lock),
        "can_disable": bool(allowed),
    }
    if reason:
        record["lock_reason"] = reason

    # Time remaining on a timer lock.
    if b.lock.kind == "timer" and b.lock.until:
        try:
            until = dt.datetime.fromisoformat(b.lock.until)
            remaining = until - now
            record["lock_until"] = b.lock.until
            record["lock_remaining_seconds"] = max(0, int(remaining.total_seconds()))
            record["lock_remaining"] = _format_duration(remaining)
        except ValueError:
            pass

    # Allowance.
    if b.allowance.minutes_per_day > 0:
        record["allowance_minutes_per_day"] = b.allowance.minutes_per_day
        record["allowance_minutes_left"] = b.allowance.minutes_left_today

    return record


def _human_status(record: dict) -> str:
    state = "ACTIVE" if record["effective_active"] else ("ON" if record["enabled"] else "off")
    parts = [f"{state:>6}  {record['name']}"]
    if record["lock_kind"] != "none":
        lock_line = f"        lock: {record['lock_description']}"
        if "lock_remaining" in record:
            lock_line += f" ({record['lock_remaining']} left)"
        elif not record["can_disable"]:
            lock_line += "  [locked]"
        parts.append(lock_line)
    if "allowance_minutes_left" in record:
        parts.append(
            f"        allowance: {record['allowance_minutes_left']}/"
            f"{record['allowance_minutes_per_day']} min left today"
        )
    return "\n".join(parts)


def run_cli(argv: list[str]) -> int:
    args = _build_parser().parse_args(argv)
    as_json = bool(getattr(args, "json", False))
    engine = Engine.instance()

    if args.cmd == "list":
        records = [
            {"name": b.name, "enabled": bool(b.enabled)}
            for b in engine.config.blocks
        ]
        if as_json:
            _emit(True, {"blocks": records}, "")
        else:
            for r in records:
                status = "ON " if r["enabled"] else "off"
                print(f"{status}  {r['name']}")
        return 0

    if args.cmd == "status":
        records = [_block_status(engine, b) for b in engine.config.blocks]
        active = sum(1 for r in records if r["effective_active"])
        if as_json:
            _emit(True, {"active_count": active, "total": len(records),
                         "blocks": records}, "")
        else:
            if not records:
                print("No blocks configured.")
            else:
                for r in records:
                    print(_human_status(r))
                print(f"\n{active} of {len(records)} block(s) active.")
        return 0

    if args.cmd in ("start", "stop", "toggle"):
        # The LockConfig model stores no expected random string (only
        # random_length), so a random lock cannot be satisfied non-interactively
        # from the CLI: random_expected stays None and the engine refuses.
        try:
            if args.cmd == "start":
                # Enabling never gates on a lock, so no proofs are needed.
                ok = engine.set_block_enabled(args.block, True)
            elif args.cmd == "stop":
                ok = engine.set_block_enabled(
                    args.block, False,
                    password_attempt=args.password,
                    random_attempt=args.unlock_text,
                    random_expected=None,
                )
            else:
                ok = engine.toggle_block(
                    args.block,
                    password_attempt=args.password,
                    random_attempt=args.unlock_text,
                    random_expected=None,
                )
        except LockedError as e:
            _emit(as_json,
                  {"ok": False, "error": "locked", "block": args.block,
                   "reason": e.reason},
                  f"Refused: {e.reason}", stream=sys.stderr)
            return 3
        if not ok:
            _emit(as_json,
                  {"ok": False, "error": "block_not_found", "block": args.block},
                  f"Block '{args.block}' not found.", stream=sys.stderr)
            return 2
        b = engine.find_block(args.block)
        _emit(as_json,
              {"ok": True, "command": args.cmd, "block": args.block,
               "enabled": bool(b.enabled) if b else None},
              f"OK: {args.cmd} '{args.block}'")
        return 0

    if args.cmd == "lock":
        cfg = load_config()
        b = next((x for x in cfg.blocks if x.name.lower() == args.block.lower()), None)
        if not b:
            _emit(as_json,
                  {"ok": False, "error": "block_not_found", "block": args.block},
                  f"Block '{args.block}' not found.", stream=sys.stderr)
            return 2
        lock = LockConfig()
        if args.timer:
            # Arm with the same clock the lock is later evaluated against
            # (clock.wall_now), and validate the free-form HH:MM string.
            try:
                hh, _, mm = args.timer.partition(":")
                until = wall_now() + dt.timedelta(hours=int(hh), minutes=int(mm or 0))
            except ValueError:
                _emit(as_json,
                      {"ok": False, "error": "bad_timer", "value": args.timer},
                      "Invalid --timer; expected HH:MM (e.g. 02:30).",
                      stream=sys.stderr)
                return 2
            lock.kind = "timer"
            lock.until = until.isoformat(timespec="minutes")
        elif args.until:
            lock.kind = "timer"
            lock.until = args.until
        elif args.random:
            lock.kind = "random"
            lock.random_length = int(args.random)
        elif args.restart:
            lock.kind = "restart"
        elif args.password:
            h, s = hash_password(args.password)
            lock.kind = "password"
            lock.password_hash = h
            lock.password_salt = s
        elif args.time_range:
            start, _, end = args.time_range.partition("-")
            lock.kind = "range"
            lock.range_start = start
            lock.range_end = end
        b.lock = lock
        save_config(cfg)
        engine.reload_config()
        engine.set_block_enabled(b.name, True)
        _emit(as_json,
              {"ok": True, "command": "lock", "block": b.name, "lock_kind": lock.kind},
              f"OK: locked '{b.name}' ({lock.kind})")
        return 0

    return 1
