"""Characterization tests for jobapp.company — domain resolution precedence."""
from __future__ import annotations

import pandas as pd

from jobapp.company import infer_company_domain, normalize_company_fields
from jobapp.learning import LearningEvent, LearningStore


class TestInferCompanyDomain:
    def test_existing_domain_wins_over_everything(self):
        domain, source = infer_company_domain(
            "Goldman Sachs", existing_domain="www.Foo.com"
        )
        assert (domain, source) == ("foo.com", "from_existing_domain_or_email")

    def test_existing_email_used_when_no_domain(self):
        domain, source = infer_company_domain("Acme", existing_email="j@acme.io")
        assert (domain, source) == ("acme.io", "from_existing_domain_or_email")

    def test_curated_override_hit(self):
        domain, source = infer_company_domain("Goldman Sachs")
        assert (domain, source) == ("gs.com", "from_company_override")

    def test_override_matches_after_suffix_stripping(self):
        domain, source = infer_company_domain("Goldman Sachs Group Inc.")
        assert (domain, source) == ("gs.com", "from_company_override")

    def test_known_bad_heuristic_domain_is_fixed(self):
        domain, _ = infer_company_domain("X", existing_domain="sulife.com")
        assert domain == "sunlife.com"

    def test_heuristic_fallback_appends_dot_com(self):
        domain, source = infer_company_domain("Acme Rockets")
        assert (domain, source) == ("acmerockets.com", "heuristic_company_to_com")

    def test_missing_company(self):
        assert infer_company_domain("") == ("", "missing_company")

    def test_learning_feedback_used_before_heuristic(self, tmp_path):
        store = LearningStore(tmp_path / "lf.csv")
        store.append(
            LearningEvent(
                event_type="replied",
                company_normalized="zeta widgets",
                domain="zeta.io",
            )
        )
        domain, source = infer_company_domain("Zeta Widgets", learning_store=store)
        assert (domain, source) == ("zeta.io", "from_learning_feedback")


class TestNormalizeCompanyFields:
    def test_adds_domain_and_source_columns(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LEARNING_FEEDBACK_PATH", str(tmp_path / "lf.csv"))
        monkeypatch.chdir(tmp_path)  # isolate from repo-level pattern file
        df = pd.DataFrame(
            {
                "company_name": ["Goldman Sachs", "Acme Rockets"],
                "domain": ["", ""],
                "email": ["", ""],
            }
        )
        out = normalize_company_fields(df)
        assert list(out["company_domain"]) == ["gs.com", "acmerockets.com"]
        assert list(out["domain_source"]) == [
            "from_company_override",
            "heuristic_company_to_com",
        ]
        assert out.loc[0, "company_normalized"] == "goldman sachs"
