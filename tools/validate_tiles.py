"""生成したタイルがグリッドPNGタイル仕様に適合しているかを検証する.

パレットPNGタイルの検証:
  * 不透明ピクセルの RGB がすべて legend.json のいずれかの項目に一致すること
  * 半透明（不透明度が 0 でも 255 でもない）ピクセルが無いこと

    縮小方法に average / bilinear を使うと、下位ZLで凡例に無い中間色が生まれ、
    ピクセル値から凡例項目を引けなくなる。この検証はそれを検出するためにある。

数値PNGタイルの検証:
  * 復号した値が指定した範囲に収まること
  * 半透明ピクセルが無いこと

全ZLを走査するので、下位ZLの縮小で仕様を外していないかまで確認できる。
"""

import argparse
import json
import os
import sys
from collections import Counter

import numpy as np
from PIL import Image


def iter_tiles(tiles_dir, ext="png"):
    for root, _dirs, files in os.walk(tiles_dir):
        for name in sorted(files):
            if name.lower().endswith("." + ext):
                yield os.path.join(root, name)


def zoom_of(path, tiles_dir):
    rel = os.path.relpath(path, tiles_dir)
    head = rel.split(os.sep)[0]
    return int(head) if head.isdigit() else -1


def load_rgba(path):
    with Image.open(path) as im:
        return np.asarray(im.convert("RGBA"))


def validate_palette(tiles_dir, legend_path, ext="png", max_report=12):
    with open(legend_path, encoding="utf-8") as f:
        legend = json.load(f)
    items = legend["items"] if isinstance(legend, dict) else legend
    allowed = {(i["r"], i["g"], i["b"]) for i in items}

    bad_colors = Counter()
    bad_by_zoom = Counter()
    semi_transparent = 0
    seen = Counter()
    n_tiles = 0

    for path in iter_tiles(tiles_dir, ext):
        n_tiles += 1
        a = load_rgba(path)
        alpha = a[..., 3]
        semi = np.count_nonzero((alpha != 0) & (alpha != 255))
        semi_transparent += int(semi)

        opaque = alpha == 255
        if not opaque.any():
            continue
        rgb = a[..., :3][opaque]
        uniq, counts = np.unique(rgb.reshape(-1, 3), axis=0, return_counts=True)
        for c, n in zip(uniq, counts):
            key = (int(c[0]), int(c[1]), int(c[2]))
            seen[key] += int(n)
            if key not in allowed:
                bad_colors[key] += int(n)
                bad_by_zoom[zoom_of(path, tiles_dir)] += int(n)

    print(f"検証対象: {n_tiles} タイル ({tiles_dir})")
    print(f"凡例の色数: {len(allowed)} / 実際に現れた色数: {len(seen)}")
    for c, n in sorted(seen.items(), key=lambda kv: -kv[1]):
        mark = "OK " if c in allowed else "NG "
        title = next((i["title"] for i in items if (i["r"], i["g"], i["b"]) == c), "—")
        print(f"  {mark} rgb{c} {n:>10,} px  {title}")

    ok = True
    if bad_colors:
        ok = False
        print(f"\nNG: 凡例に無い色が {len(bad_colors)} 種類 / "
              f"{sum(bad_colors.values()):,} px 出現した")
        print(f"    ZL別: {dict(sorted(bad_by_zoom.items()))}")
        for c, n in list(sorted(bad_colors.items(), key=lambda kv: -kv[1]))[:max_report]:
            print(f"      rgb{c}  {n:,} px")
        print("    縮小方法が near 以外になっていないか確認すること")
    if semi_transparent:
        ok = False
        print(f"\nNG: 半透明ピクセルが {semi_transparent:,} px ある"
              "（仕様は不透明度 0 か最大値のみを推奨）")

    print("\n判定:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def validate_numeric(tiles_dir, tilejson_path, ext="png"):
    with open(tilejson_path, encoding="utf-8") as f:
        tj = json.load(f)
    num = tj["datapng"]["numeric"]
    f_, o_ = float(num["factor"]), float(num["offset"])
    vmin_exp = num.get("value_min")
    vmax_exp = num.get("value_max")

    n_tiles = 0
    semi_transparent = 0
    vmin = vmax = None
    out_of_range = 0

    for path in iter_tiles(tiles_dir, ext):
        n_tiles += 1
        a = load_rgba(path).astype(np.int64)
        alpha = a[..., 3]
        semi_transparent += int(np.count_nonzero((alpha != 0) & (alpha != 255)))
        valid = alpha == 255
        if not valid.any():
            continue
        r, g, b = a[..., 0], a[..., 1], a[..., 2]
        rp = np.where(r < 2 ** 7, r, r - 2 ** 8)  # 仕様: r' = r or r - 2^8
        v = f_ * (2 ** 16 * rp + 2 ** 8 * g + b) + o_
        vv = v[valid]
        lo, hi = float(vv.min()), float(vv.max())
        vmin = lo if vmin is None else min(vmin, lo)
        vmax = hi if vmax is None else max(vmax, hi)
        if vmin_exp is not None:
            tol = abs(f_)
            out_of_range += int(np.count_nonzero(
                (vv < vmin_exp - tol) | (vv > vmax_exp + tol)))

    print(f"検証対象: {n_tiles} タイル ({tiles_dir})")
    print(f"係数 f={f_} / オフセット o={o_}")
    print(f"復号した値域: {vmin} 〜 {vmax}")
    if vmin_exp is not None:
        print(f"元ラスターの値域: {vmin_exp} 〜 {vmax_exp}")

    ok = True
    if out_of_range:
        ok = False
        print(f"\nNG: 元ラスターの値域から外れた画素が {out_of_range:,} px ある"
              "（縮小方法が near 以外になっていないか確認すること）")
    if semi_transparent:
        ok = False
        print(f"\nNG: 半透明ピクセルが {semi_transparent:,} px ある")

    print("\n判定:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="生成タイルの仕様適合検証")
    ap.add_argument("tiles_dir")
    ap.add_argument("--ext", default="png")
    a = ap.parse_args(argv)

    legend = os.path.join(a.tiles_dir, "legend.json")
    tilejson = os.path.join(a.tiles_dir, "tiles.json")
    if os.path.exists(legend):
        return validate_palette(a.tiles_dir, legend, a.ext)
    if os.path.exists(tilejson):
        return validate_numeric(a.tiles_dir, tilejson, a.ext)
    raise SystemExit(f"{a.tiles_dir} に legend.json も tiles.json も無い")


if __name__ == "__main__":
    sys.exit(main())
