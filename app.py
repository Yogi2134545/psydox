"""Psydox — Nike Image Processor"""
import logging
import streamlit as st
import yaml, bcrypt, zipfile, json, tempfile, threading, gc, shutil, hashlib, secrets, time, os
from pathlib import Path
from math import gcd

PSYDOX_VERSION = "2.0.0"
PSYDOX_BUILD   = "7b406dc"

_log = logging.getLogger("psydox.app")
logging.basicConfig(level=logging.INFO)
_log.info("Psydox %s build %s starting up", PSYDOX_VERSION, PSYDOX_BUILD)

try:
    from nano_banana.ui import render_nano_banana as _render_nano_banana
    _NB_AVAILABLE = True
except ImportError:
    _NB_AVAILABLE = False

st.set_page_config(page_title="Psydox", page_icon="⚡", layout="wide",
                   initial_sidebar_state="expanded")


@st.cache_resource
def _bootstrap() -> None:
    try:
        from psydox.storage.database import init_db
        init_db()
        _log.info("Database initialised")
    except Exception as _e:
        _log.warning("init_db failed: %s", _e)
    try:
        from psydox.features.loader import bootstrap_features
        bootstrap_features()
        _log.info("Features bootstrapped")
    except Exception as _e:
        _log.warning("bootstrap_features failed: %s", _e)

_bootstrap()

import sys
sys.path.insert(0, str(Path(__file__).parent))
from process_images import (
    process_all, RATIO_PRESETS,
    DEFAULT_JPEG_QUALITY, DEFAULT_MAX_RETRIES, DEFAULT_REQUEST_TIMEOUT,
    DEFAULT_BG_GREY, _preview_queue,
)

# ── Job registry — @st.cache_resource persists across reruns (unlike plain globals) ──
@st.cache_resource
def _get_jobs() -> dict:
    return {}

_JOBS = _get_jobs()   # same dict object every run — never wiped by st.rerun()

def _job_dir(jid):  return Path(tempfile.gettempdir()) / f"psydox_{jid}"
def _status_file(jid): return _job_dir(jid) / "status.json"

def _read_job(jid):
    """Return live status dict — memory first, then disk."""
    if jid in _JOBS:
        return _JOBS[jid]
    f = _status_file(jid)
    if f.exists():
        try:
            d = json.loads(f.read_text())
            _JOBS[jid] = d
            return d
        except Exception:
            pass
    return {}

def _flush_job(jid):
    """Write current memory state to disk (skip non-serialisable previews)."""
    try:
        safe = {k: v for k, v in _JOBS[jid].items() if k != "previews"}
        _status_file(jid).write_text(json.dumps(safe))
    except Exception:
        pass

# ── Auth ─────────────────────────────────────────────────────────────────────
# Legacy users.yaml kept for reference only — AuthService migrates it to DB on startup.
USERS_FILE = Path(__file__).parent / "users.yaml"

# ── Session defaults ──────────────────────────────────────────────────────────
for k, v in {"logged_in": False, "user_id": "", "session_id": "", "user_name": "",
              "user_email": "", "user_role": "viewer",
              "job_id": None, "preview_idx": 0, "zip_bytes": None, "zip_path": None,
              "excel_bytes": None, "nb_mode": False}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ── Recover job from URL ──────────────────────────────────────────────────────
_url_job = st.query_params.get("job")
_url_zip = st.query_params.get("zip")

if st.session_state.job_id is None:
    if _url_job:
        d = _read_job(_url_job)
        if d and not d.get("running"):
            # Only restore finished jobs — don't restore a wiped job folder
            if _job_dir(_url_job).exists():
                st.session_state.job_id = _url_job
            else:
                st.query_params.clear()
        elif d.get("running"):
            st.session_state.job_id = _url_job
    elif _url_zip:
        zp = _job_dir(_url_zip) / "_psydox_output.zip"
        if zp.exists():
            if _url_zip not in _JOBS:
                _JOBS[_url_zip] = {"running": False, "done": 0, "total": 0,
                                   "results": {"total":0,"success":0,"failed":0,"skipped":0},
                                   "error": None, "zip_path": str(zp), "previews": []}
            st.session_state.job_id = _url_zip

# ── Stale-job check: if memory has no thread but disk says running ─────────────
_jid = st.session_state.job_id
if _jid and _jid not in _JOBS:
    _d = _read_job(_jid)
    if _d.get("running"):
        _d["running"] = False
        _d["error"]   = "STALE"
        _JOBS[_jid]   = _d
        _flush_job(_jid)

# ═════════════════════════════════════════════════════════════════════════════
#  AUTH — login gate + per-load role refresh
# ═════════════════════════════════════════════════════════════════════════════
# render_auth_page is called on EVERY page load (not just when logged_out).
# For logged-in users it short-circuits: validates the session, refreshes
# user_role from DB (so admin role changes take effect on the next interaction),
# then returns True.  For guests it shows the login form and returns False.
try:
    from psydox.auth.service import get_auth_service
    from psydox.auth.ui import render_auth_page
    _auth_svc = get_auth_service()
    if not render_auth_page(_auth_svc):
        st.stop()
except Exception as _auth_err:
    _log.exception("Auth system error")
    st.error(
        "Authentication service unavailable. "
        "Please try refreshing. If the problem persists, contact your administrator."
    )
    st.stop()

# ── Post-auth job ownership check — clear job_id when it belongs to a different user ──
if st.session_state.job_id:
    _owned_d   = _read_job(st.session_state.job_id)
    _job_owner = _owned_d.get("owner", "")
    _cur_uid   = st.session_state.get("user_id", "")
    # Only enforce when both sides are populated (legacy jobs have no owner field)
    if _job_owner and _cur_uid and _job_owner != _cur_uid:
        _log.warning("Job %s owned by %s, not current user %s — clearing from session",
                     st.session_state.job_id, _job_owner, _cur_uid)
        st.session_state.job_id = None
        st.session_state.zip_path = None
        st.query_params.clear()

# ═════════════════════════════════════════════════════════════════════════════
#  BACKGROUND WORKER
# ═════════════════════════════════════════════════════════════════════════════
def _worker(job_id, cfg, out_dir):
    try:
        def _cb(done, total, active=0, started=0):
            _JOBS[job_id]["done"]    = done
            _JOBS[job_id]["total"]   = total
            _JOBS[job_id]["active"]  = active
            _JOBS[job_id]["started"] = started
            _max_prev = cfg.get("_max_previews", 100)
            try:
                while True:
                    _JOBS[job_id]["previews"].append(_preview_queue.get_nowait())
                    if len(_JOBS[job_id]["previews"]) > _max_prev:
                        _JOBS[job_id]["previews"] = _JOBS[job_id]["previews"][-_max_prev:]
            except Exception:
                pass
            if done % 10 == 0:
                _flush_job(job_id)

        res = process_all(cfg, progress_cb=_cb)

        try:
            while True:
                _JOBS[job_id]["previews"].append(_preview_queue.get_nowait())
        except Exception:
            pass

        out_files = [f for f in Path(out_dir).rglob("*")
                     if f.is_file() and f.suffix.lower() in (".jpg",".jpeg",".png",".webp")]
        zip_path = None
        if out_files:
            # Write ZIP directly to a .tmp file then rename — avoids loading
            # all images into memory at once (OOM risk on large batches).
            zp  = Path(out_dir) / "_psydox_output.zip"
            ztmp = Path(out_dir) / "_psydox_output.zip.tmp"
            with zipfile.ZipFile(ztmp, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
                for f in out_files:
                    zf.write(f, f.relative_to(out_dir))
            ztmp.rename(zp)
            zip_path = str(zp)

        _JOBS[job_id]["zip_path"] = zip_path
        _JOBS[job_id]["results"]  = res
    except Exception:
        import traceback
        _JOBS[job_id]["error"] = traceback.format_exc()
    finally:
        _JOBS[job_id]["running"] = False
        _flush_job(job_id)

# ═════════════════════════════════════════════════════════════════════════════
#  RAZORPAY PAYMENT RETURN — handle before any nav routing
# ═════════════════════════════════════════════════════════════════════════════
if st.query_params.get("rzpay") == "1":
    _order_id   = st.query_params.get("order_id", "")
    _payment_id = st.query_params.get("payment_id", "")
    _signature  = st.query_params.get("sig", "")
    if _order_id and _payment_id and _signature:
        try:
            from psydox.billing.service import get_billing_service
            _bsvc = get_billing_service()
            _ok = _bsvc.handle_payment_success(_order_id, _payment_id, _signature)
            if _ok:
                st.session_state["billing_success_msg"] = "Payment successful! Your wallet has been credited."
            else:
                st.session_state["billing_success_msg"] = "⚠️ Payment verification failed. Contact support."
        except Exception as _pay_err:
            _log.exception("Razorpay payment handling failed")
            st.session_state["billing_success_msg"] = f"Payment error: {_pay_err}"
    st.query_params.clear()
    st.session_state.psydox_nav = "wallet"
    st.rerun()

# ═════════════════════════════════════════════════════════════════════════════
#  NAV MODE
# ═════════════════════════════════════════════════════════════════════════════
if "psydox_nav" not in st.session_state:
    st.session_state.psydox_nav = "dashboard"

# Access flags — driven entirely by DB role, refreshed from DB on every load above.
# Never use hardcoded email checks here; role changes in admin panel take effect
# on the user's next page interaction.
_user_role      = st.session_state.get("user_role", "viewer")
_user_is_owner  = _user_role in ("owner", "admin")
_user_can_ai    = _user_role in ("owner",)
_user_can_batch = _user_role in ("owner", "admin", "manager", "operator",
                                  "editor", "creative", "catalog_operator")

# ── Progress polling fragment — defined and called UNCONDITIONALLY here so the
# run_every scheduler always finds it regardless of navigation state (BUG-004).
# Non-batch nav states return early and render nothing. ───────────────────────
_MAX_JOB_SECS = 7200  # 2-hour hard timeout (BUG-005 partial watchdog)

@st.fragment(run_every=2)
def _poll():
    try:
        if st.session_state.get("psydox_nav") not in ("batch", "classic"):
            return
        jid = st.session_state.get("job_id", "")
        if not jid:
            return
        j = _read_job(jid)
        if not j.get("running") and st.session_state.get("_shown_" + jid):
            return
        # BUG-005: timeout guard for stuck/hung worker threads
        if j.get("running") and j.get("started_at") and \
                time.time() - j["started_at"] > _MAX_JOB_SECS:
            j["running"] = False
            j["error"]   = "TIMEOUT: job exceeded maximum run time"
            _JOBS[jid]   = j
            _flush_job(jid)
            st.rerun(scope="app")
            return
        if j.get("running"):
            done   = j.get("done",   0)
            total  = j.get("total",  0)
            active = j.get("active", 0)
            pct    = done / total if total > 0 else 0
            label  = (f"✅  {done} / {total} done — {int(pct*100)}%"
                      f"  |  ⬇️ {active} downloading now")
            st.progress(pct, text=label)
        elif (j.get("results") or j.get("error")) and \
                not st.session_state.get("_shown_" + jid):
            st.session_state["_shown_" + jid] = True
            st.rerun(scope="app")
    except Exception:
        pass

_poll()

# ─── Dashboard view ──────────────────────────────────────────────────────────
if st.session_state.psydox_nav == "dashboard":
    try:
        from psydox.dashboard.page import render_dashboard

        def _on_feature(fid):
            # Route Quick Create features into the Studio with that tool pre-selected
            st.session_state.psydox_nav = "studio"
            st.session_state.studio_start_tool = fid
            st.rerun()

        def _go_classic():
            st.session_state.psydox_nav = "studio"
            st.session_state.studio_start_tool = "background"
            st.rerun()

        def _go_ai():
            if not _user_can_ai:
                st.error("AI Studio requires operator role or higher.")
                return
            st.session_state.psydox_nav = "studio"
            st.session_state.studio_start_tool = "ai_background"
            st.rerun()

        def _new_project():
            st.session_state.psydox_nav = "new_project"
            st.rerun()

        def _go_batch():
            st.session_state.psydox_nav = "batch"
            st.rerun()

        def _go_admin_users():
            if not _user_is_owner:
                st.error("Admin access requires owner or admin role.")
                return
            st.session_state.psydox_nav = "admin_users"
            st.rerun()

        def _go_wallet():
            st.session_state.psydox_nav = "wallet"
            st.rerun()

        render_dashboard(
            user_email=st.session_state.user_email,
            user_name=st.session_state.user_name,
            on_feature_select=_on_feature,
            on_classic=_go_classic,
            on_ai_studio=_go_ai if _user_can_ai else None,
            on_new_project=_new_project,
            on_batch=_go_batch,
            on_admin_users=_go_admin_users if _user_is_owner else None,
            on_wallet=_go_wallet,
        )
    except Exception as e:
        _log.exception("Dashboard render failed")
        st.error("An internal error occurred loading the dashboard. Please refresh or contact your administrator.")
    st.stop()

# ─── Studio view (single-image editor — Classic + AI) ────────────────────────
if st.session_state.psydox_nav == "studio":
    try:
        from psydox.studio.page import render_studio

        def _back_to_dash():
            st.session_state.psydox_nav = "dashboard"
            st.rerun()

        start_tool = st.session_state.pop("studio_start_tool", None)
        render_studio(
            user_email=st.session_state.user_email,
            user_name=st.session_state.user_name,
            on_back=_back_to_dash,
            start_tool=start_tool,
        )
    except Exception as e:
        _log.exception("Studio render failed")
        st.error("An internal error occurred loading the Studio. Please refresh or contact your administrator.")
    st.stop()

# ─── New project view ────────────────────────────────────────────────────────
if st.session_state.psydox_nav == "new_project":
    with st.sidebar:
        if st.button("← Dashboard"):
            st.session_state.psydox_nav = "dashboard"
            st.rerun()
    st.markdown("## + New Project")
    with st.form("new_project_form"):
        proj_name = st.text_input("Project name", placeholder="e.g. Summer Collection 2025")
        proj_desc = st.text_area("Description (optional)", height=80)
        submitted = st.form_submit_button("Create Project →", use_container_width=True)
    if submitted and proj_name.strip():
        try:
            from psydox.projects.service import get_project_service
            proj = get_project_service().create(
                name=proj_name.strip(),
                owner_email=st.session_state.user_email,
                description=proj_desc.strip(),
            )
            st.success(f"Project **{proj.name}** created! ID: `{proj.id}`")
            st.session_state.psydox_nav = "dashboard"
            st.rerun()
        except Exception as e:
            st.error(f"Could not create project: {e}")
    st.stop()

# ─── Wallet / Pricing view ───────────────────────────────────────────────────
if st.session_state.psydox_nav == "wallet":
    try:
        from psydox.billing.ui import render_wallet_page

        def _back_from_wallet():
            st.session_state.psydox_nav = "dashboard"
            st.rerun()

        render_wallet_page(on_back=_back_from_wallet)
    except Exception as e:
        _log.exception("Wallet page error")
        st.error("An internal error occurred loading the Wallet page. Please refresh or contact your administrator.")
    st.stop()

# ─── Admin Users view ────────────────────────────────────────────────────────
if st.session_state.psydox_nav == "admin_users":
    if not _user_is_owner:
        st.error("Access denied — admin only.")
        st.session_state.psydox_nav = "dashboard"
        st.rerun()
    else:
        try:
            from psydox.admin.users_page import render_admin_users_page
            render_admin_users_page(on_back=lambda: (
                setattr(st.session_state, "psydox_nav", "dashboard") or st.rerun()
            ))
        except Exception as e:
            _log.exception("Admin users page error")
            st.error("An internal error occurred loading the Admin page. Please refresh or contact your administrator.")
        st.stop()

# ─── Batch processing view (old classic Excel processor) ─────────────────────
# All nav states OTHER than "dashboard", "studio", "new_project" fall through
# to the batch processing UI below (psydox_nav == "batch" or legacy "classic").
# This preserves the existing Excel batch processor exactly as-is.
if st.session_state.psydox_nav not in ("batch", "classic"):
    # Unknown nav state — redirect to dashboard
    st.session_state.psydox_nav = "dashboard"
    st.rerun()

# Role gate — viewer/user/reviewer roles cannot access batch processing
if not _user_can_batch:
    st.error("⛔ You don't have permission to use the Batch Processor.")
    st.caption(f"Current role: **{_user_role}**. Ask an admin to update your role.")
    if st.button("← Back to Dashboard"):
        st.session_state.psydox_nav = "dashboard"
        st.rerun()
    st.stop()

# ═════════════════════════════════════════════════════════════════════════════
#  BATCH PROCESSING HEADER + SIDEBAR
# ═════════════════════════════════════════════════════════════════════════════
c1, c2, c3 = st.columns([6, 1, 1])
with c1:
    st.markdown("""<div style='background:#ff6600;padding:10px 20px;border-radius:8px;
    margin-bottom:16px;'><span style='color:white;font-size:22px;font-weight:bold'>
    ⚡ Psydox</span> <span style='color:#ffe0c0;font-size:13px'>Batch Processing
    </span></div>""", unsafe_allow_html=True)
with c2:
    if st.button("🏠 Dashboard", use_container_width=True):
        st.session_state.psydox_nav = "dashboard"
        st.rerun()
with c3:
    st.markdown(f"<div style='text-align:right;padding-top:6px;color:#888'>"
                f"👤 {st.session_state.user_name}</div>", unsafe_allow_html=True)
    if st.button("Sign Out"):
        try:
            from psydox.auth.service import get_auth_service
            get_auth_service().logout(
                st.session_state.get("session_id", ""),
                user_email=st.session_state.get("user_email", ""),
            )
        except Exception:
            pass
        st.session_state.logged_in  = False
        st.session_state.session_id = ""
        st.rerun()

with st.sidebar:
    st.markdown("## 📂 Upload Excel")
    uploaded = st.file_uploader("Excel (.xlsx / .xls)", type=["xlsx","xls"],
                                 key="file_uploader")
    if uploaded:
        st.session_state.excel_bytes = uploaded.getvalue()
    elif st.session_state.excel_bytes is None:
        # Show helper text when no file is loaded
        st.caption("No file loaded — please upload an Excel file.")

    have_file = st.session_state.excel_bytes is not None
    if have_file and not uploaded:
        st.caption("✅ File ready to process.")

    st.markdown("## 🖼️ Image Settings")
    rkeys = list(RATIO_PRESETS.keys())
    ridx  = next((i for i,k in enumerate(rkeys) if "1080" in k), 0)
    rc    = st.selectbox("Ratio Preset", rkeys, index=ridx)
    preset_size = RATIO_PRESETS[rc]
    tw, th = preset_size if preset_size is not None else (1080, 1350)
    col_w, col_h = st.columns(2)
    tw = col_w.number_input("Width (px)",  360, 4320, int(tw), key=f"tw_{rc}")
    th = col_h.number_input("Height (px)", 450, 5400, int(th), key=f"th_{rc}")
    jq = st.slider("JPEG Quality", 50, 95, int(DEFAULT_JPEG_QUALITY))

    st.markdown("## 🌐 Network")
    mr = st.number_input("Max Retries", 1, 10, 5)
    rt = st.number_input("Timeout (s)", 5, 120, int(DEFAULT_REQUEST_TIMEOUT))

    st.markdown("## 🎨 Background")
    BG = {
        "Auto (keep original)": "auto",
        "White": (255,255,255), "Ivory": (255,253,240), "Cream": (245,245,220),
        "Pearl": (240,240,240), "Silver": (220,220,220), "Grey": (200,200,200),
        "Ash": (180,180,180), "Stone": (150,150,150), "Slate": (100,100,100),
        "Charcoal": (60,60,60), "Dark": (30,30,30), "Black": (0,0,0),
        "Blush": (255,230,230), "Peach": (255,220,180), "Sky Blue": (200,220,245),
        "Lavender": (220,200,240), "Sage": (200,220,190),
    }
    bgc    = st.selectbox("Background", list(BG.keys()))
    bgrgb  = BG[bgc]
    bggrey = int(sum(bgrgb)/3) if isinstance(bgrgb, tuple) else DEFAULT_BG_GREY

    pack = st.checkbox("Pack Shot Mode")

    # AI Studio is now in the unified Studio workspace — not in batch mode.
    st.session_state.nb_mode = False
    if _user_can_ai:
        st.info("💡 Use **⚡ Classic Studio** or **✨ AI Studio** from the dashboard for single-image editing.")

    st.markdown("---")

    job    = _read_job(st.session_state.job_id) if st.session_state.job_id else {}
    is_run = job.get("running", False)

    run_btn = st.button("▶  RUN", use_container_width=True, type="primary",
                        disabled=(not have_file or is_run))

    # New Run — always visible when a job exists
    if st.session_state.job_id:
        if st.button("🔄  New Run", use_container_width=True):
            st.session_state.job_id    = None
            st.session_state.zip_bytes = None
            st.session_state.zip_path  = None
            st.session_state.excel_bytes = None
            # Clear the file uploader widget state so the old file doesn't
            # re-populate excel_bytes on the next render via retained widget state.
            st.session_state.pop("file_uploader", None)
            st.query_params.clear()
            st.rerun()

# ═════════════════════════════════════════════════════════════════════════════
#  START RUN
# ═════════════════════════════════════════════════════════════════════════════
if run_btn and have_file and not is_run:
    excel_bytes = st.session_state.excel_bytes
    # BUG-001/ZIP-001/SEC-005: use a cryptographically random ID so no two users
    # can ever share a job slot, and IDs are not guessable from file content.
    job_id      = secrets.token_hex(8)

    # Wipe stale output FIRST, then recreate and write Excel
    job_dir = _job_dir(job_id)
    if job_dir.exists():
        shutil.rmtree(str(job_dir), ignore_errors=True)
    job_dir.mkdir(parents=True, exist_ok=True)

    out_dir    = str(job_dir)
    excel_path = str(job_dir / "input.xlsx")
    with open(excel_path, "wb") as f:
        f.write(excel_bytes)

    cfg = dict(
        INPUT_EXCEL=excel_path, OUTPUT_FOLDER=out_dir,
        TARGET_W=int(tw), TARGET_H=int(th), JPEG_QUALITY=int(jq),
        MAX_RETRIES=int(mr), REQUEST_TIMEOUT=int(rt),
        USE_REMBG=False, BG_GREY=int(bggrey), BG_RGB=bgrgb, PACK_MODE=pack,
    )

    _JOBS[job_id] = {"running": True, "done": 0, "total": 0, "started": 0, "active": 0,
                     "results": None, "error": None, "zip_path": None, "previews": [],
                     # BUG-007/SEC-005: record owner so URL recovery can enforce isolation
                     "owner": st.session_state.get("user_id", ""),
                     # BUG-005: record start time for hung-job watchdog in _poll
                     "started_at": time.time()}
    _flush_job(job_id)

    st.session_state.job_id    = job_id
    st.session_state.zip_bytes = None
    st.session_state.zip_path  = None
    st.session_state.preview_idx = 0
    st.query_params["job"] = job_id

    threading.Thread(target=_worker, args=(job_id, cfg, out_dir), daemon=True).start()
    st.rerun()

# ═════════════════════════════════════════════════════════════════════════════
#  PROGRESS + RESULTS
# ═════════════════════════════════════════════════════════════════════════════
job_id = st.session_state.job_id
job    = _read_job(job_id) if job_id else {}

# ═════════════════════════════════════════════════════════════════════════════
#  RESULTS
# ═════════════════════════════════════════════════════════════════════════════
if job.get("error"):
    if job["error"] == "STALE":
        st.warning("Server restarted and lost the job. Click **🔄 New Run** in the sidebar to start again.")
    else:
        st.error("Processing error:")
        st.code(job["error"])

elif job.get("results"):
    res = job["results"]
    total   = res.get("total",   0)
    success = res.get("success", 0)
    failed  = res.get("failed",  0)
    skipped = res.get("skipped", 0)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total",       total)
    c2.metric("✓ Processed", success)
    c3.metric("✗ Failed DL", failed)
    c4.metric("⚠ Skipped",   skipped)
    if failed > 0 or skipped > 0:
        st.warning(
            f"⚠️ {failed} image(s) failed to download, {skipped} skipped. "
            "Only successful images are in the ZIP. "
            "Download the **Failed Excel** below to see which rows failed and the specific reason."
        )

    # Switch URL to ?zip= once done
    if job_id and st.query_params.get("zip") != job_id:
        st.query_params["zip"] = job_id
        try: del st.query_params["job"]
        except Exception: pass

    zp = job.get("zip_path")
    if zp and Path(zp).exists():
        # BUG-002/ZIP-002: validate without loading all bytes into memory;
        # stream the file directly to the download button instead of
        # caching the full bytes in session_state.
        if not st.session_state.get("zip_path"):
            try:
                with zipfile.ZipFile(zp) as _zf:
                    _bad = _zf.testzip()
                if _bad is not None:
                    raise zipfile.BadZipFile(f"corrupted entry: {_bad}")
                st.session_state.zip_path = zp  # store path, not bytes
            except zipfile.BadZipFile:
                st.error("⚠️ The ZIP file was corrupted (server may have restarted mid-write). "
                         "Click **🔄 New Run** in the sidebar to process again.")
                st.session_state.job_id  = None
                st.session_state.zip_path = None
                st.query_params.clear()
            except Exception as e:
                _log.exception("ZIP validation error")
                st.error("Could not validate the output ZIP. Please try again or contact your administrator.")

        if st.session_state.get("zip_path") and Path(st.session_state.zip_path).exists():
            mb = os.path.getsize(st.session_state.zip_path) / 1024 / 1024
            st.success(f"✅  Done — {mb:.1f} MB ZIP ready")
            if st.download_button(f"⬇  Download ZIP  ({mb:.1f} MB)",
                                  data=open(st.session_state.zip_path, "rb"),
                                  file_name="psydox_processed.zip",
                                  mime="application/zip",
                                  use_container_width=True):
                try:
                    shutil.rmtree(str(_job_dir(job_id)), ignore_errors=True)
                except Exception: pass
                st.session_state.zip_bytes   = None
                st.session_state.zip_path    = None
                st.session_state.job_id      = None
                st.session_state.excel_bytes = None
                _JOBS.pop(job_id, None)  # BUG-003: pop instead of del — never raises KeyError
                st.query_params.clear()
                gc.collect()

            # ── Failed images Excel (generated once, cached in session state) ─
            if failed > 0:
                _fex_key = f"_fex_{job_id}"
                if _fex_key not in st.session_state:
                    _fex_bytes = None
                    try:
                        import csv as _csv, types as _types
                        from psydox.batch.excel_reader import read_excel_bytes as _rxb
                        from psydox.batch.processor import build_failed_excel
                        _rp = res.get("report")
                        _eb = st.session_state.excel_bytes
                        if _rp and Path(_rp).exists() and _eb:
                            _rr = _rxb(_eb)
                            def _reason(s):
                                if s == "FAILED_DOWNLOAD": return "Download failed"
                                if s == "FAIL:INVALID_URL": return "Cell is not a URL (skipped)"
                                if s == "FAIL:DROPBOX_DELETED": return "Dropbox file deleted — re-upload and reshare"
                                if s == "FAIL:DROPBOX_BLOCKED": return "Dropbox link private or expired — set to 'Anyone with link'"
                                if s == "FAIL:HTML_RESPONSE": return "URL returned a webpage, not an image"
                                if s == "FAIL:HTTP_403": return "Access denied (403) — link is private or CDN blocked"
                                if s == "FAIL:HTTP_404": return "File not found (404) — URL no longer exists"
                                if s == "FAIL:HTTP_410": return "File deleted (410) — URL has been removed"
                                if s == "FAIL:HTTP_451": return "Unavailable for legal reasons (451)"
                                if s.startswith("FAILED_OPEN"): return "Could not open image"
                                if s == "FAILED_SAVE": return "Could not save image"
                                if s.startswith("FAILED_CONVERT"): return "Image conversion failed"
                                return s.replace("_", " ").title()
                            _seen, _fe = set(), []
                            with open(_rp, "r", encoding="utf-8") as _f:
                                for _row in _csv.DictReader(_f):
                                    _sc = _row.get("style_code", "")
                                    _st = _row.get("status", "OK")
                                    if _st != "OK" and _sc and _sc not in _seen:
                                        _seen.add(_sc)
                                        _fe.append(_types.SimpleNamespace(
                                            style_code=_sc,
                                            reason=_reason(_st),
                                            raw_row=_rr.raw_rows.get(_sc),
                                        ))
                            if _fe:
                                _fex_bytes = build_failed_excel(_fe, _rr.headers, _rr.raw_rows)
                    except Exception:
                        pass
                    st.session_state[_fex_key] = _fex_bytes
                if st.session_state.get(_fex_key):
                    st.download_button(
                        f"⬇ Download Failed Excel ({failed} records)",
                        data=st.session_state[_fex_key],
                        file_name="failed_images.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True,
                        key="batch_failed_dl_btn",
                    )
    else:
        if not job.get("running"):
            st.warning(
                "No output images — all downloads failed. "
                "**Common causes:** Dropbox files deleted or moved, links set to private "
                "(must be 'Anyone with the link'), or URLs require login. "
                "Download the Failed Excel below to see which rows failed and why."
            )

    st.markdown("---")

# ═════════════════════════════════════════════════════════════════════════════
#  BEFORE / AFTER PREVIEW
# ═════════════════════════════════════════════════════════════════════════════
previews = (_JOBS.get(job_id) or {}).get("previews", [])

if previews:
    st.markdown("### 🖼️ Before / After")
    total_p = len(previews)
    idx     = st.session_state.preview_idx
    n1, n2, n3 = st.columns([1, 6, 1])
    with n1:
        if st.button("❮", disabled=(idx == 0)):
            st.session_state.preview_idx = max(0, idx-1); st.rerun()
    with n2:
        st.markdown(f"<div style='text-align:center;padding-top:6px;color:#aaa'>"
                    f"<b>{idx+1}</b> / {total_p}</div>", unsafe_allow_html=True)
    with n3:
        if st.button("❯", disabled=(idx >= total_p-1)):
            st.session_state.preview_idx = min(total_p-1, idx+1); st.rerun()

    e = previews[idx]
    cb, _, ca = st.columns([10, 1, 10])
    with cb:
        # e[5] = actual original dims (added after thumbnail shrink); fall back to thumb size
        bw, bh = e[5] if len(e) > 5 else e[0].size
        bg = gcd(bw, bh) or 1  # BUG-008: guard against ZeroDivisionError when dim is 0
        st.markdown(f"**ORIGINAL** — <span style='color:#ff4444;font-size:22px'><b>{e[2]}%</b></span>",
                    unsafe_allow_html=True)
        st.image(e[0], use_container_width=True)
        st.caption(f"{bw}×{bh}px | {bw//bg}:{bh//bg}")
    with ca:
        # e[6] = actual output dims (the real saved file size, not the thumbnail)
        aw, ah = e[6] if len(e) > 6 else e[1].size
        ag = gcd(aw, ah) or 1  # BUG-008: guard against ZeroDivisionError when dim is 0
        st.markdown(f"**PROCESSED** — <span style='color:#00cc66;font-size:22px'><b>{e[3]}%</b></span>",
                    unsafe_allow_html=True)
        st.image(e[1], use_container_width=True)
        st.caption(f"{aw}×{ah}px | {aw//ag}:{ah//ag}")

elif not job.get("running") and not job.get("results") and not job.get("error"):
    st.markdown("""
    <div style='text-align:center;padding:80px 0;color:#555'>
      <div style='font-size:64px'>⚡</div>
      <h3 style='color:#666'>Upload your Excel and click RUN</h3>
    </div>""", unsafe_allow_html=True)

# Nano Banana is now an internal engine only.
# Single-image AI work happens in the Studio (psydox_nav="studio").
