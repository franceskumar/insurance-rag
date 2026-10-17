"""SQLite document storage. Each operation owns its connection and transaction."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .ingestion import extract, infer_category


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY, digest TEXT UNIQUE NOT NULL,
                    title TEXT NOT NULL, filename TEXT NOT NULL,
                    category TEXT NOT NULL, size INTEGER NOT NULL,
                    page_count INTEGER NOT NULL, is_demo INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS chunks (
                    id TEXT PRIMARY KEY, document_id TEXT NOT NULL
                    REFERENCES documents(id) ON DELETE CASCADE,
                    ordinal INTEGER NOT NULL, page INTEGER NOT NULL,
                    section TEXT NOT NULL, text TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS chunks_document ON chunks(document_id);
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY, question TEXT NOT NULL,
                    payload TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def seed(self, directory: Path):
        with self.connect() as db:
            if db.execute("SELECT 1 FROM metadata WHERE key='demo_seeded'").fetchone():
                return
        for path in sorted(directory.glob("*.md")):
            self.ingest(path.name, path.read_bytes(), is_demo=True)
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO metadata VALUES ('demo_seeded', '1')")

    def ingest(self, filename: str, content: bytes, is_demo: bool = False) -> dict:
        filename = filename.replace("\\", "/").rsplit("/", 1)[-1][:240] or "document.txt"
        digest = hashlib.sha256(content).hexdigest()
        with self.connect() as db:
            duplicate = db.execute("SELECT id FROM documents WHERE digest=?", (digest,)).fetchone()
        if duplicate:
            return {"document": self.document(duplicate["id"]), "duplicate": True}
        title, passages, page_count = extract(filename, content)
        document_id = uuid.uuid4().hex
        with self.connect() as db:
            # A concurrent identical upload may have won after extraction.
            inserted = db.execute(
                "INSERT OR IGNORE INTO documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (document_id, digest, title, filename, infer_category(filename, title),
                 len(content), page_count, int(is_demo), now()),
            ).rowcount
            if not inserted:
                document_id = db.execute("SELECT id FROM documents WHERE digest=?", (digest,)).fetchone()["id"]
            else:
                db.executemany("INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?)", [
                    (uuid.uuid4().hex, document_id, i, p.page, p.section, p.text)
                    for i, p in enumerate(passages)
                ])
        return {"document": self.document(document_id), "duplicate": not bool(inserted)}

    def documents(self) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("""
                SELECT d.*, COUNT(c.id) AS chunk_count FROM documents d
                LEFT JOIN chunks c ON c.document_id=d.id GROUP BY d.id
                ORDER BY d.is_demo ASC, d.created_at DESC
            """).fetchall()
        return [self._public_document(row) for row in rows]

    @staticmethod
    def _public_document(row) -> dict:
        result = dict(row)
        result.pop("digest", None)
        result["is_demo"] = bool(result["is_demo"])
        return result

    def document(self, document_id: str) -> dict | None:
        return next((d for d in self.documents() if d["id"] == document_id), None)

    def chunks(self, document_ids: list[str] | None = None) -> list[dict]:
        params = document_ids or []
        where = "WHERE d.id IN (" + ",".join("?" for _ in params) + ")" if params else ""
        with self.connect() as db:
            rows = db.execute(f"""
                SELECT c.*, d.title, d.filename, d.category, d.is_demo
                FROM chunks c JOIN documents d ON c.document_id=d.id
                {where} ORDER BY d.created_at, c.ordinal
            """, params).fetchall()
        return [dict(row) for row in rows]

    def delete(self, document_id: str) -> bool:
        with self.connect() as db:
            return bool(db.execute("DELETE FROM documents WHERE id=?", (document_id,)).rowcount)

    def record(self, question: str, payload: dict) -> dict:
        record = {"id": uuid.uuid4().hex, "question": question, "created_at": now(), **payload}
        with self.connect() as db:
            db.execute("INSERT INTO conversations VALUES (?, ?, ?, ?)",
                       (record["id"], question, json.dumps(record), record["created_at"]))
        return record

    def history(self) -> list[dict]:
        with self.connect() as db:
            return [json.loads(row["payload"]) for row in db.execute(
                "SELECT payload FROM conversations ORDER BY created_at DESC LIMIT 50"
            ).fetchall()]

    def clear_history(self):
        with self.connect() as db:
            db.execute("DELETE FROM conversations")
