"""Psydox Auth — email and input validation."""
from __future__ import annotations

import re

_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")

# Basic list of commonly-blocked disposable email domains
_DISPOSABLE_DOMAINS = frozenset({
    "mailinator.com", "guerrillamail.com", "trashmail.com", "temp-mail.org",
    "throwaway.email", "maildrop.cc", "yopmail.com", "sharklasers.com",
    "guerrillamailblock.com", "grr.la", "guerrillamail.info", "guerrillamail.biz",
    "guerrillamail.de", "guerrillamail.net", "guerrillamail.org", "spam4.me",
    "dispostable.com", "mailnull.com", "spamgourmet.com", "tempinbox.com",
    "fakeinbox.com", "throwam.com", "getairmail.com", "10minutemail.com",
    "tempr.email", "discard.email", "spamevader.com",
})


def validate_email(email: str) -> list[str]:
    """Return list of error messages. Empty = valid."""
    errors: list[str] = []
    if not email or not email.strip():
        errors.append("Email address is required.")
        return errors
    normalized = email.strip().lower()
    if " " in normalized:
        errors.append("Email address must not contain spaces.")
    if not _EMAIL_RE.match(normalized):
        errors.append("Please enter a valid email address.")
        return errors
    domain = normalized.split("@")[-1]
    if domain in _DISPOSABLE_DOMAINS:
        errors.append("Disposable email addresses are not allowed.")
    return errors


def normalize_email(email: str) -> str:
    return email.strip().lower()


def validate_name(name: str) -> list[str]:
    errors: list[str] = []
    if not name or not name.strip():
        errors.append("Full name is required.")
    elif len(name.strip()) < 2:
        errors.append("Full name must be at least 2 characters.")
    elif len(name.strip()) > 120:
        errors.append("Full name must be 120 characters or fewer.")
    return errors
