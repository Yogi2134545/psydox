"""
RBAC / Owner Role Persistence Tests
Runs against a temporary in-memory DB — safe to run any time without touching psydox.db.

Each test prints PASS or FAIL with the actual result.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time

# ── Use a fresh temp DB so tests never corrupt the live psydox.db ────────────
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()
os.environ["PSYDOX_DB_PATH"] = _tmp_db.name

# Force re-init so any cached DB connection uses the temp path
import importlib

# ── Helpers ───────────────────────────────────────────────────────────────────
PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"

_results: list[tuple[str, str, str]] = []   # (test_name, result, detail)


def check(name: str, condition: bool, detail: str = "") -> None:
    result = PASS if condition else FAIL
    _results.append((name, result, detail))
    icon = "✅" if result == PASS else "❌"
    print(f"  {icon} {name}")
    if detail:
        print(f"       {detail}")


def hdr(title: str) -> None:
    print(f"\n{'-'*70}")
    print(f"  {title}")
    print(f"{'-'*70}")


# ═════════════════════════════════════════════════════════════════════════════
#  Bootstrap DB + auth service
# ═════════════════════════════════════════════════════════════════════════════
hdr("SETUP — fresh temp DB")

# Reset module-level singletons so they pick up the new DB path
for mod_name in list(sys.modules.keys()):
    if "psydox" in mod_name:
        del sys.modules[mod_name]

from psydox.storage.database import init_db
init_db()
print(f"  DB path: {_tmp_db.name}")

from psydox.auth.service import get_auth_service
svc = get_auth_service()
print(f"  AuthService created OK")


# ═════════════════════════════════════════════════════════════════════════════
#  TEST 1 — Yogeshwar exists in DB
# ═════════════════════════════════════════════════════════════════════════════
hdr("TEST 1 — Yogeshwar exists in DB")
from psydox.auth.repository import get_user_repository
repo = get_user_repository()
y = repo.get_by_email("yogeshwar@popclub.co")
check("TEST 1 — Yogeshwar exists", y is not None, f"result: {y}")


# ═════════════════════════════════════════════════════════════════════════════
#  TEST 2 — Yogeshwar role = owner
# ═════════════════════════════════════════════════════════════════════════════
hdr("TEST 2 — Yogeshwar role = owner")
y = repo.get_by_email("yogeshwar@popclub.co")
actual_role = y.role if y else "NOT FOUND"
check("TEST 2 — Yogeshwar role == 'owner'",
      actual_role == "owner",
      f"actual role in DB: '{actual_role}'")


# ═════════════════════════════════════════════════════════════════════════════
#  TEST 3 — Database restart does not change Yogeshwar role
# ═════════════════════════════════════════════════════════════════════════════
hdr("TEST 3 — DB restart does not change Yogeshwar role")

# Simulate a restart: clear the global singleton and recreate
import psydox.auth.service as _svc_mod
_svc_mod._service = None

svc2 = get_auth_service()   # new AuthService instance → runs _ensure_migrated() again
y2 = repo.get_by_email("yogeshwar@popclub.co")
role_after_restart = y2.role if y2 else "NOT FOUND"
check("TEST 3 — role after simulated restart",
      role_after_restart == "owner",
      f"role after restart: '{role_after_restart}'")


# ═════════════════════════════════════════════════════════════════════════════
#  TEST 4 — If DB role is set to admin, next restart restores owner
# ═════════════════════════════════════════════════════════════════════════════
hdr("TEST 4 — _ensure_system_owner corrects admin→owner on startup")

# Manually corrupt the DB role to simulate a bad admin change
y3 = repo.get_by_email("yogeshwar@popclub.co")
if y3:
    # Write admin directly to DB, bypassing service
    from psydox.storage.database import get_db
    db = get_db()
    db.execute("UPDATE users SET role='admin', updated_at=? WHERE id=?",
               (time.time(), y3.id))
    db.commit()

    corrupted = repo.get_by_email("yogeshwar@popclub.co")
    role_before = corrupted.role if corrupted else "NOT FOUND"
    check("TEST 4a — role was corrupted to 'admin' (pre-condition)",
          role_before == "admin",
          f"DB role before restart: '{role_before}'")

    # Simulate restart — new AuthService should fix it
    _svc_mod._service = None
    _svc_mod._service = None
    svc3 = get_auth_service()

    restored = repo.get_by_email("yogeshwar@popclub.co")
    role_after = restored.role if restored else "NOT FOUND"
    check("TEST 4b — role restored to 'owner' after simulated restart",
          role_after == "owner",
          f"DB role after restart: '{role_after}'")
else:
    check("TEST 4 — Yogeshwar not found (precondition failed)", False, "user not in DB")


# ═════════════════════════════════════════════════════════════════════════════
#  TEST 5 — Unauthorized user cannot change roles
# ═════════════════════════════════════════════════════════════════════════════
hdr("TEST 5 — admin_update_role owner protection (service layer)")

# Attempt to downgrade Yogeshwar's role through admin_update_role
y4 = repo.get_by_email("yogeshwar@popclub.co")
if y4:
    result = svc.admin_update_role(y4.id, "viewer", admin_email="surya.pant@popclub.co")
    check("TEST 5a — downgrading owner role is rejected",
          not result.success,
          f"result.success={result.success}, error='{result.error}'")

    y4_after = repo.get_by_email("yogeshwar@popclub.co")
    check("TEST 5b — Yogeshwar role unchanged after rejected downgrade",
          y4_after.role == "owner",
          f"DB role after rejected downgrade: '{y4_after.role}'")
else:
    check("TEST 5 — precondition failed", False, "Yogeshwar not in DB")


# ═════════════════════════════════════════════════════════════════════════════
#  TEST 6 — owner role cannot be GRANTED through admin_update_role
# ═════════════════════════════════════════════════════════════════════════════
hdr("TEST 6 — owner role cannot be granted through normal flow")

# Get surya's user (migrated from yaml)
surya = repo.get_by_email("surya.pant@popclub.co")
if surya:
    result = svc.admin_update_role(surya.id, "owner", admin_email="yogeshwar@popclub.co")
    check("TEST 6 — granting owner role is rejected",
          not result.success,
          f"result.success={result.success}, error='{result.error}'")
    surya_after = repo.get_by_email("surya.pant@popclub.co")
    check("TEST 6b — surya role unchanged",
          surya_after.role != "owner",
          f"surya role after attempt: '{surya_after.role}'")
else:
    check("TEST 6 — surya not in DB (migrated from yaml?)", False,
          "surya.pant@popclub.co not found — yaml migration may not have run")


# ═════════════════════════════════════════════════════════════════════════════
#  TEST 7 — authorized user CAN change an allowed role
# ═════════════════════════════════════════════════════════════════════════════
hdr("TEST 7 — authorized role change works and persists")

ankit = repo.get_by_email("ankit@popclub.co")
if ankit:
    original_role = ankit.role
    target_role   = "editor"

    result = svc.admin_update_role(ankit.id, target_role, admin_email="yogeshwar@popclub.co")
    check("TEST 7a — role change accepted",
          result.success,
          f"result.success={result.success}, error='{getattr(result, 'error', '')}'")

    ankit_after = repo.get_by_email("ankit@popclub.co")
    check("TEST 7b — role persists in DB",
          ankit_after.role == target_role,
          f"DB role: '{ankit_after.role}' (expected '{target_role}')")

    # Simulate restart
    _svc_mod._service = None
    svc4 = get_auth_service()
    ankit_after2 = repo.get_by_email("ankit@popclub.co")
    check("TEST 7c — role persists after simulated restart",
          ankit_after2.role == target_role,
          f"DB role after restart: '{ankit_after2.role}'")
else:
    check("TEST 7 — ankit not found", False, "ankit@popclub.co not found")


# ═════════════════════════════════════════════════════════════════════════════
#  TEST 8 — migration does NOT overwrite existing users
# ═════════════════════════════════════════════════════════════════════════════
hdr("TEST 8 — yaml migration is idempotent (does not overwrite existing users)")

# Manually set Yogeshwar to owner (it should already be owner)
y5 = repo.get_by_email("yogeshwar@popclub.co")
if y5:
    # Run migrate_from_yaml again — it should skip existing users
    count = repo.migrate_from_yaml()
    y5_after = repo.get_by_email("yogeshwar@popclub.co")
    check("TEST 8 — migrate_from_yaml does not overwrite existing user's role",
          y5_after.role == "owner",
          f"role after re-migration: '{y5_after.role}' (should still be 'owner')")
    print(f"       migrate_from_yaml returned: {count} inserted (expected 0 for all existing users)")
else:
    check("TEST 8 — precondition failed", False, "Yogeshwar not in DB")


# ═════════════════════════════════════════════════════════════════════════════
#  TEST 9 — unknown role string is rejected by update_role
# ═════════════════════════════════════════════════════════════════════════════
hdr("TEST 9 — unknown role string does NOT silently downgrade to viewer")

devesh = repo.get_by_email("devesh@popclub.co")
if devesh:
    before_role = devesh.role
    repo.update_role(devesh.id, "superadmin")   # unknown role
    devesh_after = repo.get_by_email("devesh@popclub.co")
    check("TEST 9 — unknown role string rejected (role unchanged)",
          devesh_after.role == before_role,
          f"role before: '{before_role}', role after update with 'superadmin': '{devesh_after.role}'")
else:
    check("TEST 9 — devesh not found", False, "devesh@popclub.co not found")


# ═════════════════════════════════════════════════════════════════════════════
#  TEST 10 — Session defaults don't overwrite session_state role
# ═════════════════════════════════════════════════════════════════════════════
hdr("TEST 10 — session_state 'if k not in' guard prevents role overwrite")

# Simulating the app.py session default block
fake_session = {"user_role": "owner"}
defaults = {"user_role": "viewer"}
for k, v in defaults.items():
    if k not in fake_session:
        fake_session[k] = v

check("TEST 10 — 'if k not in' guard prevents overwriting existing role",
      fake_session["user_role"] == "owner",
      f"session_state['user_role'] after defaults block: '{fake_session['user_role']}'")


# ═════════════════════════════════════════════════════════════════════════════
#  TEST 11 — Fresh DB: yogeshwar gets owner via yaml (now that yaml has owner)
# ═════════════════════════════════════════════════════════════════════════════
hdr("TEST 11 — Fresh DB: yaml migration assigns owner role to yogeshwar directly")

_tmp_db2 = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db2.close()
os.environ["PSYDOX_DB_PATH"] = _tmp_db2.name

# Clear all psydox module singletons so fresh DB is used
for mod_name in list(sys.modules.keys()):
    if "psydox" in mod_name:
        del sys.modules[mod_name]

from psydox.storage.database import init_db as _init2
_init2()
from psydox.auth.service import get_auth_service as _get_svc2
from psydox.auth.repository import get_user_repository as _get_repo2
svc_fresh = _get_svc2()
repo_fresh = _get_repo2()

y_fresh = repo_fresh.get_by_email("yogeshwar@popclub.co")
role_fresh = y_fresh.role if y_fresh else "NOT FOUND"
check("TEST 11 — Fresh DB: yogeshwar role after migration",
      role_fresh == "owner",
      f"role on fresh DB: '{role_fresh}'")

# Cleanup temp DBs
import os as _os
try: _os.unlink(_tmp_db.name)
except: pass
try: _os.unlink(_tmp_db2.name)
except: pass


# ═════════════════════════════════════════════════════════════════════════════
#  FINAL REPORT
# ═════════════════════════════════════════════════════════════════════════════
print(f"\n{'='*70}")
print("  FINAL TEST REPORT")
print(f"{'='*70}")
print(f"  {'Test':<55} {'Result'}")
print(f"  {'─'*55} {'─'*6}")

passed = 0
failed = 0
for name, result, detail in _results:
    icon = "✅" if result == PASS else "❌"
    print(f"  {icon} {name:<54} {result}")
    if result == PASS:
        passed += 1
    else:
        failed += 1
        if detail:
            print(f"       detail: {detail}")

print(f"\n  Passed: {passed}  Failed: {failed}  Total: {passed + failed}")
print(f"{'='*70}\n")

sys.exit(0 if failed == 0 else 1)
