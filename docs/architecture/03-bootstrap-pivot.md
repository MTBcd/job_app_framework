# Bootstrap Pivot — AI Job Application Copilot

**Status:** ACTIVE — this supersedes `01-target-architecture.md` and `02-roadmap.md` (kept for reference; their venture-scale scope no longer applies). `00-repo-audit.md` remains fully valid — the audit findings and the P0 security remediation are unchanged.

**New objective:** a profitable, solo-maintainable SaaS. One product, one user type (job seekers), €2–10k MRR, no team, no daily ops. Every decision below is optimized for *first paying customer fastest, then simplicity forever*.

---

## 1. The seven determinations

### 1.1 Features REMOVED (not in this product, ever, unless customers scream)

| Feature (from the old plan) | Why it's gone |
|---|---|
| Organizations / teams / workspaces | Job seekers are individuals. Single-user accounts, `user_id` on every row. Deletes an entire dimension of complexity (RLS design, roles, invites, seat billing). |
| Multi-workflow engine (recruiting, sales, fundraising…) | Different product, different buyer. The moment we serve two masters we serve neither. |
| Agent framework (10 named agents, memory, tool registries) | V1 needs exactly three LLM calls: personalize email, tailor cover letter, suggest CV improvements. Those are functions with prompts, not agents. |
| pgvector / embeddings / knowledge base | The user's CV is the knowledge base, and it fits in a prompt. Semantic search over nothing is nothing. |
| CQRS, transactional outbox, event-driven design | A `jobs` table and an `events` table in Postgres. That's the whole "architecture". |
| Microsoft Graph, Resend | Job seekers ≈ Gmail. One provider until revenue says otherwise. |
| Public API, API keys, webhooks out | Nobody asked. |
| Celery + Redis | Two more services to deploy, monitor, and pay for. Replaced by a Postgres-backed job queue polled by one worker process (`FOR UPDATE SKIP LOCKED`). Two moving parts total: web + worker, one database. |

### 1.2 Features POSTPONED (real value, wrong month)

| Feature | When it earns its slot |
|---|---|
| Gmail **OAuth** sending | Post-revenue. `gmail.send` is a *restricted* scope: Google verification + CASA security assessment, weeks-to-months of lead time and recurring cost. MVP ships on **SMTP/IMAP with Gmail app passwords** — exactly what V0 does today, zero verification, works now. One-page setup guide with screenshots. Revisit at ~50 customers. |
| Follow-up sequences | V1.1. The V0 retry logic already gives us "next-best address after a bounce"; scheduled human-approved follow-ups come right after launch — they demonstrably increase reply rates, but launch doesn't wait for them. |
| LinkedIn message generation | V1.1+. Cheap to add (one more prompt), but it dilutes the email-first funnel story at launch. |
| Auto-send above confidence threshold | Only after months of trust data. MVP: human reviews **every** email. This is a feature, not a limitation — it's also our anti-spam and deliverability shield. |
| Job-board integrations / job scraping | Paste a job description into a textarea. That's the MVP integration. |
| Analytics dashboards | Launch metric surface = a handful of counters (sent, replies, reply rate, interviews). PostHog answers everything else about *product* usage. |
| CV PDF *rendering* (generating a designed PDF) | MVP outputs CV improvement suggestions + a tailored cover letter as text/markdown to copy or download. Typesetting PDFs is a rabbit hole; suggestions are the value. |

### 1.3 Features UNNECESSARY (challenged out of the MVP list)

- **"Campaigns" as a first-class concept.** A job seeker has one campaign: getting hired. Forcing them to create/name/configure a campaign before sending email #1 is pure friction against the two-minute-comprehension goal. V1 model: **the user has Companies and Applications.** (If we later need batching, an invisible `batch_id` on applications does it without UI.) The "Campaigns" nav item becomes **"Applications"** — same milestone slot, less concept.
- **Dashboard as a separate build item.** The dashboard *is* the applications table plus four counters. No charts in V1.
- **Settings sprawl.** V1 settings = mailbox connection, sender identity, daily send cap, billing link. Four things.

### 1.4 Features BUILT FIRST (the money path, in order)

1. Upload CV (PDF/text) → extracted text stored.
2. Import companies (CSV/XLSX paste or upload — V0's header-alias loader shines here) + add single company manually.
3. Contact + email inference with confidence and reasoning (V0 core, straight port).
4. AI personalization: email draft + tailored cover letter + CV suggestions, grounded in CV + company + optional job description.
5. Review screen (approve/edit/reject — keyboard-first, this is the product's heart).
6. Send via user's Gmail (app password SMTP), reply/bounce sync (IMAP), status on the application row.
7. Stripe Checkout + customer portal (Payment Links first — near-zero billing code).

Auth (Clerk) and the deploy pipeline come first chronologically (Milestone 1) but the list above is the priority ranking whenever anything competes for time.

### 1.5 Modules REUSED (the prototype pays off)

| V0 module | Fate in the product |
|---|---|
| `email_inference.py` | **Ported nearly verbatim** into the API service. Candidates, confidence, reasoning strings — already exactly what the review UI needs to display. |
| `cleaning.py`, `contacts.py` | Ported as-is (name particles, initials handling, accents). Already characterization-tested (164 tests, previous round). |
| `company.py` resolution order + curated domain overrides | Ported; the two hardcoded dicts become seed rows in an `email_patterns`/`domain_overrides` table. |
| `learning.py` weights + aggregates | Ported; events go to Postgres, same weights. This quietly gets better with every user — see 1.7. |
| `sender.py` policy rails (dry-run, blocklist, caps, dedupe) + SMTP send | Ported. `smtplib` is *fine* at MVP scale — it's the user's own Gmail at ≤50 emails/day. |
| `reply_parser.py`, `bounce_parser.py` | Ported with one fix: sync cursor (last-seen date/UID) instead of rescanning from the earliest send. |
| `retry_logic.py` | Ported → powers "suggest next address after bounce". |
| `data_loading.py` alias map | Ported → the company/contact import mapping step. |
| `exports.py` | Ported → "download my data as CSV" endpoint (users love this, costs nothing). |
| The 164-test characterization suite | Travels with the port; every audited defect gets fixed under its own test. |

### 1.6 Modules REWRITTEN (thin, deliberate)

| V0 module | Replacement |
|---|---|
| `history.py` (CSV store) | SQLAlchemy models: `applications`, `events`. The CSV design can't do concurrency or per-user data. |
| `config.py` + `SendSettings` | One `pydantic-settings` object. |
| `pipeline.py`, `cli.py` | Service functions called by API routes and the worker. (A maintenance CLI can stay for you, not for users.) |
| `drafts.py` | The salutation/company-display helpers survive; the `string.Template` engine and your personal quant pitch are replaced by the LLM personalization service + a default template per user. |
| `logging_utils.py` | structlog JSON + Sentry (already planned; ~30 lines). |

### 1.7 The competitive moat (protect these)

1. **Email inference with explainable confidence** — competitors (Hunter, Apollo) sell this as a standalone product; we ship it *inside* the workflow, with reasoning shown at review time. It's why a user pays instead of guessing `first.last@`.
2. **The learning loop** — every send/reply/bounce across *all* users strengthens pattern confidence per domain. At even 100 users this becomes a dataset no new entrant has. (Privacy line: signals aggregate on `domain|pattern`, never on people.)
3. **The bounce/reply corpora** — bilingual DSN parsing that actually works was earned with 392 real sends. Boring, valuable, hard to replicate from docs.
4. **The finance/quant seed data** — 150 curated finance-employer domains + display names. This picks our launch niche for us: **quant/finance job seekers** first (you are the ICP — you can write the landing page from lived pain). Niche first, expand later; indie 101.

---

## 2. Product decisions that need your eyes (my recommendations inline)

1. **Sending = Gmail app password (SMTP/IMAP) for MVP.** Friction: user must enable 2FA and mint an app password (guided, ~3 minutes). Alternative "zero-setup" mode ships alongside: **"Open in Gmail"** deep-link that pre-fills the drafted email — no credentials at all, still tracked as `sent_manually`. OAuth graduates in post-launch. *Risk owned: Google could tighten app passwords; the deep-link mode is the fallback.*
2. **Pricing:** subscriptions fit ongoing search; job search is bursty and ends (that's success). Recommendation: **Pro €19/month** + **30-day Sprint €39 one-time** (no auto-renew). Free tier: 3 companies end-to-end (full value shown, hard cap). Stripe Payment Links + customer portal = almost no billing code.
3. **"Campaigns" dropped in favor of "Applications"** (see 1.3) — confirm you're comfortable renaming the concept.
4. **Niche launch:** landing page speaks to quant/finance/data candidates first. Same engine works for everyone; the *copy* niches down.

## 3. Milestones (yours, confirmed, with exit gates)

- **M1 — Foundation:** repo restructure (`jobapp` core + `jobapp.db` + `jobapp.api`; `web/` Next.js), Clerk auth, Postgres schema + Alembic, landing page, applications-table dashboard shell, deploy to Railway (web + worker + Postgres), Sentry. *Gate: you can sign in and see an empty dashboard in production.*
- **M2 — Data in:** company/contact import (CSV/XLSX + manual), CV upload with text extraction, email inference wired, review page listing candidates with confidence/reasoning. *Gate: real spreadsheet → reviewed addresses in prod.*
- **M3 — AI:** personalization, cover letter, CV suggestions (Claude via one provider module with cost metering into `ai_runs`), application composer. *Gate: approve-ready application generated end-to-end; cost per application known.*
- **M4 — Out & paid:** SMTP send + open-in-Gmail mode, IMAP reply/bounce sync via worker, counters, Stripe, public launch. *Gate: a stranger pays and sends.*

Standing risks: app-password setup friction (mitigate: video + deep-link fallback) · LLM cost per free user (mitigate: hard free cap, cache company research) · your bandwidth (mitigate: every milestone independently shippable; stop anywhere and it still works).

---

*Prepared under the indie-hacker test: every line above either helps a user get an interview or helps you get a paying customer. Everything that didn't, died here.*
