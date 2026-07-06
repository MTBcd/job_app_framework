"""Characterization tests for jobapp.cleaning — pins V0 behavior before porting."""
from __future__ import annotations

import math

from jobapp.cleaning import (
    ascii_email_token,
    company_display_name,
    extract_domain,
    is_valid_email,
    normalize_company_name,
    normalize_email_localpart,
    normalize_whitespace,
    slug_token,
    smart_title,
    split_name_parts,
)


class TestNormalizeWhitespace:
    def test_collapses_spaces_tabs_nbsp(self):
        assert normalize_whitespace("  a  b\t c  ") == "a b c"

    def test_none_and_nan_become_empty(self):
        assert normalize_whitespace(None) == ""
        assert normalize_whitespace(math.nan) == ""

    def test_non_string_coerced(self):
        assert normalize_whitespace(42) == "42"


class TestAsciiEmailToken:
    def test_strips_accents(self):
        assert ascii_email_token("Émile") == "emile"

    def test_removes_apostrophes(self):
        assert ascii_email_token("O'Brien") == "obrien"
        assert ascii_email_token("O’Brien") == "obrien"

    def test_hyphens_and_spaces_removed(self):
        assert ascii_email_token("Jean-Luc") == "jeanluc"
        assert ascii_email_token("Anne Marie") == "annemarie"

    def test_dots_collapsed_and_stripped(self):
        assert ascii_email_token("j..smith.") == "j.smith"


class TestNormalizeEmailLocalpart:
    def test_collapses_separator_runs(self):
        assert normalize_email_localpart("j__smith") == "j.smith"
        assert normalize_email_localpart(".j.smith-") == "j.smith"


class TestSlugToken:
    def test_ampersand_becomes_and(self):
        assert slug_token("S&P Global") == "s and p global"


class TestSmartTitle:
    def test_capitalizes_hyphen_and_apostrophe_parts(self):
        assert smart_title("jean-luc o'neil") == "Jean-Luc O'Neil"

    def test_lowercases_rest_of_uppercase_input(self):
        assert smart_title("FONTAINE") == "Fontaine"

    def test_empty(self):
        assert smart_title("") == ""


class TestSplitNameParts:
    def test_commas_and_slashes_split(self):
        assert split_name_parts("Smith, John / J") == ["Smith", "John", "J"]


class TestNormalizeCompanyName:
    def test_strips_corporate_suffixes_and_parens(self):
        assert normalize_company_name("Goldman Sachs Group Inc. (NY)") == "goldman sachs"

    def test_ampersand_normalized(self):
        # "&" -> " and "; suffix "co" removed
        assert normalize_company_name("Johnson & Johnson Co") == "johnson and johnson"

    def test_private_banking_removed(self):
        assert normalize_company_name("Acme Private Banking") == "acme"


class TestCompanyDisplayName:
    def test_trims_punctuation_edges(self):
        assert company_display_name("  Acme Corp -, ") == "Acme Corp"


class TestIsValidEmail:
    def test_valid(self):
        assert is_valid_email("john.smith@acme.com")
        # V0 allows apostrophes in the local part (unlike sender.is_valid_email,
        # see audit 00-repo-audit.md section 2.3 item 7).
        assert is_valid_email("o'brien@acme.com")

    def test_invalid(self):
        assert not is_valid_email("j smith@acme.com")
        assert not is_valid_email("nodomain@")
        assert not is_valid_email(None)
        assert not is_valid_email(math.nan)


class TestExtractDomain:
    def test_from_email(self):
        assert extract_domain("John@Acme.COM") == "acme.com"

    def test_from_url_with_path_and_query(self):
        assert extract_domain("https://www.acme.co.uk/careers?x=1#top") == "acme.co.uk"

    def test_mailto_prefix(self):
        assert extract_domain("mailto:j@x.io") == "x.io"

    def test_bare_domain(self):
        assert extract_domain("acme.io") == "acme.io"

    def test_garbage_empty(self):
        assert extract_domain("not a domain") == ""
        assert extract_domain("") == ""
