#!/usr/bin/env bash
# Step 1: 入力検査。auto 値を解決して inspect/{inputs.json,report.md} に残す。
# 以降のステップは inputs.json だけを読む。

STEP_NAME="01_inspect"
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
load_config "${1:-}"
require_python_gdal

[[ -d "$SRC_DIR" ]] || die "入力ディレクトリが無い: $SRC_DIR"
resolve_src_encoding
mkdir -p "$INSPECT_DIR"

args=(
  "$SRC_DIR"
  --dataset-id "$DATASET_ID"
  --value-field "$VALUE_FIELD"
  --value-kind "$VALUE_KIND"
  --tile-type "$TILE_TYPE"
  --min-zoom "$MIN_ZOOM"
  --max-zoom "$MAX_ZOOM"
  --max-zoom-margin "$MAX_ZOOM_MARGIN"
  --max-zoom-cap "$MAX_ZOOM_CAP"
  --mesh-size "$MESH_SIZE"
  --srs "$SRC_SRS"
  -o "$INSPECT_DIR"
)
[[ -n "$SRC_PATTERN" ]] && args+=(--pattern "$SRC_PATTERN")

python3 "$TOOLS_DIR/inspect_inputs.py" "${args[@]}"

tile_type="$(decision tile_type)"
if [[ "$tile_type" == "palette" && -z "$RANK_DEF" ]]; then
  warn "タイル種別が palette だが RANK_DEF が未設定。colors/ の定義を指定すること"
fi

log "完了: $INSPECT_DIR/report.md"
