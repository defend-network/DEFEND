from __future__ import annotations

import hashlib
import hmac
import ipaddress
import os
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .config import DataPaths
from .sqlite_utils import connect_sqlite, json_dumps, json_loads, transaction


_SENSITIVE_METADATA_KEY_FRAGMENTS = (
    "password",
    "token",
    "cookie",
    "authorization",
    "secret",
)
_MAX_METADATA_DEPTH = 6
_MAX_METADATA_ITEMS = 50
_MAX_METADATA_KEY_CHARS = 120
_MAX_METADATA_STRING_CHARS = 2_000


def _safe_usage_metadata(value: Any, *, depth: int = 0) -> Any:
    """Return a bounded copy safe for admin responses without altering storage."""
    if depth > _MAX_METADATA_DEPTH:
        return None
    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for raw_key, nested in list(value.items())[:_MAX_METADATA_ITEMS]:
            key = str(raw_key)[:_MAX_METADATA_KEY_CHARS]
            normalized = key.casefold()
            if any(fragment in normalized for fragment in _SENSITIVE_METADATA_KEY_FRAGMENTS):
                continue
            safe[key] = _safe_usage_metadata(nested, depth=depth + 1)
        return safe
    if isinstance(value, list):
        return [
            _safe_usage_metadata(nested, depth=depth + 1)
            for nested in value[:_MAX_METADATA_ITEMS]
        ]
    if isinstance(value, str):
        return value[:_MAX_METADATA_STRING_CHARS]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_ip(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        return "unknown"
    # Strip IPv6 brackets and a simple IPv4 :port suffix.
    if raw.startswith("[") and "]" in raw:
        raw = raw[1:raw.index("]")]
    elif raw.count(":") == 1 and raw.rsplit(":", 1)[1].isdigit():
        raw = raw.rsplit(":", 1)[0]
    try:
        return str(ipaddress.ip_address(raw))
    except ValueError:
        return "unknown"


def client_ip(headers: dict[str, str], observed: str | None, *, trust_cloudflare: bool) -> str:
    """Resolve the client IP using the explicitly configured proxy trust boundary.

    We intentionally do not trust X-Forwarded-For. Cloudflare's header is used
    only when explicitly enabled by DEFEND_TRUST_CLOUDFLARE.
    """
    if trust_cloudflare:
        cf = _clean_ip(headers.get("cf-connecting-ip"))
        if cf != "unknown":
            return cf
    return _clean_ip(observed)


def coarse_client_meta(user_agent: str | None, accept_language: str | None = None) -> dict[str, str]:
    ua = (user_agent or "").lower()
    if "edg/" in ua:
        browser = "edge"
    elif "chrome/" in ua and "chromium" not in ua:
        browser = "chrome"
    elif "firefox/" in ua:
        browser = "firefox"
    elif "safari/" in ua and "chrome/" not in ua and "chromium" not in ua:
        browser = "safari"
    else:
        browser = "other"

    if any(x in ua for x in ("iphone", "ipad", "ios")):
        platform = "ios"
    elif "android" in ua:
        platform = "android"
    elif "windows" in ua:
        platform = "windows"
    elif "mac os" in ua or "macintosh" in ua:
        platform = "macos"
    elif "linux" in ua:
        platform = "linux"
    else:
        platform = "other"

    device = "mobile" if any(x in ua for x in ("mobile", "iphone", "android")) else "desktop"
    lang = (accept_language or "").split(",", 1)[0].strip().lower()[:16] or "unknown"
    return {"browser": browser, "platform": platform, "device": device, "language": lang}


def visitor_hmac_secret() -> bytes:
    secret = os.getenv("DEFEND_VISITOR_HMAC_KEY", "").strip()
    if len(secret) < 32:
        raise RuntimeError(
            "DEFEND_VISITOR_HMAC_KEY must be configured with at least 32 characters"
        )
    return secret.encode("utf-8")


def fingerprint_hmac(ip: str, client_meta: dict[str, str]) -> str:
    """Return a pseudonymous secondary correlation value for a connection."""
    payload = "|".join(
        [
            _clean_ip(ip),
            client_meta.get("browser", "other"),
            client_meta.get("platform", "other"),
            client_meta.get("device", "other"),
            client_meta.get("language", "unknown"),
        ]
    )
    digest = hmac.new(visitor_hmac_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"fp_{digest}"


def cookie_identifiers_hmac(visitor_id: str, session_id: str) -> str:
    """Hash server-issued visitor/session cookie identifiers for correlation."""
    payload = f"{visitor_id}|{session_id}".encode("utf-8")
    digest = hmac.new(visitor_hmac_secret(), payload, hashlib.sha256).hexdigest()
    return f"cookie_{digest}"


_VISITOR_RE = re.compile(r"^vis_[A-Za-z0-9_-]{24,96}$")
_SESSION_RE = re.compile(r"^vsess_[A-Za-z0-9_-]{24,96}$")


@dataclass(frozen=True)
class VisitorSession:
    visitor_id: str
    session_id: str


class VisitorStore:
    """Pseudonymous visitor/session/conversation index and owner analytics metadata.

    Detailed connection observations are stored separately for bounded retention.
    The HMAC fingerprint is secondary correlation only; it never becomes the
    primary visitor identity and is never used to merge visitors automatically.
    """

    def __init__(self, paths: DataPaths):
        self.paths = paths.ensure()
        self.db_path = self.paths.db / "visitors.db"
        self.conn = connect_sqlite(self.db_path)
        self._migrate()

    def close(self) -> None:
        self.conn.close()

    def _migrate(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS visitors (
                visitor_id TEXT PRIMARY KEY,
                fingerprint_hmac TEXT,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                seen_count INTEGER NOT NULL DEFAULT 1,
                client_meta_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_visitors_fingerprint
                ON visitors(fingerprint_hmac);
            CREATE INDEX IF NOT EXISTS idx_visitors_last_seen
                ON visitors(last_seen DESC);

            CREATE TABLE IF NOT EXISTS visitor_sessions (
                session_id TEXT PRIMARY KEY,
                visitor_id TEXT NOT NULL REFERENCES visitors(visitor_id) ON DELETE CASCADE,
                created_at TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                client_meta_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_visitor_sessions_visitor
                ON visitor_sessions(visitor_id, last_seen DESC);

            CREATE TABLE IF NOT EXISTS conversation_index (
                conversation_id TEXT PRIMARY KEY,
                visitor_id TEXT NOT NULL REFERENCES visitors(visitor_id) ON DELETE CASCADE,
                session_id TEXT REFERENCES visitor_sessions(session_id),
                title TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_route TEXT,
                last_model TEXT,
                research_status TEXT,
                message_count INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_conversation_index_visitor
                ON conversation_index(visitor_id, updated_at DESC);

            CREATE TABLE IF NOT EXISTS usage_events (
                event_id TEXT PRIMARY KEY,
                visitor_id TEXT,
                conversation_id TEXT,
                request_id TEXT,
                event_type TEXT NOT NULL,
                route TEXT,
                model TEXT,
                research_status TEXT,
                evidence_count INTEGER,
                status TEXT,
                created_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_usage_events_visitor
                ON usage_events(visitor_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_usage_events_conversation
                ON usage_events(conversation_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_usage_events_created
                ON usage_events(created_at DESC);

            CREATE TABLE IF NOT EXISTS connection_events (
                connection_id TEXT PRIMARY KEY,
                visitor_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                ip_address TEXT NOT NULL,
                user_agent TEXT NOT NULL,
                browser TEXT NOT NULL,
                platform TEXT NOT NULL,
                device TEXT NOT NULL,
                language TEXT NOT NULL,
                fingerprint_hmac TEXT NOT NULL,
                cookie_hash TEXT NOT NULL,
                observed_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_connection_events_visitor
                ON connection_events(visitor_id, observed_at DESC);
            CREATE INDEX IF NOT EXISTS idx_connection_events_session
                ON connection_events(session_id, observed_at DESC);
            CREATE INDEX IF NOT EXISTS idx_connection_events_ip
                ON connection_events(ip_address, observed_at DESC);
            CREATE INDEX IF NOT EXISTS idx_connection_events_observed
                ON connection_events(observed_at DESC);
            """
        )
        self.conn.execute(
            "INSERT OR REPLACE INTO schema_meta(key,value) VALUES('schema_version','2')"
        )
        self.conn.commit()

    @staticmethod
    def _new_visitor_id() -> str:
        return f"vis_{uuid.uuid4().hex}"

    @staticmethod
    def _new_session_id() -> str:
        return f"vsess_{uuid.uuid4().hex}"

    def ensure_visitor(
        self,
        cookie_visitor_id: str | None,
        *,
        fingerprint: str,
        client_meta: dict[str, str],
    ) -> str:
        now = utc_now()
        candidate = (cookie_visitor_id or "").strip()
        row = None
        if _VISITOR_RE.fullmatch(candidate):
            row = self.conn.execute(
                "SELECT visitor_id FROM visitors WHERE visitor_id=?",
                (candidate,),
            ).fetchone()

        # Never accept a caller-chosen unknown visitor id. Generate a new one.
        visitor_id = candidate if row is not None else self._new_visitor_id()
        with transaction(self.conn, immediate=True):
            existing = self.conn.execute(
                "SELECT visitor_id FROM visitors WHERE visitor_id=?",
                (visitor_id,),
            ).fetchone()
            if existing is None:
                self.conn.execute(
                    """
                    INSERT INTO visitors(
                        visitor_id,fingerprint_hmac,first_seen,last_seen,seen_count,client_meta_json
                    ) VALUES(?,?,?,?,?,?)
                    """,
                    (visitor_id, fingerprint, now, now, 1, json_dumps(client_meta)),
                )
            else:
                self.conn.execute(
                    """
                    UPDATE visitors
                    SET fingerprint_hmac=?, last_seen=?, seen_count=seen_count+1,
                        client_meta_json=?
                    WHERE visitor_id=?
                    """,
                    (fingerprint, now, json_dumps(client_meta), visitor_id),
                )
        return visitor_id

    def ensure_session(
        self,
        cookie_session_id: str | None,
        visitor_id: str,
        *,
        client_meta: dict[str, str],
    ) -> str:
        now = utc_now()
        candidate = (cookie_session_id or "").strip()
        row = None
        if _SESSION_RE.fullmatch(candidate):
            row = self.conn.execute(
                "SELECT visitor_id FROM visitor_sessions WHERE session_id=?",
                (candidate,),
            ).fetchone()

        # Existing session must belong to the current visitor. Otherwise rotate it.
        session_id = (
            candidate
            if row is not None and row["visitor_id"] == visitor_id
            else self._new_session_id()
        )
        with transaction(self.conn, immediate=True):
            existing = self.conn.execute(
                "SELECT visitor_id FROM visitor_sessions WHERE session_id=?",
                (session_id,),
            ).fetchone()
            if existing is None:
                self.conn.execute(
                    """
                    INSERT INTO visitor_sessions(
                        session_id,visitor_id,created_at,last_seen,client_meta_json
                    ) VALUES(?,?,?,?,?)
                    """,
                    (session_id, visitor_id, now, now, json_dumps(client_meta)),
                )
            else:
                if existing["visitor_id"] != visitor_id:
                    raise RuntimeError("Visitor session ownership mismatch")
                self.conn.execute(
                    "UPDATE visitor_sessions SET last_seen=?,client_meta_json=? WHERE session_id=?",
                    (now, json_dumps(client_meta), session_id),
                )
        return session_id

    def claim_or_verify_conversation(
        self,
        *,
        conversation_id: str,
        visitor_id: str,
        session_id: str | None,
        title: str | None = None,
    ) -> bool:
        now = utc_now()
        with transaction(self.conn, immediate=True):
            row = self.conn.execute(
                "SELECT visitor_id FROM conversation_index WHERE conversation_id=?",
                (conversation_id,),
            ).fetchone()
            if row is not None:
                return row["visitor_id"] == visitor_id
            self.conn.execute(
                """
                INSERT INTO conversation_index(
                    conversation_id,visitor_id,session_id,title,created_at,updated_at,message_count
                ) VALUES(?,?,?,?,?,?,0)
                """,
                (
                    conversation_id,
                    visitor_id,
                    session_id,
                    (title or "New chat")[:160],
                    now,
                    now,
                ),
            )
        return True

    def owns_conversation(self, visitor_id: str, conversation_id: str) -> bool:
        row = self.conn.execute(
            "SELECT visitor_id FROM conversation_index WHERE conversation_id=?",
            (conversation_id,),
        ).fetchone()
        return row is not None and row["visitor_id"] == visitor_id

    def touch_conversation(
        self,
        *,
        conversation_id: str,
        visitor_id: str,
        title: str | None = None,
        last_route: str | None = None,
        last_model: str | None = None,
        research_status: str | None = None,
        increment_messages: int = 0,
    ) -> bool:
        if not self.owns_conversation(visitor_id, conversation_id):
            return False
        now = utc_now()
        row = self.conn.execute(
            "SELECT title FROM conversation_index WHERE conversation_id=?",
            (conversation_id,),
        ).fetchone()
        current_title = (row["title"] if row else None) or ""
        next_title = current_title
        if title and (not current_title or current_title == "New chat"):
            next_title = title[:160]
        self.conn.execute(
            """
            UPDATE conversation_index
            SET updated_at=?, title=?,
                last_route=COALESCE(?,last_route),
                last_model=COALESCE(?,last_model),
                research_status=COALESCE(?,research_status),
                message_count=message_count+?
            WHERE conversation_id=? AND visitor_id=?
            """,
            (
                now,
                next_title,
                last_route,
                last_model,
                research_status,
                max(0, int(increment_messages)),
                conversation_id,
                visitor_id,
            ),
        )
        self.conn.commit()
        return True

    def list_conversations_for_visitor(self, visitor_id: str, *, limit: int = 5) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT conversation_id,title,created_at,updated_at,last_route,last_model,
                   research_status,message_count
            FROM conversation_index
            WHERE visitor_id=?
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (visitor_id, max(1, min(int(limit), 200))),
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_conversation_index(self, visitor_id: str, conversation_id: str) -> bool:
        cur = self.conn.execute(
            "DELETE FROM conversation_index WHERE conversation_id=? AND visitor_id=?",
            (conversation_id, visitor_id),
        )
        self.conn.commit()
        return cur.rowcount == 1

    def record_event(
        self,
        *,
        event_type: str,
        visitor_id: str | None = None,
        conversation_id: str | None = None,
        request_id: str | None = None,
        route: str | None = None,
        model: str | None = None,
        research_status: str | None = None,
        evidence_count: int | None = None,
        status: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        event_id = f"evt_{uuid.uuid4().hex}"
        self.conn.execute(
            """
            INSERT INTO usage_events(
                event_id,visitor_id,conversation_id,request_id,event_type,route,model,
                research_status,evidence_count,status,created_at,metadata_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                event_id,
                visitor_id,
                conversation_id,
                request_id,
                event_type,
                route,
                model,
                research_status,
                evidence_count,
                status,
                utc_now(),
                json_dumps(metadata or {}),
            ),
        )
        self.conn.commit()
        return event_id

    def record_connection(
        self,
        *,
        visitor_id: str,
        session_id: str,
        ip_address: str,
        user_agent: str,
        client_meta: dict[str, str],
        cookie_hash: str,
        observed_at: str | None = None,
    ) -> str:
        connection_id = f"conn_{uuid.uuid4().hex}"
        canonical_ip = _clean_ip(ip_address)
        self.conn.execute(
            """
            INSERT INTO connection_events(
                connection_id,visitor_id,session_id,ip_address,user_agent,browser,
                platform,device,language,fingerprint_hmac,cookie_hash,observed_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                connection_id,
                visitor_id,
                session_id,
                canonical_ip,
                user_agent or "",
                client_meta.get("browser", "other"),
                client_meta.get("platform", "other"),
                client_meta.get("device", "other"),
                client_meta.get("language", "unknown"),
                fingerprint_hmac(canonical_ip, client_meta),
                cookie_hash,
                observed_at or utc_now(),
            ),
        )
        self.conn.commit()
        return connection_id

    def connection_detail(self, connection_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM connection_events WHERE connection_id=?",
            (connection_id,),
        ).fetchone()
        return dict(row) if row is not None else None

    def purge_connection_history(self, *, before: str) -> int:
        cur = self.conn.execute(
            "DELETE FROM connection_events WHERE observed_at < ?",
            (before,),
        )
        self.conn.commit()
        return cur.rowcount

    def overview(self) -> dict[str, int]:
        return {
            "visitors": int(self.conn.execute("SELECT COUNT(*) FROM visitors").fetchone()[0]),
            "sessions": int(self.conn.execute("SELECT COUNT(*) FROM visitor_sessions").fetchone()[0]),
            "conversations": int(self.conn.execute("SELECT COUNT(*) FROM conversation_index").fetchone()[0]),
            "usage_events": int(self.conn.execute("SELECT COUNT(*) FROM usage_events").fetchone()[0]),
        }

    def list_visitors(self, *, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT v.visitor_id,v.fingerprint_hmac,v.first_seen,v.last_seen,v.seen_count,
                   v.client_meta_json,
                   COUNT(DISTINCT c.conversation_id) AS conversation_count,
                   COALESCE(SUM(c.message_count),0) AS message_count
            FROM visitors v
            LEFT JOIN conversation_index c ON c.visitor_id=v.visitor_id
            GROUP BY v.visitor_id
            ORDER BY v.last_seen DESC
            LIMIT ? OFFSET ?
            """,
            (max(1, min(int(limit), 500)), max(0, int(offset))),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            item = dict(r)
            item["client_meta"] = json_loads(item.pop("client_meta_json"), {})
            out.append(item)
        return out

    def search_visitors(
        self,
        *,
        query: str = "",
        linked_visitor_ids: list[str] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        if not 1 <= int(limit) <= 100:
            raise ValueError("limit must be between 1 and 100")
        if not 0 <= int(offset) <= 1_000_000:
            raise ValueError("offset must be between 0 and 1000000")
        cleaned = (query or "").strip()[:200]
        like = f"%{cleaned}%"
        linked = list(dict.fromkeys(linked_visitor_ids or []))[:1000]
        linked_clause = ""
        linked_params: list[str] = []
        if linked:
            linked_clause = f" OR v.visitor_id IN ({','.join('?' for _ in linked)})"
            linked_params = linked
        where = f"""
            WHERE ?='' OR v.visitor_id LIKE ? OR v.fingerprint_hmac LIKE ?
                OR v.client_meta_json LIKE ?
                OR EXISTS(
                    SELECT 1 FROM connection_events ce
                    WHERE ce.visitor_id=v.visitor_id AND (
                        ce.ip_address LIKE ? OR ce.user_agent LIKE ? OR ce.browser LIKE ?
                        OR ce.platform LIKE ? OR ce.device LIKE ? OR ce.language LIKE ?
                        OR ce.fingerprint_hmac LIKE ?
                    )
                )
                {linked_clause}
        """
        params: list[object] = [cleaned, like, like, like, like, like, like, like, like, like, like, *linked_params]
        total = int(
            self.conn.execute(
                f"SELECT COUNT(*) FROM visitors v {where}", tuple(params)
            ).fetchone()[0]
        )
        rows = self.conn.execute(
            f"""
            SELECT v.visitor_id,v.fingerprint_hmac,v.first_seen,v.last_seen,v.seen_count,
                   v.client_meta_json,
                   COUNT(DISTINCT s.session_id) AS session_count,
                   (SELECT COUNT(*) FROM conversation_index c
                    WHERE c.visitor_id=v.visitor_id) AS conversation_count,
                   (SELECT COALESCE(SUM(c.message_count),0) FROM conversation_index c
                    WHERE c.visitor_id=v.visitor_id) AS message_count,
                   (SELECT ce.ip_address FROM connection_events ce
                    WHERE ce.visitor_id=v.visitor_id
                    ORDER BY ce.observed_at DESC LIMIT 1) AS recent_ip,
                   (SELECT COUNT(DISTINCT ce.fingerprint_hmac) FROM connection_events ce
                    WHERE ce.visitor_id=v.visitor_id) AS device_count
            FROM visitors v
            LEFT JOIN visitor_sessions s ON s.visitor_id=v.visitor_id
            LEFT JOIN conversation_index c ON c.visitor_id=v.visitor_id
            {where}
            GROUP BY v.visitor_id
            ORDER BY v.last_seen DESC,v.visitor_id ASC LIMIT ? OFFSET ?
            """,
            (*params, int(limit), int(offset)),
        ).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["client_meta"] = json_loads(item.pop("client_meta_json"), {})
            items.append(item)
        return {"items": items, "total": total}

    def telemetry_summary(self, visitor_ids: list[str]) -> dict[str, Any]:
        clean_ids = list(dict.fromkeys(value for value in visitor_ids if value))[:200]
        if not clean_ids:
            return {"recent_ip": None, "device_count": 0}
        placeholders = ",".join("?" for _ in clean_ids)
        recent = self.conn.execute(
            f"""
            SELECT ip_address FROM connection_events
            WHERE visitor_id IN ({placeholders})
            ORDER BY observed_at DESC LIMIT 1
            """,
            tuple(clean_ids),
        ).fetchone()
        devices = int(
            self.conn.execute(
                f"""
                SELECT COUNT(DISTINCT fingerprint_hmac) FROM connection_events
                WHERE visitor_id IN ({placeholders})
                """,
                tuple(clean_ids),
            ).fetchone()[0]
        )
        return {
            "recent_ip": recent["ip_address"] if recent is not None else None,
            "device_count": devices,
        }

    def visitor_admin_detail(
        self, visitor_id: str, *, nested_limit: int = 200
    ) -> dict[str, Any] | None:
        cap = max(1, min(int(nested_limit), 200))
        row = self.conn.execute(
            "SELECT * FROM visitors WHERE visitor_id=?", ((visitor_id or "").strip(),)
        ).fetchone()
        if row is None:
            return None
        visitor = dict(row)
        visitor["client_meta"] = json_loads(visitor.pop("client_meta_json"), {})
        session_rows = self.conn.execute(
            """
            SELECT session_id,created_at,last_seen,client_meta_json
            FROM visitor_sessions WHERE visitor_id=?
            ORDER BY last_seen DESC LIMIT ?
            """,
            (visitor_id, cap),
        ).fetchall()
        sessions = []
        for session in session_rows:
            item = dict(session)
            item["client_meta"] = json_loads(item.pop("client_meta_json"), {})
            sessions.append(item)
        connections = [
            dict(item)
            for item in self.conn.execute(
                """
                SELECT connection_id,visitor_id,session_id,ip_address,user_agent,browser,
                       platform,device,language,fingerprint_hmac,observed_at
                FROM connection_events WHERE visitor_id=?
                ORDER BY observed_at DESC LIMIT ?
                """,
                (visitor_id, cap),
            ).fetchall()
        ]
        conversations = self.list_conversations_for_visitor(visitor_id, limit=cap)
        usage_rows = self.conn.execute(
            """
            SELECT event_id,visitor_id,conversation_id,request_id,event_type,route,model,
                   research_status,evidence_count,status,created_at,metadata_json
            FROM usage_events WHERE visitor_id=?
            ORDER BY created_at DESC LIMIT ?
            """,
            (visitor_id, cap),
        ).fetchall()
        usage = []
        for event in usage_rows:
            item = dict(event)
            stored_metadata = json_loads(item.pop("metadata_json"), {})
            safe_metadata = _safe_usage_metadata(stored_metadata)
            item["metadata"] = safe_metadata if isinstance(safe_metadata, dict) else {}
            usage.append(item)
        return {
            "visitor": visitor,
            "sessions": sessions,
            "connections": connections,
            "conversations": conversations,
            "usage_events": usage,
        }

    def visitor_detail(self, visitor_id: str, *, conv_limit: int = 50) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM visitors WHERE visitor_id=?",
            (visitor_id,),
        ).fetchone()
        if row is None:
            return None
        data = dict(row)
        data["client_meta"] = json_loads(data.pop("client_meta_json"), {})
        data["conversations"] = self.list_conversations_for_visitor(
            visitor_id, limit=max(1, min(int(conv_limit), 200))
        )
        return data

    def list_recent_conversations(self, *, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT conversation_id,visitor_id,title,created_at,updated_at,last_route,last_model,
                   research_status,message_count
            FROM conversation_index
            ORDER BY updated_at DESC
            LIMIT ? OFFSET ?
            """,
            (max(1, min(int(limit), 500)), max(0, int(offset))),
        ).fetchall()
        return [dict(r) for r in rows]
