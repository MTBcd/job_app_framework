from __future__ import annotations

import argparse
import sys

import pandas as pd

from .bounce_parser import sync_bounce_feedback
from .config import get_settings
from .exports import write_outputs
from .pipeline import prepare_contacts
from .reply_parser import sync_reply_feedback
from .sender import build_retry_queue, send_dataframe


def run_prepare() -> int:
    settings = get_settings()
    df = prepare_contacts(settings)
    write_outputs(df, settings.processed_dir / "drafts_ready")
    print(f"Prepared {len(df)} contacts.")
    return 0


def run_send() -> int:
    settings = get_settings()
    df = prepare_contacts(settings)
    sent_df = send_dataframe(df, settings)
    write_outputs(sent_df, settings.processed_dir / "send_results")
    print(sent_df["send_status"].value_counts(dropna=False).to_string())
    return 0


def run_sync_replies() -> int:
    settings = get_settings()
    updated = sync_reply_feedback(
        history_path=settings.send_history_path,
        learning_path=settings.learning_feedback_path,
        imap_host=settings.imap_host,
        imap_username=settings.imap_username,
        imap_password=settings.imap_password,
    )
    print(f"Replies synced: {len(updated)}")
    return 0


def run_sync_bounces() -> int:
    settings = get_settings()
    updated = sync_bounce_feedback(
        history_path=settings.send_history_path,
        learning_path=settings.learning_feedback_path,
        imap_host=settings.imap_host,
        imap_username=settings.imap_username,
        imap_password=settings.imap_password,
    )
    print(f"Bounces synced: {len(updated)}")
    return 0


def run_build_retry_queue() -> int:
    settings = get_settings()
    df = prepare_contacts(settings)
    retry_df = build_retry_queue(df, settings)

    output_stem = settings.processed_dir / "retry_queue"
    if retry_df.empty:
        retry_df = pd.DataFrame(columns=df.columns)
    write_outputs(retry_df, output_stem)

    print(f"Retry queue rows: {len(retry_df)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local job application workflow")
    parser.add_argument(
        "command",
        choices=[
            "prepare",
            "send",
            "sync-replies",
            "sync-bounces",
            "build-retry-queue",
        ],
    )
    args = parser.parse_args(argv)

    if args.command == "prepare":
        return run_prepare()
    if args.command == "send":
        return run_send()
    if args.command == "sync-replies":
        return run_sync_replies()
    if args.command == "sync-bounces":
        return run_sync_bounces()
    if args.command == "build-retry-queue":
        return run_build_retry_queue()
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))