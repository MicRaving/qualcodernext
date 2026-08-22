"""Password hashing — argon2id by default (SERVER_PLAN.md §6.2).

Verify is constant-time (argon2's verify). Empty passwords are rejected at
the registration layer, not here (passkey-only accounts carry hash '').
"""
from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()  # argon2id, sensible defaults


def hash_password(password: str) -> str:
    if not password:
        raise ValueError("empty password")
    return _hasher.hash(password)


def verify_password(password: str, stored: str) -> bool:
    if not stored:
        return False  # passkey-only account
    try:
        return _hasher.verify(stored, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(stored: str) -> bool:
    """True when parameters drifted — callers re-hash on successful login."""
    try:
        return _hasher.check_needs_rehash(stored)
    except (InvalidHashError, ValueError):
        return False
