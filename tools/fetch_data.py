"""サンプルデータの ZIP を取得して展開する.

日本の公開データの ZIP はファイル名が CP932 のことが多く、`unzip` や
`zipfile.extractall` にそのまま任せると文字化けする。エントリごとに
汎用フラグ bit 11（UTF-8 フラグ）を見て、立っていなければ CP437 → CP932 で
読み直す。1 つの ZIP の中で UTF-8 と CP932 が混在することもあるので、
ZIP 全体ではなくエントリ単位で判定する（実データで遭遇した）。

標準ライブラリのみを使う。
"""

import argparse
import os
import shutil
import sys
import urllib.request
import zipfile


def decode_name(info):
    name = info.filename
    if not (info.flag_bits & 0x800):  # UTF-8 フラグが立っていない
        for enc in ("cp932", "cp437"):
            try:
                return name.encode("cp437").decode(enc)
            except (UnicodeEncodeError, UnicodeDecodeError):
                continue
    return name


def download(url, dst, force=False):
    if os.path.exists(dst) and not force:
        print(f"取得済み: {dst} ({os.path.getsize(dst):,} バイト)")
        return dst
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    print(f"取得: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "hazard-map-tile-pipeline"})
    tmp = dst + ".part"
    with urllib.request.urlopen(req) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f)
    os.replace(tmp, dst)
    print(f"  → {dst} ({os.path.getsize(dst):,} バイト)")
    return dst


def extract(zip_path, outdir, contains=None, flatten=False):
    n = 0
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            name = decode_name(info).replace("\\", "/")
            if info.is_dir():
                continue
            if contains and contains not in name:
                continue
            rel = os.path.basename(name) if flatten else name
            dst = os.path.join(outdir, rel)
            os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
            with z.open(info) as src, open(dst, "wb") as out:
                shutil.copyfileobj(src, out)
            n += 1
    print(f"展開: {n} ファイル → {outdir}")
    if n == 0 and contains:
        print(f"  警告: '{contains}' に一致するエントリが無かった", file=sys.stderr)
    return n


def main(argv=None):
    ap = argparse.ArgumentParser(description="サンプルデータの取得と展開")
    ap.add_argument("url")
    ap.add_argument("outdir")
    ap.add_argument("--cache-dir", default=None, help="ZIP の保存先（既定は outdir/../_zip）")
    ap.add_argument("--contains", default=None, help="この文字列を含むエントリだけ展開する")
    ap.add_argument("--flatten", action="store_true", help="ディレクトリ階層を潰して平置きする")
    ap.add_argument("--force", action="store_true", help="キャッシュを無視して再取得する")
    a = ap.parse_args(argv)

    cache = a.cache_dir or os.path.join(os.path.dirname(os.path.abspath(a.outdir)), "_zip")
    zip_path = os.path.join(cache, os.path.basename(a.url))
    download(a.url, zip_path, force=a.force)
    os.makedirs(a.outdir, exist_ok=True)
    extract(zip_path, a.outdir, contains=a.contains, flatten=a.flatten)
    return 0


if __name__ == "__main__":
    sys.exit(main())
