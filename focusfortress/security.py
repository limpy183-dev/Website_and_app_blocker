"""Password hashing & random-string generator for lock methods."""
from __future__ import annotations

import hashlib
import secrets
import string


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    if salt is None:
        salt = secrets.token_hex(16)
    h = hashlib.sha256()
    h.update(salt.encode("utf-8"))
    h.update(password.encode("utf-8"))
    return h.hexdigest(), salt


def verify_password(password: str, hashed: str, salt: str) -> bool:
    calc, _ = hash_password(password, salt)
    return secrets.compare_digest(calc, hashed)


def random_unlock_text(length: int) -> str:
    length = max(1, min(999, length))
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))
