"""Dataclass models persisted to config.json."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict, fields
from typing import Any, Dict, List, Optional


def _only_known(cls: type, data: Any) -> Dict[str, Any]:
    """Return only the keys of ``data`` that are valid fields of ``cls``.

    Lets old/new config files survive round-trips: unknown keys (from a
    future version, or one we no longer recognise) are silently dropped
    instead of crashing ``cls(**data)``.
    """
    if not isinstance(data, dict):
        return {}
    valid = {f.name for f in fields(cls)}
    return {k: v for k, v in data.items() if k in valid}


@dataclass
class LockConfig:
    """How the user is prevented from disabling an active block."""
    kind: str = "none"                 # none|timer|random|range|restart|password
    until: Optional[str] = None        # ISO datetime for timer
    random_length: int = 32            # chars required for random
    range_start: str = "22:00"         # HH:MM for range lock
    range_end: str = "06:00"
    range_mode: str = "block_during"   # block_during|allow_during
    password_hash: Optional[str] = None  # sha256 hex
    password_salt: Optional[str] = None


@dataclass
class ScheduleSlot:
    day: int        # 0=Mon .. 6=Sun
    start: str      # HH:MM
    end: str        # HH:MM


@dataclass
class Allowance:
    minutes_per_day: int = 0           # 0 = no allowance
    minutes_left_today: int = 0
    last_reset: str = ""               # ISO date


#: The nine documented core warning fields (report §11.1). These are always
#: serialised; every other WarningConfig field is dropped from the saved form
#: when it equals its default, so old/simple configs round-trip unchanged.
_CORE_WARNING_KEYS = frozenset({
    "enabled", "message", "sound_path", "volume", "popup_duration_seconds",
    "fade_enabled", "fade_seconds", "always_on_top", "dismiss_mode",
})


@dataclass
class WarningConfig:
    """Per-block warning/alarm settings (see Implementation_report.txt §11)."""
    enabled: bool = False
    message: str = ""
    sound_path: str = ""
    volume: int = 80
    popup_duration_seconds: int = 8
    fade_enabled: bool = True
    fade_seconds: int = 2
    always_on_top: bool = True
    dismiss_mode: str = "auto_close"   # auto_close|click_to_close|type_to_dismiss|hold_to_dismiss
    # Optional extras (report §14-§19). Values left at their default are pruned
    # from the serialised form so legacy configs round-trip to exactly the
    # nine core fields above (see AppConfig.to_dict / _CORE_WARNING_KEYS).
    messages: List[str] = field(default_factory=list)  # random message pool (§15)
    theme: str = "default"             # popup theme / preset name (§17)
    # ---- Popup presentation (§7.2, §17, §19.5) ----
    popup_mode: str = "centered"       # centered|compact|fullscreen
    image_path: str = ""               # image or .gif shown above the message
    text_color: str = ""               # optional hex override for the message
    background_color: str = ""         # optional hex override for the popup
    # ---- Audio (§8.3) ----
    loop_sound: bool = False           # loop the sound until the popup closes
    sound_max_seconds: int = 0         # 0 = play to natural end
    # ---- Dismiss / strict mode (§9.3, §16.2) ----
    close_delay_seconds: int = 0       # hide the dismiss control for N seconds
    hold_seconds: int = 2              # press-and-hold duration for hold_to_dismiss
    repeat_minutes: int = 0            # re-show every N min while active (0 = once)
    # ---- Lock triggers (§6.4) ----
    on_lock_unlock: bool = False       # warn when a timer lock expires
    on_early_unlock: bool = False      # warn when a disable attempt is blocked


@dataclass
class BlockList:
    name: str = "New Block"
    enabled: bool = False              # currently active
    # Website patterns:
    sites: List[str] = field(default_factory=list)       # domains / URLs / wildcards
    site_exceptions: List[str] = field(default_factory=list)
    # Application blocking:
    app_files: List[str] = field(default_factory=list)   # full .exe paths
    app_folders: List[str] = field(default_factory=list) # folders whose .exe are blocked
    app_windows: List[str] = field(default_factory=list) # window-title substrings
    store_apps: List[str] = field(default_factory=list)  # AppUserModelIDs / package names
    # Restrictions & behaviour:
    users: List[str] = field(default_factory=list)       # empty = all users
    lock: LockConfig = field(default_factory=LockConfig)
    schedule: List[ScheduleSlot] = field(default_factory=list)
    allowance: Allowance = field(default_factory=Allowance)
    warning: WarningConfig = field(default_factory=WarningConfig)
    block_embedded: bool = True
    custom_block_message: str = ""
    # State (written by engine):
    active_since: Optional[str] = None
    # ---- Flat warning fields (alternate, flat-config surface) ----
    # The canonical warning settings live in the nested ``warning`` config
    # above (that is what the UI and engine read). These flat fields mirror
    # the same options for callers/configs that prefer a flat layout; the
    # engine treats a block's warning as active if *either* the nested config
    # or these flat fields are enabled.
    warning_enabled: bool = False
    warning_message: str = ""
    warning_sound_path: str = ""
    warning_volume: int = 80
    warning_popup_duration_seconds: int = 10
    warning_fade_enabled: bool = True
    warning_fade_seconds: int = 2
    warning_always_on_top: bool = True
    warning_dismiss_mode: str = "auto_close"


@dataclass
class PomodoroConfig:
    enabled: bool = False
    work_minutes: int = 25
    break_minutes: int = 5
    cycles: int = 4
    target_block: str = ""             # name of block list to drive
    # ---- Long breaks (report §3.9) ----
    long_break_minutes: int = 15       # duration of the long break
    long_break_every: int = 4          # take a long break every Nth work cycle (0 = off)
    # ---- Phase warnings (report §6.2) - optional popups on phase changes ----
    phase_warnings: bool = False
    work_message: str = "Focus time. Distractions are blocked."
    break_message: str = "Break started. Step away for a bit."
    complete_message: str = "Pomodoro complete. Great work."
    warning_sound_path: str = ""
    warning_volume: int = 80


@dataclass
class FrozenTurkeyConfig:
    enabled: bool = False
    action: str = "lock"               # lock|logoff|shutdown
    start: str = "22:00"
    end: str = "06:00"
    days: List[int] = field(default_factory=lambda: [0, 1, 2, 3, 4, 5, 6])
    warn_seconds: int = 60             # cancellable countdown before the action (0 = none)


@dataclass
class GlobalSettings:
    block_time_changes: bool = True
    block_task_manager: bool = True
    proxy_port: int = 58123
    start_with_windows: bool = True
    custom_block_page_html: str = ""
    motivational_quote: str = "Stay focused. Future you will thank you."
    # ---- Anti-bypass (all opt-in, default OFF) ----
    protect_process: bool = False
    """Deny PROCESS_TERMINATE on our own process so Task Manager / taskkill
    cannot close FocusFortress while a block is active."""
    force_protect_termination: bool = False
    """Force Protect FocusFortress from Termination.

    The strongest available protection mode: stacks DACL deny on
    PROCESS_TERMINATE, console-control-handler swallowing, HIGH process
    priority, and a *pair* of partner watchdogs that watch each other and
    instantly relaunch FocusFortress if it is somehow killed.  Active
    unconditionally while this toggle is on (does not require an active
    block)."""
    ignore_time_changes: bool = False
    """Use a monotonic clock for all timers/schedules. Changing the system
    clock will not shorten timer locks or skip schedule windows."""
    watchdog_enabled: bool = False
    """Spawn a sidecar process that relaunches FocusFortress if it's killed
    while any block is active."""
    block_doh: bool = False
    """Block well-known public DNS-over-HTTPS endpoints so browsers cannot
    bypass the hosts file by doing DNS inside HTTPS."""
    doh_allowlist: List[str] = field(default_factory=list)
    """Substrings of DoH hostnames you do NOT want blocked (e.g. 'nextdns.io').
    Leave empty for default behaviour."""
    revert_proxy_tampering: bool = False
    """Re-assert the WinINET proxy settings every few seconds so the user
    cannot disable the proxy from Internet Options while a block is active."""
    # ----
    pomodoro: PomodoroConfig = field(default_factory=PomodoroConfig)
    frozen_turkey: FrozenTurkeyConfig = field(default_factory=FrozenTurkeyConfig)


#: Current config schema version. Bump this whenever the on-disk shape
#: changes in a way that needs an explicit migration (see ``_migrate_config``).
#: A config with no ``schema_version`` key is treated as version 0.
CONFIG_SCHEMA_VERSION = 1


def _migrate_config(data: Dict[str, Any], from_version: int) -> Dict[str, Any]:
    """Apply ordered migrations to bring ``data`` up to ``CONFIG_SCHEMA_VERSION``.

    Each migration step transforms the *raw dict* (not dataclasses) from one
    version to the next, so adding a future step is a matter of appending a
    ``if v == N:`` branch that mutates ``data`` and increments ``v``.

    Tolerant parsing in :meth:`AppConfig.from_dict` already defaults missing
    keys and drops unknown ones, so version 0 -> 1 needs no field surgery; the
    step exists to stamp the version and give later migrations a place to hook
    in. Unknown / future versions are passed through untouched (forward-compat).
    """
    v = from_version
    # v0 -> v1: introduce the explicit schema_version stamp. No data change.
    if v < 1:
        v = 1
    # (future migrations: ``if v == 1: ...; v = 2`` etc.)
    data["schema_version"] = max(v, from_version)
    return data


@dataclass
class AppConfig:
    blocks: List[BlockList] = field(default_factory=list)
    settings: GlobalSettings = field(default_factory=GlobalSettings)
    schema_version: int = CONFIG_SCHEMA_VERSION

    # ---- serialisation helpers ----

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # Always stamp the current schema version on save.
        d["schema_version"] = CONFIG_SCHEMA_VERSION
        # Keep the serialised warning block down to its core fields when the
        # optional extras are at their defaults, so old/simple configs
        # round-trip to exactly the documented shape.
        warning_defaults = asdict(WarningConfig())
        for b in d.get("blocks", []):
            w = b.get("warning")
            if isinstance(w, dict):
                for k in list(w.keys()):
                    if k not in _CORE_WARNING_KEYS and w.get(k) == warning_defaults.get(k):
                        w.pop(k, None)
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AppConfig":
        # Run migrations first so the rest of the parser only ever sees a dict
        # at the current schema version. A missing key means a pre-versioning
        # config (version 0). An unknown future version is loaded best-effort.
        try:
            on_disk_version = int(d.get("schema_version", 0))
        except (TypeError, ValueError):
            on_disk_version = 0
        if on_disk_version < CONFIG_SCHEMA_VERSION:
            d = _migrate_config(dict(d), on_disk_version)
        version = max(on_disk_version, CONFIG_SCHEMA_VERSION)

        blocks = []
        for b in d.get("blocks", []):
            lock = LockConfig(**_only_known(LockConfig, b.get("lock", {})))
            allowance = Allowance(**_only_known(Allowance, b.get("allowance", {})))
            warning = WarningConfig(**_only_known(WarningConfig, b.get("warning", {})))
            schedule = [
                ScheduleSlot(**_only_known(ScheduleSlot, s))
                for s in b.get("schedule", [])
            ]
            b_clean = _only_known(BlockList, {
                k: v for k, v in b.items()
                if k not in ("lock", "allowance", "warning", "schedule")
            })
            blocks.append(
                BlockList(
                    lock=lock,
                    allowance=allowance,
                    warning=warning,
                    schedule=schedule,
                    **b_clean,
                )
            )
        s = d.get("settings", {})
        pomo = PomodoroConfig(**_only_known(PomodoroConfig, s.get("pomodoro", {})))
        ft = FrozenTurkeyConfig(**_only_known(FrozenTurkeyConfig, s.get("frozen_turkey", {})))
        s_clean = _only_known(GlobalSettings, {
            k: v for k, v in s.items() if k not in ("pomodoro", "frozen_turkey")
        })
        settings = GlobalSettings(pomodoro=pomo, frozen_turkey=ft, **s_clean)
        return cls(blocks=blocks, settings=settings, schema_version=version)
