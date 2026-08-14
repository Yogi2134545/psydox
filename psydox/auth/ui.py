"""Psydox Auth — Streamlit auth UI.

Renders the authentication flow as a state-machine.
Returns True when the user is authenticated and the app should proceed.

States:
  login         — sign-in form (default)
  register      — registration form
  verify_sent   — "check your email" confirmation
  verify_ok     — email verified successfully (from ?verify= param)
  verify_fail   — token invalid/expired
  forgot        — forgot-password form
  reset_sent    — "check your email" confirmation for reset
  reset         — set-new-password form (from ?reset= param)
  profile       — account profile / change password
  sessions      — active sessions management

URL-triggered states are handled on entry before any interaction:
  ?verify=<token>  → auto-verify, redirect to verify_ok / verify_fail
  ?reset=<token>   → show reset-password form

The function signature is:
  render_auth_page(auth_service) -> bool
  Returns True = user is now authenticated.

After successful login, these session_state keys are set:
  logged_in      True
  user_id        str
  session_id     str
  user_name      str
  user_email     str
  user_role      str
"""
from __future__ import annotations

import streamlit as st
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from psydox.auth.service import AuthService

# ── Branding constants ────────────────────────────────────────────────────────
_BRAND_COLOR = "#ff6600"
_CARD_CSS = """
<style>
.auth-card {
    max-width: 420px;
    margin: 0 auto;
    padding: 40px 40px 32px;
    background: var(--background-color, #111);
    border: 1px solid rgba(255,102,0,0.2);
    border-radius: 16px;
}
.auth-logo {
    text-align: center;
    padding: 0 0 24px;
}
.auth-logo .icon { font-size: 48px; }
.auth-logo h1 {
    color: #ff6600;
    margin: 0;
    font-size: 2rem;
    letter-spacing: 2px;
}
.auth-logo p { color: #888; font-size: 13px; margin: 4px 0 0; }
.auth-divider { color: #888; text-align:center; margin: 8px 0; font-size: 13px; }
.auth-footer { text-align: center; color: #888; font-size: 12px; margin-top: 16px; }
</style>
"""


def _inject_css() -> None:
    st.markdown(_CARD_CSS, unsafe_allow_html=True)


def _logo(subtitle: str = "Image Processing Engine") -> None:
    st.markdown(
        f"""<div class="auth-logo">
            <div class="icon">⚡</div>
            <h1>Psydox</h1>
            <p>{subtitle}</p>
        </div>""",
        unsafe_allow_html=True,
    )


def _set_state(state: str) -> None:
    st.session_state.auth_state = state


def _success_login(result, svc) -> None:
    """Populate session state after a successful login AuthResult."""
    st.session_state.logged_in  = True
    st.session_state.user_id    = result.user.id
    st.session_state.session_id = result.session_id or ""
    st.session_state.user_name  = result.user.full_name or result.user.email
    st.session_state.user_email = result.user.email
    st.session_state.user_role  = result.user.role
    st.session_state.auth_state = "authenticated"


# ── URL param handling (called once before rendering) ─────────────────────────

def _handle_url_params(svc: "AuthService") -> str | None:
    """
    Handle ?verify=<token> and ?reset=<token>.
    Returns the state to enter, or None to keep the current state.
    """
    verify_tok = st.query_params.get("verify", "")
    reset_tok  = st.query_params.get("reset", "")

    if verify_tok and not st.session_state.get("_url_verify_done"):
        st.session_state._url_verify_done = True
        st.query_params.clear()
        result = svc.verify_email(verify_tok)
        if result.success:
            st.session_state._verify_user_name = result.user.full_name if result.user else ""
            return "verify_ok"
        else:
            st.session_state._verify_error = result.error
            return "verify_fail"

    if reset_tok and not st.session_state.get("_url_reset_token"):
        st.session_state._url_reset_token = reset_tok
        st.query_params.clear()
        return "reset"

    return None


# ── Individual page renderers ─────────────────────────────────────────────────

def _page_login(svc: "AuthService") -> bool:
    _logo()
    # Show success banner when redirected from skip-verify registration
    reg_email = st.session_state.pop("_reg_success_email", None)
    if reg_email:
        st.success(f"✅ Account created for **{reg_email}**. You can sign in now.")
    with st.form("auth_login_form"):
        email = st.text_input("Email", placeholder="you@company.com", key="li_email")
        pwd   = st.text_input("Password", type="password", key="li_pwd")
        col_r, col_f = st.columns([1, 1])
        with col_r:
            remember = st.checkbox("Remember me", key="li_remember")
        ok = st.form_submit_button("Sign In →", use_container_width=True)

    if ok:
        if not email or not pwd:
            st.error("Please enter your email and password.")
        else:
            result = svc.login(email, pwd, remember_me=remember)
            if result.success:
                _success_login(result, svc)
                st.rerun()
                return True
            elif result.error_code == "UNVERIFIED":
                st.warning("Please verify your email address before signing in.")
                if st.button("Resend verification email →", key="li_resend"):
                    link = svc.resend_verification(email)
                    st.session_state._reg_email       = email
                    st.session_state._reg_in_app_link = link
                    _set_state("verify_sent")
                    st.rerun()
            else:
                st.error(result.error or "Sign in failed.")

    st.markdown('<div class="auth-divider">— or —</div>', unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Create account", use_container_width=True, key="li_to_reg"):
            _set_state("register")
            st.rerun()
    with c2:
        if st.button("Forgot password?", use_container_width=True, key="li_to_forgot"):
            _set_state("forgot")
            st.rerun()

    return False


def _page_register(svc: "AuthService") -> None:
    _logo("Create your account")
    with st.form("auth_reg_form"):
        name     = st.text_input("Full name", placeholder="Jane Smith", key="reg_name")
        email    = st.text_input("Email", placeholder="you@company.com", key="reg_email")
        pwd      = st.text_input("Password", type="password", key="reg_pwd",
                                  help="Min 8 chars, must include uppercase, lowercase, and a number.")
        pwd2     = st.text_input("Confirm password", type="password", key="reg_pwd2")
        terms    = st.checkbox(
            "I agree to the Terms of Service and Privacy Policy", key="reg_terms"
        )
        ok = st.form_submit_button("Create Account →", use_container_width=True)

    if ok:
        result = svc.register(name, email, pwd, pwd2, terms_accepted=terms)
        if result.success:
            st.session_state._reg_email       = email
            st.session_state._reg_in_app_link = result.in_app_link or ""
            _set_state("verify_sent")
            st.rerun()
        else:
            st.error(result.error or "Registration failed.")

    st.markdown('<div class="auth-divider">Already have an account?</div>', unsafe_allow_html=True)
    if st.button("← Sign In", use_container_width=True, key="reg_to_li"):
        _set_state("login")
        st.rerun()


def _page_verify_sent() -> None:
    _logo()
    email        = st.session_state.get("_reg_email", "your inbox")
    in_app_link  = st.session_state.get("_reg_in_app_link", "")

    if in_app_link:
        # No email service configured — show the link directly on screen
        st.warning(
            "⚠️ **Email delivery is not configured** — no verification email was sent.\n\n"
            "Click the button below to verify your account right now:"
        )
        st.markdown(
            f"""<div style="text-align:center;margin:24px 0">
              <a href="{in_app_link}" target="_self"
                 style="background:#ff6600;color:white;padding:14px 32px;
                        text-decoration:none;border-radius:8px;font-weight:bold;
                        font-size:16px;display:inline-block">
                ✅ Verify My Account
              </a>
            </div>""",
            unsafe_allow_html=True,
        )
        st.caption(
            "To receive real emails, add **RESEND_API_KEY** in your Railway environment variables. "
            "Sign up free at resend.com (100 emails/day)."
        )
    else:
        st.success(
            f"✅ Account created! A verification email has been sent to **{email}**.\n\n"
            "Click the link in that email to activate your account."
        )
        st.info("The link expires in 48 hours. Check your spam folder if it doesn't arrive.")

    if st.button("← Back to Sign In", use_container_width=True, key="vs_back"):
        st.session_state._reg_in_app_link = ""
        _set_state("login")
        st.rerun()


def _page_verify_ok() -> None:
    _logo()
    name = st.session_state.get("_verify_user_name", "")
    greeting = f"Welcome, {name}!" if name else "Email verified!"
    st.success(f"✅ {greeting} Your email address has been verified.")
    st.write("Your account is now active. You can sign in below.")
    if st.button("Sign In →", use_container_width=True, key="vok_login"):
        _set_state("login")
        st.rerun()


def _page_verify_fail() -> None:
    _logo()
    error = st.session_state.get("_verify_error", "Verification link is invalid or has expired.")
    st.error(f"❌ {error}")
    st.write("You can request a new verification email by signing in or creating a new account.")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Sign In", use_container_width=True, key="vf_login"):
            _set_state("login")
            st.rerun()
    with c2:
        if st.button("Create Account", use_container_width=True, key="vf_reg"):
            _set_state("register")
            st.rerun()


def _page_forgot(svc: "AuthService") -> None:
    _logo("Reset your password")
    with st.form("auth_forgot_form"):
        email = st.text_input("Email address", placeholder="you@company.com", key="fg_email")
        ok    = st.form_submit_button("Send Reset Link →", use_container_width=True)

    if ok:
        if not email:
            st.error("Please enter your email address.")
        else:
            svc.request_password_reset(email)
            st.session_state._reset_req_email = email
            _set_state("reset_sent")
            st.rerun()

    if st.button("← Back to Sign In", use_container_width=True, key="fg_back"):
        _set_state("login")
        st.rerun()


def _page_reset_sent() -> None:
    _logo()
    email = st.session_state.get("_reset_req_email", "your inbox")
    st.info(
        f"If an account exists for **{email}**, you will receive a password reset email shortly.\n\n"
        "The link expires in 1 hour."
    )
    if st.button("← Back to Sign In", use_container_width=True, key="rs_back"):
        _set_state("login")
        st.rerun()


def _page_reset(svc: "AuthService") -> None:
    _logo("Set new password")
    token = st.session_state.get("_url_reset_token", "")
    if not token:
        st.error("Invalid reset link. Please request a new one.")
        if st.button("← Back to Sign In", key="rp_no_token"):
            _set_state("login")
            st.rerun()
        return

    with st.form("auth_reset_form"):
        pwd  = st.text_input("New password", type="password", key="rp_pwd",
                              help="Min 8 chars, must include uppercase, lowercase, and a number.")
        pwd2 = st.text_input("Confirm new password", type="password", key="rp_pwd2")
        ok   = st.form_submit_button("Set New Password →", use_container_width=True)

    if ok:
        result = svc.reset_password(token, pwd, pwd2)
        if result.success:
            st.session_state._url_reset_token = None
            st.success("✅ Password updated successfully! You can now sign in.")
            _set_state("login")
            st.rerun()
        else:
            st.error(result.error or "Password reset failed.")

    if st.button("← Cancel", key="rp_cancel"):
        st.session_state._url_reset_token = None
        _set_state("login")
        st.rerun()


# ── Profile (rendered inside app, not on auth wall) ───────────────────────────

def render_profile_page(svc: "AuthService") -> None:
    """Render the profile page. Called from inside the authenticated app."""
    from psydox.auth.models import AccountStatus
    import time

    user_id = st.session_state.get("user_id", "")
    if not user_id:
        st.error("Session expired. Please sign in again.")
        return

    user = svc.get_user(user_id)
    if not user:
        st.error("User not found.")
        return

    st.markdown("## 👤 My Profile")
    col1, col2 = st.columns([2, 1])
    with col1:
        st.markdown(f"**Email:** {user.email}")
        verified_label = "✅ Verified" if user.email_verified else "⚠️ Not verified"
        st.markdown(f"**Status:** {user.status.value.replace('_', ' ').title()}  |  {verified_label}")
        st.markdown(f"**Role:** {user.role}")
        if user.created_at:
            import datetime
            joined = datetime.datetime.fromtimestamp(user.created_at).strftime("%B %Y")
            st.markdown(f"**Member since:** {joined}")
        if user.last_login_at:
            import datetime
            last = datetime.datetime.fromtimestamp(user.last_login_at).strftime("%Y-%m-%d %H:%M")
            st.markdown(f"**Last login:** {last}")

    st.markdown("---")
    st.markdown("### Update Name")
    with st.form("profile_name_form"):
        new_name = st.text_input("Full name", value=user.full_name, key="prof_name")
        save_ok  = st.form_submit_button("Save Changes", use_container_width=True)
    if save_ok:
        result = svc.update_profile(user_id, new_name)
        if result.success:
            st.session_state.user_name = result.user.full_name
            st.success("Profile updated.")
            st.rerun()
        else:
            st.error(result.error)

    st.markdown("---")
    st.markdown("### Change Password")
    with st.form("profile_pw_form"):
        cur_pw  = st.text_input("Current password", type="password", key="cpw_cur")
        new_pw  = st.text_input("New password", type="password", key="cpw_new",
                                 help="Min 8 chars, uppercase, lowercase, and a number.")
        new_pw2 = st.text_input("Confirm new password", type="password", key="cpw_new2")
        pw_ok   = st.form_submit_button("Change Password", use_container_width=True)
    if pw_ok:
        result = svc.change_password(user_id, cur_pw, new_pw, new_pw2)
        if result.success:
            st.success("Password changed successfully.")
        else:
            st.error(result.error)

    st.markdown("---")
    st.markdown("### Active Sessions")
    sessions = svc.get_active_sessions(user_id)
    if not sessions:
        st.caption("No active sessions.")
    for sess in sessions:
        import datetime
        c1, c2, c3 = st.columns([3, 2, 1])
        with c1:
            label = "📱 Remember-me session" if sess.remember_me else "💻 Session"
            exp   = datetime.datetime.fromtimestamp(sess.expires_at).strftime("%Y-%m-%d")
            st.caption(f"{label}  |  expires {exp}")
        with c2:
            if sess.user_agent:
                st.caption(sess.user_agent[:60])
        with c3:
            current = sess.id == st.session_state.get("session_id", "")
            if current:
                st.caption("(current)")
            else:
                if st.button("Revoke", key=f"revoke_{sess.id}"):
                    svc.revoke_session(sess.id, user_id)
                    st.rerun()

    st.markdown("---")
    if st.button("⚠️ Sign out all devices", key="prof_logout_all"):
        svc.logout_all(user_id, user_email=user.email)
        st.session_state.logged_in = False
        st.session_state.session_id = ""
        st.rerun()


# ── Main render function ──────────────────────────────────────────────────────

def render_auth_page(svc: "AuthService") -> bool:
    """
    Render the auth UI.
    Returns True if the user is authenticated and the app should proceed.

    Reads/writes these session_state keys:
      auth_state, logged_in, user_id, session_id, user_name, user_email, user_role
    """
    # Short-circuit: already authenticated (session restored from cookie/session_state)
    if st.session_state.get("logged_in") and st.session_state.get("session_id"):
        user = svc.validate_session(st.session_state.session_id)
        if user:
            # Refresh role in case it changed
            st.session_state.user_role  = user.role
            st.session_state.user_name  = user.full_name or user.email
            st.session_state.user_email = user.email
            return True
        # Session expired — fall through to login
        st.session_state.logged_in  = False
        st.session_state.session_id = ""

    # Default state
    if "auth_state" not in st.session_state:
        st.session_state.auth_state = "login"

    # Handle ?verify= and ?reset= URL params (one-shot)
    url_state = _handle_url_params(svc)
    if url_state:
        st.session_state.auth_state = url_state

    _inject_css()

    _, col, _ = st.columns([1, 2, 1])
    with col:
        state = st.session_state.auth_state

        if state == "authenticated":
            return True
        elif state == "login":
            authenticated = _page_login(svc)
            if authenticated:
                return True
        elif state == "register":
            _page_register(svc)
        elif state == "verify_sent":
            _page_verify_sent()
        elif state == "verify_ok":
            _page_verify_ok()
        elif state == "verify_fail":
            _page_verify_fail()
        elif state == "forgot":
            _page_forgot(svc)
        elif state == "reset_sent":
            _page_reset_sent()
        elif state == "reset":
            _page_reset(svc)
        else:
            _set_state("login")
            st.rerun()

    return False
