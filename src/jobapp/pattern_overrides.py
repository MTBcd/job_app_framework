# =========================
# file: src/jobapp/pattern_overrides.py
# =========================
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from .cleaning import extract_domain, normalize_company_name, normalize_whitespace


DEFAULT_PATTERN_PATH = Path("data/manual/company_email_patterns.csv")


def normalize_company_key(value: str) -> str:
    return normalize_company_name(value).replace(" and ", " ").strip().lower()


def load_company_patterns(path: str | Path = DEFAULT_PATTERN_PATH) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        return pd.DataFrame(
            columns=[
                "company_name",
                "company_normalized",
                "domain",
                "email_pattern",
                "confidence",
                "source",
                "notes",
            ]
        )

    df = pd.read_csv(path)
    for column in [
        "company_name",
        "company_normalized",
        "domain",
        "email_pattern",
        "confidence",
        "source",
        "notes",
    ]:
        if column not in df.columns:
            df[column] = ""

    df["company_normalized"] = df["company_normalized"].where(
        df["company_normalized"].astype(str).str.strip().ne(""),
        df["company_name"].map(normalize_company_key),
    )
    df["company_normalized"] = df["company_normalized"].map(normalize_company_key)
    df["domain"] = df["domain"].map(extract_domain)
    df["email_pattern"] = df["email_pattern"].map(lambda x: normalize_whitespace(x).lower())
    df["confidence"] = pd.to_numeric(df["confidence"], errors="coerce").fillna(0.95)
    return df


def get_company_pattern(
    company_name: str,
    company_normalized: str = "",
    path: str | Path = DEFAULT_PATTERN_PATH,
) -> dict[str, Any] | None:
    df = load_company_patterns(path)
    if df.empty:
        return None

    keys = {
        normalize_company_key(company_name),
        normalize_company_key(company_normalized),
    }
    keys.discard("")

    matched = df[df["company_normalized"].isin(keys)]
    if matched.empty:
        return None

    row = matched.sort_values("confidence", ascending=False).iloc[0]
    return {
        "company_name": row.get("company_name", ""),
        "company_normalized": row.get("company_normalized", ""),
        "domain": row.get("domain", ""),
        "email_pattern": row.get("email_pattern", ""),
        "confidence": float(row.get("confidence", 0.95) or 0.95),
        "source": row.get("source", ""),
        "notes": row.get("notes", ""),
    }