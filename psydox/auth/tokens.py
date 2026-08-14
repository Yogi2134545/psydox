"""Psydox Auth — secure token generation and hashing.

Tokens are generated as URL-safe base64 (256-bit entropy).
Only the SHA-256 hash is stored in the database — the raw token is
sent in the email and never persisted.  On verification the caller
provides the raw token, we hash it, and compare with the stored hash.
"""
from __future__ import annotations

import hashlib
import secrets


_TOKEN_BYTES = 32  # 256 bits


class TokenService:

    def generate(self) -> str:
        """Return a cryptographically secure URL-safe token (raw, not hashed)."""
        return secrets.token_urlsafe(_TOKEN_BYTES)

    def hash(self, raw_token: str) -> str:
        """SHA-256 hash of the raw token — safe to store in the DB."""
        return hashlib.sha256(raw_token.encode()).hexdigest()

    def verify(self, raw_token: str, stored_hash: str) -> bool:
        """Return True if hash(raw_token) == stored_hash (constant-time compare)."""
        return secrets.compare_digest(self.hash(raw_token), stored_hash)
