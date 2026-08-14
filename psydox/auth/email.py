"""Psydox Auth — email service abstraction.

EmailService sends transactional auth emails (verification, password reset).

Implementations:
  ConsoleEmailService — logs to stdout (development / no SMTP configured)
  SMTPEmailService    — sends real email via SMTP

Factory: get_email_service() returns the appropriate implementation based on
environment variables.

Environment variables (for SMTP):
  SMTP_HOST   — required to enable SMTP
  SMTP_PORT   — default 587
  SMTP_USER   — SMTP username / sender address
  SMTP_PASS   — SMTP password (never logged)
  SMTP_FROM   — From address (defaults to SMTP_USER)
  SMTP_TLS    — "1" to force TLS (STARTTLS used when port!=465)
  PSYDOX_BASE_URL — base URL for verification/reset links (default http://localhost:8501)

DO NOT commit real SMTP credentials — use environment variables.
"""
from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod

_log = logging.getLogger("psydox.auth.email")

_PSYDOX_BASE_URL = os.environ.get("PSYDOX_BASE_URL", "http://localhost:8501")

_VERIFY_SUBJECT = "Verify your Psydox email address"
_RESET_SUBJECT  = "Reset your Psydox password"


class EmailService(ABC):

    @abstractmethod
    def send_verification_email(self, email: str, name: str, token: str) -> None: ...

    @abstractmethod
    def send_password_reset_email(self, email: str, name: str, token: str) -> None: ...

    def _verify_link(self, token: str) -> str:
        return f"{_PSYDOX_BASE_URL.rstrip('/')}?verify={token}"

    def _reset_link(self, token: str) -> str:
        return f"{_PSYDOX_BASE_URL.rstrip('/')}?reset={token}"


class ConsoleEmailService(EmailService):
    """Development fallback — prints links to stdout/log. Zero configuration."""

    def send_verification_email(self, email: str, name: str, token: str) -> None:
        link = self._verify_link(token)
        msg = (
            f"\n{'='*60}\n"
            f"[Psydox DEV] Email Verification\n"
            f"To:    {email} ({name})\n"
            f"Link:  {link}\n"
            f"{'='*60}"
        )
        print(msg)
        _log.info("VERIFICATION EMAIL (console): %s → %s", email, link)

    def send_password_reset_email(self, email: str, name: str, token: str) -> None:
        link = self._reset_link(token)
        msg = (
            f"\n{'='*60}\n"
            f"[Psydox DEV] Password Reset\n"
            f"To:    {email} ({name})\n"
            f"Link:  {link}\n"
            f"{'='*60}"
        )
        print(msg)
        _log.info("RESET EMAIL (console): %s → %s", email, link)


class SMTPEmailService(EmailService):
    """Production SMTP email sender. Reads credentials from environment."""

    def __init__(self) -> None:
        self.host    = os.environ.get("SMTP_HOST", "")
        self.port    = int(os.environ.get("SMTP_PORT", "587"))
        self.user    = os.environ.get("SMTP_USER", "")
        self.passwd  = os.environ.get("SMTP_PASS", "")
        self.from_   = os.environ.get("SMTP_FROM", self.user)
        self.use_tls = os.environ.get("SMTP_TLS", "1").lower() in ("1", "true", "yes")

    def send_verification_email(self, email: str, name: str, token: str) -> None:
        link = self._verify_link(token)
        first = name.split()[0] if name else "there"
        html = f"""
<div style="font-family:sans-serif;max-width:480px;margin:0 auto">
  <h2 style="color:#ff6600">⚡ Psydox</h2>
  <p>Hi {first},</p>
  <p>Click the button below to verify your email address and activate your Psydox account.</p>
  <p style="text-align:center;margin:32px 0">
    <a href="{link}" style="background:#ff6600;color:white;padding:14px 28px;
       text-decoration:none;border-radius:8px;font-weight:bold">Verify Email</a>
  </p>
  <p style="color:#888;font-size:13px">
    This link expires in 48 hours and can only be used once.<br>
    If you didn't create a Psydox account, you can safely ignore this email.
  </p>
  <p style="color:#aaa;font-size:12px">Or copy this link: {link}</p>
</div>"""
        self._send(email, _VERIFY_SUBJECT, html)

    def send_password_reset_email(self, email: str, name: str, token: str) -> None:
        link = self._reset_link(token)
        first = name.split()[0] if name else "there"
        html = f"""
<div style="font-family:sans-serif;max-width:480px;margin:0 auto">
  <h2 style="color:#ff6600">⚡ Psydox</h2>
  <p>Hi {first},</p>
  <p>We received a request to reset your Psydox password. Click the button below to set a new password.</p>
  <p style="text-align:center;margin:32px 0">
    <a href="{link}" style="background:#ff6600;color:white;padding:14px 28px;
       text-decoration:none;border-radius:8px;font-weight:bold">Reset Password</a>
  </p>
  <p style="color:#888;font-size:13px">
    This link expires in 1 hour and can only be used once.<br>
    If you did not request a password reset, you can safely ignore this email. Your password will not be changed.
  </p>
  <p style="color:#aaa;font-size:12px">Or copy this link: {link}</p>
</div>"""
        self._send(email, _RESET_SUBJECT, html)

    def _send(self, to: str, subject: str, html: str) -> None:
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        msg = MIMEMultipart("alternative")
        msg["From"]    = self.from_
        msg["To"]      = to
        msg["Subject"] = subject
        msg.attach(MIMEText(html, "html"))

        try:
            if self.port == 465:
                with smtplib.SMTP_SSL(self.host, self.port) as smtp:
                    smtp.login(self.user, self.passwd)
                    smtp.sendmail(self.from_, to, msg.as_string())
            else:
                with smtplib.SMTP(self.host, self.port) as smtp:
                    smtp.ehlo()
                    if self.use_tls:
                        smtp.starttls()
                    smtp.login(self.user, self.passwd)
                    smtp.sendmail(self.from_, to, msg.as_string())
            _log.info("Email sent: %s → %s", subject, to)
        except Exception as exc:
            _log.error("SMTP send failed to %s: %s", to, exc)
            raise


def get_email_service() -> EmailService:
    if os.environ.get("SMTP_HOST"):
        return SMTPEmailService()
    return ConsoleEmailService()
