#!/usr/bin/env bash
# Step 3: ラスタライズ。ポリゴンをメッシュ解像度のグリッドに焼き、
# 続けて nearest neighbor で UPSCALE 倍に拡大する。
#
# 拡大する理由: メッシュ解像度のままタイル化すると、最大ZLで1メッシュが数ピクセルに
# しかならず、ブラウザ側の拡大補間でメッシュ境界がぼやける。nearest で先に細かく
# しておくと境界が保たれる。bilinear 等を使うと隣接ランクの色（＝値）が混ざるので使わない。

STEP_NAME="03_rasterize"
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
load_config "${1:-}"
require_cmd gdal_rasterize gdalwarp gdalinfo

value_kind="$(decision value_kind)"
tile_type="$(decision tile_type)"
lon_step="$(decision lon_step_deg)"
lat_step="$(decision lat_step_deg)"

[[ -n "$lon_step" && -n "$lat_step" ]] || die "メッシュ間隔が inputs.json に無い。MESH_SIZE を明示すること"

IN_GPKG="$WORK_DIR/prepared.gpkg"
[[ -f "$IN_GPKG" ]] || die "$IN_GPKG が無い。先に 02_prepare.sh を実行すること"

GRAY_TIF="$WORK_DIR/value.tif"
HIRES_TIF="$WORK_DIR/value_hires.tif"

# 値の型: ランクは整数、浸水深は実数。
# ランクの 0 は「浸水なし」を意味する実データ値なので -init 0 でよい。
# 実数値は 0m が有効値になりうるため、nodata を別に立てる。
if [[ "$tile_type" == "palette" ]]; then
  ot="Int32"; init="-init 0"; nodata_args=()
  log "ランクラスターを作る（0 = 浸水なし）"
else
  ot="Float32"; init="-init -9999"; nodata_args=(-a_nodata -9999)
  log "実数値ラスターを作る（-9999 = 無効値）"
fi

log "解像度: 経度 $lon_step 度 × 緯度 $lat_step 度"

# shellcheck disable=SC2086
run gdal_rasterize \
  -a _value \
  $init \
  "${nodata_args[@]}" \
  -ot "$ot" \
  -tr "$lon_step" "$lat_step" \
  -tap \
  -co COMPRESS=DEFLATE -co PREDICTOR=2 -co TILED=YES \
  -l prepared \
  "$IN_GPKG" "$GRAY_TIF"

if [[ "${UPSCALE:-1}" -gt 1 ]]; then
  hi_lon="$(python3 -c "print(repr($lon_step / $UPSCALE))")"
  hi_lat="$(python3 -c "print(repr($lat_step / $UPSCALE))")"
  log "高解像度化: ${UPSCALE}倍（nearest neighbor）→ 経度 $hi_lon 度 × 緯度 $hi_lat 度"
  run gdalwarp \
    -tr "$hi_lon" "$hi_lat" \
    -r near \
    -of GTiff \
    -co COMPRESS=DEFLATE -co PREDICTOR=2 -co TILED=YES \
    -overwrite \
    "$GRAY_TIF" "$HIRES_TIF"
else
  cp -f "$GRAY_TIF" "$HIRES_TIF"
fi

gdalinfo -stats "$HIRES_TIF" | sed -n '/Size is/p;/Minimum=/p'
log "完了: $HIRES_TIF"
