"""Characterization tests for jobapp.contacts — name parsing and normalization."""
from __future__ import annotations

import pandas as pd

from jobapp.contacts import normalize_contacts, parse_full_name, parse_raw_text


class TestParseFullName:
    def test_simple_two_part_name(self):
        parsed = parse_full_name("John Smith")
        assert parsed["first_name"] == "John"
        assert parsed["last_name"] == "Smith"
        assert parsed["full_name_clean"] == "John Smith"
        assert parsed["first_initial"] == "j"
        assert parsed["last_initial"] == "s"
        assert parsed["is_initials_only"] is False
        assert parsed["name_parse_warning"] == ""

    def test_comma_reversed_name_reordered(self):
        parsed = parse_full_name("Smith, John")
        assert parsed["first_name"] == "John"
        assert parsed["last_name"] == "Smith"

    def test_prefixes_and_suffixes_filtered(self):
        parsed = parse_full_name("Dr. John Smith Jr")
        assert parsed["first_name"] == "John"
        assert parsed["last_name"] == "Smith"

    def test_credential_suffixes_filtered(self):
        parsed = parse_full_name("Jane Doe CFA")
        assert parsed["first_name"] == "Jane"
        assert parsed["last_name"] == "Doe"

    def test_surname_particles_grouped_into_last_name(self):
        parsed = parse_full_name("Jean de la Fontaine")
        assert parsed["first_name"] == "Jean"
        assert parsed["last_name"] == "De La Fontaine"
        assert parsed["name_parse_warning"] == "compound_last_name"

    def test_initial_only_first_name_flagged(self):
        parsed = parse_full_name("J. Smith")
        assert parsed["first_name"] == "J"
        assert parsed["last_name"] == "Smith"
        assert parsed["is_initials_only"] is True
        assert parsed["name_parse_warning"] == "first_name_initial_only"

    def test_single_token(self):
        parsed = parse_full_name("Madonna")
        assert parsed["first_name"] == "Madonna"
        assert parsed["last_name"] == ""
        assert parsed["name_parse_warning"] == "single_token_name"

    def test_empty_name(self):
        parsed = parse_full_name("")
        assert parsed["name_parse_warning"] == "missing_name"

    def test_only_prefix_is_missing_name(self):
        parsed = parse_full_name("Mr")
        assert parsed["name_parse_warning"] == "missing_name"

    def test_linkedin_noise_stripped(self):
        parsed = parse_full_name("Jane Doe (Open to Work) | LinkedIn")
        assert parsed["first_name"] == "Jane"
        assert parsed["last_name"] == "Doe"


class TestParseRawText:
    def test_pipe_separated_blob(self):
        blob = "Jane Doe | Talent Acquisition Manager | Acme Corp | jane.doe@acme.com"
        payload = parse_raw_text(blob)
        assert payload["raw_email"] == "jane.doe@acme.com"
        assert payload["raw_domain"] == "acme.com"
        assert payload["raw_name"] == "Jane Doe"
        assert payload["raw_title"] == "Talent Acquisition Manager"
        assert payload["raw_company"] == "Acme Corp"

    def test_newline_blob_collapses_to_single_line(self):
        # Pinned V0 defect (found while writing these tests): parse_raw_text
        # runs normalize_whitespace over the blob *before* splitting, which
        # collapses newlines to spaces — so newline-separated LinkedIn text is
        # treated as one line and name/title/company are never separated.
        # Only "|"-separated blobs get line-by-line parsing.
        blob = "Jane Doe\nTalent Acquisition Manager\nAcme Corp"
        payload = parse_raw_text(blob)
        assert payload["raw_name"] == "Jane Doe Talent Acquisition Manager Acme Corp"
        assert payload["raw_title"] == ""
        assert payload["raw_company"] == ""

    def test_empty_text(self):
        payload = parse_raw_text("")
        assert payload == {
            "raw_email": "",
            "raw_domain": "",
            "raw_name": "",
            "raw_company": "",
            "raw_title": "",
        }


class TestNormalizeContacts:
    def test_full_name_composed_from_parts(self):
        df = pd.DataFrame({"first_name": ["John"], "last_name": ["Smith"]})
        out = normalize_contacts(df)
        assert out.loc[0, "full_name"] == "John Smith"
        assert out.loc[0, "first_name_ascii"] == "john"
        assert out.loc[0, "last_name_ascii"] == "smith"

    def test_fields_backfilled_from_raw_text(self):
        blob = "Jane Doe | Recruiter | Acme Corp | jane.doe@acme.com"
        df = pd.DataFrame({"raw_text": [blob]})
        out = normalize_contacts(df)
        assert out.loc[0, "first_name"] == "Jane"
        assert out.loc[0, "last_name"] == "Doe"
        assert out.loc[0, "company_name"] == "Acme Corp"
        assert out.loc[0, "email"] == "jane.doe@acme.com"
        assert out.loc[0, "domain"] == "acme.com"
        assert bool(out.loc[0, "email_is_valid"]) is True

    def test_existing_values_win_over_raw_text(self):
        blob = "Jane Doe | Recruiter | Acme Corp | jane.doe@acme.com"
        df = pd.DataFrame({"raw_text": [blob], "company_name": ["Beta LLC"]})
        out = normalize_contacts(df)
        assert out.loc[0, "company_name"] == "Beta LLC"

    def test_names_title_cased(self):
        df = pd.DataFrame({"first_name": ["JOHN"], "last_name": ["smith"]})
        out = normalize_contacts(df)
        assert out.loc[0, "first_name"] == "John"
        assert out.loc[0, "last_name"] == "Smith"
