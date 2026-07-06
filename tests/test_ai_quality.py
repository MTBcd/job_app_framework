"""AI personalization layer: prompt contracts, eval contract, adapter unit
tests (stubbed SDK client — no network, no API key required)."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from evals.checks import run_checks, score
from evals.golden_set import SCENARIOS, scenario_inputs
from jobapp.providers import AiProviderError
from jobapp.providers.anthropic_provider import (
    AnthropicProvider,
    estimate_cost_cents,
)
from jobapp.providers.fakes import FakeAIProvider
from jobapp.providers.prompts import (
    EMAIL_SCHEMA,
    EMAIL_SYSTEM,
    FORBIDDEN_PHRASES,
    PLAN_SCHEMA,
    PLAN_SYSTEM,
    PROMPT_VERSION,
    email_user_message,
    plan_user_message,
)


class TestPromptContracts:
    def test_golden_set_has_ten_scenarios(self):
        assert len(SCENARIOS) == 10
        assert len({s["id"] for s in SCENARIOS}) == 10

    def test_grounding_rules_in_every_system_prompt(self):
        for system in (PLAN_SYSTEM, EMAIL_SYSTEM):
            assert "NEVER invent" in system
            assert "candidate_profile" in system

    def test_forbidden_phrases_embedded_in_email_prompt(self):
        assert "i hope this email finds you well" in EMAIL_SYSTEM.lower()
        assert "120-180 words" in EMAIL_SYSTEM

    def test_p2_rules_present(self):
        # Company must be named exactly, once, in the body
        assert "EXACT official name" in EMAIL_SYSTEM
        assert "shortened" in EMAIL_SYSTEM and "possessive" in EMAIL_SYSTEM
        # Career-changer identity rule
        assert "previous professional" in EMAIL_SYSTEM
        assert "never as an apology" in EMAIL_SYSTEM
        # Subject format rule
        assert "application — " in EMAIL_SYSTEM
        assert "Introduction — " in EMAIL_SYSTEM
        assert "never salesy" in EMAIL_SYSTEM

    def test_schemas_are_strict(self):
        for schema in (PLAN_SCHEMA, EMAIL_SCHEMA):
            assert schema["additionalProperties"] is False
            assert set(schema["required"]) == set(schema["properties"].keys())

    def test_user_messages_carry_only_serialized_inputs(self):
        inputs = scenario_inputs(SCENARIOS[0])
        message = plan_user_message(inputs)
        assert json.dumps(inputs["company_name"]) [1:-1] in message
        assert "Produce the personalization plan" in message
        email_msg = email_user_message(inputs, {"angle": "x"})
        assert "PERSONALIZATION PLAN" in email_msg


class TestFakeProviderMeetsEvalContract:
    @pytest.mark.parametrize("scenario", SCENARIOS, ids=[s["id"] for s in SCENARIOS])
    def test_scenario_passes_contract_checks(self, scenario):
        fake = FakeAIProvider()
        inputs = scenario_inputs(scenario)
        plan, _ = fake.personalization_plan(inputs)
        assert plan["call_to_action"]  # structured, not prose
        email, _ = fake.tailored_email(inputs, plan)
        results = run_checks(scenario, email["subject"], email["body"],
                             strict_length=False)
        passed, total = score(results)
        failing = [r for r in results if not r.passed]
        assert passed == total, f"failed: {[(r.name, r.detail) for r in failing]}"

    def test_email_carries_claim_traceability(self):
        fake = FakeAIProvider()
        inputs = scenario_inputs(SCENARIOS[0])
        plan, _ = fake.personalization_plan(inputs)
        email, _ = fake.tailored_email(inputs, plan)
        assert email["claims_used"]
        assert all(c["grounded_in"] for c in email["claims_used"])


def _stub_response(payload: dict, *, stop_reason="end_turn", tokens=(1200, 400)):
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=[SimpleNamespace(type="text", text=json.dumps(payload))],
        usage=SimpleNamespace(input_tokens=tokens[0], output_tokens=tokens[1]),
    )


def _stub_client(response=None, error=None):
    def create(**request):
        _stub_client.last_request = request
        if error is not None:
            raise error
        return response

    return SimpleNamespace(messages=SimpleNamespace(create=create))


class TestAnthropicAdapter:
    def test_structured_call_parses_and_meters(self):
        payload = {"subject": "s", "body": "b", "claims_used": []}
        provider = AnthropicProvider(
            model="claude-opus-4-8",
            client=_stub_client(_stub_response(payload)),
        )
        output, usage = provider.tailored_email({"company_name": "X"}, {"angle": "a"})
        assert output == payload
        assert usage.model == "claude-opus-4-8"
        assert usage.tokens_in == 1200 and usage.tokens_out == 400
        # 1200*$5/MTok + 400*$25/MTok = $0.016 = 1.6 cents
        assert usage.cost_cents == pytest.approx(1.6)
        assert usage.prompt_version == PROMPT_VERSION
        assert usage.latency_ms >= 0

    def test_request_uses_structured_outputs_and_no_temperature(self):
        payload = {"subject": "s", "body": "b", "claims_used": []}
        provider = AnthropicProvider(
            model="claude-opus-4-8", temperature=0.7,
            client=_stub_client(_stub_response(payload)),
        )
        provider.tailored_email({}, {})
        request = _stub_client.last_request
        # temperature must NOT be sent on Opus 4.8 (API rejects it with 400)
        assert "temperature" not in request
        assert request["output_config"]["format"]["type"] == "json_schema"
        assert request["model"] == "claude-opus-4-8"

    def test_temperature_sent_only_on_supporting_models(self):
        payload = {"subject": "s", "body": "b", "claims_used": []}
        provider = AnthropicProvider(
            model="claude-haiku-4-5", temperature=0.5,
            client=_stub_client(_stub_response(payload)),
        )
        provider.tailored_email({}, {})
        assert _stub_client.last_request["temperature"] == 0.5

    def test_refusal_raises_provider_error(self):
        provider = AnthropicProvider(
            model="claude-opus-4-8",
            client=_stub_client(_stub_response({}, stop_reason="refusal")),
        )
        with pytest.raises(AiProviderError, match="refusal"):
            provider.personalization_plan({})

    def test_invalid_json_raises_provider_error(self):
        broken = SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text="not json")],
            usage=SimpleNamespace(input_tokens=1, output_tokens=1),
        )
        provider = AnthropicProvider(model="claude-opus-4-8",
                                     client=_stub_client(broken))
        with pytest.raises(AiProviderError, match="invalid_json"):
            provider.personalization_plan({})

    def test_cost_table(self):
        assert estimate_cost_cents("claude-sonnet-5", 1_000_000, 0) == pytest.approx(300)
        assert estimate_cost_cents("claude-haiku-4-5", 0, 1_000_000) == pytest.approx(500)


class TestGenerationFallback:
    def test_pipeline_survives_provider_failure(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/f.db")
        monkeypatch.setenv("APP_ENV", "local")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "")
        from jobapp import db as db_module
        from jobapp import settings as settings_module

        settings_module.get_settings.cache_clear()
        db_module.get_engine.cache_clear()
        db_module.get_sessionmaker.cache_clear()
        try:
            from jobapp.db import get_engine, get_sessionmaker
            from jobapp.db.models import Base, User
            from jobapp.services.applications import create_application
            from jobapp.services.pipeline import prepare_application

            Base.metadata.create_all(get_engine())
            session = get_sessionmaker()()
            user = User(clerk_user_id="f1", email="f@test.io")
            session.add(user)
            session.flush()
            application = create_application(
                session, user, company_name="Beta LLC", contact_name="Ann Lee"
            )

            class ExplodingAI:
                def personalization_plan(self, inputs):
                    raise AiProviderError("boom")

                def tailored_email(self, inputs, plan):
                    raise AiProviderError("boom")

            prepare_application(session, application.id, ai_provider=ExplodingAI())
            session.refresh(application)
            assert application.status == "ready_for_review"
            assert application.body  # fake fallback content, never empty
            assert "ai_generation_failed" in application.review_reasons
            session.close()
        finally:
            settings_module.get_settings.cache_clear()
            db_module.get_engine.cache_clear()
            db_module.get_sessionmaker.cache_clear()
