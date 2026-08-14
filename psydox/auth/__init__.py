"""Psydox Auth package — public API.

UI functions (render_auth_page, render_profile_page) require Streamlit;
import them directly from psydox.auth.ui when needed inside a Streamlit context.
"""
from psydox.auth.models  import AccountStatus, AuthResult, User, Session
from psydox.auth.service import AuthService, get_auth_service

__all__ = [
    "AccountStatus",
    "AuthResult",
    "AuthService",
    "get_auth_service",
    "Session",
    "User",
]
