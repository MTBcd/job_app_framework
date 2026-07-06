"""AI personalization demo: plan + tailored email for 3 golden scenarios.

    PYTHONPATH=src:. python3 scripts/demo_ai_quality.py             # fake
    ANTHROPIC_API_KEY=... PYTHONPATH=src:. python3 scripts/demo_ai_quality.py  # real

With a key set, this makes ~6 API calls (est. < $0.15 on claude-opus-4-8).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from evals.golden_set import SCENARIOS, scenario_inputs  # noqa: E402

DEMO_IDS = ("junior_swe", "marketing_grad", "career_changer")


def main() -> None:
    from jobapp.providers import get_ai_provider

    provider = get_ai_provider()
    print(f"Provider: {type(provider).__name__}\n{'=' * 62}")

    for scenario in (s for s in SCENARIOS if s["id"] in DEMO_IDS):
        inputs = scenario_inputs(scenario)
        plan, plan_usage = provider.personalization_plan(inputs)
        email, email_usage = provider.tailored_email(inputs, plan)

        print(f"\n▌ {scenario['label']}  ({scenario['id']})")
        print(f"  angle: {plan.get('angle', '')}")
        print(f"  gaps flagged: {plan.get('gaps_to_avoid_overclaiming', [])}")
        print(f"  excluded facts: {[f['fact'] for f in plan.get('excluded_facts', [])]}")
        print(f"\n  Subject: {email['subject']}\n")
        for line in email["body"].splitlines():
            print(f"  {line}")
        cost = plan_usage.cost_cents + email_usage.cost_cents
        latency = plan_usage.latency_ms + email_usage.latency_ms
        print(f"\n  [model={plan_usage.model} prompt={plan_usage.prompt_version or '-'}"
              f" cost={cost:.2f}¢ latency={latency}ms"
              f" words={len(email['body'].split())}]")
        print("=" * 62)


if __name__ == "__main__":
    os.environ.setdefault("APP_ENV", "local")
    main()
