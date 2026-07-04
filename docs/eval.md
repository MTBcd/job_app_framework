# Evaluating AI Personalization Quality

## Commands

```bash
pip install -e ".[dev]"

# Full golden-set eval (10 scenarios, automatic checks, writes evals/last_run.json)
PYTHONPATH=src:. python3 scripts/run_eval.py

# 3-scenario demo with plans, emails, cost and latency
PYTHONPATH=src:. python3 scripts/demo_ai_quality.py

# Real outputs: set a key first (never required for tests)
export ANTHROPIC_API_KEY=sk-ant-...
PYTHONPATH=src:. python3 scripts/run_eval.py
```

Without a key both scripts run the deterministic fake (plumbing + contract
verification). With a key they use `AnthropicProvider` — model from `AI_MODEL`
(default `claude-opus-4-8`; drop to `claude-sonnet-5` after quality parity is
confirmed). A full 10-scenario real run ≈ 20 calls, est. **$0.30–0.60** on
Opus 4.8. Cost/latency/prompt-version are printed per scenario and stored in
`ai_runs` when generation runs inside the app.

## What the automatic checks catch (`evals/checks.py`)

word count 120–180 (real provider) · forbidden AI-cliché phrases
(`providers/prompts.py::FORBIDDEN_PHRASES`) · scenario-specific prohibited
claims (hallucination tripwires — facts absent from the inputs) · required
grounding terms present · non-generic subject · call to action ·
**numbers grounding** (every digit in the email must appear in the inputs —
cheap fabrication detector) · no bullet points.

Automatic checks are necessary, not sufficient — they catch violations, not
blandness. Judge real outputs manually.

## Manual rubric (score each 1–5, target ≥ 4)

1. **Specific** — could this email have been sent to a different company
   unchanged? (If yes: 1.)
2. **Credible** — does every claim sound like the candidate's real history?
   Check `claims_used` traceability against the inputs.
3. **Human** — read it aloud. Any phrase a person wouldn't say?
4. **Honest under missing data** — for low-confidence scenarios
   (marketing_grad) the email must get *more general*, never invent.
5. **Career-changer honesty** — the career_changer scenario must own the
   transition, not disguise it.
6. **Better than generic ChatGPT** — paste the same inputs into a plain
   "write an application email" prompt; ours must be clearly tighter,
   less flattering, more grounded.

## Prompt iteration loop

1. Edit `src/jobapp/providers/prompts.py`; **bump `PROMPT_VERSION`**.
2. `python3 scripts/run_eval.py` with a key; compare `evals/last_run.json`
   against the previous run (commit the diff summary in the PR, never the
   raw file — it is gitignored).
3. Tests pin the contract: `pytest tests/test_ai_quality.py`.

## Privacy & safety notes

Inputs sent to the model are the structured profile/opportunity/research JSON
only — never raw CV text at generation time (parse-once at upload). The
adapter refuses to overstate: provider failures fall back to the deterministic
template and flag `ai_generation_failed` for human review.
