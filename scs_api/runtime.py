from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from scs_data.config import ScsPaths
from scs_data.customers import ScsCustomerStore
from scs_data.identity import ScsIdentityStore
from scs_data.jobs import ScsJobStore
from scs_data.mailer import DeliveryResult, ScsInvitationMailer
from scs_data.memberships import ScsMembershipStore
from shared_platform.application import ApplicationContext

from .app import build_scs_app


@dataclass(frozen=True)
class UnconfiguredMailer:
    def send_invitation(self, *_args: object) -> DeliveryResult:
        return DeliveryResult(False, "not_configured")


context = ApplicationContext(
    "scs",
    Path(os.environ.get("SCS_DATA_ROOT", r"C:\SCS_DATA")),
    "SCS",
    "SCS",
    "scs_employee_session",
    os.environ.get("SCS_PUBLIC_ORIGIN", "https://ai.sunshineclimatesolutions.com"),
    int(os.environ.get("SCS_API_PORT", "8100")),
    int(os.environ.get("SCS_WEB_PORT", "3100")),
)
identity = ScsIdentityStore(ScsPaths.from_context(context).ensure().database)
customers = ScsCustomerStore(identity.conn, identity.audit)
memberships = ScsMembershipStore(identity.conn, identity.audit)
jobs = ScsJobStore(identity.conn, identity.audit)
if all(os.environ.get(key) for key in ("SCS_GMAIL_USERNAME", "SCS_GMAIL_APP_PASSWORD", "SCS_GMAIL_SENDER")):
    mailer: object = ScsInvitationMailer(
        username=os.environ["SCS_GMAIL_USERNAME"],
        app_password=os.environ["SCS_GMAIL_APP_PASSWORD"],
        sender=os.environ["SCS_GMAIL_SENDER"],
    )
else:
    mailer = UnconfiguredMailer()
app = build_scs_app(context, identity, mailer, customers=customers, memberships=memberships, jobs=jobs)
