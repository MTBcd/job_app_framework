"""Characterization tests for jobapp.data_loading — ingest and header mapping."""
from __future__ import annotations

import pandas as pd
import pytest

from jobapp.data_loading import canonicalize_header, load_input_frames


class TestCanonicalizeHeader:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("First Name", "first_name"),
            ("Given name", "first_name"),
            ("SURNAME", "last_name"),
            ("Organisation", "company_name"),
            ("Employer", "company_name"),
            ("Job Title", "job_title"),
            ("Professional Email", "email"),
            ("Company Domain", "domain"),
            ("Website", "domain"),
            ("LinkedIn Text", "raw_text"),
            ("City", "location"),
        ],
    )
    def test_known_aliases(self, raw, expected):
        assert canonicalize_header(raw) == expected

    def test_unknown_header_slugified_not_mapped(self):
        # Pinned V0 gap: "E-mail" is not in the alias map, so it slugs to
        # "e_mail" and the column is silently ignored downstream.
        assert canonicalize_header("E-mail") == "e_mail"

    def test_none_becomes_empty(self):
        assert canonicalize_header(None) == ""


class TestLoadInputFrames:
    def test_csv_loaded_with_provenance(self, tmp_path):
        (tmp_path / "one.csv").write_text(
            "First Name,Company\nJohn,Acme\nJane,Beta\n", encoding="utf-8"
        )
        df = load_input_frames([tmp_path / "one.csv"])
        assert list(df["first_name"]) == ["John", "Jane"]
        assert list(df["company_name"]) == ["Acme", "Beta"]
        assert set(df["source_file"]) == {"one.csv"}
        assert list(df["source_row_number"]) == [2, 3]

    def test_row_numbers_wrong_across_multiple_files(self, tmp_path):
        # Pinned V0 defect (audit 2.3 item 4): source_row_number is the
        # post-concat index + 2, so rows from the second file get numbers
        # continuing after the first file instead of restarting at 2.
        (tmp_path / "a.csv").write_text("Name\nAnn\nBob\n", encoding="utf-8")
        (tmp_path / "b.csv").write_text("Name\nCid\n", encoding="utf-8")
        df = load_input_frames(sorted(tmp_path.glob("*.csv")))
        b_rows = df[df["source_file"] == "b.csv"]
        assert list(b_rows["source_row_number"]) == [4]  # should be [2]

    def test_duplicate_target_columns_coalesced(self, tmp_path):
        (tmp_path / "dup.csv").write_text(
            "Email,Mail\na@x.com,\n,b@y.com\n", encoding="utf-8"
        )
        df = load_input_frames([tmp_path / "dup.csv"])
        assert list(df["email"]) == ["a@x.com", "b@y.com"]

    def test_xlsx_multi_sheet(self, tmp_path):
        path = tmp_path / "book.xlsx"
        with pd.ExcelWriter(path) as writer:
            pd.DataFrame({"Full Name": ["Ann Lee"]}).to_excel(
                writer, sheet_name="S1", index=False
            )
            pd.DataFrame({"Full Name": ["Bob Ray"]}).to_excel(
                writer, sheet_name="S2", index=False
            )
        df = load_input_frames([path])
        assert sorted(df["full_name"]) == ["Ann Lee", "Bob Ray"]
        assert sorted(set(df["source_sheet"])) == ["S1", "S2"]

    def test_no_files_raises(self):
        with pytest.raises(FileNotFoundError):
            load_input_frames([])
