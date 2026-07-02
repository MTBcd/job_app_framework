"""Characterization tests for jobapp.history — send history store and person keys."""
from __future__ import annotations

import pytest

from jobapp.history import HistoryRecord, SendHistoryStore, build_person_key


class TestBuildPersonKey:
    def test_ascii_name_and_company(self):
        key = build_person_key(
            {
                "first_name_ascii": "john",
                "last_name_ascii": "smith",
                "company_normalized": "acme",
            }
        )
        assert key == "john|smith|acme"

    def test_falls_back_to_display_fields(self):
        key = build_person_key({"first_name": "John", "last_name": "Smith"})
        assert key == "john|smith"

    def test_company_alone_becomes_whole_key(self):
        # Pinned V0 defect (found while writing these tests): the primary key
        # path fires as soon as *any* of first/last/company is present, so a
        # row with only a company collapses to "acme" — every nameless contact
        # at the same company shares one identity (breaks dedupe/attempts).
        key = build_person_key({"full_name": "John Smith", "company_name": "Acme"})
        assert key == "acme"

    def test_full_name_fallback_only_when_primary_fields_empty(self):
        key = build_person_key({"full_name": "John Smith", "domain": "x.com"})
        assert key == "john smith||x.com"

    def test_empty_row_yields_literal_pipes_not_hash(self):
        # Pinned V0 defect: the fallback join of three empty strings is "||",
        # which is truthy, so the sha256 branch is unreachable and every fully
        # empty row shares the same person key.
        assert build_person_key({}) == "||"


@pytest.fixture()
def store(tmp_path):
    return SendHistoryStore(tmp_path / "history.csv")


def _record(store, *, person_key="john|smith|acme", email="jsmith@acme.com",
            status="sent", message_id=""):
    return HistoryRecord(
        person_key=person_key,
        email_attempted=email,
        status=status,
        message_id=message_id,
        attempt_number=store.next_attempt_number(person_key),
    )


class TestSendHistoryStore:
    def test_append_and_load_roundtrip(self, store):
        store.append(_record(store))
        rows = store.load()
        assert len(rows) == 1
        assert rows[0]["person_key"] == "john|smith|acme"
        assert rows[0]["status"] == "sent"

    def test_attempt_numbers_increment_per_person(self, store):
        store.append(_record(store, status="failed_send"))
        store.append(_record(store, email="john.smith@acme.com", status="sent"))
        assert store.next_attempt_number("john|smith|acme") == 3
        assert store.next_attempt_number("someone|else|x") == 1

    def test_success_statuses(self, store):
        store.append(_record(store, status="dry_run"))
        # dry_run is NOT a success in history.has_success_for_person...
        assert store.has_success_for_person("john|smith|acme") is False
        store.append(_record(store, status="replied"))
        assert store.has_success_for_person("john|smith|acme") is True
        # ...but IS a success in retry_logic.SUCCESS_STATUSES — two disagreeing
        # vocabularies, unified in the M1 port (audit 00-repo-audit.md).

    def test_was_email_tried_for_person(self, store):
        store.append(_record(store))
        assert store.was_email_tried_for_person("john|smith|acme", "JSMITH@acme.com")
        assert not store.was_email_tried_for_person("john|smith|acme", "other@acme.com")

    def test_update_by_message_id(self, store):
        store.append(_record(store, message_id="<m1@x>"))
        assert store.update_by_message_id(
            message_id="<m1@x>", new_status="replied", failure_reason="reply_detected"
        )
        assert store.load()[0]["status"] == "replied"

    def test_update_status_hits_all_people_sharing_the_address(self, store):
        # Pinned V0 defect (audit 2.3 item 5): updates by email are not
        # person-scoped — a bounce for one person flips everyone who ever
        # resolved to the same address.
        store.append(_record(store, person_key="john|smith|acme"))
        store.append(_record(store, person_key="jane|smith|acme", email="jsmith@acme.com"))
        store.update_status(
            email_attempted="jsmith@acme.com", new_status="failed_hard_bounce"
        )
        statuses = [row["status"] for row in store.load()]
        assert statuses == ["failed_hard_bounce", "failed_hard_bounce"]

    def test_get_by_message_id(self, store):
        store.append(_record(store, message_id="<m9@x>"))
        assert store.get_by_message_id("<m9@x>") is not None
        assert store.get_by_message_id("<nope@x>") is None
        assert store.get_by_message_id("") is None

    def test_recent_sent_rows_filters_terminal_failures(self, store):
        store.append(_record(store, status="sent"))
        store.append(_record(store, email="a@b.co", status="failed_hard_bounce"))
        assert len(store.recent_sent_rows()) == 1
