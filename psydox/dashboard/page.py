"""Psydox main dashboard renderer."""
import streamlit as st

from psydox.core.registry import get_registry
from psydox.jobs.manager import get_job_manager
from psydox.dashboard.theme import get_theme_manager
from psydox.dashboard.widgets import render_stats_row, render_recent_jobs, render_feature_grid


def render_dashboard(user_email: str = "", on_feature_select=None) -> None:
    """Render the full Gen-Z Psydox dashboard."""
    tm = get_theme_manager()
    tm.inject_css()

    # ── Sidebar: theme picker ──────────────────────────────────────────────────
    with st.sidebar:
        st.markdown("### 🎨 Theme")
        themes = tm.all_themes()
        names  = [t.name for t in themes]
        keys   = [t.name.lower().replace(" ", "_") for t in themes]
        cur_key = st.session_state.get("psydox_theme", "midnight")
        try:
            cur_idx = keys.index(cur_key)
        except ValueError:
            cur_idx = 0
        picked = st.radio("", names, index=cur_idx, key="theme_picker", label_visibility="collapsed")
        if picked:
            tm.set(picked.lower().replace(" ", "_"))

    # ── Header ─────────────────────────────────────────────────────────────────
    st.markdown(
        '<h1 style="font-size:2.2rem;font-weight:800;background:var(--gradient);'
        '-webkit-background-clip:text;-webkit-text-fill-color:transparent;'
        'background-clip:text;margin-bottom:4px;">⚡ Psydox Studio</h1>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<p style="color:var(--text-secondary);margin-top:0;font-size:0.95rem;">'
        'AI-powered product image platform</p>',
        unsafe_allow_html=True,
    )
    st.divider()

    # ── Stats row ──────────────────────────────────────────────────────────────
    jm    = get_job_manager()
    stats = jm.stats(user_email=user_email)
    render_stats_row(stats)
    st.markdown("<br>", unsafe_allow_html=True)

    # ── Features grid ─────────────────────────────────────────────────────────
    st.markdown("### Features")
    registry = get_registry()
    features = registry.all()
    render_feature_grid(features, on_select=on_feature_select)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Recent jobs ────────────────────────────────────────────────────────────
    st.markdown("### Recent Activity")
    recent = jm.recent(user_email=user_email, n=10)

    def _handle_download(job, out):
        fname = f"{job.feature_id}_{job.id}.jpg"
        st.download_button(
            label=f"⬇ Download {out.get('label','')}",
            data=out["bytes"],
            file_name=fname,
            mime=out.get("mime", "image/jpeg"),
            key=f"dl_btn_{job.id}_{fname}",
        )

    render_recent_jobs(recent, on_download=_handle_download)
