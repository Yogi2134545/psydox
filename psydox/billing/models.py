"""Billing domain models."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class WalletBalance:
    user_id: str
    balance_paise: int

    @property
    def balance_inr(self) -> float:
        return self.balance_paise / 100.0


@dataclass
class WalletTransaction:
    id: str
    user_id: str
    type: str          # "credit" | "debit"
    amount_paise: int
    description: str
    ref_id: str
    created_at: float

    @property
    def amount_inr(self) -> float:
        return self.amount_paise / 100.0


@dataclass
class RechargePack:
    id: str
    name: str
    amount_inr: int
    bonus_pct: int       # e.g. 10 means 10% bonus credits

    @property
    def credits_inr(self) -> float:
        return self.amount_inr * (1 + self.bonus_pct / 100)

    @property
    def credits_paise(self) -> int:
        return round(self.credits_inr * 100)

    @property
    def amount_paise(self) -> int:
        return self.amount_inr * 100


RECHARGE_PACKS: list[RechargePack] = [
    RechargePack("starter",      "Starter",       299,   0),
    RechargePack("basic",        "Basic",          599,   0),
    RechargePack("standard",     "Standard",       999,   5),
    RechargePack("professional", "Professional",  1499,   5),
    RechargePack("business",     "Business",      2499,  10),
    RechargePack("growth",       "Growth",        3999,  10),
    RechargePack("scale",        "Scale",         5999,  15),
    RechargePack("team",         "Team",          8999,  15),
    RechargePack("agency",       "Agency",       14999,  20),
    RechargePack("enterprise",   "Enterprise",   24999,  25),
]
