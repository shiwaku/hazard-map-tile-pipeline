"""ランク定義ファイル (colors/*.json) の読み込みと派生物の生成.

派生物は 3 種類ある.

  * gdaldem color-relief 用のカラーマップテキスト
  * 産総研 JSON凡例フォーマット (パレットPNGタイルに添える legend.json)
  * 浸水深の実数値 → ランク の分類しきい値

標準ライブラリのみを使う.
"""

import json
import os


class RankDef:
    def __init__(self, obj, path=None):
        self.path = path
        self.id = obj["id"]
        self.title = obj.get("title", self.id)
        self.unit = obj.get("unit", "")
        self.nodata_rank = obj.get("nodata_rank", 0)
        self.source = obj.get("source", [])
        self.note = obj.get("note")
        self.ranks = sorted(obj["ranks"], key=lambda r: r["rank"])
        self._validate()

    def _validate(self):
        seen_rank = set()
        seen_rgb = set()
        for r in self.ranks:
            if r["rank"] in seen_rank:
                raise ValueError(f"{self.id}: rank {r['rank']} が重複している")
            if r["rank"] == self.nodata_rank:
                raise ValueError(f"{self.id}: rank {r['rank']} が nodata_rank と衝突している")
            seen_rank.add(r["rank"])
            rgb = tuple(r["rgb"])
            if len(rgb) != 3 or any(not (0 <= c <= 255) for c in rgb):
                raise ValueError(f"{self.id}: rank {r['rank']} の rgb が不正: {rgb}")
            # 産総研パレットPNGタイル仕様は「r,g,b の組み合わせがファイル内で一意」を要求する.
            # 色が重複するとピクセル値から凡例項目を一意に引けなくなる.
            if rgb in seen_rgb:
                raise ValueError(f"{self.id}: rgb {rgb} が複数のランクで使われている")
            seen_rgb.add(rgb)

    @property
    def max_rank(self):
        return max(r["rank"] for r in self.ranks)

    def color_relief_text(self):
        """gdaldem color-relief -exact_color_entry 用のカラーマップ.

        nodata_rank は alpha=0 (透明) にする. 浸水なしのメッシュを背景地図に
        重ねられるようにするため.
        """
        # gdaldem は数値エントリが単調非減少で並んでいることを要求する。
        # `nv` 行は band の NoData 値に展開されるため、ランク値より後ろに置くと
        # 「単調非減少でない」と怒られる。このパイプラインではラスターの NoData を
        # 常に nodata_rank（既定 0）にしているので、`nv` は使わず数値行で表す。
        lines = [f"# {self.title} ({self.id})", f"# 生成元: {self.path or self.id}"]
        lines.append(f"{self.nodata_rank} 0 0 0 0  # 該当なし（透明）")
        for r in self.ranks:
            r_, g_, b_ = r["rgb"]
            lines.append(f"{r['rank']} {r_} {g_} {b_} 255  # {r['title']}")
        return "\n".join(lines) + "\n"

    def legend_json(self):
        """産総研 JSON凡例フォーマット (凡例オブジェクト形式).

        value は 2^16 r + 2^8 g + b を 6 桁の 16 進数文字列で持つ.
        """
        items = []
        for r in self.ranks:
            r_, g_, b_ = r["rgb"]
            item = {
                "r": r_,
                "g": g_,
                "b": b_,
                "title": r["title"],
                "value": "%06X" % ((r_ << 16) + (g_ << 8) + b_),
            }
            if r.get("description"):
                item["description"] = r["description"]
            item["rank"] = r["rank"]
            if r.get("min") is not None:
                item["min"] = r["min"]
            if r.get("max") is not None:
                item["max"] = r["max"]
            items.append(item)
        legend = {"title": self.title, "items": items}
        if self.unit:
            legend["unit"] = self.unit
        if self.source:
            legend["source"] = self.source
        return legend

    def thresholds(self):
        """実数値 → ランク の分類用. [(下限, ランク), ...] を下限の昇順で返す."""
        out = []
        for r in self.ranks:
            lo = r.get("min")
            if lo is None:
                continue
            out.append((float(lo), r["rank"]))
        out.sort()
        return out

    def classify_sql(self, field, out_field="rank"):
        """実数値属性 → ランク整数 の CASE WHEN 式を組み立てる.

        しきい値は定義ファイルの min/max から導出するので、定義を直せば SQL も追従する.
        """
        parts = []
        for r in self.ranks:
            lo, hi = r.get("min"), r.get("max")
            conds = []
            if lo is not None:
                conds.append(f'"{field}" >= {lo}')
            if hi is not None:
                conds.append(f'"{field}" < {hi}')
            if not conds:
                continue
            parts.append(f"WHEN {' AND '.join(conds)} THEN {r['rank']}")
        body = "\n      ".join(parts)
        return f"CASE\n      {body}\n      ELSE {self.nodata_rank}\n    END AS {out_field}"


def load(path):
    with open(path, encoding="utf-8") as f:
        return RankDef(json.load(f), path=os.path.basename(path))


def _main(argv):
    import argparse

    ap = argparse.ArgumentParser(description="ランク定義から派生物を生成する")
    ap.add_argument("rankdef")
    ap.add_argument("--emit", choices=["colormap", "legend", "sql"], default="colormap")
    ap.add_argument("--field", default="depth", help="--emit sql のときの入力属性名")
    ap.add_argument("-o", "--output")
    a = ap.parse_args(argv)

    rd = load(a.rankdef)
    if a.emit == "colormap":
        text = rd.color_relief_text()
    elif a.emit == "legend":
        text = json.dumps(rd.legend_json(), ensure_ascii=False, indent=2) + "\n"
    else:
        text = rd.classify_sql(a.field) + "\n"

    if a.output:
        with open(a.output, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        print(text, end="")


if __name__ == "__main__":
    import sys

    _main(sys.argv[1:])
