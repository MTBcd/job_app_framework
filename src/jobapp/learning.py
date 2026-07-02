from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .history import utc_now_iso


DEFAULT_LEARNING_COLUMNS = [
    "event_at_utc",
    "event_type",
    "weight",
    "company_normalized",
    "domain",
    "email_pattern",
    "email",
    "message_id",
    "source",
]

DEFAULT_EVENT_WEIGHTS = {
    "sent": 1.0,
    "delivered": 1.5,
    "replied": 4.0,
    "hard_bounce": -3.0,
    "soft_bounce": -0.75,
    "failed_send": -1.0,
}


@dataclass
class LearningEvent:
    event_type: str
    company_normalized: str = ""
    domain: str = ""
    email_pattern: str = ""
    email: str = ""
    message_id: str = ""
    source: str = ""
    weight: float = 0.0
    event_at_utc: str = ""

    def to_dict(self) -> Dict[str, Any]:
        row = asdict(self)
        if not row["event_at_utc"]:
            row["event_at_utc"] = utc_now_iso()
        if not row["weight"]:
            row["weight"] = DEFAULT_EVENT_WEIGHTS.get(row["event_type"], 0.0)
        for column in DEFAULT_LEARNING_COLUMNS:
            row.setdefault(column, "")
        return row


class LearningStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write_header()

    def _write_header(self) -> None:
        with self.path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=DEFAULT_LEARNING_COLUMNS)
            writer.writeheader()

    def load(self) -> List[Dict[str, str]]:
        if not self.path.exists():
            return []
        with self.path.open("r", newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))

    def append(self, event: LearningEvent) -> None:
        with self.path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=DEFAULT_LEARNING_COLUMNS)
            writer.writerow(event.to_dict())

    def aggregate(self) -> Dict[str, Dict[str, float]]:
        company_domain_scores: Dict[str, float] = {}
        domain_pattern_scores: Dict[str, float] = {}
        company_pattern_scores: Dict[str, float] = {}

        for event in self.load():
            try:
                weight = float(event.get("weight", "0") or 0.0)
            except ValueError:
                weight = 0.0

            company = str(event.get("company_normalized", "")).strip().lower()
            domain = str(event.get("domain", "")).strip().lower()
            pattern = str(event.get("email_pattern", "")).strip().lower()

            if company and domain:
                key = f"{company}|{domain}"
                company_domain_scores[key] = company_domain_scores.get(key, 0.0) + weight

            if domain and pattern:
                key = f"{domain}|{pattern}"
                domain_pattern_scores[key] = domain_pattern_scores.get(key, 0.0) + weight

            if company and pattern:
                key = f"{company}|{pattern}"
                company_pattern_scores[key] = company_pattern_scores.get(key, 0.0) + weight

        return {
            "company_domain_scores": company_domain_scores,
            "domain_pattern_scores": domain_pattern_scores,
            "company_pattern_scores": company_pattern_scores,
        }

    def best_domain_for_company(self, company_normalized: str) -> str:
        company_key = str(company_normalized or "").strip().lower()
        if not company_key:
            return ""
        totals: Dict[str, float] = {}
        for event in self.load():
            company = str(event.get("company_normalized", "")).strip().lower()
            domain = str(event.get("domain", "")).strip().lower()
            if company != company_key or not domain:
                continue
            try:
                weight = float(event.get("weight", "0") or 0.0)
            except ValueError:
                weight = 0.0
            totals[domain] = totals.get(domain, 0.0) + weight
        positive = {domain: score for domain, score in totals.items() if score > 0}
        if not positive:
            return ""
        return sorted(positive.items(), key=lambda item: (item[1], item[0]), reverse=True)[0][0]

    def domain_boost(self, company_normalized: str, domain: str) -> float:
        company = str(company_normalized or "").strip().lower()
        domain = str(domain or "").strip().lower()
        if not company or not domain:
            return 0.0
        value = self.aggregate()["company_domain_scores"].get(f"{company}|{domain}", 0.0)
        return max(min(value * 0.05, 0.25), -0.25)

    def pattern_boost(self, company_normalized: str, domain: str, pattern: str) -> float:
        company = str(company_normalized or "").strip().lower()
        domain = str(domain or "").strip().lower()
        pattern = str(pattern or "").strip().lower()
        if not pattern:
            return 0.0
        aggregate = self.aggregate()
        company_pattern = aggregate["company_pattern_scores"].get(f"{company}|{pattern}", 0.0)
        domain_pattern = aggregate["domain_pattern_scores"].get(f"{domain}|{pattern}", 0.0)
        combined = company_pattern * 0.04 + domain_pattern * 0.035
        return max(min(combined, 0.3), -0.3)

    def has_message_event(self, message_id: str, event_type: str) -> bool:
        message_id = str(message_id or "").strip()
        event_type = str(event_type or "").strip().lower()
        if not message_id or not event_type:
            return False
        return any(
            event.get("message_id", "").strip() == message_id
            and event.get("event_type", "").strip().lower() == event_type
            for event in self.load()
        )