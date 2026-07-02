from __future__ import annotations

from pathlib import Path

import pandas as pd


NORMALIZED_COLUMN_ORDER = [
    "source_file",
    "source_sheet",
    "source_row_number",
    "raw_text",
    "first_name",
    "last_name",
    "full_name",
    "first_name_ascii",
    "last_name_ascii",
    "company_name",
    "company_normalized",
    "job_title",
    "location",
    "domain",
    "company_domain",
    "domain_source",
    "email",
    "email_is_valid",
    "email_selected",
    "email_pattern",
    "email_confidence",
    "email_reasoning",
    "email_candidates_json",
    "email_selected_is_valid",
    "needs_manual_review",
    "manual_review_reason",
    "salutation",
    "draft_subject",
    "draft_body",
    "send_status",
    "send_error",
    "sent_at_utc",
]


def reorder_columns(df: pd.DataFrame) -> pd.DataFrame:
    front = [col for col in NORMALIZED_COLUMN_ORDER if col in df.columns]
    tail = [col for col in df.columns if col not in front]
    return df[front + tail]


def write_outputs(df: pd.DataFrame, output_stem: Path) -> None:
    output_stem.parent.mkdir(parents=True, exist_ok=True)
    ordered = reorder_columns(df)
    ordered.to_csv(output_stem.with_suffix(".csv"), index=False, encoding="utf-8-sig")
    ordered.to_excel(output_stem.with_suffix(".xlsx"), index=False)
