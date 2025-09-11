# NASA Image Downloader

Download images from the NASA Image & Video Library API into a local folder structure,
store each image’s metadata in a JSON file, and automatically resume where the
last run stopped.  The script is idempotent and runs safely as a nightly job or
as a manual command.

## Description

- Queries NASA’s public “Image and Video Library” API for all images between a
  start and an end date.
- Downloads each image to an `images/` directory.
- Saves the raw API response for each item to a companion
  `index‑<nasa_id>.json` file in `metadata/`.
- Keeps a `last_run.txt` file with the date of the most recent successful run;
  subsequent executions automatically pick up from that date.
- Skips files that already exist locally, so the script can be called multiple
  times without re‑downloading anything.
- Optional time‑budget: stops after a configurable maximum run time (2 h by
  default).
- Graceful error handling – printing failures to STDERR but continuing the
  entire run.

## Prerequisites

- Python 3.7 or later (the shebang is `/usr/bin/env python3`).
- Python packages:
  - `requests`
  - `tqdm` (optional; if missing the script falls back to a plain list)

    ```bash
    pip install requests tqdm
    ```

## Usage

```bash
python downloader.py [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--output BASE_DIR]
```

| Argument | Description |
|----------|-------------|
| `--start` | Start date (inclusive). If omitted, the script reads the date from
  `last_run.txt`; if that file does not exist it defaults to **three days ago**. |
| `--end`   | End date (inclusive). Defaults to **today**. |
| `--output` | Base directory where `images/` and `metadata/` folders will be
  created. Default is the current working directory. |

The script prints progress to the console and records the last successful
end date in `last_run.txt` (or in the chosen output directory).

## Examples

Below are valid calls that demonstrate typical use‑cases.

```bash
# 1. Default run – uses last_run.txt for the start date (or defaults to
#    3 days ago) and downloads everything up to today.
python downloader.py

# 2. Override date range – gather images created in the first week of July 2023.
python downloader.py --start 2023-07-01 --end 2023-07-07

# 3. Recent images only – start is yesterday, end is today.
python downloader.py --start $(date -u +%Y-%m-%d --date='-1 day') \
                     --end $(date -u +%Y-%m-%d)

# 4. Output everything under a specific directory tree.
python downloader.py --output /Users/me/Nasa

# 5. Custom state directory: images and metadata will live inside `/tmp/nasa_imgs/`.
python downloader.py --start 2023-06-20 --output /tmp/nasa_imgs

# 6. Combine date range and custom output base.
python downloader.py --start 2023-01-01 \
                     --end 2023-01-05 \
                     --output /Projects/nasa_imgs
```

## Output Structure

After a successful run:

```
images/
├── <high‑res‑image‑1>.jpg
├── <high‑res‑image‑2>.png
└── ...

metadata/
├── index-XYZ123.json
├── index-ABC456.json
└── ...

last_run.txt
```

- Each `index‑<nasa_id>.json` contains the full API response for the image.
- The `images` folder holds the highest‑resolution image that NASA offers
  for each item.

## Author

*Created by Jarian Cottingham.*

## License

This project is released under the MIT License. See `LICENSE` for details.
```
