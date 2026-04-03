#!/usr/bin/env python3
"""Compare completed HTV145FRF probe runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def is_active(entry: dict) -> bool:
    return (entry.get("parsed_d01") or {}).get("status_text") == "on"


def is_idle(entry: dict) -> bool:
    return (entry.get("parsed_d01") or {}).get("status_text") in {"off_idle", "off_recent"}


def summarize_rows(rows: list[dict], source: str) -> dict:
    pre_idle = None
    active = None
    post_idle = None

    for row in rows:
        if pre_idle is None and is_idle(row):
            pre_idle = row
        if active is None and is_active(row):
            active = row
        if active is not None and is_idle(row):
            post_idle = row

    def candidate_tail(entry: dict | None) -> str | None:
        if not entry:
            return None
        unknown_chunks = (entry.get("parsed_d01") or {}).get("unknown_chunks") or []
        return unknown_chunks[1]["hex"] if len(unknown_chunks) > 1 else None

    def duration(entry: dict | None) -> int | None:
        if not entry:
            return None
        return (entry.get("parsed_d01") or {}).get("duration_seconds")

    label = rows[0].get("label") if rows else None
    return {
        "source": source,
        "label": label,
        "polls": len(rows),
        "active_duration_seconds": duration(active),
        "pre_idle_tail": candidate_tail(pre_idle),
        "post_idle_tail": candidate_tail(post_idle),
        "tail_changed": candidate_tail(pre_idle) != candidate_tail(post_idle),
        "pre_idle_d01": (pre_idle or {}).get("status_non_null", {}).get("D01"),
        "active_d01": (active or {}).get("status_non_null", {}).get("D01"),
        "post_idle_d01": (post_idle or {}).get("status_non_null", {}).get("D01"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare one or more completed homgar_flow_probe JSONL files."
    )
    parser.add_argument("files", nargs="+", help="Probe JSONL files to compare.")
    args = parser.parse_args()

    summaries = [summarize_rows(load_rows(Path(file)), file) for file in args.files]

    print(json.dumps(summaries, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
