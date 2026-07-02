# V0 Repository Audit

**Scope:** full read of every module in `src/jobapp/`, templates, configuration, git hygiene, and committed data.
**Date:** 2026-07-02
**Verdict in one line:** the prototype contains a genuinely valuable heuristic core (email inference, learning signals, bounce/reply parsing, safety rails) wrapped in a storage and execution model (CSV + pandas + synchronous CLI) that cannot carry a SaaS — and the repository itself has two P0 security problems that must be fixed before anything else.

---

## 1. P0 findings — act before any feature work

### 1.1 Live credentials are committed and pushed to GitHub

`.env` is tracked in git and pushed to the `main` branch of `mtbcd/job_app_framework`. It contains real values for `SMTP_PASSWORD`, `IMAP_PASSWORD`, `SMTP_USERNAME`, `IMAP_USERNAME`, plus a personal phone number and attachment path.

Anyone with read access to the repository (and anyone who ever gets it — forks, clones, leaked tokens, a future open-sourcing mistake) has working credentials for the Gmail account.

**Remediation (owner decision required, do not skip any step):**

1. **Rotate now.** Revoke the Gmail app passwords (SMTP and IMAP) in Google Account → Security → App passwords. Rotation is the fix; deleting the file is not, because the secret lives in git history.
2. Remove `.env` from tracking and add a `.gitignore` (venv, `__pycache__`, `.env`, `data/`, `logs/`).
3. Rewrite history to purge the secret and the PII files (e.g. `git filter-repo --invert-paths --path .env --path .venvmail ...`), then force-push. This rewrites `main`'s history — acceptable now because the repo has a single commit and no other consumers. It will never be this cheap again.
4. Add secret scanning (GitHub push protection + `gitleaks` in CI) so this class of mistake becomes impossible to repeat.

### 1.2 ~9,000 rows of real personal data are committed

Tracked files include `contacts_normalized.csv` (8,940 rows), `drafts_ready.csv` (8,940), `send_results.csv` (1,919), `logs/send_history.csv` (392 real send attempts), `logs/learning_feedback.csv` (440 events with recipient emails), plus xlsx duplicates at the repo root and under `data/processed/`, and the raw prospecting workbooks (`Talent_aquisition_DB.xlsx`, `prospecting_contacts_sorted_by_jr_quant_pay.xlsx`).

This is real PII (names, employers, job titles, inferred and real email addresses) of third parties, in a git repo. For a company that wants to sell outreach software, this is both a legal exposure (GDPR/PIPEDA — these are largely Canadian and EU contacts) and a reputational one. It must come out of history in the same `filter-repo` pass as the credentials.

### 1.3 Repo hygiene

- **7,921 of the 7,999 tracked files are a committed Windows virtualenv** (`.venvmail/`), plus ~100 `__pycache__/*.pyc` files. Source code is 20 files.
- No `.gitignore`, no `pyproject.toml`, no lockfile, no CI, no tests, no license.
- `requirements.txt` is four unpinned lower-bound dependencies.

None of this is unusual for a personal prototype. All of it is disqualifying for a company repo, and all of it is a one-hour fix.

---

## 2. Current architecture (Step 2)

### 2.1 Shape

V0 is a **local-first batch ETL pipeline** operated by a CLI, with CSV files acting as both database and message bus:

```
data/raw/*.xlsx|csv
      │
      ▼
┌─────────────────────────────────────────────────────────┐
│ prepare (pipeline.py)                                    │
│  data_loading → contacts → company → email_inference →   │
│  drafts → exports                                        │
└─────────────────────────────────────────────────────────┘
      │  data/processed/drafts_ready.csv|xlsx
      ▼
┌──────────────┐   logs/send_history.csv   ┌──────────────┐
│ send          │◄────────────────────────►│ history.py    │
│ (sender.py)   │   logs/learning_feedback │ learning.py   │
└──────────────┘◄────────────────────────►└──────────────┘
      │ SMTP (Gmail app password)                ▲
      ▼                                          │
recipient mailboxes                              │
      │ IMAP (same account)                      │
      ▼                                          │
┌───────────────────────────────┐                │
│ sync-replies / sync-bounces    │────────────────┘
│ (reply_parser / bounce_parser) │
└───────────────────────────────┘
      │
      ▼
build-retry-queue (retry_logic.py) → data/processed/retry_queue.csv
```

- **Domain model:** a pandas `DataFrame` with ~32 stringly-typed columns. Every module takes the frame, adds columns, returns it.
- **Persistence:** append-only CSVs (`send_history`, `learning_feedback`) re-read in full on essentially every query, rewritten in full on every update.
- **Execution:** synchronous, single-process, rate-limited with `time.sleep`.
- **Learning loop:** send/reply/bounce events carry weights (sent +1.0, delivered +1.5, replied +4.0, soft bounce −0.75, failed −1.0, hard bounce −3.0); aggregates boost future domain/pattern confidence. The loop is real and closes — this is the most important architectural idea in the repo.
- **Configuration:** `.env` via two competing settings objects (`config.Settings` and `sender.SendSettings.from_env()`), plus scattered raw `os.getenv` calls in `company.py`, `email_inference.py`, `drafts.py`.

### 2.2 Module-by-module assessment

| Module | Lines | What it does | Strengths | Weaknesses | Verdict |
|---|---|---|---|---|---|
| `config.py` | 81 | `.env` → dataclass | Centralized, typed-ish | Defaults evaluated at import time; `load_dotenv(override=True)` stomps real env (12-factor violation); no validation (`int()` crashes on bad input); duplicated by `SendSettings` | **Replace** (pydantic-settings) |
| `data_loading.py` | 103 | Multi-file/sheet ingest, header aliasing, duplicate-column coalescing | The alias map and coalescing logic encode real-world messiness knowledge | `source_row_number = index + 2` is wrong for any run with >1 file/sheet (index is post-concat); loads everything in memory | **Keep logic**, port to import service |
| `cleaning.py` | 237 | Text/email/domain normalization primitives | Pure, deterministic, testable; unicode/accent handling | Top 95 lines are a commented-out duplicate of the file itself | **Keep**, delete dead half, add tests |
| `contacts.py` | 355 | Name parsing (particles, prefixes/suffixes, initials, comma-reversed), raw LinkedIn-blob parsing, contact normalization | Genuinely good name heuristics — the particle/initials handling is beyond what most v1 products ship | Row-wise pandas ops; `is_initials_only` computed here *and* re-derived in `email_inference` (two sources of truth); raw-text parser is fragile line-order heuristics | **Keep parsing core**, restructure I/O |
| `company.py` | 301 | Company normalization + domain inference | Layered resolution order (existing → verified file → override → learned → heuristic) is the right design | 150-entry finance-specific `DOMAIN_OVERRIDES` dict and a `BAD_HEURISTIC_DOMAIN_FIXES` patch dict hardcoded in source — this is *data in code*; reads env directly | **Keep resolution algorithm; move data to DB** |
| `email_inference.py` | 479 | Candidate generation, scoring, confidence, reasoning traces, review flags | **The crown jewel.** Pattern priors, learned per-domain patterns from the dataset itself, verified-pattern boosts, initials-only logic, review thresholds with named reasons, full reasoning trace + candidates JSON | `LearningStore.aggregate()` re-reads and re-aggregates the whole CSV **per row, twice** (O(n·m) file I/O — fine at 400 rows, dead at 100k); `get_company_pattern` re-reads its CSV per call; pattern learning happens inline on the input frame | **Keep algorithm intact**, re-platform storage |
| `drafts.py` | 367 | Template rendering, salutations, company display names | Salutation fallbacks; template/logic separation exists | 200-entry hardcoded company display-name dict; **the founder's name is hardcoded as default sender**; personal quant-finance pitch baked into fallback template; `import re` twice; module-level env read | **Replace** (template engine per user/org; display names → DB) |
| `sender.py` | 548 | Validation, allow/block lists, dedupe, dry-run, SMTP send, history + learning writes, failure classification | Safety rails are the right instincts: dry-run default, consumer-domain blocklist, run caps, dedupe by person and by candidate, manual-review gating | 120-line commented-out previous version left in file; duplicate settings object; duplicate email regex that *disagrees* with `cleaning.is_valid_email` (apostrophes); one function mixes policy, transport, persistence; new SMTP connection per message; blocking `sleep`; `Message-ID @local.jobapp` (non-existent domain — hurts threading/deliverability) | **Decompose**: policy engine (keep) / transport adapter (replace) / persistence (replace) |
| `history.py` | 229 | Send-history store + person keys | `build_person_key` identity logic; attempt counting | Full-file read per query, full-file rewrite per update, no locking (concurrent runs corrupt); `update_status(email_attempted=...)` flips **every** row sharing that email across all people | **Replace with Postgres**; keep the semantics |
| `learning.py` | 160 | Weighted event log + aggregates | The event weights and the three aggregate views (company↔domain, domain↔pattern, company↔pattern) are a sound v0 signal model | `aggregate()` recomputes from disk on every call and is called per-row; no idempotency beyond message-id check | **Keep model, re-platform** |
| `retry_logic.py` | 206 | Skip/next-candidate decisions | Pure functions over history; terminal-status sets; soft-bounce caps | Depends on history store's O(n) scans | **Keep**, becomes the follow-up state machine seed |
| `reply_parser.py` | 225 | IMAP reply detection | Correct matching priority: `In-Reply-To`/`References` first, sender fallback second; bounce exclusion | Fetches full RFC822 for up to 300 messages every run; `SINCE` computed from **earliest** send date → mailbox scan grows forever; sender-fallback marks auto-replies/OOO as "replied" (pollutes the +4.0 learning signal); bare `except` everywhere | **Keep heuristics, replace transport + idempotency** |
| `bounce_parser.py` | 413 | IMAP bounce detection/classification | Hard/soft regex corpus incl. French; DSN (`message/delivery-status`) parsing; nested rfc822 walking; encoding fallbacks — hard-won operational knowledge | Same IMAP scan issues; `update_status` rewrites the file per bounce; recipient extraction can mismatch | **Keep corpus + classifier**, replace transport |
| `pattern_overrides.py` | 87 | Curated verified-pattern CSV | The concept of *verified* patterns with confidence + provenance | File re-read per lookup | **Keep concept → DB table** |
| `exports.py` | 54 | Column ordering, CSV/XLSX writes | Fine | XLSX write of 9k rows is slow; always writes both formats | **Keep** as export utility |
| `pipeline.py` | 38 | Orchestration | Readable | Hidden side-writes; `send` path re-runs it (see 2.3) | **Replace** with explicit workflow |
| `cli.py` | 100 | argparse entrypoint | Thin, correct | See 2.3 | **Keep pattern** for internal tooling |
| `logging_utils.py` | 24 | File+stream logger | Exists | Single global logger, no structure, no correlation ids | **Replace** (structlog) |

### 2.3 Cross-cutting defects found during the audit

These are bugs/design faults independent of any re-architecture decision. I am **not** fixing them now (Step 7 — nothing modified without validation), but they must not survive into V1:

1. **The advertised review workflow is broken by the code.** README says: run `prepare`, manually review `drafts_ready`, then run `send`. But `run_send()` calls `prepare_contacts()` again and sends from the *freshly re-inferred* frame — human edits to the reviewed file are silently ignored. The single most important safety promise of the tool is not actually wired.
2. **Learning-signal pollution.** Provided personal emails generate `sent` events with `domain=gmail.com` and `pattern=provided` (visible in the committed `learning_feedback.csv`), so consumer domains accumulate positive weight attached to company keys. The learning loop is learning noise.
3. **O(n²) file I/O** in inference (per-row full re-read + re-aggregate of the learning CSV, twice per row) and per-lookup re-read of the pattern CSV.
4. **`source_row_number` is wrong** whenever more than one file/sheet is loaded (computed as post-concat index + 2), so "go fix row N in your spreadsheet" points at the wrong row — a trust-destroying bug for a data product.
5. **History updates are not person-scoped**: a bounce for `j.smith@x.com` flips status for every person who ever resolved to that address.
6. **No concurrency safety anywhere**: two simultaneous CLI runs interleave CSV appends and full-file rewrites; the dedupe guarantee ("never email the same person twice") only holds single-threaded.
7. **Three disagreeing email regexes** (`cleaning`, `sender`, `reply/bounce parsers`) — an address can be valid at inference time and invalid at send time.
8. **Deliverability gaps**: fake Message-ID domain, no `List-Unsubscribe`, no plain+HTML alternative, per-message SMTP connections, no warm-up pacing beyond a fixed sleep, no SPF/DKIM/DMARC story. Fine for 3 personal emails a day; fatal for a product whose deliverability *is* the product.
9. **Dead code as noise**: ~215 lines of commented-out duplicates (half of `cleaning.py`, the old `send_dataframe`), module headers like `# file: src/jobapp/company.py`, double imports — artifacts of copy-paste iteration that make every future diff harder to review.
10. **Windows-coupled artifacts**: committed `.venvmail` with `.exe` files; absolute `C:\Users\...` paths visible in committed logs.

### 2.4 What V0 got *right* (credit where due)

1. **The feedback loop exists.** Send → observe (reply/bounce) → weight → re-rank. Most outreach prototypes never close this loop. Kandi-class products live or die on it.
2. **Confidence is explainable.** Every inferred email carries a pattern, a numeric confidence, and a human-readable reasoning list, and low-confidence rows are gated behind named review reasons (`heuristic_domain`, `top_candidates_too_close`, …). That is exactly the trust surface an AI outreach product needs — it just lives in CSV cells today.
3. **Safety-first defaults.** Dry-run on by default, consumer domains blocked, hard caps per run, dedupe by person *and* by attempted address, initials-only names refuse to invent first names. These instincts must survive every rewrite.
4. **Resolution layering.** Existing data → verified/curated → override → learned → heuristic, with provenance recorded (`domain_source`). This is the correct precedence design for every enrichment we will ever build; it generalizes far beyond emails.
5. **Real operational knowledge** encoded in the bounce corpus (incl. French), DSN parsing, header decoding fallbacks, LinkedIn blob parsing. This was earned by actually running campaigns (392 real sends in the history) and is expensive to re-learn.

---

## 3. Conclusion

V0 is a validated **algorithm prototype**, not an application substrate. The inference/learning/parsing logic is worth extracting nearly verbatim into a properly typed, tested core; the storage, configuration, execution, and delivery layers must be rebuilt on the target stack; and the repository needs an immediate security remediation before any of that starts.

The decision framework applied throughout: **keep encoded knowledge, replace plumbing.** Knowledge (patterns, weights, corpora, precedence rules, safety policies) took months of real usage to accumulate. Plumbing (CSV stores, pandas frames, sleep loops) took days to write and would take longer to scale than to replace.

Next documents:
- `01-target-architecture.md` — what we build instead, and why (Steps 3–5).
- `02-roadmap.md` — independently deployable milestones (Step 6).
