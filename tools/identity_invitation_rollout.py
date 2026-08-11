from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence

from defend_data.config import DataPaths
from defend_data.identity_mailer import GmailInvitationMailer, activation_url
from defend_data.identity_store import IdentityStore


def run(
    command: str,
    *,
    paths: DataPaths | None = None,
    mailer: GmailInvitationMailer | None = None,
    output: Callable[[str], object] = print,
) -> int:
    """Run the offline rollout check without emitting invitation material."""
    store = IdentityStore(paths or DataPaths.from_env())
    try:
        if command == "check":
            preflight = store.invitation_transport_preflight()
            if preflight.ready:
                output("READY legacy_pending=0")
                return 0
            output(f"BLOCKED legacy_pending={preflight.legacy_pending_count}")
            return 2

        if command != "reissue":
            raise ValueError("command must be check or reissue")

        active_mailer = mailer or GmailInvitationMailer()

        def deliver(invitation, credential: str) -> bool:
            result = active_mailer.send_invitation(
                recipient=invitation.email,
                activation_url=activation_url(credential),
                expires_at=invitation.expires_at,
            )
            return result.delivered

        try:
            replacements = store.reissue_legacy_pending_invitations(
                deliver=deliver
            )
        except Exception:
            # Provider and database exceptions can include recipient or server
            # material. The operator gets a stable, credential-free failure.
            output("REISSUE FAILED; no database changes were committed")
            return 3

        output(
            f"REISSUED count={len(replacements)} delivered={len(replacements)}"
        )
        preflight = store.invitation_transport_preflight()
        if not preflight.ready:
            output(f"BLOCKED legacy_pending={preflight.legacy_pending_count}")
            return 2
        output("READY legacy_pending=0")
        return 0
    finally:
        store.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check or safely reissue pre-fragment DEFEND invitations."
    )
    parser.add_argument("command", choices=("check", "reissue"))
    args = parser.parse_args(argv)
    return run(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
