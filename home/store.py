"""Durable state: rooms, messages, artifacts, Council rounds, turns and saved sessions.

One SQLite file per data root, guarded by an OS file lock so only one server uses it.
All writes run inside BEGIN IMMEDIATE transactions on one connection behind a lock.

Public (HTTP-facing) operations return JSON-serializable dictionaries:
    create_room, list_rooms, room, save_artifact.

Internal operations used by home/council.py (no SQL outside this module):
    session(room_id, agent_id)            saved provider session for direct talk
    create_round(...)                     validate + persist request, owner message,
                                          participants, frozen context and first turns
    round(round_id), round_context(round_id)
    mark_round_running / finish_round     queued->running, running->terminal
    cancel_round(round_id)                owner Stop; queued turns become cancelled
    reactivate_round(round_id)            owner Resume of an interrupted/cancelled round
    ensure_turn / requeue_turn / claim_turn / end_turn / complete_turn
    recover_unfinished()                  startup: unfinished work -> interrupted

Resident registry (used by home/council.py, which owns adapters and locking):
    residents()                           every registered resident, archived included
    seed_residents(rows)                  insert configured rows once per ID; never
                                          overwrites edits or revives archived rows
    add_resident / set_resident_archived  stable IDs; home slots kept on archive
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import threading
import uuid
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO

from .models import (
    MAX_ARTIFACT_BYTES,
    MAX_ARTIFACTS_PER_ROUND,
    MAX_CONTEXT_BYTES,
    MAX_RESIDENTS,
    MAX_TITLE_CHARS,
    ConflictError,
    NotFoundError,
    Reply,
    StoreLockedError,
    UnsupportedSchemaError,
    ValidationError,
    utf8_len,
)

SCHEMA_VERSION = 3

ROUND_STATES = ("queued", "running", "completed", "failed", "cancelled", "interrupted")
ACTIVE_STATES = ("queued", "running")
PHASES = ("reply", "proposal", "critique", "synthesis")
HISTORY_LIMIT = 200
ROOM_ROUND_LIMIT = 50
ARTIFACT_PAGE_LIMIT = 100
ROOM_PAGE_LIMIT = 100

_STATES_SQL = ",".join(f"'{s}'" for s in ROUND_STATES)
_PHASES_SQL = ",".join(f"'{p}'" for p in PHASES)

# Each entry upgrades from version N-1 to N. Never edit a released entry; append.
MIGRATIONS: dict[int, str] = {
    1: f"""
CREATE TABLE rooms (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE messages (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    room_id TEXT NOT NULL REFERENCES rooms(id),
    round_id TEXT,
    role TEXT NOT NULL CHECK (role IN ('owner', 'agent', 'system')),
    agent_id TEXT,
    phase TEXT,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX messages_by_room ON messages(room_id, seq);
CREATE TABLE artifacts (
    id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL REFERENCES rooms(id),
    created_at TEXT NOT NULL
);
CREATE TABLE artifact_versions (
    artifact_id TEXT NOT NULL REFERENCES artifacts(id),
    version INTEGER NOT NULL CHECK (version >= 1),
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (artifact_id, version)
);
CREATE TABLE rounds (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    room_id TEXT NOT NULL REFERENCES rooms(id),
    request_id TEXT NOT NULL UNIQUE,
    request_sha256 TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('direct', 'council')),
    status TEXT NOT NULL CHECK (status IN ({_STATES_SQL})),
    active_room TEXT UNIQUE,
    participants TEXT NOT NULL,
    artifacts TEXT NOT NULL,
    context TEXT NOT NULL,
    context_sha256 TEXT NOT NULL,
    owner_message_id TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK ((active_room IS NOT NULL) = (status IN ('queued', 'running')))
);
CREATE TABLE turns (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    round_id TEXT NOT NULL REFERENCES rounds(id),
    agent_id TEXT NOT NULL,
    phase TEXT NOT NULL CHECK (phase IN ({_PHASES_SQL})),
    status TEXT NOT NULL CHECK (status IN ({_STATES_SQL})),
    launched INTEGER NOT NULL DEFAULT 0 CHECK (launched IN (0, 1)),
    content TEXT,
    error TEXT,
    provider TEXT,
    session_id TEXT,
    model TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (round_id, agent_id, phase)
);
CREATE UNIQUE INDEX one_synthesis_per_round ON turns(round_id) WHERE phase = 'synthesis';
CREATE TABLE sessions (
    room_id TEXT NOT NULL REFERENCES rooms(id),
    agent_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    session_id TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (room_id, agent_id)
);
""",
    2: f"""
CREATE TABLE residents (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    provider TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT '',
    binding_id TEXT NOT NULL,
    home_slot INTEGER NOT NULL CHECK (home_slot BETWEEN 0 AND {MAX_RESIDENTS - 1}),
    archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX one_active_resident_per_slot ON residents(home_slot) WHERE archived = 0;
ALTER TABLE rounds ADD COLUMN participant_snapshots TEXT NOT NULL DEFAULT '{{}}';
ALTER TABLE messages ADD COLUMN agent_name TEXT;
ALTER TABLE messages ADD COLUMN agent_provider TEXT;
""",
    3: """
CREATE INDEX rounds_by_room ON rounds(room_id, seq);
CREATE INDEX artifacts_by_room ON artifacts(room_id, created_at, id);
""",
}

ContextBuilder = Callable[[list[dict[str, Any]], int, list[dict[str, Any]], str], str]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _new_id() -> str:
    return uuid.uuid4().hex


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _lock_file(handle: BinaryIO) -> None:
    if sys.platform == "win32":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_file(handle: BinaryIO) -> None:
    if sys.platform == "win32":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _check_title(title: Any, what: str) -> str:
    if not isinstance(title, str) or not title.strip():
        raise ValidationError(f"{what} title must be non-empty text")
    title = title.strip()
    if len(title) > MAX_TITLE_CHARS:
        raise ValidationError(f"{what} title is over {MAX_TITLE_CHARS} characters")
    return title


class Store:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._guard = threading.RLock()
        self._lock_files = ExitStack()
        self._lock_handle: BinaryIO | None = self._lock_files.enter_context(
            os.fdopen(os.open(self.path.with_name(self.path.name + ".lock"),
                              os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o600), "a+b"))
        try:
            _lock_file(self._lock_handle)
        except OSError:
            self._lock_files.close()
            self._lock_handle = None
            raise StoreLockedError("Another KiFoundry Home server is already using this data root")
        try:
            # Reserve a new database with owner-only POSIX permissions before SQLite
            # opens it. Existing roots/files keep their permissions and contents.
            try:
                descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                pass
            else:
                os.close(descriptor)
            self._db = sqlite3.connect(
                str(self.path), isolation_level=None, check_same_thread=False, timeout=10
            )
            self._db.row_factory = sqlite3.Row
            self._migrate()
            self._db.execute("PRAGMA foreign_keys = ON")
            self._db.execute("PRAGMA journal_mode = WAL")
        except BaseException:
            self._release_lock()
            raise

    # ----- lifecycle -------------------------------------------------------------------

    def _migrate(self) -> None:
        version = self._db.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            self._db.close()
            raise UnsupportedSchemaError(
                f"Database schema {version} is newer than supported {SCHEMA_VERSION}; refusing to change it"
            )
        if version == 0:
            tables = self._db.execute("SELECT count(*) FROM sqlite_master").fetchone()[0]
            if tables:
                self._db.close()
                raise UnsupportedSchemaError("Database has unknown tables and no schema version; refusing to change it")
        for target in range(version + 1, SCHEMA_VERSION + 1):
            try:
                self._db.executescript(
                    f"BEGIN IMMEDIATE;\n{MIGRATIONS[target]}\nPRAGMA user_version = {target};\nCOMMIT;"
                )
            except BaseException:
                if self._db.in_transaction:
                    self._db.execute("ROLLBACK")
                raise

    def _release_lock(self) -> None:
        if self._lock_handle is not None:
            try:
                _unlock_file(self._lock_handle)
            except OSError:
                pass
            self._lock_files.close()
            self._lock_handle = None

    def close(self) -> None:
        with self._guard:
            try:
                self._db.close()
            finally:
                self._release_lock()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._guard:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                yield self._db
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
            self._db.execute("COMMIT")

    def _read(self, sql: str, args: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with self._guard:
            return self._db.execute(sql, args).fetchall()

    # ----- rooms and messages ----------------------------------------------------------

    def create_room(self, title: str = "Commons") -> dict[str, Any]:
        title = _check_title(title, "Room")
        room = {"id": _new_id(), "title": title, "created_at": _now()}
        with self._tx() as db:
            db.execute("INSERT INTO rooms (id, title, created_at) VALUES (?, ?, ?)",
                       (room["id"], room["title"], room["created_at"]))
        return room

    def list_rooms(self) -> list[dict[str, Any]]:
        rows = self._read(
            "SELECT r.id, r.title, r.created_at, "
            "(SELECT id FROM rounds WHERE active_room = r.id) AS active_round_id "
            "FROM rooms r ORDER BY r.created_at, r.id"
        )
        return [dict(row) for row in rows]

    def list_rooms_page(self, before: int | None = None) -> dict[str, Any]:
        """Bounded browser list. The full integration list remains available separately."""
        if before is not None and (type(before) is not int or not 1 <= before <= 2**63 - 1):
            raise ValidationError("Invalid conversation history cursor")
        rows = self._read(
            "SELECT r.rowid AS cursor, r.id, r.title, r.created_at, "
            "(SELECT id FROM rounds WHERE active_room = r.id) AS active_round_id FROM rooms r " +
            ("WHERE r.rowid < ? " if before is not None else "") +
            "ORDER BY r.rowid DESC LIMIT ?",
            (before, ROOM_PAGE_LIMIT + 1) if before is not None else (ROOM_PAGE_LIMIT + 1,),
        )
        page = rows[:ROOM_PAGE_LIMIT]
        return {"rooms": [{key: row[key] for key in ("id", "title", "created_at", "active_round_id")}
                          for row in page],
                "next_room_cursor": str(page[-1]["cursor"]) if len(rows) > ROOM_PAGE_LIMIT else None}

    def room(self, room_id: str, message_limit: int = HISTORY_LIMIT) -> dict[str, Any]:
        """Trusted full readback, including immutable artifact bodies."""
        return self._room(room_id, message_limit, for_browser=False)

    def room_for_browser(self, room_id: str) -> dict[str, Any]:
        """Bounded history and version metadata; draft bodies are fetched on selection."""
        return self._room(room_id, HISTORY_LIMIT, for_browser=True)

    def _room(self, room_id: str, message_limit: int, *, for_browser: bool) -> dict[str, Any]:
        with self._guard:
            row = self._db.execute("SELECT id, title, created_at FROM rooms WHERE id = ?", (room_id,)).fetchone()
            if row is None:
                raise NotFoundError("Room not found")
            total = self._db.execute("SELECT count(*) FROM messages WHERE room_id = ?", (room_id,)).fetchone()[0]
            messages = self._db.execute(
                "SELECT * FROM (SELECT * FROM messages WHERE room_id = ? ORDER BY seq DESC LIMIT ?) ORDER BY seq",
                (room_id, message_limit),
            ).fetchall()
            round_ids = self._db.execute(
                "SELECT id FROM (SELECT id, seq FROM rounds WHERE room_id = ? ORDER BY seq DESC LIMIT ?) ORDER BY seq",
                (room_id, ROOM_ROUND_LIMIT),
            ).fetchall()
            return {
                **dict(row),
                "messages": [self._message_dict(m) for m in messages],
                "earlier_messages": max(0, total - len(messages)),
                "rounds": [self._round_dict(self._db, r["id"], for_browser=for_browser) for r in round_ids],
                **(self.artifact_page(room_id) if for_browser else {"artifacts": self._artifacts(self._db, room_id)}),
            }

    @staticmethod
    def _message_dict(row: sqlite3.Row) -> dict[str, Any]:
        # agent_name/agent_provider are the speaker as saved when the reply arrived; rows
        # written before schema 2 keep None rather than a reconstructed identity.
        return {k: row[k] for k in ("id", "role", "agent_id", "agent_name", "agent_provider", "phase",
                                    "content", "round_id", "created_at")}

    @staticmethod
    def _insert_message(db: sqlite3.Connection, room_id: str, role: str, content: str,
                        round_id: str | None = None, agent_id: str | None = None,
                        phase: str | None = None, agent_name: str | None = None,
                        agent_provider: str | None = None) -> str:
        message_id = _new_id()
        db.execute(
            "INSERT INTO messages (id, room_id, round_id, role, agent_id, agent_name, agent_provider, phase, "
            "content, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (message_id, room_id, round_id, role, agent_id, agent_name, agent_provider, phase, content, _now()),
        )
        return message_id

    def _require_room(self, db: sqlite3.Connection, room_id: str) -> None:
        if db.execute("SELECT 1 FROM rooms WHERE id = ?", (room_id,)).fetchone() is None:
            raise NotFoundError("Room not found")

    # ----- artifacts -------------------------------------------------------------------

    @staticmethod
    def _version_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {"id": row["artifact_id"], "title": row["title"], "version": row["version"],
                "content": row["content"], "sha256": row["sha256"], "created_at": row["created_at"]}

    def _artifacts(self, db: sqlite3.Connection, room_id: str) -> list[dict[str, Any]]:
        rows = db.execute(
            "SELECT v.* FROM artifact_versions v JOIN artifacts a ON a.id = v.artifact_id "
            "WHERE a.room_id = ? ORDER BY a.created_at, a.id, v.version",
            (room_id,),
        ).fetchall()
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(row["artifact_id"], []).append(self._version_dict(row))
        # Latest version fields at the top level, every immutable version for comparison.
        return [{**versions[-1], "versions": versions} for versions in grouped.values()]

    def artifact_page(self, room_id: str, before: int | None = None) -> dict[str, Any]:
        """Latest version metadata, ordered by insertion, without reading draft bodies."""
        if before is not None and (type(before) is not int or not 1 <= before <= 2**63 - 1):
            raise ValidationError("Invalid artifact history cursor")
        with self._guard:
            self._require_room(self._db, room_id)
            rows = self._db.execute(
                "SELECT v.rowid AS cursor, v.artifact_id, v.title, v.version, v.sha256, v.created_at, "
                "(SELECT max(newest.version) FROM artifact_versions newest WHERE newest.artifact_id = v.artifact_id) AS latest_version "
                "FROM artifact_versions v JOIN artifacts a ON a.id = v.artifact_id "
                "WHERE a.room_id = ? " + ("AND v.rowid < ? " if before is not None else "") +
                "ORDER BY v.rowid DESC LIMIT ?",
                (room_id, before, ARTIFACT_PAGE_LIMIT + 1) if before is not None else
                (room_id, ARTIFACT_PAGE_LIMIT + 1),
            ).fetchall()
            page = rows[:ARTIFACT_PAGE_LIMIT]
            return {
                "artifacts": [{"id": row["artifact_id"], **{key: row[key] for key in
                              ("title", "version", "sha256", "created_at", "latest_version")}} for row in page],
                "next_artifact_cursor": str(page[-1]["cursor"]) if len(rows) > ARTIFACT_PAGE_LIMIT else None,
            }

    def artifact_version(self, room_id: str, artifact_id: str, version: int) -> dict[str, Any]:
        """One exact immutable body, only within its owning room."""
        if type(version) is not int or not 1 <= version <= 2**63 - 1:
            raise ValidationError("Invalid artifact version")
        rows = self._read(
            "SELECT v.*, (SELECT max(newest.version) FROM artifact_versions newest "
            "WHERE newest.artifact_id = v.artifact_id) AS latest_version "
            "FROM artifact_versions v JOIN artifacts a ON a.id = v.artifact_id "
            "WHERE a.room_id = ? AND v.artifact_id = ? AND v.version = ?",
            (room_id, artifact_id, version),
        )
        if not rows:
            raise NotFoundError("Artifact version not found in this room")
        return {**self._version_dict(rows[0]), "latest_version": rows[0]["latest_version"]}

    def save_artifact(self, room_id: str, title: str, content: str,
                      artifact_id: str | None = None, expected_version: int | None = None) -> dict[str, Any]:
        title = _check_title(title, "Artifact")
        if not isinstance(content, str):
            raise ValidationError("Artifact content must be text")
        if utf8_len(content) > MAX_ARTIFACT_BYTES:
            raise ValidationError(f"Artifact is over {MAX_ARTIFACT_BYTES // 1024} KiB")
        now = _now()
        with self._tx() as db:
            self._require_room(db, room_id)
            if artifact_id is None:
                if expected_version is not None:
                    raise ValidationError("expected_version needs an artifact_id")
                artifact_id = _new_id()
                db.execute("INSERT INTO artifacts (id, room_id, created_at) VALUES (?, ?, ?)",
                           (artifact_id, room_id, now))
                version = 1
            else:
                owner = db.execute("SELECT room_id FROM artifacts WHERE id = ?", (artifact_id,)).fetchone()
                if owner is None or owner["room_id"] != room_id:
                    raise NotFoundError("Artifact not found in this room")
                if type(expected_version) is not int:
                    raise ValidationError("Saving a new version needs expected_version")
                latest = db.execute("SELECT max(version) FROM artifact_versions WHERE artifact_id = ?",
                                    (artifact_id,)).fetchone()[0]
                if latest != expected_version:
                    raise ConflictError(
                        f"Artifact changed: latest is version {latest}, not {expected_version}; reload and compare"
                    )
                version = latest + 1
            db.execute(
                "INSERT INTO artifact_versions (artifact_id, version, title, content, sha256, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (artifact_id, version, title, content, sha256_text(content), now),
            )
        return {"id": artifact_id, "title": title, "version": version, "content": content,
                "sha256": sha256_text(content), "created_at": now}

    # ----- sessions --------------------------------------------------------------------

    def session(self, room_id: str, agent_id: str) -> str | None:
        rows = self._read("SELECT session_id FROM sessions WHERE room_id = ? AND agent_id = ?", (room_id, agent_id))
        return rows[0]["session_id"] if rows else None

    # ----- rounds ----------------------------------------------------------------------

    def create_round(self, *, room_id: str, request_id: str, request_sha256: str, mode: str, text: str,
                     participants: list[str], artifact_ids: list[str], first_phase: str,
                     build_context: ContextBuilder,
                     participant_snapshots: dict[str, dict[str, str]] | None = None,
                     ) -> tuple[dict[str, Any], bool]:
        """Persist everything a round needs before any provider launch.

        Returns (round, created). A repeated request_id with the same request hash returns
        the saved round with created=False; a different payload under that id is refused.
        participant_snapshots freezes {agent_id: {name, provider, role}} as selected, so
        prompts and attribution survive later registry changes.
        """
        snapshots = {key: {f: str(value.get(f, "")) for f in ("name", "provider", "role")}
                     for key, value in (participant_snapshots or {}).items()}
        if snapshots and set(snapshots) != set(participants):
            raise ValidationError("Participant snapshots must match the selected participants")
        if len(artifact_ids) > MAX_ARTIFACTS_PER_ROUND:
            raise ValidationError(f"Select at most {MAX_ARTIFACTS_PER_ROUND} artifacts")
        with self._tx() as db:
            existing = db.execute("SELECT id, request_sha256 FROM rounds WHERE request_id = ?",
                                  (request_id,)).fetchone()
            if existing is not None:
                if existing["request_sha256"] != request_sha256:
                    raise ConflictError("This request_id was already used for a different request")
                return self._round_dict(db, existing["id"]), False
            self._require_room(db, room_id)
            active = db.execute("SELECT id FROM rounds WHERE active_room = ?", (room_id,)).fetchone()
            if active is not None:
                raise ConflictError("This room already has an active round; wait, stop or resume it first")
            frozen: list[dict[str, Any]] = []
            for artifact_id in artifact_ids:
                owner = db.execute("SELECT room_id FROM artifacts WHERE id = ?", (artifact_id,)).fetchone()
                if owner is None or owner["room_id"] != room_id:
                    raise ValidationError("A selected artifact does not belong to this room")
                latest = db.execute(
                    "SELECT * FROM artifact_versions WHERE artifact_id = ? ORDER BY version DESC LIMIT 1",
                    (artifact_id,),
                ).fetchone()
                frozen.append(self._version_dict(latest))
            older = db.execute("SELECT count(*) FROM messages WHERE room_id = ?", (room_id,)).fetchone()[0]
            history_rows = db.execute(
                "SELECT * FROM (SELECT * FROM messages WHERE room_id = ? ORDER BY seq DESC LIMIT ?) ORDER BY seq",
                (room_id, HISTORY_LIMIT),
            ).fetchall()
            history = [self._message_dict(r) for r in history_rows]
            context = build_context(history, older - len(history), frozen, text)
            if utf8_len(context) > MAX_CONTEXT_BYTES:
                raise ValidationError(f"Shared context is over {MAX_CONTEXT_BYTES // 1024} KiB")
            round_id = _new_id()
            now = _now()
            owner_message_id = self._insert_message(db, room_id, "owner", text, round_id=round_id)
            db.execute(
                "INSERT INTO rounds (id, room_id, request_id, request_sha256, mode, status, active_room, "
                "participants, participant_snapshots, artifacts, context, context_sha256, owner_message_id, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (round_id, room_id, request_id, request_sha256, mode, room_id, json.dumps(participants),
                 json.dumps(snapshots),
                 json.dumps([{k: a[k] for k in ("id", "title", "version", "sha256")} for a in frozen]),
                 context, sha256_text(context), owner_message_id, now, now),
            )
            for agent_id in participants:
                self._insert_turn(db, round_id, agent_id, first_phase)
            return self._round_dict(db, round_id), True

    def _round_dict(self, db: sqlite3.Connection, round_id: str, *, for_browser: bool = False) -> dict[str, Any]:
        fields = ("id, room_id, request_id, status, mode, participants, participant_snapshots, artifacts, "
                  "context_sha256, length(CAST(context AS BLOB)) AS context_bytes, owner_message_id, "
                  "note, created_at, updated_at") if for_browser else "*"
        row = db.execute(f"SELECT {fields} FROM rounds WHERE id = ?", (round_id,)).fetchone()
        if row is None:
            raise NotFoundError("Round not found")
        participants = json.loads(row["participants"])
        if for_browser:
            turn_rows = db.execute(
                "SELECT id, round_id, agent_id, phase, status, launched, error, provider, created_at, updated_at "
                "FROM turns WHERE round_id = ? ORDER BY seq", (round_id,),
            ).fetchall()
            turns = [{**dict(turn), "launched": bool(turn["launched"])} for turn in turn_rows]
        else:
            turns = [self._turn_dict(t) for t in
                     db.execute("SELECT * FROM turns WHERE round_id = ? ORDER BY seq", (round_id,)).fetchall()]
        synthesis = [t["agent_id"] for t in turns if t["phase"] == "synthesis"]
        snapshots = json.loads(row["participant_snapshots"])
        if for_browser:
            snapshots = {key: {field: value.get(field, "") for field in ("name", "provider")}
                         for key, value in snapshots.items()}
        return {
            "id": row["id"], "room_id": row["room_id"], "request_id": row["request_id"],
            "status": row["status"], "mode": row["mode"], "participants": participants,
            "participant_snapshots": snapshots,
            "artifacts": json.loads(row["artifacts"]), "context_sha256": row["context_sha256"],
            "context_bytes": row["context_bytes"] if for_browser else utf8_len(row["context"]),
            "owner_message_id": row["owner_message_id"],
            "max_calls": 1 if row["mode"] == "direct" else 2 * len(participants) + 1,
            "synthesizer": synthesis[0] if synthesis else None, "note": row["note"],
            "created_at": row["created_at"], "updated_at": row["updated_at"], "turns": turns,
        }

    def round(self, round_id: str) -> dict[str, Any]:
        with self._guard:
            return self._round_dict(self._db, round_id)

    def round_for_browser(self, round_id: str) -> dict[str, Any]:
        with self._guard:
            return self._round_dict(self._db, round_id, for_browser=True)

    def round_for_request(self, request_id: str, request_sha256: str) -> dict[str, Any] | None:
        """The round already saved under request_id, or None. A different payload is refused."""
        with self._guard:
            row = self._db.execute("SELECT id, request_sha256 FROM rounds WHERE request_id = ?",
                                   (request_id,)).fetchone()
            if row is None:
                return None
            if row["request_sha256"] != request_sha256:
                raise ConflictError("This request_id was already used for a different request")
            return self._round_dict(self._db, row["id"])

    def round_context(self, round_id: str) -> str:
        rows = self._read("SELECT context FROM rounds WHERE id = ?", (round_id,))
        if not rows:
            raise NotFoundError("Round not found")
        return str(rows[0]["context"])

    def _system_note(self, db: sqlite3.Connection, round_id: str, content: str) -> None:
        room_id = db.execute("SELECT room_id FROM rounds WHERE id = ?", (round_id,)).fetchone()["room_id"]
        self._insert_message(db, room_id, "system", content, round_id=round_id)

    def mark_round_running(self, round_id: str) -> bool:
        with self._tx() as db:
            cur = db.execute("UPDATE rounds SET status = 'running', updated_at = ? WHERE id = ? AND status = 'queued'",
                             (_now(), round_id))
            return cur.rowcount == 1

    def finish_round(self, round_id: str, status: str, note: str = "") -> bool:
        """running -> completed/failed/interrupted. A round already stopped is left as it is."""
        if status not in ("completed", "failed", "interrupted"):
            raise ValueError(status)
        with self._tx() as db:
            cur = db.execute(
                "UPDATE rounds SET status = ?, active_room = NULL, note = ?, updated_at = ? "
                "WHERE id = ? AND status IN ('queued', 'running')",
                (status, note, _now(), round_id),
            )
            if cur.rowcount and status != "completed":
                self._system_note(db, round_id, note or f"Round {status}.")
            return cur.rowcount == 1

    def cancel_round(self, round_id: str) -> dict[str, Any]:
        with self._tx() as db:
            cur = db.execute(
                "UPDATE rounds SET status = 'cancelled', active_room = NULL, updated_at = ?, "
                "note = 'Stopped by the owner; completed replies are kept and later phases will not run.' "
                "WHERE id = ? AND status IN ('queued', 'running')",
                (_now(), round_id),
            )
            if cur.rowcount:
                db.execute("UPDATE turns SET status = 'cancelled', error = 'stopped before launch', updated_at = ? "
                           "WHERE round_id = ? AND status = 'queued'", (_now(), round_id))
                self._system_note(db, round_id, "Stopped by the owner. Completed replies are kept.")
            return self._round_dict(db, round_id)

    def reactivate_round(self, round_id: str) -> dict[str, Any]:
        """Owner Resume: interrupted/cancelled -> queued, retaking the room's active slot."""
        with self._tx() as db:
            row = db.execute("SELECT room_id, status FROM rounds WHERE id = ?", (round_id,)).fetchone()
            if row is None:
                raise NotFoundError("Round not found")
            if row["status"] not in ("interrupted", "cancelled"):
                raise ConflictError(f"Only an interrupted or stopped round can resume (this one is {row['status']})")
            try:
                db.execute("UPDATE rounds SET status = 'queued', active_room = ?, note = '', updated_at = ? "
                           "WHERE id = ?", (row["room_id"], _now(), round_id))
            except sqlite3.IntegrityError:
                raise ConflictError("This room already has an active round") from None
            return self._round_dict(db, round_id)

    # ----- turns -----------------------------------------------------------------------

    @staticmethod
    def _turn_dict(row: sqlite3.Row) -> dict[str, Any]:
        turn = {k: row[k] for k in ("id", "round_id", "agent_id", "phase", "status", "content", "error",
                                    "provider", "session_id", "model", "created_at", "updated_at")}
        turn["launched"] = bool(row["launched"])
        return turn

    @staticmethod
    def _insert_turn(db: sqlite3.Connection, round_id: str, agent_id: str, phase: str) -> str:
        turn_id = _new_id()
        now = _now()
        db.execute("INSERT INTO turns (id, round_id, agent_id, phase, status, created_at, updated_at) "
                   "VALUES (?, ?, ?, ?, 'queued', ?, ?)", (turn_id, round_id, agent_id, phase, now, now))
        return turn_id

    def ensure_turn(self, round_id: str, agent_id: str, phase: str) -> dict[str, Any] | None:
        """Return the saved turn, creating a queued one only while the round is running."""
        with self._tx() as db:
            row = db.execute("SELECT * FROM turns WHERE round_id = ? AND agent_id = ? AND phase = ?",
                             (round_id, agent_id, phase)).fetchone()
            if row is None:
                status = db.execute("SELECT status FROM rounds WHERE id = ?", (round_id,)).fetchone()["status"]
                if status != "running":
                    return None
                turn_id = self._insert_turn(db, round_id, agent_id, phase)
                row = db.execute("SELECT * FROM turns WHERE id = ?", (turn_id,)).fetchone()
            return self._turn_dict(row)

    def requeue_turn(self, turn_id: str, allow_launched: bool = False) -> bool:
        """Make a stopped turn runnable again. Launched turns need explicit owner permission."""
        with self._tx() as db:
            cur = db.execute(
                "UPDATE turns SET status = 'queued', error = NULL, updated_at = ? WHERE id = ? "
                "AND status IN ('cancelled', 'interrupted') AND (launched = 0 OR ?)",
                (_now(), turn_id, 1 if allow_launched else 0),
            )
            return cur.rowcount == 1

    def claim_turn(self, turn_id: str) -> bool:
        """queued -> running (launched) only while its round is running; else the turn is stopped."""
        with self._tx() as db:
            row = db.execute("SELECT t.status, r.status AS round_status FROM turns t JOIN rounds r "
                             "ON r.id = t.round_id WHERE t.id = ?", (turn_id,)).fetchone()
            if row["status"] != "queued":
                return False
            if row["round_status"] != "running":
                stopped = "cancelled" if row["round_status"] == "cancelled" else "interrupted"
                db.execute("UPDATE turns SET status = ?, error = 'stopped before launch', updated_at = ? "
                           "WHERE id = ?", (stopped, _now(), turn_id))
                return False
            db.execute("UPDATE turns SET status = 'running', launched = 1, updated_at = ? WHERE id = ?",
                       (_now(), turn_id))
            return True

    def end_turn(self, turn_id: str, status: str, error: str) -> None:
        """queued/running -> failed/cancelled/interrupted with a safe summary."""
        if status not in ("failed", "cancelled", "interrupted"):
            raise ValueError(status)
        with self._tx() as db:
            db.execute("UPDATE turns SET status = ?, error = ?, updated_at = ? "
                       "WHERE id = ? AND status IN ('queued', 'running')", (status, error, _now(), turn_id))

    def complete_turn(self, turn_id: str, reply: Reply, save_session: bool,
                      speaker_name: str | None = None) -> bool:
        """Save a reply that actually arrived, even if Stop was pressed while it was in flight.

        The message records the speaker's name (given, else the round's frozen snapshot) and
        the provider the reply reported, so later renames or archives never rewrite history.
        """
        with self._tx() as db:
            row = db.execute("SELECT t.*, r.room_id, r.participant_snapshots FROM turns t JOIN rounds r "
                             "ON r.id = t.round_id WHERE t.id = ?", (turn_id,)).fetchone()
            if row["status"] != "running":
                return False
            if speaker_name is None:
                speaker_name = json.loads(row["participant_snapshots"]).get(row["agent_id"], {}).get("name")
            db.execute("UPDATE turns SET status = 'completed', content = ?, provider = ?, session_id = ?, "
                       "model = ?, error = NULL, updated_at = ? WHERE id = ?",
                       (reply.text, reply.provider, reply.session_id, reply.model, _now(), turn_id))
            self._insert_message(db, row["room_id"], "agent", reply.text, round_id=row["round_id"],
                                 agent_id=row["agent_id"], phase=row["phase"], agent_name=speaker_name,
                                 agent_provider=reply.provider)
            if save_session and reply.session_id:
                db.execute(
                    "INSERT INTO sessions (room_id, agent_id, provider, session_id, updated_at) "
                    "VALUES (?, ?, ?, ?, ?) ON CONFLICT (room_id, agent_id) DO UPDATE SET "
                    "provider = excluded.provider, session_id = excluded.session_id, updated_at = excluded.updated_at",
                    (row["room_id"], row["agent_id"], reply.provider, reply.session_id, _now()),
                )
            return True

    # ----- resident registry -------------------------------------------------------------

    @staticmethod
    def _resident_dict(row: sqlite3.Row) -> dict[str, Any]:
        resident = {k: row[k] for k in ("id", "name", "provider", "role", "binding_id", "home_slot",
                                        "created_at", "updated_at")}
        resident["archived"] = bool(row["archived"])
        return resident

    @staticmethod
    def _free_slot(db: sqlite3.Connection, preferred: int | None = None) -> int:
        taken = {r[0] for r in db.execute("SELECT home_slot FROM residents WHERE archived = 0")}
        if preferred is not None and preferred not in taken:
            return preferred
        for slot in range(MAX_RESIDENTS):
            if slot not in taken:
                return slot
        raise ConflictError(f"The town is full: archive a resident before adding more than {MAX_RESIDENTS}")

    def residents(self) -> list[dict[str, Any]]:
        rows = self._read("SELECT * FROM residents ORDER BY home_slot, created_at, id")
        return [self._resident_dict(r) for r in rows]

    def seed_residents(self, rows: list[dict[str, str]]) -> None:
        """Insert configured residents whose ID was never registered. Existing rows, edits and
        archives win; an archived configured resident is not recreated at restart. A full town
        defers new seeds until a later restart with room, without preventing Home from opening."""
        with self._tx() as db:
            now = _now()
            for item in rows:
                if db.execute("SELECT 1 FROM residents WHERE id = ?", (item["id"],)).fetchone():
                    continue
                try:
                    slot = self._free_slot(db)
                except ConflictError:
                    continue  # trusted bindings remain available; no existing resident moves out
                db.execute(
                    "INSERT INTO residents (id, name, provider, role, binding_id, home_slot, archived, "
                    "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)",
                    (item["id"], item["name"], item["provider"], item.get("role", ""), item["binding_id"],
                     slot, now, now),
                )

    def add_resident(self, resident_id: str, name: str, provider: str, role: str,
                     binding_id: str) -> dict[str, Any]:
        """Register a new resident in the first unoccupied active home slot."""
        with self._tx() as db:
            if db.execute("SELECT 1 FROM residents WHERE id = ?", (resident_id,)).fetchone():
                raise ConflictError("That resident ID is already registered")
            now = _now()
            db.execute(
                "INSERT INTO residents (id, name, provider, role, binding_id, home_slot, archived, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)",
                (resident_id, name, provider, role, binding_id, self._free_slot(db), now, now),
            )
            return self._resident_dict(db.execute("SELECT * FROM residents WHERE id = ?",
                                                  (resident_id,)).fetchone())

    def set_resident_archived(self, resident_id: str, archived: bool) -> dict[str, Any]:
        """Archive keeps the slot number; restore retakes it if free, else the first free slot.
        No other resident moves."""
        with self._tx() as db:
            row = db.execute("SELECT * FROM residents WHERE id = ?", (resident_id,)).fetchone()
            if row is None:
                raise NotFoundError("Resident not found")
            if bool(row["archived"]) == archived:
                raise ConflictError("That resident is already " + ("archived" if archived else "active"))
            slot = row["home_slot"] if archived else self._free_slot(db, preferred=row["home_slot"])
            db.execute("UPDATE residents SET archived = ?, home_slot = ?, updated_at = ? WHERE id = ?",
                       (1 if archived else 0, slot, _now(), resident_id))
            return self._resident_dict(db.execute("SELECT * FROM residents WHERE id = ?",
                                                  (resident_id,)).fetchone())

    # ----- recovery --------------------------------------------------------------------

    def recover_unfinished(self) -> list[str]:
        """Startup only: mark unfinished work interrupted. Nothing is relaunched or killed."""
        with self._tx() as db:
            now = _now()
            ids = [r["id"] for r in db.execute("SELECT id FROM rounds WHERE status IN ('queued', 'running')")]
            db.execute(
                "UPDATE turns SET status = 'interrupted', updated_at = ?, error = CASE launched "
                "WHEN 1 THEN 'outcome unknown: the app stopped while this call was running' "
                "ELSE 'not started before the app stopped' END WHERE status IN ('queued', 'running')",
                (now,),
            )
            db.execute(
                "UPDATE rounds SET status = 'interrupted', active_room = NULL, updated_at = ?, "
                "note = 'Interrupted by an app restart; nothing was relaunched.' "
                "WHERE status IN ('queued', 'running')",
                (now,),
            )
            for round_id in ids:
                self._system_note(db, round_id, "Interrupted by an app restart. Saved replies are kept; "
                                                "nothing was relaunched.")
            return ids
