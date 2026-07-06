"""Characterization tests for jobapp.learning — feedback events and aggregates."""
from __future__ import annotations

import pytest

from jobapp.learning import DEFAULT_EVENT_WEIGHTS, LearningEvent, LearningStore


class TestLearningEvent:
    def test_default_weights_applied(self):
        assert LearningEvent(event_type="replied").to_dict()["weight"] == 4.0
        assert LearningEvent(event_type="hard_bounce").to_dict()["weight"] == -3.0
        assert LearningEvent(event_type="sent").to_dict()["weight"] == 1.0

    def test_unknown_event_type_zero_weight(self):
        assert LearningEvent(event_type="mystery").to_dict()["weight"] == 0.0

    def test_timestamp_autofilled(self):
        assert LearningEvent(event_type="sent").to_dict()["event_at_utc"] != ""

    def test_weight_table_pinned(self):
        # The V0 signal design: replies dominate, hard bounces punish hardest.
        assert DEFAULT_EVENT_WEIGHTS == {
            "sent": 1.0,
            "delivered": 1.5,
            "replied": 4.0,
            "hard_bounce": -3.0,
            "soft_bounce": -0.75,
            "failed_send": -1.0,
        }


@pytest.fixture()
def store(tmp_path):
    return LearningStore(tmp_path / "lf.csv")


class TestLearningStore:
    def test_append_and_load_roundtrip(self, store):
        store.append(
            LearningEvent(
                event_type="replied",
                company_normalized="acme",
                domain="acme.com",
                email_pattern="first.last",
            )
        )
        rows = store.load()
        assert len(rows) == 1
        assert rows[0]["event_type"] == "replied"
        assert rows[0]["weight"] == "4.0"

    def test_aggregate_sums_weights_per_key(self, store):
        store.append(
            LearningEvent(event_type="sent", company_normalized="acme", domain="acme.com",
                          email_pattern="flast")
        )
        store.append(
            LearningEvent(event_type="replied", company_normalized="acme", domain="acme.com",
                          email_pattern="flast")
        )
        aggregate = store.aggregate()
        assert aggregate["company_domain_scores"]["acme|acme.com"] == 5.0
        assert aggregate["domain_pattern_scores"]["acme.com|flast"] == 5.0
        assert aggregate["company_pattern_scores"]["acme|flast"] == 5.0

    def test_best_domain_requires_positive_score(self, store):
        store.append(
            LearningEvent(event_type="hard_bounce", company_normalized="acme",
                          domain="bad.com")
        )
        assert store.best_domain_for_company("acme") == ""
        store.append(
            LearningEvent(event_type="replied", company_normalized="acme",
                          domain="good.com")
        )
        assert store.best_domain_for_company("acme") == "good.com"

    def test_domain_boost_clamped(self, store):
        for _ in range(10):
            store.append(
                LearningEvent(event_type="replied", company_normalized="acme",
                              domain="acme.com")
            )
        assert store.domain_boost("acme", "acme.com") == 0.25  # clamp ceiling

    def test_pattern_boost_clamped(self, store):
        for _ in range(10):
            store.append(
                LearningEvent(event_type="replied", company_normalized="acme",
                              domain="acme.com", email_pattern="flast")
            )
        assert store.pattern_boost("acme", "acme.com", "flast") == 0.3  # clamp ceiling

    def test_has_message_event(self, store):
        store.append(LearningEvent(event_type="replied", message_id="<m1@x>"))
        assert store.has_message_event("<m1@x>", "replied") is True
        assert store.has_message_event("<m1@x>", "sent") is False
        assert store.has_message_event("<m2@x>", "replied") is False
