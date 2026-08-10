from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .config import DataPaths
from .sqlite_utils import connect_sqlite, json_dumps, json_loads, transaction


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class MessageRecord:
    message_id: str
    conversation_id: str
    seq: int
    role: str
    content: str
    created_at: str
    trace_id: str | None
    request_id: str | None
    metadata: dict[str, Any]


class ConversationStore:
    """Durable chat history. This is history/state, not semantic memory."""

    VALID_ROLES = {"system", "user", "assistant", "tool"}

    def __init__(self, paths: DataPaths):
        self.paths = paths.ensure()
        self.db_path = self.paths.db / "conversations.db"
        self.conn = connect_sqlite(self.db_path)
        self._migrate()

    def close(self) -> None:
        self.conn.close()

    def _migrate(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS conversations (
                conversation_id TEXT PRIMARY KEY,
                user_id TEXT,
                project_id TEXT,
                title TEXT,
                summary_text TEXT,
                summary_updated_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS messages (
                message_id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,
                seq INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                trace_id TEXT,
                request_id TEXT,
                created_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                UNIQUE(conversation_id, seq)
            );
            CREATE INDEX IF NOT EXISTS idx_messages_conv_seq ON messages(conversation_id, seq);
            CREATE TABLE IF NOT EXISTS attachments (
                attachment_id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,
                document_id TEXT,
                artifact_id TEXT,
                display_name TEXT,
                created_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );
            """
        )
        self.conn.execute("INSERT OR REPLACE INTO schema_meta(key,value) VALUES('schema_version','1')")
        self.conn.commit()

    def ensure_conversation(self, conversation_id: str, *, user_id: str | None = None,
                            project_id: str | None = None, title: str | None = None,
                            metadata: dict[str, Any] | None = None) -> None:
        now = utc_now()
        self.conn.execute(
            """INSERT INTO conversations(conversation_id,user_id,project_id,title,created_at,updated_at,metadata_json)
               VALUES(?,?,?,?,?,?,?)
               ON CONFLICT(conversation_id) DO UPDATE SET
                 updated_at=excluded.updated_at,
                 user_id=COALESCE(conversations.user_id, excluded.user_id),
                 project_id=COALESCE(conversations.project_id, excluded.project_id),
                 title=COALESCE(conversations.title, excluded.title)""",
            (conversation_id, user_id, project_id, title, now, now, json_dumps(metadata or {})),
        )
        self.conn.commit()

    def append_message(self, conversation_id: str, *, role: str, content: str,
                       trace_id: str | None = None, request_id: str | None = None,
                       metadata: dict[str, Any] | None = None) -> MessageRecord:
        if role not in self.VALID_ROLES:
            raise ValueError(f"Invalid role: {role}")
        if not isinstance(content, str):
            raise TypeError("content must be str")
        self.ensure_conversation(conversation_id)
        now = utc_now()
        message_id = f"msg_{uuid.uuid4().hex}"
        with transaction(self.conn, immediate=True):
            row = self.conn.execute(
                "SELECT COALESCE(MAX(seq),0)+1 AS next_seq FROM messages WHERE conversation_id=?",
                (conversation_id,),
            ).fetchone()
            seq = int(row["next_seq"])
            self.conn.execute(
                """INSERT INTO messages(message_id,conversation_id,seq,role,content,trace_id,request_id,created_at,metadata_json)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (message_id, conversation_id, seq, role, content, trace_id, request_id, now, json_dumps(metadata or {})),
            )
            self.conn.execute("UPDATE conversations SET updated_at=? WHERE conversation_id=?", (now, conversation_id))
        return MessageRecord(message_id, conversation_id, seq, role, content, now, trace_id, request_id, metadata or {})

    def recent_messages(self, conversation_id: str, limit: int = 10) -> list[MessageRecord]:
        rows = self.conn.execute(
            """SELECT * FROM (
                 SELECT * FROM messages WHERE conversation_id=? ORDER BY seq DESC LIMIT ?
               ) ORDER BY seq ASC""",
            (conversation_id, max(1, int(limit))),
        ).fetchall()
        return [
            MessageRecord(r["message_id"], r["conversation_id"], r["seq"], r["role"], r["content"],
                          r["created_at"], r["trace_id"], r["request_id"], json_loads(r["metadata_json"], {}))
            for r in rows
        ]


    def add_attachment(
        self,
        conversation_id: str,
        *,
        document_id: str | None = None,
        artifact_id: str | None = None,
        display_name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        self.ensure_conversation(conversation_id)
        attachment_id = f"att_{uuid.uuid4().hex}"
        self.conn.execute(
            """
            INSERT INTO attachments(
                attachment_id,conversation_id,document_id,artifact_id,
                display_name,created_at,metadata_json
            ) VALUES(?,?,?,?,?,?,?)
            """,
            (
                attachment_id,
                conversation_id,
                document_id,
                artifact_id,
                display_name,
                utc_now(),
                json_dumps(metadata or {}),
            ),
        )
        self.conn.commit()
        return attachment_id

    def get_messages(self, conversation_id: str, *, limit: int = 500) -> list[MessageRecord]:
        return self.recent_messages(conversation_id, limit=max(1, min(int(limit), 1000)))

    def delete_conversation(self, conversation_id: str) -> bool:
        cur = self.conn.execute(
            "DELETE FROM conversations WHERE conversation_id=?",
            (conversation_id,),
        )
        self.conn.commit()
        return cur.rowcount == 1

    def stats(self) -> dict[str, int]:
        conv = int(self.conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0])
        msgs = int(self.conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0])
        atts = int(self.conn.execute("SELECT COUNT(*) FROM attachments").fetchone()[0])
        return {
            "conversations": conv,
            "messages": msgs,
            "attachments": atts,
        }

    def set_summary(self, conversation_id: str, summary_text: str) -> None:
        self.ensure_conversation(conversation_id)
        now = utc_now()
        self.conn.execute(
            "UPDATE conversations SET summary_text=?,summary_updated_at=?,updated_at=? WHERE conversation_id=?",
            (summary_text, now, now, conversation_id),
        )
        self.conn.commit()

    def get_summary(self, conversation_id: str) -> str | None:
        row = self.conn.execute("SELECT summary_text FROM conversations WHERE conversation_id=?", (conversation_id,)).fetchone()
        return row["summary_text"] if row else None
