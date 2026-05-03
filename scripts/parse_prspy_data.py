#!/usr/bin/env python3

from __future__ import annotations

import csv
import json
import os
import sys
import tempfile
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


API_URL = "https://servers.realitymod.com/api/ServerInfo"
OUTPUT_FILE = Path("data/servers_last_seen.tsv")
TIMEZONE = os.environ.get("LAST_SEEN_TIMEZONE", "Europe/Warsaw")

FIELDNAMES = [
    "server_id",
    "server_name",
    "last_seen",
    "bf2_d_dl",
    "bf2_sponsortext",
    "bf2_communitylogo_url",
]


def clean_cell(value: object) -> str:
    """
    Keep the TSV file safe and readable.
    Server names and sponsor text can contain odd spacing, tabs, or newlines.
    """
    if value is None:
        return ""

    text = str(value)
    text = text.replace("\t", " ")
    text = text.replace("\r", " ")
    text = text.replace("\n", " ")
    return " ".join(text.split())


def today_iso() -> str:
    return datetime.now(ZoneInfo(TIMEZONE)).date().isoformat()


def fetch_server_info() -> dict:
    request = urllib.request.Request(
        API_URL,
        headers={
            "User-Agent": "pr-server-last-seen-tracker/1.0"
        },
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status != 200:
            raise RuntimeError(f"API returned HTTP {response.status}")

        raw = response.read().decode("utf-8")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("API response was not valid JSON") from exc

    if not isinstance(data, dict) or not isinstance(data.get("servers"), list):
        raise RuntimeError("API response did not contain a top-level 'servers' list")

    return data


def read_existing_records(path: Path) -> dict[str, dict[str, str]]:
    """
    Reads the existing TSV file.

    Old records are intentionally preserved forever unless you manually edit the file.
    """
    records: dict[str, dict[str, str]] = {}

    if not path.exists():
        return records

    with path.open("r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file, delimiter="\t")

        if reader.fieldnames != FIELDNAMES:
            raise RuntimeError(
                f"{path} has unexpected columns. "
                f"Expected: {FIELDNAMES}. Found: {reader.fieldnames}"
            )

        for row in reader:
            server_id = clean_cell(row.get("server_id"))

            if not server_id:
                continue

            records[server_id] = {
                "server_id": server_id,
                "server_name": clean_cell(row.get("server_name")),
                "last_seen": clean_cell(row.get("last_seen")),
                "bf2_d_dl": clean_cell(row.get("bf2_d_dl")),
                "bf2_sponsortext": clean_cell(row.get("bf2_sponsortext")),
                "bf2_communitylogo_url": clean_cell(row.get("bf2_communitylogo_url")),
            }

    return records


def update_records(
    existing_records: dict[str, dict[str, str]],
    api_data: dict,
    seen_date: str,
) -> dict[str, dict[str, str]]:
    records = dict(existing_records)

    for server in api_data["servers"]:
        if not isinstance(server, dict):
            continue

        server_id = clean_cell(server.get("serverId"))
        properties = server.get("properties") or {}

        if not server_id:
            continue

        if not isinstance(properties, dict):
            properties = {}

        server_name = clean_cell(properties.get("hostname")) or "(unknown hostname)"

        records[server_id] = {
            "server_id": server_id,
            "server_name": server_name,
            "last_seen": seen_date,
            "bf2_d_dl": clean_cell(properties.get("bf2_d_dl")),
            "bf2_sponsortext": clean_cell(properties.get("bf2_sponsortext")),
            "bf2_communitylogo_url": clean_cell(properties.get("bf2_communitylogo_url")),
        }

    return records


def write_records(path: Path, records: dict[str, dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    sorted_records = sorted(
        records.values(),
        key=lambda row: (
            row["last_seen"],
            row["server_name"].casefold(),
            row["server_id"],
        ),
    )

    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="",
        delete=False,
        dir=path.parent,
    ) as temp_file:
        writer = csv.DictWriter(
            temp_file,
            fieldnames=FIELDNAMES,
            delimiter="\t",
            lineterminator="\n",
        )

        writer.writeheader()
        writer.writerows(sorted_records)

        temp_path = Path(temp_file.name)

    temp_path.replace(path)


def main() -> int:
    seen_date = today_iso()

    print(f"Fetching server data from {API_URL}")
    print(f"Using last_seen date: {seen_date} ({TIMEZONE})")

    api_data = fetch_server_info()
    existing_records = read_existing_records(OUTPUT_FILE)
    updated_records = update_records(existing_records, api_data, seen_date)

    write_records(OUTPUT_FILE, updated_records)

    current_count = len(api_data["servers"])
    total_count = len(updated_records)

    print(f"Servers seen in this run: {current_count}")
    print(f"Total servers preserved in file: {total_count}")
    print(f"Wrote: {OUTPUT_FILE}")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
