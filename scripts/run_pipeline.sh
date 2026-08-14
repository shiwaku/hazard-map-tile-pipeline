#!/usr/bin/env bash
# Step 1〜5 を通しで実行する。
#
#   ./scripts/run_pipeline.sh config/sample.conf
#   ./scripts/run_pipeline.sh config/sample.conf --from 3
#   ./scripts/run_pipeline.sh config/sample.conf --from 2 --to 4

set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

conf="${1:-}"
[[ -n "$conf" ]] || { echo "使い方: $0 <config> [--from N] [--to N]" >&2; exit 1; }
shift

from=1; to=5
while [[ $# -gt 0 ]]; do
  case "$1" in
    --from) from="$2"; shift 2 ;;
    --to)   to="$2";   shift 2 ;;
    *) echo "不明な引数: $1" >&2; exit 1 ;;
  esac
done

steps=(
  "01_inspect.sh"
  "02_prepare.sh"
  "03_rasterize.sh"
  "04_make_tiles.sh"
  "05_make_metadata.sh"
)

start=$(date +%s)
for i in $(seq "$from" "$to"); do
  script="${steps[$((i-1))]}"
  printf '\n\033[1;32m=== Step %d: %s ===\033[0m\n' "$i" "$script" >&2
  bash "$HERE/$script" "$conf"
done
printf '\n\033[1;32m完了 (%d 秒)\033[0m\n' "$(( $(date +%s) - start ))" >&2
