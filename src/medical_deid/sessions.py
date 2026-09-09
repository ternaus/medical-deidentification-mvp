"""Persistent, local-only processing sessions."""

import shutil
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


@dataclass(frozen=True)
class SessionRecord:
    """State exposed by the local session API."""

    id: str
    source_filename: str
    status: str
    stage: str
    created_at: str
    updated_at: str
    error_message: str | None
    result_available: bool
    feedback_submitted: bool


class SessionNotFoundError(LookupError):
    """Raised when a requested session no longer exists."""


class SessionRepository:
    """Store session metadata in SQLite and artifacts in one exact directory."""

    def __init__(self, database_path: Path, sessions_dir: Path) -> None:
        self._database_path = database_path
        self._sessions_dir = sessions_dir

    def initialize(self) -> None:
        """Create storage and migrate the small local schema when needed."""
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        self._sessions_dir.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    source_filename TEXT NOT NULL,
                    status TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    error_message TEXT
                )
                """
            )
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(sessions)").fetchall()
            }
            if "updated_at" not in columns:
                connection.execute("ALTER TABLE sessions ADD COLUMN updated_at TEXT")
                connection.execute("UPDATE sessions SET updated_at = created_at")
            if "error_message" not in columns:
                connection.execute("ALTER TABLE sessions ADD COLUMN error_message TEXT")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS feedback (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    text TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

    def create(self, source_filename: str, suffix: str, content: bytes) -> SessionRecord:
        """Persist a queued session and its immutable source upload."""
        session_id = str(uuid4())
        now = self._now()
        artifact_dir = self.session_dir(session_id)
        artifact_dir.mkdir(parents=True, exist_ok=False)
        self.source_path(session_id, suffix).write_bytes(content)

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO sessions (
                    id, source_filename, status, stage, created_at, updated_at, error_message
                ) VALUES (?, ?, 'queued', 'queued', ?, ?, NULL)
                """,
                (session_id, source_filename, now, now),
            )

        return self.get(session_id)

    def get(self, session_id: str) -> SessionRecord:
        """Return one session or raise a public 404-friendly error."""
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, source_filename, status, stage, created_at, updated_at, error_message
                FROM sessions
                WHERE id = ?
                """,
                (session_id,),
            ).fetchone()
            if row is None:
                raise SessionNotFoundError(session_id)
            feedback_submitted = bool(
                connection.execute(
                    "SELECT 1 FROM feedback WHERE session_id = ? LIMIT 1", (session_id,)
                ).fetchone()
            )

        return SessionRecord(
            *row,
            result_available=self.result_path(session_id).is_file(),
            feedback_submitted=feedback_submitted,
        )

    def list_recent(self, limit: int = 10) -> list[SessionRecord]:
        """Return the ten newest sessions without document content."""
        with self._connect() as connection:
            ids = [
                row[0]
                for row in connection.execute(
                    "SELECT id FROM sessions ORDER BY created_at DESC LIMIT ?", (limit,)
                ).fetchall()
            ]
        return [self.get(session_id) for session_id in ids]

    def list_unfinished(self) -> list[str]:
        """Return sessions that need recovery after a local app restart."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id FROM sessions WHERE status IN ('queued', 'running')"
            ).fetchall()
        return [row[0] for row in rows]

    def update_status(
        self,
        session_id: str,
        *,
        status: str,
        stage: str,
        error_message: str | None = None,
    ) -> SessionRecord:
        """Atomically persist a content-free lifecycle transition."""
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE sessions
                SET status = ?, stage = ?, updated_at = ?, error_message = ?
                WHERE id = ?
                """,
                (status, stage, self._now(), error_message, session_id),
            )
            if cursor.rowcount != 1:
                raise SessionNotFoundError(session_id)
        return self.get(session_id)

    def save_feedback(self, session_id: str, text: str) -> None:
        """Store user feedback before acknowledging it to the browser."""
        self.get(session_id)
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO feedback (id, session_id, text, created_at) VALUES (?, ?, ?, ?)",
                (str(uuid4()), session_id, text, self._now()),
            )

    def delete(self, session_id: str) -> None:
        """Delete precisely one completed or failed local session."""
        record = self.get(session_id)
        if record.status == "running":
            raise ValueError("A document being processed cannot be deleted yet.")
        artifact_dir = self.session_dir(session_id)
        with self._connect() as connection:
            connection.execute("DELETE FROM feedback WHERE session_id = ?", (session_id,))
            connection.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        if artifact_dir.exists():
            shutil.rmtree(artifact_dir)

    def session_dir(self, session_id: str) -> Path:
        """Return the only artifact directory owned by this session."""
        return self._sessions_dir / session_id

    def source_path(self, session_id: str, suffix: str | None = None) -> Path:
        """Resolve an existing source file or construct its initial destination."""
        artifact_dir = self.session_dir(session_id)
        if suffix is not None:
            return artifact_dir / f"source{suffix}"
        matches = list(artifact_dir.glob("source.*"))
        if len(matches) != 1:
            raise SessionNotFoundError(session_id)
        return matches[0]

    def result_path(self, session_id: str) -> Path:
        """Return the fixed reconstructed-PDF location for a session."""
        return self.session_dir(session_id) / "anonymized.pdf"

    def work_dir(self, session_id: str) -> Path:
        """Return the private temporary directory for one processing attempt."""
        return self.session_dir(session_id) / "work"

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @staticmethod
    def _now() -> str:
        return datetime.now(tz=UTC).isoformat()
