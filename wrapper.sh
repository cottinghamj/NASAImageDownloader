#!/usr/bin/env bash
set -euo pipefail

# Change to the project root
cd "$(dirname "$0")"

# Activate virtualenv if you want – optional
# source .venv/bin/activate

python3 downloader.py
