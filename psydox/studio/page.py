"""
Psydox Studio — unified single-image editing workspace.

Layout:
  ┌─────────────────────────────────────────────────────────────┐
  │  TOP BAR: ⚡ PSYDOX  [Project]  [← Back]  [Undo] [Export] │
  ├──────────┬──────────────────────────────────┬───────────────┤
  │ TOOLBAR  │           CANVAS                 │  PROPERTIES   │
  │ (tools)  │  (upload zone / image / compare) │  (tool UI)    │
  └──────────┴──────────────────────────────────┴───────────────┘

Classic tools visible to all users.
AI tools visible and executable ONLY by the owner account.
"""
from __future__ import annotations

import io
import logging
from typing import Any

import streamlit as st
from PIL import Image

from psydox.access import require_owner
from psydox.studio.executor import execute_tool, exec_enhance


@st.cache_data(show_spinner=False, max_entries=50)
def _image_wh(image_bytes: bytes) -> tuple:
    return Image.open(io.BytesIO(image_bytes)).size


@st.cache_data(show_spinner=False, max_entries=50)
def _cached_quality_score(image_bytes: bytes):
    from psydox.quality.engine import AIQualityEngine
    return AIQualityEngine().score(image_bytes)


@st.cache_data(show_spinner=False, max_entries=5)
def _cached_read_excel(excel_bytes: bytes):
    from psydox.batch.excel_reader import read_excel_bytes
    return read_excel_bytes(excel_bytes)


def _render_provider_selector() -> str | None:
    """Show provider status + selector. Returns the selected provider id or None."""
    try:
        from psydox.ai_core.provider_registry import get_provider_registry
        registry = get_provider_registry()
        infos    = registry.list()

        # Build status display
        status_lines = []
        for info in infos:
            dot = "●" if info.status.value == "configured" else "○"
            color = info.status_color
            status_lines.append(
                f'<span style="color:{color};font-size:11px;">'
                f'{info.icon} {info.display_name} — {info.status_label}</span>'
            )
        st.markdown(
            '<div class="psx-props-header">AI PROVIDER</div>'
            + "<br>".join(status_lines),
            unsafe_allow_html=True,
        )

        configured = [i for i in infos if i.status.value == "configured"]
        if not configured:
            st.warning("No AI provider configured. Ask the admin to set an API key in Railway environment variables.")
            return None

        options      = [i.id for i in configured]
        labels       = {i.id: f"{i.icon} {i.display_name}" for i in configured}
        current      = st.session_state.get("studio_provider", options[0])
        if current not in options:
            current = options[0]

        selected = st.selectbox(
            "Provider", options, index=options.index(current),
            format_func=lambda x: labels.get(x, x),
            key="studio_provider_sel",
        )
        st.session_state["studio_provider"] = selected

        # Show model for selected provider
        sel_info = next((i for i in infos if i.id == selected), None)
        if sel_info:
            st.caption(f"Model: {sel_info.default_model}")

        st.markdown("---")
        return selected
    except Exception as e:
        st.caption(f"Provider status unavailable: {e}")
        return None

_log = logging.getLogger("psydox.studio")

# ── Tool definitions ──────────────────────────────────────────────────────────
# Each entry: (id, icon, label, requires_ai)
_CLASSIC_TOOLS = [
    ("background",  "🎨", "Background",  False),
    ("resize",      "📐", "Resize",      False),
    ("crop",        "✂️",  "Crop",        False),
    ("enhance",     "✨", "Enhance",     False),
    ("masking",     "🎭", "Masking",     False),
    ("packshot",    "📦", "Packshot",    False),
    ("marketplace", "🛒", "Marketplace", False),
]

_AI_TOOLS = [
    ("ai_background", "🤖", "AI Background", True),
    ("ai_lifestyle",  "🌴", "AI Lifestyle",  True),
    ("ai_model",      "👤", "AI Model",      True),
    ("ai_scene",      "🏠", "AI Scene",      True),
    ("ai_angles",     "🎯", "AI Angles",     True),
    ("jadu_ka_ghar",  "🪄", "Jadu Ka Ghar",  True),
]

# ── State helpers ─────────────────────────────────────────────────────────────

def _ensure_state() -> None:
    defaults: dict[str, Any] = {
        "studio_history":      [],       # list of {"bytes": bytes, "label": str}
        "studio_history_idx":  -1,
        "studio_tool":         "background",
        "studio_project_name": "Untitled Project",
        "studio_tool_params":  {},       # {tool_id: {param: value}}
        "studio_compare":      "before_after",  # "single" | "before_after"
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def _current_bytes() -> bytes | None:
    h   = st.session_state.studio_history
    idx = st.session_state.studio_history_idx
    if not h or idx < 0 or idx >= len(h):
        return None
    return h[idx]["bytes"]


def _original_bytes() -> bytes | None:
    h = st.session_state.studio_history
    return h[0]["bytes"] if h else None


def _push_history(img_bytes: bytes, label: str) -> None:
    h   = st.session_state.studio_history
    idx = st.session_state.studio_history_idx
    # Truncate any redo states above current position
    new_h = h[: idx + 1] + [{"bytes": img_bytes, "label": label}]
    # Keep at most 12 history states to avoid excessive memory use
    if len(new_h) > 12:
        new_h = [new_h[0]] + new_h[-11:]
    st.session_state.studio_history      = new_h
    st.session_state.studio_history_idx  = len(new_h) - 1


def _tool_params(tool_id: str) -> dict:
    return st.session_state.studio_tool_params.get(tool_id, {})


def _set_tool_param(tool_id: str, key: str, value: Any) -> None:
    p = st.session_state.studio_tool_params
    if tool_id not in p:
        p[tool_id] = {}
    p[tool_id][key] = value


# ── CSS injection ─────────────────────────────────────────────────────────────

def _inject_css() -> None:
    st.markdown("""
<style>
/* Studio top bar */
.psx-studio-topbar {
    display: flex; align-items: center; gap: 8px;
    background: var(--background-color, #0f0f0f);
    border-bottom: 1px solid rgba(255,255,255,.08);
    padding: 6px 0 10px; margin-bottom: 8px;
}

/* Tool button grid */
.psx-tool-btn {
    display: flex; flex-direction: column; align-items: center;
    padding: 8px 6px; border-radius: 8px; cursor: pointer;
    font-size: 11px; color: var(--text-color, #ccc);
    border: 1px solid transparent;
    transition: background .15s, border-color .15s;
}
.psx-tool-btn:hover  { background: rgba(255,255,255,.06); border-color: rgba(255,255,255,.12); }
.psx-tool-btn.active { background: rgba(99,102,241,.18);  border-color: #6366f1; color: #818cf8; }
.psx-tool-btn .icon  { font-size: 18px; margin-bottom: 3px; }
.psx-tool-btn .ai-dot { display: inline-block; width: 5px; height: 5px;
    border-radius: 50%; background: #6366f1; margin-left: 3px; vertical-align: super; }

/* Canvas container */
.psx-canvas-wrap {
    background: #141414; border-radius: 10px; overflow: hidden;
    border: 1px solid rgba(255,255,255,.07);
    min-height: 380px; display: flex; align-items: center; justify-content: center;
}

/* Upload drop zone */
.psx-upload-zone {
    text-align: center; padding: 60px 24px;
    border: 2px dashed rgba(255,255,255,.15); border-radius: 12px;
    color: rgba(255,255,255,.4); width: 100%;
}
.psx-upload-zone .icon { font-size: 48px; margin-bottom: 12px; }
.psx-upload-zone h3 { font-size: 1.1rem; margin: 0 0 6px; color: rgba(255,255,255,.7); }

/* Properties panel */
.psx-props-header {
    font-size: 0.75rem; font-weight: 600; letter-spacing: .08em;
    text-transform: uppercase; color: rgba(255,255,255,.4);
    margin: 0 0 10px; padding-bottom: 6px;
    border-bottom: 1px solid rgba(255,255,255,.08);
}

/* History item */
.psx-hist-item {
    display: inline-block; padding: 4px 10px; border-radius: 20px;
    font-size: 11px; background: rgba(255,255,255,.06);
    border: 1px solid rgba(255,255,255,.08); margin: 2px;
    color: rgba(255,255,255,.6);
}
.psx-hist-item.current {
    background: rgba(99,102,241,.2); border-color: #6366f1;
    color: #a5b4fc; font-weight: 600;
}

/* AI badge */
.psx-ai-badge {
    display: inline-block; padding: 1px 6px; border-radius: 4px;
    font-size: 9px; font-weight: 700; letter-spacing: .06em;
    background: rgba(99,102,241,.25); color: #818cf8;
    text-transform: uppercase; vertical-align: middle; margin-left: 4px;
}

/* Owner banner */
.psx-owner-banner {
    background: linear-gradient(90deg, rgba(99,102,241,.15), rgba(168,85,247,.15));
    border: 1px solid rgba(99,102,241,.3); border-radius: 8px;
    padding: 6px 12px; font-size: 12px; color: #a5b4fc;
    margin-bottom: 8px;
}
</style>
""", unsafe_allow_html=True)


# ── Main entry point ──────────────────────────────────────────────────────────

def render_studio(
    user_email: str = "",
    user_name:  str = "",
    on_back: callable | None = None,
    start_tool: str | None = None,
) -> None:
    """Render the full Psydox Studio workspace."""
    _ensure_state()
    _inject_css()

    # AI tools are shown when the user's DB role permits — refreshed by auth on every load.
    _ai_roles = ("owner",)
    is_owner_user = st.session_state.get("user_role", "viewer") in _ai_roles

    if start_tool and st.session_state.studio_tool != start_tool:
        st.session_state.studio_tool = start_tool

    # ── Top bar ───────────────────────────────────────────────────────────────
    tb1, tb2, tb3, tb4, tb5, tb6 = st.columns([1.8, 2.5, 1.2, 0.8, 0.8, 1.2])
    with tb1:
        st.markdown(
            '<span style="font-size:1.3rem;font-weight:800;color:#6366f1;">⚡ PSYDOX</span>'
            f'<span style="font-size:0.75rem;color:rgba(255,255,255,.4);margin-left:6px;">'
            f'{"AI Studio" if (is_owner_user and st.session_state.get("studio_tool","").startswith(("ai_","jadu"))) else "Classic Studio"}</span>',
            unsafe_allow_html=True,
        )
    with tb2:
        new_name = st.text_input(
            "", value=st.session_state.studio_project_name,
            placeholder="Project name", label_visibility="collapsed",
            key="studio_proj_name",
        )
        if new_name != st.session_state.studio_project_name:
            st.session_state.studio_project_name = new_name
    with tb3:
        if on_back and st.button("← Dashboard", use_container_width=True, key="stu_back"):
            on_back()
    with tb4:
        h = st.session_state.studio_history
        idx = st.session_state.studio_history_idx
        if st.button("↩ Undo", disabled=(idx <= 0), use_container_width=True, key="stu_undo"):
            st.session_state.studio_history_idx -= 1
            st.rerun()
    with tb5:
        if st.button("↪ Redo", disabled=(idx >= len(h) - 1), use_container_width=True, key="stu_redo"):
            st.session_state.studio_history_idx += 1
            st.rerun()
    with tb6:
        cur = _current_bytes()
        if cur:
            _is_png = cur[:4] == b'\x89PNG'
            _ext  = "png" if _is_png else "jpg"
            _mime = "image/png" if _is_png else "image/jpeg"
            _proj = st.session_state.studio_project_name.replace(' ', '_')
            st.download_button(
                "⬇ Export", data=cur,
                file_name=f"{_proj}.{_ext}",
                mime=_mime, use_container_width=True, key="stu_export",
            )

    st.markdown("<div style='margin-bottom:4px'/>", unsafe_allow_html=True)

    # ── No image: show upload zone ────────────────────────────────────────────
    if not st.session_state.studio_history:
        _render_upload_zone(is_owner_user)
        return

    # ── Main workspace ────────────────────────────────────────────────────────
    tool_col, canvas_col, props_col = st.columns([1.3, 4, 2.2], gap="small")

    with tool_col:
        _render_toolbar(user_email, is_owner_user)

    with canvas_col:
        _render_canvas(is_owner_user)

    with props_col:
        _render_properties(user_email, is_owner_user)


# ── Upload zone ───────────────────────────────────────────────────────────────

def _render_upload_zone(is_owner_user: bool) -> None:
    tab_img, tab_excel = st.tabs(["📸 Single Image", "📊 Excel Batch Import"])

    with tab_img:
        st.markdown(
            '<div class="psx-upload-zone">'
            '<div class="icon">📸</div>'
            '<h3>Drop your product image here</h3>'
            '<p>JPEG, PNG, WebP supported</p>'
            '</div>',
            unsafe_allow_html=True,
        )
        uploaded = st.file_uploader(
            "Upload image", type=["jpg", "jpeg", "png", "webp"],
            label_visibility="collapsed", key="studio_uploader",
        )
        if uploaded:
            if _do_upload(uploaded):
                st.rerun()

    with tab_excel:
        _render_excel_import()


def _do_upload(uploaded_file) -> bool:
    from psydox.security.upload import validate_upload
    raw = uploaded_file.getvalue()
    result = validate_upload(raw, uploaded_file.name)
    if not result.valid:
        for e in result.errors:
            st.error(e)
        return False
    for w in result.warnings:
        st.warning(w)
    # Reset history with the uploaded image as the first state
    st.session_state.studio_history      = [{"bytes": raw, "label": "Original"}]
    st.session_state.studio_history_idx  = 0
    st.session_state.studio_project_name = uploaded_file.name.rsplit(".", 1)[0].replace("_", " ").title()
    return True


def _render_excel_import() -> None:
    """
    Excel batch import panel.

    Excel format:
      Column 1:  STYLE_CODE  (product identifier)
      Column 2+: Image URLs  (up to 12 columns of image links per row)

    Two modes:
      • Load single  — pick one style code + URL → open in Studio editor
      • Run Bulk     — process ALL style codes, download ZIP
    """
    from psydox.batch.processor import RATIO_PRESETS, BG_OPTIONS, BatchConfig
    from psydox.batch.excel_reader import read_excel_bytes, download_image

    st.markdown(
        '<div class="psx-props-header">EXCEL CATALOG IMPORT</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "Column 1 = Style Code  |  Columns 2–13 = Image URLs. "
        "Supports Google Drive, Dropbox, OneDrive, and direct links."
    )

    excel_file = st.file_uploader(
        "Upload Excel catalog",
        type=["xlsx", "xls"],
        key="studio_excel_uploader",
        label_visibility="collapsed",
    )
    if excel_file:
        st.session_state["studio_excel_data"] = excel_file.getvalue()
        st.session_state.pop("studio_batch_result", None)

    excel_data: bytes | None = st.session_state.get("studio_excel_data")
    if not excel_data:
        st.info("Upload an Excel file to import product images from a catalog.")
        return

    read_result = _cached_read_excel(excel_data)
    if read_result.errors:
        for err in read_result.errors:
            st.error(err)
        return
    for warn in read_result.warnings:
        st.warning(warn)

    st.success(
        f"**{read_result.total_styles}** style codes · "
        f"**{read_result.total_urls}** image URLs"
    )

    # ── Output settings ───────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown('<div class="psx-props-header">OUTPUT SETTINGS</div>', unsafe_allow_html=True)

    preset_options = list(RATIO_PRESETS.keys())
    chosen_preset  = st.selectbox("Ratio", preset_options, index=0, key="excel_ratio")
    preset_size    = RATIO_PRESETS[chosen_preset]
    if preset_size is None:
        col_w, col_h = st.columns(2)
        custom_w = col_w.number_input("Width",  360, 4320, 1080, key="excel_cust_w")
        custom_h = col_h.number_input("Height", 360, 5400, 1350, key="excel_cust_h")
        target_w, target_h = int(custom_w), int(custom_h)
    else:
        target_w, target_h = preset_size

    bg_name = st.selectbox("Background", list(BG_OPTIONS.keys()), key="excel_bg")
    bg_val  = BG_OPTIONS[bg_name]

    jq = st.slider("JPEG Quality", 50, 95, 92, key="excel_jq")

    # ── Tabs: Single load vs Bulk run ──────────────────────────────────────────
    st.markdown("---")
    t_single, t_bulk = st.tabs(["Open Single in Studio", "⚡ Run Bulk (ZIP)"])

    with t_single:
        style_codes   = sorted(read_result.styles.keys())
        selected_code = st.selectbox(
            "Style code", style_codes, key="studio_excel_code_sel",
        )
        if selected_code:
            urls = read_result.styles[selected_code]
            st.caption(f"{len(urls)} URL(s)")
            if len(urls) == 1:
                chosen_url = urls[0]
            else:
                chosen_url = st.selectbox(
                    "Image URL", urls,
                    format_func=lambda u: u[:85] + ("…" if len(u) > 85 else ""),
                    key="studio_excel_url_sel",
                )

            if st.button(
                f"Load '{selected_code}' into Studio",
                use_container_width=True, type="primary",
                key="studio_excel_load_btn",
            ):
                with st.spinner(f"Downloading {selected_code}…"):
                    img_bytes = download_image(chosen_url, timeout=15)
                if not img_bytes:
                    st.error(f"Could not download image. Check that the URL is public.")
                    return
                try:
                    from psydox.security.upload import validate_upload
                    v = validate_upload(img_bytes, f"{selected_code}.jpg")
                    if not v.valid:
                        for e in v.errors: st.error(e)
                        return
                    for w in v.warnings: st.warning(w)
                except Exception:
                    pass
                st.session_state.studio_history     = [{"bytes": img_bytes, "label": f"Original ({selected_code})"}]
                st.session_state.studio_history_idx = 0
                st.session_state.studio_project_name = selected_code
                st.rerun()

    with t_bulk:
        n_styles = read_result.total_styles
        n_imgs   = read_result.total_urls
        st.caption(
            f"Will download **{n_imgs}** images across **{n_styles}** style codes, "
            f"resize to **{target_w}×{target_h}** ({chosen_preset.split('(')[0].strip()}), "
            f"background **{bg_name}**, JPEG quality **{jq}**, output as ZIP."
        )

        if st.button(
            f"⚡ Run Bulk ({n_styles} styles)",
            use_container_width=True, type="primary",
            key="studio_bulk_run_btn",
        ):
            from psydox.batch.processor import run_batch

            cfg = BatchConfig(
                target_w=target_w,
                target_h=target_h,
                jpeg_quality=jq,
                bg_rgb=bg_val,
            )

            progress_bar  = st.progress(0.0, text="Starting…")
            status_text   = st.empty()

            def _cb(done: int, total: int, style: str) -> None:
                pct = done / total if total > 0 else 0
                progress_bar.progress(pct, text=f"Processing {style}… ({done}/{total})")
                status_text.caption(f"Last: {style}")

            with st.spinner("Running batch…"):
                batch_result = run_batch(
                    read_result.styles, cfg, progress_cb=_cb,
                    raw_rows=read_result.raw_rows,
                    headers=read_result.headers,
                )

            progress_bar.empty()
            status_text.empty()
            st.session_state["studio_batch_result"] = batch_result

        # Show result / download
        batch_result = st.session_state.get("studio_batch_result")
        if batch_result:
            c1, c2, c3 = st.columns(3)
            c1.metric("✓ Processed", batch_result.success)
            c2.metric("✗ Failed DL", batch_result.failed)
            c3.metric("⚠ Skipped",   batch_result.skipped)

            if batch_result.errors:
                with st.expander(f"Errors ({len(batch_result.errors)})"):
                    for e in batch_result.errors[:20]:
                        st.caption(e)

            if batch_result.zip_bytes:
                mb = len(batch_result.zip_bytes) / 1024 / 1024
                st.success(f"ZIP ready — {mb:.1f} MB")
                st.download_button(
                    f"⬇ Download ZIP ({mb:.1f} MB)",
                    data=batch_result.zip_bytes,
                    file_name="psydox_batch.zip",
                    mime="application/zip",
                    use_container_width=True,
                    key="studio_bulk_dl_btn",
                )
            elif batch_result.success == 0:
                st.warning("No images were processed. Check that your URLs are publicly accessible.")

            if batch_result.failed_excel_bytes:
                st.download_button(
                    f"⬇ Download Failed Excel ({batch_result.failed} records)",
                    data=batch_result.failed_excel_bytes,
                    file_name="failed_images.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                    key="studio_bulk_failed_dl_btn",
                )


# ── Toolbar ───────────────────────────────────────────────────────────────────

def _render_toolbar(user_email: str, is_owner_user: bool) -> None:
    st.markdown('<div class="psx-props-header">TOOLS</div>', unsafe_allow_html=True)

    # Upload a different image
    new_upload = st.file_uploader(
        "Change image", type=["jpg", "jpeg", "png", "webp"],
        key="studio_change_img", label_visibility="collapsed",
    )
    if new_upload:
        if _do_upload(new_upload):
            st.rerun()
    st.caption("Change image")

    st.markdown("---")
    st.caption("CLASSIC")

    active = st.session_state.studio_tool
    for tid, icon, label, _ in _CLASSIC_TOOLS:
        is_active = active == tid
        btn_style = "primary" if is_active else "secondary"
        if st.button(
            f"{icon} {label}",
            key=f"tool_{tid}", use_container_width=True, type=btn_style,
        ):
            st.session_state.studio_tool = tid
            st.rerun()

    if is_owner_user:
        st.markdown("---")
        st.markdown(
            '<div class="psx-owner-banner">✨ AI Tools — Owner</div>',
            unsafe_allow_html=True,
        )
        for tid, icon, label, _ in _AI_TOOLS:
            is_active = active == tid
            btn_style = "primary" if is_active else "secondary"
            if st.button(
                f"{icon} {label} ",
                key=f"tool_{tid}", use_container_width=True, type=btn_style,
            ):
                st.session_state.studio_tool = tid
                st.rerun()


# ── Canvas ────────────────────────────────────────────────────────────────────

def _render_canvas(is_owner_user: bool) -> None:
    cur = _current_bytes()
    orig = _original_bytes()
    idx = st.session_state.studio_history_idx

    if not cur:
        return

    compare = st.session_state.get("studio_compare", "before_after")

    # Compare toggle (only when we have more than the original)
    if idx > 0:
        cmp_c1, cmp_c2 = st.columns([3, 1])
        with cmp_c2:
            new_compare = st.selectbox(
                "", ["Before / After", "Current only"],
                index=0 if compare == "before_after" else 1,
                key="canvas_compare_sel", label_visibility="collapsed",
            )
            st.session_state.studio_compare = "before_after" if "Before" in new_compare else "single"
        compare = st.session_state.studio_compare

    if compare == "before_after" and orig and cur != orig:
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown("**Original**")
            st.image(orig, use_container_width=True)
        with col_b:
            st.markdown("**Current**")
            st.image(cur, use_container_width=True)
    else:
        st.image(cur, caption="Current", use_container_width=True)

    # Quality badge
    try:
        qs = _cached_quality_score(cur)
        verdict_color = {"APPROVED": "#22c55e", "REVIEW": "#f59e0b", "NEEDS_FIX": "#ef4444"}.get(
            qs.verdict.value, "#888"
        )
        st.markdown(
            f'<div style="font-size:11px;color:rgba(255,255,255,.5);margin-top:4px;">'
            f'Quality: <span style="color:{verdict_color};font-weight:600;">'
            f'{qs.verdict.value}</span> · {qs.score}/100</div>',
            unsafe_allow_html=True,
        )
    except Exception:
        pass

    # History timeline
    h = st.session_state.studio_history
    if len(h) > 1:
        st.markdown("---")
        st.caption("History")
        hist_html = ""
        for i, state in enumerate(h):
            is_cur = i == st.session_state.studio_history_idx
            cls = "psx-hist-item current" if is_cur else "psx-hist-item"
            hist_html += f'<span class="{cls}">{state["label"]}</span>'
        st.markdown(hist_html, unsafe_allow_html=True)

        hc1, hc2, hc3 = st.columns(3)
        with hc1:
            if st.button("↩ Undo", key="canvas_undo",
                         disabled=(st.session_state.studio_history_idx <= 0),
                         use_container_width=True):
                st.session_state.studio_history_idx -= 1
                st.rerun()
        with hc2:
            if st.button("↪ Redo", key="canvas_redo",
                         disabled=(st.session_state.studio_history_idx >= len(h) - 1),
                         use_container_width=True):
                st.session_state.studio_history_idx += 1
                st.rerun()
        with hc3:
            if st.button("🔄 Reset", key="canvas_reset", use_container_width=True):
                st.session_state.studio_history     = [h[0]]
                st.session_state.studio_history_idx = 0
                st.rerun()


# ── Properties panel dispatch ─────────────────────────────────────────────────

def _render_properties(user_email: str, is_owner_user: bool) -> None:
    tool = st.session_state.studio_tool
    cur  = _current_bytes()

    all_tools = dict((t[0], t) for t in _CLASSIC_TOOLS + _AI_TOOLS)
    if tool not in all_tools:
        st.info("Select a tool from the left toolbar.")
        return

    tid, icon, label, requires_ai = all_tools[tool]

    # Security gate — AI tools require editor role or higher
    if requires_ai and not is_owner_user:
        st.error("AI tools require editor, manager, admin, or owner role.")
        return

    # Billing gate — owner/admin bypass; other roles need wallet balance
    if requires_ai:
        _role = st.session_state.get("user_role", "viewer")
        if _role not in ("owner", "admin"):
            try:
                from psydox.billing.service import get_billing_service
                _uid = st.session_state.get("user_id", "")
                if _uid:
                    _bal = get_billing_service().get_balance(_uid)
                    _bal_inr = _bal.balance_inr
                    import os as _os
                    _min_inr = float(_os.environ.get("BILLING_MIN_BALANCE_INR", "1"))
                    if _bal_inr < _min_inr:
                        st.warning(
                            f"**💳 Wallet balance:** ₹{_bal_inr:.2f}  \n"
                            f"A minimum of ₹{_min_inr:.2f} is required to use AI tools."
                        )
                        if st.button("Top Up Wallet →", key="billing_topup_from_studio",
                                     use_container_width=True, type="primary"):
                            st.session_state.psydox_nav = "wallet"
                            st.rerun()
                        return
                    st.caption(f"💳 Wallet: ₹{_bal_inr:.2f}")
            except Exception as _billing_err:
                _log.warning("Billing gate check failed: %s", _billing_err)

    st.markdown(
        f'<div class="psx-props-header">{icon} {label.upper()}'
        + ('&nbsp;<span class="psx-ai-badge">AI</span>' if requires_ai else "")
        + "</div>",
        unsafe_allow_html=True,
    )

    if not cur:
        st.info("Upload an image to begin.")
        return

    # Route to the right property renderer + executor
    dispatch = {
        "background":    _props_background,
        "resize":        _props_resize,
        "crop":          _props_crop,
        "enhance":       _props_enhance,
        "masking":       _props_masking,
        "packshot":      _props_packshot,
        "marketplace":   _props_marketplace,
        "ai_background": _props_ai_background,
        "ai_lifestyle":  _props_ai_lifestyle,
        "ai_model":      _props_ai_model,
        "ai_scene":      _props_ai_scene,
        "ai_angles":     _props_ai_angles,
        "jadu_ka_ghar":  _props_jadu_ka_ghar,
    }
    fn = dispatch.get(tool)
    if fn:
        fn(cur, user_email)


# ═════════════════════════════════════════════════════════════════════════════
#  CLASSIC TOOL PANELS
# ═════════════════════════════════════════════════════════════════════════════

def _props_background(cur: bytes, user_email: str) -> None:
    from psydox.features.background.service import SOLID_COLORS, GRADIENT_PRESETS

    mode = st.selectbox("Mode", ["Solid Color", "Gradient", "Transparent"],
                        key="bg_mode")

    inputs: dict = {"image_bytes": cur}

    if mode == "Solid Color":
        color_name = st.selectbox("Color", list(SOLID_COLORS.keys()),
                                  index=0, key="bg_color_name")
        custom_hex = st.text_input("Custom HEX (overrides above)", placeholder="#ffffff",
                                   key="bg_hex").strip()
        inputs["bg_type"] = "solid"
        if custom_hex.startswith("#") and len(custom_hex) in (4, 7):
            try:
                h = custom_hex.lstrip("#")
                if len(h) == 3:
                    h = h[0]*2 + h[1]*2 + h[2]*2
                rgb = tuple(int(h[i:i+2], 16) for i in (0, 2, 4))
                inputs["color_rgb"] = rgb
            except Exception:
                inputs["color_name"] = color_name
        else:
            inputs["color_name"] = color_name

    elif mode == "Gradient":
        grad_name = st.selectbox("Gradient", list(GRADIENT_PRESETS.keys()),
                                 key="bg_gradient")
        inputs["bg_type"]       = "gradient"
        inputs["gradient_name"] = grad_name

    else:  # Transparent
        inputs["bg_type"] = "transparent"

    _apply_button("background", cur, "Apply Background", inputs=inputs)


def _props_resize(cur: bytes, user_email: str) -> None:
    from psydox.batch.processor import RATIO_PRESETS

    ow, oh = _image_wh(cur)
    st.caption(f"Original: {ow} × {oh} px")

    # Ratio preset selector
    preset_options = list(RATIO_PRESETS.keys())
    chosen_preset = st.selectbox("Ratio preset", preset_options,
                                 index=0, key="resize_preset")
    preset_size = RATIO_PRESETS[chosen_preset]

    if preset_size is not None:
        tw, th = preset_size
        st.caption(f"Output: {tw} × {th} px")
    else:
        col_w, col_h = st.columns(2)
        tw = col_w.number_input("Width (px)",  64, 8000, ow, step=10, key="resize_w")
        th = col_h.number_input("Height (px)", 64, 8000, oh, step=10, key="resize_h")

    mode_map = {"Fit (letterbox)": "fit", "Fill (crop)": "fill", "Stretch": "stretch"}
    fit_mode = mode_map[st.selectbox("Fit mode", list(mode_map.keys()), key="resize_fit")]

    inputs = {
        "image_bytes": cur,
        "operation": "resize",
        "target_w": int(tw),
        "target_h": int(th),
        "fit_mode": fit_mode,
    }
    _apply_button("resize", cur, "Apply Resize", inputs=inputs)


def _props_crop(cur: bytes, user_email: str) -> None:
    ow, oh = _image_wh(cur)
    st.caption(f"Original: {ow} × {oh} px")

    mode = st.radio("Crop mode", ["Ratio preset", "Manual"], key="crop_mode", horizontal=True)

    if mode == "Ratio preset":
        ratios = {"1:1 (Square)": (1, 1), "4:3": (4, 3), "3:4": (3, 4),
                  "16:9": (16, 9), "9:16": (9, 16), "2:3": (2, 3), "3:2": (3, 2)}
        ratio_key = st.selectbox("Ratio", list(ratios.keys()), key="crop_ratio")
        rw, rh = ratios[ratio_key]
        # Center crop to ratio
        if ow / oh > rw / rh:
            nw, nh = int(oh * rw / rh), oh
        else:
            nw, nh = ow, int(ow * rh / rw)
        left  = (ow - nw) // 2
        top   = (oh - nh) // 2
        right = left + nw
        bottom = top + nh
    else:
        c1, c2 = st.columns(2)
        left   = c1.number_input("Left",   0, ow, 0, key="crop_l")
        top    = c2.number_input("Top",    0, oh, 0, key="crop_t")
        right  = c1.number_input("Right",  0, ow, ow, key="crop_r")
        bottom = c2.number_input("Bottom", 0, oh, oh, key="crop_b")
        nw, nh = int(right - left), int(bottom - top)

    st.caption(f"Output: {nw} × {nh} px")
    if nw <= 0 or nh <= 0:
        st.warning("Invalid crop box — Right must be greater than Left, and Bottom greater than Top.")
        return
    inputs = {
        "image_bytes": cur,
        "operation": "crop",
        "crop_box": (int(left), int(top), int(right), int(bottom)),
    }
    _apply_button("crop", cur, "Apply Crop", inputs=inputs)


def _props_enhance(cur: bytes, user_email: str) -> None:
    st.caption("Adjust image properties (1.0 = unchanged)")
    brightness = st.slider("Brightness", 0.2, 2.0, 1.0, 0.05, key="enh_bright")
    contrast   = st.slider("Contrast",   0.2, 2.0, 1.0, 0.05, key="enh_contrast")
    saturation = st.slider("Saturation", 0.0, 2.0, 1.0, 0.05, key="enh_sat")
    sharpness  = st.slider("Sharpness",  0.0, 2.0, 1.0, 0.05, key="enh_sharp")

    if st.button("✨ Apply Enhance", use_container_width=True, type="primary", key="btn_enhance"):
        with st.spinner("Enhancing..."):
            result = exec_enhance(cur, brightness, contrast, saturation, sharpness)
        if result is None:
            st.error("Enhance failed — please try again.")
        elif result:
            changed = []
            if brightness != 1.0: changed.append(f"brightness {brightness:.2f}")
            if contrast   != 1.0: changed.append(f"contrast {contrast:.2f}")
            if saturation != 1.0: changed.append(f"saturation {saturation:.2f}")
            if sharpness  != 1.0: changed.append(f"sharpness {sharpness:.2f}")
            label = "Enhance: " + (", ".join(changed) if changed else "no change")
            _push_history(result, label)
            st.rerun()


def _props_masking(cur: bytes, user_email: str) -> None:
    from psydox.masking.engine import _rembg_ok, _cv2_ok

    if _rembg_ok:
        engine_note = "rembg (AI segmentation)"
    elif _cv2_ok:
        engine_note = "OpenCV edge-detection"
    else:
        engine_note = "basic (no cv2/rembg)"
    st.caption(f"Engine: {engine_note}")

    MODE_LABELS = {
        "Remove BG (transparent PNG)": "transparent",
        "Replace BG — White":          "white_bg",
        "Replace BG — Custom colour":  "custom_bg",
        "Detect bounding box":         "detect",
    }
    mode_label = st.selectbox("Mode", list(MODE_LABELS.keys()), key="mask_mode")
    mode       = MODE_LABELS[mode_label]

    inputs: dict = {"image_bytes": cur, "mode": mode}

    if mode == "custom_bg":
        hex_val = st.text_input("Background HEX", value="#ffffff",
                                placeholder="#rrggbb", key="mask_hex").strip()
        try:
            h = hex_val.lstrip("#")
            if len(h) == 3:
                h = h[0]*2 + h[1]*2 + h[2]*2
            if len(h) == 6:
                inputs["bg_rgb"] = tuple(int(h[i:i+2], 16) for i in (0, 2, 4))
            else:
                st.warning("Invalid HEX — using white.")
                inputs["bg_rgb"] = (255, 255, 255)
        except Exception:
            st.warning("Invalid HEX — using white.")
            inputs["bg_rgb"] = (255, 255, 255)

    if mode == "transparent":
        st.info("Output will be a PNG with a transparent background.")

    _apply_button("masking", cur, mode_label, inputs=inputs)


def _props_packshot(cur: bytes, user_email: str) -> None:
    size = st.selectbox("Output size", ["2000×2000", "1500×1500", "1080×1080", "800×800"],
                        key="pack_size")
    sz = int(size.split("×")[0])
    padding = st.slider("Padding (%)", 2, 20, 8, key="pack_pad") / 100.0
    bg_color = st.selectbox("Background", ["White", "Black", "Transparent"],
                            key="pack_bg")
    inputs = {
        "image_bytes": cur,
        "operation":   "packshot",
        "size":        sz,
        "padding":     padding,
        "bg_color":    bg_color.lower(),
    }
    _apply_button("packshot", cur, "Create Packshot", inputs=inputs)


def _props_marketplace(cur: bytes, user_email: str) -> None:
    from psydox.features.classic.service import MARKETPLACE_PRESETS
    preset_labels = {v["label"]: k for k, v in MARKETPLACE_PRESETS.items()}
    selected = st.multiselect(
        "Platforms", list(preset_labels.keys()),
        default=["Amazon Main", "Instagram Square"],
        key="mp_presets",
    )
    if not selected:
        st.info("Select at least one platform.")
        return

    preset_ids = [preset_labels[s] for s in selected]
    st.caption(f"{len(preset_ids)} format(s) selected — creates a ZIP on download")

    inputs = {
        "image_bytes": cur,
        "operation":   "marketplace",
        "presets":     preset_ids,
    }
    _apply_button("marketplace", cur, "Generate Marketplace Pack", inputs=inputs,
                  multi_output=True)


# ═════════════════════════════════════════════════════════════════════════════
#  AI TOOL PANELS  (owner only — _render_properties already gates entry)
# ═════════════════════════════════════════════════════════════════════════════

def _props_ai_background(cur: bytes, user_email: str) -> None:
    provider_id = _render_provider_selector()
    if provider_id is None:
        return
    from psydox.features.background.service import AI_BG_TYPES
    ai_type = st.selectbox("Scene type", AI_BG_TYPES, key="ai_bg_type")
    custom_prompt = ""
    if ai_type == "Custom AI":
        custom_prompt = st.text_area("Describe the background", height=80,
                                     placeholder="e.g. 'minimalist white studio with soft shadows'",
                                     key="ai_bg_prompt")
    else:
        st.caption(_ai_bg_description(ai_type))
        custom_prompt = st.text_input("Additional details (optional)", key="ai_bg_extra")

    inputs = {
        "image_bytes":   cur,
        "bg_type":       ai_type.lower().replace(" ", "_"),
        "ai_prompt":     custom_prompt,
        "_provider_id":  provider_id,
    }
    _apply_button("ai_background", cur, "🤖 Generate Background", inputs=inputs,
                  user_email=user_email, is_ai=True)


def _ai_bg_description(ai_type: str) -> str:
    desc = {
        "Studio":    "Clean studio lighting, pure white/grey backdrop, product focused",
        "Lifestyle": "Real-world context, natural environment, authentic feel",
        "Outdoor":   "Natural outdoor setting — park, street, nature",
        "Editorial": "High-fashion editorial look, dramatic lighting",
    }
    return desc.get(ai_type, "")


def _props_ai_lifestyle(cur: bytes, user_email: str) -> None:
    provider_id = _render_provider_selector()
    if provider_id is None:
        return
    styles = [
        "Casual Street Style", "Home Kitchen", "Office Desk",
        "Gym / Fitness", "Café / Coffee Shop", "Luxury Interior",
        "Outdoor Nature", "Holiday / Beach", "Studio Flat Lay",
    ]
    style = st.selectbox("Scene style", styles, key="ls_style")
    product_desc = st.text_input("Product description",
                                  placeholder="e.g. Blue ceramic coffee mug",
                                  key="ls_prod_desc")
    custom = st.text_area("Custom prompt override (optional)", height=68, key="ls_custom")

    inputs = {
        "image_bytes":   cur,
        "style":         style,
        "product_desc":  product_desc,
        "custom_prompt": custom,
        "_provider_id":  provider_id,
    }
    _apply_button("ai_lifestyle", cur, "🌴 Generate Lifestyle", inputs=inputs,
                  user_email=user_email, is_ai=True)


_MODEL_ANGLES = ["Front", "Back", "¾ Left", "¾ Right", "Left Side", "Right Side"]


def _props_ai_model(cur: bytes, user_email: str) -> None:
    from psydox.batch.processor import RATIO_PRESETS
    provider_id = _render_provider_selector()
    if provider_id is None:
        return
    gender    = st.selectbox("Gender", ["Female", "Male", "Non-binary"], key="mod_gender")
    age_group = st.selectbox("Age group", ["18-25", "25-35", "35-45", "45+"], key="mod_age")
    ethnicity = st.selectbox("Ethnicity", [
        "South Asian / Indian", "East Asian", "African / Black",
        "Hispanic / Latino", "Caucasian / White", "Middle Eastern",
    ], key="mod_eth")
    style = st.selectbox("Style", [
        "Natural / Minimal", "Editorial Fashion", "Casual Lifestyle",
        "Athletic / Sporty", "Luxury / Premium",
    ], key="mod_style")
    product_desc = st.text_input("Product description", placeholder="e.g. Navy hoodie",
                                  key="mod_prod")

    st.markdown('<div class="psx-props-header">OUTPUT SIZE</div>', unsafe_allow_html=True)
    ratio_label = st.selectbox("Ratio / Size", list(RATIO_PRESETS.keys()), key="mod_ratio")
    ratio_dims  = RATIO_PRESETS[ratio_label]
    if ratio_dims is None:
        _rc1, _rc2 = st.columns(2)
        _rw = _rc1.number_input("Width px",  64, 4096, 1080, key="mod_ratio_w")
        _rh = _rc2.number_input("Height px", 64, 4096, 1350, key="mod_ratio_h")
        ratio_dims = (int(_rw), int(_rh))

    st.markdown('<div class="psx-props-header">ANGLES</div>', unsafe_allow_html=True)
    selected_angles = st.multiselect(
        "Select angles to generate",
        options=_MODEL_ANGLES,
        default=["Front"],
        key="mod_angles",
    )

    if not selected_angles:
        st.info("Select at least one angle.")
        _render_model_results()
        return

    n = len(selected_angles)
    if not st.button(
        f"Apply — 👤 Generate {n} Model Shot{'s' if n > 1 else ''}",
        use_container_width=True, type="primary", key="apply_ai_model",
    ):
        _render_model_results()
        return

    inputs = {
        "image_bytes":  cur,
        "gender":       gender,
        "age_group":    age_group,
        "ethnicity":    ethnicity,
        "style":        style,
        "product_desc": product_desc,
        "angles":       selected_angles,
        "_provider_id": provider_id,
        "_ratio_wh":    ratio_dims,
    }

    with st.spinner(f"Generating {n} model shot(s)…"):
        result = _execute_tool("ai_model", inputs, user_email)

    st.session_state["ai_model_last_result"] = result

    if result and result.get("success"):
        _charge_wallet_for_ai("ai_model", result)

    if result and result.get("success") and result.get("outputs"):
        meta      = result.get("metadata", {})
        generated = meta.get("generated", len(result["outputs"]))
        total     = meta.get("total", n)
        st.success(f"Generated {generated}/{total} model shot(s).")
        _push_history(result["outputs"][0]["bytes"],
                      f"AI Model — {selected_angles[0]}")
    elif result:
        for err in result.get("errors", ["Unknown error"]):
            st.error(err)

    _render_model_results()
    st.rerun()


def _render_model_results() -> None:
    """Display all model shots from the last generation run."""
    result = st.session_state.get("ai_model_last_result")
    if not result or not result.get("outputs"):
        return

    outputs = result["outputs"]
    st.markdown("---")
    st.markdown(
        f'<div class="psx-props-header">RESULTS — {len(outputs)} shot(s)</div>',
        unsafe_allow_html=True,
    )

    for i, out in enumerate(outputs):
        lbl   = out.get("label", f"Shot {i + 1}")
        angle = lbl.split("·")[-1].strip() if "·" in lbl else lbl
        with st.expander(f"👤 {angle}", expanded=(i == 0)):
            if out.get("bytes"):
                st.image(out["bytes"], use_container_width=True)
                safe = angle.lower().replace(" ", "_").replace("¾", "34").replace("/", "")
                st.download_button(
                    f"⬇ Download {angle}",
                    data=out["bytes"],
                    file_name=f"model_{safe}.jpg",
                    mime="image/jpeg",
                    key=f"dl_model_{i}",
                )
                if st.button("Set as current image", key=f"set_model_{i}",
                             use_container_width=True):
                    _push_history(out["bytes"], f"AI Model — {angle}")
                    st.rerun()
            else:
                st.caption("No image produced.")


def _props_ai_scene(cur: bytes, user_email: str) -> None:
    """AI Scene uses BackgroundFeature with an outdoor/studio prompt."""
    provider_id = _render_provider_selector()
    if provider_id is None:
        return
    scene_type = st.selectbox("Scene environment", [
        "Luxury Interior", "Modern Kitchen", "Rooftop Urban",
        "Forest / Nature", "Desert / Minimalist", "Café Setting",
        "Beach / Ocean", "Snow / Winter", "Night City",
    ], key="scene_type")
    mood = st.selectbox("Mood / Lighting", [
        "Natural Daylight", "Golden Hour", "Overcast Soft",
        "Dramatic Studio", "Neon Night",
    ], key="scene_mood")
    extra = st.text_input("Additional details", placeholder="brand, texture, props...",
                           key="scene_extra")

    prompt = f"{scene_type} background, {mood} lighting, product photography"
    if extra:
        prompt += f", {extra}"

    inputs = {
        "image_bytes":   cur,
        "bg_type":       "custom_ai",
        "ai_prompt":     prompt,
        "_provider_id":  provider_id,
    }
    _apply_button("ai_scene", cur, "🏠 Generate Scene", inputs=inputs,
                  user_email=user_email, is_ai=True)


def _props_ai_angles(cur: bytes, user_email: str) -> None:
    """Multi-angle product generation panel (owner only)."""
    from psydox.generation.contract import list_angles

    provider_id = _render_provider_selector()
    if provider_id is None:
        return

    st.markdown('<div class="psx-props-header">SELECT ANGLES</div>', unsafe_allow_html=True)

    all_angles = list_angles()

    # Initialise checkbox state (unchecked by default — user must actively choose)
    for a in all_angles:
        _k = f"angle_cb_{a.angle_id}"
        if _k not in st.session_state:
            st.session_state[_k] = False

    # Quick-select row
    _qa, _qc = st.columns(2)
    if _qa.button("☑ Select All", key="angles_sel_all", use_container_width=True):
        for a in all_angles:
            st.session_state[f"angle_cb_{a.angle_id}"] = True
        st.rerun()
    if _qc.button("☐ Clear All", key="angles_sel_clear", use_container_width=True):
        for a in all_angles:
            st.session_state[f"angle_cb_{a.angle_id}"] = False
        st.rerun()

    # Individual angle checkboxes in a 2-column grid
    _col_a, _col_b = st.columns(2)
    selected_ids: list[str] = []
    for i, angle in enumerate(all_angles):
        _col = _col_a if i % 2 == 0 else _col_b
        _checked = _col.checkbox(
            angle.display_name,
            key=f"angle_cb_{angle.angle_id}",
            help=angle.camera_description,
        )
        if _checked:
            selected_ids.append(angle.angle_id)

    # Budget summary
    if selected_ids:
        _budget = len(selected_ids) * 0.50
        st.caption(
            f"**{len(selected_ids)} angle(s) selected** · "
            f"max budget ₹{_budget:.2f} (₹0.50 each)"
        )
    else:
        st.caption("Tick the angles you want to generate above.")

    if not selected_ids:
        st.button(
            "🎯 Generate Angles",
            use_container_width=True, type="primary",
            key="apply_ai_angles", disabled=True,
        )
        _render_angle_results()
        return

    if not st.button(
        f"🎯 Generate {len(selected_ids)} Angle(s)",
        use_container_width=True, type="primary", key="apply_ai_angles",
    ):
        # Show previous results if they exist
        _render_angle_results()
        return

    with st.spinner(f"Generating {len(selected_ids)} product angle(s)…"):
        from psydox.studio.executor import execute_angle_generation
        result = execute_angle_generation(
            inputs={
                "image_bytes": cur,
                "angle_ids":   selected_ids,
                "provider_id": provider_id or "gemini",
            },
            user_email=user_email,
        )

    st.session_state["ai_angles_last_result"] = result

    if result.get("success"):
        _charge_wallet_for_ai("ai_angles", result)

    if result.get("success") and result.get("outputs"):
        meta = result.get("metadata", {})
        approved = meta.get("approved", 0)
        total    = meta.get("requested", len(selected_ids))
        cost     = meta.get("total_cost_inr", 0.0)
        cpa      = meta.get("cost_per_approved", 0.0)
        st.success(
            f"Generated {approved}/{total} angles approved. "
            f"Total cost: ₹{cost:.3f} | ₹{cpa:.3f}/approved angle"
        )
        # Push first approved image to main canvas
        first_approved = next(
            (o for o in result["outputs"] if o.get("outcome") == "APPROVED"), None
        )
        if first_approved:
            _push_history(first_approved["bytes"], f"AI Angles — {first_approved['label']}")
    elif result.get("errors"):
        for err in result["errors"]:
            st.error(err)
    else:
        st.warning("No angles generated. Check provider configuration.")

    _render_angle_results()
    st.rerun()


def _render_angle_results() -> None:
    """Display angle results from the last generation run."""
    result = st.session_state.get("ai_angles_last_result")
    if not result or not result.get("outputs"):
        return

    outputs = result["outputs"]
    approved = [o for o in outputs if o.get("outcome") == "APPROVED"]
    review   = [o for o in outputs if o.get("outcome") == "REVIEW"]
    failed   = [o for o in outputs if o.get("outcome") in ("HARD_FAIL", "FAILED", "BUDGET_CONFLICT")]

    st.markdown("---")
    st.markdown(
        f'<div class="psx-props-header">RESULTS'
        f' — {len(approved)}✅ {len(review)}👁 {len(failed)}❌'
        f' of {len(outputs)}</div>',
        unsafe_allow_html=True,
    )

    _OUTCOME_STYLE = {
        "APPROVED":        ("✅", "#22c55e"),
        "REVIEW":          ("👁️", "#f59e0b"),
        "HARD_FAIL":       ("❌", "#ef4444"),
        "FAILED":          ("❌", "#ef4444"),
        "BUDGET_CONFLICT": ("🚫", "#94a3b8"),
    }

    for out in outputs:
        outcome = out.get("outcome", "UNKNOWN")
        icon, _  = _OUTCOME_STYLE.get(outcome, ("?", "#888"))
        name  = out.get("display_name") or out.get("label", "").split("—")[0].strip()
        cost  = out.get("cost_inr", 0.0)
        qual  = out.get("quality_score", 0)
        fid   = out.get("fidelity_score", 0.0)

        with st.expander(f"{icon} {name} ({outcome})", expanded=(outcome == "APPROVED")):
            if out.get("bytes"):
                st.image(out["bytes"], use_container_width=True)
                st.caption(
                    f"Quality: {qual}/100  |  Fidelity: {fid:.0%}  |  Cost: ₹{cost:.3f}"
                )
                st.download_button(
                    f"⬇ Download {name}",
                    data=out["bytes"],
                    file_name=f"{out.get('angle_id', 'angle').lower()}_output.jpg",
                    mime="image/jpeg",
                    key=f"dl_angle_{out.get('angle_id', name)}",
                )
            else:
                if outcome == "APPROVED":
                    st.caption(f"No image bytes available. Status: {outcome}")
                else:
                    st.caption(f"No image produced. Status: {outcome}")


# ═════════════════════════════════════════════════════════════════════════════
#  JADU KA GHAR — Ideogram AI  (owner only)
# ═════════════════════════════════════════════════════════════════════════════

def _props_jadu_ka_ghar(cur: bytes, user_email: str) -> None:
    """
    Jadu Ka Ghar — Ideogram AI Studio panel.

    Requires IDEOGRAM_API_KEY in Railway environment variables.
    Modes: Remix · Replace BG · Remove BG · Generate · Describe
    """
    from jadu_ka_ghar.client import (
        STYLE_TYPES, STYLE_PRESETS, ASPECT_RATIOS,
        MAGIC_PROMPT_OPTIONS, RENDERING_SPEEDS, COLOR_PALETTES,
    )

    # ── API key status ────────────────────────────────────────────────────────
    import os as _os
    _key_set = bool(_os.environ.get("IDEOGRAM_API_KEY", "").strip())
    if not _key_set:
        st.warning(
            "**IDEOGRAM_API_KEY not set.**  \n"
            "Add it to Railway → Variables → `IDEOGRAM_API_KEY`.  \n"
            "Get a key at [ideogram.ai](https://ideogram.ai/manage-api)."
        )
        st.caption(
            "Jadu Ka Ghar uses Ideogram AI — a separate service from Google AI. "
            "It specialises in photorealistic style remix, background AI, and text-in-images."
        )

    st.markdown(
        '<div class="psx-owner-banner" style="background:linear-gradient(90deg,'
        'rgba(168,85,247,.15),rgba(236,72,153,.15));border-color:rgba(168,85,247,.4);">'
        "🪄 Powered by Ideogram AI — Jadu Ka Ghar</div>",
        unsafe_allow_html=True,
    )

    # ── Mode tabs ─────────────────────────────────────────────────────────────
    tab_remix, tab_replace, tab_remove, tab_gen, tab_describe = st.tabs([
        "✨ Remix",
        "🎨 Replace BG",
        "🪄 Remove BG",
        "🌟 Generate",
        "🔍 Describe",
    ])

    # ── Common speed selector (shown in each tab to keep UI compact) ──────────
    def _speed_select(key_sfx: str) -> str:
        return st.selectbox(
            "Speed", RENDERING_SPEEDS, index=0,
            help="TURBO = faster but may be lower quality; STANDARD = best quality",
            key=f"jkg_speed_{key_sfx}",
        )

    # ════════════════════════════════════════════════════════
    # TAB 1 — REMIX
    # ════════════════════════════════════════════════════════
    with tab_remix:
        st.caption(
            "Keep your product as visual reference and apply a new style, "
            "scene, or aesthetic via Ideogram remix."
        )
        prompt = st.text_area(
            "Style / scene prompt",
            placeholder=(
                "e.g. 'Luxury white marble studio, soft diffused lighting, "
                "high-fashion editorial look'"
            ),
            height=90,
            key="jkg_remix_prompt",
        )

        c1, c2 = st.columns(2)
        with c1:
            style_type = st.selectbox(
                "Style type", STYLE_TYPES,
                index=STYLE_TYPES.index("GENERAL"),
                key="jkg_remix_style_type",
            )
            aspect_ratio = st.selectbox(
                "Aspect ratio", ASPECT_RATIOS,
                index=ASPECT_RATIOS.index("AUTO"),
                key="jkg_remix_aspect",
            )
        with c2:
            style_preset = st.selectbox(
                "Style preset", STYLE_PRESETS,
                index=0,
                key="jkg_remix_style_preset",
            )
            magic_prompt = st.selectbox(
                "Magic Prompt",
                MAGIC_PROMPT_OPTIONS,
                index=0,
                help="AUTO = Ideogram's LLM enhances your prompt automatically",
                key="jkg_remix_magic",
            )

        image_weight = st.slider(
            "Image weight (product fidelity)",
            min_value=0, max_value=100, value=50,
            help="Higher = output stays closer to the input product image",
            key="jkg_remix_imgwt",
        )
        negative_prompt = st.text_input(
            "Negative prompt (optional)",
            placeholder="e.g. blurry, ugly, low quality, watermark",
            key="jkg_remix_neg",
        )
        rendering_speed = _speed_select("remix")
        color_palette = st.selectbox(
            "Color palette (optional)", COLOR_PALETTES,
            index=0, key="jkg_remix_palette",
        )

        if st.button(
            "✨ Remix with Ideogram",
            use_container_width=True, type="primary",
            key="apply_jkg_remix",
            disabled=not _key_set,
        ):
            if not prompt.strip():
                st.warning("Enter a style/scene prompt above.")
            else:
                inputs = {
                    "mode": "remix",
                    "image_bytes": cur,
                    "prompt": prompt,
                    "style_type": style_type,
                    "style_preset": style_preset,
                    "aspect_ratio": aspect_ratio,
                    "magic_prompt": magic_prompt,
                    "negative_prompt": negative_prompt,
                    "image_weight": image_weight,
                    "rendering_speed": rendering_speed,
                    "color_palette": color_palette,
                }
                with st.spinner("Remixing with Ideogram AI…"):
                    result = _execute_tool("jadu_ka_ghar", inputs, user_email)
                if result and result.get("success") and result.get("outputs"):
                    _push_history(result["outputs"][0]["bytes"], "Jadu — Remix")
                    st.rerun()
                elif result:
                    for err in result.get("errors", ["Unknown error"]):
                        st.error(err)

    # ════════════════════════════════════════════════════════
    # TAB 2 — REPLACE BACKGROUND
    # ════════════════════════════════════════════════════════
    with tab_replace:
        st.caption(
            "AI-powered background replacement — Ideogram preserves the product "
            "and regenerates everything else."
        )

        _BG_PRESETS = {
            "Custom prompt": "",
            "Pure white studio": "Pure white seamless studio background, clean minimal",
            "Luxury marble": "White Carrara marble surface with grey veining, luxury product photography",
            "Wood surface": "Natural warm-toned wood grain surface, organic artisan texture",
            "Concrete": "Raw textured concrete surface, industrial modern aesthetic",
            "Golden Hour outdoor": "Warm golden-hour sunlight, long soft shadows, outdoor lifestyle",
            "Tropical beach": "White-sand tropical beach with turquoise ocean, bright sunlight",
            "Moody dark studio": "Pure black studio background with dramatic low-key lighting",
            "Forest nature": "Lush green forest with dappled sunlight filtering through the canopy",
            "City rooftop": "Modern city rooftop terrace at sunset, skyline in background",
            "Cafe interior": "Cosy artisan café with exposed brick, warm lighting and coffee aesthetic",
            "Snow winter": "Clean snow-covered winter landscape, pristine white ground",
            "Neon cyberpunk": "Neon-lit cyberpunk city at night, vivid magenta and cyan glow",
        }

        bg_preset = st.selectbox(
            "Background preset", list(_BG_PRESETS.keys()),
            key="jkg_repbg_preset",
        )
        if bg_preset == "Custom prompt":
            bg_prompt = st.text_area(
                "Describe the background",
                height=80,
                placeholder="e.g. Luxury penthouse terrace with city skyline at night",
                key="jkg_repbg_custom",
            )
        else:
            bg_prompt = _BG_PRESETS[bg_preset]
            extra = st.text_input(
                "Additional details (optional)",
                placeholder="e.g. warm tones, shallow depth of field",
                key="jkg_repbg_extra",
            )
            if extra:
                bg_prompt = f"{bg_prompt}, {extra}"
            st.caption(f"Prompt: {bg_prompt}")

        c1b, c2b = st.columns(2)
        with c1b:
            magic_prompt_rb = st.selectbox(
                "Magic Prompt", MAGIC_PROMPT_OPTIONS,
                key="jkg_repbg_magic",
            )
        with c2b:
            style_preset_rb = st.selectbox(
                "Style preset", STYLE_PRESETS,
                index=0, key="jkg_repbg_style",
            )
        rendering_speed_rb = _speed_select("repbg")

        if st.button(
            "🎨 Replace Background",
            use_container_width=True, type="primary",
            key="apply_jkg_repbg",
            disabled=not _key_set,
        ):
            if not bg_prompt.strip():
                st.warning("Enter a background description.")
            else:
                inputs = {
                    "mode": "replace_bg",
                    "image_bytes": cur,
                    "prompt": bg_prompt,
                    "magic_prompt": magic_prompt_rb,
                    "style_preset": style_preset_rb,
                    "rendering_speed": rendering_speed_rb,
                }
                with st.spinner("Replacing background with Ideogram AI…"):
                    result = _execute_tool("jadu_ka_ghar", inputs, user_email)
                if result and result.get("success") and result.get("outputs"):
                    _push_history(result["outputs"][0]["bytes"], "Jadu — Replace BG")
                    st.rerun()
                elif result:
                    for err in result.get("errors", ["Unknown error"]):
                        st.error(err)

    # ════════════════════════════════════════════════════════
    # TAB 3 — REMOVE BACKGROUND
    # ════════════════════════════════════════════════════════
    with tab_remove:
        st.caption(
            "One-click AI background removal via Ideogram. "
            "Returns a PNG with transparent background — perfect for packshots."
        )
        st.info(
            "No parameters needed — Ideogram automatically detects and removes "
            "the background, preserving the product with clean edges."
        )

        if st.button(
            "🪄 Remove Background",
            use_container_width=True, type="primary",
            key="apply_jkg_rembg",
            disabled=not _key_set,
        ):
            inputs = {"mode": "remove_bg", "image_bytes": cur}
            with st.spinner("Removing background with Ideogram AI…"):
                result = _execute_tool("jadu_ka_ghar", inputs, user_email)
            if result and result.get("success") and result.get("outputs"):
                _push_history(result["outputs"][0]["bytes"], "Jadu — Remove BG")
                st.rerun()
            elif result:
                for err in result.get("errors", ["Unknown error"]):
                    st.error(err)

    # ════════════════════════════════════════════════════════
    # TAB 4 — GENERATE
    # ════════════════════════════════════════════════════════
    with tab_gen:
        st.caption(
            "Pure text-to-image generation — describe your product scene and "
            "Ideogram creates it from scratch. Use your uploaded image as reference only."
        )

        gen_prompt = st.text_area(
            "Generation prompt",
            placeholder=(
                "e.g. 'Nike Air Max 90 sneakers on a pure white studio background, "
                "product photography, ultra-high resolution'"
            ),
            height=100,
            key="jkg_gen_prompt",
        )
        gen_neg = st.text_input(
            "Negative prompt (optional)",
            placeholder="blurry, deformed, low quality, text, watermark",
            key="jkg_gen_neg",
        )

        c1g, c2g = st.columns(2)
        with c1g:
            gen_style_type = st.selectbox(
                "Style type", STYLE_TYPES,
                index=STYLE_TYPES.index("REALISTIC"),
                key="jkg_gen_style_type",
            )
            gen_aspect = st.selectbox(
                "Aspect ratio", ASPECT_RATIOS,
                index=ASPECT_RATIOS.index("1x1"),
                key="jkg_gen_aspect",
            )
        with c2g:
            gen_preset = st.selectbox(
                "Style preset", STYLE_PRESETS,
                index=STYLE_PRESETS.index("PRODUCT_PHOTOGRAPHY"),
                key="jkg_gen_preset",
            )
            gen_magic = st.selectbox(
                "Magic Prompt", MAGIC_PROMPT_OPTIONS,
                index=0, key="jkg_gen_magic",
            )

        gen_speed    = _speed_select("gen")
        gen_palette  = st.selectbox(
            "Color palette (optional)", COLOR_PALETTES,
            index=0, key="jkg_gen_palette",
        )

        if st.button(
            "🌟 Generate Image",
            use_container_width=True, type="primary",
            key="apply_jkg_gen",
            disabled=not _key_set,
        ):
            if not gen_prompt.strip():
                st.warning("Enter a generation prompt above.")
            else:
                inputs = {
                    "mode": "generate",
                    "prompt": gen_prompt,
                    "negative_prompt": gen_neg,
                    "style_type": gen_style_type,
                    "style_preset": gen_preset,
                    "aspect_ratio": gen_aspect,
                    "magic_prompt": gen_magic,
                    "rendering_speed": gen_speed,
                    "color_palette": gen_palette,
                }
                with st.spinner("Generating with Ideogram AI…"):
                    result = _execute_tool("jadu_ka_ghar", inputs, user_email)
                if result and result.get("success") and result.get("outputs"):
                    _push_history(result["outputs"][0]["bytes"], "Jadu — Generate")
                    st.rerun()
                elif result:
                    for err in result.get("errors", ["Unknown error"]):
                        st.error(err)

    # ════════════════════════════════════════════════════════
    # TAB 5 — DESCRIBE
    # ════════════════════════════════════════════════════════
    with tab_describe:
        st.caption(
            "Reverse-engineer your product image into a reusable text prompt. "
            "Copy the result into Remix or Generate for consistent re-generation."
        )

        if st.button(
            "🔍 Describe This Image",
            use_container_width=True, type="primary",
            key="apply_jkg_describe",
            disabled=not _key_set,
        ):
            inputs = {"mode": "describe", "image_bytes": cur}
            with st.spinner("Analysing image with Ideogram AI…"):
                result = _execute_tool("jadu_ka_ghar", inputs, user_email)
            if result and result.get("success"):
                desc = result.get("metadata", {}).get("description", "")
                if desc:
                    st.session_state["jkg_last_description"] = desc
                else:
                    st.warning("Ideogram returned an empty description.")
            elif result:
                for err in result.get("errors", ["Unknown error"]):
                    st.error(err)

        desc = st.session_state.get("jkg_last_description", "")
        if desc:
            st.markdown("**Description:**")
            st.code(desc, language=None)
            st.caption("Copy this prompt into Remix or Generate tab for consistent re-generation.")


# ── Generic apply button ──────────────────────────────────────────────────────

def _charge_wallet_for_ai(tool_id: str, result: dict) -> None:
    """Deduct cost from wallet after a successful AI generation (non-blocking)."""
    try:
        _role = st.session_state.get("user_role", "viewer")
        _uid  = st.session_state.get("user_id", "")
        if not _uid:
            return
        from psydox.billing.service import get_billing_service
        bsvc = get_billing_service()
        if not bsvc.should_charge(_role):
            return
        cost_usd = result.get("metadata", {}).get("cost_usd", 0.0)
        charged = bsvc.charge_for_generation(
            user_id=_uid,
            tool_id=tool_id,
            cost_usd=cost_usd or 0.0,
            description=f"AI generation: {tool_id}",
        )
        if charged:
            st.toast(f"💳 ₹{charged/100:.2f} deducted from wallet")
    except Exception as _be:
        _log.warning("Wallet deduction failed (non-fatal): %s", _be)


def _apply_button(
    tool_id: str,
    cur: bytes,
    label: str,
    inputs: dict,
    user_email: str = "",
    is_ai: bool = False,
    multi_output: bool = False,
) -> None:
    if st.button(f"{'🤖 ' if is_ai else ''}Apply — {label.split('—')[0].strip() if '—' in label else label}",
                 use_container_width=True, type="primary", key=f"apply_{tool_id}"):
        with st.spinner(f"{'Generating...' if is_ai else 'Processing...'}"):
            result = _execute_tool(tool_id, inputs, user_email)

        if result and result.get("success"):
            if is_ai:
                _charge_wallet_for_ai(tool_id, result)

        if result and result.get("success") and result.get("outputs"):
            if multi_output and len(result["outputs"]) > 1:
                # Marketplace: show a zip download
                import zipfile, io as _io
                buf = _io.BytesIO()
                with zipfile.ZipFile(buf, "w") as zf:
                    for out in result["outputs"]:
                        zf.writestr(f"{out.get('label', tool_id)}.jpg", out["bytes"])
                buf.seek(0)
                st.download_button(
                    "⬇ Download ZIP",
                    data=buf.getvalue(),
                    file_name=f"{tool_id}_pack.zip",
                    mime="application/zip",
                    use_container_width=True,
                    key=f"dl_{tool_id}_zip",
                )
                # Push first output to history for preview
                _push_history(result["outputs"][0]["bytes"], label)
            else:
                out_bytes = result["outputs"][0]["bytes"]
                _push_history(out_bytes, label)
            st.rerun()
        elif result:
            for err in result.get("errors", ["Unknown error"]):
                st.error(err)


# ── Tool executor — delegates to psydox.studio.executor ──────────────────────

def _execute_tool(tool_id: str, inputs: dict, user_email: str) -> dict | None:
    """Thin UI wrapper around the stateless executor (no streamlit dependency)."""
    return execute_tool(tool_id, inputs, user_email)
