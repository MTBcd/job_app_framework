# Job Application Copilot

## Run the beta app locally (Minimal Review UI)

```bash
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
PYTHONPATH=src APP_ENV=local uvicorn jobapp.api.app:app --reload
```

Open **http://127.0.0.1:8000/ui** — then either click **“Run demo flow”**
(seeds a sample profile + opportunity and lands on the review screen, no
external services needed) or walk the real journey: **Profile → New
application → Review → edit → Approve → Simulate send**.

Notes:

- Without `ANTHROPIC_API_KEY` the app uses the deterministic fake AI provider
  (a banner says so). `export ANTHROPIC_API_KEY=sk-ant-...` before starting
  for real drafts (model via `AI_MODEL`, default `claude-opus-4-8`).
- Sending is **simulated** in this milestone — the fake transport records the
  exact approved content; nothing leaves your machine. Approval freezes an
  immutable snapshot; later edits never change what is "sent".
- Data lives in a local `jobapp.db` SQLite file (gitignored).
- Tests: `pytest` · Lint: `ruff check src tests scripts evals`
- AI quality eval: see `docs/eval.md` · API reference: `docs/api.md`

---

# V0 archive: local spontaneous job application workflow

> Everything below documents the original V0 CLI prototype, kept for
> reference while its logic is ported. The product entry point is the app
> above.

This project is a local, modular Python framework for preparing and sending spontaneous job applications safely and systematically.

It is designed to help you take messy prospecting data, clean it, infer likely professional email addresses, generate personalized drafts, send emails one by one, and improve over time using feedback from replies and delivery failures.

The framework is local-first. It does not require a web app or deployment setup. It uses Excel/CSV inputs and outputs, `.env` configuration, and local logs.

---

## What this framework does

The workflow covers the full preparation and sending cycle:

1. ingest messy prospecting files,
2. normalize names, companies, domains, and raw copied text,
3. infer likely corporate email addresses,
4. generate professional draft emails,
5. send them safely one by one,
6. log all activity locally,
7. avoid duplicate sends,
8. learn from replies and bounces,
9. build retry queues using alternative email patterns.

---

## Main improvements over the original scripts

Compared with the initial scripts, this framework now:

- removes hardcoded credentials,
- removes hardcoded Windows file paths,
- centralizes configuration in `.env`,
- normalizes inconsistent Excel and CSV column names,
- parses messy LinkedIn-style copied text,
- improves company and domain normalization,
- generates multiple likely professional email candidates,
- scores candidates with reasoning,
- supports safer North-American corporate email inference,
- generates editable draft emails from templates,
- supports dry-run sending,
- validates recipient emails before sending,
- blocks consumer email domains by default,
- stores send history locally,
- avoids sending twice to the same person,
- detects replies and strengthens future confidence,
- detects bounces and prepares alternative retries,
- keeps all outputs in local CSV/XLSX files.

---

## Project structure

job_app_framework/
├── .env
├── .env.example
├── README.md
├── requirements.txt
├── data/
│   ├── raw/
│   └── processed/
├── logs/
└── src/
    └── jobapp/
        ├── __init__.py
        ├── cli.py
        ├── config.py
        ├── data_loading.py
        ├── cleaning.py
        ├── contacts.py
        ├── company.py
        ├── email_inference.py
        ├── drafts.py
        ├── sender.py
        ├── exports.py
        ├── pipeline.py
        ├── logging_utils.py
        ├── history.py
        ├── learning.py
        ├── reply_parser.py
        ├── bounce_parser.py
        ├── retry_logic.py
        └── templates/
            ├── email_subject.txt
            └── email_body_en.txt

---

## How the framework is organized

### config.py
Loads environment variables from `.env` and exposes project settings such as:
- input file pattern,
- SMTP settings,
- attachment path,
- send limits,
- retry rules,
- IMAP settings for reply and bounce synchronization.

### data_loading.py
Loads Excel and CSV files from `data/raw/`, reads all sheets where needed, normalizes header names, and merges everything into a single dataframe.

### cleaning.py
Provides core text-cleaning utilities:
- whitespace normalization,
- accent stripping,
- safe email token normalization,
- email validation,
- domain extraction,
- company-name normalization helpers.

### contacts.py
Turns messy raw contact data into structured contact rows. It:
- parses raw text blobs,
- reconstructs names,
- fills missing `first_name`, `last_name`, and `full_name`,
- extracts raw email/domain when present,
- creates normalized name fields used by inference.

### company.py
Normalizes company names and infers company domains. It uses:
- explicit company-to-domain overrides,
- existing domain/email when available,
- learning feedback from past successful sends,
- heuristic fallback logic.

### email_inference.py
Builds likely professional email addresses and ranks them. It:
- generates multiple patterns,
- scores them,
- records reasoning,
- uses known observed domain patterns,
- uses learned feedback from previous sends, replies, and bounces.

### drafts.py
Builds personalized email subjects and bodies from templates stored in `src/jobapp/templates/`.

### sender.py
Sends emails safely or simulates them in dry-run mode. It:
- validates recipients,
- blocks consumer domains by default,
- limits send volume,
- writes send history,
- records feedback events,
- supports retry queue generation.

### history.py
Stores the persistent local send history used to:
- avoid duplicate sends,
- track attempts,
- match replies and bounces,
- keep person-level send state.

### learning.py
Stores feedback events such as:
- sent,
- replied,
- hard bounce,
- soft bounce,
- failed send.

This feedback is later used to improve:
- company-domain confidence,
- domain-pattern confidence,
- company-pattern confidence.

### reply_parser.py
Connects to the mailbox via IMAP and tries to detect replies to previously sent emails. Matching replies are recorded as positive feedback.

### bounce_parser.py
Connects to the mailbox via IMAP and detects delivery failure notifications. Matching bounces are recorded as negative feedback.

### retry_logic.py
Uses send history and candidate lists to decide:
- whether a person should be skipped,
- whether a candidate email was already tried,
- what the next best alternative email should be.

### pipeline.py
Runs the end-to-end preparation flow:
- load raw data,
- normalize contacts,
- normalize companies,
- infer emails,
- build drafts,
- export clean outputs.

### cli.py
Provides the command-line entrypoint for the workflow.

---

## Input data

Place your input files in:

data/raw/

Supported input formats:
- `.csv`
- `.xlsx`
- `.xls`

Excel workbooks with multiple sheets are supported.

---

## Accepted input columns

The loader automatically maps many inconsistent headers to the internal schema.

Examples of accepted column aliases:

### Person name
- `first name`
- `firstname`
- `given name`
- `last name`
- `lastname`
- `surname`
- `family name`
- `full name`
- `name`
- `contact`

### Company and role
- `company`
- `organization`
- `organisation`
- `employer`
- `job title`
- `title`
- `role`
- `position`

### Email and domain
- `email`
- `professional email`
- `company email`
- `mail`
- `email domain`
- `domain`
- `website`
- `company domain`

### Raw text
- `raw text`
- `linkedin text`
- `notes`
- `blob`

### Other optional fields
- `sex`
- `gender`
- `location`
- `city`
- `country`

---

## Expected kinds of raw input

The framework is designed to tolerate imperfect prospecting data, including:

- copied LinkedIn text,
- incomplete names,
- inconsistent company naming,
- pre-existing personal or professional emails,
- domain-only data,
- text blobs mixing person, company, role, and notes,
- different header styles across spreadsheets.

---

## Environment configuration

Create a `.env` file in the project root.

Example:

APP_ENV=local
DATA_INPUT_GLOB=data/raw/*

DEFAULT_COUNTRY=CA
DEFAULT_LANGUAGE=en
DRY_RUN=true

SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USE_TLS=true
SMTP_USERNAME=your_email@example.com
SMTP_PASSWORD=your_app_password
SMTP_FROM_EMAIL=your_email@example.com
SMTP_FROM_NAME=Your Name

ATTACHMENT_PATH=C:/path/to/your/cv.pdf
REPLY_TO=
SEND_RATE_SECONDS=3
MAX_EMAILS_PER_RUN=20

ALLOWED_RECIPIENT_DOMAINS=
BLOCKED_RECIPIENT_DOMAINS=gmail.com,yahoo.com,hotmail.com,outlook.com

SEND_HISTORY_PATH=logs/send_history.csv
LEARNING_FEEDBACK_PATH=logs/learning_feedback.csv
MAX_ATTEMPTS_PER_PERSON=3
MAX_RETRIES_SAME_SOFT_BOUNCE=2

IMAP_HOST=imap.gmail.com
IMAP_USERNAME=your_email@example.com
IMAP_PASSWORD=your_app_password

### Important notes
- `DRY_RUN=true` means no real emails are sent.
- `SMTP_PASSWORD` should be an app password if you use Gmail.
- `IMAP_*` settings are used for reply and bounce synchronization.
- `ATTACHMENT_PATH` points to your CV or attachment file.
- `BLOCKED_RECIPIENT_DOMAINS` prevents accidental sending to consumer mailboxes by default.

---

## Installation

Create and activate a virtual environment, then install dependencies.

### Windows

python -m venv .venvmail
.venvmail\Scripts\activate
pip install -r requirements.txt

### macOS / Linux

python -m venv .venvmail
source .venvmail/bin/activate
pip install -r requirements.txt

Then create your `.env` file in the project root.

---

## Main workflow

The framework is meant to be used in stages.

### 1. Prepare contacts and drafts

python -m src.jobapp.cli prepare

This command:
- loads raw files,
- normalizes contacts,
- normalizes company/domain fields,
- infers likely corporate email addresses,
- builds draft emails,
- writes outputs to `data/processed/`.

### 2. Review the prepared output

Before sending anything, inspect the generated files and focus on:
- `company_name`
- `company_domain`
- `domain_source`
- `email_selected`
- `email_confidence`
- `email_reasoning`
- `draft_subject`
- `draft_body`

This review is essential.

### 3. Dry-run the send flow

Keep:

DRY_RUN=true

Then run:

python -m src.jobapp.cli send

This does not send real emails. It simulates the sending process, writes logs, and updates the send history.

### 4. Send a small real batch

Once you are satisfied:
- set `DRY_RUN=false`,
- reduce `MAX_EMAILS_PER_RUN`,
- send only a few emails first.

Example:

DRY_RUN=false
MAX_EMAILS_PER_RUN=3

Then run:

python -m src.jobapp.cli send

### 5. Sync replies

After some recipients reply, run:

python -m src.jobapp.cli sync-replies

This:
- marks matching messages as replied,
- records positive learning feedback,
- strengthens future domain/pattern confidence.

### 6. Sync bounces

After delivery failures appear in the mailbox, run:

python -m src.jobapp.cli sync-bounces

This:
- marks bounced addresses,
- records negative learning feedback,
- helps the framework avoid bad patterns later.

### 7. Build a retry queue

After bounce synchronization, generate alternative candidates:

python -m src.jobapp.cli build-retry-queue

This creates a retry queue using:
- the next-best untried email pattern,
- retry limits,
- send history,
- bounce-aware filtering.

---

## Available CLI commands

### Prepare contacts and drafts
python -m src.jobapp.cli prepare

### Run send flow
python -m src.jobapp.cli send

### Sync replies from IMAP
python -m src.jobapp.cli sync-replies

### Sync bounces from IMAP
python -m src.jobapp.cli sync-bounces

### Build retry queue
python -m src.jobapp.cli build-retry-queue

---

## Output files

The framework writes local outputs to `data/processed/` and `logs/`.

### In `data/processed/`
Typical files include:
- `contacts_normalized.csv`
- `contacts_normalized.xlsx`
- `drafts_ready.csv`
- `drafts_ready.xlsx`
- `send_results.csv`
- `send_results.xlsx`
- `retry_queue.csv`
- `retry_queue.xlsx`

### In `logs/`
Typical files include:
- `pipeline.log`
- `send_history.csv`
- `learning_feedback.csv`

---

## Main output columns

The normalized export usually contains fields such as:

- `source_file`
- `source_sheet`
- `source_row_number`
- `raw_text`
- `first_name`
- `last_name`
- `full_name`
- `first_name_ascii`
- `last_name_ascii`
- `company_name`
- `company_normalized`
- `job_title`
- `location`
- `domain`
- `company_domain`
- `domain_source`
- `email`
- `email_is_valid`
- `email_selected`
- `email_pattern`
- `email_confidence`
- `email_reasoning`
- `email_candidates_json`
- `email_selected_is_valid`
- `salutation`
- `draft_subject`
- `draft_body`
- `send_status`
- `send_error`
- `sent_at_utc`

---

## Email inference logic

The framework supports and ranks common corporate patterns such as:

- `first@domain`
- `first.last@domain`
- `firstlast@domain`
- `flast@domain`
- `f.last@domain`
- `first_l@domain`
- `last.first@domain`

It also uses:
- known domain-specific pattern learning from existing emails in the dataset,
- company/domain overrides,
- feedback from successful sends,
- feedback from replies,
- penalties from bounces and failures.

For each inferred email, it stores:
- the selected candidate,
- the selected pattern,
- a confidence score,
- reasoning,
- the full candidate list in JSON form.

---

## Duplicate prevention and retries

The framework keeps a local send history and uses it to avoid sending twice to the same person.

It checks:
- whether the person was already successfully contacted,
- whether the same email candidate was already tried,
- whether retry attempts are exhausted.

When a hard bounce is detected, the system can prepare a new retry queue using the next-best candidate that has not been tried yet.

---

## Learning and self-improvement

A major feature of the final framework is that it improves with use.

### Positive signals
- message sent,
- successful reply,
- repeated successful contact at the same domain/company.

### Negative signals
- hard bounce,
- soft bounce,
- failed send.

These signals are written to `logs/learning_feedback.csv` and later reused to improve:
- company-domain selection,
- domain-pattern ranking,
- confidence scores.

So over time, the framework becomes more accurate for the companies and domains you contact repeatedly.

---

## Draft templates

Templates are stored in:

src/jobapp/templates/

Files:
- `email_subject.txt`
- `email_body_en.txt`

You can edit these safely without changing the Python logic.

The draft builder injects values such as:
- company name,
- salutation,
- job title clause,
- sender name,
- sender email.

---

## Safety behavior

The framework is designed to reduce mistakes.

It:
- validates recipient email addresses,
- blocks consumer domains by default,
- supports dry-run mode,
- limits sends per run,
- delays between sends,
- keeps local logs,
- stores send history,
- supports manual review before real sending,
- avoids duplicate sends.

---

## Recommended first run

For your first real use:

1. place only a small sample of rows in `data/raw/`,
2. keep `DRY_RUN=true`,
3. run `prepare`,
4. inspect the processed files,
5. run `send`,
6. inspect `send_history.csv`,
7. only then switch to real sending,
8. start with 2 to 5 emails maximum.

---

## Recommended real usage cycle

A safe operating cycle is:

python -m src.jobapp.cli prepare
python -m src.jobapp.cli send
python -m src.jobapp.cli sync-replies
python -m src.jobapp.cli sync-bounces
python -m src.jobapp.cli build-retry-queue

---

## Known limitations

This framework is local-first and heuristic by design.

That means:
- it does not call external enrichment APIs,
- company-domain inference may still require manual overrides,
- some corporate email formats remain ambiguous,
- name parsing can still be imperfect on noisy or incomplete data,
- reply and bounce detection depends on mailbox structure and IMAP access.

Because of this, manual review remains important before real sending.

---

## Summary

This framework gives you a practical local system to:

- clean prospecting data,
- normalize people and companies,
- infer likely corporate emails,
- generate email drafts,
- send safely,
- avoid duplicates,
- learn from outcomes,
- retry better candidates over time.

It is intentionally simple, local, and reusable, while being much safer and more structured than the original standalone scripts.
