"""タイルセットのメタデータを生成する.

出力は 2 つ.

  tiles.json   TileJSON 2.2.0. 数値PNGの場合は係数 f とオフセット o を必ず含める
               (これが無いと受け取り側は画素値から実数を復元できない).
  legend.json  産総研 JSON凡例フォーマット. パレットPNGの場合のみ.

標準ライブラリのみを使う.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rankdef  # noqa: E402


def build_tilejson(inputs, tile_url, tile_format, attribution=None, name=None,
                   description=None, numeric=None, legend_url=None):
    d = inputs["decisions"]
    minx, miny, maxx, maxy = d["bounds"]
    tj = {
        "tilejson": "2.2.0",
        "name": name or inputs["dataset_id"],
        "scheme": "xyz",
        "tiles": [tile_url],
        "minzoom": d["min_zoom"],
        "maxzoom": d["max_zoom"],
        "bounds": [round(minx, 7), round(miny, 7), round(maxx, 7), round(maxy, 7)],
        "center": [round((minx + maxx) / 2, 7), round((miny + maxy) / 2, 7), d["max_zoom"]],
        "format": tile_format,
    }
    if description:
        tj["description"] = description
    if attribution:
        tj["attribution"] = attribution

    # 仕様準拠の情報。TileJSON の標準メンバーではないので接頭辞を付けて衝突を避ける。
    ext = {
        "tile_type": d["tile_type"],
        "value_kind": d["value_kind"],
        "value_field": d["value_field"],
        "mesh": d["mesh_label"],
        "spec": "https://gsj-seamless.jp/labs/datapng/gridpngtileSpec.html",
    }
    if d.get("mesh_side_m"):
        ext["mesh_side_m"] = d["mesh_side_m"]
    if numeric:
        # 数値PNGタイル: v = factor * (2^16 r' + 2^8 g + b) + offset
        ext["numeric"] = {
            "factor": numeric["factor"],
            "offset": numeric["offset"],
            "unit": numeric.get("unit", ""),
            "formula": "v = factor * (2^16 * r' + 2^8 * g + b) + offset  "
                       "(r' = r if r < 128 else r - 256)",
            "nodata": "alpha = 0",
        }
        if numeric.get("value_min") is not None:
            ext["numeric"]["value_min"] = numeric["value_min"]
            ext["numeric"]["value_max"] = numeric["value_max"]
    if legend_url:
        ext["legend"] = legend_url
    tj["datapng"] = ext
    return tj


def main(argv=None):
    ap = argparse.ArgumentParser(description="tiles.json / legend.json を生成する")
    ap.add_argument("--inputs", required=True, help="01_inspect が出した inputs.json")
    ap.add_argument("--outdir", required=True, help="タイルディレクトリ (tiles/)")
    ap.add_argument("--tile-url", required=True)
    ap.add_argument("--tile-format", default="png")
    ap.add_argument("--name")
    ap.add_argument("--description")
    ap.add_argument("--attribution")
    ap.add_argument("--rankdef", help="パレットPNGのときのランク定義 JSON")
    ap.add_argument("--legend-url", help="tiles.json に書く legend.json の URL")
    ap.add_argument("--factor", type=float)
    ap.add_argument("--offset", type=float)
    ap.add_argument("--unit", default="")
    ap.add_argument("--value-min", type=float)
    ap.add_argument("--value-max", type=float)
    a = ap.parse_args(argv)

    with open(a.inputs, encoding="utf-8") as f:
        inputs = json.load(f)

    tile_type = inputs["decisions"]["tile_type"]
    os.makedirs(a.outdir, exist_ok=True)

    numeric = None
    legend_url = None

    if tile_type == "numeric":
        if a.factor is None:
            raise SystemExit("数値PNGには --factor が必要")
        numeric = {
            "factor": a.factor,
            "offset": a.offset or 0.0,
            "unit": a.unit,
            "value_min": a.value_min,
            "value_max": a.value_max,
        }
    else:
        if not a.rankdef:
            raise SystemExit("パレットPNGには --rankdef が必要")
        rd = rankdef.load(a.rankdef)
        legend_path = os.path.join(a.outdir, "legend.json")
        with open(legend_path, "w", encoding="utf-8") as f:
            json.dump(rd.legend_json(), f, ensure_ascii=False, indent=2)
            f.write("\n")
        legend_url = a.legend_url or "legend.json"
        print(f"legend.json: {legend_path}")

    tj = build_tilejson(
        inputs,
        tile_url=a.tile_url,
        tile_format=a.tile_format,
        attribution=a.attribution,
        name=a.name,
        description=a.description,
        numeric=numeric,
        legend_url=legend_url,
    )
    tj_path = os.path.join(a.outdir, "tiles.json")
    with open(tj_path, "w", encoding="utf-8") as f:
        json.dump(tj, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"tiles.json: {tj_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
