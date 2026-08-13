from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from shared_platform.application import ApplicationContext


@dataclass(frozen=True)
class ScsPaths:
    root: Path
    db: Path
    database: Path
    uploads: Path
    exports: Path
    backups: Path
    tmp: Path
    logs: Path

    @classmethod
    def from_context(cls, context: ApplicationContext) -> "ScsPaths":
        if not isinstance(context, ApplicationContext) or context.application_id != "scs":
            raise ValueError("ScsPaths requires an explicit SCS context")
        expected = ("SCS", "SCS", "scs_employee_session", "https://ai.sunshineclimatesolutions.com", 8100, 3100)
        actual = (context.environment_prefix, context.secret_namespace, context.session_cookie, context.public_origin, context.api_port, context.web_port)
        if actual != expected or context.data_root.name.casefold() != "scs_data":
            raise ValueError("SCS context does not match the reserved isolation boundary")
        root = context.data_root.resolve(strict=False)
        db = root / "db"
        return cls(
            root=root,
            db=db,
            database=db / "scs.sqlite3",
            uploads=root / "uploads",
            exports=root / "exports",
            backups=root / "backups",
            tmp=root / "tmp",
            logs=root / "logs",
        )

    def directories(self) -> tuple[Path, ...]:
        return (self.root, self.db, self.uploads, self.exports, self.backups, self.tmp, self.logs)

    def ensure(self) -> "ScsPaths":
        for path in self.directories():
            path.mkdir(parents=True, exist_ok=True)
        return self
