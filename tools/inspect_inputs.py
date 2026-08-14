"""入力ベクトルデータを検査し、パイプラインの `auto` 値を解決する.

このスクリプトが判定するもの:

  * 値属性 (VALUE_FIELD)   … ランクまたは浸水深が入っている属性
  * 値の種別 (VALUE_KIND)  … rank (離散ランク) か depth (実数値) か
  * 出力タイル種別          … rank -> palette 固定 / depth -> palette も numeric も可
  * メッシュサイズ          … ポリゴン頂点の座標間隔から実測する
  * 最大ズームレベル        … メッシュサイズとデータ中心緯度から算出

判定根拠はすべて report.md に残す. パイプラインの各ステップは inputs.json だけを
読み、判定をやり直さない (根拠とレポートが食い違うと追えなくなるため).

標準ライブラリと osgeo のみを使う.
"""

import argparse
import json
import math
import os
import sys
from collections import Counter

from osgeo import gdal, ogr, osr

gdal.UseExceptions()
ogr.UseExceptions()

VECTOR_EXT = (".shp", ".geojson", ".json", ".gpkg", ".fgb", ".gml")

# 値属性の候補名. 上にあるものほど優先する.
# 国土数値情報は属性名がコード化されているため、実データで確認した対応を持つ.
FIELD_HINTS = [
    # 国土数値情報 洪水浸水想定区域 (河川単位 A31a / 1次メッシュ単位 A31b)
    ("A31a_205", "浸水深ランク（想定最大規模）"),
    ("A31a_105", "浸水深ランク（計画規模）"),
    ("A31a_305", "浸水継続時間ランク"),
    ("A31a_405", "危険区域区分"),
    ("A31b_201", "浸水深ランク（想定最大規模）"),
    ("A31b_101", "浸水深ランク（計画規模）"),
    ("A31b_301", "浸水継続時間ランク"),
    ("A31b_401", "危険区域区分"),
    # 電子化ガイドラインのツールが出力する GIS データで広く見られる名前
    ("GRIDCODE", "ランク"),
    ("gridcode", "ランク"),
    # 汎用
    ("rank", "ランク"),
    ("RANK", "ランク"),
    ("depth", "浸水深"),
    ("DEPTH", "浸水深"),
]

# 除外する属性名 (ID や座標など、値ではないもの)
FIELD_DENY = {"id", "fid", "objectid", "shape_area", "shape_leng", "shape_length"}

# 細分メッシュ (共通編 表9 / 表10). 1辺の長さ, 緯度差(秒), 経度差(秒)
SUBDIVIDED_MESH = [
    ("5mメッシュ", 5.0, 0.15, 0.225),
    ("10mメッシュ", 10.0, 0.3, 0.45),
    ("12.5mメッシュ", 12.5, 0.375, 0.5625),
    ("25mメッシュ", 25.0, 0.75, 1.125),
    ("50mメッシュ", 50.0, 1.5, 2.25),
    ("100mメッシュ", 100.0, 3.0, 4.5),
]

EARTH_CIRCUMFERENCE = 156543.033928  # ZL0 における赤道上の解像度 (m/px, 256px タイル)


def tile_resolution(zoom, lat_deg):
    return EARTH_CIRCUMFERENCE * math.cos(math.radians(lat_deg)) / (2 ** zoom)


def native_zoom(mesh_m, lat_deg):
    """タイル解像度がメッシュサイズに最も近いズームレベル."""
    return int(round(math.log2(tile_resolution(0, lat_deg) / mesh_m)))


def list_inputs(src_dir, pattern=None):
    out = []
    for root, _dirs, files in os.walk(src_dir):
        for name in sorted(files):
            if not name.lower().endswith(VECTOR_EXT):
                continue
            if pattern and pattern not in name:
                continue
            out.append(os.path.join(root, name))
    return sorted(out)


def _rings(geom):
    """ジオメトリからリング (LinearRing) を平坦に取り出す."""
    name = geom.GetGeometryName()
    if name in ("POLYGON",):
        for i in range(geom.GetGeometryCount()):
            yield geom.GetGeometryRef(i)
    elif name in ("MULTIPOLYGON", "GEOMETRYCOLLECTION"):
        for i in range(geom.GetGeometryCount()):
            yield from _rings(geom.GetGeometryRef(i))
    elif name in ("LINESTRING", "LINEARRING"):
        yield geom


def detect_mesh(layer, max_features=300):
    """ポリゴン頂点の座標間隔からメッシュサイズを実測する.

    浸水想定区域のポリゴンはメッシュ境界に沿って作られるため、頂点の x 座標 /
    y 座標はメッシュ間隔の格子上に載る. 隣り合う相異なる座標値の差の最頻値が
    メッシュ 1 辺になる.

    戻り値は (経度差(度), 緯度差(度), サンプル数) または None.
    """
    xs, ys = set(), set()
    n = 0
    layer.ResetReading()
    for feat in layer:
        geom = feat.GetGeometryRef()
        if geom is None:
            continue
        for ring in _rings(geom):
            for i in range(ring.GetPointCount()):
                x, y = ring.GetPoint_2D(i)
                xs.add(round(x, 9))
                ys.add(round(y, 9))
        n += 1
        if n >= max_features:
            break
    layer.ResetReading()
    if len(xs) < 8 or len(ys) < 8:
        return None

    def mode_diff(values):
        v = sorted(values)
        diffs = Counter()
        for i in range(len(v) - 1):
            d = round(v[i + 1] - v[i], 9)
            if d > 0:
                # 浮動小数の誤差を吸収するため 1e-7 度 (約 1cm) に丸めて数える
                diffs[round(d, 7)] += 1
        if not diffs:
            return None
        return diffs.most_common(1)[0][0]

    dx, dy = mode_diff(xs), mode_diff(ys)
    if dx is None or dy is None:
        return None
    return dx, dy, n


def is_geographic(srs):
    return bool(srs is not None and srs.IsGeographic())


def transform_extent(extent, srs):
    """レイヤ範囲 (minx, maxx, miny, maxy) を EPSG:4326 の (minx, miny, maxx, maxy) にする."""
    minx, maxx, miny, maxy = extent
    if srs is None or is_geographic(srs):
        return minx, miny, maxx, maxy
    tgt = osr.SpatialReference()
    tgt.ImportFromEPSG(4326)
    tgt.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    src = srs.Clone()
    src.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    ct = osr.CoordinateTransformation(src, tgt)
    xs, ys = [], []
    for x, y in ((minx, miny), (minx, maxy), (maxx, miny), (maxx, maxy)):
        lon, lat, _ = ct.TransformPoint(x, y)
        xs.append(lon)
        ys.append(lat)
    return min(xs), min(ys), max(xs), max(ys)


def match_mesh(dx, dy, geographic, tol=0.05):
    """実測した座標間隔を細分メッシュの規定値に突き合わせる.

    地理座標系なら秒で、投影座標系ならメートルで照合する。どちらで一致しても
    返すのは細分メッシュの規定値（秒）で、ラスタライズの格子はこれに合わせる。
    元データが平面直角座標系でも、出力は標準の細分メッシュ格子に載る。
    """
    if geographic:
        dx_sec, dy_sec = dx * 3600, dy * 3600
        for name, side_m, lat_sec, lon_sec in SUBDIVIDED_MESH:
            if abs(dx_sec - lon_sec) <= lon_sec * tol and abs(dy_sec - lat_sec) <= lat_sec * tol:
                return {"name": name, "side_m": side_m, "lat_sec": lat_sec, "lon_sec": lon_sec}
        return None

    side = (dx + dy) / 2.0  # 投影座標系ではメートル。正方メッシュを想定
    for name, side_m, lat_sec, lon_sec in SUBDIVIDED_MESH:
        if abs(side - side_m) <= side_m * tol:
            return {"name": name, "side_m": side_m, "lat_sec": lat_sec, "lon_sec": lon_sec}
    return None


def pick_value_field(field_defs, values_by_field, explicit=None):
    """値属性を選ぶ. 戻り値は (属性名, 選定理由)."""
    names = [f["name"] for f in field_defs]
    if explicit and explicit != "auto":
        if explicit not in names:
            raise SystemExit(f"VALUE_FIELD='{explicit}' が入力に存在しない. 候補: {names}")
        return explicit, "設定で明示指定"

    for hint, label in FIELD_HINTS:
        if hint in names:
            return hint, f"既知の属性名 '{hint}' ({label}) に一致"

    # ヒントに当たらない場合は、数値型で値が変化する属性のうち最初のものを採る.
    for f in field_defs:
        if f["name"].lower() in FIELD_DENY:
            continue
        if f["type"] not in ("Integer", "Integer64", "Real"):
            continue
        vals = values_by_field.get(f["name"], [])
        distinct = {v for v in vals if v is not None}
        if len(distinct) >= 2:
            return f["name"], f"数値型で値が {len(distinct)} 種類ある唯一の候補として推定"

    raise SystemExit(
        "値属性を自動判定できなかった. VALUE_FIELD を設定で明示すること. "
        f"属性一覧: {[(f['name'], f['type']) for f in field_defs]}"
    )


def classify_value_kind(field_type, values, explicit=None):
    """rank か depth かを判定する. 戻り値は (種別, 理由)."""
    vals = [v for v in values if v is not None]
    distinct = sorted({v for v in vals})
    if explicit and explicit != "auto":
        return explicit, "設定で明示指定"

    if not distinct:
        raise SystemExit("値属性がすべて NULL. 入力データを確認すること")

    is_int_type = field_type in ("Integer", "Integer64")
    all_integral = all(float(v).is_integer() for v in distinct)

    # 離散ランクの条件: 整数値のみ、種類が少なく、1 から連番に近い
    if all_integral and len(distinct) <= 32 and min(distinct) >= 0 and max(distinct) <= 32:
        reason = (
            f"整数値 {len(distinct)} 種類 {[int(v) for v in distinct]} "
            f"(型: {field_type}) — 離散ランクと判定"
        )
        return "rank", reason

    if not is_int_type or not all_integral:
        return "depth", (
            f"実数値 {len(distinct)} 種類 (型: {field_type}, "
            f"範囲 {min(distinct):.3f}〜{max(distinct):.3f}) — 実数値と判定"
        )

    return "depth", (
        f"整数型だが値が {len(distinct)} 種類 (範囲 {min(distinct)}〜{max(distinct)}) と多く、"
        "ランクコードの体裁でないため実数値として扱う"
    )


def inspect_file(path, value_field=None, value_kind=None, sample_limit=200000):
    ds = ogr.Open(path)
    if ds is None:
        raise SystemExit(f"開けない: {path}")
    layer = ds.GetLayer(0)
    defn = layer.GetLayerDefn()

    fields = []
    for i in range(defn.GetFieldCount()):
        fd = defn.GetFieldDefn(i)
        fields.append({"name": fd.GetName(), "type": fd.GetTypeName()})

    srs = layer.GetSpatialRef()
    if srs is None:
        crs = {"authority": None, "code": None, "name": None}
    else:
        srs.AutoIdentifyEPSG()
        crs = {
            "authority": srs.GetAuthorityName(None),
            "code": srs.GetAuthorityCode(None),
            "name": srs.GetName(),
            "is_geographic": bool(srs.IsGeographic()),
        }

    values_by_field = {f["name"]: [] for f in fields}
    count = 0
    for feat in layer:
        for f in fields:
            if len(values_by_field[f["name"]]) < sample_limit:
                values_by_field[f["name"]].append(feat.GetField(f["name"]))
        count += 1
    layer.ResetReading()

    picked, pick_reason = pick_value_field(fields, values_by_field, value_field)
    ftype = next(f["type"] for f in fields if f["name"] == picked)
    kind, kind_reason = classify_value_kind(ftype, values_by_field[picked], value_kind)

    vals = [v for v in values_by_field[picked] if v is not None]
    hist = Counter(vals) if kind == "rank" else None

    geographic = is_geographic(srs)
    raw_extent = layer.GetExtent()  # (minx, maxx, miny, maxy) — レイヤ座標系
    minx4326, miny4326, maxx4326, maxy4326 = transform_extent(raw_extent, srs)

    mesh_raw = detect_mesh(layer)
    mesh = None
    if mesh_raw:
        dx, dy, sampled = mesh_raw
        matched = match_mesh(dx, dy, geographic)
        mesh = {
            "units": "degree" if geographic else "metre",
            "x_step": dx,
            "y_step": dy,
            "sampled_features": sampled,
            "matched": matched,
        }
        if geographic:
            mesh["lon_step_sec"] = round(dx * 3600, 6)
            mesh["lat_step_sec"] = round(dy * 3600, 6)
        # ラスタライズ格子は常に細分メッシュの規定値（秒）に載せる。
        # 規定値に一致しない場合のみ実測値をそのまま使う（地理座標系のときだけ可能）。
        if matched:
            mesh["lon_step_deg"] = matched["lon_sec"] / 3600.0
            mesh["lat_step_deg"] = matched["lat_sec"] / 3600.0
        elif geographic:
            mesh["lon_step_deg"] = dx
            mesh["lat_step_deg"] = dy

    return {
        "path": path,
        "driver": ds.GetDriver().GetName(),
        "layer": layer.GetName(),
        "geometry_type": ogr.GeometryTypeToName(layer.GetGeomType()),
        "feature_count": count,
        "crs": crs,
        "extent": {"minx": minx4326, "maxx": maxx4326, "miny": miny4326, "maxy": maxy4326},
        "extent_native": {"minx": raw_extent[0], "maxx": raw_extent[1],
                          "miny": raw_extent[2], "maxy": raw_extent[3]},
        "fields": fields,
        "value_field": picked,
        "value_field_reason": pick_reason,
        "value_field_type": ftype,
        "value_kind": kind,
        "value_kind_reason": kind_reason,
        "value_min": min(vals) if vals else None,
        "value_max": max(vals) if vals else None,
        "value_distinct": len({v for v in vals}),
        "rank_histogram": {str(int(k)): v for k, v in sorted(hist.items())} if hist else None,
        "null_count": count - len(vals),
        "mesh": mesh,
    }


def mesh_step_label(m):
    """検出した座標間隔を単位付きの文字列にする."""
    if m["units"] == "degree":
        return f"経度 {m['lon_step_sec']}″ × 緯度 {m['lat_step_sec']}″"
    return f"X {m['x_step']:g}m × Y {m['y_step']:g}m"


def build_report(result):
    L = []
    a = L.append
    a(f"# 入力検査レポート: {result['dataset_id']}")
    a("")
    a(f"- 入力ディレクトリ: `{result['src_dir']}`")
    a(f"- ファイル数: {len(result['files'])}")
    a("")
    a("## 判定結果")
    a("")
    a("| 項目 | 値 | 根拠 |")
    a("|------|-----|------|")
    d = result["decisions"]
    a(f"| 値属性 | `{d['value_field']}` | {d['value_field_reason']} |")
    a(f"| 値の種別 | `{d['value_kind']}` | {d['value_kind_reason']} |")
    a(f"| タイル種別 | `{d['tile_type']}` | {d['tile_type_reason']} |")
    a(f"| メッシュ | {d['mesh_label']} | {d['mesh_reason']} |")
    a(f"| 最大ZL | {d['max_zoom']} | {d['max_zoom_reason']} |")
    a(f"| 最小ZL | {d['min_zoom']} | 設定値 |")
    a(f"| CRS | {d['srs']} | {d['srs_reason']} |")
    a("")

    if d["value_kind"] == "depth":
        a("> 元データが浸水深の実数値なので、**パレットPNG・数値PNG のどちらでも出力できる**。")
        a("> `TILE_TYPE` で選ぶ。既定は `numeric`（実数値をそのまま保持するため）。")
        a("")
    else:
        a("> 元データが離散ランクなので、出力は**パレットPNGに限られる**。")
        a("> ランク値から実数の浸水深は復元できないため、数値PNGにする意味がない。")
        a("")

    a("## 解像度")
    a("")
    a("| ZL | タイル解像度 (m/px) | メッシュ1辺との比 |")
    a("|----|--------------------|------------------|")
    mesh_m = d.get("mesh_side_m")
    for z in range(max(0, d["max_zoom"] - 4), d["max_zoom"] + 2):
        res = tile_resolution(z, d["center_lat"])
        ratio = f"{mesh_m / res:.2f} px/メッシュ" if mesh_m else "—"
        mark = "  ← 採用" if z == d["max_zoom"] else ""
        a(f"| {z} | {res:.3f} | {ratio}{mark} |")
    a("")
    a(f"※ 計算基準緯度: {d['center_lat']:.4f}°（データ範囲の中心）")
    a("")

    a("## ファイル別")
    a("")
    for f in result["files"]:
        a(f"### `{os.path.relpath(f['path'], result['src_dir'])}`")
        a("")
        a(f"- レイヤ: `{f['layer']}` / {f['geometry_type']} / {f['feature_count']} フィーチャ")
        crs = f["crs"]
        a(f"- CRS: {crs['authority']}:{crs['code']} ({crs['name']})")
        e = f["extent"]
        a(f"- 範囲: {e['minx']:.5f}, {e['miny']:.5f} 〜 {e['maxx']:.5f}, {e['maxy']:.5f}")
        a(f"- 属性: {', '.join('%s (%s)' % (x['name'], x['type']) for x in f['fields'])}")
        a(f"- 値属性 `{f['value_field']}` ({f['value_field_type']}): "
          f"{f['value_distinct']} 種類 / NULL {f['null_count']} 件")
        if f["rank_histogram"]:
            a(f"- ランク別件数: {f['rank_histogram']}")
        else:
            a(f"- 値の範囲: {f['value_min']} 〜 {f['value_max']}")
        if f["mesh"]:
            m = f["mesh"]
            matched = m["matched"]["name"] if m["matched"] else "規定の細分メッシュに一致せず"
            a(f"- 座標間隔: {mesh_step_label(m)} → {matched}")
        else:
            a("- 座標間隔: 判定できず（頂点が少ない、または格子状でない）")
        a("")
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="ハザードマップ入力データの検査")
    ap.add_argument("src_dir")
    ap.add_argument("--dataset-id", required=True)
    ap.add_argument("--pattern", default=None, help="ファイル名に含まれる文字列で絞り込む")
    ap.add_argument("--value-field", default="auto")
    ap.add_argument("--value-kind", default="auto", choices=["auto", "rank", "depth"])
    ap.add_argument("--tile-type", default="auto", choices=["auto", "palette", "numeric"])
    ap.add_argument("--min-zoom", type=int, default=9)
    ap.add_argument("--max-zoom", default="auto")
    ap.add_argument("--max-zoom-margin", type=int, default=3,
                    help="ネイティブZLに加算する段数。既定3はメッシュ1辺が約8pxになる")
    ap.add_argument("--max-zoom-cap", type=int, default=18)
    ap.add_argument("--mesh-size", default="auto", help="'auto' または 1辺のメートル数")
    ap.add_argument("--srs", default="auto")
    ap.add_argument("-o", "--outdir", required=True)
    a = ap.parse_args(argv)

    paths = list_inputs(a.src_dir, a.pattern)
    if not paths:
        raise SystemExit(f"入力が見つからない: {a.src_dir} (pattern={a.pattern})")

    files = [inspect_file(p, a.value_field, a.value_kind) for p in paths]

    kinds = {f["value_kind"] for f in files}
    if len(kinds) > 1:
        raise SystemExit(
            f"値の種別がファイル間で混在している: {kinds}. "
            "ランクと実数値は別のデータセットとして処理すること"
        )
    value_kind = kinds.pop()
    value_field = files[0]["value_field"]
    if len({f["value_field"] for f in files}) > 1:
        raise SystemExit(
            f"値属性がファイル間で異なる: {sorted({f['value_field'] for f in files})}. "
            "VALUE_FIELD を明示するか、データセットを分けること"
        )

    # タイル種別
    if a.tile_type != "auto":
        tile_type, tile_reason = a.tile_type, "設定で明示指定"
        if value_kind == "rank" and tile_type == "numeric":
            raise SystemExit(
                "元データが離散ランクなので数値PNGにはできない "
                "(ランクから実数の浸水深は復元できない). TILE_TYPE=palette にすること"
            )
    elif value_kind == "rank":
        tile_type, tile_reason = "palette", "元データが離散ランクのため（数値PNGは選べない）"
    else:
        tile_type, tile_reason = "numeric", "元データが実数値のため（パレットPNGも選択可）"

    # CRS
    crs0 = files[0]["crs"]
    if a.srs != "auto":
        srs, srs_reason = a.srs, "設定で明示指定"
    elif crs0["code"]:
        srs = f"{crs0['authority']}:{crs0['code']}"
        srs_reason = f"入力に埋め込まれた CRS ({crs0['name']})"
    else:
        raise SystemExit("CRS を判定できない。SRC_SRS を設定で明示すること")

    # 範囲と中心緯度
    minx = min(f["extent"]["minx"] for f in files)
    maxx = max(f["extent"]["maxx"] for f in files)
    miny = min(f["extent"]["miny"] for f in files)
    maxy = max(f["extent"]["maxy"] for f in files)
    center_lat = (miny + maxy) / 2.0

    # メッシュ
    mesh_side_m, mesh_label, mesh_reason = None, "不明", "判定できず"
    lon_step = lat_step = None
    if a.mesh_size != "auto":
        mesh_side_m = float(a.mesh_size)
        mesh_label = f"{mesh_side_m:g}mメッシュ"
        mesh_reason = "設定で明示指定"
        lat_step = mesh_side_m / 5.0 * 0.15 / 3600.0
        lon_step = mesh_side_m / 5.0 * 0.225 / 3600.0
    else:
        meshes = [f["mesh"] for f in files if f["mesh"]]
        matched = [m for m in meshes if m["matched"]]
        if matched:
            m = matched[0]
            mesh_side_m = m["matched"]["side_m"]
            mesh_label = m["matched"]["name"]
            # 3次メッシュ (基準地域メッシュ) は緯度30″×経度45″. その分割数が細分メッシュの分母.
            division = int(round(30.0 / m["matched"]["lat_sec"]))
            mesh_reason = (
                f"頂点座標の間隔を実測（{mesh_step_label(m)}）"
                f" → 細分メッシュ 1/{division}（3次メッシュの{division}分割）"
            )
            lon_step, lat_step = m["lon_step_deg"], m["lat_step_deg"]
        elif meshes and meshes[0].get("lon_step_deg"):
            m = meshes[0]
            lon_step, lat_step = m["lon_step_deg"], m["lat_step_deg"]
            mesh_side_m = lat_step * 3600 / 0.15 * 5.0
            mesh_label = f"約{mesh_side_m:.1f}mメッシュ（規定値に不一致）"
            mesh_reason = (
                f"頂点座標の間隔を実測（{mesh_step_label(m)}）。"
                "細分メッシュの規定値に一致しないため MESH_SIZE の明示を推奨"
            )
        elif meshes:
            m = meshes[0]
            mesh_reason = (
                f"頂点座標の間隔を実測（{mesh_step_label(m)}）が細分メッシュの規定値に一致しない。"
                "投影座標系の入力では格子を決められないため MESH_SIZE を明示すること"
            )

    # 最大ZL
    if a.max_zoom != "auto":
        max_zoom = int(a.max_zoom)
        max_zoom_reason = "設定で明示指定"
    elif mesh_side_m:
        nz = native_zoom(mesh_side_m, center_lat)
        max_zoom = min(a.max_zoom_cap, nz + a.max_zoom_margin)
        max_zoom_reason = (
            f"ネイティブZL{nz}（タイル解像度がメッシュ {mesh_side_m:g}m に最も近いZL）"
            f"＋{a.max_zoom_margin}段。メッシュ境界を拡大時もくっきり保つため。"
            f"上限{a.max_zoom_cap}でクリップ"
        )
    else:
        raise SystemExit("メッシュサイズを判定できないため最大ZLを決められない。MAX_ZOOM を明示すること")

    result = {
        "dataset_id": a.dataset_id,
        "src_dir": a.src_dir,
        "files": files,
        "decisions": {
            "value_field": value_field,
            "value_field_reason": files[0]["value_field_reason"],
            "value_kind": value_kind,
            "value_kind_reason": files[0]["value_kind_reason"],
            "tile_type": tile_type,
            "tile_type_reason": tile_reason,
            "srs": srs,
            "srs_reason": srs_reason,
            "mesh_label": mesh_label,
            "mesh_reason": mesh_reason,
            "mesh_side_m": mesh_side_m,
            "lon_step_deg": lon_step,
            "lat_step_deg": lat_step,
            "min_zoom": a.min_zoom,
            "max_zoom": max_zoom,
            "max_zoom_reason": max_zoom_reason,
            "center_lat": center_lat,
            "bounds": [minx, miny, maxx, maxy],
        },
    }

    os.makedirs(a.outdir, exist_ok=True)
    with open(os.path.join(a.outdir, "inputs.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    with open(os.path.join(a.outdir, "report.md"), "w", encoding="utf-8") as f:
        f.write(build_report(result))

    print(build_report(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
