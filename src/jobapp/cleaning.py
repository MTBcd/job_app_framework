# from __future__ import annotations

# import json
# import re
# from typing import Iterable

# import pandas as pd
# from unidecode import unidecode


# CORPORATE_SUFFIXES = {
#     "inc", "inc.", "corp", "corporation", "llc", "ltd", "limited", "lp", "llp",
#     "co", "company", "group", "holdings", "plc", "sa", "sas", "ag", "gmbh"
# }

# PARTICLES = {"de", "del", "de la", "de le", "van", "von", "da", "dos", "du", "la", "le", "des", "st", "saint"}


# def normalize_whitespace(value: object) -> str:
#     text = "" if value is None or pd.isna(value) else str(value)
#     text = re.sub(r"[\u00a0\t\r]+", " ", text)
#     return re.sub(r"\s+", " ", text).strip()


# def strip_accents_keep_case(value: str) -> str:
#     return unidecode(value or "")


# def slug_token(value: str) -> str:
#     value = strip_accents_keep_case(normalize_whitespace(value)).lower()
#     value = value.replace("&", " and ")
#     value = re.sub(r"[^a-z0-9]+", " ", value)
#     return re.sub(r"\s+", " ", value).strip()


# def ascii_email_token(value: str) -> str:
#     value = strip_accents_keep_case(normalize_whitespace(value)).lower()
#     value = value.replace("'", "").replace("’", "")
#     value = re.sub(r"[^a-z0-9.-]+", "", value)
#     return value.strip(".-")


# def split_name_parts(name: str) -> list[str]:
#     cleaned = normalize_whitespace(name).replace(",", " ")
#     parts = [part for part in re.split(r"[\s/]+", cleaned) if part]
#     return parts


# def smart_title(value: str) -> str:
#     if not value:
#         return ""
#     text = normalize_whitespace(value)
#     parts = re.split(r"([\s\-'])", text)
#     return "".join(part.capitalize() if re.match(r"[A-Za-zÀ-ÿ]", part) else part for part in parts)


# def normalize_company_name(value: str) -> str:
#     text = normalize_whitespace(value)
#     text = re.sub(r"\(.*?\)", "", text)
#     text = text.replace("&", " and ")
#     text = re.sub(r"\bprivate banking\b", "", text, flags=re.IGNORECASE)
#     tokens = [tok for tok in slug_token(text).split() if tok not in CORPORATE_SUFFIXES]
#     return " ".join(tokens).strip()


# def company_display_name(value: str) -> str:
#     text = normalize_whitespace(value)
#     text = re.sub(r"\s+", " ", text)
#     return text.strip(" -,")


# def is_valid_email(value: object) -> bool:
#     if value is None or (isinstance(value, float) and pd.isna(value)):
#         return False
#     email = normalize_whitespace(value)
#     pattern = r"^[A-Z0-9._%+\-']+@[A-Z0-9.-]+\.[A-Z]{2,}$"
#     return re.match(pattern, email, flags=re.IGNORECASE) is not None


# def extract_domain(value: object) -> str:
#     text = normalize_whitespace(value).lower()
#     if "@" in text:
#         return text.split("@", 1)[1].strip(" .;,")
#     text = re.sub(r"^https?://", "", text)
#     text = re.sub(r"^www\.", "", text)
#     match = re.search(r"([a-z0-9.-]+\.[a-z]{2,})", text)
#     return match.group(1) if match else ""


# def safe_json_dumps(value: object) -> str:
#     return json.dumps(value, ensure_ascii=False)





from __future__ import annotations

import json
import re

import pandas as pd
from unidecode import unidecode


CORPORATE_SUFFIXES = {
    "inc",
    "inc.",
    "corp",
    "corporation",
    "llc",
    "ltd",
    "limited",
    "lp",
    "llp",
    "co",
    "company",
    "group",
    "holdings",
    "plc",
    "sa",
    "sas",
    "ag",
    "gmbh",
}

PARTICLES = {
    "de",
    "del",
    "de la",
    "de le",
    "van",
    "von",
    "da",
    "dos",
    "du",
    "la",
    "le",
    "des",
    "st",
    "saint",
}


def normalize_whitespace(value: object) -> str:
    text = "" if value is None or pd.isna(value) else str(value)
    text = re.sub(r"[\u00a0\t\r]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def strip_accents_keep_case(value: str) -> str:
    return unidecode(value or "")


def slug_token(value: str) -> str:
    value = strip_accents_keep_case(normalize_whitespace(value)).lower()
    value = value.replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def ascii_email_token(value: str) -> str:
    value = strip_accents_keep_case(normalize_whitespace(value)).lower()
    value = value.replace("&", " and ")
    value = value.replace("’", "'").replace("`", "'")
    value = value.replace("'", "")
    value = re.sub(r"[^a-z0-9.\-_ ]+", "", value)
    value = re.sub(r"[\s\-]+", "", value)
    value = re.sub(r"\.+", ".", value)
    return value.strip(".-_ ")


def normalize_email_localpart(value: str) -> str:
    token = ascii_email_token(value)
    token = re.sub(r"[._-]{2,}", ".", token)
    return token.strip("._-")


def split_name_parts(name: str) -> list[str]:
    cleaned = normalize_whitespace(name).replace(",", " ")
    return [part for part in re.split(r"[\s/]+", cleaned) if part]


def smart_title(value: str) -> str:
    if not value:
        return ""
    text = normalize_whitespace(value)
    parts = re.split(r"([\s\-'])", text)
    return "".join(
        part.capitalize() if re.match(r"[A-Za-zÀ-ÿ]", part) else part
        for part in parts
    )


def normalize_company_name(value: str) -> str:
    text = normalize_whitespace(value)
    text = re.sub(r"\(.*?\)", "", text)
    text = text.replace("&", " and ")
    text = re.sub(r"\bprivate banking\b", "", text, flags=re.IGNORECASE)
    tokens = [tok for tok in slug_token(text).split() if tok not in CORPORATE_SUFFIXES]
    return " ".join(tokens).strip()


def company_display_name(value: str) -> str:
    text = normalize_whitespace(value)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" -,")


def is_valid_email(value: object) -> bool:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return False
    email = normalize_whitespace(value)
    pattern = r"^[A-Z0-9._%+\-']+@[A-Z0-9.-]+\.[A-Z]{2,}$"
    return re.match(pattern, email, flags=re.IGNORECASE) is not None


def extract_domain(value: object) -> str:
    text = normalize_whitespace(value).lower()
    if not text:
        return ""
    if "@" in text:
        text = text.split("@", 1)[1]

    text = re.sub(r"^https?://", "", text)
    text = re.sub(r"^mailto:", "", text)
    text = re.sub(r"^www\.", "", text)
    text = text.split("/", 1)[0]
    text = text.split("?", 1)[0]
    text = text.split("#", 1)[0]
    text = text.strip(" .;,")

    match = re.search(r"([a-z0-9.-]+\.[a-z]{2,})", text)
    return match.group(1) if match else ""


def safe_json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)