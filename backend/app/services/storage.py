from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATABASE = BACKEND_ROOT / "data" / "decisionos.sqlite3"


class DecisionStorage:
    def __init__(self, database_path: Path | None = None) -> None:
        configured = os.getenv("DATABASE_URL", "")
        if database_path is not None:
            self.path = Path(database_path)
        elif configured.startswith("sqlite:///"):
            database = Path(configured.removeprefix("sqlite:///"))
            self.path = database if database.is_absolute() else BACKEND_ROOT.parent / database
        else:
            self.path = DEFAULT_DATABASE
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS decisions (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
            connection.execute("CREATE TABLE IF NOT EXISTS approvals (decision_id TEXT PRIMARY KEY, payload TEXT NOT NULL, FOREIGN KEY(decision_id) REFERENCES decisions(id))")
            connection.execute("CREATE TABLE IF NOT EXISTS deleted_datasets (dataset_id TEXT PRIMARY KEY, deleted_at TEXT NOT NULL)")

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def save_decision(self, decision: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute("INSERT OR REPLACE INTO decisions(id, payload) VALUES (?, ?)", (decision["id"], json.dumps(decision)))

    def is_dataset_deleted(self, dataset_id: str) -> bool:
        if not dataset_id:
            return False
        with self._connect() as connection:
            row = connection.execute("SELECT 1 FROM deleted_datasets WHERE dataset_id = ?", (dataset_id,)).fetchone()
        return row is not None

    def delete_dataset_records(self, dataset_id: str) -> int:
        if not dataset_id:
            return 0
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            connection.execute("INSERT OR REPLACE INTO deleted_datasets(dataset_id, deleted_at) VALUES (?, ?)", (dataset_id, now))
            rows = connection.execute("SELECT id, payload FROM decisions").fetchall()
            decision_ids: list[str] = []
            for decision_id, payload in rows:
                decision = self._parse_payload(payload)
                if decision and decision.get("dataset_id") == dataset_id:
                    decision_ids.append(decision_id)
            if decision_ids:
                placeholders = ",".join("?" for _ in decision_ids)
                connection.execute(f"DELETE FROM approvals WHERE decision_id IN ({placeholders})", decision_ids)
                connection.execute(f"DELETE FROM decisions WHERE id IN ({placeholders})", decision_ids)
            return len(decision_ids)

    def count_decisions_for_dataset(self, dataset_id: str) -> int:
        if not dataset_id:
            return 0
        with self._connect() as connection:
            rows = connection.execute("SELECT payload FROM decisions").fetchall()
        count = 0
        for (payload,) in rows:
            decision = self._parse_payload(payload)
            if decision and decision.get("dataset_id") == dataset_id:
                count += 1
        return count

    def get_decision(self, decision_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT payload FROM decisions WHERE id = ?", (decision_id,)).fetchone()
        if not row:
            return None
        decision = self._parse_payload(row[0])
        if not decision or decision.get("status") == "invalidated" or self.is_dataset_deleted(decision.get("dataset_id", "")):
            return None
        return decision

    def get_latest_decision(self) -> dict[str, Any] | None:
        with self._connect() as connection:
            rows = connection.execute("SELECT payload FROM decisions").fetchall()
        candidates: list[tuple[datetime, dict[str, Any]]] = []
        for (payload,) in rows:
            decision = self._parse_payload(payload)
            if not decision or not decision.get("id"):
                continue
            if decision.get("status") == "invalidated" or self.is_dataset_deleted(decision.get("dataset_id", "")):
                continue
            created_at = decision.get("created_at")
            try:
                timestamp = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                timestamp = datetime.min.replace(tzinfo=timezone.utc)
            candidates.append((timestamp, decision))
        if not candidates:
            return None
        return max(candidates, key=lambda item: (item[0], str(item[1]["id"])))[1]

    def get_approval(self, decision_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT payload FROM approvals WHERE decision_id = ?", (decision_id,)).fetchone()
        return self._parse_payload(row[0]) if row else None

    def save_approval(self, approval: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute("INSERT OR REPLACE INTO approvals(decision_id, payload) VALUES (?, ?)", (approval["decision_id"], json.dumps(approval)))

    @staticmethod
    def _parse_payload(payload: str) -> dict[str, Any] | None:
        try:
            value = json.loads(payload)
        except (TypeError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None


storage = DecisionStorage()