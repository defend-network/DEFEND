from __future__ import annotations

import os
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import make_msgid
from urllib.parse import quote, urlsplit

from .identity_security import normalize_email


def public_web_origin() -> str:
    configured = os.getenv(
        "DEFEND_PUBLIC_WEB_ORIGIN", "https://ai.defend-network.org"
    ).strip().rstrip("/")
    parsed = urlsplit(configured)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return "https://ai.defend-network.org"
    return configured


def activation_url(credential: str) -> str:
    return f"{public_web_origin()}/activate#token={quote(credential, safe='')}"


@dataclass(frozen=True)
class DeliveryResult:
    delivered: bool
    provider_message_id: str | None = None
    error: str | None = None


class GmailInvitationMailer:
    """Small Gmail SMTP adapter that never exposes transport credentials."""

    def __init__(self) -> None:
        self._security = os.getenv("DEFEND_GMAIL_SMTP_SECURITY", "ssl").strip().lower()
        self._host = os.getenv("DEFEND_GMAIL_SMTP_HOST", "smtp.gmail.com").strip()
        default_port = "587" if self._security == "starttls" else "465"
        try:
            self._port = int(os.getenv("DEFEND_GMAIL_SMTP_PORT", default_port))
        except ValueError:
            self._port = 0
        self._username = os.getenv("DEFEND_GMAIL_SMTP_USERNAME", "").strip()
        self._password = os.getenv("DEFEND_GMAIL_APP_PASSWORD", "")
        self._sender = os.getenv(
            "DEFEND_GMAIL_SENDER", "chairman@defend-network.org"
        ).strip()
        try:
            configured_timeout = float(os.getenv("DEFEND_GMAIL_SMTP_TIMEOUT", "15"))
        except ValueError:
            configured_timeout = 15.0
        self._timeout = max(1.0, min(configured_timeout, 60.0))

    def _configured(self) -> bool:
        return bool(
            self._security in {"ssl", "starttls"}
            and self._host
            and 0 < self._port <= 65535
            and self._username
            and self._password
            and self._sender
        )

    def send_invitation(
        self,
        *,
        recipient: str,
        activation_url: str,
        expires_at: str,
    ) -> DeliveryResult:
        if not self._configured():
            return DeliveryResult(False, error="Gmail SMTP is not configured")

        try:
            normalized_recipient = normalize_email(recipient)
            message = EmailMessage()
            message["Subject"] = "Activate your DEFEND account"
            message["From"] = self._sender
            message["To"] = normalized_recipient
            message["Message-ID"] = make_msgid()
            message.set_content(
                "You have been invited to activate your DEFEND account.\n\n"
                f"Activation link: {activation_url}\n\n"
                f"This invitation expires at {expires_at}.\n"
                "If you were not expecting this invitation, you can ignore this message."
            )

            context = ssl.create_default_context()
            if self._security == "ssl":
                with smtplib.SMTP_SSL(
                    self._host,
                    self._port,
                    context=context,
                    timeout=self._timeout,
                ) as smtp:
                    smtp.login(self._username, self._password)
                    refused = smtp.send_message(message)
            else:
                with smtplib.SMTP(
                    self._host,
                    self._port,
                    timeout=self._timeout,
                ) as smtp:
                    smtp.starttls(context=context)
                    smtp.login(self._username, self._password)
                    refused = smtp.send_message(message)
            if refused:
                return DeliveryResult(False, error="Gmail SMTP refused the recipient")
            return DeliveryResult(
                True,
                provider_message_id=str(message["Message-ID"]),
            )
        except Exception as exc:
            # Exception messages can contain server-supplied text. Keep only the
            # exception class so credentials and invitation links cannot leak.
            kind = type(exc).__name__[:80] or "SMTPError"
            return DeliveryResult(False, error=f"{kind}: email delivery failed"[:240])
