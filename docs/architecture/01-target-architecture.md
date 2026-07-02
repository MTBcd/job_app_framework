# Target Architecture (V1 → V3)

> **SUPERSEDED (2026-07-02):** the project pivoted to a bootstrapped solo-founder SaaS.
> See `03-bootstrap-pivot.md` for the active plan. Kept for reference; the module
> keep/replace analysis in §1–2 remains largely valid, the platform scope does not.

**Status:** proposal — awaiting founder validation (Step 7). Nothing here is implemented yet.
**Prime directive:** keep V0's encoded knowledge, replace V0's plumbing, and ship a usable product at every milestone.

---

## 1. What we preserve from V0 (Step 3)

Preserved means: ported into the new core as typed, tested, dependency-injected modules — algorithms intact, storage and I/O swapped.

| V0 asset | Where it lands in V1 |
|---|---|
| Email pattern generation + priors + initials/particle logic (`email_inference.py`) | `core/inference/patterns.py` — pure functions, property-based tests |
| Confidence scoring with reasoning traces + review flags | `core/inference/scoring.py`; reasoning persisted on `email_candidates` rows; review reasons become first-class enum |
| Learning event weights (sent/delivered/replied/bounce) and the three aggregate views | `learning_events` table + materialized aggregates; same weights as starting values, now tunable per-workspace |
| Resolution precedence (existing → verified → curated → learned → heuristic) with provenance | Generalized `Resolver` pattern used for domains, patterns, and later any enrichment; provenance column on every resolved fact |
| Bounce classification corpus (EN/FR regexes, DSN parsing, nested MIME walking) | `core/deliverability/bounce_classifier.py` — pure classifier fed by webhook/IMAP adapters |
| Reply-matching priority (References/In-Reply-To → sender fallback) | `core/deliverability/reply_matcher.py`, extended with OOO/auto-reply detection before it may emit a `replied` event |
| Name parsing (particles, prefixes/suffixes, comma-reversal, initials-only) | `core/identity/names.py` |
| Header alias map + duplicate-column coalescing (`data_loading.py`) | Import service column-mapping step (later exposed in the UI as a mapping screen) |
| Safety rails: dry-run default, consumer-domain blocklist, run caps, person+address dedupe, manual-review gate | `core/sending/policy.py` — the send-policy engine; every rule becomes explicit, tested, and org-configurable with safe defaults |
| Retry/next-candidate state logic (`retry_logic.py`) | Seed of the follow-up/sequence state machine |
| Curated domain overrides + verified pattern file + display-name fixes (data currently in code) | Rows in `company_domain_overrides` / `email_patterns` / `company_aliases` tables, seeded by migration from the V0 dicts, with `source='curated_v0'` |
| The workflow itself (prepare → review → send → observe → learn → retry) | Becomes the campaign state machine; the *manual review gate* stays — it is a feature, not a limitation |

## 2. What we redesign, and why (Step 4)

| V0 element | Replacement | Justification |
|---|---|---|
| CSV files as database | PostgreSQL (+ pgvector later) | Concurrency, transactions, multi-tenancy, indexes. Every V0 store does full-file scans per query and full rewrites per update; two simultaneous users would corrupt state. Not fixable incrementally — it's the foundation. |
| pandas DataFrame as domain model | Pydantic entities + SQLAlchemy models | 32 stringly-typed columns give no compile-time safety, no validation, and force row-wise `.get()` defensive code everywhere. Typed entities make every bug class found in the audit (disagreeing regexes, two sources of truth for `is_initials_only`) structurally impossible. |
| Two settings objects + scattered `os.getenv` | Single `pydantic-settings` config, injected | One source of truth, validated at startup, testable, no import-time side effects. |
| Synchronous send loop with `time.sleep` | Celery workers + Redis; per-mailbox token-bucket rate limits; scheduled sends | Sending is long-running, failure-prone, rate-limited work — the textbook case for a task queue. Also unlocks scheduling, warm-up ramps, and retries with backoff. |
| Personal Gmail SMTP/IMAP + app passwords | `EmailProvider` port with Gmail API and Microsoft Graph adapters (OAuth), Resend for product transactional mail | App passwords are being deprecated, IMAP polling doesn't scale past one user, and OAuth'd APIs give us history sync, thread ids, and webhooks (near-real-time reply/bounce detection instead of full-mailbox rescans). Users send from *their own* mailboxes — deliverability and compliance both demand it. |
| Templates with founder's personal pitch + hardcoded fallback name | Per-workspace template entities with variable schema; AI drafting on top | Content belongs to users, engine belongs to us. |
| `print` + one log file | structlog JSON logs, Sentry, PostHog | You cannot operate a SaaS on `print`. Correlation ids (request → task → send) from day one. |
| No tests | pytest as extraction harness | Every V0 algorithm gets characterization tests **while** being ported — the port is only "done" when tests pin current behavior (minus the audited bugs, each fixed deliberately with its own test). |
| Batch identity (`person_key` string concat) | Proper entities with surrogate keys + uniqueness constraints + merge logic | The audit showed person-keys colliding/splitting on name variants and history updates hitting the wrong people. |

**Explicitly rebuilt, not ported:** `pipeline.py`, `cli.py` (as product surface), `history.py`, `exports.py` internals, `config.py`, `logging_utils.py`, `sender.py`'s transport half. Combined they are ~600 lines; nothing in them is load-bearing knowledge.

## 3. Where I am challenging the brief (you asked me to)

1. **CQRS and event sourcing: not yet.** We adopt *event-driven* in the narrow, valuable sense — an append-only `events` table (transactional outbox) that workers and analytics consume. Full CQRS/read-model separation is complexity we don't need below ~10⁶ events/day; the outbox gives us the audit trail and the future migration path for free.
2. **Eight workflows (jobs, recruiting, sales, fundraising…): one now.** The engine is built workflow-agnostic (campaign → targets → messages → signals is identical everywhere), but we ship **job-search outreach only** until it has paying users. Every horizontal at this stage multiplies surface area and dilutes the learning data that is supposed to be our moat. The schema carries a `campaign.kind` discriminator so nothing blocks the expansion.
3. **Microservices: no.** One FastAPI app + one Celery worker pool + one Postgres, deployed as a modular monolith with enforced internal boundaries (import-linter). We split services when a boundary proves it needs independent scaling, not before.
4. **"Autonomous AI employee": staged autonomy.** The product earns autonomy: first AI drafts + human approves everything (the V0 review gate, productized), then auto-send above configurable confidence with sampling review, then autonomous sequences with budgets and kill-switches. Full autonomy on day one is both unsafe (deliverability, reputation, anti-spam law) and unsellable (trust).
5. **Compliance is a feature, not a checkbox.** CAN-SPAM/CASL/GDPR: suppression lists, unsubscribe handling, per-recipient consent basis, data deletion. Kandi competitors get shut down or blacklisted over this; we build suppression + unsubscribe into the send policy engine in the first sending milestone. (CASL matters immediately — V0's own data is Canadian.)

## 4. Proposed architecture (Step 5)

### 4.1 System overview

```
                    ┌────────────────────────────────────────────┐
                    │  Next.js app (Vercel/Railway)               │
                    │  React · TS · Tailwind · shadcn/ui          │
                    │  Clerk auth · PostHog                       │
                    └───────────────┬────────────────────────────┘
                                    │ HTTPS (typed client from OpenAPI)
                    ┌───────────────▼────────────────────────────┐
                    │  FastAPI (api/)                             │
                    │  routers → services → core domain           │
                    │  Clerk JWT verification · rate limits       │
                    │  Stripe webhooks · provider OAuth flows     │
                    └───────┬───────────────────────┬────────────┘
                            │                       │ enqueue
                    ┌───────▼───────┐       ┌───────▼────────────┐
                    │ PostgreSQL     │◄──────│ Celery workers      │
                    │ + pgvector     │       │  import · enrich ·  │
                    │ (multi-tenant, │       │  infer · send ·     │
                    │  outbox events)│       │  sync · learn · AI  │
                    └───────┬───────┘       └───┬────────┬───────┘
                            │                   │        │
                    ┌───────▼──────┐    ┌───────▼──┐ ┌───▼──────────────┐
                    │ Redis         │    │ Email    │ │ AI providers      │
                    │ queue · cache │    │ ports:   │ │ port: Anthropic · │
                    │ rate buckets  │    │ Gmail API│ │ OpenAI · Gemini   │
                    └──────────────┘    │ MS Graph │ │ (structured out.) │
                                        │ Resend   │ └──────────────────┘
                                        └──────────┘
        Sentry (api+workers+web) · structlog JSON · GitHub Actions → Railway/Fly
```

### 4.2 Repository layout (monorepo)

```
/
├── apps/
│   ├── api/                    # FastAPI service
│   │   ├── src/app/
│   │   │   ├── api/            # routers (thin: parse → service → respond)
│   │   │   ├── services/       # use-cases; transaction boundaries
│   │   │   ├── core/           # pure domain: inference, identity,
│   │   │   │                   #   deliverability, sending-policy, learning
│   │   │   ├── adapters/       # db repositories, email providers, ai providers
│   │   │   ├── models/         # SQLAlchemy
│   │   │   ├── schemas/        # Pydantic DTOs
│   │   │   └── workers/        # Celery tasks (thin wrappers over services)
│   │   └── tests/              # unit (core), integration (services+db), e2e (api)
│   └── web/                    # Next.js
├── packages/
│   └── shared/                 # OpenAPI-generated TS client, shared enums
├── infra/                      # Dockerfiles, compose, railway/fly configs
└── docs/
```

Dependency rule (enforced by import-linter in CI): `api → services → core`; `adapters` implement `core` ports; `core` imports nothing outward. This is Hexagonal/Clean Architecture applied only where it pays: the **core is pure and unit-testable without a database**, which is exactly what lets us port V0 algorithms with characterization tests first.

### 4.3 Database design (multi-tenant from the first migration)

Every tenant-owned table carries `workspace_id` (FK, indexed, NOT NULL) and RLS policies. Clerk organizations map 1:1 to workspaces.

**Identity & tenancy:** `users`, `workspaces`, `workspace_members` (role), `api_keys`.

**Graph:** 
- `companies` (workspace-scoped; normalized_name, display_name, domains[], enrichment jsonb, embedding vector) 
- `contacts` (company FK nullable, name fields incl. ascii/initials/parse-warnings from V0 logic, title, location, source provenance)
- `email_addresses` (contact FK, address, `kind` provided|inferred|verified, pattern, confidence, reasoning jsonb, verification_status, uniqueness on (workspace, address))
- `company_domain_overrides`, `company_aliases`, `email_patterns` (domain, pattern, confidence, `source` curated|learned|verified|user, evidence_count) — the V0 dicts/CSVs become these rows.

**Outreach:**
- `campaigns` (kind: job_search|…, status, settings jsonb: caps, thresholds, schedule windows)
- `campaign_targets` (campaign×contact; state machine: `draft → needs_review → approved → queued → sent → replied|bounced|exhausted|suppressed`; review_reasons[])
- `messages` (target FK, direction, channel, subject, body, template_version FK, provider_message_id, thread_id, scheduled_at/sent_at, status)
- `templates` + `template_versions` (immutable versions; messages reference the exact version — reproducibility)
- `sequences` / `sequence_steps` (V2: follow-ups; retry_logic semantics live here)
- `suppression_list` (workspace, address/domain, reason: unsubscribe|hard_bounce|manual|legal)

**Signals & learning:**
- `events` (append-only outbox: aggregate_type, aggregate_id, type, payload jsonb, occurred_at; workers consume via `FOR UPDATE SKIP LOCKED`)
- `learning_events` (V0 weights preserved: type, weight, company/domain/pattern keys, message FK) with `learning_aggregates` refreshed incrementally
- `mailbox_connections` (provider, oauth tokens encrypted with KMS-style envelope, sync cursor/history_id, health)
- `replies`, `bounces` (classified; FK to message)

**AI:**
- `ai_runs` (agent, model, prompt_version, input/output refs, tokens, cost_cents, latency, status) — every LLM call accounted from day one
- `documents` (resumes/CVs, versions, storage ref), `knowledge_items` (+ `embedding` pgvector) for the user's background corpus
- `resume_versions`, `cover_letters` referencing `ai_runs`

**Billing/ops:** `subscriptions` (Stripe mirror), `usage_counters` (sends, enrichments, ai tokens per period), `audit_log`.

Key constraints encoding V0's hard lessons: dedupe = unique partial index on `messages(workspace_id, contact_id) where status='sent'` per campaign policy; bounce updates are message-scoped (never "all rows with this address"); `email_addresses.address` unique per workspace so learning signals attach to one row.

### 4.4 The send path (replaces `sender.py`)

1. API: `POST /campaigns/{id}/targets/{id}/approve` → target `approved`, `send_message` task enqueued with `scheduled_at` respecting workspace send-windows.
2. Worker: re-checks **policy engine** (suppression, caps, dedupe, confidence gate, domain allow/block — the V0 rules, now transactional), renders template version, sends via the workspace's `EmailProvider`, writes `messages` + outbox event in one transaction. Idempotency key = target id + attempt; Celery `acks_late` + idempotent task body.
3. Rate limiting: Redis token bucket per mailbox (warm-up schedule: new mailboxes ramp 10→50/day) — replaces `time.sleep`.
4. Reply/bounce ingestion: Gmail `history.list` / Graph delta webhooks (fallback: polling with **last-cursor**, fixing V0's earliest-date rescan); classifier (ported corpus) → `replies`/`bounces` + learning events; OOO/auto-reply detected before any `replied` credit.

### 4.5 AI layer

One `AIProvider` port (Anthropic default, OpenAI/Gemini adapters) with structured-output helpers, retries, cost metering into `ai_runs`.

Agents are **typed services with a shared runtime** (memory = scoped DB reads + pgvector retrieval; tools = whitelisted functions; every step logged to `ai_runs`; evals = golden datasets in CI), not free-roaming loops:

- **V1 agents:** Personalization Agent (drafts from contact+company+knowledge corpus), Company Research Agent (web/enrichment → structured company profile), Reply Analysis Agent (classify replies: positive/negative/OOO/referral → learning weights).
- **V2:** Resume/Cover-letter agents (versioned outputs), Campaign Strategy Agent (target selection assist), Email Pattern Agent (LLM-assisted pattern verification against public evidence).
- **Learning loop stays statistical** (weights/aggregates) with LLM analysis layered on top — deterministic core, explainable, cheap; LLMs where language understanding is genuinely needed.

Autonomy ladder (per workspace): `draft_only` → `auto_send_above_confidence(τ)` → `autonomous_sequences(budget, kill_switch)`.

### 4.6 Security & compliance baseline

- Secrets in platform env vaults only; `.env` never tracked again (CI gitleaks + GitHub push protection).
- OAuth tokens encrypted at rest (per-workspace data key); least-scope Gmail/Graph scopes.
- RLS on all tenant tables; API-layer workspace guard as second belt.
- Suppression + one-click unsubscribe headers (`List-Unsubscribe`) on every outreach send; consent-basis field on contacts; hard-delete workflows (GDPR/CASL).
- Sentry scrubbing PII; logs carry ids, not addresses.

### 4.7 Testing & CI

- **Core:** pure unit tests + property-based tests (hypothesis) for name parsing/pattern generation; golden files for bounce corpus.
- **Services:** integration against ephemeral Postgres (testcontainers).
- **API:** schemathesis contract tests from OpenAPI.
- **Web:** Vitest + Playwright smoke on preview deploys.
- GitHub Actions: lint (ruff, mypy --strict on core), tests, build, migrate-check, deploy on tag. Every milestone ships behind this gate.

---

## 5. Why this architecture wins

1. **It monetizes V0's real asset** — the learning loop — by giving it storage that can aggregate across thousands of users. Every send any tenant makes improves pattern confidence (workspace-private signals, globally learnable *patterns* — a data moat competitors can't copy from our UI).
2. **Explainability as UX:** V0's reasoning traces become the product's trust surface (confidence chips, "why this email" popovers) — the Linear/Cursor-grade feel comes from showing the machine's work, instantly.
3. **Boring, senior choices** (Postgres, Celery, monolith, typed core) minimize ops burden at seed stage while the enforced hexagonal boundary keeps every future split (services, new channels like LinkedIn, new workflows) additive rather than surgical.
