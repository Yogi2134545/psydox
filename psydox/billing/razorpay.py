"""Razorpay API client — uses requests + hmac, no extra package needed."""
from __future__ import annotations

import base64
import hashlib
import hmac as _hmac
import json
import logging
import os

import requests

_log = logging.getLogger("psydox.billing.razorpay")

_BASE_URL = "https://api.razorpay.com/v1"


def _key_id() -> str:
    return os.environ.get("RAZORPAY_KEY_ID", "")


def _key_secret() -> str:
    return os.environ.get("RAZORPAY_KEY_SECRET", "")


def is_configured() -> bool:
    return bool(_key_id() and _key_secret())


def _auth_header() -> dict:
    token = base64.b64encode(f"{_key_id()}:{_key_secret()}".encode()).decode()
    return {"Authorization": f"Basic {token}", "Content-Type": "application/json"}


def create_order(amount_paise: int, currency: str = "INR", receipt: str = "") -> dict:
    """Create a Razorpay order. Returns the full order dict from the API."""
    resp = requests.post(
        f"{_BASE_URL}/orders",
        headers=_auth_header(),
        data=json.dumps({
            "amount": amount_paise,
            "currency": currency,
            "receipt": receipt or "psydox_wallet",
            "payment_capture": 1,
        }),
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def verify_signature(order_id: str, payment_id: str, signature: str) -> bool:
    """Verify Razorpay payment signature using HMAC-SHA256."""
    secret = _key_secret()
    if not secret:
        return False
    msg = f"{order_id}|{payment_id}"
    expected = _hmac.new(
        secret.encode(), msg.encode(), hashlib.sha256
    ).hexdigest()
    return _hmac.compare_digest(expected, signature)
