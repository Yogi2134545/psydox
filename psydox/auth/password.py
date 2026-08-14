"""Psydox Auth — password hashing and validation."""
from __future__ import annotations

import re


_MIN_LENGTH = 8
_BCRYPT_ROUNDS = 12


class PasswordService:

    def hash(self, plaintext: str) -> str:
        import bcrypt
        return bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)).decode()

    def verify(self, plaintext: str, hashed: str) -> bool:
        try:
            import bcrypt
            return bcrypt.checkpw(plaintext.encode(), hashed.encode())
        except Exception:
            return False

    def validate_strength(self, password: str) -> list[str]:
        """Return list of validation error messages; empty list means OK."""
        errors: list[str] = []
        if len(password) < _MIN_LENGTH:
            errors.append(f"Password must be at least {_MIN_LENGTH} characters.")
        if not re.search(r"[A-Z]", password):
            errors.append("Password must contain at least one uppercase letter.")
        if not re.search(r"[a-z]", password):
            errors.append("Password must contain at least one lowercase letter.")
        if not re.search(r"\d", password):
            errors.append("Password must contain at least one number.")
        return errors
