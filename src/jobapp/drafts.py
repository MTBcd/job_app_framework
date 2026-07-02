# =========================
# file: src/jobapp/drafts.py
# =========================
from __future__ import annotations

import re
from pathlib import Path
from string import Template

import pandas as pd

from .cleaning import normalize_whitespace
import os

sender_phone_env = os.getenv("SENDER_PHONE", "")


LLM_ARTIFACT_RE = re.compile(r":contentReference\[[^\]]+\]\{[^}]+\}")


def _load_template(template_path: Path, fallback: str) -> Template:
    if template_path.exists():
        return Template(template_path.read_text(encoding="utf-8"))
    return Template(fallback)


def _is_usable_name(value: str) -> bool:
    value = normalize_whitespace(value)
    return bool(value) and len(value) > 1 and not value.endswith(".")


def _default_salutation(first_name: str, last_name: str) -> str:
    first_name = normalize_whitespace(first_name)
    last_name = normalize_whitespace(last_name)

    if _is_usable_name(first_name) and _is_usable_name(last_name):
        return f"Dear {first_name} {last_name},"
    if _is_usable_name(first_name):
        return f"Dear {first_name},"
    if _is_usable_name(last_name):
        return f"Dear Mr./Ms. {last_name},"
    return "Dear Sir or Madam,"

import re

def _clean_company_for_email(company: str) -> str:
    company = normalize_whitespace(company)

    overrides = {
        # JPMorgan
        "jpmorgan chase and co": "JPMorgan",
        "jpmorgan chase and": "JPMorgan",
        "jp morgan chase and co": "JPMorgan",
        "jp morgan chase and": "JPMorgan",
        "jpmorgan chase": "JPMorgan",
        "jpmorgan chase co": "JPMorgan",
        "jpmorgan chase co.": "JPMorgan",
        "jpmorgan chase co ltd": "JPMorgan",
        "jpmorgan chase private bank": "JPMorgan Private Bank",
        "jp morgan": "JPMorgan",
        "j p morgan": "JPMorgan",

        # Bank of America
        "bank of america": "Bank of America",
        "bank of america merrill lynch": "Bank of America",
        "merrill lynch": "Bank of America",
        "bofa": "Bank of America",

        # Citi
        "citi": "Citi",
        "citibank": "Citi",
        "citibank n a": "Citi",
        "citibank na": "Citi",

        # Goldman / Morgan Stanley / UBS / Barclays / Jefferies / Credit Suisse / Nomura / MUFG
        "goldman sachs": "Goldman Sachs",
        "morgan stanley": "Morgan Stanley",
        "ubs": "UBS",
        "barclays": "Barclays",
        "jefferies": "Jefferies",
        "credit suisse": "Credit Suisse",
        "nomura": "Nomura",
        "mufg": "MUFG",

        # Canadian bank platforms
        "rbc": "RBC",
        "rbc capital markets": "RBC Capital Markets",
        "rbc global asset management": "RBC Global Asset Management",
        "rbc markets": "RBC Capital Markets",

        "td": "TD",
        "td securities": "TD Securities",
        "td asset management": "TD Asset Management",

        "bmo": "BMO",
        "bank of montreal": "BMO",
        "bmo financial": "BMO",
        "bmo financial group": "BMO",
        "bmo capital markets": "BMO Capital Markets",
        "bmo global asset management": "BMO Global Asset Management",

        "cibc": "CIBC",
        "cibc capital markets": "CIBC Capital Markets",
        "cibc asset management": "CIBC Asset Management",
        "cibc global asset management": "CIBC Global Asset Management",

        "scotiabank": "Scotiabank",
        "national bank of canada": "National Bank of Canada",
        "desjardins": "Desjardins",
        "desiardins": "Desjardins",

        # Asset managers / pensions / buy side
        "blackrock": "BlackRock",
        "neuberger berman": "Neuberger Berman",
        "balyasny asset management": "Balyasny Asset Management",
        "cubist systematic strategies": "Cubist Systematic Strategies",
        "hillsdale": "Hillsdale",
        "hillsdale investment management": "Hillsdale Investment Management",
        "mawer investment management": "Mawer Investment Management",
        "fidelity investments": "Fidelity Investments",
        "invesco": "Invesco",
        "cpp investments": "CPP Investments",
        "cpp": "CPP Investments",
        "omers": "OMERS",
        "omers capital markets": "OMERS Capital Markets",
        "ontario teachers pension plan": "Ontario Teachers’ Pension Plan",
        "ontaric teachers": "Ontario Teachers’ Pension Plan",
        "aimco": "AIMCo",
        "alberta investment management": "AIMCo",
        "alberta investment management corporation": "AIMCo",
        "brookfield asset management": "Brookfield Asset Management",
        "ehp funds": "EHP Funds",
        "picton mahoney": "Picton Mahoney",
        "picton mahoney asset management": "Picton Mahoney Asset Management",
        "black swan": "Black Swan",
        "canada guaranty": "Canada Guaranty",
        "ci global asset management": "CI Global Asset Management",
        "equitable": "Equitable",
        "mackenzie investments": "Mackenzie Investments",
        "manulife": "Manulife",
        "manulife financial": "Manulife",
        "manulife mmf": "Manulife",
        "sun life global investments": "Sun Life Global Investments",
        "gwn capital management": "GWN Capital Management",
        "genus capital": "Genus Capital",
        "nei investments": "NEI Investments",
        "polar asset management partners": "Polar Asset Management Partners",
        "agf investments": "AGF Investments",
        "abu dhabi investment authority": "Abu Dhabi Investment Authority",
        "absa": "Absa",
        "arrow capital management": "Arrow Capital Management",
        "beutel goodman": "Beutel Goodman",
        "connor clark lunn": "Connor, Clark & Lunn",
        "connor clark and lunn": "Connor, Clark & Lunn",
        "connor clark lunn investment management": "Connor, Clark & Lunn Investment Management",
        "connor clark and lunn investment management": "Connor, Clark & Lunn Investment Management",
        "cormark": "Cormark",
        "cortland credit": "Cortland Credit Group",
        "cortland credit group": "Cortland Credit Group",
        "cortland credit insg": "Cortland Credit Group",
        "laketon investment management": "Laketon Investment Management",
        "goldenwise capital management": "Goldenwise Capital Management",
        "hartree partners": "Hartree Partners",
        "scivest capital management": "SciVest Capital Management",
        "wavefront global asset management": "WaveFront Global Asset Management",
        "validus risk management": "Validus Risk Management",
        "ventum financial": "Ventum Financial",
        "vanguard": "Vanguard",

        # Exchanges / infra / payments / public finance
        "tmx": "TMX",
        "tmx group": "TMX Group",
        "payments canada": "Payments Canada",
        "aequitas neo exchange": "Aequitas NEO Exchange",

        # Other financial / data / consulting firms seen in extract
        "dv trading": "DV Trading",
        "fincad": "FINCAD",
        "risklab": "RiskLab",
        "deloitte": "Deloitte",
        "deloitte canada": "Deloitte",
        "ey": "EY",
        "fis": "FIS",
        "crisil": "CRISIL",
        "s p global": "S&P Global",
        "societe generale": "Société Générale",
        "natixis corporate investment banking": "Natixis Corporate & Investment Banking",
        "thomson reuters": "Thomson Reuters",
        "solactive": "Solactive",
        "coinbase": "Coinbase",
        "murex": "Murex",
        "numerix": "Numerix",
        "numerixs technologies": "Numerix",
        "huatai securities": "Huatai Securities",
        "nedbank": "Nedbank",
        "glg": "GLG",
        "global x canada": "Global X Canada",
        "ia global asset management": "iA Global Asset Management",
        "first west credit union": "First West Credit Union",
        "cambridge global payments": "Cambridge Global Payments",

        # Clean obvious typos / malformed names from extract
        "jpmorgan chase co": "JPMorgan",
        "jpmorgan chase co.": "JPMorgan",
        "jpmorgan chase co ltd": "JPMorgan",
        "millenniun": "Millennium",
        "sustainalytic": "Sustainalytics",
        "ihs marki": "IHS Markit",
        "alg tradinc": "AlG Trading",
        "function anaiytics": "Function Group Analytics",
        "su life": "Sun Life",
        "ontario public service": "Ontario Public Service",
        "office of the superintendent": "Office of the Superintendent",
        "capital market canada": "Capital Market Canada",
        "capital markets": "Capital Markets",
        "cmb wealth management": "CMB Wealth Management",
        "china international capital": "China International Capital Corp",
        "corporate knights": "Corporate Knights",
        "jacob securities": "Jacob Securities",
        "javelin analytics": "Javelin Analytics",
        "kpmg canada": "KPMG Canada",
        "optimize financial": "Optimize Financial Group",
        "pansaf international ing": "PANSAF INTERNATIONAL ING",
        "reinsurance": "Reinsurance Group",
        "wealth engine": "Wealth Engine",
        "wealth partners": "Wealth Partners",
        "banyan software": "Banyan Software",
        "braves technologies": "Braves Technologies",
        "humber polytechnic": "Humber Polytechnic",
        "jwf capital": "JWF Capital",
        "optrust": "OPTrust",
        "outlier": "Outlier",
        "pmpr biomedical": "PMPR Biomedical",
        "rnk technologies": "RNK Technologies",
        "shepherd ventures": "Shepherd Ventures",
        "fintelics": "Fintelics",

        # Keep clean standard brands exactly as they should appear
        "millennium": "Millennium",
        "raymond james": "Raymond James",
        "wells fargo": "Wells Fargo",
        "state street": "State Street",
        "agam capital": "Agam Capital",
        "subtrate capital": "Substrate Capital",
        "substrate capital": "Substrate Capital",
        "active digital": "Active Digital",
        "mapleridge": "Mapleridge",
        "quan zone": "Quan Zone",
        "talon training ll": "Talon Training Group",
        "asset pro": "Asset Pro",
        "bayport financial services": "Bayport Financial Services",
        "bcs": "BCS",
        "central": "Central",
        "county cork": "County Cork",
        "emi van essen": "Emi van Essen",
        "gammax": "GammaX",
        "horizon insights": "Horizon Insights",
        "magarh capital": "Magarh Capital",
        "montreal business development": "Montreal Business Development",
        "bel": "Bel",
        "bmc": "BMC",
        "eidosearch": "EIDOSearch",
        "eq consulting": "EQ Consulting",
        "fintegral consulting": "Fintegral Consulting",
        "ggy": "GGY",
        "houghton mifflin harcourt": "Houghton Mifflin Harcourt",
        "ontario": "Ontario",
        "canada revenue agency": "Canada Revenue Agency",
        "cypress investments": "Cypress Investments",
        "ti": "TI",
    }

    key = company.lower()
    key = key.replace("&", " and ")
    key = re.sub(r"[^a-z0-9]+", " ", key)
    key = re.sub(r"\s+", " ", key).strip()

    return overrides.get(key, company)

def _clean_draft_text(text: str) -> str:
    text = LLM_ARTIFACT_RE.sub("", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"\s+,", ",", text)
    text = re.sub(r"\s+\.", ".", text)
    text = text.replace(" ,", ",")
    text = text.replace(" .", ".")
    return text.strip()


def build_drafts(
    df: pd.DataFrame,
    templates_dir: Path,
    sender_name: str = "",
    sender_email: str = "",
) -> pd.DataFrame:
    df = df.copy()

    subject_template = _load_template(
        templates_dir / "email_subject.txt",
        "Spontaneous Application – Quantitative Finance Profile",
    )

    body_template = _load_template(
        templates_dir / "email_body_en.txt",
        """${salutation}

    I am reaching out to express my interest in quantitative research, model validation, or risk-related opportunities at ${company}.

    I am a Toronto-based quantitative analyst with hands-on experience in model validation, asset allocation, and quantitative research across asset management and hedge fund environments. My work has included developing stress-testing frameworks, volatility models, and portfolio analytics tools using Python and R.

    More specifically, I have worked on:
    - implementing a Heston-Nandi GARCH model for OTC pricing validation,
    - building a Merton-based credit risk stress-testing framework,
    - developing macro-regime detection and allocation models,
    - constructing portfolio analytics and performance attribution tools.

    These experiences have allowed me to combine quantitative modelling, financial intuition, and practical implementation in real-world investment contexts.

    I am particularly interested in contributing to teams where quantitative methods directly support investment decisions, risk management, or model governance.

    I would greatly appreciate the opportunity to connect and discuss how my background could be relevant to your team at ${company}. Please find my resume attached for your consideration.

    Thank you very much for your time and consideration.

    Kind regards,  
    ${sender_name}  
    ${sender_email}
    """,
    )

    subjects: list[str] = []
    bodies: list[str] = []
    salutations: list[str] = []

    clean_sender_name = normalize_whitespace(sender_name) or "Mael Boccardi"
    clean_sender_email = normalize_whitespace(sender_email)

    for _, row in df.iterrows():
        first_name = normalize_whitespace(row.get("first_name", ""))
        last_name = normalize_whitespace(row.get("last_name", ""))
        company = _clean_company_for_email(row.get("company_name", "")) or "your organization"
        salutation = _default_salutation(first_name, last_name)

        mapping = {
            "salutation": salutation,
            "first_name": first_name,
            "last_name": last_name,
            "company": company,
            "company_name": company,
            "sender_name": clean_sender_name,
            "sender_email": clean_sender_email,
            "sender_phone": sender_phone_env,
        }

        subject = subject_template.safe_substitute(mapping)
        body = body_template.safe_substitute(mapping)

        subjects.append(_clean_draft_text(subject))
        bodies.append(_clean_draft_text(body))
        salutations.append(salutation)

    df["salutation"] = salutations
    df["draft_subject"] = subjects
    df["draft_body"] = bodies
    return df