#!/usr/bin/env bash
# 共通処理: 設定ロード・既定値・ログ・依存チェック
# 各ステップスクリプトの先頭で source して使う.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TOOLS_DIR="$REPO_ROOT/tools"
COLORS_DIR="$REPO_ROOT/colors"

# ---- ログ -------------------------------------------------------------------

log()  { printf '\033[1;34m[%s]\033[0m %s\n' "${STEP_NAME:-pipeline}" "$*" >&2; }
warn() { printf '\033[1;33m[%s] 警告:\033[0m %s\n' "${STEP_NAME:-pipeline}" "$*" >&2; }
die()  { printf '\033[1;31m[%s] エラー:\033[0m %s\n' "${STEP_NAME:-pipeline}" "$*" >&2; exit 1; }

run() { log "実行: $*"; "$@"; }

# ---- 設定 -------------------------------------------------------------------

load_config() {
  local conf="${1:-}"
  [[ -n "$conf" ]] || die "設定ファイルを第1引数に指定すること (例: config/sample.conf)"
  [[ -f "$conf" ]] || die "設定ファイルが無い: $conf"

  # --- 既定値 ---------------------------------------------------------------
  DATASET_ID=""                 # 出力ディレクトリ名。必須
  SRC_DIR=""                    # 入力ディレクトリ。必須
  SRC_PATTERN=""                # ファイル名の部分一致で絞り込む（省略可）
  SRC_SRS="auto"                # 入力の CRS。auto なら埋め込みから判定
  VALUE_FIELD="auto"            # ランク／浸水深が入っている属性名
  VALUE_KIND="auto"             # rank | depth | auto
  TILE_TYPE="auto"              # palette | numeric | auto
  RANK_DEF=""                   # colors/*.json（palette のとき必須）
  MESH_SIZE="auto"              # メッシュ1辺のメートル数。auto なら頂点間隔から実測
  UPSCALE=2                     # ラスタライズ後の高解像度化倍率（メッシュ境界を保つ）
  MIN_ZOOM=9
  MAX_ZOOM="auto"
  MAX_ZOOM_MARGIN=3             # ネイティブZLへの加算段数
  MAX_ZOOM_CAP=18
  TILE_RESAMPLING="near"        # 下位ZLの縮小方法。near 以外は原則使わない（README参照）
  TILE_FORMAT="png"
  NUM_FACTOR=0.01               # 数値PNGの係数 f
  NUM_OFFSET=0                  # 数値PNGのオフセット o
  NUM_UNIT="m"
  SRC_ENCODING="auto"           # 入力 DBF の文字コード。auto なら指定の無いものを CP932 と仮定
  MAKEVALID="true"              # ogr2ogr -makevalid を使うか
  PROCESSES=8
  TILE_URL=""                   # tiles.json に書く URL テンプレート
  ATTRIBUTION=""
  DESCRIPTION=""
  RESUME="false"

  # shellcheck disable=SC1090
  source "$conf"

  CONFIG_FILE="$conf"
  [[ -n "$DATASET_ID" ]] || die "DATASET_ID が未設定: $conf"
  [[ -n "$SRC_DIR" ]]    || die "SRC_DIR が未設定: $conf"

  # 相対パスは設定ファイルからではなくリポジトリルートから解決する
  [[ "$SRC_DIR" = /* ]] || SRC_DIR="$REPO_ROOT/$SRC_DIR"
  if [[ -n "$RANK_DEF" && "$RANK_DEF" != /* ]]; then RANK_DEF="$REPO_ROOT/$RANK_DEF"; fi

  OUT_DIR="$REPO_ROOT/output/$DATASET_ID"
  INSPECT_DIR="$OUT_DIR/inspect"
  WORK_DIR="$OUT_DIR/work"
  TILES_DIR="$OUT_DIR/tiles"
  INPUTS_JSON="$INSPECT_DIR/inputs.json"

  [[ -n "$TILE_URL" ]] || TILE_URL="./{z}/{x}/{y}.${TILE_FORMAT}"

  mkdir -p "$OUT_DIR"
}

# inputs.json から判定結果を読む。各ステップはここだけを根拠にする。
decision() {
  local key="$1"
  [[ -f "$INPUTS_JSON" ]] || die "$INPUTS_JSON が無い。先に 01_inspect.sh を実行すること"
  python3 -c "
import json,sys
d=json.load(open('$INPUTS_JSON',encoding='utf-8'))['decisions']
v=d.get('$key')
print('' if v is None else v)
"
}

# ---- 依存チェック -----------------------------------------------------------

require_cmd() {
  for c in "$@"; do
    command -v "$c" >/dev/null 2>&1 || die "$c が見つからない。GDAL をインストールすること"
  done
}

require_python_gdal() {
  python3 -c "from osgeo import gdal" 2>/dev/null \
    || die "Python の GDAL バインディング (osgeo) が無い"
}

# ---- 入力の文字コード -------------------------------------------------------

# シェープファイルの DBF の文字コードは、.cpg ファイルか DBF ヘッダの LDID
# （29 バイト目）で示される。国土数値情報は LDID=19（Shift-JIS）が入っているので
# GDAL が正しく読む。一方、電子化ガイドラインの MAXALL シェープは LDID=0（指定なし）で
# .cpg も無く、GDAL は日本語のフィールド名を生バイトのまま返す。属性名が
# `浸水深` ではなく `\udc90Z...` になり、VALUE_FIELD の指定が一致しなくなる
# （石川県の公開データで実際に踏んだ）。
#
# 指定がまったく無いときだけ CP932 を仮定する。日本語のハザードデータでは
# 事実上これで正しく、指定があるデータには触らないので既存の入力を壊さない。
resolve_src_encoding() {
  local mode="${SRC_ENCODING:-auto}"
  if [[ "$mode" != "auto" ]]; then
    [[ -n "$mode" ]] && { export SHAPE_ENCODING="$mode"; log "SHAPE_ENCODING=$mode（設定で明示指定）"; }
    return 0
  fi

  local enc
  enc="$(list_inputs "$SRC_DIR" "$SRC_PATTERN" | python3 -c '
import os, sys

for raw in sys.stdin.buffer.read().split(b"\0"):
    if not raw:
        continue
    path = os.fsdecode(raw)
    stem, ext = os.path.splitext(path)
    if ext.lower() != ".shp":
        continue
    # .cpg があれば GDAL がそれを見るので触らない
    if any(os.path.exists(stem + e) for e in (".cpg", ".CPG")):
        break
    dbf = next((stem + e for e in (".dbf", ".DBF") if os.path.exists(stem + e)), None)
    if not dbf:
        break
    with open(dbf, "rb") as f:
        f.seek(29)
        ldid = f.read(1)
    if ldid and ldid[0] == 0:
        print("CP932")
    break
')" || return 0

  if [[ "$enc" == "CP932" ]]; then
    export SHAPE_ENCODING="CP932"
    log "DBF に文字コードの指定が無いため SHAPE_ENCODING=CP932 を仮定する"
  fi
}

# 入力ファイルを NUL 区切りで列挙する（空白・日本語のファイル名に耐える）
list_inputs() {
  local dir="$1" pattern="${2:-}"
  if [[ -n "$pattern" ]]; then
    find "$dir" -type f \( -iname '*.shp' -o -iname '*.geojson' -o -iname '*.json' \
      -o -iname '*.gpkg' -o -iname '*.fgb' \) -name "*${pattern}*" -print0 | sort -z
  else
    find "$dir" -type f \( -iname '*.shp' -o -iname '*.geojson' -o -iname '*.json' \
      -o -iname '*.gpkg' -o -iname '*.fgb' \) -print0 | sort -z
  fi
}
