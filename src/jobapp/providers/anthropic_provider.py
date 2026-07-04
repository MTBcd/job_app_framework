"""Anthropic adapter for the AIProvider port.

Uses the Messages API with structured outputs (output_config.format ->
json_schema) so every response parses. Meters tokens, cost, latency, and
prompt version into AiUsage. Raises AiProviderError on failure — services
catch it and fall back to the deterministic fake (never dead-end).

Note on sampling: temperature/top_p are REMOVED on claude-opus-4-8/4.7,
claude-sonnet-5, and claude-fable-5 (the API returns 400). The adapter only
sends temperature on models known to accept it.
"""
from __future__ import annotations

import json
import logging
import time

import anthropic

from jobapp.providers import AiProviderError, AiUsage
from jobapp.providers.prompts import (
    CV_SCHEMA,
    CV_SYSTEM,
    EMAIL_SCHEMA,
    EMAIL_SYSTEM,
    PLAN_SCHEMA,
    PLAN_SYSTEM,
    PROMPT_VERSION,
    cv_user_message,
    email_user_message,
    plan_user_message,
)
from jobapp.settings import get_settings

logger = logging.getLogger("jobapp.ai")

# $/MTok (input, output) — claude-api reference, cached 2026-06.
# Sonnet 5 sticker price used (intro pricing ignored for conservative margins).
PRICES_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-opus-4-8": (5.00, 25.00),
    "claude-opus-4-7": (5.00, 25.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-fable-5": (10.00, 50.00),
}

# Models that still accept a temperature parameter. Current-generation
# models (Opus 4.7+, Sonnet 5, Fable 5) reject it with a 400.
TEMPERATURE_ALLOWED = {"claude-sonnet-4-6", "claude-haiku-4-5", "claude-opus-4-6"}

DEFAULT_TIMEOUT_SECONDS = 45.0
DEFAULT_MAX_TOKENS = 2000


def estimate_cost_cents(model: str, tokens_in: int, tokens_out: int) -> float:
    price_in, price_out = PRICES_PER_MTOK.get(model, (5.00, 25.00))
    return round((tokens_in * price_in + tokens_out * price_out) / 1_000_000 * 100, 4)


class AnthropicProvider:
    def __init__(
        self,
        *,
        model: str | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float | None = None,
        client: anthropic.Anthropic | None = None,
    ) -> None:
        settings = get_settings()
        self.model = model or settings.ai_model
        self.max_tokens = max_tokens
        self.temperature = temperature
        # api_key=None lets the SDK resolve ANTHROPIC_API_KEY itself.
        self._client = client or anthropic.Anthropic(
            api_key=settings.anthropic_api_key or None,
            timeout=timeout,
            max_retries=2,
        )

    # ---- AIProvider protocol -------------------------------------------
    def parse_cv(self, cv_text: str) -> tuple[dict, AiUsage]:
        return self._structured_call(
            kind="parse_cv",
            system=CV_SYSTEM,
            user_message=cv_user_message(cv_text),
            schema=CV_SCHEMA,
        )

    def personalization_plan(self, inputs: dict) -> tuple[dict, AiUsage]:
        return self._structured_call(
            kind="personalization_plan",
            system=PLAN_SYSTEM,
            user_message=plan_user_message(inputs),
            schema=PLAN_SCHEMA,
        )

    def tailored_email(self, inputs: dict, plan: dict) -> tuple[dict, AiUsage]:
        return self._structured_call(
            kind="tailored_email",
            system=EMAIL_SYSTEM,
            user_message=email_user_message(inputs, plan),
            schema=EMAIL_SCHEMA,
        )

    # ---- internals ------------------------------------------------------
    def _structured_call(
        self, *, kind: str, system: str, user_message: str, schema: dict
    ) -> tuple[dict, AiUsage]:
        request: dict = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user_message}],
            "output_config": {"format": {"type": "json_schema", "schema": schema}},
        }
        if self.temperature is not None and self.model in TEMPERATURE_ALLOWED:
            request["temperature"] = self.temperature

        started = time.monotonic()
        try:
            response = self._client.messages.create(**request)
        except anthropic.APIStatusError as exc:
            logger.error("ai call failed kind=%s model=%s status=%s",
                         kind, self.model, exc.status_code)
            raise AiProviderError(f"{kind}: api_status_{exc.status_code}") from exc
        except anthropic.APIConnectionError as exc:
            logger.error("ai connection failed kind=%s model=%s", kind, self.model)
            raise AiProviderError(f"{kind}: connection_error") from exc
        latency_ms = int((time.monotonic() - started) * 1000)

        if response.stop_reason == "refusal":
            raise AiProviderError(f"{kind}: refusal")
        if response.stop_reason == "max_tokens":
            raise AiProviderError(f"{kind}: truncated_at_max_tokens")

        text = next(
            (block.text for block in response.content if block.type == "text"), ""
        )
        try:
            output = json.loads(text)
        except json.JSONDecodeError as exc:
            raise AiProviderError(f"{kind}: invalid_json_output") from exc

        usage = AiUsage(
            model=self.model,
            tokens_in=response.usage.input_tokens,
            tokens_out=response.usage.output_tokens,
            cost_cents=estimate_cost_cents(
                self.model, response.usage.input_tokens, response.usage.output_tokens
            ),
            latency_ms=latency_ms,
            prompt_version=PROMPT_VERSION,
        )
        logger.info(
            "ai call kind=%s model=%s in=%s out=%s cost_cents=%.3f latency_ms=%s",
            kind, self.model, usage.tokens_in, usage.tokens_out,
            usage.cost_cents, usage.latency_ms,
        )
        return output, usage
