"""BillingService — wallet operations, cost charging, and Razorpay order management."""
from __future__ import annotations

import logging
import os
import time
import uuid

from psydox.billing.models import (
    RECHARGE_PACKS, RechargePack, WalletBalance, WalletTransaction,
)

_log = logging.getLogger("psydox.billing.service")

_BYPASS_ROLES = frozenset({"owner", "admin"})


class InsufficientFundsError(Exception):
    """Raised when a wallet deduction cannot proceed due to insufficient balance."""

# Fallback cost per AI tool call in INR (used when cost_usd is not reported).
# These represent the approximate API provider cost per image generation.
_TOOL_FALLBACK_COST_INR: dict[str, float] = {
    "ai_background": 0.50,
    "ai_lifestyle":  1.00,
    "ai_model":      1.50,
    "ai_scene":      1.00,
    "ai_angles":     0.50,
    "jadu_ka_ghar":  1.00,
}


def _markup_pct() -> float:
    return float(os.environ.get("COST_MARKUP_PERCENT", "20"))


def _usd_to_inr() -> float:
    return float(os.environ.get("USD_TO_INR", "83"))


def compute_charge_paise(tool_id: str, cost_usd: float) -> int:
    """Convert API cost to customer charge in paise (with markup)."""
    if cost_usd and cost_usd > 0:
        cost_inr = cost_usd * _usd_to_inr()
    else:
        cost_inr = _TOOL_FALLBACK_COST_INR.get(tool_id, 1.0)
    charged_inr = cost_inr * (1 + _markup_pct() / 100)
    return max(1, round(charged_inr * 100))


class BillingService:
    def __init__(self) -> None:
        from psydox.storage.database import get_db
        self._db = get_db

    # ── Wallet read ────────────────────────────────────────────────────────────

    def get_balance(self, user_id: str) -> WalletBalance:
        row = self._db().execute(
            "SELECT balance_paise FROM user_wallets WHERE user_id = ?", (user_id,)
        ).fetchone()
        return WalletBalance(
            user_id=user_id,
            balance_paise=row["balance_paise"] if row else 0,
        )

    def get_transactions(self, user_id: str, limit: int = 30) -> list[WalletTransaction]:
        rows = self._db().execute(
            "SELECT * FROM wallet_transactions WHERE user_id = ? "
            "ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        return [
            WalletTransaction(
                id=r["id"],
                user_id=r["user_id"],
                type=r["type"],
                amount_paise=r["amount_paise"],
                description=r["description"],
                ref_id=r["ref_id"],
                created_at=r["created_at"],
            )
            for r in rows
        ]

    # ── Wallet write ───────────────────────────────────────────────────────────

    def _credit(self, user_id: str, amount_paise: int, description: str, ref_id: str = "") -> WalletTransaction:
        db = self._db()
        now = time.time()
        txn_id = str(uuid.uuid4())
        db.execute(
            "INSERT INTO user_wallets (user_id, balance_paise, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET "
            "balance_paise = balance_paise + excluded.balance_paise, updated_at = excluded.updated_at",
            (user_id, amount_paise, now),
        )
        db.execute(
            "INSERT INTO wallet_transactions (id, user_id, type, amount_paise, description, ref_id, created_at) "
            "VALUES (?, ?, 'credit', ?, ?, ?, ?)",
            (txn_id, user_id, amount_paise, description, ref_id or "", now),
        )
        db.commit()
        return WalletTransaction(txn_id, user_id, "credit", amount_paise, description, ref_id or "", now)

    def _deduct(self, user_id: str, amount_paise: int, description: str, ref_id: str = "") -> WalletTransaction:
        db = self._db()
        now = time.time()
        txn_id = str(uuid.uuid4())
        # Ensure wallet row exists (creates with 0 balance if new user)
        db.execute(
            "INSERT INTO user_wallets (user_id, balance_paise, updated_at) VALUES (?, 0, ?) "
            "ON CONFLICT(user_id) DO NOTHING",
            (user_id, now),
        )
        # Atomic deduct — only succeeds if current balance >= amount (no overdraft)
        cur = db.execute(
            "UPDATE user_wallets SET balance_paise = balance_paise - ?, updated_at = ? "
            "WHERE user_id = ? AND balance_paise >= ?",
            (amount_paise, now, user_id, amount_paise),
        )
        if cur.rowcount == 0:
            db.rollback()
            raise InsufficientFundsError(
                f"Insufficient wallet balance: need {amount_paise} paise."
            )
        db.execute(
            "INSERT INTO wallet_transactions (id, user_id, type, amount_paise, description, ref_id, created_at) "
            "VALUES (?, ?, 'debit', ?, ?, ?, ?)",
            (txn_id, user_id, amount_paise, description, ref_id or "", now),
        )
        db.commit()
        return WalletTransaction(txn_id, user_id, "debit", amount_paise, description, ref_id or "", now)

    # ── Razorpay order ─────────────────────────────────────────────────────────

    def create_topup_order(self, user_id: str, pack_id: str) -> dict:
        """Create a Razorpay order for the given pack. Returns dict with order_id and Razorpay key."""
        pack = next((p for p in RECHARGE_PACKS if p.id == pack_id), None)
        if not pack:
            raise ValueError(f"Unknown pack_id: {pack_id}")

        from psydox.billing import razorpay as _rz
        if not _rz.is_configured():
            raise RuntimeError("Razorpay is not configured. Set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET.")

        order = _rz.create_order(
            amount_paise=pack.amount_paise,
            receipt=f"psydox_wallet_{user_id[:8]}",
        )
        order_id = order["id"]

        db = self._db()
        db.execute(
            "INSERT INTO razorpay_orders "
            "(order_id, user_id, pack_id, amount_paise, credits_paise, status, payment_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, 'created', '', ?)",
            (order_id, user_id, pack_id, pack.amount_paise, pack.credits_paise, time.time()),
        )
        db.commit()

        return {
            "order_id":     order_id,
            "amount_paise": pack.amount_paise,
            "credits_paise": pack.credits_paise,
            "pack_name":    pack.name,
            "key_id":       _rz._key_id(),
        }

    def handle_payment_success(self, order_id: str, payment_id: str, signature: str) -> bool:
        """Verify Razorpay signature and credit wallet. Idempotent — safe to call twice."""
        from psydox.billing import razorpay as _rz
        if not _rz.verify_signature(order_id, payment_id, signature):
            _log.warning("Razorpay signature verification failed for order %s", order_id)
            return False

        db = self._db()
        row = db.execute(
            "SELECT * FROM razorpay_orders WHERE order_id = ?", (order_id,)
        ).fetchone()
        if not row:
            _log.error("Order %s not found in DB", order_id)
            return False
        if row["status"] == "paid":
            _log.info("Order %s already credited — idempotent no-op", order_id)
            return True

        now = time.time()
        # Atomic: mark paid only if currently not paid (prevents double-credit race).
        cur = db.execute(
            "UPDATE razorpay_orders SET status = 'paid', payment_id = ?, paid_at = ? "
            "WHERE order_id = ? AND status != 'paid'",
            (payment_id, now, order_id),
        )
        if cur.rowcount == 0:
            _log.info("Order %s already credited by concurrent process — no-op", order_id)
            return True

        # Credit the wallet in the same transaction (single commit covers both).
        txn_id = str(uuid.uuid4())
        pack = next((p for p in RECHARGE_PACKS if p.id == row["pack_id"]), None)
        pack_name = pack.name if pack else row["pack_id"]
        db.execute(
            "INSERT INTO user_wallets (user_id, balance_paise, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET "
            "balance_paise = balance_paise + excluded.balance_paise, updated_at = excluded.updated_at",
            (row["user_id"], row["credits_paise"], now),
        )
        db.execute(
            "INSERT INTO wallet_transactions (id, user_id, type, amount_paise, description, ref_id, created_at) "
            "VALUES (?, ?, 'credit', ?, ?, ?, ?)",
            (txn_id, row["user_id"], row["credits_paise"],
             f"Wallet recharge — {pack_name} (payment {payment_id[:12]})",
             payment_id, now),
        )
        db.commit()
        _log.info(
            "Credited ₹%.2f to user %s (order %s, payment %s)",
            row["credits_paise"] / 100, row["user_id"], order_id, payment_id,
        )
        return True

    # ── AI generation charge ───────────────────────────────────────────────────

    def charge_for_generation(
        self,
        user_id: str,
        tool_id: str,
        cost_usd: float = 0.0,
        description: str = "",
        ref_id: str = "",
    ) -> int:
        """Deduct the marked-up cost from the user's wallet. Returns paise charged.
        Raises InsufficientFundsError when balance is too low — callers must handle this.
        """
        try:
            amount_paise = compute_charge_paise(tool_id, cost_usd)
            self._deduct(
                user_id=user_id,
                amount_paise=amount_paise,
                description=description or f"AI generation: {tool_id}",
                ref_id=ref_id,
            )
            return amount_paise
        except InsufficientFundsError:
            raise  # propagate — generation must not proceed on empty wallet
        except Exception as exc:
            _log.warning("charge_for_generation failed: %s", exc)
            return 0

    def should_charge(self, user_role: str) -> bool:
        """Returns False for roles that bypass billing (owner, admin)."""
        return user_role not in _BYPASS_ROLES


_service: BillingService | None = None


def get_billing_service() -> BillingService:
    global _service
    if _service is None:
        _service = BillingService()
    return _service
