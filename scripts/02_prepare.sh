#!/usr/bin/env bash
# Step 2: 前処理。入力を 1 つの GPKG にまとめ、CRS を EPSG:4326 に揃え、
# 値属性を `_value` という固定名の整数（または実数）カラムに正規化する。
#
# 属性名は案件ごとにばらばらなので、ここで一度だけ正規化して以降を単純にする。
# 実数値 → パレットPNG の場合は、ここでランク定義のしきい値に従ってランクに分類する。

STEP_NAME="02_prepare"
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
load_config "${1:-}"
require_cmd ogr2ogr ogrinfo
resolve_src_encoding

value_field="$(decision value_field)"
value_kind="$(decision value_kind)"
tile_type="$(decision tile_type)"
src_srs="$(decision srs)"

mkdir -p "$WORK_DIR"
OUT_GPKG="$WORK_DIR/prepared.gpkg"
LAYER="prepared"

# 値カラムの作り方を決める
if [[ "$value_kind" == "depth" && "$tile_type" == "palette" ]]; then
  [[ -n "$RANK_DEF" ]] || die "実数値をパレットPNGにするにはランク定義 (RANK_DEF) が必要"
  value_expr="$(python3 "$TOOLS_DIR/rankdef.py" "$RANK_DEF" --emit sql --field "$value_field" \
                 | sed 's/ AS rank$/ AS _value/')"
  log "実数値 → ランク分類を適用する（$(basename "$RANK_DEF")）"
else
  value_expr="\"$value_field\" AS _value"
fi

feature_count() {
  ogrinfo -so -al "$OUT_GPKG" "$LAYER" 2>/dev/null | awk '/Feature Count/{print $3}'
}

convert_one() {
  local src="$1" layer_name="$2" makevalid="$3" first="$4"
  local -a cmd=(ogr2ogr -f GPKG)
  [[ $first -eq 1 ]] || cmd+=(-update -append)
  cmd+=(
    -nln "$LAYER"
    -t_srs EPSG:4326
    -s_srs "$src_srs"
    -nlt MULTIPOLYGON
    -dialect SQLITE
    -sql "SELECT geometry AS geom, $value_expr FROM \"$layer_name\" WHERE \"$value_field\" IS NOT NULL"
  )
  [[ "$makevalid" == "true" ]] && cmd+=(-makevalid)
  [[ $first -eq 1 ]] && cmd+=(-lco SPATIAL_INDEX=YES)
  cmd+=("$OUT_GPKG" "$src")
  "${cmd[@]}"
}

# 入力をすべて 1 つの GPKG にまとめる。-makevalid の有無はデータセット全体で
# 揃える（ファイルごとに切り替えると、失敗した append の残骸と正常分の区別が
# つかず二重登録になりうる）。やり直すときは GPKG ごと作り直す。
#
# 戻り値: 0=成功 / 1=ogr2ogr が失敗 / 2=全件落ちた
convert_all() {
  local makevalid="$1"
  local first=1 count=0 before after added src layer_name actual

  rm -f "$OUT_GPKG"
  while IFS= read -r -d '' src; do
    layer_name="$(basename "${src%.*}")"
    # GPKG / GeoJSON はレイヤ名がファイル名と一致しないことがあるので実際の名前を引く
    actual="$(ogrinfo -q "$src" 2>/dev/null | head -1 | sed 's/^[0-9]*: //; s/ (.*//')"
    [[ -n "$actual" ]] && layer_name="$actual"

    log "変換: $(basename "$src") (レイヤ: $layer_name)"
    before=0
    [[ $first -eq 0 ]] && before="$(feature_count)"

    convert_one "$src" "$layer_name" "$makevalid" "$first" || return 1

    after="$(feature_count)"
    added=$(( after - before ))
    [[ "$added" -gt 0 ]] || return 2

    log "  → $added 件追加（累計 $after 件）"
    first=0
    count=$(( count + 1 ))
  done < <(list_inputs "$SRC_DIR" "$SRC_PATTERN")

  [[ $count -gt 0 ]] || die "入力が 1 件も無い: $SRC_DIR"
  CONVERTED_FILES=$count
  return 0
}

# -makevalid は無効ジオメトリを直せる一方で、全件落とすことも、例外で
# ogr2ogr ごと落ちることもある（後者は石川県の MAXALL で実際に踏んだ。
# 閉じていないリングが混ざっており GEOS が IllegalArgumentException を投げる）。
# どちらの壊れ方でも -makevalid 無しに戻して通す。
rc=0
convert_all "$MAKEVALID" || rc=$?
if [[ $rc -ne 0 ]]; then
  [[ "$MAKEVALID" == "true" ]] || die "ogr2ogr が失敗した（-makevalid は使っていない）: $SRC_DIR"
  case $rc in
    1) warn "-makevalid で ogr2ogr が失敗した。-makevalid 無しでやり直す" ;;
    2) warn "-makevalid で全件落ちた。-makevalid 無しでやり直す" ;;
  esac
  rc=0
  convert_all "false" || rc=$?
  [[ $rc -eq 0 ]] || die "-makevalid 無しでも変換できなかった: $SRC_DIR"
fi

count="$CONVERTED_FILES"
total="$(feature_count)"
log "完了: $OUT_GPKG（$count ファイル / $total フィーチャ）"
