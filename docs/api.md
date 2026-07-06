# API & Vertical Slice — Developer Guide

## Run the demo (no keys, no network)

```bash
pip install -e ".[dev]"
PYTHONPATH=src python3 scripts/demo_vertical_slice.py
```

Prints all 16 slice steps: profile → opportunity → research (with provenance)
→ contact selection (with reasoning) → email resolution (with confidence,
source, honest label) → personalization plan → tailored draft → edit →
approve → send (fake transport proves it received the **exact** approved
body) → reply → privacy-safe learning events.

Run the API: `PYTHONPATH=src APP_ENV=local uvicorn jobapp.api.app:app --reload`
Worker: `PYTHONPATH=src python3 -m jobapp.worker` · Tests: `pytest` (183)

## Auth (dev)

`APP_ENV=local` + header `X-Dev-User-Email: you@example.com` — lazily creates
the user. Clerk JWT verification replaces this dependency later; routes are
agnostic.

## Endpoints

| Method & path | Purpose |
|---|---|
| `GET /health` | liveness |
| `POST /cv` `{content_text, filename?}` | upload CV; parsed **once** into a structured profile (source of truth) |
| `GET /cv` | CV + parsed profile |
| `PUT /cv/profile` `{parsed_profile}` | user correction of the extracted profile |
| `POST /applications` `{company_name, role?, jd_text?, jd_url?, location?, notes?, contact_name?, contact_title?, tone?}` | create opportunity + application, queue pipeline. Company-only is first-class. 402 free cap · 409 duplicate company |
| `GET /applications?status=` | tracker list |
| `GET /applications/{id}` | full review pack: research (facts with source/url/timestamp/confidence), contact rationale, email provenance (`email_source`, `email_pattern`, `email_confidence`, `email_label`), personalization plan, candidates with reasoning |
| `GET /applications/{id}/status` | pipeline polling `{status, pipeline_stage}` |
| `PATCH /applications/{id}` `{subject?, body?}` | edit draft (409 once sent) |
| `POST /applications/{id}/approve` `{subject?, body?}` | freeze the approved snapshot |
| `POST /applications/{id}/send` | preflight + send the snapshot. 409 reasons: `not_approved`, `invalid_recipient`, `blocked_consumer_domain`, `suppressed_recipient`, `duplicate_recipient`, `daily_cap_reached` |

## Contracts

**Approved-exactly-sent.** `approve` snapshots subject/body; `send` consumes
only the snapshot and never re-runs research/inference/generation. Regression:
`tests/test_vertical_slice.py::test_complete_vertical_slice` (post-approval
tampering demonstrably not sent). This closes V0 audit defect 2.3(1).

**Email labels never overstate.** `provided → Verified` · `curated_pattern /
learned_pattern → Known pattern` · heuristic → `High-/Low-confidence
inference` (V0 threshold 0.72) · none → `Manual review required`. Inferred
addresses are never labeled Verified.

**Research provenance.** Every fact: `{fact, source, source_url, retrieved_at,
confidence}`. Providers must degrade (fewer facts, lower confidence →
`limited_research` review flag) rather than invent.

**Privacy boundary (learning).** Learning events store only
`domain + email_pattern + weight` (V0 weights: sent +1.0, replied +4.0,
hard bounce −3.0…). `payload` stays empty; no names, addresses, or CV content
— cross-user aggregation cannot leak personal data. Regression in the slice
test asserts this on every event.

## Provider ports (`jobapp/providers/`)

`AIProvider` (parse_cv, personalization_plan, tailored_email) ·
`ResearchProvider` · `EmailProvider` (send). Deterministic fakes back tests
and the demo; factories fall back to fakes whenever credentials are absent.
Real adapters (Anthropic, web research, SMTP live / Gmail OAuth) plug in
without touching services.
