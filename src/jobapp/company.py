# =========================
# file: src/jobapp/company.py
# =========================
from __future__ import annotations

import os
import re

import pandas as pd

from .cleaning import company_display_name, extract_domain, normalize_company_name
from .learning import LearningStore
from .pattern_overrides import get_company_pattern


DOMAIN_OVERRIDES = {
    "bank of america": "bofa.com",
    "bank of america merrill lynch": "bofa.com",
    "merrill lynch": "bofa.com",
    "bank of montreal": "bmo.com",
    "bmo capital markets": "bmo.com",
    "bnp paribas": "bnpparibas.com",
    "bnp paribas cib": "bnpparibas.com",
    "credit agricole": "credit-agricole.com",
    "credit agricole cib": "ca-cib.com",
    "goldman sachs": "gs.com",
    "jpmorgan": "jpmorgan.com",
    "jp morgan": "jpmorgan.com",
    "jpmorgan chase": "jpmorgan.com",
    "jpmorgan chase and": "jpmorgan.com",
    "jpmorgan chase co": "jpmorgan.com",
    "jpmorgan chase and co": "jpmorgan.com",
    "j p morgan": "jpmorgan.com",
    "jp morgan chase and": "jpmorgan.com",
    "jp morgan chase co": "jpmorgan.com",
    "jp morgan chase and co": "jpmorgan.com",
    "morgan stanley": "morganstanley.com",
    "natixis corporate and investment": "natixis.com",
    "ofi invest assetmanagement": "ofi-invest-am.com",
    "oddo bhf": "oddo-bhf.com",
    "rothschild and co": "rothschildandco.com",
    "societe generale": "socgen.com",
    "societe generale corporate": "socgen.com",
    "socgen": "socgen.com",
    "sg cib": "socgen.com",
    "standard chartered bank": "sc.com",
    "state street": "statestreet.com",
    "td securities": "tdsecurities.com",
    "td bank": "td.com",
    "ubs": "ubs.com",
    "bofa": "bofa.com",
    "citi": "citi.com",
    "citigroup": "citi.com",
    "citibank": "citi.com",
    "jefferies": "jefferies.com",
    "barclays": "barclays.com",
    "credit suisse": "credit-suisse.com",
    "deutsche bank": "db.com",
    "hsbc": "hsbc.com",
    "nomura": "nomura.com",
    "scotiabank": "scotiabank.com",
    "bank of nova scotia": "scotiabank.com",
    "rbc": "rbc.com",
    "royal bank of canada": "rbc.com",
    "rbc capital markets": "rbccm.com",
    "rbc global asset management": "rbc.com",
    "rbc gam": "rbc.com",
    "bmo": "bmo.com",
    "sun life": "sunlife.com",
    "manulife": "manulife.com",
    "blackrock": "blackrock.com",
    "blackstone": "blackstone.com",
    "amundi": "amundi.com",
    "pimco": "pimco.com",
    "schroders": "schroders.com",
    "wellington management": "wellington.com",
    "moodys": "moodys.com",
    "morningstar": "morningstar.com",
    "sp global": "spglobal.com",
    "s p global": "spglobal.com",
    "tradeweb": "tradeweb.com",
    "fidelity investments": "fmr.com",
    "capital group": "capgroup.com",
    "t rowe price": "troweprice.com",
    "trowe price": "troweprice.com",
    "1832 asset management": "scotiagam.com",
    "1832 asset management lp": "scotiagam.com",
    "agf": "agf.com",
    "agf investments": "agf.com",
    "coinbase": "coinbase.com",
    "crisil": "crisil.com",
    "crisil limited": "crisil.com",
    "deloitte": "deloitte.com",
    "deloitte canada": "deloitte.ca",
    "ey": "ey.com",
    "fincad": "fincad.com",
    "global x canada": "globalx.ca",
    "kpmg canada": "kpmg.ca",
    "mawer": "mawer.com",
    "mawer investment management": "mawer.com",
    "murex": "murex.com",
    "omers": "omers.com",
    "omers capital markets": "omers.com",
    "optrust": "optrust.com",
    "picton mahoney": "pictonmahoney.com",
    "picton mahoney assetmanagement": "pictonmahoney.com",
    "picton mahoney asset management": "pictonmahoney.com",
    "reinsurance group": "rgare.com",
    "solactive": "solactive.com",
    "thomson reuters": "thomsonreuters.com",
    "tmx group": "tmx.com",
    "validus": "validusrm.com",
    "validus risk management": "validusrm.com",
    "wealthengine": "wealthengine.com",
    "aequitas neo exchange": "cboe.com",
    "neo exchange": "cboe.com",
    "cboe canada": "cboe.com",
    "arrow capital management": "arrow-capital.com",
    "arrow capital management inc": "arrow-capital.com",
    "bayport financial services": "bayportfinance.com",
    "black swan dexteritas": "blackswandexteritas.com",
    "canada guaranty": "canadaguaranty.ca",
    "ci global asset management": "ci.com",
    "cmb wealth management": "td.com",
    "connor clark and lunn": "cclgroup.com",
    "connor clark lunn": "cclgroup.com",
    "connor clark and lunn financial group": "cclgroup.com",
    "connor clark and lunn investment management": "cclgroup.com",
    "cormark": "cormark.com",
    "cormark securities": "cormark.com",
    "cortland credit group": "cortlandcredit.ca",
    "cpp investments": "cppib.com",
    "cpp": "cppib.com",
    "cubist systematic strategies": "systematic-strategies.com",
    "dv trading": "dvtrading.ca",
    "dv trading llc": "dvtrading.ca",
    "ehp funds": "ehpfunds.com",
    "first west credit union": "firstwestcu.ca",
    "genus capital": "genuscap.com",
    "glc asset management group": "glc-amgroup.com",
    "goldenwise capital management": "gwisecapital.com",
    "gwn capital management": "gwncapital.com",
    "gwn capital management ltd": "gwncapital.com",
    "hartree partners": "hartreepartners.com",
    "hillsdale": "hillsdaleinv.com",
    "hillsdale investment management": "hillsdaleinv.com",
    "hillsdale investment management inc": "hillsdaleinv.com",
    "huatai securities": "htsc.com",
    "ia global asset management": "ia.ca",
    "laketon investment management": "laketon.com",
    "nedbank": "nedbank.co.za",
    "nei investments": "neiinvestments.com",
    "ontario teachers pension plan": "otpp.com",
    "ontario teachers": "otpp.com",
    "payments canada": "payments.ca",
    "polar asset management partners": "polaramp.com",
    "scivest capital management": "scivest.com",
    "scivest capital management inc": "scivest.com",
    "university pension plan": "upp.ca",
    "ventum financial": "ventumfinancial.com",
    "wavefront global asset management": "wavefrontglobal.com",
}

BAD_HEURISTIC_DOMAIN_FIXES = {
    "jpmorganchaseand.com": "jpmorgan.com",
    "nationalofcanada.com": "nbc.ca",
    "ontarioteacherspensionplan.com": "otpp.com",
    "brookfieldasset.com": "brookfield.com",
    "pictonmahoneyasset.com": "pictonmahoney.com",
    "cibcasset.com": "cibc.com",
    "rbcasset.com": "rbc.com",
    "tdasset.com": "td.com",
    "bmoasset.com": "bmo.com",
    "deloittecanada.com": "deloitte.ca",
    "paymentscanada.com": "payments.ca",
    "abudhabiauthority.com": "adia.ae",
    "desiardins.com": "desjardins.com",
    "sulife.com": "sunlife.com",
    "sustainalytic.com": "sustainalytics.com",
}

BUSINESS_UNIT_TOKENS = {
    "assetmanagement",
    "management",
    "capital",
    "partners",
    "bank",
    "banking",
    "financial",
    "financials",
    "securities",
    "investments",
    "investment",
    "advisors",
    "adviser",
    "advisers",
    "wealth",
    "markets",
    "global",
    "international",
    "corporate",
    "private",
    "group",
    "holdings",
    "cib",
    "cm",
}


def _normalize_company_key(value: str) -> str:
    return normalize_company_name(value).replace(" and ", " ").strip()


def _candidate_company_keys(value: str) -> list[str]:
    base = _normalize_company_key(value)
    if not base:
        return []

    tokens = base.split()
    keys = [base]

    reduced_tokens = [token for token in tokens if token not in BUSINESS_UNIT_TOKENS]
    reduced = " ".join(reduced_tokens).strip()
    if reduced and reduced not in keys:
        keys.append(reduced)

    joined = re.sub(r"[^a-z0-9]+", "", base)
    if joined and joined not in keys:
        keys.append(joined)

    joined_reduced = re.sub(r"[^a-z0-9]+", "", reduced)
    if joined_reduced and joined_reduced not in keys:
        keys.append(joined_reduced)

    return keys


def _fix_bad_domain(domain: str) -> str:
    domain = extract_domain(domain)
    return BAD_HEURISTIC_DOMAIN_FIXES.get(domain, domain)


def infer_company_domain(
    company_name: str,
    existing_domain: str = "",
    existing_email: str = "",
    learning_store: LearningStore | None = None,
) -> tuple[str, str]:
    direct_domain = _fix_bad_domain(extract_domain(existing_domain) or extract_domain(existing_email))
    if direct_domain:
        return direct_domain, "from_existing_domain_or_email"

    candidate_keys = _candidate_company_keys(company_name)
    normalized_company = candidate_keys[0] if candidate_keys else ""

    verified_pattern = get_company_pattern(company_name, normalized_company)
    if verified_pattern and verified_pattern.get("domain"):
        return _fix_bad_domain(verified_pattern["domain"]), "from_verified_pattern_file"

    for key in candidate_keys:
        if key in DOMAIN_OVERRIDES:
            return _fix_bad_domain(DOMAIN_OVERRIDES[key]), "from_company_override"

    if learning_store:
        for key in candidate_keys:
            learned = learning_store.best_domain_for_company(key)
            if learned:
                return _fix_bad_domain(learned), "from_learning_feedback"

    if not candidate_keys:
        return "", "missing_company"

    reduced = candidate_keys[1] if len(candidate_keys) > 1 else candidate_keys[0]
    joined = re.sub(r"[^a-z0-9]+", "", reduced)
    if not joined:
        return "", "missing_joined_company"

    return _fix_bad_domain(f"{joined}.com"), "heuristic_company_to_com"


def normalize_company_fields(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    learning_store = LearningStore(os.getenv("LEARNING_FEEDBACK_PATH", "logs/learning_feedback.csv"))

    df["company_name"] = df["company_name"].map(company_display_name)
    df["company_normalized"] = df["company_name"].map(_normalize_company_key)

    inferred = df.apply(
        lambda row: infer_company_domain(
            row.get("company_name", ""),
            row.get("domain", ""),
            row.get("email", ""),
            learning_store=learning_store,
        ),
        axis=1,
    )
    inferred_df = inferred.apply(pd.Series)
    inferred_df.columns = ["company_domain", "domain_source"]

    df["company_domain"] = inferred_df["company_domain"].map(extract_domain)
    df["domain_source"] = inferred_df["domain_source"]
    return df