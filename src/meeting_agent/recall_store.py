"""Durable integration state. Run one backend worker per SQLite database."""

from __future__ import annotations

import json
import time
from uuid import uuid4

from .repository import SQLiteRepository


class RecallStore:
    def __init__(self, repository: SQLiteRepository):
        self.repository = repository
        self.connect = repository._connect
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS recall_bots (
                    session_id TEXT PRIMARY KEY REFERENCES sessions(id),
                    bot_id TEXT UNIQUE,
                    launch_key TEXT UNIQUE NOT NULL,
                    state TEXT NOT NULL,
                    join_at TEXT,
                    error TEXT,
                    last_status_at TEXT,
                    media_expires INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS recall_jobs (
                    id TEXT PRIMARY KEY,
                    body TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'queued',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    next_at REAL NOT NULL DEFAULT 0,
                    error TEXT
                );
                CREATE TABLE IF NOT EXISTS recall_audio (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES sessions(id),
                    text TEXT NOT NULL,
                    audio BLOB NOT NULL,
                    state TEXT NOT NULL DEFAULT 'queued',
                    expires REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS recall_calendars (
                    id TEXT PRIMARY KEY,
                    template_session_id TEXT NOT NULL REFERENCES sessions(id),
                    auto_join INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'connected',
                    email TEXT,
                    last_sync TEXT
                );
                CREATE TABLE IF NOT EXISTS recall_calendar_events (
                    id TEXT PRIMARY KEY,
                    calendar_id TEXT NOT NULL REFERENCES recall_calendars(id),
                    session_id TEXT REFERENCES sessions(id),
                    body TEXT NOT NULL,
                    fingerprint TEXT,
                    state TEXT NOT NULL DEFAULT 'discovered'
                );
                CREATE TABLE IF NOT EXISTS recall_transcripts (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES sessions(id),
                    recording_id TEXT,
                    created_at TEXT NOT NULL,
                    body TEXT NOT NULL
                );
            """)

    def one(self, sql, args=()):
        with self.connect() as db:
            row = db.execute(sql, args).fetchone()
            return dict(row) if row else None

    def all(self, sql, args=()):
        with self.connect() as db:
            return [dict(row) for row in db.execute(sql, args).fetchall()]

    def execute(self, sql, args=()):
        with self.connect() as db:
            return db.execute(sql, args).rowcount

    def bot(self, session_id):
        return self.one("SELECT * FROM recall_bots WHERE session_id=?", (session_id,))

    def enqueue(self, job_id, payload):
        return (
            self.execute(
                "INSERT OR IGNORE INTO recall_jobs(id,body) VALUES(?,?)",
                (job_id, json.dumps(payload)),
            )
            == 1
        )

    def recover(self):
        # Do not replay a possibly completed external side effect after a crash.
        self.execute(
            "UPDATE recall_jobs SET state='needs_attention',error='Interrupted during processing; inspect before retrying' WHERE state='processing'"
        )
        self.execute(
            "UPDATE recall_bots SET state='needs_attention',error='Create outcome unknown; reconcile before another launch' WHERE state='creating'"
        )
        self.execute("UPDATE recall_audio SET state='failed' WHERE state='playing'")
        self.execute(
            "UPDATE recall_bots SET state='needs_attention',error='Launch intent has no queued job; inspect before retrying' WHERE state='queued' AND launch_key NOT LIKE 'calendar:%' AND NOT EXISTS (SELECT 1 FROM recall_jobs WHERE id='launch:' || recall_bots.session_id)"
        )

    def claim_job(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM recall_jobs WHERE state='queued' AND next_at<=? ORDER BY rowid LIMIT 1",
                (time.time(),),
            ).fetchone()
            if row:
                db.execute(
                    "UPDATE recall_jobs SET state='processing', attempts=attempts+1 WHERE id=?",
                    (row["id"],),
                )
            return dict(row) if row else None

    def add_audio(self, session_id, text, audio, audio_id=None):
        audio_id = audio_id or str(uuid4())
        self.execute(
            "INSERT OR IGNORE INTO recall_audio(id,session_id,text,audio,expires) VALUES(?,?,?,?,?)",
            (audio_id, session_id, text, audio, time.time() + 60),
        )
        return audio_id

    def claim_audio(self, session_id):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "UPDATE recall_audio SET state='expired',audio=X'' WHERE expires<? AND state IN ('queued','playing')",
                (time.time(),),
            )
            row = db.execute(
                "SELECT id,text FROM recall_audio WHERE session_id=? AND state='queued' AND expires>? ORDER BY rowid LIMIT 1",
                (session_id, time.time()),
            ).fetchone()
            if row:
                db.execute(
                    "UPDATE recall_audio SET state='playing' WHERE id=?", (row["id"],)
                )
            return dict(row) if row else None
