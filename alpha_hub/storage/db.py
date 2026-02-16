from __future__ import annotations

import json
import os
import sqlite3
import threading
from dataclasses import dataclass, field
from typing import Optional, Any

from ..common.time_util import utc_now_iso

def _default_db_path() -> str:
    return os.getenv("ALPHA_HUB_DB_PATH", "data/alpha_hub.db")



SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS messages (
  message_id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL,
  role TEXT NOT NULL,
  content_text TEXT NOT NULL,
  created_at_utc TEXT NOT NULL,
  client_request_id TEXT,
  attachments_json TEXT NOT NULL DEFAULT '[]'
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_idempotent
ON messages(conversation_id, client_request_id)
WHERE client_request_id IS NOT NULL;
"""


@dataclass
class MessageRow:
    message_id: str
    conversation_id: str
    role: str
    content_text: str
    created_at_utc: str
    client_request_id: Optional[str] = None
    attachments: list[dict[str, Any]] = field(default_factory=list)


class SqliteStore:
    """v0 storage: SQLite (single connection + explicit close).

    Why:
    - TestClient uses threads; we guard with a lock
    - Single connection avoids ResourceWarning surprises in some environments
    """

    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path or _default_db_path()
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()
            self._ensure_migrations()

    def _ensure_migrations(self) -> None:
        """Lightweight migrations for older databases."""
        cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(messages)").fetchall()}
        if "attachments_json" not in cols:
            self._conn.execute("ALTER TABLE messages ADD COLUMN attachments_json TEXT NOT NULL DEFAULT '[]'")
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass

    def _row_to_message(self, row: sqlite3.Row) -> MessageRow:
        try:
            att = json.loads(row["attachments_json"] or "[]")
            if not isinstance(att, list):
                att = []
        except Exception:
            att = []
        return MessageRow(
            message_id=row["message_id"],
            conversation_id=row["conversation_id"],
            role=row["role"],
            content_text=row["content_text"],
            created_at_utc=row["created_at_utc"],
            client_request_id=row["client_request_id"],
            attachments=att,
        )

    def get_message(self, message_id: str) -> Optional[MessageRow]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM messages WHERE message_id=?", (message_id,)).fetchone()
        if not row:
            return None
        return self._row_to_message(row)

    def create_message(
        self,
        *,
        message_id: str,
        conversation_id: str,
        role: str,
        content_text: str,
        client_request_id: Optional[str],
        attachments: Optional[list[dict[str, Any]]] = None,
    ) -> MessageRow:
        created_at_utc = utc_now_iso()
        attachments = attachments or []
        attachments_json = json.dumps(attachments, ensure_ascii=False)

        with self._lock:
            if client_request_id:
                row = self._conn.execute(
                    """
                    SELECT * FROM messages
                    WHERE conversation_id=? AND client_request_id=?
                    """,
                    (conversation_id, client_request_id),
                ).fetchone()
                if row:
                    return self._row_to_message(row)

            self._conn.execute(
                """
                INSERT INTO messages(message_id, conversation_id, role, content_text, created_at_utc, client_request_id, attachments_json)
                VALUES (?,?,?,?,?,?,?)
                """,
                (message_id, conversation_id, role, content_text, created_at_utc, client_request_id, attachments_json),
            )
            self._conn.commit()

        return MessageRow(
            message_id=message_id,
            conversation_id=conversation_id,
            role=role,
            content_text=content_text,
            created_at_utc=created_at_utc,
            client_request_id=client_request_id,
            attachments=attachments,
        )

    def list_messages(
        self,
        conversation_id: str,
        *,
        limit: Optional[int] = None,
        before_created_at_utc: Optional[str] = None,
    ) -> list[MessageRow]:
        """List messages in a conversation.

        - If limit is provided, returns the most recent N messages.
        - If before_created_at_utc is provided, only returns messages earlier than that timestamp.
        """
        params: list[Any] = [conversation_id]
        where = "WHERE conversation_id=?"
        if before_created_at_utc:
            where += " AND created_at_utc < ?"
            params.append(before_created_at_utc)

        if limit is None:
            sql = f"SELECT * FROM messages {where} ORDER BY created_at_utc ASC"
            with self._lock:
                rows = self._conn.execute(sql, tuple(params)).fetchall()
            return [self._row_to_message(r) for r in rows]

        # newest first then reverse
        sql = f"SELECT * FROM messages {where} ORDER BY created_at_utc DESC LIMIT ?"
        params.append(int(limit))
        with self._lock:
            rows = self._conn.execute(sql, tuple(params)).fetchall()
        msgs = [self._row_to_message(r) for r in rows]
        msgs.reverse()
        return msgs