#!/usr/bin/env bash
# 生成したタイルをローカルの MapLibre ビューワで確認する。
#
#   ./scripts/serve.sh            → http://localhost:8080/
#   ./scripts/serve.sh 9000       → ポート指定
#
# output/ 以下の全タイルセットを一覧に出すので、設定ファイルは取らない。
# ビューワは Vite アプリ（viewer/）なので、初回だけビルドが必要:
#
#   cd viewer && npm ci && npm run build
#
# 開発中は `cd viewer && npm run dev` のほうが速い（HMR が効き、
# output/ を /data として直接読むのでコピーも要らない）。

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT_DIR="$REPO_ROOT/output"
DIST_DIR="$REPO_ROOT/viewer/dist"
PORT="${1:-${PORT:-8080}}"

log()  { printf '\033[1;34m[serve]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[serve] エラー:\033[0m %s\n' "$*" >&2; exit 1; }

[[ -d "$OUTPUT_DIR" ]] || die "output/ が無い。先に ./scripts/run_pipeline.sh を実行すること"

# データセット一覧を作る（ビューワはこれを読んでレイヤーを組み立てる）
python3 "$REPO_ROOT/tools/make_dataset_index.py" "$OUTPUT_DIR"

if [[ ! -f "$DIST_DIR/index.html" ]]; then
  die "ビューワがビルドされていない。次を実行すること:
    cd viewer && npm ci && npm run build
  （開発中は cd viewer && npm run dev のほうが手軽）"
fi

# ビルド成果物を output/ 直下に置く。タイルは ./<データセットID>/tiles/... で
# 同じ階層から引けるので、静的サーバー 1 つで完結する。
log "ビューワを配置: $DIST_DIR → $OUTPUT_DIR"
cp -R "$DIST_DIR/." "$OUTPUT_DIR/"

log "http://localhost:$PORT/ で確認できる（Ctrl-C で終了）"
cd "$OUTPUT_DIR"
exec python3 -m http.server "$PORT"
