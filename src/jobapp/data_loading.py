from __future__ import annotations

import re
from pathlib import Path

import pandas as pd


COLUMN_ALIASES: dict[str, str] = {
    "first_name": "first_name",
    "firstname": "first_name",
    "given_name": "first_name",
    "givenname": "first_name",
    "last_name": "last_name",
    "lastname": "last_name",
    "surname": "last_name",
    "family_name": "last_name",
    "full_name": "full_name",
    "name": "full_name",
    "contact": "full_name",
    "company": "company_name",
    "organization": "company_name",
    "organisation": "company_name",
    "employer": "company_name",
    "job_title": "job_title",
    "job": "job_title",
    "title": "job_title",
    "role": "job_title",
    "position": "job_title",
    "email": "email",
    "professional_email": "email",
    "company_email": "email",
    "mail": "email",
    "email_domain": "domain",
    "company_domain": "domain",
    "domain": "domain",
    "website": "domain",
    "raw_text": "raw_text",
    "linkedin_text": "raw_text",
    "notes": "raw_text",
    "blob": "raw_text",
    "sex": "sex",
    "gender": "sex",
    "location": "location",
    "city": "location",
    "country": "location",
}


def canonicalize_header(value: str) -> str:
    value = str(value or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", "_", value).strip("_")
    return COLUMN_ALIASES.get(value, value)


def _read_single_file(path: Path) -> list[pd.DataFrame]:
    if path.suffix.lower() == ".csv":
        df = pd.read_csv(path)
        df["source_file"] = path.name
        df["source_sheet"] = "csv"
        return [df]

    if path.suffix.lower() in {".xlsx", ".xls"}:
        excel = pd.ExcelFile(path)
        frames: list[pd.DataFrame] = []
        for sheet_name in excel.sheet_names:
            df = excel.parse(sheet_name)
            df["source_file"] = path.name
            df["source_sheet"] = sheet_name
            frames.append(df)
        return frames

    return []


def load_input_frames(paths: list[Path]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in paths:
        frames.extend(_read_single_file(path))

    if not frames:
        raise FileNotFoundError("No input CSV/XLS/XLSX files found.")

    combined = pd.concat(frames, ignore_index=True)
    combined.columns = [canonicalize_header(col) for col in combined.columns]
    combined = _coalesce_duplicate_columns(combined)
    combined["source_row_number"] = combined.index + 2
    return combined


def _coalesce_duplicate_columns(df: pd.DataFrame) -> pd.DataFrame:
    result = pd.DataFrame(index=df.index)
    for col in dict.fromkeys(df.columns):
        matches = df.loc[:, df.columns == col]
        if matches.shape[1] == 1:
            result[col] = matches.iloc[:, 0]
            continue

        merged = matches.iloc[:, 0]
        for idx in range(1, matches.shape[1]):
            merged = merged.combine_first(matches.iloc[:, idx])
        result[col] = merged
    return result
