"""Password hashing & random-string generator for lock methods.

Password hashes are stored in ``config.json``, which is user-readable by
design, so the hash and salt are exposed to an offline attacker.  We therefore
use a slow KDF (PBKDF2-HMAC-SHA256) to make brute-forcing expensive.

Stored-hash format::

    pbkdf2$<iterations>$<hex digest>

``verify_password`` recognises this scheme and verifies with the embedded
iteration count.  Any hash *without* the ``pbkdf2$`` prefix is treated as a
legacy single-round ``sha256(salt || password)`` digest, so existing password
locks created by older versions keep working.  New hashes always use PBKDF2.
"""
from __future__ import annotations

import hashlib
import secrets
import string


# Iteration count for new hashes. Increasing this only affects newly created
# hashes; existing stored hashes embed the iteration count they were made with.
_PBKDF2_ITERATIONS = 200_000
_PBKDF2_PREFIX = "pbkdf2$"


def _pbkdf2_hex(password: str, salt: str, iterations: int) -> str:
    dk = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations
    )
    return dk.hex()


def _legacy_sha256_hex(password: str, salt: str) -> str:
    h = hashlib.sha256()
    h.update(salt.encode("utf-8"))
    h.update(password.encode("utf-8"))
    return h.hexdigest()


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """Return ``(stored_hash, salt)`` for ``password``.

    The stored hash is ``pbkdf2$<iterations>$<hex>``; callers persist it
    opaquely and hand it back to :func:`verify_password` unchanged.
    """
    if salt is None:
        salt = secrets.token_hex(16)
    digest = _pbkdf2_hex(password, salt, _PBKDF2_ITERATIONS)
    stored = f"{_PBKDF2_PREFIX}{_PBKDF2_ITERATIONS}${digest}"
    return stored, salt


def verify_password(password: str, hashed: str, salt: str) -> bool:
    if hashed.startswith(_PBKDF2_PREFIX):
        # Format: pbkdf2$<iterations>$<hex>
        try:
            _, iters_str, expected = hashed.split("$", 2)
            iterations = int(iters_str)
        except (ValueError, AttributeError):
            return False
        calc = _pbkdf2_hex(password, salt, iterations)
        return secrets.compare_digest(calc, expected)
    # Legacy single-round sha256(salt || password) digest.
    calc = _legacy_sha256_hex(password, salt)
    return secrets.compare_digest(calc, hashed)


def random_unlock_text(length: int) -> str:
    length = max(1, min(999, length))
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))
