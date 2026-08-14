"""Psydox Gen-Z Dashboard — main page renderer."""
from __future__ import annotations

import streamlit as st

from psydox.access import can_access_ai_studio
from psydox.dashboard.theme import get_theme_manager
from psydox.dashboard.preferences import get_preferences
from psydox.dashboard.widgets import (
    render_hero, render_stats_row, render_quick_create,
    render_recent_jobs, render_recent_projects, render_ai_usage,
    WIDGET_REGISTRY,
)
from psydox.jobs.manager import get_job_manager


def render_dashboard(
    user_email:       str = "",
    user_name:        str = "",
    on_feature_select = None,
    on_classic:       callable | None = None,
    on_ai_studio:     callable | None = None,
    on_new_project:   callable | None = None,
    on_batch:         callable | None = None,
) -> None:
    """Full Gen-Z dashboard."""
    is_owner = can_access_ai_studio(user_email)
    prefs = get_preferences(user_email)
    tm    = get_theme_manager()
    tm.inject_css(accent_override=prefs.get("accent", ""))

    # ── Sidebar ────────────────────────────────────────────────────────────────
    with st.sidebar:
        st.markdown("---")
        st.markdown("**🎨 Theme**")
        themes   = tm.all_themes()
        cur_key  = prefs.theme()
        cur_idx  = next((i for i, t in enumerate(themes) if t.key == cur_key), 0)
        picked   = st.radio(
            "", [t.name for t in themes],
            index=cur_idx, key="sb_theme", label_visibility="collapsed",
        )
        if picked:
            new_key = picked.lower().replace(" ", "_")
            if new_key != cur_key:
                prefs.set("theme", new_key)
                prefs.save()
                tm.set(new_key)
                st.rerun()

        st.markdown("**📐 Layout**")
        layout = st.radio(
            "", ["Comfortable", "Compact"],
            index=0 if prefs.layout() == "comfortable" else 1,
            key="sb_layout", label_visibility="collapsed",
        )
        if layout:
            prefs.set("layout", layout.lower())

        st.markdown("---")
        st.markdown(
            f'<div style="color:var(--text-secondary);font-size:0.85rem;padding-bottom:8px;">'
            f'👤 {user_name or user_email}</div>',
            unsafe_allow_html=True,
        )
        if st.button("⚡ Classic Studio", use_container_width=True, key="sb_classic"):
            if on_classic:
                on_classic()
        if is_owner:
            if st.button("✨ AI Studio", use_container_width=True, key="sb_ai_studio"):
                if on_ai_studio:
                    on_ai_studio()
        if on_batch and st.button("📊 Batch Processing", use_container_width=True, key="sb_batch"):
            on_batch()

        # Admin: download registered users as Excel
        if is_owner:
            st.markdown("---")
            st.markdown("**👥 Users**")
            try:
                from psydox.auth.service import get_all_users_excel
                excel_bytes = get_all_users_excel()
                st.download_button(
                    "⬇ Download Users Excel",
                    data=excel_bytes,
                    file_name="psydox_users.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                    key="sb_users_dl",
                )
            except Exception as _e:
                st.caption(f"Users export unavailable: {_e}")

        if st.button("Sign Out", key="sb_signout", use_container_width=True):
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

        # Admin: health check (only shown when DEBUG_MODE or admin role)
        import os
        if os.environ.get("DEBUG_MODE", "").lower() in ("1", "true"):
            st.markdown("---")
            if st.button("🔍 Health Check", use_container_width=True, key="sb_health"):
                st.session_state["show_health"] = True
            if st.session_state.get("show_health"):
                try:
                    from psydox.health import check_health
                    report = check_health()
                    for comp in report.components:
                        st.caption(f"{comp.icon()} {comp.name}: {comp.message or comp.status.value}")
                except Exception as e:
                    st.caption(f"Health check error: {e}")

    # ── Header ─────────────────────────────────────────────────────────────────
    hcol1, hcol2 = st.columns([6, 1])
    with hcol1:
        st.markdown(
            '<span class="psx-gradient-text" style="font-size:2.4rem;">⚡ Psydox Studio</span>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<p style="color:var(--text-secondary);font-size:0.9rem;margin-top:-8px;">'
            'CREATE. VERIFY. DELIVER.</p>',
            unsafe_allow_html=True,
        )
    with hcol2:
        if on_new_project and st.button("+ New Project", use_container_width=True, key="hdr_new"):
            on_new_project()

    st.divider()

    # ── Hero ───────────────────────────────────────────────────────────────────
    render_hero(
        user_name=user_name,
        on_classic=on_classic,
        on_ai_studio=on_ai_studio if is_owner else None,
    )

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Stats row ──────────────────────────────────────────────────────────────
    jm    = get_job_manager()
    stats = jm.stats(user_email=user_email)
    if prefs.is_widget_visible("metrics"):
        render_stats_row(stats)
        st.markdown("<br>", unsafe_allow_html=True)

    # ── Quick Create ───────────────────────────────────────────────────────────
    if prefs.is_widget_visible("quick_create"):
        render_quick_create(
            on_select=on_feature_select,
            pinned_ids=prefs.pinned_features(),
            cols=4 if prefs.layout() == "comfortable" else 5,
            show_ai=is_owner,
        )
        st.markdown("<br>", unsafe_allow_html=True)

    # ── Recent projects ────────────────────────────────────────────────────────
    if prefs.is_widget_visible("recent_projects"):
        try:
            from psydox.projects.service import get_project_service
            projects = get_project_service().list(user_email)
            render_recent_projects(
                [p.to_dict() for p in projects[:6]],
                on_open=lambda pid: st.session_state.update({"view_project": pid}),
            )
            st.markdown("<br>", unsafe_allow_html=True)
        except Exception:
            pass

    # ── Recent jobs ────────────────────────────────────────────────────────────
    if prefs.is_widget_visible("recent_jobs"):
        recent = jm.recent(user_email=user_email, n=10)

        def _handle_download(job, out):
            fname = f"{job.feature_id}_{job.id}.jpg"
            st.download_button(
                label=f"⬇ Download {out.get('label', '')}",
                data=out["bytes"],
                file_name=fname,
                mime=out.get("mime", "image/jpeg"),
                key=f"dl_btn_{job.id}_{fname}",
            )

        render_recent_jobs(recent, on_download=_handle_download)

    # ── Widget customization toggle ────────────────────────────────────────────
    with st.expander("⚙️ Customize dashboard", expanded=False):
        st.caption("Show / hide widgets:")
        for widget_id, _, label, default in WIDGET_REGISTRY:
            if widget_id == "hero":
                continue
            visible = prefs.is_widget_visible(widget_id)
            new_val = st.checkbox(label, value=visible, key=f"wvis_{widget_id}")
            if new_val != visible:
                prefs.toggle_widget(widget_id)
                prefs.save()
                st.rerun()

        # Accent color override
        st.markdown("**Accent colour**")
        current_accent = prefs.get("accent", "")
        new_accent = st.text_input("HEX (leave blank to use theme default)",
                                    value=current_accent, key="accent_input")
        if new_accent != current_accent:
            prefs.set("accent", new_accent.strip())
            prefs.save()
            st.rerun()
