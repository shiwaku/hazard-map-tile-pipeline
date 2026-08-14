#!/usr/bin/env bash
# Step 4: タイル生成。
#
#   palette: ランクラスター → gdaldem color-relief -exact_color_entry → gdal2tiles
#   numeric: 実数値ラスター → tools/encode_numeric.py で RGBA に符号化 → gdal2tiles
#
# 縮小方法は既定 near。average / bilinear を使うと、下位ZLのタイルに
# 「凡例に無い色」や「元の値と対応しない画素値」が現れて、どちらの仕様からも外れる。
# near はどのバンドも同じ元ピクセルを採るため、色の組み合わせが崩れない。

STEP_NAME="04_make_tiles"
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
load_config "${1:-}"
require_cmd gdal2tiles.py
require_python_gdal

tile_type="$(decision tile_type)"
min_zoom="$(decision min_zoom)"
max_zoom="$(decision max_zoom)"

HIRES_TIF="$WORK_DIR/value_hires.tif"
[[ -f "$HIRES_TIF" ]] || die "$HIRES_TIF が無い。先に 03_rasterize.sh を実行すること"

RGBA="$WORK_DIR/rgba.vrt"

if [[ "$tile_type" == "palette" ]]; then
  require_cmd gdaldem
  [[ -n "$RANK_DEF" ]] || die "RANK_DEF が未設定"
  CMAP="$WORK_DIR/colormap.txt"
  run python3 "$TOOLS_DIR/rankdef.py" "$RANK_DEF" --emit colormap -o "$CMAP"
  log "カラーマップ: $CMAP"
  # -exact_color_entry: 定義した値に完全一致した画素だけ着色する。
  # 補間色を作らせないことがパレットPNGの前提（凡例に無い色を出さない）。
  run gdaldem color-relief "$HIRES_TIF" "$CMAP" "$RGBA" -of VRT -alpha -exact_color_entry
else
  RGBA="$WORK_DIR/rgba.tif"
  run python3 "$TOOLS_DIR/encode_numeric.py" "$HIRES_TIF" "$RGBA" \
    --factor "$NUM_FACTOR" --offset "$NUM_OFFSET" --src-nodata -9999
fi

rm -rf "$TILES_DIR"
mkdir -p "$TILES_DIR"

tile_args=(
  --xyz
  -z "${min_zoom}-${max_zoom}"
  -r "$TILE_RESAMPLING"
  --processes="$PROCESSES"
  -w none
  -x
)
[[ "$TILE_FORMAT" != "png" ]] && tile_args+=(--tiledriver="$(echo "$TILE_FORMAT" | tr '[:lower:]' '[:upper:]')")
[[ "$RESUME" == "true" ]] && tile_args+=(-e)

run gdal2tiles.py "${tile_args[@]}" "$RGBA" "$TILES_DIR"

n="$(find "$TILES_DIR" -name "*.${TILE_FORMAT}" | wc -l)"
size="$(du -sh "$TILES_DIR" | cut -f1)"
log "完了: $n タイル / $size （$TILES_DIR）"
