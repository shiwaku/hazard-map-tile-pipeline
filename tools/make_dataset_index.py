"""output/ を走査してビューワ用のデータセット一覧 datasets.json を作る.

ビューワは 1 データセット = 1 レイヤーとして扱う。tiles/tiles.json があるディレクトリだけを
データセットとみなすので、ビューワ本体（index.html / assets / icons）を同じ場所に置いても
混ざらない。

表示名は tiles.json の name（無ければディレクトリ名）を使う。

標準ライブラリのみを使う。
"""

import argparse
import json
import os
import sys


def scan(output_dir):
    datasets = []
    if not os.path.isdir(output_dir):
        return datasets
    for name in sorted(os.listdir(output_dir)):
        if name.startswith((".", "_")):
            continue
        tj_path = os.path.join(output_dir, name, "tiles", "tiles.json")
        if not os.path.isfile(tj_path):
            continue
        title = name
        try:
            with open(tj_path, encoding="utf-8") as f:
                title = json.load(f).get("name") or name
        except (OSError, json.JSONDecodeError) as e:
            print(f"警告: {tj_path} を読めない（{e}）。ディレクトリ名を表示名にする", file=sys.stderr)
        datasets.append({"id": name, "name": title, "tilejson": f"{name}/tiles/tiles.json"})
    return datasets


def main(argv=None):
    ap = argparse.ArgumentParser(description="ビューワ用データセット一覧の生成")
    ap.add_argument("output_dir", help="パイプラインの出力ディレクトリ（通常 output/）")
    ap.add_argument("-o", "--output", help="書き出し先（既定は <output_dir>/datasets.json）")
    a = ap.parse_args(argv)

    datasets = scan(a.output_dir)
    dst = a.output or os.path.join(a.output_dir, "datasets.json")
    with open(dst, "w", encoding="utf-8") as f:
        json.dump({"datasets": datasets}, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"datasets.json: {dst}（{len(datasets)} 件）")
    for d in datasets:
        print(f"  - {d['id']}")
    if not datasets:
        print("  タイルセットが無い。先に run_pipeline.sh を実行すること", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
