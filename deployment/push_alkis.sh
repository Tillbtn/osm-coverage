#!/usr/bin/env bash
#
# Push locally-processed ALKIS (all or selected states) data to the server. Sends both files per state:
#   data/<st>/alkis.parquet     the extracted addresses
#   data/<st>/alkis_meta.json   the processed ALKIS stand
#
set -euo pipefail

REMOTE="${REMOTE:-osm-coverage}"
REMOTE_BASE="${REMOTE_BASE:-/opt/osm-coverage/data_link}"
DATA_DIR="data"

SSH_OPTS="-o RemoteCommand=none -o RequestTTY=no"

# States to push: CLI args, or auto-detect every data/<st>/alkis.parquet.
if [ "$#" -gt 0 ]; then
    states=("$@")
else
    states=()
    for p in "$DATA_DIR"/*/alkis.parquet; do
        [ -e "$p" ] || continue
        states+=("$(basename "$(dirname "$p")")")
    done
fi

if [ "${#states[@]}" -eq 0 ]; then
    echo "No states with $DATA_DIR/<st>/alkis.parquet found." >&2
    exit 1
fi

echo "Pushing ${#states[@]} state(s) to $REMOTE:$REMOTE_BASE"
for st in "${states[@]}"; do
    parquet="$DATA_DIR/$st/alkis.parquet"
    meta="$DATA_DIR/$st/alkis_meta.json"

    if [ ! -f "$parquet" ]; then
        echo "  [$st] skip: no $parquet" >&2
        continue
    fi

    echo "  [$st] -> $REMOTE_BASE/$st/"
    ssh $SSH_OPTS "$REMOTE" "mkdir -p '$REMOTE_BASE/$st'"
    scp $SSH_OPTS "$parquet" "$REMOTE:$REMOTE_BASE/$st/alkis.parquet"

    if [ -f "$meta" ]; then
        scp $SSH_OPTS "$meta" "$REMOTE:$REMOTE_BASE/$st/alkis_meta.json"
    else
        echo "  [$st] note: no alkis_meta.json" >&2
    fi
done

echo "Done."
