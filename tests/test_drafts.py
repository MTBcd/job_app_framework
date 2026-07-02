"""Characterization tests for jobapp.drafts — salutations and template rendering."""
from __future__ import annotations

import pandas as pd

from jobapp.drafts import (
    _clean_company_for_email,
    _clean_draft_text,
    _default_salutation,
    build_drafts,
)


class TestDefaultSalutation:
    def test_both_names(self):
        assert _default_salutation("John", "Smith") == "Dear John Smith,"

    def test_first_only(self):
        assert _default_salutation("John", "") == "Dear John,"

    def test_last_only(self):
        assert _default_salutation("", "Smith") == "Dear Mr./Ms. Smith,"

    def test_neither(self):
        assert _default_salutation("", "") == "Dear Sir or Madam,"

    def test_initial_with_dot_not_usable(self):
        assert _default_salutation("J.", "Smith") == "Dear Mr./Ms. Smith,"


class TestCleanCompanyForEmail:
    def test_known_brand_normalized(self):
        assert _clean_company_for_email("jpmorgan chase & co") == "JPMorgan"
        assert _clean_company_for_email("BANK OF AMERICA") == "Bank of America"

    def test_unknown_company_passes_through(self):
        assert _clean_company_for_email("Acme Rockets") == "Acme Rockets"


class TestCleanDraftText:
    def test_llm_artifacts_stripped(self):
        text = "Hello :contentReference[oaicite:0]{index=0} world"
        assert _clean_draft_text(text) == "Hello world"

    def test_whitespace_and_punctuation_fixed(self):
        assert _clean_draft_text("Hello  ,  world .\n\n\n\nBye") == "Hello, world.\n\nBye"


class TestBuildDrafts:
    def test_template_substitution(self, tmp_path):
        (tmp_path / "email_subject.txt").write_text(
            "Hello ${company}", encoding="utf-8"
        )
        (tmp_path / "email_body_en.txt").write_text(
            "${salutation}\nInterested in ${company}. — ${sender_name}",
            encoding="utf-8",
        )
        df = pd.DataFrame(
            {"first_name": ["Jane"], "last_name": ["Doe"], "company_name": ["Acme"]}
        )
        out = build_drafts(df, tmp_path, sender_name="Alex Bell", sender_email="a@b.co")
        assert out.loc[0, "draft_subject"] == "Hello Acme"
        assert out.loc[0, "salutation"] == "Dear Jane Doe,"
        assert "Interested in Acme. — Alex Bell" in out.loc[0, "draft_body"]

    def test_missing_company_uses_placeholder(self, tmp_path):
        (tmp_path / "email_subject.txt").write_text("At ${company}", encoding="utf-8")
        (tmp_path / "email_body_en.txt").write_text("${salutation}", encoding="utf-8")
        df = pd.DataFrame(
            {"first_name": ["Jane"], "last_name": ["Doe"], "company_name": [""]}
        )
        out = build_drafts(df, tmp_path)
        assert out.loc[0, "draft_subject"] == "At your organization"

    def test_default_sender_name_is_hardcoded_founder(self, tmp_path):
        # Pinned V0 defect (audit 00-repo-audit.md, drafts.py row): the
        # founder's personal name is the baked-in fallback sender. Removed in
        # the M1 port where sender identity becomes required configuration.
        (tmp_path / "email_subject.txt").write_text("s", encoding="utf-8")
        (tmp_path / "email_body_en.txt").write_text("${sender_name}", encoding="utf-8")
        df = pd.DataFrame(
            {"first_name": ["Jane"], "last_name": ["Doe"], "company_name": ["Acme"]}
        )
        out = build_drafts(df, tmp_path, sender_name="", sender_email="")
        assert out.loc[0, "draft_body"] == "Mael Boccardi"
