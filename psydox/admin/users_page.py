"""Psydox Admin — Users Management Page.

Owner/admin only.  Shows all registered users, allows:
  - Manual email verification (for users whose email never arrived)
  - Role change
  - Suspend / reactivate
  - Download full user Excel
  - Registration history Excel

All write actions are gated to owner/admin role inside this module.
The caller (app.py) must also gate navigation to this page.
"""
from __future__ import annotations

import datetime
import streamlit as st


def _fmt_ts(ts) -> str:
    if not ts:
        return "—"
    return datetime.datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M")


_STATUS_BADGE = {
    "active":               "🟢 Active",
    "pending_verification": "🟡 Pending",
    "suspended":            "🔴 Suspended",
    "disabled":             "⚫ Disabled",
}

_ROLE_OPTIONS = ["user", "viewer", "editor", "manager", "reviewer",
                 "creative", "operator", "catalog_operator", "admin", "owner"]


def render_admin_users_page(on_back=None) -> None:
    """Full user management admin page. Call from app.py after owner check."""
    from psydox.auth.service import get_auth_service, get_all_users_excel, get_registration_log_excel
    from psydox.auth.models import AccountStatus

    svc              = get_auth_service()
    admin_email      = st.session_state.get("user_email", "")
    admin_role       = st.session_state.get("user_role", "admin")
    _caller_is_owner = admin_role == "owner"

    # ── Header ────────────────────────────────────────────────────────────────
    hcol, bcol = st.columns([5, 1])
    with hcol:
        st.markdown("## 👥 User Management")
    with bcol:
        if on_back and st.button("← Dashboard", use_container_width=True):
            on_back()

    users = svc.admin_list_users()

    # ── Stats row ─────────────────────────────────────────────────────────────
    total     = len(users)
    active    = sum(1 for u in users if u.status.value == "active")
    pending   = sum(1 for u in users if u.status.value == "pending_verification")
    suspended = sum(1 for u in users if u.status.value == "suspended")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Users",  total)
    c2.metric("Active",       active)
    c3.metric("Pending",      pending,   delta=f"-{pending} need verify" if pending else None,
              delta_color="inverse")
    c4.metric("Suspended",    suspended, delta_color="inverse")

    st.markdown("---")

    # ── Downloads ─────────────────────────────────────────────────────────────
    dc1, dc2 = st.columns(2)
    with dc1:
        try:
            excel = get_all_users_excel()
            st.download_button(
                "⬇ Download All Users (Excel)",
                data=excel,
                file_name=f"psydox_users_{datetime.date.today()}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                key="adm_dl_users",
            )
        except Exception as e:
            st.error(f"Export failed: {e}")
    with dc2:
        try:
            reg_excel = get_registration_log_excel()
            if reg_excel:
                st.download_button(
                    "⬇ Download Registration History (Excel)",
                    data=reg_excel,
                    file_name=f"psydox_registrations_{datetime.date.today()}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                    key="adm_dl_regs",
                )
            else:
                st.caption("No registration log file yet.")
        except Exception as e:
            st.caption(f"Registration log unavailable: {e}")

    st.markdown("---")

    # ── Search / filter ───────────────────────────────────────────────────────
    f1, f2, f3 = st.columns([3, 2, 2])
    with f1:
        search = st.text_input("Search email or name", placeholder="Search…", key="adm_search")
    with f2:
        filter_status = st.selectbox("Status", ["All", "Active", "Pending", "Suspended"], key="adm_fstatus")
    with f3:
        filter_role = st.selectbox("Role", ["All"] + _ROLE_OPTIONS, key="adm_frole")

    # Apply filters
    filtered = users
    if search:
        q = search.lower()
        filtered = [u for u in filtered if q in u.email.lower() or q in u.full_name.lower()]
    if filter_status != "All":
        status_map = {"Active": "active", "Pending": "pending_verification", "Suspended": "suspended"}
        filtered = [u for u in filtered if u.status.value == status_map.get(filter_status, "")]
    if filter_role != "All":
        filtered = [u for u in filtered if u.role == filter_role]

    st.caption(f"Showing {len(filtered)} of {total} users")

    if not filtered:
        st.info("No users match the current filter.")
        return

    # ── User table ────────────────────────────────────────────────────────────
    for user in filtered:
        with st.expander(
            f"{_STATUS_BADGE.get(user.status.value, user.status.value)}  "
            f"**{user.full_name or user.email}**  —  {user.email}  |  `{user.role}`",
            expanded=(user.status.value == "pending_verification"),
        ):
            col_info, col_actions = st.columns([3, 2])

            with col_info:
                st.markdown(f"**Email:** {user.email}")
                st.markdown(f"**Full Name:** {user.full_name or '—'}")
                st.markdown(f"**Role:** `{user.role}`")
                st.markdown(f"**Status:** {_STATUS_BADGE.get(user.status.value, user.status.value)}")
                st.markdown(f"**Email Verified:** {'✅ Yes' if user.email_verified else '❌ No'}")
                st.markdown(f"**Registered:** {_fmt_ts(user.created_at)}")
                st.markdown(f"**Last Login:** {_fmt_ts(user.last_login_at)}")

            with col_actions:
                uid = user.id

                # Verify button — only shown for unverified accounts
                if not user.email_verified or user.status.value == "pending_verification":
                    if st.button("✅ Verify Now", key=f"verify_{uid}", use_container_width=True,
                                 help="Manually activate this account (use when email delivery fails)"):
                        res = svc.admin_verify_user(uid, admin_email)
                        if res.success:
                            st.success(f"{user.email} is now verified and active.")
                            st.rerun()
                        else:
                            st.error(res.error)

                # Role change — enforce hierarchy:
                #   Only owner can assign/edit owner or admin roles.
                #   Admin can only assign roles below admin.
                #   Nobody can change their own role (safety lock).
                _is_self      = user.email.lower() == admin_email.lower()
                _target_priv  = user.role in ("owner", "admin")
                _can_edit     = _caller_is_owner or (not _is_self and not _target_priv)
                _assignable   = _ROLE_OPTIONS if _caller_is_owner else [
                    r for r in _ROLE_OPTIONS if r not in ("owner", "admin")
                ]

                if not _can_edit:
                    if _is_self:
                        st.caption("🔒 Cannot change your own role.")
                    elif user.role == "owner":
                        st.caption("🔒 Owner role — only another owner can modify this.")
                    else:
                        st.caption("🔒 Admin role — only the owner can modify admin accounts.")
                else:
                    # Show deferred success message from a previous save
                    _msg_key = f"role_saved_msg_{uid}"
                    if _msg_key in st.session_state:
                        st.success(st.session_state.pop(_msg_key))

                    # Pre-init session state from DB — only on first render,
                    # never overwrite a pending user selection on reruns.
                    _role_key = f"role_{uid}"
                    if _role_key not in st.session_state:
                        st.session_state[_role_key] = user.role

                    new_role = st.selectbox(
                        "Change Role",
                        _assignable,
                        key=_role_key,
                        # no index= — session state alone controls the value so
                        # the click-rerun cannot reset it back to the DB value
                        # before the save handler runs.
                    )
                    if new_role != user.role:
                        col_save, col_cancel = st.columns(2)
                        with col_save:
                            if st.button("Save Role", key=f"saverole_{uid}",
                                         use_container_width=True, type="primary"):
                                res = svc.admin_update_role(uid, new_role, admin_email)
                                if res.success:
                                    # Store message so it survives the rerun
                                    st.session_state[_msg_key] = (
                                        f"Role updated: {user.role} → {new_role}"
                                    )
                                    # Sync selectbox to new DB value so the
                                    # button disappears immediately after save.
                                    st.session_state[_role_key] = new_role
                                    st.rerun()
                                else:
                                    st.error(res.error)
                        with col_cancel:
                            if st.button("Cancel", key=f"cancelrole_{uid}",
                                         use_container_width=True):
                                st.session_state[_role_key] = user.role
                                st.rerun()

                # Suspend / Activate — only owner can suspend owners/admins
                from psydox.auth.models import AccountStatus as _AS
                _can_suspend = _caller_is_owner or (not _is_self and not _target_priv)
                if _can_suspend:
                    if user.status == _AS.ACTIVE:
                        if st.button("🔴 Suspend", key=f"suspend_{uid}", use_container_width=True):
                            svc.admin_set_status(uid, _AS.SUSPENDED, admin_email)
                            st.warning(f"{user.email} suspended.")
                            st.rerun()
                    elif user.status == _AS.SUSPENDED:
                        if st.button("🟢 Reactivate", key=f"activate_{uid}", use_container_width=True):
                            svc.admin_set_status(uid, _AS.ACTIVE, admin_email)
                            st.success(f"{user.email} reactivated.")
                            st.rerun()

                # Resend verification email
                if not user.email_verified:
                    if st.button("📧 Resend Verification Email",
                                 key=f"resend_{uid}", use_container_width=True):
                        link = svc.resend_verification(user.email)
                        if link:
                            st.warning(
                                "No email service configured — copy this link and send it manually:"
                            )
                            st.code(link, language=None)
                        else:
                            st.info(f"Verification email sent to {user.email}.")
