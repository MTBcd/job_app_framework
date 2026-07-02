from __future__ import annotations

from pathlib import Path

import pandas as pd

from .company import normalize_company_fields
from .config import Settings
from .contacts import normalize_contacts
from .data_loading import load_input_frames
from .drafts import build_drafts
from .email_inference import apply_email_inference
from .exports import reorder_columns, write_outputs
from .logging_utils import get_logger


def prepare_contacts(settings: Settings) -> pd.DataFrame:
    logger = get_logger(settings.logs_dir / "pipeline.log")
    logger.info("Loading input files.")
    raw = load_input_frames(settings.input_paths)
    logger.info("Loaded %s rows from %s files.", len(raw), len(settings.input_paths))

    contacts = normalize_contacts(raw)
    contacts = normalize_company_fields(contacts)
    contacts = apply_email_inference(contacts)
    contacts = build_drafts(
        contacts,
        Path(__file__).resolve().parent / "templates",
        sender_name=settings.smtp_from_name or settings.smtp_from_email,
        sender_email=settings.smtp_from_email,
    )
    contacts["send_status"] = ""
    contacts["send_error"] = ""
    contacts["sent_at_utc"] = ""

    write_outputs(contacts, settings.processed_dir / "contacts_normalized")
    logger.info("Wrote normalized contacts to %s.", settings.processed_dir)
    return reorder_columns(contacts)
