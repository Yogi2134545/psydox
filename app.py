"""
Psydox — Streamlit Web App
Wraps the process_images.py engine with a browser-based UI.
"""
import streamlit as st
import yaml, bcrypt, zipfile, io, tempfile, threading, time
from pathlib import Path
from math import gcd

st.set_page_config(
    page_title="Psydox",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Import processing engine (no tkinter needed) ─────────────────────────────
import sys
sys.path.insert(0, str(Path(__file__).parent))

from process_images import (
    process_all, RATIO_PRESETS,
    DEFAULT_TARGET_W, DEFAULT_TARGET_H, DEFAULT_JPEG_QUALITY,
    DEFAULT_MAX_RETRIES, DEFAULT_REQUEST_TIMEOUT, DEFAULT_USE_REMBG,
    DEFAULT_BG_GREY, _preview_queue, compute_quality_score,
)

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

# ── Session state ─────────────────────────────────────────────────────────────
for k, v in {
    "logged_in": False, "user_name": "",
    "processing": False, "results": None,
    "preview_history": [], "preview_idx": 0,
    "zip_bytes": None,
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

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
                st.error("No users configured yet. Run `python create_users.py` first.")
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
#  MAIN APP
# ═════════════════════════════════════════════════════════════════════════════

# ── Top bar ───────────────────────────────────────────────────────────────────
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
    uploaded_excel = st.file_uploader("Excel File (.xlsx / .xls)",
                                      type=["xlsx", "xls"])

    st.markdown("## 🖼️ Image Settings")
    ratio_keys = list(RATIO_PRESETS.keys())
    default_ratio = next((k for k in ratio_keys if "1080" in k), ratio_keys[0])
    ratio_choice  = st.selectbox("Ratio Preset", ratio_keys,
                                  index=ratio_keys.index(default_ratio))
    tw, th = RATIO_PRESETS[ratio_choice]

    cw, ch = st.columns(2)
    target_w = cw.number_input("Width (px)",  360, 4320, int(tw))
    target_h = ch.number_input("Height (px)", 450, 5400, int(th))
    jpeg_quality = st.slider("JPEG Quality", 50, 95, int(DEFAULT_JPEG_QUALITY))

    st.markdown("## 🌐 Network")
    max_retries = st.number_input("Max Retries", 1, 10, int(DEFAULT_MAX_RETRIES))
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
    bg_choice = st.selectbox("Select background", list(BG_OPTIONS.keys()))
    bg_rgb_cfg = BG_OPTIONS[bg_choice]
    bg_grey    = int(sum(bg_rgb_cfg) / 3) if isinstance(bg_rgb_cfg, tuple) else DEFAULT_BG_GREY

    pack_mode = st.checkbox("Pack Shot Mode",
                            help="Combine multiple product views into one composite")

    st.markdown("---")
    run_btn = st.button("▶  RUN",
                        use_container_width=True,
                        type="primary",
                        disabled=(uploaded_excel is None or st.session_state.processing))

# ── RUN ───────────────────────────────────────────────────────────────────────
if run_btn and uploaded_excel and not st.session_state.processing:
    st.session_state.processing    = True
    st.session_state.preview_history = []
    st.session_state.preview_idx  = 0
    st.session_state.results      = None
    st.session_state.zip_bytes    = None

    # Save Excel to temp file
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp.write(uploaded_excel.getvalue())
        excel_path = tmp.name

    out_dir = tempfile.mkdtemp(prefix="psydox_")

    cfg = dict(
        INPUT_EXCEL   = excel_path,
        OUTPUT_FOLDER = out_dir,
        TARGET_W      = int(target_w),
        TARGET_H      = int(target_h),
        JPEG_QUALITY  = int(jpeg_quality),
        MAX_RETRIES   = int(max_retries),
        REQUEST_TIMEOUT = int(req_timeout),
        USE_REMBG     = False,
        BG_GREY       = int(bg_grey),
        BG_RGB        = bg_rgb_cfg,
        PACK_MODE     = pack_mode,
    )

    progress_bar  = st.progress(0, text="Starting…")
    status_text   = st.empty()

    def _progress_cb(done, total):
        pct = int(done / total * 100) if total else 0
        progress_bar.progress(pct, text=f"Processing {done} / {total} images…")
        # drain preview queue
        try:
            while True:
                st.session_state.preview_history.append(_preview_queue.get_nowait())
        except Exception:
            pass

    stop_ev = threading.Event()   # never set → runs to completion
    error_msg = None
    try:
        res = process_all(cfg, progress_cb=_progress_cb, stop_event=stop_ev)
    except Exception as e:
        import traceback
        error_msg = traceback.format_exc()
        res = None

    if error_msg:
        st.error(f"Processing error — check your Excel file and URLs")
        st.code(error_msg)

    # drain remaining preview items
    try:
        while True:
            st.session_state.preview_history.append(_preview_queue.get_nowait())
    except Exception:
        pass

    # Zip outputs — collect ALL image files written to out_dir
    out_files = [f for f in Path(out_dir).rglob("*")
                 if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")]
    if out_files:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in out_files:
                zf.write(f, f.relative_to(out_dir))
        buf.seek(0)
        st.session_state.zip_bytes = buf.getvalue()
    elif res and res.get("success", 0) == 0:
        st.warning("No images were processed. Check that your Excel URLs are accessible.")

    st.session_state.results   = res
    st.session_state.processing = False
    st.rerun()

# ── Stats + Download ──────────────────────────────────────────────────────────
if st.session_state.results:
    res = st.session_state.results
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total",       res.get("total",   0))
    c2.metric("✓ Processed", res.get("success", 0))
    c3.metric("✗ Failed",    res.get("failed",  0))
    c4.metric("⚠ Skipped",   res.get("skipped", 0))

    if st.session_state.zip_bytes:
        st.download_button(
            "⬇  Download All Processed Images  (.zip)",
            data      = st.session_state.zip_bytes,
            file_name = "psydox_processed.zip",
            mime      = "application/zip",
            use_container_width=True,
        )
    st.markdown("---")

# ── Before / After Preview ────────────────────────────────────────────────────
history = st.session_state.preview_history
if history:
    st.markdown("### 🖼️ Before / After Preview")

    total = len(history)
    idx   = st.session_state.preview_idx

    nav1, nav2, nav3 = st.columns([1, 6, 1])
    with nav1:
        if st.button("❮ Prev", disabled=(idx == 0)):
            st.session_state.preview_idx = max(0, idx - 1)
            st.rerun()
    with nav2:
        st.markdown(f"<div style='text-align:center;padding-top:6px;color:#aaa;'>"
                    f"Image  <b>{idx+1}</b>  /  {total}</div>",
                    unsafe_allow_html=True)
    with nav3:
        if st.button("Next ❯", disabled=(idx >= total - 1)):
            st.session_state.preview_idx = min(total - 1, idx + 1)
            st.rerun()

    entry       = history[idx]
    before_pil  = entry[0]
    after_pil   = entry[1]
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
        st.markdown(
            f"`{bw} × {bh} px` &nbsp;|&nbsp; "
            f"**Ratio {bw//bg} : {bh//bg}** &nbsp;|&nbsp; `{src_fmt}`")

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
        st.markdown(
            f"`{aw} × {ah} px` &nbsp;|&nbsp; "
            f"**Ratio {aw//ag} : {ah//ag}** &nbsp;|&nbsp; `JPEG`")

else:
    st.markdown("""
    <div style='text-align:center;padding:80px 0;color:#555;'>
      <div style='font-size:64px;'>⚡</div>
      <h3 style='color:#666;'>Upload your Excel file and click RUN</h3>
      <p style='color:#555;'>Processed images will appear here with before/after comparison</p>
    </div>""", unsafe_allow_html=True)
