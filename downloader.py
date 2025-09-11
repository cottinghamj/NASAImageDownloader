#!/usr/bin/env python3
"""
NASA image downloader.

The script queries NASA’s public “Image and Video Library” API for
all images between a start and an end date, downloads each image
to the *images* directory and writes a JSON file with the API
metadata next to it.  The JSON file is named
`index‑<nasa_id>.json`, where `<nasa_id>` is the unique ID returned
by the API.

Now the images are fetched via the asset endpoint so the highest‑resolution
image is downloaded. See the example at the top of this repository for
the asset‑based approach.

Designed to be run as a nightly daemon or cron job – it keeps a
local record of the last successful run date, so a subsequent
execution will automatically pick up new images and re‑write the
metadata for any images that may have been updated.

Features
--------
* idempotent – already‑downloaded images are skipped
* optional time‑budget (max 2 h per run)
* simple state file (`last_run.txt`) stores the end date of the last run
* separate `images/` and `metadata/` directories
* graceful error handling – failures are printed but do not stop the whole run

Usage
-----
```text
python downloader.py [--start YYYY-MM-DD] [--end YYYY-MM-DD]
```
If `--start` is omitted, the script reads the date from
`last_run.txt`; if that file does not exist it defaults to three
days ago. `--end` defaults to today.

Dependencies
-------------
* requests
"""

import argparse
import datetime
import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, List

import requests
try:
    from tqdm import tqdm
except ImportError:
    def tqdm(iterable, *args, **kwargs):
        return iterable

# ------------------------------------------------------------------
# Configuration
# ------------------------------------------------------------------
API_SEARCH_URL = "https://images-api.nasa.gov/search"
API_ASSET_URL = "https://images-api.nasa.gov/asset"

IMG_DIR = Path("images")
META_DIR = Path("metadata")
STATE_FILE = Path("last_run.txt")
MAX_RUN_TIME = 2 * 60 * 60  # 2 hours in seconds

# Ensure the output directories exist
IMG_DIR.mkdir(parents=True, exist_ok=True)
META_DIR.mkdir(parents=True, exist_ok=True)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="Download NASA images for a date range")
    parser.add_argument(
        "--start",
        type=str,
        help="Start date (YYYY-MM-DD). If omitted, uses date stored in last_run.txt.",
    )
    parser.add_argument(
        "--end",
        type=str,
        help="End date (YYYY-MM-DD). Defaults to today.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=".",
        help="Base directory where images/ and metadata/ folders will be created. Default is the current working directory.",
    )
    return parser.parse_args()


def load_state() -> datetime.datetime:
    """Return the date stored in STATE_FILE or default to 3 days ago."""
    if STATE_FILE.exists():
        try:
            date_str = STATE_FILE.read_text().strip()
            return datetime.datetime.strptime(date_str, "%Y-%m-%d")
        except Exception:
            pass
    # default to 3 days ago UTC
    return datetime.datetime.utcnow() - datetime.timedelta(days=3)


def save_state(end_date: datetime.datetime) -> None:
    """Persist the last successful run date."""
    STATE_FILE.write_text(end_date.strftime("%Y-%m-%d"))


def fetch_items(start: datetime.datetime, end: datetime.datetime) -> List[Dict]:
    """
    Pull all image items from the NASA API in the given date range.

    The API paginates results; we loop until a page returns no items.
    Returns the raw ``items`` list from the API.
    """
    items: List[Dict] = []
    page = 1
    while True:
        params = {
            "media_type": "image",
            "page": page,
            "year_start": start.year,
            "year_end": end.year,
        }
        try:
            r = requests.get(API_SEARCH_URL, params=params, timeout=20)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            print(f"API request failed: {e}", file=sys.stderr)
            break
        batch = data.get("collection", {}).get("items", [])
        if not batch or len(batch) == 0:
            break
        items.extend(batch)
        page += 1

    # Filter by the exact date range
    filtered = []
    for itm in items:
        d = itm.get("data", [{}])[0]
        iso = d.get("date_created") or d.get("date")
        if not iso:
            continue
        try:
            # Accept ISO format with or without timezone suffix
            dt = datetime.datetime.fromisoformat(iso.rstrip("Z"))
        except Exception:
            continue
        if start <= dt <= end:
            filtered.append(itm)
    return filtered


def download_file(url: str, dest: Path) -> bool:
    """Stream‑download the file at *url* to *dest* if it does not already exist."""
    if dest.exists():
        return False
    try:
        with requests.get(url, stream=True, timeout=30) as r:
            r.raise_for_status()
            with dest.open("wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        return True
    except Exception as e:
        raise RuntimeError(f"Download error for {url}: {e}") from e


def save_metadata(item: Dict, dest: Path) -> None:
    """Persist the full API item as formatted JSON."""
    with dest.open("w", encoding="utf-8") as f:
        json.dump(item, f, ensure_ascii=False, indent=2)


# ------------------------------------------------------------------
# Main logic
# ------------------------------------------------------------------
def main() -> None:
    args = parse_args()

    # Resolve output base directory and override global paths
    base_dir = Path(args.output).resolve()
    global IMG_DIR, META_DIR, STATE_FILE
    IMG_DIR = base_dir / "images"
    META_DIR = base_dir / "metadata"
    STATE_FILE = base_dir / "last_run.txt"
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    META_DIR.mkdir(parents=True, exist_ok=True)

    start_date = (
        datetime.datetime.strptime(args.start, "%Y-%m-%d")
        if args.start
        else load_state()
    )
    end_date = (
        datetime.datetime.strptime(args.end, "%Y-%m-%d")
        if args.end
        else datetime.datetime.utcnow()
    )

    if start_date > end_date:
        print("Error: start date must be <= end date", file=sys.stderr)
        sys.exit(1)

    print(f"Fetching NASA image metadata from {start_date.date()} to {end_date.date()}")
    items = fetch_items(start_date, end_date)
    print(f"Found {len(items)} items")

    start_time = time.time()

    for idx, item in enumerate(tqdm(items, desc="Downloading"), start=1):
        data = item.get("data", [{}])[0]
        nasa_id = data.get("nasa_id") or data.get("title", f"item_{idx}")

        # ------------------------------------------------------------------
        # Asset lookup: fetch high‑resolution image URL
        # ------------------------------------------------------------------
        asset_url = f"{API_ASSET_URL}/{nasa_id}"
        try:
            asset_resp = requests.get(asset_url, timeout=20)
            asset_resp.raise_for_status()
            assets = asset_resp.json()
            # Choose the first asset – usually the highest quality
            asset_href = assets.get("collection", {}).get("items", [{}])[0].get("href")
            if not asset_href:
                print(f"[{idx}] No asset link for item {nasa_id}", file=sys.stderr)
                continue
        except Exception as e:
            print(f"[{idx}] Failed asset lookup for {nasa_id}: {e}", file=sys.stderr)
            continue

        filename = Path(asset_href).name
        image_path = IMG_DIR / filename
        meta_path = META_DIR / f"index-{nasa_id}.json"

        try:
            downloaded = download_file(asset_href, image_path)
        except Exception as e:
            print(f"[{idx}] Failed download {asset_href}: {e}", file=sys.stderr)
            continue

        # Persist metadata
        try:
            save_metadata(item, meta_path)
        except Exception as e:
            print(f"[{idx}] Failed to write metadata for {nasa_id}: {e}", file=sys.stderr)

        elapsed = time.time() - start_time
        if downloaded:
            time.sleep(3)
        if elapsed > MAX_RUN_TIME:
            print("Maximum runtime exceeded, stopping early")
            break

    # Persist the last successful end date
    save_state(end_date)
    print("Download complete")


if __name__ == "__main__":
    main()
