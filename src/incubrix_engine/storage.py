from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

from .models import Lead

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    stable_creator_id TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL,
    checked_date TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);
"""


class LeadStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.executescript(SCHEMA)

    def close(self) -> None:
        self.connection.close()

    def upsert_many(self, leads: list[Lead]) -> None:
        values = [
            (
                lead.stable_creator_id,
                json.dumps(asdict(lead), ensure_ascii=False, default=str),
                lead.candidate_status,
                lead.checked_date,
            )
            for lead in leads
            if lead.stable_creator_id
        ]
        self.connection.executemany(
            """
            INSERT INTO leads(stable_creator_id, payload_json, status, checked_date)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(stable_creator_id) DO UPDATE SET
                payload_json=excluded.payload_json,
                status=excluded.status,
                checked_date=excluded.checked_date,
                updated_at=CURRENT_TIMESTAMP
            """,
            values,
        )
        self.connection.commit()

    def qualified_ids(self) -> set[str]:
        rows = self.connection.execute(
            "SELECT stable_creator_id FROM leads WHERE status='Qualified'"
        ).fetchall()
        return {row[0] for row in rows}
