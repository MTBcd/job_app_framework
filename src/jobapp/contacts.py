# =========================
# file: src/jobapp/contacts.py
# =========================
from __future__ import annotations

import re
from typing import Any

import pandas as pd

from .cleaning import (
    ascii_email_token,
    company_display_name,
    extract_domain,
    is_valid_email,
    normalize_whitespace,
    smart_title,
    split_name_parts,
)


EMAIL_RE = re.compile(r"([A-Z0-9._%+\-']+@[A-Z0-9.-]+\.[A-Z]{2,})", flags=re.IGNORECASE)

TITLE_HINTS = (
    "analyst",
    "associate",
    "manager",
    "director",
    "vice president",
    "vp",
    "partner",
    "principal",
    "trader",
    "portfolio manager",
    "investment",
    "sales",
    "hr",
    "talent",
    "recruit",
    "recruiter",
    "recruiting",
    "compliance",
    "operations",
    "research",
    "managing director",
)

NAME_PREFIXES = {
    "mr",
    "mrs",
    "ms",
    "miss",
    "mx",
    "dr",
    "prof",
    "monsieur",
    "mme",
    "mlle",
}

NAME_SUFFIXES = {
    "jr",
    "sr",
    "ii",
    "iii",
    "iv",
    "v",
    "cfa",
    "frm",
    "phd",
    "mba",
    "msc",
    "m.sc",
    "bsc",
    "caia",
    "cpa",
    "cmt",
}

SURNAME_PARTICLES = {
    "da",
    "de",
    "del",
    "dela",
    "de la",
    "de las",
    "de le",
    "de los",
    "des",
    "di",
    "du",
    "el",
    "al",
    "la",
    "le",
    "van",
    "von",
    "der",
    "den",
    "ten",
    "ter",
    "bin",
    "ibn",
    "st",
    "saint",
}


def _clean_name_token(token: str) -> str:
    token = normalize_whitespace(token)
    token = token.strip(" ,;|")
    token = re.sub(r"^[.]+|[.]+$", "", token)
    return token


def _normalized_token(token: str) -> str:
    return ascii_email_token(token).lower()


def _is_initial_token(token: str) -> bool:
    cleaned = re.sub(r"[^A-Za-z]", "", token or "")
    return len(cleaned) == 1


def _strip_name_noise(value: str) -> str:
    text = normalize_whitespace(value)
    text = re.sub(r"\([^)]*\)", " ", text)
    text = text.replace("|", " ").replace("•", " ").replace("·", " ")
    text = re.sub(r"\b(?:linkedin|open to work)\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" ,;-")
    return text


def _filtered_name_parts(name: str) -> list[str]:
    raw_parts = split_name_parts(_strip_name_noise(name))
    parts: list[str] = []
    for part in raw_parts:
        token = _clean_name_token(part)
        if not token:
            continue
        norm = _normalized_token(token)
        if norm in NAME_PREFIXES or norm in NAME_SUFFIXES:
            continue
        parts.append(token)
    return parts


def parse_full_name(full_name: str) -> dict[str, Any]:
    parts = _filtered_name_parts(full_name)
    if not parts:
        return {
            "full_name_clean": "",
            "first_name": "",
            "last_name": "",
            "first_initial": "",
            "last_initial": "",
            "is_initials_only": False,
            "name_parse_warning": "missing_name",
        }

    if "," in normalize_whitespace(full_name):
        chunks = [normalize_whitespace(chunk) for chunk in normalize_whitespace(full_name).split(",", 1)]
        if len(chunks) == 2 and chunks[0] and chunks[1]:
            reordered = _filtered_name_parts(f"{chunks[1]} {chunks[0]}")
            if reordered:
                parts = reordered

    if len(parts) == 1:
        token = smart_title(parts[0])
        first_initial = ascii_email_token(token)[:1]
        return {
            "full_name_clean": token,
            "first_name": token,
            "last_name": "",
            "first_initial": first_initial,
            "last_initial": "",
            "is_initials_only": _is_initial_token(token),
            "name_parse_warning": "single_token_name",
        }

    normalized_parts = [_normalized_token(part) for part in parts]
    surname_start = len(parts) - 1
    i = surname_start - 1
    while i >= 0:
        single = normalized_parts[i]
        pair = (
            f"{normalized_parts[i]} {normalized_parts[i + 1]}"
            if i + 1 < len(normalized_parts)
            else single
        )
        if single in SURNAME_PARTICLES or pair in SURNAME_PARTICLES:
            surname_start = i
            i -= 1
            continue
        break

    first_parts = parts[:surname_start]
    last_parts = parts[surname_start:]

    if not first_parts:
        first_parts = parts[:-1]
        last_parts = parts[-1:]

    first_name = " ".join(smart_title(part) for part in first_parts).strip()
    last_name = " ".join(smart_title(part) for part in last_parts).strip()

    first_initial = ascii_email_token(first_name)[:1]
    last_initial = ascii_email_token(last_name)[:1]

    first_initial_only = all(_is_initial_token(part) for part in first_parts) and bool(first_parts)

    warning = ""
    if first_initial_only:
        warning = "first_name_initial_only"
    elif not last_name:
        warning = "missing_last_name"
    elif len(last_parts) > 2:
        warning = "compound_last_name"

    return {
        "full_name_clean": normalize_whitespace(f"{first_name} {last_name}"),
        "first_name": first_name,
        "last_name": last_name,
        "first_initial": first_initial,
        "last_initial": last_initial,
        "is_initials_only": first_initial_only and bool(last_name),
        "name_parse_warning": warning,
    }


def parse_raw_text(raw_text: str) -> dict[str, str]:
    text = normalize_whitespace(raw_text)
    lines = [line.strip("•- ").strip() for line in re.split(r"[\n|]+", text) if line.strip()]
    payload = {
        "raw_email": "",
        "raw_domain": "",
        "raw_name": "",
        "raw_company": "",
        "raw_title": "",
    }

    email_match = EMAIL_RE.search(text)
    if email_match:
        payload["raw_email"] = email_match.group(1)
        payload["raw_domain"] = extract_domain(payload["raw_email"])

    if lines:
        payload["raw_name"] = lines[0]

    for line in lines[1:]:
        lowered = line.lower()
        if "@" in line and not payload["raw_domain"]:
            payload["raw_domain"] = extract_domain(line)
            continue
        if any(keyword in lowered for keyword in TITLE_HINTS):
            if not payload["raw_title"]:
                payload["raw_title"] = line
            continue
        if not payload["raw_company"] and 1 <= len(line.split()) <= 10:
            payload["raw_company"] = line

    return payload


def normalize_contacts(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    for column in [
        "first_name",
        "last_name",
        "full_name",
        "company_name",
        "job_title",
        "email",
        "domain",
        "raw_text",
        "sex",
        "location",
    ]:
        if column not in df.columns:
            df[column] = ""

    raw_parsed = df["raw_text"].fillna("").map(parse_raw_text).apply(pd.Series)
    for column in raw_parsed.columns:
        if column not in df.columns:
            df[column] = ""
        df[column] = df[column].where(
            df[column].astype(str).str.strip().ne(""),
            raw_parsed[column],
        )

    df["full_name"] = df["full_name"].fillna("").astype(str).str.strip()
    mask_missing_name = df["full_name"].eq("") & (
        df["first_name"].astype(str).str.strip().ne("")
        | df["last_name"].astype(str).str.strip().ne("")
    )
    df.loc[mask_missing_name, "full_name"] = (
        df.loc[mask_missing_name, "first_name"].fillna("").astype(str).str.strip()
        + " "
        + df.loc[mask_missing_name, "last_name"].fillna("").astype(str).str.strip()
    ).str.strip()

    df["full_name"] = df["full_name"].where(
        df["full_name"].astype(str).str.strip().ne(""),
        df["raw_name"],
    )

    parsed = df["full_name"].map(parse_full_name).apply(pd.Series)

    df["first_name"] = df["first_name"].where(
        df["first_name"].astype(str).str.strip().ne(""),
        parsed["first_name"],
    )
    df["last_name"] = df["last_name"].where(
        df["last_name"].astype(str).str.strip().ne(""),
        parsed["last_name"],
    )

    df["first_name"] = df["first_name"].map(smart_title)
    df["last_name"] = df["last_name"].map(smart_title)
    df["full_name"] = parsed["full_name_clean"].where(
        parsed["full_name_clean"].astype(str).str.strip().ne(""),
        (df["first_name"].fillna("") + " " + df["last_name"].fillna("")).str.strip(),
    )

    df["company_name"] = df["company_name"].where(
        df["company_name"].astype(str).str.strip().ne(""),
        df["raw_company"],
    ).map(company_display_name)

    df["job_title"] = df["job_title"].where(
        df["job_title"].astype(str).str.strip().ne(""),
        df["raw_title"],
    ).map(normalize_whitespace)

    df["email"] = df["email"].where(
        df["email"].astype(str).str.strip().ne(""),
        df["raw_email"],
    ).map(normalize_whitespace)

    df["domain"] = df["domain"].where(
        df["domain"].astype(str).str.strip().ne(""),
        df["raw_domain"],
    ).map(extract_domain)

    df["first_name_ascii"] = df["first_name"].map(ascii_email_token)
    df["last_name_ascii"] = df["last_name"].map(ascii_email_token)
    df["first_initial"] = parsed["first_initial"].fillna("").astype(str)
    df["last_initial"] = parsed["last_initial"].fillna("").astype(str)
    df["is_initials_only"] = parsed["is_initials_only"].fillna(False).astype(bool)
    df["name_parse_warning"] = parsed["name_parse_warning"].fillna("").astype(str)
    df["email_is_valid"] = df["email"].map(is_valid_email)

    return df

