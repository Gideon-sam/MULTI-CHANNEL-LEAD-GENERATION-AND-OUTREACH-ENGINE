"""Owned-account seed scheduler and evidence ledger. This module never sends messages."""

from __future__ import annotations

import csv
import hashlib
import json
import secrets
import sqlite3
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlencode, urlparse

CHANNELS = ("email", "linkedin", "instagram")
EVENTS = ("native_scheduled", "sent", "reply", "opt_out", "bounce")


class SeedStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY, campaign TEXT NOT NULL, channel TEXT NOT NULL,
                sender TEXT NOT NULL, recipient TEXT NOT NULL, due_at TEXT NOT NULL,
                token_hash TEXT UNIQUE NOT NULL, ownership_confirmed INTEGER NOT NULL,
                state TEXT NOT NULL DEFAULT 'queued'
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY, message_id TEXT NOT NULL REFERENCES messages(id),
                event TEXT NOT NULL, recorded_at TEXT NOT NULL, evidence TEXT NOT NULL
            );
        """)
        self.db.execute("PRAGMA foreign_keys=ON")

    def close(self):
        self.db.close()

    def plan(
        self, accounts_path: Path, base_url: str, start: datetime, campaign: str
    ) -> list[dict]:
        accounts = json.loads(accounts_path.read_text(encoding="utf-8"))
        if set(accounts) != set(CHANNELS):
            raise ValueError(
                "Provide owned sender and recipient accounts for email, linkedin and instagram"
            )
        if start.tzinfo is None:
            raise ValueError("Start time must include its UTC offset")
        if start < datetime.now(UTC) - timedelta(minutes=5):
            raise ValueError("Schedule start must not be in the past")
        target = urlparse(base_url)
        if (
            target.scheme not in {"http", "https"}
            or not target.netloc
            or target.query
            or target.fragment
            or target.username
        ):
            raise ValueError(
                "Tracking base URL must be HTTP(S), without credentials, query or fragment"
            )
        for channel, account in accounts.items():
            if (
                account.get("ownership_confirmed") is not True
                or not account.get("sender")
                or not account.get("recipient")
            ):
                raise ValueError(
                    f"{channel}: both accounts and explicit ownership confirmation are required"
                )
        rows = []
        try:
            for channel in CHANNELS:
                account = accounts[channel]
                for touch, offset in enumerate((0, 3, 8), start=1):
                    message_id = f"{campaign}-{channel}-{touch}"
                    token = secrets.token_urlsafe(24)
                    due_at = (start + timedelta(days=offset)).astimezone(UTC).isoformat()
                    self.db.execute(
                        "INSERT INTO messages(id,campaign,channel,sender,recipient,due_at,token_hash,ownership_confirmed) VALUES(?,?,?,?,?,?,?,1)",
                        (
                            message_id,
                            campaign,
                            channel,
                            account["sender"],
                            account["recipient"],
                            due_at,
                            hashlib.sha256(token.encode()).hexdigest(),
                        ),
                    )
                    rows.append(
                        {
                            "message_id": message_id,
                            "channel": channel,
                            "sender": account["sender"],
                            "recipient": account["recipient"],
                            "due_at": due_at,
                            "tracking_url": base_url.rstrip("/") + "/t/" + token,
                            "state": "queued_for_manual_native_scheduling",
                        }
                    )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return rows

    def due(self, now: datetime) -> list[dict]:
        rows = self.db.execute(
            "SELECT id,channel,sender,recipient,due_at FROM messages WHERE state='queued' AND due_at<=? ORDER BY due_at,id",
            (now.astimezone(UTC).isoformat(),),
        ).fetchall()
        return [
            dict(zip(("message_id", "channel", "sender", "recipient", "due_at"), row, strict=True))
            for row in rows
        ]

    def record(self, message_id: str, event: str, evidence: str) -> None:
        if event not in EVENTS:
            raise ValueError("Unsupported event")
        if not evidence.strip():
            raise ValueError("A real evidence path or URL is required")
        if not evidence.startswith("https://") and not Path(evidence).is_file():
            raise ValueError("Evidence must be an existing file or HTTPS URL")
        row = self.db.execute(
            "SELECT campaign,channel,recipient,state FROM messages WHERE id=?", (message_id,)
        ).fetchone()
        if row is None:
            raise ValueError("Unknown seed message")
        existing = {
            item[0]
            for item in self.db.execute(
                "SELECT event FROM events WHERE message_id=?", (message_id,)
            )
        }
        if event in existing:
            return
        if event == "sent" and ("native_scheduled" not in existing or row[3] == "suppressed"):
            raise ValueError(
                "Record native scheduling proof first; suppressed messages cannot be sent"
            )
        if event == "reply" and "sent" not in existing:
            raise ValueError("A reply requires an earlier recorded send")
        with self.db:
            self.db.execute(
                "INSERT INTO events(message_id,event,recorded_at,evidence) VALUES(?,?,?,?)",
                (message_id, event, datetime.now(UTC).isoformat(), evidence),
            )
            if event == "sent":
                self.db.execute("UPDATE messages SET state='sent' WHERE id=?", (message_id,))
            if event in {"reply", "opt_out", "bounce"}:
                self.db.execute(
                    "UPDATE messages SET state='suppressed' WHERE campaign=? AND recipient=? AND state='queued'",
                    (row[0], row[2]),
                )

    def click(self, token: str) -> str | None:
        row = self.db.execute(
            "SELECT id,channel,campaign,state FROM messages WHERE token_hash=?",
            (hashlib.sha256(token.encode()).hexdigest(),),
        ).fetchone()
        if row is None:
            return None
        with self.db:
            self.db.execute(
                "INSERT INTO events(message_id,event,recorded_at,evidence) VALUES(?,?,?,?)",
                (
                    row[0],
                    "click" if row[3] == "sent" else "pre_send_link_check",
                    datetime.now(UTC).isoformat(),
                    "First-party tracking endpoint request; no IP address retained",
                ),
            )
        return "https://incubrix.com/?" + urlencode(
            {
                "utm_source": "seed_test",
                "utm_medium": row[1],
                "utm_campaign": row[2],
                "utm_content": row[0],
            }
        )

    def report(self) -> dict:
        channels = {}
        for channel in CHANNELS:
            rows = self.db.execute(
                "SELECT m.id,e.event,e.recorded_at,e.evidence FROM messages m LEFT JOIN events e ON e.message_id=m.id WHERE m.channel=? ORDER BY m.id,e.id",
                (channel,),
            ).fetchall()
            by_message: dict[str, set] = {}
            for message_id, event, *_ in rows:
                by_message.setdefault(message_id, set()).add(event)
            complete = any(
                {"native_scheduled", "sent", "click", "reply"} <= events
                for events in by_message.values()
            )
            channels[channel] = {"evidence_complete": complete, "events": rows}
        return {
            "evidence_complete": all(item["evidence_complete"] for item in channels.values()),
            "external_proof_requires_reviewer_verification": True,
            "channels": channels,
            "transport": "manual native-platform sends; no external send API in this project",
        }


def write_seed_plan(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def serve_tracking(db_path: Path, port: int) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/health":
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ok")
                return
            if not self.path.startswith("/t/") or len(self.path) > 100:
                self.send_error(404)
                return
            store = SeedStore(db_path)
            try:
                destination = store.click(self.path[3:].split("?", 1)[0])
            finally:
                store.close()
            if not destination:
                self.send_error(404)
                return
            self.send_response(302)
            self.send_header("Location", destination)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()

        def log_message(self, *_args):
            pass  # Tokens and IPs must not be written to access logs.

    with ThreadingHTTPServer(("127.0.0.1", port), Handler) as server:
        print(f"Owned-account tracking: http://127.0.0.1:{port}; bind is local only")
        server.serve_forever()
