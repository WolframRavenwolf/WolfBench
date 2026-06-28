#!/usr/bin/env bash
# wolfbench-export-release.sh
# Build complete WolfBench data snapshots for GitHub Release assets.
#
# The generated archive is redacted and contains lightweight run data
# (config.json + result.json + sanitized Hermes usage), matching the public-data
# shape previously kept in the git tree. Full traces remain available through
# Weave.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RUNS_DIR="${SCRIPT_DIR}/wolfbench-runs"
OUT_ROOT="${SCRIPT_DIR}/release-assets"
SUFFIX=""
DRY_RUN=0
KEEP_STAGE=0

usage() {
    cat <<'EOF'
Usage: ./wolfbench-export-release.sh [options]

Build a complete WolfBench data snapshot for GitHub Release assets.

Options:
  --suffix YYYY-MM-DD_HHMMSS  Use a specific WolfBench snapshot suffix.
                              Defaults to the newest wolfbench_results_*.json.
  --out DIR                   Output root. Default: ./release-assets
  --dry-run                   Print the planned export without creating assets.
  --keep-stage                Keep the temporary staged run-data directory.
  -h, --help                  Show this help.

Output:
  release-assets/data-YYYY-MM-DD_HHMMSS/
    wolfbench_results_YYYY-MM-DD_HHMMSS.json
    wolfbench-overrides.json
    wolfbench_YYYY-MM-DD_HHMMSS.html
    wolfbench-runs-full-YYYY-MM-DD_HHMMSS.tar.zst
    manifest-YYYY-MM-DD_HHMMSS.json
    SHA256SUMS
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --suffix)
            SUFFIX="${2:?ERROR: --suffix requires a value}"
            shift
            ;;
        --out)
            OUT_ROOT="${2:?ERROR: --out requires a value}"
            shift
            ;;
        --dry-run)
            DRY_RUN=1
            ;;
        --keep-stage)
            KEEP_STAGE=1
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "ERROR: Unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
    shift
done

if [[ -z "$SUFFIX" ]]; then
    latest_results=$(find "$SCRIPT_DIR" -maxdepth 1 -type f \
        -name 'wolfbench_results_[0-9][0-9][0-9][0-9]-*.json' \
        ! -name '*excluded*' | sort | tail -n 1)
    if [[ -z "$latest_results" ]]; then
        echo "ERROR: No wolfbench_results_*.json snapshot found in ${SCRIPT_DIR}" >&2
        exit 1
    fi
    SUFFIX="$(basename "$latest_results" .json)"
    SUFFIX="${SUFFIX#wolfbench_results_}"
fi

RESULTS="${SCRIPT_DIR}/wolfbench_results_${SUFFIX}.json"
OVERRIDES="${SCRIPT_DIR}/wolfbench-overrides.json"
HTML="${SCRIPT_DIR}/wolfbench_${SUFFIX}.html"
RELEASE_DIR="${OUT_ROOT}/data-${SUFFIX}"
ARCHIVE="${RELEASE_DIR}/wolfbench-runs-full-${SUFFIX}.tar.zst"
MANIFEST="${RELEASE_DIR}/manifest-${SUFFIX}.json"
CHECKSUMS="${RELEASE_DIR}/SHA256SUMS"

require_file() {
    local path="$1"
    local label="$2"
    if [[ ! -f "$path" ]]; then
        echo "ERROR: Missing ${label}: ${path}" >&2
        exit 1
    fi
}

require_file "$RESULTS" "results snapshot"
require_file "$OVERRIDES" "display overrides"
require_file "$HTML" "interactive HTML"
if [[ ! -d "$RUNS_DIR" ]]; then
    echo "ERROR: Missing run-data directory: ${RUNS_DIR}" >&2
    exit 1
fi

if [[ "$DRY_RUN" -ne 1 ]]; then
    if ! command -v zstd >/dev/null 2>&1; then
        echo "ERROR: zstd is required to build .tar.zst release assets." >&2
        exit 1
    fi
    if ! command -v python3 >/dev/null 2>&1; then
        echo "ERROR: python3 is required to write the manifest." >&2
        exit 1
    fi
fi

echo "WolfBench release export"
echo "  suffix:       ${SUFFIX}"
echo "  source runs:  ${RUNS_DIR}"
echo "  release dir:  ${RELEASE_DIR}"
echo "  archive:      ${ARCHIVE}"

if [[ "$DRY_RUN" -eq 1 ]]; then
    echo ""
    echo "DRY RUN: would stage config.json + result.json + sanitized Hermes usage files, redact secrets, archive them, and write manifest/checksums."
    echo "DRY RUN: skipping full run-data file counts to keep this check fast."
    exit 0
fi

mkdir -p "$RELEASE_DIR"
rm -f "$RELEASE_DIR"/wolfbench_results_excluded_*.json
STAGE="$(mktemp -d "${TMPDIR:-/tmp}/wolfbench-release.XXXXXX")"
cleanup() {
    if [[ "$KEEP_STAGE" -eq 1 ]]; then
        echo "Kept staging directory: ${STAGE}"
    else
        rm -rf "$STAGE"
    fi
}
trap cleanup EXIT

STAGED_RUNS="${STAGE}/wolfbench-runs"

echo ""
echo "=== Copying release metadata ==="
cp -p "$RESULTS" "$RELEASE_DIR/"
cp -p "$OVERRIDES" "$RELEASE_DIR/"
cp -p "$HTML" "$RELEASE_DIR/"

echo ""
echo "=== Staging lightweight run data ==="
FILE_LIST="${STAGE}/release-files.txt"
(
    cd "$SCRIPT_DIR"
    {
        find wolfbench-runs -maxdepth 4 -type f \( -name 'config.json' -o -name 'result.json' \)
        shopt -s nullglob
        printf '%s\n' wolfbench-runs/*/*/*/agent/hermes-session.jsonl
    } | sort -u > "$FILE_LIST"
)
CONFIG_COUNT=$(grep -c '/config.json$' "$FILE_LIST" || true)
RESULT_COUNT=$(grep -c '/result.json$' "$FILE_LIST" || true)
HERMES_SESSION_COUNT=$(grep -c '/agent/hermes-session.jsonl$' "$FILE_LIST" || true)
if [[ "$CONFIG_COUNT" -eq 0 || "$RESULT_COUNT" -eq 0 ]]; then
    echo "ERROR: Expected config.json and result.json files in ${RUNS_DIR}; got config=${CONFIG_COUNT}, result=${RESULT_COUNT}" >&2
    exit 1
fi
mkdir -p "$STAGED_RUNS"
(
    cd "$SCRIPT_DIR"
    tar -cf - -T "$FILE_LIST" | (cd "$STAGE" && tar -xf -)
)
echo "Staged ${CONFIG_COUNT} config.json + ${RESULT_COUNT} result.json + ${HERMES_SESSION_COUNT} Hermes session usage files."

echo ""
echo "=== Sanitizing Hermes session usage ==="
python3 - "$STAGED_RUNS" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
allowed = (
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "actual_cost_usd",
    "estimated_cost_usd",
)
sanitized = 0
skipped = 0

for path in root.rglob("hermes-session.jsonl"):
    try:
        first_line = path.read_text(errors="replace").splitlines()[0]
        session = json.loads(first_line)
    except (IndexError, json.JSONDecodeError, OSError):
        skipped += 1
        path.write_text("{}\n")
        continue

    usage = {key: session.get(key) for key in allowed}
    path.write_text(json.dumps(usage, sort_keys=True, separators=(",", ":")) + "\n")
    sanitized += 1

print(f"Sanitized {sanitized} Hermes session usage files.")
if skipped:
    print(f"Skipped {skipped} unreadable Hermes session files; wrote empty placeholders.")
PY

echo ""
echo "=== Redacting secrets in staged data ==="
SECRET_LIST="$(mktemp "${TMPDIR:-/tmp}/wolfbench-release-secrets.XXXXXX")"
grep -rlE '"(sk-|wandb_v1_|key-)[a-zA-Z0-9_-]{20,}"' \
    "$STAGED_RUNS" --include='*.json' --include='*.jsonl' > "$SECRET_LIST" 2>/dev/null || true
SECRET_FILES=$(wc -l < "$SECRET_LIST" | tr -d ' ')
if [[ "$SECRET_FILES" -gt 0 ]]; then
    xargs perl -0pi -e 's/"(sk-|wandb_v1_|key-)[a-zA-Z0-9_-]{20,}"/"REDACTED"/g' < "$SECRET_LIST"
    echo "Redacted secrets in ${SECRET_FILES} files."
else
    echo "No secret-shaped values found."
fi
rm -f "$SECRET_LIST"

echo ""
echo "=== Building archive ==="
rm -f "$ARCHIVE"
(
    cd "$STAGE"
    COPYFILE_DISABLE=1 tar -cf - wolfbench-runs | zstd -T0 -19 -o "$ARCHIVE"
)

echo ""
echo "=== Writing manifest ==="
python3 - "$MANIFEST" "$SUFFIX" "$SCRIPT_DIR" "$RELEASE_DIR" "$ARCHIVE" "$RESULTS" "$OVERRIDES" "$HTML" "$CONFIG_COUNT" "$RESULT_COUNT" "$HERMES_SESSION_COUNT" "$SECRET_FILES" <<'PY'
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

manifest_path, suffix, source_dir, release_dir, archive, results, overrides, html, config_count, result_count, hermes_session_count, secret_files = sys.argv[1:]

def file_info(path):
    p = Path(path)
    if not p.exists():
        return None
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return {
        "name": p.name,
        "bytes": p.stat().st_size,
        "sha256": h.hexdigest(),
    }

files = []
for path in (results, overrides, html, archive):
    info = file_info(path)
    if info:
        files.append(info)

manifest = {
    "name": f"data-{suffix}",
    "created_at": datetime.now(timezone.utc).isoformat(),
    "source_dir": source_dir,
    "release_dir": release_dir,
    "data_shape": "curated results, display overrides, and lightweight public run archive: config.json + result.json + sanitized Hermes usage",
    "runs_archive": Path(archive).name,
    "counts": {
        "config_json": int(config_count),
        "result_json": int(result_count),
        "hermes_session_jsonl": int(hermes_session_count),
        "redacted_files": int(secret_files),
    },
    "files": files,
}

Path(manifest_path).write_text(json.dumps(manifest, indent=2) + "\n")
PY

echo ""
echo "=== Writing checksums ==="
(
    cd "$RELEASE_DIR"
    rm -f "$CHECKSUMS"
    for f in wolfbench_results_"${SUFFIX}".json wolfbench-overrides.json wolfbench_"${SUFFIX}".html wolfbench-runs-full-"${SUFFIX}".tar.zst manifest-"${SUFFIX}".json; do
        [[ -f "$f" ]] || continue
        shasum -a 256 "$f" >> SHA256SUMS
    done
)

echo ""
echo "Release assets ready:"
ls -lh "$RELEASE_DIR"
