"""実数値ラスターを数値PNGタイル仕様の RGBA にエンコードする.

産総研「グリッドPNGタイル 仕様」(0.1, 2020-12-15) 数値PNGタイルの規定:

    r' = r            (r <  2^7)
    r' = r - 2^8      (r >= 2^7)
    v  = f (2^16 r' + 2^8 g + b) + o

つまり R,G,B を並べた 24 ビット符号付き整数 n に対して v = f*n + o.
逆に n = round((v - o) / f) を求め、その 2 の補数表現の各バイトを R,G,B に置く.

無効値は「完全に透明なピクセル(不透明度0)」で表す(同仕様). そのため出力は
4 バンド (RGBA) の Byte ラスターになる.

係数 f とオフセット o は配信側が決める定数で、タイルと一緒に必ず公開する必要がある
(受け取り側はこの 2 つを知らないと値を復元できない). 05_make_metadata.sh が
tiles.json に書き出す.
"""

import argparse
import sys

import numpy as np
from osgeo import gdal

gdal.UseExceptions()

INT24_MIN = -(2 ** 23)
INT24_MAX = 2 ** 23 - 1


def encode(src_path, dst_path, factor, offset, src_nodata=None, block=512,
           creation_options=("COMPRESS=DEFLATE", "PREDICTOR=2", "TILED=YES")):
    src = gdal.Open(src_path)
    if src is None:
        raise SystemExit(f"開けない: {src_path}")
    if src.RasterCount != 1:
        raise SystemExit(f"入力は 1 バンドである必要がある (実際: {src.RasterCount})")

    band = src.GetRasterBand(1)
    nodata = src_nodata if src_nodata is not None else band.GetNoDataValue()

    drv = gdal.GetDriverByName("GTiff")
    dst = drv.Create(dst_path, src.RasterXSize, src.RasterYSize, 4,
                     gdal.GDT_Byte, options=list(creation_options))
    dst.SetGeoTransform(src.GetGeoTransform())
    dst.SetProjection(src.GetProjection())
    for i, ci in enumerate(
        [gdal.GCI_RedBand, gdal.GCI_GreenBand, gdal.GCI_BlueBand, gdal.GCI_AlphaBand], start=1
    ):
        dst.GetRasterBand(i).SetColorInterpretation(ci)

    clipped_lo = clipped_hi = 0
    vmin = vmax = None

    for y0 in range(0, src.RasterYSize, block):
        rows = min(block, src.RasterYSize - y0)
        for x0 in range(0, src.RasterXSize, block):
            cols = min(block, src.RasterXSize - x0)
            v = band.ReadAsArray(x0, y0, cols, rows).astype(np.float64)

            valid = np.isfinite(v)
            if nodata is not None:
                valid &= v != nodata

            if valid.any():
                bmin, bmax = float(v[valid].min()), float(v[valid].max())
                vmin = bmin if vmin is None else min(vmin, bmin)
                vmax = bmax if vmax is None else max(vmax, bmax)

            with np.errstate(invalid="ignore"):
                nf = (v - offset) / factor
            n = np.where(valid, np.rint(nf), 0).astype(np.int64)

            clipped_lo += int(np.count_nonzero(valid & (n < INT24_MIN)))
            clipped_hi += int(np.count_nonzero(valid & (n > INT24_MAX)))
            n = np.clip(n, INT24_MIN, INT24_MAX)

            u = (n & 0xFFFFFF).astype(np.uint32)  # 2 の補数 24 ビット
            r = ((u >> 16) & 0xFF).astype(np.uint8)
            g = ((u >> 8) & 0xFF).astype(np.uint8)
            b = (u & 0xFF).astype(np.uint8)
            a = np.where(valid, 255, 0).astype(np.uint8)

            # 無効ピクセルは RGB も 0 にしておく (透明なので表示には影響しないが、
            # 圧縮が効きやすくなり、誤って不透明扱いされたときも 0 に落ちる)
            r = np.where(valid, r, 0)
            g = np.where(valid, g, 0)
            b = np.where(valid, b, 0)

            for i, arr in enumerate([r, g, b, a], start=1):
                dst.GetRasterBand(i).WriteArray(arr, x0, y0)

    dst.FlushCache()
    dst = None

    if clipped_lo or clipped_hi:
        print(
            f"警告: 24ビット符号付き整数の範囲を超えた画素があり丸めた "
            f"(下限超過 {clipped_lo}px / 上限超過 {clipped_hi}px). "
            f"係数 f={factor} が小さすぎる可能性がある",
            file=sys.stderr,
        )

    return {
        "factor": factor,
        "offset": offset,
        "value_min": vmin,
        "value_max": vmax,
        "encoded_min": None if vmin is None else int(round((vmin - offset) / factor)),
        "encoded_max": None if vmax is None else int(round((vmax - offset) / factor)),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="実数値ラスター → 数値PNGタイル用 RGBA")
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--factor", type=float, default=0.01,
                    help="係数 f。既定 0.01 は cm 単位で保持する意味になる（地理院標高タイルと同じ）")
    ap.add_argument("--offset", type=float, default=0.0, help="オフセット o")
    ap.add_argument("--src-nodata", type=float, default=None)
    a = ap.parse_args(argv)

    info = encode(a.src, a.dst, a.factor, a.offset, a.src_nodata)
    print(
        f"エンコード完了: f={info['factor']} o={info['offset']} "
        f"値域 {info['value_min']}〜{info['value_max']} "
        f"→ 整数 {info['encoded_min']}〜{info['encoded_max']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
