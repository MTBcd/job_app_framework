from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


DEFAULT_HISTORY_COLUMNS = [
    "person_key",
    "full_name",
    "company_name",
    "company_normalized",
    "domain",
    "email_attempted",
    "email_pattern",
    "attempt_number",
    "status",
    "failure_reason",
    "message_id",
    "sent_at_utc",
    "source_file",
    "source_row_number",
    "email_confidence",
    "email_reasoning",
    "email_candidates_json",
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def build_person_key(row: Dict[str, Any]) -> str:
    parts = [
        _clean(row.get("first_name_ascii") or row.get("first_name")),
        _clean(row.get("last_name_ascii") or row.get("last_name")),
        _clean(row.get("company_normalized") or row.get("company_name")),
    ]
    raw_key = "|".join(part.lower() for part in parts if part)
    if raw_key:
        return raw_key

    fallback = "|".join(
        [
            _clean(row.get("full_name")).lower(),
            _clean(row.get("company_name")).lower(),
            _clean(row.get("domain")).lower(),
        ]
    )
    return fallback or hashlib.sha256(
        json.dumps(row, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


@dataclass
class HistoryRecord:
    person_key: str
    full_name: str = ""
    company_name: str = ""
    company_normalized: str = ""
    domain: str = ""
    email_attempted: str = ""
    email_pattern: str = ""
    attempt_number: int = 1
    status: str = ""
    failure_reason: str = ""
    message_id: str = ""
    sent_at_utc: str = ""
    source_file: str = ""
    source_row_number: str = ""
    email_confidence: str = ""
    email_reasoning: str = ""
    email_candidates_json: str = ""

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        for column in DEFAULT_HISTORY_COLUMNS:
            data.setdefault(column, "")
        return data


class SendHistoryStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write_header()

    def _write_header(self) -> None:
        with self.path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=DEFAULT_HISTORY_COLUMNS)
            writer.writeheader()

    def load(self) -> List[Dict[str, str]]:
        if not self.path.exists():
            return []
        with self.path.open("r", newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))

    def write_all(self, rows: Iterable[Dict[str, Any]]) -> None:
        normalized = [
            {column: row.get(column, "") for column in DEFAULT_HISTORY_COLUMNS}
            for row in rows
        ]
        with self.path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=DEFAULT_HISTORY_COLUMNS)
            writer.writeheader()
            writer.writerows(normalized)

    def append(self, record: HistoryRecord) -> None:
        with self.path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=DEFAULT_HISTORY_COLUMNS)
            writer.writerow(record.to_dict())

    def append_many(self, records: Iterable[HistoryRecord]) -> None:
        with self.path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=DEFAULT_HISTORY_COLUMNS)
            for record in records:
                writer.writerow(record.to_dict())

    def update_by_message_id(
        self,
        *,
        message_id: str,
        new_status: str,
        failure_reason: str = "",
    ) -> bool:
        needle = message_id.strip()
        if not needle:
            return False
        rows = self.load()
        updated = False
        for row in rows:
            if row.get("message_id", "").strip() == needle:
                row["status"] = new_status
                if failure_reason:
                    row["failure_reason"] = failure_reason
                updated = True
        if updated:
            self.write_all(rows)
        return updated

    def update_status(
        self,
        *,
        email_attempted: str,
        new_status: str,
        failure_reason: str = "",
        message_id: Optional[str] = None,
    ) -> bool:
        rows = self.load()
        updated = False
        needle = email_attempted.strip().lower()
        for row in rows:
            if row.get("email_attempted", "").strip().lower() == needle:
                row["status"] = new_status
                row["failure_reason"] = failure_reason
                if message_id is not None:
                    row["message_id"] = message_id
                updated = True
        if updated:
            self.write_all(rows)
        return updated

    def has_success_for_person(self, person_key: str) -> bool:
        success_statuses = {"sent", "delivered", "replied"}
        return any(
            row.get("person_key") == person_key and row.get("status") in success_statuses
            for row in self.load()
        )

    def attempts_for_person(self, person_key: str) -> List[Dict[str, str]]:
        return [row for row in self.load() if row.get("person_key") == person_key]

    def attempts_for_email(self, email_attempted: str) -> List[Dict[str, str]]:
        needle = email_attempted.strip().lower()
        return [
            row
            for row in self.load()
            if row.get("email_attempted", "").strip().lower() == needle
        ]

    def was_email_tried_for_person(self, person_key: str, email_attempted: str) -> bool:
        needle = email_attempted.strip().lower()
        return any(
            row.get("email_attempted", "").strip().lower() == needle
            for row in self.attempts_for_person(person_key)
        )

    def attempts_for_person_email(
        self,
        person_key: str,
        email_attempted: str,
    ) -> List[Dict[str, str]]:
        needle = email_attempted.strip().lower()
        return [
            row
            for row in self.attempts_for_person(person_key)
            if row.get("email_attempted", "").strip().lower() == needle
        ]

    def next_attempt_number(self, person_key: str) -> int:
        numbers: List[int] = []
        for row in self.attempts_for_person(person_key):
            try:
                numbers.append(int(row.get("attempt_number", "0") or 0))
            except ValueError:
                pass
        return (max(numbers) if numbers else 0) + 1

    def get_by_message_id(self, message_id: str) -> Optional[Dict[str, str]]:
        needle = message_id.strip()
        if not needle:
            return None
        for row in self.load():
            if row.get("message_id", "").strip() == needle:
                return row
        return None

    def recent_sent_rows(self) -> List[Dict[str, str]]:
        valid_statuses = {"sent", "delivered", "replied"}
        return [row for row in self.load() if row.get("status") in valid_statuses]