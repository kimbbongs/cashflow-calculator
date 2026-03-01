#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

INPUT_JSON="${1:-examples/input.sample.json}"
OUTPUT_JSON="${2:-outputs/recommendation_from_json.json}"

python3 -m app.cli --input-json "$INPUT_JSON" --output-json "$OUTPUT_JSON"

