"""
Psydox Dashboard Widgets

Independent, registerable UI components.  Each widget is a function.
Widgets are self-contained — adding a new widget doesn't require editing any
other widget or the dashboard page.

Available widgets:
  render_hero              — greeting + primary CTAs
  render_stats_row         — 4 key metrics
  render_quick_create      — feature grid (auto-populated from registry)
  render_recent_jobs       — job history with download
  render_recent_projects   — project cards
  render_ai_usage_widget   — cost / generation stats

Widget registry:
  WIDGET_REGISTRY maps widget_id → (render_fn, label, default_visible)
  New widgets register by adding an entry — dashboard page discovers them.
"""
from __future__ import annotations

import datetime
import streamlit as st

from psydox.jobs.manager import Job, JobStatus


# ── Hero ──────────────────────────────────────────────────────────────────────

def render_hero(user_name: str = "", on_classic=None, on_ai_studio=None) -> None:
    hour = datetime.datetime.now().hour
    if hour < 12:
        greeting = "Good morning"
    elif hour < 17:
        greeting = "Good afternoon"
    else:
        greeting = "Good evening"

    name_part = f", {user_name.split()[0]}" if user_name else ""

    st.markdown(
        f'<h2 style="font-size:2rem;font-weight:800;color:var(--text-primary);margin-bottom:4px;">'
        f'{greeting}{name_part} 👋</h2>'
        f'<p style="color:var(--text-secondary);font-size:1rem;margin-bottom:24px;">'
        f'What are we creating today?</p>',
        unsafe_allow_html=True,
    )

    cols = [1, 4] if not on_ai_studio else [1, 1, 4]
    c1, *rest = st.columns(cols)
    with c1:
        if st.button("⚡ CLASSIC", use_container_width=True, help="Fast catalog processing"):
            if on_classic:
                on_classic()
    if on_ai_studio:
        with rest[0]:
            if st.button("✨ AI STUDIO", use_container_width=True, help="Create premium AI product content"):
                on_ai_studio()


# ── Stats ─────────────────────────────────────────────────────────────────────

def render_stats_row(stats: dict, ai_stats: dict | None = None) -> None:
    cols = st.columns(4)
    with cols[0]: st.metric("Total Jobs",   stats.get("total",     0))
    with cols[1]: st.metric("✅ Completed", stats.get("completed", 0))
    with cols[2]: st.metric("⚙️ Active",    stats.get("active",    0))
    with cols[3]: st.metric("❌ Failed",    stats.get("failed",    0))


# ── Quick Create ──────────────────────────────────────────────────────────────

def render_quick_create(on_select=None, pinned_ids: list | None = None,
                         cols: int = 4, show_ai: bool = True) -> None:
    """Auto-populated from feature registry.  Pinned features appear first.
    When show_ai=False, AI-requiring features are hidden entirely."""
    from psydox.core.registry import get_registry
    registry  = get_registry()
    all_feats = registry.all()

    # Filter AI features for non-owners
    if not show_ai:
        all_feats = [f for f in all_feats if not f.manifest.requires_ai]

    if pinned_ids:
        pinned  = [f for f in all_feats if f.manifest.id in pinned_ids]
        rest    = [f for f in all_feats if f.manifest.id not in pinned_ids]
        features = pinned + rest
    else:
        features = all_feats

    if not features:
        st.info("No features registered yet.")
        return

    st.markdown("### ⚡ Quick Create")
    for row_start in range(0, len(features), cols):
        row_feats = features[row_start:row_start + cols]
        columns   = st.columns(cols)
        for col, feat in zip(columns, row_feats):
            m = feat.manifest
            with col:
                ai_badge = '<span class="psx-badge psx-ai">AI</span>' if m.requires_ai else ""
                st.markdown(f"""
<div class="psx-feat">
  <div class="psx-feat-icon">{m.icon}</div>
  <div class="psx-feat-name">{m.name} {ai_badge}</div>
  <div class="psx-feat-desc">{m.description[:55]}{"…" if len(m.description) > 55 else ""}</div>
</div>""", unsafe_allow_html=True)
                if st.button(f"Open", key=f"qc_{m.id}", use_container_width=True):
                    if on_select:
                        on_select(m.id)


# ── Recent jobs ───────────────────────────────────────────────────────────────

def render_recent_jobs(jobs: list[Job], on_download=None) -> None:
    st.markdown("### 🕐 Recent Activity")
    if not jobs:
        st.markdown(
            '<div style="text-align:center;padding:32px;opacity:.5;">'
            'No activity yet — run a feature to see results here</div>',
            unsafe_allow_html=True,
        )
        return

    for job in jobs:
        icon = job.status_icon()
        dur  = job.duration_s()
        dur_txt = f"  ·  {dur}s" if dur else ""

        label_color = {
            JobStatus.COMPLETED: "var(--success)",
            JobStatus.FAILED:    "var(--danger)",
            JobStatus.PROCESSING: "var(--accent-primary)",
        }.get(job.status, "var(--text-secondary)")

        with st.expander(f"{icon} **{job.label}** `{job.id}`{dur_txt}", expanded=False):
            c1, c2 = st.columns([3, 1])
            with c1:
                st.markdown(
                    f'Feature: <code>{job.feature_id}</code> · '
                    f'<span style="color:{label_color}">{job.status.value.upper()}</span>',
                    unsafe_allow_html=True,
                )
                for e in job.errors:
                    st.error(e, icon="⚠️")
                if job.metadata.get("quality_score") is not None:
                    qs = job.metadata["quality_score"]
                    qv = job.metadata.get("quality_verdict", "")
                    st.caption(f"Quality: {qs}/100 — {qv}")
            with c2:
                if job.outputs:
                    for i, out in enumerate(job.outputs):
                        lbl = out.get("label", f"Output {i+1}")
                        if st.button(f"⬇ {lbl}", key=f"dl_{job.id}_{i}"):
                            if on_download:
                                on_download(job, out)


# ── Recent projects (placeholder — requires project system) ───────────────────

def render_recent_projects(projects: list[dict], on_open=None) -> None:
    st.markdown("### 📁 Projects")
    if not projects:
        st.markdown(
            '<div style="text-align:center;padding:32px;opacity:.5;">'
            'No projects yet — create one to get started</div>',
            unsafe_allow_html=True,
        )
        return
    cols = st.columns(min(len(projects), 3))
    for col, proj in zip(cols, projects):
        with col:
            st.markdown(f"""
<div class="psx-card">
  <div style="font-weight:700;font-size:1rem;color:var(--text-primary);">{proj.get("name","Project")}</div>
  <div style="color:var(--text-secondary);font-size:0.8rem;margin-top:4px;">
    {proj.get("product_count",0)} products · {proj.get("status","active")}
  </div>
</div>""", unsafe_allow_html=True)
            if st.button("Open", key=f"proj_{proj.get('id','x')}", use_container_width=True):
                if on_open:
                    on_open(proj.get("id"))


# ── AI usage widget ───────────────────────────────────────────────────────────

def render_ai_usage(user_email: str = "") -> None:
    """Show AI usage statistics from the database."""
    st.markdown("### 💰 AI Usage")
    try:
        from psydox.storage.database import get_db
        db = get_db()
        if user_email:
            rows = db.execute(
                "SELECT SUM(cost_usd), COUNT(*) FROM ai_usage WHERE 1=1", ()
            ).fetchone()
        else:
            rows = db.execute("SELECT SUM(cost_usd), COUNT(*) FROM ai_usage").fetchone()

        total_cost  = rows[0] or 0.0
        total_gens  = rows[1] or 0
        c1, c2 = st.columns(2)
        c1.metric("AI Generations", total_gens)
        c2.metric("Estimated Cost", f"${total_cost:.2f}")
    except Exception:
        st.caption("AI usage tracking unavailable")


# ── Observability widgets (Phase J) ──────────────────────────────────────────

def render_batch_metrics(days: int = 7) -> None:
    """Batch throughput and failure stats from job_items table."""
    st.markdown("### ⚙️ Batch Metrics")
    try:
        from psydox.admin.analytics import AnalyticsService
        data = AnalyticsService().batch_summary(days=days)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Items ({}d)".format(days), data["total_items"])
        c2.metric("✅ Completed",  data["completed"])
        c3.metric("❌ Failed",     data["failed"])
        c4.metric("Pass rate",     f"{data['pass_rate']*100:.0f}%")

        if data["top_errors"]:
            with st.expander("Top failure reasons"):
                for e in data["top_errors"][:5]:
                    st.caption(f"×{e['count']}  {e['error'][:120]}")
    except Exception:
        st.caption("Batch metrics unavailable")


def render_quality_overview(days: int = 7) -> None:
    """Quality score distribution from quality_results table."""
    st.markdown("### 🎯 Quality Overview")
    try:
        from psydox.admin.analytics import AnalyticsService
        data = AnalyticsService().quality_summary(days=days)
        if data["total"] == 0:
            st.caption("No quality data in the last {} days.".format(days))
            return
        c1, c2, c3 = st.columns(3)
        c1.metric("Checks ({}d)".format(days), data["total"])
        c2.metric("Avg score",  f"{data['avg_score']:.0f}/100")
        c3.metric("Pass rate",  f"{data['pass_rate']*100:.0f}%")

        by_v = data.get("by_verdict", {})
        approved   = by_v.get("APPROVED",  0)
        review     = by_v.get("REVIEW",    0)
        needs_fix  = by_v.get("NEEDS_FIX", 0)
        st.caption(
            f"✅ Approved: {approved}  |  "
            f"👁️ Review: {review}  |  "
            f"🔧 Needs Fix: {needs_fix}"
        )
    except Exception:
        st.caption("Quality overview unavailable")


def render_ai_cost_breakdown(days: int = 30) -> None:
    """AI usage cost broken down by feature and provider."""
    st.markdown("### 💰 AI Usage & Cost")
    try:
        from psydox.admin.analytics import AnalyticsService
        data = AnalyticsService().ai_usage_summary(days=days)
        c1, c2, c3 = st.columns(3)
        c1.metric("Requests ({}d)".format(days), data["total_requests"])
        c2.metric("Total cost",   f"${data['total_cost']:.3f}")
        c3.metric("Avg latency",  f"{data['avg_latency_ms']}ms")

        if data["by_feature"]:
            with st.expander("By feature"):
                for row in data["by_feature"][:8]:
                    st.caption(f"{row['key']}: {row['requests']} requests  |  ${row['cost_usd']:.3f}")
        if data["by_provider"]:
            with st.expander("By provider"):
                for row in data["by_provider"][:5]:
                    st.caption(f"{row['key']}: {row['requests']} requests  |  ${row['cost_usd']:.3f}")
    except Exception:
        st.caption("AI cost data unavailable")


# ── Widget registry ───────────────────────────────────────────────────────────
# (widget_id, render_fn, label, default_visible)
# New widgets: add an entry here — dashboard discovers them automatically.

WIDGET_REGISTRY: list[tuple[str, callable, str, bool]] = [
    ("hero",             render_hero,             "Welcome",       True),
    ("metrics",          render_stats_row,         "Metrics",       True),
    ("quick_create",     render_quick_create,      "Quick Create",  True),
    ("recent_jobs",      render_recent_jobs,        "Recent Jobs",   True),
    ("recent_projects",  render_recent_projects,    "Projects",      True),
    ("ai_usage",         render_ai_usage,           "AI Usage",      False),
    ("batch_metrics",    render_batch_metrics,      "Batch Metrics", False),
    ("quality_overview", render_quality_overview,   "Quality",       False),
    ("ai_cost",          render_ai_cost_breakdown,  "AI Cost",       False),
]


def metric_widget(label: str, value, delta=None, help: str = "") -> None:
    st.metric(label=label, value=str(value), delta=delta, help=help)
