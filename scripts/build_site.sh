#!/usr/bin/env bash
# 公開用サイト一式を組み立てる。
#
#   ./scripts/build_site.sh                → _site/
#   ./scripts/build_site.sh path/to/dir    → 出力先を指定
#
# output/ にはタイルのほかに inspect/（検査レポート）と work/（中間ラスター）が
# 入っていて合計 20MB 近い。公開するのはタイルとビューワだけなので、必要なものを
# 別ディレクトリに集める。GitHub Pages にはこのディレクトリを配る。
#
# serve.sh との違い: serve.sh はローカル確認用に output/ 直下へビューワを置く
# （中間ファイルもそのまま残る）。こちらは公開物だけを別に組み立てるので、
# 手元でも「実際に公開される中身」をそのまま確認できる。
#
# 事前に viewer/dist が必要:
#
#   cd viewer && npm ci && npm run build

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT_DIR="$REPO_ROOT/output"
DIST_DIR="$REPO_ROOT/viewer/dist"
SITE_DIR="${1:-$REPO_ROOT/_site}"

log() { printf '\033[1;34m[build_site]\033[0m %s\n' "$*" >&2; }
die() { printf '\033[1;31m[build_site] エラー:\033[0m %s\n' "$*" >&2; exit 1; }

[[ -d "$OUTPUT_DIR" ]] || die "output/ が無い。先に ./scripts/run_pipeline.sh を実行すること"
[[ -f "$DIST_DIR/index.html" ]] || die "ビューワがビルドされていない。次を実行すること:
    cd viewer && npm ci && npm run build"

rm -rf "$SITE_DIR"
mkdir -p "$SITE_DIR"

# ビューワ本体（index.html / assets / icons / sw.js / manifest）
cp -R "$DIST_DIR/." "$SITE_DIR/"

# タイルセット。tiles/tiles.json があるディレクトリだけを対象にするので、
# inspect/ と work/ は公開されない。
n=0
while IFS= read -r -d '' tj; do
  id="$(basename "$(dirname "$(dirname "$tj")")")"
  mkdir -p "$SITE_DIR/$id/tiles"
  cp -R "$OUTPUT_DIR/$id/tiles/." "$SITE_DIR/$id/tiles/"
  log "収録: $id"
  n=$((n + 1))
done < <(find "$OUTPUT_DIR" -mindepth 3 -maxdepth 3 -path '*/tiles/tiles.json' -print0)

[[ "$n" -gt 0 ]] || die "公開できるタイルセットが無い（output/<id>/tiles/tiles.json が見つからない）"

# ビューワはこの一覧を読んでレイヤーを組み立てる
python3 "$REPO_ROOT/tools/make_dataset_index.py" "$SITE_DIR"

log "完了: $SITE_DIR（$n タイルセット / $(find "$SITE_DIR" -type f | wc -l) ファイル / $(du -sh "$SITE_DIR" | cut -f1)）"
