from __future__ import annotations

from dataclasses import dataclass
import smtplib
from email.message import EmailMessage
from urllib.parse import quote


@dataclass(frozen=True)
class DeliveryResult:
    ok: bool
    status: str


def invitation_activation_url(public_origin: str, raw_token: str) -> str:
    if public_origin.rstrip("/") != "https://ai.sunshineclimatesolutions.com":
        raise ValueError("invitation activation requires the SCS origin")
    if not isinstance(raw_token, str) or not raw_token.startswith("scsinvite_"):
        raise ValueError("invalid SCS invitation token")
    return f"{public_origin.rstrip('/')}/activate#token={quote(raw_token, safe='_-')}"


class ScsInvitationMailer:
    def __init__(self, *, username: str, app_password: str, sender: str, host: str = "smtp.gmail.com", port: int = 465) -> None:
        self._username = username
        self._app_password = app_password
        self._sender = sender
        self._host = host
        self._port = port

    def __repr__(self) -> str:
        return "ScsInvitationMailer(configured=True)"

    def send_invitation(self, email: str, activation_url: str) -> DeliveryResult:
        message = EmailMessage()
        message["Subject"] = "Sunshine Climate Solutions employee invitation"
        message["From"] = self._sender
        message["To"] = email
        message.set_content(
            "You have been invited to the Sunshine Climate Solutions operations portal.\n\n"
            f"Activate your employee account: {activation_url}\n"
        )
        try:
            with smtplib.SMTP_SSL(self._host, self._port, timeout=15) as smtp:
                smtp.login(self._username, self._app_password)
                smtp.send_message(message)
            return DeliveryResult(True, "sent")
        except Exception:
            return DeliveryResult(False, "failed")
