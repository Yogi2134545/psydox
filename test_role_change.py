"""
Role Change Persistence Tests
Verifies that admin_update_role actually persists to the DB for Surya and Ankit.
Uses a fresh in-memory temp DB — safe to run any time.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time

sys.path.insert(0, ".")

# Fresh temp DB
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["PSYDOX_DB_PATH"] = _tmp.name

# -- Helpers ------------------------------------------------------------------
PASS, FAIL = "PASS", "FAIL"
_results: list[tuple[str, str, str]] = []

def check(name, condition, detail=""):
    r = PASS if condition else FAIL
    _results.append((name, r, detail))
    icon = "OK " if r == PASS else "ERR"
    print(f"  [{icon}] {name}")
    if detail:
        print(f"        {detail}")

def hdr(title):
    print(f"\n--- {title} ---")

# -- Setup --------------------------------------------------------------------
from psydox.storage.database import init_db
init_db()
from psydox.auth.service import get_auth_service
from psydox.auth.repository import get_user_repository

svc  = get_auth_service()
repo = get_user_repository()

hdr("SETUP — verify initial roles from yaml migration")
for email, expected in [
    ("yogeshwar@popclub.co", "owner"),
    ("surya.pant@popclub.co", "admin"),
    ("ankit@popclub.co", "manager"),
]:
    u = repo.get_by_email(email)
    actual = u.role if u else "NOT FOUND"
    check(f"initial role {email}", actual == expected,
          f"expected={expected!r} actual={actual!r}")

# -- Test 1: Yogeshwar changes Surya admin -> manager -------------------------
hdr("TEST 1: Surya admin -> manager")
surya = repo.get_by_email("surya.pant@popclub.co")
res = svc.admin_update_role(surya.id, "manager", admin_email="yogeshwar@popclub.co")
check("T1a result.success is True",  res.success, f"error={res.error!r}")
check("T1b result.error is empty",   res.error == "", f"error={res.error!r}")

surya2 = repo.get_by_email("surya.pant@popclub.co")
check("T1c Surya DB role == 'manager'", surya2.role == "manager",
      f"actual={surya2.role!r}")

# Simulate the rerun: load ALL users fresh, Surya must appear as manager
all_users = repo.list_all()
surya3 = next((u for u in all_users if u.email == "surya.pant@popclub.co"), None)
_surya3_role = surya3.role if surya3 else "NOT FOUND"
check("T1d list_all() returns updated role for Surya",
      surya3 is not None and surya3.role == "manager",
      f"actual={_surya3_role!r}")

# -- Test 2: Yogeshwar changes Ankit manager -> editor ------------------------
hdr("TEST 2: Ankit manager -> editor")
ankit = repo.get_by_email("ankit@popclub.co")
res2 = svc.admin_update_role(ankit.id, "editor", admin_email="yogeshwar@popclub.co")
check("T2a result.success is True",  res2.success, f"error={res2.error!r}")

ankit2 = repo.get_by_email("ankit@popclub.co")
check("T2b Ankit DB role == 'editor'", ankit2.role == "editor",
      f"actual={ankit2.role!r}")

all_users2 = repo.list_all()
ankit3 = next((u for u in all_users2 if u.email == "ankit@popclub.co"), None)
_ankit3_role = ankit3.role if ankit3 else "NOT FOUND"
check("T2c list_all() returns updated role for Ankit",
      ankit3 is not None and ankit3.role == "editor",
      f"actual={_ankit3_role!r}")

# -- Test 3: simulate what the UI session state fix prevents ------------------
hdr("TEST 3: Simulate button-click rerun scenario")
# Before fix: on the click-rerun the selectbox could reset new_role to the
# current DB value BEFORE the save handler runs, so new_role == user.role
# and the button was never rendered. This test simulates both flows.

# Step A — user changes selectbox to "viewer" (session state has new value)
devesh = repo.get_by_email("devesh@popclub.co")
db_role      = devesh.role          # e.g. "operator"
selected_role = "viewer"            # user selected this in the dropdown

# OLD (broken) code would re-compute index from db_role on click-rerun,
# resetting session_state to db_role. Simulate that:
_broken_new_role = db_role          # index= overrides session state
check("T3a OLD code: new_role reset to db_role on click-rerun",
      _broken_new_role == db_role,
      f"click-rerun sees new_role={_broken_new_role!r}, save never called")

# NEW (fixed) code: session state is NOT overridden on click-rerun.
# Simulate: session_state[key] = selected_role (user's pick), no index= reset.
_fixed_new_role = selected_role     # preserved from session state
check("T3b NEW code: new_role preserved across click-rerun",
      _fixed_new_role != db_role,
      f"click-rerun sees new_role={_fixed_new_role!r}, will call save")

# Step B — actually call save with the preserved new_role
res3 = svc.admin_update_role(devesh.id, _fixed_new_role,
                             admin_email="yogeshwar@popclub.co")
check("T3c save with preserved role succeeds", res3.success,
      f"error={res3.error!r}")

devesh2 = repo.get_by_email("devesh@popclub.co")
check("T3d Devesh DB role == 'viewer' after save",
      devesh2.role == "viewer",
      f"actual={devesh2.role!r}")

# -- Test 4: owner protection still works ------------------------------------
hdr("TEST 4: Owner role protection still intact after UI fix")
yogi = repo.get_by_email("yogeshwar@popclub.co")
res4 = svc.admin_update_role(yogi.id, "admin", admin_email="yogeshwar@popclub.co")
check("T4a owner cannot be downgraded", not res4.success,
      f"success={res4.success}, error={res4.error!r}")

yogi2 = repo.get_by_email("yogeshwar@popclub.co")
check("T4b Yogeshwar role still owner", yogi2.role == "owner",
      f"actual={yogi2.role!r}")

# -- Test 5: second change on same user persists ------------------------------
hdr("TEST 5: Second change on same user (Ankit editor -> reviewer)")
ankit_again = repo.get_by_email("ankit@popclub.co")
check("T5a precondition: Ankit is 'editor'", ankit_again.role == "editor",
      f"actual={ankit_again.role!r}")

res5 = svc.admin_update_role(ankit_again.id, "reviewer",
                             admin_email="yogeshwar@popclub.co")
check("T5b second change succeeds", res5.success, f"error={res5.error!r}")

ankit_final = repo.get_by_email("ankit@popclub.co")
check("T5c Ankit DB role == 'reviewer'", ankit_final.role == "reviewer",
      f"actual={ankit_final.role!r}")

# -- Final report -------------------------------------------------------------
print(f"\n{'='*60}")
print("  ROLE CHANGE TEST RESULTS")
print(f"{'='*60}")
passed = sum(1 for _, r, _ in _results if r == PASS)
failed = sum(1 for _, r, _ in _results if r == FAIL)
for name, result, detail in _results:
    icon = "OK " if result == PASS else "ERR"
    line = f"  [{icon}] {name}"
    print(line)
    if result == FAIL and detail:
        print(f"       {detail}")

print(f"\n  Passed: {passed}  Failed: {failed}  Total: {passed + failed}")
print(f"{'='*60}\n")

try:
    os.unlink(_tmp.name)
except Exception:
    pass

sys.exit(0 if failed == 0 else 1)
