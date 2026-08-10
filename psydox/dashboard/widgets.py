"""Psydox dashboard widgets — composable UI blocks."""
import streamlit as st

from psydox.jobs.manager import Job, JobStatus


def render_metric_widget(label: str, value, delta=None, help: str = "") -> None:
    st.metric(label=label, value=str(value), delta=delta, help=help)


def render_stats_row(stats: dict) -> None:
    c1, c2, c3, c4 = st.columns(4)
    with c1: render_metric_widget("Total Jobs",   stats.get("total", 0))
    with c2: render_metric_widget("Completed",    stats.get("completed", 0))
    with c3: render_metric_widget("Active",       stats.get("active", 0))
    with c4: render_metric_widget("Failed",       stats.get("failed", 0))


def render_recent_jobs(jobs: list[Job], on_download=None) -> None:
    if not jobs:
        st.markdown(
            '<div style="text-align:center;padding:32px;opacity:.5;">No jobs yet — run a feature to get started</div>',
            unsafe_allow_html=True,
        )
        return

    for job in jobs:
        icon = job.status_icon()
        dur  = job.duration_s()
        dur_txt = f"· {dur}s" if dur else ""

        with st.expander(f"{icon} **{job.label}** `{job.id}` {dur_txt}", expanded=False):
            col1, col2 = st.columns([2, 1])
            with col1:
                st.caption(f"Feature: `{job.feature_id}` · Status: `{job.status.value}`")
                if job.errors:
                    for e in job.errors:
                        st.error(e, icon="⚠️")
            with col2:
                if job.outputs and on_download:
                    for i, out in enumerate(job.outputs):
                        lbl = out.get("label", f"Output {i+1}")
                        btn_key = f"dl_{job.id}_{i}"
                        if st.button(f"⬇ {lbl}", key=btn_key):
                            on_download(job, out)


def render_feature_grid(features: list, on_select=None, cols: int = 3) -> None:
    """Render enabled features as a clickable grid."""
    if not features:
        st.info("No features available.")
        return

    for row_start in range(0, len(features), cols):
        row_features = features[row_start:row_start + cols]
        columns = st.columns(cols)
        for col, feat in zip(columns, row_features):
            m = feat.manifest
            with col:
                ai_badge = '<span class="psydox-badge psydox-badge-ai">AI</span>' if m.requires_ai else ""
                html = f"""
<div class="psydox-feature-btn" onclick="">
  <div class="psydox-feature-icon">{m.icon}</div>
  <div class="psydox-feature-name">{m.name} {ai_badge}</div>
  <div class="psydox-feature-desc">{m.description[:60]}{"…" if len(m.description)>60 else ""}</div>
</div>"""
                st.markdown(html, unsafe_allow_html=True)
                if on_select and st.button(f"Open {m.name}", key=f"feat_{m.id}", use_container_width=True):
                    on_select(m.id)
