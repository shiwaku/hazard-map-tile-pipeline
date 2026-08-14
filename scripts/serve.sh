#!/usr/bin/env bash
# 生成したタイルをローカルの MapLibre ビューワで確認する。
#
#   ./scripts/serve.sh config/sample.conf        → http://localhost:8080/

STEP_NAME="serve"
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
load_config "${1:-}"

PORT="${PORT:-8080}"
[[ -d "$TILES_DIR" ]] || die "$TILES_DIR が無い。先にタイルを生成すること"

cp -f "$REPO_ROOT/viewer/index.html" "$OUT_DIR/index.html"

log "http://localhost:$PORT/ で確認できる（Ctrl-C で終了）"
cd "$OUT_DIR"
exec python3 -m http.server "$PORT"
