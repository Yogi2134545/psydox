"""Psydox — Nike Image Processor"""
import streamlit as st
import yaml, bcrypt, zipfile, json, tempfile, threading, gc, shutil, hashlib
from pathlib import Path
from math import gcd

st.set_page_config(page_title="Psydox", page_icon="⚡", layout="wide",
                   initial_sidebar_state="expanded")

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
USERS_FILE = Path(__file__).parent / "users.yaml"

def _load_users():
    if not USERS_FILE.exists(): return {}
    with open(USERS_FILE) as f: return yaml.safe_load(f) or {}

def _check_creds(email, password):
    u = _load_users().get(email.lower().strip())
    if u and bcrypt.checkpw(password.encode(), u["password_hash"].encode()):
        return u.get("name", email)
    return None

# ── Session defaults ──────────────────────────────────────────────────────────
for k, v in {"logged_in": False, "user_name": "", "job_id": None,
              "preview_idx": 0, "zip_bytes": None, "excel_bytes": None}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ── Recover job from URL ──────────────────────────────────────────────────────
_url_job = st.query_params.get("job")
_url_zip = st.query_params.get("zip")

if st.session_state.job_id is None:
    if _url_job:
        d = _read_job(_url_job)
        if d:
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
#  LOGIN
# ═════════════════════════════════════════════════════════════════════════════
if not st.session_state.logged_in:
    _, col, _ = st.columns([1, 2, 1])
    with col:
        st.markdown("""
        <div style='text-align:center;padding:40px 0 24px'>
          <div style='font-size:56px'>⚡</div>
          <h1 style='color:#ff6600;margin:0;letter-spacing:2px'>Psydox</h1>
          <p style='color:#888;font-size:14px'>Image Processing Engine</p>
        </div>""", unsafe_allow_html=True)
        with st.form("login"):
            email = st.text_input("Email", placeholder="you@company.com")
            pwd   = st.text_input("Password", type="password")
            ok    = st.form_submit_button("Sign In →", use_container_width=True)
        if ok:
            name = _check_creds(email, pwd)
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
def _worker(job_id, cfg, out_dir):
    try:
        def _cb(done, total):
            _JOBS[job_id]["done"]  = done
            _JOBS[job_id]["total"] = total
            try:
                while True:
                    _JOBS[job_id]["previews"].append(_preview_queue.get_nowait())
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
            zp = Path(out_dir) / "_psydox_output.zip"
            with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
                for f in out_files:
                    zf.write(f, f.relative_to(out_dir))
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
#  HEADER + SIDEBAR
# ═════════════════════════════════════════════════════════════════════════════
c1, c2 = st.columns([7, 1])
with c1:
    st.markdown("""<div style='background:#ff6600;padding:10px 20px;border-radius:8px;
    margin-bottom:16px;'><span style='color:white;font-size:22px;font-weight:bold'>
    ⚡ Psydox</span> <span style='color:#ffe0c0;font-size:13px'>Image Processing Engine
    </span></div>""", unsafe_allow_html=True)
with c2:
    st.markdown(f"<div style='text-align:right;padding-top:6px;color:#888'>"
                f"👤 {st.session_state.user_name}</div>", unsafe_allow_html=True)
    if st.button("Sign Out"):
        st.session_state.logged_in = False
        st.rerun()

with st.sidebar:
    st.markdown("## 📂 Upload Excel")
    uploaded = st.file_uploader("Excel (.xlsx / .xls)", type=["xlsx","xls"],
                                 key="file_uploader")
    # Persist bytes so they survive reruns
    if uploaded:
        st.session_state.excel_bytes = uploaded.getvalue()

    have_file = st.session_state.excel_bytes is not None

    st.markdown("## 🖼️ Image Settings")
    rkeys = list(RATIO_PRESETS.keys())
    ridx  = next((i for i,k in enumerate(rkeys) if "1080" in k), 0)
    rc    = st.selectbox("Ratio Preset", rkeys, index=ridx)
    tw, th = RATIO_PRESETS[rc]
    col_w, col_h = st.columns(2)
    tw = col_w.number_input("Width (px)",  360, 4320, int(tw))
    th = col_h.number_input("Height (px)", 450, 5400, int(th))
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
            st.session_state.excel_bytes = None
            st.query_params.clear()
            st.rerun()

# ═════════════════════════════════════════════════════════════════════════════
#  START RUN
# ═════════════════════════════════════════════════════════════════════════════
if run_btn and have_file and not is_run:
    excel_bytes = st.session_state.excel_bytes
    job_id      = hashlib.md5(excel_bytes).hexdigest()[:8]
    out_dir     = str(_job_dir(job_id))
    Path(out_dir).mkdir(parents=True, exist_ok=True)

    excel_path = str(Path(out_dir) / "input.xlsx")
    with open(excel_path, "wb") as f:
        f.write(excel_bytes)

    cfg = dict(
        INPUT_EXCEL=excel_path, OUTPUT_FOLDER=out_dir,
        TARGET_W=int(tw), TARGET_H=int(th), JPEG_QUALITY=int(jq),
        MAX_RETRIES=int(mr), REQUEST_TIMEOUT=int(rt),
        USE_REMBG=False, BG_GREY=int(bggrey), BG_RGB=bgrgb, PACK_MODE=pack,
    )

    _JOBS[job_id] = {"running": True, "done": 0, "total": 0,
                     "results": None, "error": None, "zip_path": None, "previews": []}
    _flush_job(job_id)

    st.session_state.job_id    = job_id
    st.session_state.zip_bytes = None
    st.session_state.preview_idx = 0
    st.query_params["job"] = job_id

    threading.Thread(target=_worker, args=(job_id, cfg, out_dir), daemon=True).start()
    st.rerun()

# ═════════════════════════════════════════════════════════════════════════════
#  PROGRESS  (only auto-refresh when job is actually running)
# ═════════════════════════════════════════════════════════════════════════════
job_id = st.session_state.job_id
job    = _read_job(job_id) if job_id else {}

@st.fragment(run_every=2)
def _poll():
    j = _read_job(st.session_state.job_id) if st.session_state.job_id else {}
    if j.get("running"):
        done  = j.get("done",  0)
        total = j.get("total", 0)
        pct   = done / total if total > 0 else 0
        st.progress(pct, text=f"⏳  {done} / {total} images — {int(pct*100)}%")
        st.info("Processing… updates every 2 s")
    elif j.get("results") or j.get("error"):
        # Job just finished — do one full rerun to show download button / error
        st.rerun(scope="app")

_poll()

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
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total",       res.get("total",   0))
    c2.metric("✓ Processed", res.get("success", 0))
    c3.metric("✗ Failed",    res.get("failed",  0))
    c4.metric("⚠ Skipped",   res.get("skipped", 0))

    # Switch URL to ?zip= once done
    if job_id and st.query_params.get("zip") != job_id:
        st.query_params["zip"] = job_id
        try: del st.query_params["job"]
        except Exception: pass

    zp = job.get("zip_path")
    if zp and Path(zp).exists():
        if not st.session_state.zip_bytes:
            try:
                with open(zp, "rb") as f:
                    st.session_state.zip_bytes = f.read()
            except Exception as e:
                st.error(f"Could not load ZIP: {e}")

        if st.session_state.zip_bytes:
            mb = len(st.session_state.zip_bytes) / 1024 / 1024
            st.success(f"✅  Done — {mb:.1f} MB ZIP ready")
            if st.download_button(f"⬇  Download ZIP  ({mb:.1f} MB)",
                                  data=st.session_state.zip_bytes,
                                  file_name="psydox_processed.zip",
                                  mime="application/zip",
                                  use_container_width=True):
                try:
                    shutil.rmtree(str(_job_dir(job_id)), ignore_errors=True)
                except Exception: pass
                st.session_state.zip_bytes   = None
                st.session_state.job_id      = None
                st.session_state.excel_bytes = None
                del _JOBS[job_id]
                st.query_params.clear()
                gc.collect()
    else:
        if not job.get("running"):
            st.warning("No output images — check your Excel URLs are publicly accessible.")

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
        bw, bh = e[0].size; bg = gcd(bw, bh)
        st.markdown(f"**ORIGINAL** — <span style='color:#ff4444;font-size:22px'><b>{e[2]}%</b></span>",
                    unsafe_allow_html=True)
        st.image(e[0], use_container_width=True)
        st.caption(f"{bw}×{bh}px | {bw//bg}:{bh//bg}")
    with ca:
        aw, ah = e[1].size; ag = gcd(aw, ah)
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
