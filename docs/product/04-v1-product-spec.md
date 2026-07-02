# V1 Product Specification — AI Job Search Assistant

**Status:** ACTIVE product source of truth. Complements `../architecture/03-bootstrap-pivot.md`
(business/stack decisions stand; where this spec differs on scope — match scoring, recruiter
research, follow-up suggestions, analytics now in V1 — this spec wins).
**Working name used below:** *Copilot* (naming decision pending — see Open Decisions).

The product in one sentence: **upload your CV, point at a job or company, and get a
complete, reviewed, high-quality application — researched, matched, tailored, addressed —
out the door in under five minutes.**

The one metric every screen serves: **interviews obtained per user.**
The proxy metric while interviews lag: **quality applications sent per user per week.**

---

## 1. The user journey (landing → first interview)

| Stage | Where | What happens | Emotional beat |
|---|---|---|---|
| 1. Arrival | Landing page | Sees the promise: "Interviews, not busywork." Watches the 30-sec product loop (GIF/video of an application being prepared). | "This is what I've been doing by hand for weeks." |
| 2. Signup | Clerk hosted | Google sign-in, one click. No credit card. | Zero friction. |
| 3. Onboarding step 1 | Wizard | Uploads CV (PDF/DOCX/paste). Parsing runs ~10s with a skeleton; profile appears as editable chips (skills, roles, years, education, projects). Confirms. | "It understood me." |
| 4. Onboarding step 2 | Wizard | Adds first target: paste a job description, a job URL, or just a company name. | Investment made. |
| 5. First pipeline run | Application detail | Live stage checklist: Researching company → Analyzing fit → Finding contact → Writing. 60–120s, streamed progressively — each section fills in as it completes. | **The aha moment.** Watching it work builds trust. |
| 6. Review | Application detail | Reads match score + strengths/gaps, tailored email, cover letter, CV suggestions, inferred address with confidence + "why". Edits anything inline. | In control. |
| 7. First send | Send modal | Clicks Send → mailbox not connected yet → connect-Gmail sheet appears **now** (app password, guided, 3 min) or "Open in Gmail" zero-setup fallback. Sends. | Commitment at the moment of value, not before. |
| 8. The wait | Dashboard | Application row shows "Sent · 2d ago". Adds more targets (free tier: 3 total). | Habit forming. |
| 9. Reply | Email + dashboard | Reply detected by sync → notification email "💬 Acme replied" → row turns green → user marks outcome "Interview booked". | **The payoff.** This is the moment they screenshot. |
| 10. Upgrade | Paywall | 4th application hits the free cap → upgrade modal with their own stats ("2 replies from 3 sends"). | Buys with evidence in hand. |
| 11. Retention | Weekly digest + follow-up chips | "3 applications stale — 1-click follow-up drafts ready." | Keeps momentum until hired. |
| 12. Exit (success) | Dashboard | Marks "Hired 🎉" → offer to pause/cancel gracefully + ask for testimonial. | Leaves loving us. Referrals. |

---

## 2. Navigation structure

```
Sidebar (fixed, 200px, collapsible to icons)
├── ⌘  Applications        (default screen — the tracker)
├── ＋ New application      (primary action, always visible)
├── 📊 Insights             (analytics)
├── ⚙  Settings
└── [user menu: plan badge, billing, help, sign out]

Top bar: breadcrumb · global search (applications/companies) · usage meter (free tier) 
Keyboard: ⌘K command palette (V1: navigate + create + search only)
```

Public site: `/` landing · `/pricing` · `/privacy` · `/terms` · `/guides/gmail-app-password`.
App: `/app` (applications) · `/app/applications/:id` · `/app/new` · `/app/insights` · `/app/settings/*`.

Five app surfaces total. Nothing else.

---

## 3. Screens

### 3.1 Landing page `/`
- **Hero:** headline "Get interviews, not busywork." Sub: "Copilot researches the company, tailors your CV and cover letter, finds the right person, and writes the email — you just hit send." CTA: "Start free — 3 applications". Secondary: product loop video.
- **Sections:** How it works (3 steps) · The application pack (annotated screenshot of review screen) · "Why it works" (personalization stats) · Niche strip ("Built for quantitative finance & data roles first") · Pricing teaser · FAQ (app password? privacy? my data?) · Footer (legal, contact).
- **States:** static; no auth logic. Loading: instant (SSG).

### 3.2 Onboarding wizard `/app/onboarding` (first login only, resumable, skippable after step 1)
- **Step 1 — Your CV** (required): drag-drop PDF/DOCX or paste text. → parse → editable profile chips grouped: Skills / Experience / Education / Projects / Strengths. Actions: edit chip, delete chip, add chip, re-upload, confirm.
  - Loading: skeleton chips + "Reading your CV…" (~10s). Error: "We couldn't read that file — try PDF or paste the text" (paste box opens pre-focused). Empty chips group: hidden.
- **Step 2 — First target** (skippable → lands on empty dashboard): three tabs: Paste job description · Paste job URL · Company only. One field each + optional "role you're targeting". CTA: "Prepare my application".
- **Step 3 is not a step:** it's the live pipeline on the application detail screen (3.4). Mailbox connection is deliberately **not** onboarding — it appears at first send.

### 3.3 Applications (dashboard) `/app`
The tracker. One table, four stat tiles, no charts.
- **Stat tiles:** Sent · Reply rate · Interviews · Active. (Counts respect current filter.)
- **Table columns:** Company (+contact avatar/initials) · Role · Match score chip · Status chip · Last activity · Next action (contextual button).
- **Status chips:** Preparing (animated) · Needs review · Ready · Sent · Replied 💬 · Bounced · Interview 🎯 · Rejected · Archived.
- **Row actions (hover / ⌘K):** Open · Send (if ready) · Draft follow-up (if stale ≥5 business days) · Mark outcome (Interview/Rejected/No response) · Archive.
- **Filters:** status pills + search. Sort: last activity (default), match score.
- **Follow-up chips:** stale sent rows show "Suggest follow-up" — computed at read time (no scheduler): sent + N days, no reply, no bounce, < 2 follow-ups.
- **Empty state (new user):** "Your pipeline starts here. Add a job or company and Copilot prepares the complete application." CTA: New application. (If CV missing: CTA becomes "Upload your CV first".)
- **Loading:** 6 skeleton rows. **Error:** inline retry banner, table preserved from cache.

### 3.4 Application detail `/app/applications/:id` — **the product**
Two-column workspace. Left = the application pack (tabs). Right = context rail.
- **Header:** Company · Role · match score chip · status · primary action button (state-dependent: Review → Send → Follow up) · overflow menu (Regenerate all, Archive, Delete).
- **Left tabs:**
  1. **Email** — subject + body, inline-editable rich text. Above it: recipient block — contact name/title + selected address + confidence chip (e.g., `j.smith@acme.com · 86% · first.last`) + "Why this address?" popover (the V0 reasoning trace verbatim: pattern prior, learned domain pattern, verified source). Actions: choose different candidate (dropdown w/ confidences), enter address manually, regenerate email (tone selector: direct / warm / formal), copy, **Send**.
  2. **Cover letter** — editable, regenerate, copy, download (.docx/.pdf single template).
  3. **CV** — two panes: *Suggestions* (checklist: reorder, rewrite bullets, add keywords — each with "why" and Apply button) and *Optimized CV* (editable result after applying; download .docx/.pdf, single clean ATS-safe template).
  4. **Research** — company brief (what they do, size, recent news, stack/keywords, sources listed as links) + fit analysis: match score, top-5 strengths (each mapped CV evidence ↔ JD requirement), top-3 gaps + how to address honestly. Every claim shows its source (JD text, CV text, or web).
- **Right rail:** timeline (created, researched, generated, edited, sent, reply excerpt, follow-ups) + job description (collapsible, editable) + contact card.
- **Pipeline (while preparing):** the left area is a live checklist — Research ✓ → Fit analysis ✓ → Contact & address ⟳ → Writing… Each completed stage reveals its tab immediately. Poll every 2s.
- **States:** Research failed → banner "Limited research — generated from the job description only" + Retry. No contact found → recipient block offers: try another role (dropdown: HR/hiring manager/team lead), enter manually, or send to company generic (careers@) with warning. Low confidence (<0.72, V0 threshold) → amber review flag on Send. Send blocked reasons listed explicitly (no address, bounced address, suppressed, cap reached).

### 3.5 New application `/app/new` (also a ⌘K action and modal from dashboard)
Same three tabs as onboarding step 2, plus **bulk**: upload CSV/XLSX of companies (V0 alias-map import; column-mapping preview table with confidence per column) → creates up to N applications (plan-capped), queued with visible progress. Duplicate detection: same company+role → warn chip "Already in your pipeline", link to existing.

### 3.6 Insights `/app/insights`
One screen, three blocks. No date pickers in V1 (fixed: last 30 days + all time toggle).
- Funnel: Prepared → Sent → Replied → Interview (numbers + conversion %).
- "What's working": best-performing pattern facts, computed from events ("Emails sent Tue–Thu morning got 2.1× replies", "Applications with match ≥70 reply 3× more") — only shown when sample ≥ 10, else educational defaults labeled as such.
- Activity list: last 20 events.
- Empty: "Send your first application to unlock insights." Loading: skeleton tiles. Error: retry banner.

### 3.7 Settings `/app/settings/*` (4 tabs)
- **Profile & CV:** name, target role(s), base CV (replace/re-parse; shows parsed chips), tone default, signature block. Danger zone: export my data (CSV/JSON), delete account (typed confirmation; hard delete + 30-day grace note).
- **Mailbox:** connection card (Gmail app password flow: username + 16-char password fields, live "Test connection" that sends a self-email; link to `/guides/gmail-app-password` with screenshots; status: Connected ✓ / Error with reason). Fallback toggle: "No mailbox — use Open-in-Gmail mode". Daily send cap (default 20, max 50). Dry-run switch (badge shows everywhere when on).
- **Sending:** blocked domains list (prefilled consumer domains), suppression list viewer (address, reason, date; remove allowed for `manual` only), follow-up defaults (suggest after N days, max count).
- **Billing:** current plan card, usage this period, buttons → Stripe Checkout (upgrade) / Stripe customer portal (manage/cancel/invoices). Trial/cap meter.

### 3.8 Pricing `/pricing`
Three cards: **Free** — 3 applications total, everything included, no card. **Pro €19/mo** — unlimited* (fair use 100/mo), priority generation. **Sprint €39 one-time** — 30 days of Pro, no auto-renew ("job search is a sprint, not a subscription"). Annual Pro €190. FAQ: cancel anytime, what counts as an application, refunds (14-day no-questions).

---

## 4. Modals & sheets (complete list)

1. **Send confirmation** — recipient, subject, first lines, confidence chip, daily-cap counter ("3 of 20 today"), dry-run badge if on. Buttons: Send now · Cancel. If mailbox missing → morphs into **Connect mailbox sheet** (tabs: App password / Open in Gmail).
2. **Connect mailbox sheet** — as above; test-connection inline with spinner and success/failure copy.
3. **Column mapping (import)** — preview 5 rows, per-column dropdown with auto-detected mapping (V0 alias map), confidence badges, "ignore column".
4. **Regenerate options** — scope (email/cover/CV), tone, extra instruction (one text field, 200 chars).
5. **Mark outcome** — Interview 🎯 / Rejected / No response / Hired 🎉 (+ optional note; Hired triggers confetti + pause-subscription offer).
6. **Upgrade (paywall)** — appears at cap: shows *their* stats, plan cards inline, Stripe checkout link.
7. **Follow-up draft** — generated follow-up in place, editable, Send/Discard; shows thread context.
8. **Delete confirmations** — application (soft archive default; delete = typed confirm), account (Settings).
9. **⌘K palette** — navigate, new application, search companies/applications, "send feedback".

## 5. Notifications (complete list)

**In-app toasts (transient, 4s):** saved ✓ · sent ✓ ("Application to Acme sent") · generation finished (when user navigated away) · generation failed (persistent until dismissed, with Retry) · connection test result · import completed (n created, m skipped + link) · plan activated.
**Badges:** sidebar dot on Applications when replies arrived since last visit.
**Transactional email (via user's… no — via product mailbox, Resend? — see Critique 11.1):**
1. Welcome (one email, the entire product in 5 lines + guide link).
2. **Reply received** — subject: "💬 {Company} replied" — excerpt + deep link. (The single most valuable email we send; also the churn-saver.)
3. Weekly digest (Mon 8:00 local): pipeline table + follow-up suggestions. Off switchable, on by default.
4. Cap reached / payment failed / subscription events → Stripe handles payment emails; we send only cap-reached.
No other email. No push. No SMS.

---

## 6. AI interactions (per pipeline stage)

Every AI feature follows one contract: **grounded inputs → structured output → visible reasoning → editable result → metered cost** (`ai_runs` row per call).

| # | Interaction | Inputs | Output (structured) | UI | Failure fallback |
|---|---|---|---|---|---|
| 1 | CV parse & profile extraction | CV text (pdf/docx extracted) | profile: skills[], roles[], years, education[], projects[], strengths[], warnings[] | Editable chips (onboarding, settings) | Paste-text box; manual chips |
| 2 | Company research | company name/domain (+ web search tool, cached globally per domain 30d) | brief: what, size, hq, news[], stack_keywords[], sources[] | Research tab, sources linked | Skip with "limited research" banner; JD-only generation |
| 3 | JD analysis + fit/match | profile + JD text | score 0–100, strengths[{claim, cv_evidence, jd_requirement}], gaps[{gap, mitigation}], missing_keywords[] | Score chip + Research tab lists; chips explain on hover | If no JD: "company fit" mode, score hidden, banner explains |
| 4 | Contact selection ("recruiter research") | company + role + imported contacts if any | ranked contacts [{name?, title, source, rationale}] — **V1 scope: choose among known/imported contacts + title heuristics; no deep person web-research** | Recipient block + alternatives dropdown | Generic address path or manual entry |
| 5 | Email inference | contact name + domain (V0 engine, not LLM) | candidates[{email, pattern, confidence, reasoning[]}] | Confidence chip + "why" popover | Manual entry; verify-on-send guard |
| 6 | Tailored email | profile + brief + fit + tone | subject, body (≤180 words), personalization_notes[] | Email tab | Template + merge fields as last resort, labeled |
| 7 | Cover letter | same + JD | letter (≤350 words, no clichés list enforced in prompt) | Cover tab | Same |
| 8 | CV suggestions + optimized CV | profile + JD + missing keywords | suggestions[{type, before, after, why}], optimized_cv_markdown | CV tab checklist → apply → editable doc | Suggestions only, no rewrite |
| 9 | Reply classification | inbound reply text | label: interested/interview/rejection/OOO/auto/other + suggested next step | Timeline badge + suggested action chip | Unlabeled reply, manual |
| 10 | Follow-up draft | thread + days elapsed | short follow-up (≤80 words) | Follow-up modal | Static polite template |

Models: default `claude-sonnet-5` for 2/3/6/7/8; `claude-haiku-4-5` for 1/9/10 (cheap, structured). All calls: JSON-schema outputs, 2 retries, 30s timeout, per-user daily token budget (plan-based). Estimated marginal cost per full application pack: **€0.06–0.15**; free tier worst case ≈ €0.45/user. Prompt versions stored on `ai_runs`.

Trust rules (product law): AI never sends; AI never invents facts about the user (generation prompt may only cite provided CV/profile content — enforced by including only structured profile, not free imagination; "do not fabricate experience" system rule + gaps must be honest); every number/claim in research links a source; every recommendation carries a "why".

---

## 7. Database entities (delta vs committed schema)

Existing 12 tables stand (see `models.py`). V1 additions/changes:

- **users** + `full_name`, `target_roles JSON`, `tone_default`, `signature`, `plan_expires_at` (Sprint), `weekly_digest bool`.
- **documents** — unchanged (kind='cv'); add `parsed_profile JSON`, `parse_warnings JSON`.
- **companies** + `research JSON` *(deprecated in favor of company_profiles if global cache adopted — Critique 11.2)*.
- **NEW company_profiles** — global research cache: `domain unique`, `brief JSON`, `sources JSON`, `refreshed_at`. (Cross-user cost saver; public info only.)
- **NEW job_postings** — `user_id`, `company_id`, `title`, `description_text`, `url`, `source(pasted|url|import)`.
- **NEW match_reports** — `application_id unique`, `score int`, `strengths JSON`, `gaps JSON`, `missing_keywords JSON`, `model`, `created_at`.
- **applications** + `job_posting_id FK`, `optimized_cv text`, `tone`, `outcome (pending|interview|rejected|no_response|hired)`, `outcome_at`, `follow_up_count int`, `last_reply_at`, `batch_id`.
- **events** — unchanged (types grow: `generated`, `edited`, `followup_sent`, `outcome_marked` — outcome events get learning weights later: interview +8?).
- **email_patterns / suppressions / mailbox_settings / jobs / ai_runs / email_candidates / contacts** — unchanged (contacts + `rationale`, `seniority`).

Everything still single-user rows + 2 global tables (company_profiles, seed email_patterns).

## 8. API endpoints (complete V1 surface)

Auth: Clerk JWT on everything except `/health`, `/webhooks/*`, public pages (Next.js side).

```
GET    /health
# CV / profile
POST   /cv                         (multipart or text) → parse job enqueued
GET    /cv                          → document + parsed_profile + status
PUT    /profile                     → edit chips
# Applications & pipeline
POST   /applications                {jd_text|jd_url|company_name, role?, tone?} → id, pipeline queued
POST   /applications/import         (csv/xlsx) → column-map preview token
POST   /applications/import/commit  {mapping} → created[], skipped[]
GET    /applications                ?status&search&sort&cursor
GET    /applications/{id}           (pack: research, match, docs, recipient, timeline)
PATCH  /applications/{id}           (edits: subject/body/cover/cv/jd/tone/status=archived)
POST   /applications/{id}/regenerate {scope, tone?, instruction?}
POST   /applications/{id}/outcome   {outcome, note?}
GET    /applications/{id}/status    (pipeline stage polling — lightweight)
# Recipient
GET    /applications/{id}/candidates
POST   /applications/{id}/recipient {candidate_id | manual_email | contact_role_retry}
# Sending & follow-ups
POST   /applications/{id}/send      (preflight+send or open-in-gmail payload)
POST   /applications/{id}/followup  → draft
POST   /applications/{id}/followup/send
# Insights
GET    /insights/summary            (tiles + funnel + facts)
# Settings
GET/PUT /settings/mailbox           POST /settings/mailbox/test
GET/PUT /settings/sending           (caps, blocked domains, follow-up defaults)
GET    /settings/suppressions       DELETE /settings/suppressions/{id}
GET    /settings/export             (zip: csv+json)  DELETE /account
# Billing
POST   /billing/checkout {plan}     POST /billing/portal      GET /billing/status
POST   /webhooks/stripe
```

~28 endpoints. Worker consumes `jobs` internally (kinds: `parse_cv`, `prepare_application`, `send_email`, `sync_mailbox`, `send_digest`).

## 9. Key flows

**Application pipeline:** `POST /applications` → job `prepare_application` → stages write progressively to the row (status `processing`, stage field) → research (cache hit? skip cost) → match → contact+inference (V0 engine) → generate 3 docs → status `needs_review` (+review_reasons from V0 flags) → UI polled `/status` reveals tabs as they land.

**Sending:** Send click → preflight (address valid, not suppressed, not bounced-before, cap not exceeded, mailbox ok, dry-run?) → confirmation modal → job `send_email` → SMTP via user Gmail (V0 sender policy rails) → Message-ID stored → event `sent` (+weight) → status `sent`. Open-in-Gmail mode: render `mailto:`/gmail compose URL, mark `sent_manually` on confirm.

**Reply sync:** worker `sync_mailbox` every 10 min per connected user (IMAP since last cursor — fixes V0 full-rescan) → V0 reply matcher (References → sender fallback) + bounce classifier → events (`replied` +4.0 / bounce −3.0 with pattern/domain) → application status + email + badge. OOO/auto filtered by classifier (stage 9) before status flips.

**Billing:** checkout → Stripe hosted → webhook `checkout.session.completed` → plan set (Sprint: `plan_expires_at=now+30d`) → success page. Portal for cancel/cards/invoices. Caps enforced server-side at `POST /applications` (free: 3 lifetime) and `/send` (daily cap). Webhook lag: "activating…" state on return URL, poll `/billing/status` 10s.

**Learning loop:** every send/reply/bounce/outcome event with domain+pattern feeds the V0 aggregates → inference boosts get better for everyone. Outcome `interview` is the gold label (analytics now; weight later).

## 10. States catalog (globals)

- **Empty:** every list ships one — Applications (§3.3), Insights (§3.6), Suppressions ("Nothing suppressed — bounces land here automatically"), Timeline ("No activity yet"), Candidates ("No address candidates — add a contact name first").
- **Loading:** skeletons (tables, tiles, chips); stage checklist for pipeline; button spinners for actions ≤2s; toasts for background completion.
- **Error:** field-level inline (forms) · banner with Retry (fetch) · toast (transient op) · full-screen only for 404/expired session. Copy pattern: what happened + what we did + one action. Send errors reuse V0 classification: hard bounce ("address doesn't exist — try the next candidate" + auto-suppress), soft ("we'll retry in an hour" + auto retry job), auth ("Gmail rejected the app password — reconnect", deep link).
- **Degraded AI:** every generation has a non-AI fallback (templates, suggestions-only, manual entry) — the app never dead-ends on an LLM failure.

---

## 11. Self-critique & the simplification pass

### 11.1 Cut or narrowed (complexity that didn't survive)

1. **"AI recruiter research" narrowed** (was: web-research every hiring manager). Per-contact web research is the costliest, flakiest, most privacy-sensitive stage. **V1 = choose among imported/known contacts + title-based targeting + V0 inference.** Deep person-research becomes a V2 flag. The email is personalized on *company+role+fit* — which is what actually moves reply rates.
2. **companies.research JSON dropped** → global `company_profiles` cache only (one source of truth, 10× cost saving at 100 users).
3. **CV/cover PDF design system** → **one** ATS-safe template, markdown→docx/pdf. No template picker in V1.
4. **Insights page trimmed** — no charts, no date pickers; tiles + funnel + facts list. (Charts tempt dashboards; facts drive behavior.)
5. **Review queue / bulk approve** (was in old plan) → per-application review only; bulk is a power-user V2 need.
6. **Separate Companies/Contacts pages** — never existed here; confirmed out. Entities live behind applications.
7. **Tone selector reduced** to 3 presets + one free-text instruction. Not a prompt IDE.
8. **⌘K palette scope** frozen at navigate/create/search (it can eat weeks).
9. **Transactional email provider:** we DO need one product mailbox (welcome/reply-notify/digest) — use **Resend free tier** (3k/mo) rather than building on user SMTP. One new dependency, accepted knowingly (contradicts my earlier "no Resend" — the alternative is worse).
10. **Job URL scraping** de-risked: try fetch+extract; on any failure fall back to "paste the description" — never block on scraping (many boards block bots).
11. **Follow-up suggestions stay read-time-computed** — no scheduler, no cron surface beyond the existing worker loop.

### 11.2 Missing pieces the first draft forgot (now included above)

- **Suppression semantics + CASL/GDPR:** outbound cold email to Canadians needs identification + unsubscribe honor; V1 adds a signature footer with sender identity and honors "please don't contact me" replies via suppression (classifier label → auto-suppress + suggest apology-none). Data deletion + export shipped in Settings from day one.
- **CV content is sensitive PII** → encrypt `content_text`/`parsed_profile` at rest (same Fernet envelope as mailbox passwords), Sentry scrubbing, no CV text in logs.
- **Duplicate application detection** (§3.5) — without it, bulk import creates embarrassment.
- **Outcome tracking** (`interview/hired`) — without it we can't prove the core metric or power testimonials/insights.
- **Fair-use cap on Pro** (100/mo) — protects LLM margin from scripted abuse; documented on pricing.

### 11.3 Risks register (owned, with mitigations)

- **Engineering:** Gmail app-password availability (fallback: Open-in-Gmail mode is first-class, not an afterthought) · CV parse quality on exotic layouts (paste fallback + warnings chips) · LLM latency stacking (parallelize stages 2/3 after profile; show progressive UI) · webhook/queue single-worker fragility (job retries + idempotency keys + dead-letter status visible in Settings→system health mini-card… **cut**: Sentry alert instead, no UI).
- **Product:** users fear sending from their own Gmail (education + dry-run default ON for first send + volume caps) · AI slop feel (grounding contract §6 + editable everything + "why" everywhere) · five-minute promise broken by slow research (cache + 90s hard budget: whatever isn't done degrades gracefully).
- **Business:** churn-by-success is structural (Sprint plan monetizes it; testimonial ask at "Hired") · seasonal demand (acceptable for side business) · LLM cost drift (ai_runs metering + per-plan budgets from day 1) · niche too small? (quant/finance is beachhead, engine is role-agnostic — expansion is a landing-page change, not a rebuild).

### 11.4 Final simplified V1 (the shipping cut)

**6 surfaces:** Landing+Pricing · Onboarding (2 steps) · Applications · Application detail · Insights · Settings.
**9 modals/sheets. 4 emails. 28 endpoints. 15 tables (12 existing + 3 new). One worker. One template. One niche.**
Everything else in this document that is not in this list ships **after** the first paying customer, in the order customers ask for it.

---

## 12. Open decisions for the founder

1. **Product name + domain** (needed for landing, email footer, Resend domain).
2. Pricing sign-off: Free 3 lifetime / Pro €19 / Sprint €39 (my recommendation stands).
3. Confirm Resend for the 4 product emails (free tier, one dependency).
4. Dry-run ON by default for every user's first send — recommended, tiny friction, huge trust.

*Next implementation step when you say go: Milestone 1 build against this spec — onboarding wizard + applications tracker skeleton + pipeline stages stubbed on the existing schema, deployable end of week.*
