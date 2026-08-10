from __future__ import annotations

from email.message import EmailMessage

import defend_data.identity_mailer as identity_mailer
from defend_data.identity_mailer import GmailInvitationMailer


class _SMTPRecorder:
    instances: list["_SMTPRecorder"] = []

    def __init__(self, host, port, *, context=None, timeout=None):
        self.host = host
        self.port = port
        self.context = context
        self.timeout = timeout
        self.login_args = None
        self.message = None
        self.started_tls = False
        self.__class__.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def starttls(self, *, context=None):
        self.started_tls = True
        self.context = context

    def login(self, username, password):
        self.login_args = (username, password)

    def send_message(self, message):
        self.message = message
        return {}


def _configure(monkeypatch, *, security="ssl"):
    monkeypatch.setenv("DEFEND_GMAIL_SMTP_HOST", "smtp.gmail.test")
    monkeypatch.setenv("DEFEND_GMAIL_SMTP_PORT", "465" if security == "ssl" else "587")
    monkeypatch.setenv("DEFEND_GMAIL_SMTP_SECURITY", security)
    monkeypatch.setenv("DEFEND_GMAIL_SMTP_USERNAME", "chairman@example.com")
    monkeypatch.setenv("DEFEND_GMAIL_APP_PASSWORD", "super-secret-app-password")
    monkeypatch.setenv("DEFEND_GMAIL_SENDER", "chairman@example.com")


def test_ssl_mailer_sends_a_bounded_invitation_message_without_exposing_secret(
    monkeypatch, caplog
):
    _configure(monkeypatch)
    _SMTPRecorder.instances.clear()
    monkeypatch.setattr(identity_mailer.smtplib, "SMTP_SSL", _SMTPRecorder)

    result = GmailInvitationMailer().send_invitation(
        recipient="Member@Example.com",
        activation_url="https://ai.defend-network.org/activate/invite_raw-token",
        expires_at="2026-08-12T12:00:00+00:00",
    )

    assert result.delivered is True
    assert result.error is None
    assert result.provider_message_id
    smtp = _SMTPRecorder.instances[-1]
    assert (smtp.host, smtp.port) == ("smtp.gmail.test", 465)
    assert smtp.login_args == ("chairman@example.com", "super-secret-app-password")
    assert isinstance(smtp.message, EmailMessage)
    assert smtp.message["From"] == "chairman@example.com"
    assert smtp.message["To"] == "member@example.com"
    body = smtp.message.get_body(preferencelist=("plain",)).get_content()
    assert "https://ai.defend-network.org/activate/invite_raw-token" in body
    assert "2026-08-12T12:00:00+00:00" in body
    assert "super-secret-app-password" not in repr(result)
    assert "super-secret-app-password" not in caplog.text


def test_starttls_mailer_negotiates_tls_before_authentication(monkeypatch):
    _configure(monkeypatch, security="starttls")
    _SMTPRecorder.instances.clear()
    monkeypatch.setattr(identity_mailer.smtplib, "SMTP", _SMTPRecorder)

    result = GmailInvitationMailer().send_invitation(
        recipient="member@example.com",
        activation_url="https://ai.defend-network.org/activate/invite_token",
        expires_at="2026-08-12T12:00:00+00:00",
    )

    assert result.delivered is True
    smtp = _SMTPRecorder.instances[-1]
    assert (smtp.host, smtp.port) == ("smtp.gmail.test", 587)
    assert smtp.started_tls is True


def test_missing_configuration_and_transport_errors_are_safe_and_bounded(
    monkeypatch, caplog
):
    for name in (
        "DEFEND_GMAIL_SMTP_USERNAME",
        "DEFEND_GMAIL_APP_PASSWORD",
        "DEFEND_GMAIL_SENDER",
    ):
        monkeypatch.delenv(name, raising=False)

    missing = GmailInvitationMailer().send_invitation(
        recipient="member@example.com",
        activation_url="https://ai.defend-network.org/activate/invite_token",
        expires_at="2026-08-12T12:00:00+00:00",
    )
    assert missing.delivered is False
    assert missing.error == "Gmail SMTP is not configured"

    secret = "transport-secret-that-must-not-leak"
    _configure(monkeypatch)

    class BrokenSMTP(_SMTPRecorder):
        def __enter__(self):
            raise RuntimeError(secret + "x" * 1000)

    monkeypatch.setattr(identity_mailer.smtplib, "SMTP_SSL", BrokenSMTP)
    failed = GmailInvitationMailer().send_invitation(
        recipient="member@example.com",
        activation_url="https://ai.defend-network.org/activate/invite_token",
        expires_at="2026-08-12T12:00:00+00:00",
    )

    assert failed.delivered is False
    assert failed.error
    assert len(failed.error) <= 240
    assert secret not in failed.error
    assert secret not in caplog.text
