"""
Psydox — Streamlit Web App
"""
import streamlit as st
import yaml, bcrypt, zipfile, json, tempfile, threading, gc, shutil, hashlib, time
from pathlib import Path
from math import gcd

st.set_page_config(
    page_title="Psydox",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

import sys
sys.path.insert(0, str(Path(__file__).parent))

from process_images import (
    process_all, RATIO_PRESETS,
    DEFAULT_TARGET_W, DEFAULT_TARGET_H, DEFAULT_JPEG_QUALITY,
    DEFAULT_MAX_RETRIES, DEFAULT_REQUEST_TIMEOUT, DEFAULT_USE_REMBG,
    DEFAULT_BG_GREY, _preview_queue, compute_quality_score,
)

# ─────────────────────────────────────────────────────────────────────────────
#  JOB STATE  (disk-based → survives process restarts + session resets)
#
#  All state lives in  {tmpdir}/psydox_{job_id}/
#    status.json  — {"running": bool, "done": int, "total": int,
#                    "error": str|null, "zip_path": str|null,
#                    "results": {...}|null}
#    previews/    — preview PNG pairs written by background thread
#
#  _JOBS dict is kept as a fast in-process cache (avoids disk reads every 2s).
# ─────────────────────────────────────────────────────────────────────────────
_JOBS: dict = {}   # in-memory cache

def _job_dir(job_id: str) -> Path:
    return Path(tempfile.gettempdir()) / f"psydox_{job_id}"

def _status_path(job_id: str) -> Path:
    return _job_dir(job_id) / "status.json"

def _read_status(job_id: str) -> dict:
    """Read job status — in-memory cache first, disk fallback."""
    if job_id in _JOBS:
        return _JOBS[job_id]
    sp = _status_path(job_id)
    if sp.exists():
        try:
            data = json.loads(sp.read_text())
            _JOBS[job_id] = data   # warm cache
            return data
        except Exception:
            pass
    return {}

def _write_status(job_id: str, data: dict):
    """Write status to both memory and disk — updates in-place to preserve references."""
    if job_id in _JOBS:
        _JOBS[job_id].update(data)   # in-place: background thread reference stays valid
    else:
        _JOBS[job_id] = dict(data)
    try:
        safe = {k: v for k, v in _JOBS[job_id].items() if k != "previews"}
        _status_path(job_id).write_text(json.dumps(safe))
    except Exception:
        pass


# ── Auth ──────────────────────────────────────────────────────────────────────
USERS_FILE = Path(__file__).parent / "users.yaml"

def _load_users():
    if not USERS_FILE.exists():
        return {}
    with open(USERS_FILE, "r") as f:
        return yaml.safe_load(f) or {}

def _check_credentials(email: str, password: str):
    users = _load_users()
    u = users.get(email.lower().strip())
    if u and bcrypt.checkpw(password.encode(), u["password_hash"].encode()):
        return u.get("name", email)
    return None


# ── Session state defaults ────────────────────────────────────────────────────
for k, v in {
    "logged_in": False, "user_name": "",
    "job_id": None,
    "preview_idx": 0,
    "zip_bytes": None,
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ── Recover job from URL after session expiry / process restart ───────────────
_url_job = st.query_params.get("job", None)
_url_zip = st.query_params.get("zip", None)

if st.session_state.job_id is None:
    # Recover via ?job= — works even after process restart (reads disk)
    if _url_job:
        status = _read_status(_url_job)
        if status:   # job dir exists on disk
            st.session_state.job_id = _url_job

    # Recover completed ZIP via ?zip=
    elif _url_zip:
        _candidate = _job_dir(_url_zip) / "_psydox_output.zip"
        if _candidate.exists():
            status = _read_status(_url_zip)
            if not status:
                status = {
                    "running": False, "done": 0, "total": 0,
                    "results": {"total": 0, "success": 0, "failed": 0, "skipped": 0},
                    "error": None, "zip_path": str(_candidate),
                }
                _write_status(_url_zip, status)
            st.session_state.job_id = _url_zip


# ═════════════════════════════════════════════════════════════════════════════
#  LOGIN PAGE
# ═════════════════════════════════════════════════════════════════════════════
if not st.session_state.logged_in:
    _, col, _ = st.columns([1, 2, 1])
    with col:
        st.markdown("""
        <div style='text-align:center;padding:40px 0 24px 0;'>
          <div style='font-size:56px;'>⚡</div>
          <h1 style='color:#ff6600;margin:0;letter-spacing:2px;'>Psydox</h1>
          <p style='color:#888;margin:4px 0 0 0;font-size:14px;'>Image Processing Engine</p>
        </div>
        """, unsafe_allow_html=True)

        with st.form("login"):
            email    = st.text_input("Email", placeholder="you@company.com")
            password = st.text_input("Password", type="password")
            login_btn = st.form_submit_button("Sign In →", use_container_width=True)

        if login_btn:
            if not USERS_FILE.exists():
                st.error("No users configured yet.")
            else:
                name = _check_credentials(email, password)
                if name:
                    st.session_state.logged_in = True
                    st.session_state.user_name = name
                    st.rerun()
                else:
                    st.error("Incorrect email or password.")
    st.stop()


# ═════════════════════════════════════════════════════════════════════════════
#  BACKGROUND WORKER
# ═════════════════════════════════════════════════════════════════════════════
def _bg_worker(job_id: str, cfg: dict, out_dir: str):
    """Background thread — always writes via _JOBS[job_id] directly (never a stale local ref)."""
    stop_ev = threading.Event()

    try:
        def _cb(done, total):
            # Write directly to _JOBS[job_id] — always the current object
            _JOBS[job_id]["done"]  = done
            _JOBS[job_id]["total"] = total
            # Drain preview queue
            try:
                while True:
                    _JOBS[job_id]["previews"].append(_preview_queue.get_nowait())
            except Exception:
                pass
            # Write to disk every 10 images so a fresh process can recover
            if done % 10 == 0:
                try:
                    safe = {k: v for k, v in _JOBS[job_id].items() if k != "previews"}
                    _status_path(job_id).write_text(json.dumps(safe))
                except Exception:
                    pass

        res = process_all(cfg, progress_cb=_cb, stop_event=stop_ev)

        # Drain remaining previews
        try:
            while True:
                _JOBS[job_id]["previews"].append(_preview_queue.get_nowait())
        except Exception:
            pass

        # Build ZIP on disk
        out_files = [f for f in Path(out_dir).rglob("*")
                     if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")]
        zip_path_str = None
        if out_files:
            zip_path = Path(out_dir) / "_psydox_output.zip"
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
                for f in out_files:
                    zf.write(f, f.relative_to(out_dir))
            zip_path_str = str(zip_path)

        _JOBS[job_id]["zip_path"] = zip_path_str
        _JOBS[job_id]["results"]  = res

    except Exception:
        import traceback
        _JOBS[job_id]["error"] = traceback.format_exc()
    finally:
        _JOBS[job_id]["running"] = False
        # Final disk write for recovery after process restart
        _write_status(job_id, {})


# ═════════════════════════════════════════════════════════════════════════════
#  MAIN APP  — top bar + sidebar
# ═════════════════════════════════════════════════════════════════════════════
c_logo, c_user = st.columns([7, 1])
with c_logo:
    st.markdown("""
    <div style='background:#ff6600;padding:10px 20px;border-radius:8px;
                margin-bottom:16px;display:flex;align-items:center;gap:12px;'>
      <span style='color:white;font-size:22px;font-weight:bold;'>⚡ Psydox</span>
      <span style='color:#ffe0c0;font-size:13px;'>Image Processing Engine</span>
    </div>""", unsafe_allow_html=True)
with c_user:
    st.markdown(f"<div style='text-align:right;padding-top:6px;color:#888;'>"
                f"👤 {st.session_state.user_name}</div>", unsafe_allow_html=True)
    if st.button("Sign Out"):
        st.session_state.logged_in = False
        st.rerun()

# ── SIDEBAR ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 📂 File Upload")
    uploaded_excel = st.file_uploader("Excel File (.xlsx / .xls)", type=["xlsx", "xls"])

    st.markdown("## 🖼️ Image Settings")
    ratio_keys    = list(RATIO_PRESETS.keys())
    default_ratio = next((k for k in ratio_keys if "1080" in k), ratio_keys[0])
    ratio_choice  = st.selectbox("Ratio Preset", ratio_keys,
                                  index=ratio_keys.index(default_ratio))
    tw, th = RATIO_PRESETS[ratio_choice]

    cw, ch = st.columns(2)
    target_w     = cw.number_input("Width (px)",  360, 4320, int(tw))
    target_h     = ch.number_input("Height (px)", 450, 5400, int(th))
    jpeg_quality = st.slider("JPEG Quality", 50, 95, int(DEFAULT_JPEG_QUALITY))

    st.markdown("## 🌐 Network")
    max_retries = st.number_input("Max Retries", 1, 10, 5)
    req_timeout = st.number_input("Timeout (s)", 5, 120, int(DEFAULT_REQUEST_TIMEOUT))

    st.markdown("## 🎨 Background Color")
    BG_OPTIONS = {
        "Auto (keep original)": "auto",
        "White":     (255, 255, 255),
        "Ivory":     (255, 253, 240),
        "Cream":     (245, 245, 220),
        "Pearl":     (240, 240, 240),
        "Silver":    (220, 220, 220),
        "Grey":      (200, 200, 200),
        "Ash":       (180, 180, 180),
        "Stone":     (150, 150, 150),
        "Slate":     (100, 100, 100),
        "Charcoal":  (60,  60,  60),
        "Dark":      (30,  30,  30),
        "Black":     (0,   0,   0),
        "Blush":     (255, 230, 230),
        "Peach":     (255, 220, 180),
        "Sky Blue":  (200, 220, 245),
        "Lavender":  (220, 200, 240),
        "Sage":      (200, 220, 190),
    }
    bg_choice  = st.selectbox("Select background", list(BG_OPTIONS.keys()))
    bg_rgb_cfg = BG_OPTIONS[bg_choice]
    bg_grey    = int(sum(bg_rgb_cfg) / 3) if isinstance(bg_rgb_cfg, tuple) else DEFAULT_BG_GREY

    pack_mode = st.checkbox("Pack Shot Mode",
                            help="Combine multiple product views into one composite")

    st.markdown("---")

    # Read current job status for sidebar controls
    _sidebar_job = _read_status(st.session_state.job_id) if st.session_state.job_id else {}
    is_running   = _sidebar_job.get("running", False)

    run_btn = st.button("▶  RUN",
                        use_container_width=True,
                        type="primary",
                        disabled=(uploaded_excel is None or is_running))


# ═════════════════════════════════════════════════════════════════════════════
#  START RUN
# ═════════════════════════════════════════════════════════════════════════════
if run_btn and uploaded_excel and not is_running:
    excel_bytes = uploaded_excel.getvalue()
    job_id      = hashlib.md5(excel_bytes).hexdigest()[:8]

    # Save Excel to a stable path (background thread needs it)
    out_dir = str(_job_dir(job_id))
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    excel_path = str(Path(out_dir) / "input.xlsx")
    with open(excel_path, "wb") as f:
        f.write(excel_bytes)

    cfg = dict(
        INPUT_EXCEL     = excel_path,
        OUTPUT_FOLDER   = out_dir,
        TARGET_W        = int(target_w),
        TARGET_H        = int(target_h),
        JPEG_QUALITY    = int(jpeg_quality),
        MAX_RETRIES     = int(max_retries),
        REQUEST_TIMEOUT = int(req_timeout),
        USE_REMBG       = False,
        BG_GREY         = int(bg_grey),
        BG_RGB          = bg_rgb_cfg,
        PACK_MODE       = pack_mode,
    )

    # Initialise job state (memory + disk) BEFORE starting thread
    initial_status = {
        "running": True, "done": 0, "total": 0,
        "results": None, "error": None, "zip_path": None,
    }
    _write_status(job_id, initial_status)
    # previews live only in memory
    _JOBS[job_id]["previews"] = []

    st.session_state.job_id     = job_id
    st.session_state.zip_bytes  = None
    st.session_state.preview_idx = 0

    # Put job_id in URL immediately so any session reset can recover it
    st.query_params["job"] = job_id

    threading.Thread(target=_bg_worker, args=(job_id, cfg, out_dir), daemon=True).start()
    st.rerun()


# ═════════════════════════════════════════════════════════════════════════════
#  PROGRESS FRAGMENT  — auto-refreshes every 2 s without blocking WebSocket
# ═════════════════════════════════════════════════════════════════════════════
@st.fragment(run_every=2)
def _progress_fragment():
    job_id = st.session_state.job_id
    if not job_id:
        return
    status = _read_status(job_id)

    if status.get("running"):
        done  = status.get("done",  0)
        total = status.get("total", 0)
        pct   = done / total if total > 0 else 0
        label = f"⏳  Processing  {done} / {total}  images…  ({int(pct*100)}%)"
        st.progress(pct, text=label)
        st.info("Running in background — updates every 2 seconds.")
    elif status.get("results") or status.get("error"):
        # Job just finished — trigger full page rerun to show results/download
        st.rerun(scope="app")

_progress_fragment()


# ═════════════════════════════════════════════════════════════════════════════
#  RESULTS
# ═════════════════════════════════════════════════════════════════════════════
job_id = st.session_state.job_id
status = _read_status(job_id) if job_id else {}

# Keep URL in sync
if job_id and not status.get("running"):
    if status.get("zip_path"):
        st.query_params["zip"] = job_id
        try:
            del st.query_params["job"]
        except Exception:
            pass
elif job_id and status.get("running"):
    st.query_params["job"] = job_id

if status.get("error"):
    st.error("Processing error — check your Excel file and image URLs")
    st.code(status["error"])

if status.get("results"):
    res = status["results"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total",       res.get("total",   0))
    c2.metric("✓ Processed", res.get("success", 0))
    c3.metric("✗ Failed",    res.get("failed",  0))
    c4.metric("⚠ Skipped",   res.get("skipped", 0))

    zip_path = status.get("zip_path")
    if zip_path and Path(zip_path).exists():
        if not st.session_state.zip_bytes:
            zip_size_mb = Path(zip_path).stat().st_size / 1024 / 1024
            if zip_size_mb > 500:
                st.warning(f"ZIP is {zip_size_mb:.0f} MB — loading…")
            try:
                with open(zip_path, "rb") as _zf:
                    st.session_state.zip_bytes = _zf.read()
            except Exception as _ze:
                st.error(f"Could not read ZIP: {_ze}")

        if st.session_state.zip_bytes:
            size_mb = len(st.session_state.zip_bytes) / 1024 / 1024
            st.success(f"✅  ZIP ready — {size_mb:.1f} MB")
            clicked = st.download_button(
                f"⬇  Download All Processed Images (.zip)  —  {size_mb:.1f} MB",
                data      = st.session_state.zip_bytes,
                file_name = "psydox_processed.zip",
                mime      = "application/zip",
                use_container_width=True,
                key       = "download_zip",
            )
            if clicked:
                try:
                    shutil.rmtree(str(_job_dir(job_id)), ignore_errors=True)
                    st.session_state.zip_bytes = None
                    st.session_state.job_id    = None
                    if job_id in _JOBS:
                        del _JOBS[job_id]
                    st.query_params.clear()
                except Exception:
                    pass
                gc.collect()
    else:
        if not status.get("running"):
            st.warning("No output images found. Check that your Excel URLs are publicly accessible.")

    st.markdown("---")


# ═════════════════════════════════════════════════════════════════════════════
#  BEFORE / AFTER PREVIEW
# ═════════════════════════════════════════════════════════════════════════════
# Previews live only in memory (_JOBS), not persisted to disk
previews = _JOBS.get(job_id, {}).get("previews", []) if job_id else []

if previews:
    st.markdown("### 🖼️ Before / After Preview")

    total_p = len(previews)
    idx     = st.session_state.preview_idx

    nav1, nav2, nav3 = st.columns([1, 6, 1])
    with nav1:
        if st.button("❮ Prev", disabled=(idx == 0)):
            st.session_state.preview_idx = max(0, idx - 1)
            st.rerun()
    with nav2:
        st.markdown(f"<div style='text-align:center;padding-top:6px;color:#aaa;'>"
                    f"Image  <b>{idx+1}</b>  /  {total_p}</div>",
                    unsafe_allow_html=True)
    with nav3:
        if st.button("Next ❯", disabled=(idx >= total_p - 1)):
            st.session_state.preview_idx = min(total_p - 1, idx + 1)
            st.rerun()

    entry        = previews[idx]
    before_pil   = entry[0]
    after_pil    = entry[1]
    before_score = entry[2]
    after_score  = entry[3]
    src_fmt      = entry[4] if len(entry) > 4 else "—"

    col_b, col_arr, col_a = st.columns([10, 1, 10])

    with col_b:
        bw, bh = before_pil.size
        bg = gcd(bw, bh)
        st.markdown(
            f"**ORIGINAL** &nbsp;&nbsp;"
            f"<span style='color:#ff4444;font-size:24px;font-weight:bold;'>{before_score}%</span>"
            f" &nbsp;Quality",
            unsafe_allow_html=True)
        st.image(before_pil, use_container_width=True)
        st.markdown(f"`{bw} × {bh} px` &nbsp;|&nbsp; **Ratio {bw//bg} : {bh//bg}** &nbsp;|&nbsp; `{src_fmt}`")

    with col_arr:
        st.markdown(
            "<div style='text-align:center;font-size:32px;padding-top:45%;color:#ff6600;'>→</div>",
            unsafe_allow_html=True)

    with col_a:
        aw, ah = after_pil.size
        ag = gcd(aw, ah)
        st.markdown(
            f"**PROCESSED** &nbsp;&nbsp;"
            f"<span style='color:#00cc66;font-size:24px;font-weight:bold;'>{after_score}%</span>"
            f" &nbsp;Quality",
            unsafe_allow_html=True)
        st.image(after_pil, use_container_width=True)
        st.markdown(f"`{aw} × {ah} px` &nbsp;|&nbsp; **Ratio {aw//ag} : {ah//ag}** &nbsp;|&nbsp; `JPEG`")

else:
    if not status.get("running") and not status.get("results"):
        st.markdown("""
        <div style='text-align:center;padding:80px 0;color:#555;'>
          <div style='font-size:64px;'>⚡</div>
          <h3 style='color:#666;'>Upload your Excel file and click RUN</h3>
          <p style='color:#555;'>Processed images will appear here with before/after comparison</p>
        </div>""", unsafe_allow_html=True)
