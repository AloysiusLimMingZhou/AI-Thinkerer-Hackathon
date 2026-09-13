from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from .models import (
    Citation,
    ContextNoteCreate,
    ContextNoteView,
    IntegrationView,
    MinutesView,
    Provider,
    SessionCreate,
    SessionStatus,
    SessionView,
    TranscriptEntry,
    UtteranceCreate,
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class SQLiteRepository:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    owner_name TEXT NOT NULL,
                    agent_name TEXT NOT NULL,
                    meeting_url TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS context_notes (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    source TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS transcript (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    speaker TEXT NOT NULL,
                    text TEXT NOT NULL,
                    is_final INTEGER NOT NULL,
                    spoken_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS qa_log (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    question TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    citations_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS minutes (
                    session_id TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
                    content TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS oauth_states (
                    state TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    code_verifier TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS integrations (
                    provider TEXT PRIMARY KEY,
                    encrypted_credentials TEXT NOT NULL,
                    account_id TEXT,
                    account_label TEXT,
                    scopes_json TEXT NOT NULL,
                    connected_at TEXT NOT NULL
                );
                """
            )

    @staticmethod
    def _session_from_row(row: sqlite3.Row) -> SessionView:
        return SessionView(
            id=row["id"],
            title=row["title"],
            owner_name=row["owner_name"],
            agent_name=row["agent_name"],
            meeting_url=row["meeting_url"],
            status=row["status"],
            created_at=row["created_at"],
        )

    def create_session(self, payload: SessionCreate) -> SessionView:
        session_id = str(uuid4())
        created_at = _now_iso()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO sessions
                    (id, title, owner_name, agent_name, meeting_url, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    payload.title,
                    payload.owner_name,
                    payload.agent_name,
                    payload.meeting_url,
                    SessionStatus.CREATED,
                    created_at,
                ),
            )
        session = self.get_session(session_id)
        assert session is not None
        return session

    def get_session(self, session_id: str) -> SessionView | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
        return self._session_from_row(row) if row else None

    def list_sessions(self) -> list[SessionView]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM sessions ORDER BY created_at DESC"
            ).fetchall()
        return [self._session_from_row(row) for row in rows]

    def add_context(
        self, session_id: str, notes: list[ContextNoteCreate]
    ) -> list[ContextNoteView]:
        created: list[ContextNoteView] = []
        with self._connect() as connection:
            for note in notes:
                note_id = str(uuid4())
                created_at = _now_iso()
                connection.execute(
                    """
                    INSERT INTO context_notes
                        (id, session_id, source, title, content, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        note_id,
                        session_id,
                        note.source,
                        note.title,
                        note.content,
                        created_at,
                    ),
                )
                created.append(
                    ContextNoteView(
                        id=note_id,
                        source=note.source,
                        title=note.title,
                        content=note.content,
                        created_at=created_at,
                    )
                )
        return created

    def get_context(self, session_id: str) -> list[ContextNoteView]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, source, title, content, created_at
                FROM context_notes WHERE session_id = ? ORDER BY created_at
                """,
                (session_id,),
            ).fetchall()
        return [ContextNoteView(**dict(row)) for row in rows]

    def add_transcript(
        self, session_id: str, utterance: UtteranceCreate
    ) -> TranscriptEntry:
        entry_id = str(uuid4())
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO transcript
                    (id, session_id, speaker, text, is_final, spoken_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    entry_id,
                    session_id,
                    utterance.speaker,
                    utterance.text,
                    int(utterance.is_final),
                    utterance.spoken_at.isoformat(),
                ),
            )
        return TranscriptEntry(
            id=entry_id,
            speaker=utterance.speaker,
            text=utterance.text,
            is_final=utterance.is_final,
            spoken_at=utterance.spoken_at,
        )

    def get_transcript(self, session_id: str) -> list[TranscriptEntry]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, speaker, text, is_final, spoken_at
                FROM transcript WHERE session_id = ? ORDER BY spoken_at, rowid
                """,
                (session_id,),
            ).fetchall()
        return [
            TranscriptEntry(
                id=row["id"],
                speaker=row["speaker"],
                text=row["text"],
                is_final=bool(row["is_final"]),
                spoken_at=row["spoken_at"],
            )
            for row in rows
        ]

    def add_qa(
        self,
        session_id: str,
        question: str,
        answer: str,
        citations: list[Citation],
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO qa_log
                    (id, session_id, question, answer, citations_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid4()),
                    session_id,
                    question,
                    answer,
                    json.dumps(
                        [citation.model_dump(mode="json") for citation in citations]
                    ),
                    _now_iso(),
                ),
            )

    def get_qa_log(self, session_id: str) -> list[dict[str, object]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT question, answer, citations_json, created_at
                FROM qa_log WHERE session_id = ? ORDER BY created_at
                """,
                (session_id,),
            ).fetchall()
        return [
            {
                "question": row["question"],
                "answer": row["answer"],
                "citations": json.loads(row["citations_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def save_minutes(self, session_id: str, content: str) -> MinutesView:
        updated_at = _now_iso()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO minutes (session_id, content, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    content = excluded.content,
                    updated_at = excluded.updated_at
                """,
                (session_id, content, updated_at),
            )
        return MinutesView(
            session_id=session_id, content=content, updated_at=updated_at
        )

    def get_minutes(self, session_id: str) -> MinutesView | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM minutes WHERE session_id = ?", (session_id,)
            ).fetchone()
        return MinutesView(**dict(row)) if row else None

    def record_event(
        self, session_id: str, event_type: str, payload: dict[str, object]
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO events (session_id, event_type, payload_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, event_type, json.dumps(payload, default=str), _now_iso()),
            )

    def get_events(self, session_id: str, after: int = 0) -> list[dict[str, object]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT sequence, event_type, payload_json, created_at
                FROM events
                WHERE session_id = ? AND sequence > ?
                ORDER BY sequence
                """,
                (session_id, after),
            ).fetchall()
        return [
            {
                "sequence": row["sequence"],
                "type": row["event_type"],
                "payload": json.loads(row["payload_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def create_oauth_state(
        self, state: str, provider: Provider, code_verifier: str | None
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM oauth_states WHERE created_at < ?",
                ((datetime.now(UTC).timestamp() - 600),),
            )
            connection.execute(
                """
                INSERT INTO oauth_states (state, provider, code_verifier, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (state, provider, code_verifier, str(datetime.now(UTC).timestamp())),
            )

    def consume_oauth_state(
        self, state: str, provider: Provider, max_age_seconds: int = 600
    ) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT provider, code_verifier, created_at FROM oauth_states WHERE state = ?",
                (state,),
            ).fetchone()
            connection.execute("DELETE FROM oauth_states WHERE state = ?", (state,))
        if row is None or row["provider"] != provider:
            raise ValueError("Invalid OAuth state")
        age = datetime.now(UTC).timestamp() - float(row["created_at"])
        if age > max_age_seconds:
            raise ValueError("OAuth state expired")
        return row["code_verifier"]

    def save_integration(
        self,
        provider: Provider,
        encrypted_credentials: str,
        *,
        account_id: str | None,
        account_label: str | None,
        scopes: list[str],
    ) -> IntegrationView:
        connected_at = _now_iso()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO integrations
                    (provider, encrypted_credentials, account_id, account_label,
                     scopes_json, connected_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider) DO UPDATE SET
                    encrypted_credentials = excluded.encrypted_credentials,
                    account_id = excluded.account_id,
                    account_label = excluded.account_label,
                    scopes_json = excluded.scopes_json,
                    connected_at = excluded.connected_at
                """,
                (
                    provider,
                    encrypted_credentials,
                    account_id,
                    account_label,
                    json.dumps(scopes),
                    connected_at,
                ),
            )
        return IntegrationView(
            provider=provider,
            connected=True,
            configured=True,
            account_id=account_id,
            account_label=account_label,
            scopes=scopes,
            connected_at=connected_at,
        )

    def get_encrypted_credentials(self, provider: Provider) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT encrypted_credentials FROM integrations WHERE provider = ?",
                (provider,),
            ).fetchone()
        return row["encrypted_credentials"] if row else None

    def get_integration(self, provider: Provider) -> IntegrationView | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT provider, account_id, account_label, scopes_json, connected_at
                FROM integrations WHERE provider = ?
                """,
                (provider,),
            ).fetchone()
        if row is None:
            return None
        return IntegrationView(
            provider=row["provider"],
            connected=True,
            configured=True,
            account_id=row["account_id"],
            account_label=row["account_label"],
            scopes=json.loads(row["scopes_json"]),
            connected_at=row["connected_at"],
        )

    def delete_integration(self, provider: Provider) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM integrations WHERE provider = ?", (provider,)
            )
        return cursor.rowcount > 0
