"""Characterization tests for jobapp.bounce_parser — DSN parsing and classification."""
from __future__ import annotations

import email

import pytest

from jobapp.bounce_parser import (
    classify_bounce_reason,
    extract_failed_recipient,
    is_likely_bounce,
    message_to_text,
    parse_bounce_message,
)
from jobapp.history import HistoryRecord, SendHistoryStore


class TestClassifyBounceReason:
    @pytest.mark.parametrize(
        "text",
        [
            "550 5.1.1 User unknown",
            "Recipient address rejected: no such user",
            "The email account that you tried to reach does not exist",
            "Adresse introuvable",
        ],
    )
    def test_hard_bounces(self, text):
        assert classify_bounce_reason(text) == "hard_bounce"

    @pytest.mark.parametrize(
        "text",
        [
            "Mailbox full, quota exceeded",
            "451 Temporary failure, try again later",
            "greylisted, please retry",
        ],
    )
    def test_soft_bounces(self, text):
        assert classify_bounce_reason(text) == "soft_bounce"

    def test_unknown(self):
        assert classify_bounce_reason("some unrelated text") == "unknown_bounce"


class TestExtractFailedRecipient:
    def test_final_recipient_header(self):
        text = "Final-Recipient: rfc822; jane.doe@corp.com\nAction: failed"
        assert extract_failed_recipient(text) == "jane.doe@corp.com"

    def test_x_failed_recipients_header(self):
        assert (
            extract_failed_recipient("X-Failed-Recipients: bob@corp.com")
            == "bob@corp.com"
        )

    def test_gmail_wasnt_delivered_phrase(self):
        text = "Your message wasn't delivered to sam@corp.io because..."
        assert extract_failed_recipient(text) == "sam@corp.io"

    def test_french_notification(self):
        text = "Votre message n'est pas parvenu à jean@corp.fr, car l'adresse"
        assert extract_failed_recipient(text) == "jean@corp.fr"

    def test_history_store_disambiguates(self, tmp_path):
        store = SendHistoryStore(tmp_path / "h.csv")
        store.append(
            HistoryRecord(person_key="k", email_attempted="real@corp.com", status="sent")
        )
        text = "unrelated@other.com then real@corp.com mentioned"
        assert extract_failed_recipient(text, history_store=store) == "real@corp.com"

    def test_consumer_daemon_addresses_filtered(self):
        text = "mailer-daemon@googlemail.com reported a problem for kim@corp.com"
        assert extract_failed_recipient(text) == "kim@corp.com"


def _dsn_message() -> email.message.Message:
    raw = (
        "From: Mail Delivery Subsystem <mailer-daemon@googlemail.com>\n"
        "To: sender@example.com\n"
        "Subject: Delivery Status Notification (Failure)\n"
        "Content-Type: text/plain\n"
        "\n"
        "Your message wasn't delivered to bob@corp.com\n"
        "550 5.1.1 The email account that you tried to reach does not exist.\n"
        "Final-Recipient: rfc822; bob@corp.com\n"
    )
    return email.message_from_string(raw)


class TestBounceMessageParsing:
    def test_is_likely_bounce_by_sender_and_subject(self):
        assert is_likely_bounce(_dsn_message()) is True

    def test_regular_mail_not_bounce(self):
        msg = email.message_from_string(
            "From: jane@corp.com\nSubject: Re: hello\n\nThanks for reaching out!"
        )
        assert is_likely_bounce(msg) is False

    def test_message_to_text_includes_headers_and_body(self):
        text = message_to_text(_dsn_message())
        assert "Delivery Status Notification" in text
        assert "bob@corp.com" in text

    def test_parse_bounce_message_end_to_end(self):
        result = parse_bounce_message(_dsn_message())
        assert result is not None
        assert result.recipient_email == "bob@corp.com"
        assert result.bounce_type == "hard_bounce"
        assert "550" in result.reason

    def test_non_bounce_returns_none(self):
        msg = email.message_from_string(
            "From: jane@corp.com\nSubject: hello\n\nJust saying hi"
        )
        assert parse_bounce_message(msg) is None
