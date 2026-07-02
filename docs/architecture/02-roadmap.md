# Roadmap — independently deployable milestones (Step 6)

**Rules applied to every milestone:** ships green (lint, mypy on core, tests), deployable on its own, small PRs, no milestone depends on a future one to be useful. Each PR carries: purpose, architecture decision, files, future improvements, risks.

Sequencing logic: security first (hours, not days), then the typed core extraction (it de-risks everything else and is pure porting work), then the platform substrate, then product surface, then intelligence, then scale-out. The V0 CLI keeps working for the founder's own job search until M4 replaces it — we never break the only current user.

---

## M0 — Security remediation & repo baseline *(≈1 day; do immediately)*

**Scope**
- Rotate Gmail app passwords (owner action, blocking).
- `git filter-repo` purge: `.env`, `.venvmail/`, `__pycache__`, all xlsx/csv data & logs; force-push rewritten `main` (single-commit repo — cheapest moment ever).
- Add `.gitignore`, `.env.example`, `pyproject.toml` (ruff, mypy, pytest config), pinned deps, LICENSE, minimal CI (lint + compile + gitleaks + GitHub push protection).
- Move real data to local-only storage outside the repo.

**Exit criteria:** fresh clone contains zero secrets/PII; CI green on a no-op PR; gitleaks passes on full history.
**Risks:** history rewrite invalidates existing clones (acceptable: one user); *not* rotating credentials makes everything else pointless — rotation is non-negotiable.

---

## M1 — Typed core extraction (`jobapp-core`) *(≈1–1.5 weeks)*

**Scope**
- Port, with characterization tests pinning V0 behavior first: name parsing → `core/identity`; cleaning primitives; pattern generation + scoring + review flags → `core/inference`; bounce/reply classifiers → `core/deliverability`; send-policy rules → `core/sending/policy.py`; learning weights/aggregation → `core/learning` (in-memory + file adapters for now).
- Pydantic entities (`Contact`, `Company`, `EmailCandidate`, `SendDecision`, …) replace DataFrame rows. Single email/domain validation module (kills the three disagreeing regexes).
- Fix, each with its own test, the audited algorithm bugs: `source_row_number` after concat, learning pollution from `provided/gmail.com` events, initials-only dual source of truth, O(n²) aggregate re-reads (aggregate once per run).
- Thin CLI (`jobapp prepare/send/...`) re-wired onto the core so the founder's workflow keeps functioning identically — **including making `send` consume the reviewed file rather than re-inferring** (the audit's #1 workflow bug).

**Exit criteria:** ≥90% coverage on core; V0 golden-run comparison script shows identical outputs except documented bug fixes; founder completes one real prepare→review→send cycle on the new CLI.
**Risks:** hidden behavior coupling in pandas chains — mitigated by golden-file comparisons on the (local, untracked) real dataset.

---

## M2 — Platform substrate: API, Postgres, workers *(≈2 weeks)*

**Scope**
- Monorepo layout (`apps/api`, `infra/`); FastAPI skeleton; pydantic-settings; structlog + Sentry; health/readiness endpoints.
- Postgres schema v1 (identity/tenancy, companies/contacts/email_addresses, campaigns/targets/messages, suppression, learning_events, events outbox) via Alembic; RLS on tenant tables; seeds migrated from V0 dicts (`DOMAIN_OVERRIDES`, display names, pattern CSV → tables with `source='curated_v0'`).
- Celery + Redis wired (echo task + import task); docker-compose dev env; CI deploy to Railway staging.
- Import service v1: upload CSV/XLSX → column mapping (V0 alias map) → contacts/companies rows → inference task → candidates persisted with reasoning.

**Exit criteria:** `docker compose up` gives working API+worker+db; an uploaded spreadsheet becomes queryable contacts with inferred emails via API; staging deployed by CI.
**Deployable value:** the founder can already use API+DB instead of CSVs.
**Risks:** schema churn — mitigated by keeping jsonb `enrichment`/`settings` escape hatches and additive-migration discipline.

---

## M3 — Sending engine on user mailboxes *(≈2 weeks)*

**Scope**
- `EmailProvider` port; **Gmail API adapter** (OAuth, offline refresh, encrypted token storage); Resend adapter for product transactional mail. (Graph adapter deferred to M6 — one provider proves the port.)
- Send worker: policy engine (ported rails + suppression + confidence gate) → render template version → send → `messages` row + outbox event, idempotent, `acks_late`.
- Redis token-bucket per mailbox + warm-up ramp; send windows; `List-Unsubscribe` + unsubscribe endpoint writing to suppression.
- Reply/bounce sync v1: Gmail `history.list` cursor polling task; ported classifiers; OOO detection; learning events written.
- Campaign + target state machine (`draft → needs_review → approved → queued → sent → replied/bounced/exhausted/suppressed`).

**Exit criteria:** end-to-end on staging with a test mailbox: import → infer → approve → send → reply detected → learning aggregate updated; suppression honored; dedupe proven under concurrent workers (integration test).
**Risks:** Google OAuth verification lead time for the `gmail.send`/`gmail.readonly` scopes — **start the verification application at M3 kickoff**, use test users meanwhile. Deliverability: enforce warm-up defaults, document SPF/DKIM/DMARC setup for users.

---

## M4 — Product surface: web app v1 *(≈2–3 weeks)*

**Scope**
- Next.js + Clerk (orgs→workspaces) + shadcn/ui shell; PostHog.
- Screens: onboarding (connect Gmail, upload contacts, column mapping), Contacts table (virtualized, confidence chips, "why this email" reasoning popover), Campaign board (state machine columns), **Review queue** — the V0 manual-review gate as the product's core interaction: approve/edit/reject with keyboard-first UX (Linear feel), Inbox v1 (replies threaded to targets), Settings (sending limits, blocklists, suppression).
- Typed API client generated from OpenAPI; Playwright smoke in CI.

**Exit criteria:** a non-technical user completes upload→review→send→see-reply without touching a terminal; founder switches off the CLI for daily use.
**Deployable value:** this is the private-beta cut. Recruit 5–10 job-seeker beta users.
**Risks:** UX scope creep — screens above are the whole v1; everything else is backlog.

---

## M5 — AI layer v1 *(≈2 weeks)*

**Scope**
- `AIProvider` port (Anthropic default; OpenAI adapter) with structured outputs, retries, cost metering → `ai_runs`.
- Knowledge base: resume upload + background Q&A → `knowledge_items` with pgvector embeddings.
- **Personalization Agent:** per-target drafts grounded in contact/company/knowledge; drafts land in the review queue (autonomy level: draft-only).
- **Reply Analysis Agent:** classify replies (interested/decline/OOO/referral) → refined learning weights + inbox labels.
- Eval harness: golden sets for both agents in CI; prompt versions pinned per message.

**Exit criteria:** AI drafts measurably reduce edit-rate vs template drafts on beta cohort (PostHog funnel); cost per drafted message tracked; evals gate merges.
**Risks:** draft quality variance — grounding + eval gate + human review keeps risk contained; costs metered from the first call.

---

## M6 — Monetization & second provider *(≈1–2 weeks)*

**Scope**
- Stripe: plans (free trial / pro), usage counters (sends, AI credits), webhooks → `subscriptions`; billing UI; plan-based policy limits.
- Microsoft Graph adapter (proves the provider port with a second implementation).
- Ops hardening: backups/PITR, staging/prod separation, on-call basics, status page.

**Exit criteria:** a stranger can sign up, pay, connect a mailbox, and run a campaign unassisted.
**This is the public-launch cut.**

---

## M7 — Sequences & staged autonomy *(≈2–3 weeks)*

**Scope**
- Follow-up sequences (retry_logic semantics generalized): steps, delays, stop-on-reply/bounce/unsubscribe.
- Autonomy level 2: auto-send above per-workspace confidence threshold with sampled human review + daily budgets + kill switch.
- Company Research Agent (enrichment → structured profiles feeding personalization).
- Analytics v1: campaign funnel (sent→delivered→replied), pattern accuracy dashboards from learning aggregates.

**Exit criteria:** sequences run unattended within budgets; auto-send incidents = 0 on beta; reply-rate lift from research-grounded drafts measured.

---

## M8 — Second workflow & scale-out *(post-launch, sized then)*

Candidate order: **Recruiting** (same motion, budget-holding buyers, 10× ACV) → Sales prospecting. Add workflow templates over the same engine (`campaign.kind`), workspace-level seat pricing, LinkedIn channel research, and — only when metrics demand — service splits along the existing hexagonal seams.

---

## Milestone → V0 module traceability

| V0 module | M0 | M1 | M2 | M3 | M4 | M5+ |
|---|---|---|---|---|---|---|
| cleaning/contacts (parsing) | | ported+tested | | | | |
| email_inference | | ported+tested | persisted | | UI reasoning | pattern agent |
| company (+dicts) | | algorithm | dicts→tables | | | research agent |
| drafts/templates | | | | template versions | editor | personalization |
| sender (policy) | | policy engine | | transactional send | review queue | autonomy |
| sender (SMTP) | | | | **replaced** by Gmail API | | Graph |
| history | | | **replaced** by messages/targets | dedupe constraints | | |
| learning | | model ported | tables | events flow | | weight tuning |
| reply/bounce parsers | | classifiers ported | | webhook/cursor sync | inbox | reply agent |
| retry_logic | | ported | | | | sequences |
| data_loading | | alias map | import service | | mapping UI | |
| cli | | kept for founder | | | **retired** | |
| config/logging/exports | | | **replaced** | | | |

**Standing risks across the plan:** Google OAuth verification lead time (start M3 week 1); deliverability reputation (warm-up defaults, user-domain sending, suppression discipline); founder bandwidth (each milestone is a usable product cut — we can pause after any of them without stranded work).
