"""Idempotent admin account bootstrap for DEFENDcoder.

Run with the same environment as the coder server (CODER_DATABASE_URL):

    .venv\\Scripts\\python -m tools.defend_coder_admin_bootstrap \\
        --username admin --email admin@defend-network.org

The password is read interactively with getpass — never from argv, never
logged, never written to a file, and stored in PostgreSQL only as an
Argon2id hash. Re-running the tool for an existing username is a no-op
(exit 0) so it is safe to call from provisioning scripts.
"""

from __future__ import annotations

import argparse
from getpass import getpass
import sys
from typing import Callable

from defend_coder.auth import AuthService
from defend_coder.config import CoderSettings
from defend_coder.db import CoderDatabase
from defend_coder.repositories import CoderRepository

EXIT_CREATED = 0
EXIT_ALREADY_EXISTS = 0
EXIT_USAGE = 2


def bootstrap_admin(
    repository: CoderRepository,
    *,
    username: str,
    email: str | None,
    password: str,
    role: str,
    output: Callable[[str], None] = print,
) -> bool:
    """Create an admin account if absent; return True when created.

    Never echoes the password. Raises ValueError for empty username or
    password; the password itself is only passed to AuthService, which
    stores an Argon2id hash.
    """
    existing = repository.get_account_by_username(username.strip())
    if existing is not None:
        output(
            f"DEFENDcoder account '{existing.username}' already exists "
            f"(role={existing.role}); nothing to do."
        )
        return False

    service = AuthService(repository)
    account = service.create_account(
        username=username,
        email=email,
        password=password,
        role=role,
    )
    output(
        f"Created DEFENDcoder {role} account '{account.username}' "
        f"(account_id={account.account_id})."
    )
    return True


def run(
    settings: CoderSettings,
    *,
    username: str,
    email: str | None,
    role: str,
    output: Callable[[str], None] = print,
    prompt_password: Callable[[str], str] = getpass,
    repository: CoderRepository | None = None,
) -> int:
    if not username.strip():
        output("error: --username must not be empty")
        return EXIT_USAGE

    if role not in {"admin", "consumer"}:
        output("error: --role must be admin or consumer")
        return EXIT_USAGE

    if repository is None:
        database = CoderDatabase(settings.database_url)
        database.migrate()
        repository = CoderRepository(database)

    existing = repository.get_account_by_username(username.strip())
    if existing is not None:
        output(
            f"DEFENDcoder account '{existing.username}' already exists "
            f"(role={existing.role}); nothing to do."
        )
        return EXIT_ALREADY_EXISTS

    password = prompt_password(
        f"Password for new DEFENDcoder {role} account '{username}': "
    )
    if not password:
        output("error: password must not be empty")
        return EXIT_USAGE

    confirmation = prompt_password("Confirm password: ")
    if password != confirmation:
        output("error: passwords do not match")
        return EXIT_USAGE

    bootstrap_admin(
        repository,
        username=username,
        email=email,
        password=password,
        role=role,
        output=output,
    )
    return EXIT_CREATED


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="defend_coder_admin_bootstrap",
        description=(
            "Create an idempotent DEFENDcoder admin account "
            "(password read interactively)."
        ),
    )
    parser.add_argument(
        "--username",
        required=True,
        help="username for the new account",
    )
    parser.add_argument(
        "--email",
        default=None,
        help="optional email address for the new account",
    )
    parser.add_argument(
        "--role",
        default="admin",
        choices=("admin", "consumer"),
        help="account role (default: admin)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        settings = CoderSettings.from_env()
    except RuntimeError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_USAGE
    return run(
        settings,
        username=args.username,
        email=args.email,
        role=args.role,
    )


if __name__ == "__main__":
    sys.exit(main())