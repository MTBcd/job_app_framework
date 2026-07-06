"""Golden-set evaluation runner.

    PYTHONPATH=src:. python3 scripts/run_eval.py            # fake provider
    ANTHROPIC_API_KEY=... PYTHONPATH=src:. python3 scripts/run_eval.py   # real

Writes evals/last_run.json (gitignored) and prints a per-scenario table plus
the outputs for manual review (rubric in docs/eval.md).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from evals.checks import run_checks, score  # noqa: E402
from evals.golden_set import SCENARIOS, scenario_inputs  # noqa: E402


def main() -> int:
    from jobapp.providers import get_ai_provider

    provider = get_ai_provider()
    provider_name = type(provider).__name__
    is_real = provider_name == "AnthropicProvider"
    print(f"Provider: {provider_name}  (strict length checks: {is_real})\n")

    report, total_pass, total_checks, total_cost = [], 0, 0, 0.0
    for scenario in SCENARIOS:
        inputs = scenario_inputs(scenario)
        plan, plan_usage = provider.personalization_plan(inputs)
        email, email_usage = provider.tailored_email(inputs, plan)
        total_cost += plan_usage.cost_cents + email_usage.cost_cents

        results = run_checks(scenario, email["subject"], email["body"],
                             strict_length=is_real)
        passed, count = score(results)
        total_pass += passed
        total_checks += count

        status = "PASS" if passed == count else f"{passed}/{count}"
        print(f"[{status:>5}] {scenario['id']:<18} {scenario['label']}")
        for r in results:
            if not r.passed:
                print(f"         ✗ {r.name}: {r.detail}")

        report.append({
            "id": scenario["id"], "subject": email["subject"],
            "body": email["body"], "plan": plan,
            "checks": [{"name": r.name, "passed": r.passed, "detail": r.detail}
                       for r in results],
            "cost_cents": round(plan_usage.cost_cents + email_usage.cost_cents, 3),
            "latency_ms": plan_usage.latency_ms + email_usage.latency_ms,
        })

    print(f"\nTotal: {total_pass}/{total_checks} checks passed"
          f"  ·  est. cost: {total_cost:.2f}¢ for {len(SCENARIOS)} scenarios")
    out = ROOT / "evals" / "last_run.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Full outputs: {out}  (manual rubric: docs/eval.md)")

    print("\n--- Sample outputs " + "-" * 40)
    for entry in report[:3]:
        print(f"\n### {entry['id']}\nSubject: {entry['subject']}\n\n{entry['body']}")
    return 0 if total_pass == total_checks else 1


if __name__ == "__main__":
    os.environ.setdefault("APP_ENV", "local")
    raise SystemExit(main())
