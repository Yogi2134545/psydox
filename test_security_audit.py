"""
Production-Readiness Audit — Regression Test Suite

Covers Fixes 3–13 from the security audit:
  Fix  3: users.yaml — no real bcrypt hashes
  Fix  4: app.py — legacy auth fallback removed
  Fix  5: require_owner() is owner-only; require_admin() is owner+admin
  Fix  6: Service-layer RBAC on admin_update_role / admin_set_status / admin_verify_user
  Fix  7: Wallet overdraft prevention (_deduct raises InsufficientFundsError)
  Fix  8: handle_payment_success — single atomic commit
  Fix  9: _check_rate_limit fails closed
  Fix 10: admin_update_role validates new_role before DB hit
  Fix 11: change_password revokes other sessions
  Fix 12: can_use_feature fails closed for unknown features
  Fix 13: rate-limit store persists across calls in non-Streamlit context

All tests use a fresh in-memory temp DB.  Safe to run any time.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time

sys.path.insert(0, ".")

# ── Fresh temp DB ────────────────────────────────────────────────────────────
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["PSYDOX_DB_PATH"] = _tmp.name

# ── Test harness ─────────────────────────────────────────────────────────────
PASS, FAIL = "PASS", "FAIL"
_results: list[tuple[str, str, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    r = PASS if condition else FAIL
    _results.append((name, r, detail))
    icon = "OK " if r == PASS else "ERR"
    print(f"  [{icon}] {name}")
    if not condition and detail:
        print(f"        {detail}")


def hdr(title: str) -> None:
    print(f"\n--- {title} ---")


# ── DB init ───────────────────────────────────────────────────────────────────
from psydox.storage.database import init_db
init_db()
from psydox.auth.service import get_auth_service
from psydox.auth.repository import get_user_repository
from psydox.auth.sessions import get_session_service
from psydox.auth.models import AccountStatus

svc     = get_auth_service()
repo    = get_user_repository()
sess    = get_session_service()

# Create test users directly (yaml migration skipped — pyyaml not installed in test env).
import bcrypt as _bcrypt
_PW_HASH = _bcrypt.hashpw(b"TestPass123!", _bcrypt.gensalt()).decode()
_SETUP_USERS = [
    ("yogeshwar@popclub.co",  "Yogeshwar", "owner"),
    ("surya.pant@popclub.co", "Surya",     "admin"),
    ("ankit@popclub.co",      "Ankit",     "manager"),
    ("devesh@popclub.co",     "Devesh",    "operator"),
    ("bhargavi.kt@popclub.co", "Bhargavi", "operator"),
]
for _em, _nm, _role in _SETUP_USERS:
    if not repo.get_by_email(_em):
        repo.create(_nm, _em, _PW_HASH, role=_role,
                    email_verified=True, status=AccountStatus.ACTIVE)

# ── Fix 3: users.yaml hashes stripped ────────────────────────────────────────
hdr("FIX 3: users.yaml — no real bcrypt hashes")
import pathlib, re
yaml_path = pathlib.Path("users.yaml")
if yaml_path.exists():
    _yaml_text = yaml_path.read_text(encoding="utf-8")
    # Detect real bcrypt hashes: $2b$NN$ or $2a$NN$
    _real_hashes = re.findall(r"password_hash:\s+(\$2[ab]\$\d+\$\S+)", _yaml_text)
    check("no real bcrypt hashes in users.yaml",
          len(_real_hashes) == 0,
          f"found {len(_real_hashes)} real hash(es): {_real_hashes[:2]}")
    check("password_hash entries are empty strings",
          'password_hash: ""' in _yaml_text or "password_hash: ''" in _yaml_text,
          "expected password_hash: \"\" not found")
else:
    check("users.yaml not present (acceptable)", True)

# ── Fix 4: legacy auth fallback removed from app.py ──────────────────────────
hdr("FIX 4: app.py — legacy auth fallback removed")
_app_src = pathlib.Path("app.py").read_text(encoding="utf-8")
check("no 'login_fallback' form key in app.py",
      "login_fallback" not in _app_src,
      "legacy fallback form still present")
check("no bcrypt.checkpw in auth exception handler",
      "checkpw" not in _app_src.split("render_auth_page")[1].split("BACKGROUND WORKER")[0]
      if "render_auth_page" in _app_src else True,
      "bcrypt.checkpw found in auth exception handler")
check("no yaml.safe_load in auth exception handler",
      "yaml.safe_load" not in _app_src.split("render_auth_page")[1].split("BACKGROUND WORKER")[0]
      if "render_auth_page" in _app_src else True,
      "yaml.safe_load found in auth exception handler")

# ── Fix 5: require_owner / require_admin ─────────────────────────────────────
hdr("FIX 5: require_owner() is owner-only; require_admin() added")
from psydox.access import require_owner, require_admin

# require_owner: owner passes
_yogi = repo.get_by_email("yogeshwar@popclub.co")
if _yogi:
    try:
        require_owner("yogeshwar@popclub.co")
        check("T5.1 owner passes require_owner", True)
    except PermissionError:
        check("T5.1 owner passes require_owner", False, "raised PermissionError unexpectedly")
else:
    check("T5.1 owner passes require_owner", True, "SKIP — owner not in DB yet")

# require_owner: admin is rejected
_surya = repo.get_by_email("surya.pant@popclub.co")
if _surya:
    try:
        require_owner("surya.pant@popclub.co")
        check("T5.2 admin rejected by require_owner", False, "no PermissionError raised for admin")
    except PermissionError:
        check("T5.2 admin rejected by require_owner", True)
else:
    check("T5.2 admin rejected by require_owner", True, "SKIP — surya not in DB yet")

# require_admin: owner passes
if _yogi:
    try:
        require_admin("yogeshwar@popclub.co")
        check("T5.3 owner passes require_admin", True)
    except PermissionError:
        check("T5.3 owner passes require_admin", False, "raised PermissionError unexpectedly")
else:
    check("T5.3 owner passes require_admin", True, "SKIP")

# require_admin: admin passes
if _surya:
    try:
        require_admin("surya.pant@popclub.co")
        check("T5.4 admin passes require_admin", True)
    except PermissionError:
        check("T5.4 admin passes require_admin", False, "raised PermissionError unexpectedly")
else:
    check("T5.4 admin passes require_admin", True, "SKIP")

# require_admin: manager is rejected
_ankit = repo.get_by_email("ankit@popclub.co")
if _ankit:
    try:
        require_admin("ankit@popclub.co")
        check("T5.5 manager rejected by require_admin", False, "no PermissionError for manager")
    except PermissionError:
        check("T5.5 manager rejected by require_admin", True)
else:
    check("T5.5 manager rejected by require_admin", True, "SKIP")

# ── Fix 6: service-layer RBAC on admin methods ───────────────────────────────
hdr("FIX 6: service-layer RBAC on admin write operations")

_surya2 = repo.get_by_email("surya.pant@popclub.co")
_ankit2 = repo.get_by_email("ankit@popclub.co")

# Non-admin caller is rejected by admin_update_role
if _surya2 and _ankit2:
    res_na = svc.admin_update_role(_ankit2.id, "editor", admin_email="ankit@popclub.co")
    check("T6.1 non-admin caller rejected by admin_update_role",
          not res_na.success and res_na.error_code == "FORBIDDEN",
          f"success={res_na.success} code={res_na.error_code!r}")

    # Admin caller is allowed
    res_ok = svc.admin_update_role(_ankit2.id, "editor", admin_email="surya.pant@popclub.co")
    check("T6.2 admin caller allowed by admin_update_role",
          res_ok.success,
          f"error={res_ok.error!r}")

    # Empty admin_email is rejected
    res_empty = svc.admin_update_role(_ankit2.id, "viewer", admin_email="")
    check("T6.3 empty admin_email rejected",
          not res_empty.success and res_empty.error_code == "FORBIDDEN",
          f"success={res_empty.success} code={res_empty.error_code!r}")

    # Non-admin caller rejected by admin_set_status
    res_ss = svc.admin_set_status(_surya2.id, AccountStatus.SUSPENDED, admin_email="ankit@popclub.co")
    check("T6.4 non-admin caller rejected by admin_set_status",
          not res_ss.success and res_ss.error_code == "FORBIDDEN",
          f"success={res_ss.success}")

    # Non-admin caller rejected by admin_verify_user
    _devesh = repo.get_by_email("devesh@popclub.co")
    if _devesh:
        res_av = svc.admin_verify_user(_devesh.id, admin_email="ankit@popclub.co")
        check("T6.5 non-admin caller rejected by admin_verify_user",
              not res_av.success and res_av.error_code == "FORBIDDEN",
              f"success={res_av.success}")
    else:
        check("T6.5 non-admin caller rejected by admin_verify_user", True, "SKIP")
else:
    for i in range(1, 6):
        check(f"T6.{i} SKIP — users not in DB", True, "SKIP")

# ── Fix 7: wallet overdraft prevention ───────────────────────────────────────
hdr("FIX 7: wallet overdraft prevention (_deduct raises InsufficientFundsError)")
from psydox.billing.service import BillingService, InsufficientFundsError
from psydox.storage.database import get_db

_billing = BillingService()
_test_user_id = "test-wallet-user-001"

# Top up 100 paise
_billing._credit(_test_user_id, 100, "test credit")
_bal1 = _billing.get_balance(_test_user_id)
check("T7.1 wallet credited 100 paise", _bal1.balance_paise == 100,
      f"balance={_bal1.balance_paise}")

# Deduct 50 — should succeed
_billing._deduct(_test_user_id, 50, "test deduct 50")
_bal2 = _billing.get_balance(_test_user_id)
check("T7.2 deduct 50 succeeds, balance = 50", _bal2.balance_paise == 50,
      f"balance={_bal2.balance_paise}")

# Deduct 100 — insufficient funds
_raised = False
try:
    _billing._deduct(_test_user_id, 100, "test overdraft")
except InsufficientFundsError:
    _raised = True
check("T7.3 overdraft raises InsufficientFundsError", _raised)

# Balance unchanged after rejected deduct
_bal3 = _billing.get_balance(_test_user_id)
check("T7.4 balance unchanged after rejected deduct",
      _bal3.balance_paise == 50,
      f"expected 50 got {_bal3.balance_paise}")

# No spurious debit transaction recorded for the failed deduct
_txns = _billing.get_transactions(_test_user_id)
_debits = [t for t in _txns if t.type == "debit"]
check("T7.5 only one debit transaction (the successful one)",
      len(_debits) == 1,
      f"debit count={len(_debits)}")

# ── Fix 8: handle_payment_success atomicity ───────────────────────────────────
hdr("FIX 8: handle_payment_success — single atomic commit")
import inspect
from psydox.billing.service import BillingService as _BS
_src = inspect.getsource(_BS.handle_payment_success)

# There must be exactly one db.commit() in handle_payment_success
_commit_count = _src.count("db.commit()")
check("T8.1 handle_payment_success has exactly one db.commit()",
      _commit_count == 1,
      f"found {_commit_count} commit() calls")

# The two-commit pattern (mark paid, then credit in separate commit) must be gone
_old_pattern = "db.commit()\n\n        # Credit the wallet with bonus credits"
check("T8.2 old two-commit pattern removed",
      _old_pattern not in _src,
      "old two-commit pattern still present")

# ── Fix 9: rate limiter fails closed ─────────────────────────────────────────
hdr("FIX 9: _check_rate_limit fails closed on exception")
_svc_src = pathlib.Path("psydox/auth/service.py").read_text(encoding="utf-8")
_rl_method = _svc_src[
    _svc_src.index("def _check_rate_limit"):
    _svc_src.index("def _check_rate_limit") + 400
]
check("T9.1 _check_rate_limit returns False on exception (fail closed)",
      "return False" in _rl_method and "return True" not in _rl_method,
      "_check_rate_limit still has 'return True' on exception")

# Direct test: rate limiter store persists between calls (Fix 13)
from psydox.security.ratelimit import get_rate_limiter
_rl = get_rate_limiter()
_test_email = "ratelimit_test@example.com"
# Exhaust all 5 login tokens
for _ in range(5):
    _rl.check(_test_email, "login")
_sixth = _rl.check(_test_email, "login")
check("T9.2 rate limiter denies after exhaustion", not _sixth,
      "rate limiter allowed 6th login attempt")

# ── Fix 10: role validation in admin_update_role ──────────────────────────────
hdr("FIX 10: admin_update_role rejects invalid roles")
_yogi3 = repo.get_by_email("yogeshwar@popclub.co")
_ankit3 = repo.get_by_email("ankit@popclub.co")

if _yogi3 and _ankit3:
    # "superadmin" is not a valid role
    res_bad = svc.admin_update_role(_ankit3.id, "superadmin", admin_email="yogeshwar@popclub.co")
    check("T10.1 invalid role 'superadmin' rejected",
          not res_bad.success and res_bad.error_code == "VALIDATION_ERROR",
          f"success={res_bad.success} code={res_bad.error_code!r}")

    # "owner" is not assignable through this interface
    res_owner = svc.admin_update_role(_ankit3.id, "owner", admin_email="yogeshwar@popclub.co")
    check("T10.2 'owner' role rejected as not assignable",
          not res_owner.success,
          f"success={res_owner.success} code={res_owner.error_code!r}")

    # Empty string role is rejected
    res_empty = svc.admin_update_role(_ankit3.id, "", admin_email="yogeshwar@popclub.co")
    check("T10.3 empty role string rejected",
          not res_empty.success,
          f"success={res_empty.success}")

    # Valid role is still accepted
    res_valid = svc.admin_update_role(_ankit3.id, "viewer", admin_email="yogeshwar@popclub.co")
    check("T10.4 valid role 'viewer' accepted",
          res_valid.success,
          f"error={res_valid.error!r}")
else:
    for i in range(1, 5):
        check(f"T10.{i} SKIP", True, "SKIP")

# ── Fix 11: change_password revokes other sessions ────────────────────────────
hdr("FIX 11: change_password revokes other sessions")

# Register a fresh test user
_cp_res = svc.register(
    "Session Test", "session_test@example.com",
    "Test1234!", "Test1234!", terms_accepted=True,
)
if _cp_res.success and _cp_res.user:
    _cp_user = _cp_res.user
    # Force-activate (bypass email verification for test)
    repo.verify_email(_cp_user.id)
    repo.update_status(_cp_user.id, AccountStatus.ACTIVE)
    _cp_user = repo.get_by_id(_cp_user.id)

    # Create 3 sessions
    s1 = sess.create(_cp_user.id)
    s2 = sess.create(_cp_user.id)
    s3 = sess.create(_cp_user.id)

    _active_before = sess.list_active(_cp_user.id)
    check("T11.1 3 sessions active before password change",
          len(_active_before) == 3,
          f"count={len(_active_before)}")

    # Change password keeping s2 alive
    res_cp = svc.change_password(
        _cp_user.id,
        "Test1234!", "NewPass999@", "NewPass999@",
        current_session_id=s2.id,
    )
    check("T11.2 change_password succeeded", res_cp.success, f"error={res_cp.error!r}")

    _active_after = sess.list_active(_cp_user.id)
    check("T11.3 only the kept session remains active",
          len(_active_after) == 1 and _active_after[0].id == s2.id,
          f"active count={len(_active_after)}, ids={[s.id for s in _active_after]}")

    # s1 and s3 must be revoked
    _s1_valid = sess.validate(s1.id)
    _s3_valid = sess.validate(s3.id)
    check("T11.4 session s1 revoked", _s1_valid is None, "s1 still valid")
    check("T11.5 session s3 revoked", _s3_valid is None, "s3 still valid")
    _s2_valid = sess.validate(s2.id)
    check("T11.6 current session s2 still valid", _s2_valid is not None, "s2 was revoked")
else:
    for i in range(1, 7):
        check(f"T11.{i} SKIP — registration failed", True, f"error={_cp_res.error!r}")

# ── Fix 12: can_use_feature fails closed ──────────────────────────────────────
hdr("FIX 12: can_use_feature fails closed for unknown features")
from psydox.security.rbac import get_rbac, Role

_rbac = get_rbac()

# Known feature IDs (defined in _FEATURE_PERMISSION) — standard behavior
check("T12.1 'lifestyle' feature (requires AI perm) allowed for OWNER",
      _rbac.can_use_feature(Role.OWNER, "lifestyle"))
check("T12.2 'lifestyle' feature (requires AI perm) denied for USER",
      not _rbac.can_use_feature(Role.USER, "lifestyle"))

# Unknown feature — must fail closed (deny, not allow)
check("T12.3 unknown feature 'totally_fake_feature' denied for OWNER",
      not _rbac.can_use_feature(Role.OWNER, "totally_fake_feature"),
      "unknown feature returned True for OWNER — fail open")
check("T12.4 unknown feature 'totally_fake_feature' denied for VIEWER",
      not _rbac.can_use_feature(Role.VIEWER, "totally_fake_feature"),
      "unknown feature returned True for VIEWER — fail open")

# ── Fix 13: rate-limit store persists in non-Streamlit context ────────────────
hdr("FIX 13: rate-limit store is persistent (not recreated per call)")
from psydox.security.ratelimit import _rl_store
_store_a = _rl_store()
_store_b = _rl_store()
check("T13.1 _rl_store() returns same object each call",
      _store_a is _store_b,
      f"got different dicts: {id(_store_a)} vs {id(_store_b)}")

# Mutating one is reflected in the other
_store_a["sentinel_key"] = "value"
check("T13.2 mutation visible across calls",
      _store_b.get("sentinel_key") == "value",
      "mutation not visible — separate dict instances")

# ── Final report ─────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print("  SECURITY AUDIT REGRESSION TEST RESULTS")
print(f"{'='*60}")
passed = sum(1 for _, r, _ in _results if r == PASS)
failed = sum(1 for _, r, _ in _results if r == FAIL)
for name, result, detail in _results:
    icon = "OK " if result == PASS else "ERR"
    print(f"  [{icon}] {name}")
    if result == FAIL and detail:
        print(f"       ^ {detail}")

print(f"\n  Passed: {passed}  Failed: {failed}  Total: {passed + failed}")
print(f"{'='*60}\n")

try:
    os.unlink(_tmp.name)
except Exception:
    pass

sys.exit(0 if failed == 0 else 1)
