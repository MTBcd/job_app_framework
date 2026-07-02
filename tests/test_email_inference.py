"""Characterization tests for jobapp.email_inference — the V0 inference core."""
from __future__ import annotations

import json

import pandas as pd
import pytest

from jobapp.email_inference import (
    apply_email_inference,
    generate_pattern_emails,
    learn_domain_patterns,
    score_candidates,
)


class TestGeneratePatternEmails:
    def test_full_pattern_set_for_simple_name(self):
        generated = generate_pattern_emails("John", "Smith", "acme.com")
        emails = {email for _, email, _ in generated}
        assert emails == {
            "john.smith@acme.com",
            "john@acme.com",
            "johnsmith@acme.com",
            "jsmith@acme.com",
            "j.smith@acme.com",
            "john_s@acme.com",
            "john_smith@acme.com",
            "smith.john@acme.com",
            "smith@acme.com",
        }

    def test_initial_only_first_name_restricted_to_safe_patterns(self):
        generated = generate_pattern_emails("J", "Smith", "acme.com")
        patterns = {pattern for pattern, _, _ in generated}
        # V0 refuses to invent a full first name from an initial.
        assert patterns == {"flast", "f.last"}

    def test_particle_surname_produces_both_variants(self):
        generated = generate_pattern_emails("John", "de la Fontaine", "acme.com")
        emails = {email for _, email, _ in generated}
        assert "john.delafontaine@acme.com" in emails
        assert "john.fontaine@acme.com" in emails

    def test_accented_names_normalized(self):
        generated = generate_pattern_emails("Émile", "Côté", "acme.com")
        emails = {email for _, email, _ in generated}
        assert "emile.cote@acme.com" in emails

    def test_no_domain_no_candidates(self):
        assert generate_pattern_emails("John", "Smith", "") == []

    def test_missing_name_part_no_candidates(self):
        assert generate_pattern_emails("", "Smith", "acme.com") == []
        assert generate_pattern_emails("John", "", "acme.com") == []


class TestScoreCandidates:
    def test_first_dot_last_is_default_top(self):
        candidates = score_candidates("John", "Smith", "acme.com")
        assert candidates[0].email == "john.smith@acme.com"
        assert candidates[0].pattern == "first.last"
        # prior 0.66 - 0.10 missing_domain_source penalty
        assert candidates[0].confidence == pytest.approx(0.56)

    def test_trusted_domain_source_boosts(self):
        candidates = score_candidates(
            "John", "Smith", "acme.com", domain_source="from_existing_domain_or_email"
        )
        assert candidates[0].confidence == pytest.approx(0.78)

    def test_heuristic_domain_penalized(self):
        base = score_candidates("John", "Smith", "acme.com")[0].confidence
        heuristic = score_candidates(
            "John", "Smith", "acme.com", domain_source="heuristic_company_to_com"
        )[0].confidence
        assert heuristic < base

    def test_learned_domain_pattern_outranks_prior(self):
        candidates = score_candidates(
            "John",
            "Smith",
            "acme.com",
            known_pattern_info={"pattern": "flast", "share": 1.0, "count": 3},
        )
        assert candidates[0].pattern == "flast"
        assert candidates[0].email == "jsmith@acme.com"
        assert "matches_learned_domain_pattern" in candidates[0].reasoning

    def test_verified_pattern_forces_floor(self):
        candidates = score_candidates(
            "John",
            "Smith",
            "acme.com",
            domain_source="from_verified_pattern_file",
            verified_pattern_info={
                "email_pattern": "last.first",
                "domain": "acme.com",
                "confidence": 0.95,
            },
        )
        assert candidates[0].pattern == "last.first"
        assert candidates[0].confidence >= 0.95

    def test_reasoning_trace_present_on_every_candidate(self):
        for candidate in score_candidates("John", "Smith", "acme.com"):
            assert candidate.reasoning
            assert any(reason.startswith("pattern=") for reason in candidate.reasoning)

    def test_confidence_clamped_to_bounds(self):
        for candidate in score_candidates("J", "Smith", "acme.com"):
            assert 0.05 <= candidate.confidence <= 0.99


class TestLearnDomainPatterns:
    def test_learns_majority_pattern_per_domain(self):
        df = pd.DataFrame(
            {
                "first_name": ["Ann", "Bob", "Cid"],
                "last_name": ["Lee", "Ray", "Fox"],
                "email": ["alee@acme.com", "bray@acme.com", "cid.fox@beta.com"],
            }
        )
        learned = learn_domain_patterns(df)
        assert learned["acme.com"]["pattern"] == "flast"
        assert learned["acme.com"]["count"] == 2
        assert learned["beta.com"]["pattern"] == "first.last"

    def test_rows_without_valid_email_ignored(self):
        df = pd.DataFrame(
            {"first_name": ["Ann"], "last_name": ["Lee"], "email": ["not-an-email"]}
        )
        assert learn_domain_patterns(df) == {}


@pytest.fixture()
def isolated_env(tmp_path, monkeypatch):
    """Isolate inference from the repo's learning CSV and pattern file."""
    monkeypatch.setenv("LEARNING_FEEDBACK_PATH", str(tmp_path / "lf.csv"))
    monkeypatch.chdir(tmp_path)
    return tmp_path


class TestApplyEmailInference:
    def test_provided_valid_email_selected_verbatim(self, isolated_env):
        df = pd.DataFrame(
            {
                "first_name": ["Jane"],
                "last_name": ["Doe"],
                "email": ["jane.doe@corp.com"],
                "company_name": ["Corp"],
                "company_normalized": ["corp"],
                "company_domain": ["corp.com"],
                "domain": [""],
                "domain_source": ["from_existing_domain_or_email"],
            }
        )
        out = apply_email_inference(df)
        assert out.loc[0, "email_selected"] == "jane.doe@corp.com"
        assert out.loc[0, "email_pattern"] == "provided"
        assert out.loc[0, "email_confidence"] == 1.0
        assert bool(out.loc[0, "email_selected_is_valid"]) is True

    def test_inferred_email_with_candidates_json(self, isolated_env):
        df = pd.DataFrame(
            {
                "first_name": ["John"],
                "last_name": ["Smith"],
                "email": [""],
                "company_name": ["Acme"],
                "company_normalized": ["acme"],
                "company_domain": ["acme.com"],
                "domain": [""],
                "domain_source": ["from_existing_domain_or_email"],
            }
        )
        out = apply_email_inference(df)
        assert out.loc[0, "email_selected"] == "john.smith@acme.com"
        candidates = json.loads(out.loc[0, "email_candidates_json"])
        assert len(candidates) == 9
        assert candidates[0]["pattern"] == "first.last"
        assert candidates[0]["reasoning"]

    def test_low_confidence_flags_manual_review(self, isolated_env):
        df = pd.DataFrame(
            {
                "first_name": ["John"],
                "last_name": ["Smith"],
                "email": [""],
                "company_name": ["Acme"],
                "company_normalized": ["acme"],
                "company_domain": ["acme.com"],
                "domain": [""],
                "domain_source": ["heuristic_company_to_com"],
            }
        )
        out = apply_email_inference(df)
        assert bool(out.loc[0, "needs_manual_review"]) is True
        assert "heuristic_domain" in out.loc[0, "manual_review_reason"]

    def test_no_data_flags_no_candidates(self, isolated_env):
        df = pd.DataFrame(
            {
                "first_name": [""],
                "last_name": [""],
                "email": [""],
                "company_name": [""],
                "company_normalized": [""],
                "company_domain": [""],
                "domain": [""],
                "domain_source": [""],
            }
        )
        out = apply_email_inference(df)
        assert out.loc[0, "email_selected"] == ""
        assert bool(out.loc[0, "needs_manual_review"]) is True
        assert "no_email_candidates" in out.loc[0, "manual_review_reason"]
