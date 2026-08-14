#!/usr/bin/env bash
# Step 0（任意）: サンプルデータを取得する。
#
# 設定に FETCH_URL があるときだけ動く。data/ 以下はリポジトリに含めないので、
# 手元で再現するにはこのステップを最初に一度だけ実行する。

STEP_NAME="00_fetch_data"
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

FETCH_URL=""
FETCH_CONTAINS=""
FETCH_FLATTEN="false"
load_config "${1:-}"

[[ -n "${FETCH_URL:-}" ]] || die "FETCH_URL が未設定。手動で $SRC_DIR にデータを置くこと"

args=("$FETCH_URL" "$SRC_DIR")
[[ -n "${FETCH_CONTAINS:-}" ]] && args+=(--contains "$FETCH_CONTAINS")
[[ "${FETCH_FLATTEN:-false}" == "true" ]] && args+=(--flatten)
[[ "${2:-}" == "--force" ]] && args+=(--force)

run python3 "$TOOLS_DIR/fetch_data.py" "${args[@]}"
log "完了: $SRC_DIR"
