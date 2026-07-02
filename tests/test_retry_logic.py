"""Characterization tests for jobapp.retry_logic — skip/next-candidate decisions."""
from __future__ import annotations

import json

import pytest

from jobapp.history import HistoryRecord, SendHistoryStore
from jobapp.retry_logic import choose_next_candidate, prepare_retry_row, should_skip_person


CANDIDATES = [
    {"email": "john.smith@acme.com", "pattern": "first.last", "confidence": 0.8,
     "reasoning": ["pattern=first.last"]},
    {"email": "jsmith@acme.com", "pattern": "flast", "confidence": 0.6,
     "reasoning": ["pattern=flast"]},
    {"email": "john@acme.com", "pattern": "first", "confidence": 0.4,
     "reasoning": ["pattern=first"]},
]


def _row(**overrides):
    row = {
        "first_name_ascii": "john",
        "last_name_ascii": "smith",
        "company_normalized": "acme",
        "email_selected": "john.smith@acme.com",
        "email_pattern": "first.last",
        "email_confidence": 0.8,
        "email_candidates_json": json.dumps(CANDIDATES),
    }
    row.update(overrides)
    return row


@pytest.fixture()
def store(tmp_path):
    return SendHistoryStore(tmp_path / "history.csv")


def _attempt(status, email="john.smith@acme.com"):
    return HistoryRecord(
        person_key="john|smith|acme", email_attempted=email, status=status
    )


class TestShouldSkipPerson:
    def test_no_history_no_skip(self, store):
        assert should_skip_person(_row(), store) == (False, "")

    def test_prior_success_skips(self, store):
        store.append(_attempt("sent"))
        assert should_skip_person(_row(), store) == (True, "skipped_already_sent")

    def test_dry_run_counts_as_success_here(self, store):
        # Pinned inconsistency: retry_logic treats dry_run as success while
        # history.has_success_for_person does not (see test_history).
        store.append(_attempt("dry_run"))
        assert should_skip_person(_row(), store) == (True, "skipped_already_sent")

    def test_attempt_exhaustion_skips(self, store):
        for status in ("failed_send", "failed_send", "failed_send"):
            store.append(_attempt(status))
        skip, reason = should_skip_person(_row(), store, max_attempts_per_person=3)
        assert (skip, reason) == (True, "skipped_retry_exhausted")

    def test_same_candidate_already_terminal_skips(self, store):
        store.append(_attempt("failed_hard_bounce"))
        skip, reason = should_skip_person(_row(), store)
        assert (skip, reason) == (True, "skipped_duplicate_candidate")


class TestChooseNextCandidate:
    def test_returns_next_untried_after_failure(self, store):
        store.append(_attempt("failed_hard_bounce"))
        candidate = choose_next_candidate(_row(), store)
        assert candidate is not None
        assert candidate["email"] == "jsmith@acme.com"

    def test_none_after_success(self, store):
        store.append(_attempt("sent"))
        assert choose_next_candidate(_row(), store) is None

    def test_none_when_exhausted(self, store):
        store.append(_attempt("failed_hard_bounce"))
        store.append(_attempt("failed_hard_bounce", email="jsmith@acme.com"))
        store.append(_attempt("failed_hard_bounce", email="john@acme.com"))
        assert choose_next_candidate(_row(), store, max_attempts_per_person=3) is None

    def test_require_existing_failure_gates_fresh_rows(self, store):
        assert (
            choose_next_candidate(_row(), store, require_existing_failure=True) is None
        )


class TestPrepareRetryRow:
    def test_no_retry_without_failure(self, store):
        assert prepare_retry_row(_row(), store) is None

    def test_retry_row_promotes_next_candidate(self, store):
        store.append(_attempt("failed_hard_bounce"))
        retry = prepare_retry_row(_row(), store)
        assert retry is not None
        assert retry["email_selected"] == "jsmith@acme.com"
        assert retry["email_pattern"] == "flast"
        assert retry["send_status"] == "retry_ready"
        assert retry["previous_failed_emails"] == "john.smith@acme.com"
        assert retry["previous_attempt_count"] == 1
