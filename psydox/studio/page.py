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

from psydox.access import can_access_ai_studio, require_owner
from psydox.studio.executor import execute_tool, exec_enhance


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
    ("packshot",    "📦", "Packshot",    False),
    ("marketplace", "🛒", "Marketplace", False),
]

_AI_TOOLS = [
    ("ai_background", "🤖", "AI Background", True),
    ("ai_lifestyle",  "🌴", "AI Lifestyle",  True),
    ("ai_model",      "👤", "AI Model",      True),
    ("ai_scene",      "🏠", "AI Scene",      True),
    ("ai_angles",     "🎯", "AI Angles",     True),
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

    is_owner_user = can_access_ai_studio(user_email)

    if start_tool and st.session_state.studio_tool != start_tool:
        st.session_state.studio_tool = start_tool

    # ── Top bar ───────────────────────────────────────────────────────────────
    tb1, tb2, tb3, tb4, tb5, tb6 = st.columns([1.8, 2.5, 1.2, 0.8, 0.8, 1.2])
    with tb1:
        st.markdown(
            '<span style="font-size:1.3rem;font-weight:800;color:#6366f1;">⚡ PSYDOX</span>'
            f'<span style="font-size:0.75rem;color:rgba(255,255,255,.4);margin-left:6px;">'
            f'{"AI Studio" if is_owner_user else "Classic Studio"}</span>',
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
            st.download_button(
                "⬇ Export", data=cur,
                file_name=f"{st.session_state.studio_project_name.replace(' ', '_')}.jpg",
                mime="image/jpeg", use_container_width=True, key="stu_export",
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
        _do_upload(uploaded)
        st.rerun()


def _do_upload(uploaded_file) -> None:
    from psydox.security.upload import validate_upload
    raw = uploaded_file.getvalue()
    result = validate_upload(raw, uploaded_file.name)
    if not result.valid:
        for e in result.errors:
            st.error(e)
        return
    for w in result.warnings:
        st.warning(w)
    # Reset history with the uploaded image as the first state
    st.session_state.studio_history      = [{"bytes": raw, "label": "Original"}]
    st.session_state.studio_history_idx  = 0
    st.session_state.studio_project_name = uploaded_file.name.rsplit(".", 1)[0].replace("_", " ").title()


# ── Toolbar ───────────────────────────────────────────────────────────────────

def _render_toolbar(user_email: str, is_owner_user: bool) -> None:
    st.markdown('<div class="psx-props-header">TOOLS</div>', unsafe_allow_html=True)

    # Upload a different image
    new_upload = st.file_uploader(
        "Change image", type=["jpg", "jpeg", "png", "webp"],
        key="studio_change_img", label_visibility="collapsed",
    )
    if new_upload:
        _do_upload(new_upload)
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
        from psydox.quality.engine import AIQualityEngine
        qe = AIQualityEngine()
        qs = qe.score(cur)
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

    # Security gate — never execute AI tools for non-owners
    if requires_ai and not is_owner_user:
        st.error("AI tools are available to the owner account only.")
        return

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
        "packshot":      _props_packshot,
        "marketplace":   _props_marketplace,
        "ai_background": _props_ai_background,
        "ai_lifestyle":  _props_ai_lifestyle,
        "ai_model":      _props_ai_model,
        "ai_scene":      _props_ai_scene,
        "ai_angles":     _props_ai_angles,
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
    img = Image.open(io.BytesIO(cur))
    ow, oh = img.size

    st.caption(f"Original: {ow} × {oh} px")
    lock = st.checkbox("Lock aspect ratio", value=True, key="resize_lock")

    tw = st.number_input("Width (px)",  64, 8000, ow, step=10, key="resize_w")
    if lock:
        th = int(tw * oh / ow) if ow else oh
        st.caption(f"Height → {th} px (locked)")
    else:
        th = st.number_input("Height (px)", 64, 8000, oh, step=10, key="resize_h")

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
    img = Image.open(io.BytesIO(cur))
    ow, oh = img.size
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
        if result:
            changed = []
            if brightness != 1.0: changed.append(f"brightness {brightness:.2f}")
            if contrast   != 1.0: changed.append(f"contrast {contrast:.2f}")
            if saturation != 1.0: changed.append(f"saturation {saturation:.2f}")
            if sharpness  != 1.0: changed.append(f"sharpness {sharpness:.2f}")
            label = "Enhance: " + (", ".join(changed) if changed else "no change")
            _push_history(result, label)
            st.rerun()


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
    styles = [
        "Casual Street Style", "Home Kitchen", "Office Desk",
        "Gym / Fitness", "Café / Coffee Shop", "Luxury Interior",
        "Outdoor Nature", "Holiday / Beach", "Studio Flat Lay",
    ]
    style = st.selectbox("Scene style", styles, key="ls_style")
    product_desc = st.text_input("Product description",
                                  placeholder="e.g. Blue ceramic coffee mug",
                                  key="ls_prod_desc")
    custom = st.text_area("Custom prompt override (optional)", height=60, key="ls_custom")

    inputs = {
        "image_bytes":   cur,
        "style":         style,
        "product_desc":  product_desc,
        "custom_prompt": custom,
        "_provider_id":  provider_id,
    }
    _apply_button("ai_lifestyle", cur, "🌴 Generate Lifestyle", inputs=inputs,
                  user_email=user_email, is_ai=True)


def _props_ai_model(cur: bytes, user_email: str) -> None:
    provider_id = _render_provider_selector()
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

    inputs = {
        "image_bytes":  cur,
        "gender":       gender,
        "age_group":    age_group,
        "ethnicity":    ethnicity,
        "style":        style,
        "product_desc": product_desc,
        "_provider_id": provider_id,
    }
    _apply_button("ai_model", cur, "👤 Generate Model Shot", inputs=inputs,
                  user_email=user_email, is_ai=True)


def _props_ai_scene(cur: bytes, user_email: str) -> None:
    """AI Scene uses BackgroundFeature with an outdoor/studio prompt."""
    provider_id = _render_provider_selector()
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

    st.markdown('<div class="psx-props-header">SELECT ANGLES</div>', unsafe_allow_html=True)

    all_angles = list_angles()
    angle_labels = {a.angle_id: f"{a.display_name}" for a in all_angles}

    # Default: all 8 angles selected
    default_selected = [a.angle_id for a in all_angles]
    selected_ids = st.multiselect(
        "Angles to generate",
        options=list(angle_labels.keys()),
        default=default_selected,
        format_func=lambda x: angle_labels.get(x, x),
        key="ai_angles_sel",
    )

    if selected_ids:
        budget = len(selected_ids) * 0.50
        st.caption(f"Estimated max budget: ₹{budget:.2f} ({len(selected_ids)} angles × ₹0.50)")

    if not selected_ids:
        st.warning("Select at least one angle.")
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

    st.markdown("---")
    st.markdown('<div class="psx-props-header">ANGLE RESULTS</div>', unsafe_allow_html=True)

    _OUTCOME_STYLE = {
        "APPROVED":       ("✅", "#22c55e"),
        "REVIEW":         ("👁️", "#f59e0b"),
        "HARD_FAIL":      ("❌", "#ef4444"),
        "FAILED":         ("❌", "#ef4444"),
        "BUDGET_CONFLICT": ("🚫", "#94a3b8"),
    }

    for out in result["outputs"]:
        outcome = out.get("outcome", "UNKNOWN")
        icon, color = _OUTCOME_STYLE.get(outcome, ("?", "#888"))
        label = out.get("label", "")
        cost  = out.get("cost_inr", 0.0)
        qual  = out.get("quality_score", 0)
        fid   = out.get("fidelity_score", 0.0)

        with st.expander(f"{icon} {label}", expanded=(outcome == "APPROVED")):
            if out.get("bytes"):
                st.image(out["bytes"], use_container_width=True)
                st.caption(
                    f"Quality: {qual}/100  |  Fidelity: {fid:.0%}  |  Cost: ₹{cost:.3f}"
                )
                st.download_button(
                    f"⬇ Download {label.split('—')[0].strip()}",
                    data=out["bytes"],
                    file_name=f"{out.get('angle_id', 'angle').lower()}_output.jpg",
                    mime="image/jpeg",
                    key=f"dl_angle_{out.get('angle_id', label)}",
                )
                if outcome == "APPROVED":
                    if st.button(
                        "Set as current image",
                        key=f"set_current_{out.get('angle_id', label)}",
                    ):
                        _push_history(out["bytes"], label)
                        st.rerun()
            else:
                st.caption(f"No image produced. Status: {outcome}")


# ── Generic apply button ──────────────────────────────────────────────────────

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
