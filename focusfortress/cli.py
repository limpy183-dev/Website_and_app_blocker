"""Command-line interface: `focusfortress cli start|stop|toggle|lock <block>`."""
from __future__ import annotations

import argparse
import datetime as dt
import sys

from .config_store import load_config, save_config
from .engine import Engine
from .models import LockConfig
from .security import hash_password


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="focusfortress cli")
    sub = p.add_subparsers(dest="cmd", required=True)

    for name in ("start", "stop", "toggle"):
        sp = sub.add_parser(name, help=f"{name} a block")
        sp.add_parser = None  # type: ignore
        sp.add_argument("block", help="name of the block list")

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
    return p


def run_cli(argv: list[str]) -> int:
    args = _build_parser().parse_args(argv)
    engine = Engine.instance()

    if args.cmd == "list":
        for b in engine.config.blocks:
            status = "ON " if b.enabled else "off"
            print(f"{status}  {b.name}")
        return 0

    if args.cmd in ("start", "stop", "toggle"):
        if args.cmd == "start":
            ok = engine.set_block_enabled(args.block, True)
        elif args.cmd == "stop":
            ok = engine.set_block_enabled(args.block, False)
        else:
            ok = engine.toggle_block(args.block)
        if not ok:
            print(f"Block '{args.block}' not found.", file=sys.stderr)
            return 2
        print(f"OK: {args.cmd} '{args.block}'")
        return 0

    if args.cmd == "lock":
        cfg = load_config()
        b = next((x for x in cfg.blocks if x.name.lower() == args.block.lower()), None)
        if not b:
            print(f"Block '{args.block}' not found.", file=sys.stderr)
            return 2
        lock = LockConfig()
        if args.timer:
            hh, _, mm = args.timer.partition(":")
            until = dt.datetime.now() + dt.timedelta(hours=int(hh), minutes=int(mm or 0))
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
        print(f"OK: locked '{b.name}' ({lock.kind})")
        return 0

    return 1
