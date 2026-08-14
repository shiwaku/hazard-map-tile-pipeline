#!/usr/bin/env bash
# Step 5: メタデータ生成。
#   tiles.json  … TileJSON 2.2.0（数値PNGなら係数 f・オフセット o を必ず含める）
#   legend.json … 産総研 JSON凡例フォーマット（パレットPNGのみ）

STEP_NAME="05_make_metadata"
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
load_config "${1:-}"

[[ -d "$TILES_DIR" ]] || die "$TILES_DIR が無い。先に 04_make_tiles.sh を実行すること"

tile_type="$(decision tile_type)"

args=(
  --inputs "$INPUTS_JSON"
  --outdir "$TILES_DIR"
  --tile-url "$TILE_URL"
  --tile-format "$TILE_FORMAT"
  --name "$DATASET_ID"
)
[[ -n "$DESCRIPTION" ]] && args+=(--description "$DESCRIPTION")
[[ -n "$ATTRIBUTION" ]] && args+=(--attribution "$ATTRIBUTION")

if [[ "$tile_type" == "palette" ]]; then
  args+=(--rankdef "$RANK_DEF")
else
  args+=(--factor "$NUM_FACTOR" --offset "$NUM_OFFSET" --unit "$NUM_UNIT")
  # 元ラスターの実際の値域を添える（利用側がスケールを決めるときの手掛かりになる）
  read -r vmin vmax < <(python3 - "$WORK_DIR/value_hires.tif" <<'PY'
import sys
from osgeo import gdal
gdal.UseExceptions()
# Dataset の参照を保持する。一時オブジェクトのまま GetRasterBand すると
# Dataset が回収されてバンドが無効になる（GDAL Python の定番の罠）。
ds = gdal.Open(sys.argv[1])
mn, mx = ds.GetRasterBand(1).ComputeRasterMinMax(False)
print(mn, mx)
PY
)
  args+=(--value-min "$vmin" --value-max "$vmax")
fi

run python3 "$TOOLS_DIR/make_metadata.py" "${args[@]}"
log "完了"
