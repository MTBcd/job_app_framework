"""Characterization tests for jobapp.sender pure helpers (no SMTP involved)."""
from __future__ import annotations

from jobapp import cleaning
from jobapp.history import HistoryRecord, SendHistoryStore
from jobapp.sender import (
    SendSettings,
    _was_email_already_attempted,
    classify_send_failure,
    is_allowed_recipient,
    is_valid_email,
    recipient_domain,
)


class TestClassifySendFailure:
    def test_missing_attachment(self):
        status, _ = classify_send_failure(FileNotFoundError("cv.pdf"))
        assert status == "failed_attachment_missing"

    def test_hard_bounce_patterns(self):
        status, _ = classify_send_failure(Exception("550 5.1.1 user unknown"))
        assert status == "failed_hard_bounce"

    def test_soft_bounce_patterns(self):
        status, _ = classify_send_failure(Exception("451 try again later"))
        assert status == "failed_soft_bounce"

    def test_generic_failure(self):
        status, message = classify_send_failure(Exception("connection reset"))
        assert status == "failed_send"
        assert message == "connection reset"


class TestRecipientPolicy:
    def test_invalid_email_rejected(self):
        allowed, reason = is_allowed_recipient("not-an-email", SendSettings())
        assert (allowed, reason) == (False, "invalid_email")

    def test_blocked_domain_rejected(self):
        settings = SendSettings(blocked_recipient_domains="gmail.com, yahoo.com")
        allowed, reason = is_allowed_recipient("j@gmail.com", settings)
        assert (allowed, reason) == (False, "blocked_consumer_domain")

    def test_allowlist_restricts_when_present(self):
        settings = SendSettings(allowed_recipient_domains="acme.com")
        assert is_allowed_recipient("j@acme.com", settings) == (True, "")
        assert is_allowed_recipient("j@beta.com", settings) == (
            False,
            "domain_not_allowed",
        )

    def test_default_settings_allow_corporate(self):
        assert is_allowed_recipient("jane.doe@corp.com", SendSettings()) == (True, "")

    def test_recipient_domain_extraction(self):
        assert recipient_domain("J@Acme.COM") == "acme.com"
        assert recipient_domain("no-at-sign") == ""


class TestEmailRegexDivergence:
    def test_sender_rejects_apostrophes_cleaning_accepts(self):
        # Pinned V0 defect (audit 2.3 item 7): validators disagree, so an
        # address can pass inference and fail at send time. Unified in M1.
        address = "o'brien@acme.com"
        assert cleaning.is_valid_email(address) is True
        assert is_valid_email(address) is False


class TestWasEmailAlreadyAttempted:
    def test_dry_run_counts_as_attempted(self, tmp_path):
        store = SendHistoryStore(tmp_path / "h.csv")
        store.append(
            HistoryRecord(person_key="k", email_attempted="a@b.co", status="dry_run")
        )
        assert _was_email_already_attempted(store, "A@B.CO") is True

    def test_failed_attempt_does_not_block_retry(self, tmp_path):
        store = SendHistoryStore(tmp_path / "h.csv")
        store.append(
            HistoryRecord(
                person_key="k", email_attempted="a@b.co", status="failed_hard_bounce"
            )
        )
        assert _was_email_already_attempted(store, "a@b.co") is False
