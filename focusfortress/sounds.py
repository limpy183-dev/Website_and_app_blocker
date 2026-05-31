"""Built-in warning sounds ("sound packs", report §19.4/§19.5).

Rather than ship binary audio assets, FocusFortress synthesises a small pack
of warning tones with the standard library (no third-party deps) and writes
them as 16-bit PCM WAV files into the data directory the first time they are
needed.  The Warning tab exposes them through a "Built-in sound" dropdown, so
users get reusable sounds out of the box and can still pick their own file.
"""
from __future__ import annotations

import math
import struct
import wave
from pathlib import Path
from typing import Callable, Dict, List, Optional

from .paths import DATA_DIR

_FRAMERATE = 44100
_AMPLITUDE = 18000  # of 32767 - loud but not clipping


def _envelope(i: int, total: int, attack: float = 0.01, release: float = 0.05) -> float:
    """Simple attack/release envelope to avoid clicks at note edges."""
    t = i / _FRAMERATE
    dur = total / _FRAMERATE
    a = min(1.0, t / attack) if attack > 0 else 1.0
    r = min(1.0, (dur - t) / release) if release > 0 else 1.0
    return max(0.0, min(a, r))


def _sine(freq: float, seconds: float, gain: float = 1.0) -> List[int]:
    n = int(_FRAMERATE * seconds)
    out: List[int] = []
    for i in range(n):
        env = _envelope(i, n)
        val = math.sin(2 * math.pi * freq * (i / _FRAMERATE))
        out.append(int(_AMPLITUDE * gain * env * val))
    return out


def _silence(seconds: float) -> List[int]:
    return [0] * int(_FRAMERATE * seconds)


def _beep() -> List[int]:
    return _sine(880, 0.4)


def _alarm() -> List[int]:
    out: List[int] = []
    for _ in range(4):
        out += _sine(1000, 0.18) + _sine(700, 0.18) + _silence(0.06)
    return out


def _chime() -> List[int]:
    out: List[int] = []
    for freq in (523.25, 659.25, 783.99):  # C5 E5 G5
        out += _sine(freq, 0.26, gain=0.9)
    return out


def _siren() -> List[int]:
    out: List[int] = []
    n = int(_FRAMERATE * 1.2)
    phase = 0.0
    for i in range(n):
        # Sweep 600 -> 1200 -> 600 Hz.
        frac = i / n
        freq = 600 + 600 * math.sin(math.pi * frac)
        phase += 2 * math.pi * freq / _FRAMERATE
        env = _envelope(i, n)
        out.append(int(_AMPLITUDE * 0.9 * env * math.sin(phase)))
    return out


_GENERATORS: Dict[str, Callable[[], List[int]]] = {
    "beep": _beep,
    "alarm": _alarm,
    "chime": _chime,
    "siren": _siren,
}


def _write_wav(path: Path, samples: List[int]) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(_FRAMERATE)
        clipped = (max(-32767, min(32767, s)) for s in samples)
        w.writeframes(b"".join(struct.pack("<h", s) for s in clipped))


def ensure_builtin_sounds(directory: Optional[Path] = None) -> Dict[str, str]:
    """Generate any missing built-in WAVs and return ``{name: absolute path}``.

    Fails soft: if the directory cannot be created/written (e.g. not elevated),
    only the names that already exist on disk are returned.
    """
    base = Path(directory) if directory is not None else (DATA_DIR / "sounds")
    result: Dict[str, str] = {}
    try:
        base.mkdir(parents=True, exist_ok=True)
    except Exception:
        return result
    for name, generator in _GENERATORS.items():
        path = base / f"{name}.wav"
        if not path.exists():
            try:
                _write_wav(path, generator())
            except Exception:
                continue
        if path.exists():
            result[name] = str(path)
    return result


def builtin_sound_names() -> List[str]:
    """Names of the built-in sounds (no disk access)."""
    return list(_GENERATORS.keys())
