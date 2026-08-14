# hazard-map-tile-pipeline

ハザードマップ（浸水想定区域）のシェープファイル・GeoJSON から、
産総研「グリッドPNGタイル」仕様に適合する XYZ ラスタータイルを生成するパイプライン。

**検査 → 前処理 → ラスタライズ → 符号化 → タイル生成 → メタデータ** までを設定ファイル 1 枚で通す。

- 入力の属性を検査し、**離散ランクか実数値かを判定して出力形式を決める**
- 出力は **パレットPNGタイル**（凡例 JSON 付き）または **数値PNGタイル**（係数・オフセット付き）
- メッシュサイズを頂点座標の間隔から実測し、**最大ズームレベルを自動決定**する
- 生成したタイルが仕様に適合しているかを検証するツールを同梱する

**デモ: https://shiwaku.github.io/hazard-map-tile-pipeline/**
（同梱サンプル 4 構成。`main` に push するたびに CI がパイプラインを通して作り直している）

## 出力形式は入力データの性質で決まる

これがこのパイプラインの中心にある考え方。災害種別（洪水・津波・高潮）ではなく、
**元データが浸水深をどう持っているか**で出力形式が決まる。

| 元データ | パレットPNG | 数値PNG |
|----------|:----------:|:-------:|
| 離散ランク（整数コード） | ○ | **×** |
| 浸水深の実数値（m） | ○ | ○ |

制約は片側だけ。

- **ランクからは実数値を復元できない**ので、ランクデータを数値PNGにしても意味がない。
  `TILE_TYPE="numeric"` を指定してもエラーで止まる。
- **実数値はしきい値でランクに分類できる**ので、どちらの出力も選べる。
  `TILE_TYPE` で選ぶ（`auto` の既定は `numeric`＝実数値をそのまま保持する側）。

判定は `01_inspect.sh` が属性の型と値の分布から行い、根拠を
`output/<id>/inspect/report.md` に残す。設定で上書きできる。

> **公開データの実情**: 洪水浸水想定区域の公開データは、国土数値情報も都道府県公開分も
> 浸水深をランクコードで持っており、実数値の面データは公開されていない
> （実数値の原典は浸水想定区域図データ電子化ガイドラインの `MAXALL.CSV` だが、
> これは河川管理者から個別提供されるもの）。そのため同梱サンプルでは、
> 実数値の経路を津波データで検証している。パイプラインは災害種別を区別しない。

## 必要なもの

| ツール | 用途 | 確認 |
|--------|------|------|
| GDAL 3.6+（`ogr2ogr` / `gdal_rasterize` / `gdaldem` / `gdal2tiles.py`） | 全ステップ | `gdal2tiles.py --help` |
| Python 3.9+ ＋ GDAL バインディング（`osgeo`） | 検査・符号化 | `python3 -c "from osgeo import gdal"` |
| numpy | 数値PNGの符号化 | `python3 -c "import numpy"` |
| Pillow | タイル検証（`validate_tiles.py`）のみ | `python3 -c "import PIL"` |
| bash 4+ | スクリプト実行 | — |
| Node.js 18+ ＋ npm | ビューワ（`viewer/`）のビルドのみ | `node -v` |

タイル生成だけならブラウザ用のビューワは不要で、Node.js も要らない。

## 使い方

```bash
# 1. 設定を作る
cp config/ksj-flood-ujigawa.conf.example config/ksj-flood-ujigawa.conf

# 2. サンプルデータを取得する（自分のデータを使うなら data/<id>/ に置いて省略）
./scripts/00_fetch_data.sh config/ksj-flood-ujigawa.conf

# 3. まず検査だけ実行して判定内容を確認する
./scripts/01_inspect.sh config/ksj-flood-ujigawa.conf
#    → output/ksj-flood-ujigawa/inspect/report.md

# 4. 通しで実行
./scripts/run_pipeline.sh config/ksj-flood-ujigawa.conf

# 5. 仕様適合を検証
python3 tools/validate_tiles.py output/ksj-flood-ujigawa/tiles

# 6. ローカルで確認（初回だけビューワのビルドが必要）
cd viewer && npm ci && npm run build && cd ..
./scripts/serve.sh                                  # http://localhost:8080/
```

`serve.sh` は `output/` 以下の**全タイルセット**を一覧に出すので、設定ファイルは取らない。
ビューワ開発中は `cd viewer && npm run dev`（http://localhost:8000/）のほうが速い。
`output/` を `/data` として直接読むのでコピーも要らず、パイプラインを回してリロードすれば
新しいタイルセットが一覧に出る。

途中からやり直す場合:

```bash
./scripts/run_pipeline.sh config/sample.conf --from 3          # ラスタライズ以降
./scripts/run_pipeline.sh config/sample.conf --from 2 --to 4
```

## 公開（GitHub Pages）

https://shiwaku.github.io/hazard-map-tile-pipeline/

`.github/workflows/pages.yml` が `main` への push のたびに、同梱サンプル 4 構成で
Step 0〜5 を通し、生成物を Pages にデプロイする。**タイルはリポジトリに置かない。**
`output/` はテストデータであって配布物ではないので、毎回 CI で作り直している。
デモの公開とパイプラインの end-to-end 確認を 1 本で兼ねる形になっていて、
`validate_tiles.py` が落ちればデプロイもされない。

公開されるのはタイルとビューワだけで、`inspect/`（検査レポート）と
`work/`（中間ラスター）は含めない。この切り分けは `build_site.sh` がやる:

```bash
cd viewer && npm ci && npm run build && cd ..
./scripts/build_site.sh              # → _site/（公開されるのと同じ中身）
```

`serve.sh` がローカル確認用に `output/` 直下へビューワを置く（中間ファイルもそのまま
残る）のに対して、`build_site.sh` は公開物だけを別ディレクトリに組み立てる。
Pages はプロジェクトページなので `/hazard-map-tile-pipeline/` 配下に載るが、
ビューワは `base: './'` とタイルの相対URLで動くため、サブパスでもそのまま動く。

CI は国土数値情報（`nlftp.mlit.go.jp`）と福島県サイトから ZIP を取りに行く。
**唯一の外部依存はここで、配信元の URL が変わればビルドが落ちる。**
落ちた場合はデプロイされないだけで、前回公開分はそのまま残る。

## パイプラインの構成

```
（Step 0）ZIP を取得して data/<id>/ に展開           00_fetch_data.sh（任意）
  │
data/<id>/*.shp | *.geojson
  │
  ├─ Step 1  01_inspect.sh     検査（属性の型・値の分布・CRS・メッシュ間隔）
  │                            → 値属性・値の種別・タイル種別・メッシュ・最大ZL を決定
  │                            出力: output/<id>/inspect/{inputs.json,report.md}
  │
  ├─ Step 2  02_prepare.sh     前処理（EPSG:4326 化・ジオメトリ妥当化・値の正規化）
  │                            実数値→パレットの場合はここでランクに分類する
  │                            出力: output/<id>/work/prepared.gpkg（列 `_value`）
  │
  ├─ Step 3  03_rasterize.sh   ラスタライズ（gdal_rasterize）＋ nearest で2倍拡大
  │                            出力: output/<id>/work/value_hires.tif
  │
  ├─ Step 4  04_make_tiles.sh  palette: gdaldem color-relief → gdal2tiles
  │                            numeric: RGBA 符号化 → gdal2tiles
  │                            出力: output/<id>/tiles/{z}/{x}/{y}.png
  │
  └─ Step 5  05_make_metadata.sh  tiles.json（TileJSON）＋ legend.json（JSON凡例）
                                  出力: output/<id>/tiles/{tiles.json,legend.json}

（ビューワ）serve.sh が output/datasets.json を作り、viewer/dist を output/ に配置
```

各ステップは独立して実行でき、`config/<name>.conf` を第 1 引数に取る。
Step 2 以降は `inputs.json` の判定結果だけを読み、判定をやり直さない
（根拠とレポートが食い違うと追えなくなるため）。

## 同梱サンプルでの実行実績

4 つとも公開データで、`auto` 任せ（`TILE_TYPE` を除く）で通ることを確認している。
4 つは「**入力データの値の性質**」×「**出力するタイル形式**」の組み合わせを
ひと通り見せる構成になっていて、2 つずつのペアがそれぞれ別のことを示している。

| | `ksj-flood-ujigawa` | `ksj-duration-ujigawa` | `fukushima-depth-numeric` | `fukushima-depth-palette` |
|---|---|---|---|---|
| 元データ | 国土数値情報 A31a 2025年度 | 同左（**同じZIP**） | 福島県 津波浸水想定 | 同左（**同じ入力ファイル**） |
| 対象 | 高知県 宇治川 浸水深（想定最大規模） | 高知県 宇治川 浸水継続時間 | 地域海岸9 最大浸水深 | 同左 |
| 値属性 | `A31a_205`（Integer） | `A31a_305`（Integer） | `z`（Real） | `z`（Real） |
| 値の種別 | rank（1〜4 の4種類） | rank（1〜3 の3種類） | depth（0.01〜14.26 m） | depth |
| タイル種別 | palette（**強制**） | palette（**強制**） | numeric | palette（明示指定） |
| ランク定義 | `water-depth-6rank` | `flood-duration-7rank` | —（凡例を持たない） | `water-depth-8rank` |
| CRS | EPSG:6668（地理座標系） | 同左 | EPSG:2451（平面直角IX系） | 同左 |
| メッシュ | 5m（経度0.225″×緯度0.15″） | 10m（経度0.45″×緯度0.3″） | 10m（X10m×Y10m） | 同左 |
| 最大ZL | 18（ネイティブ15＋3） | 17（ネイティブ14＋3） | 17（ネイティブ14＋3） | 17 |
| フィーチャ数 | 1,547 | 1,125 | 9,274 | 9,274 |
| 元データ容量 | 1.5 MB | 同左 | 1.5 MB | 1.5 MB |
| 生成タイル | 328 枚 / 1.1 MB | 112 枚 / 368 KB | 117 枚 / 412 KB | 117 枚 / 364 KB |
| 所要時間 | 7 秒 | 3 秒 | 4 秒 | 4 秒 |
| 検証 | PASS（凡例の6色中4色が出現） | PASS（7色中3色が出現） | PASS（復号値域 0.01〜14.26） | PASS（8色中7色が出現） |

### `fukushima-depth-*` — 同じ入力から別形式を出す

設定の差は `TILE_TYPE` と `RANK_DEF` の 2 行だけ。**実数値の入力なら数値PNGも
パレットPNGも選べる**ことの実例になっている。同じ画素をクリックすると、
numeric は `6.59 m`、palette は `5.0〜10.0m未満` を返す。

パレットPNGにすると**実数は復元できなくなる**（6.59 という値は色に潰れる）。
値そのものを配りたいなら numeric、地図として読ませたいなら palette を選ぶ。
なお numeric は色に意味が無いので、そのまま重ねても地図としては読めない
（画面上は青一色に見える）。

### `ksj-*` — 同じZIPの別属性は別データセットにする

どちらも離散ランクなので出力はパレットPNG一択で、`TILE_TYPE="numeric"` と
書けばエラーで止まる。浸水深（`A31a_205`、単位 m）と浸水継続時間
（`A31a_305`、単位 h）は意味も凡例も別物なので、1 データセットにまとめてはいけない。

同じ河川・同じZIPでも**メッシュは 5m と 10m で違う**。Step 1 が頂点間隔から
それぞれを実測するので、最大ZLも 18 と 17 に分かれる。案件ごとに手で
指定しなくても揃うことの実例でもある。

## 案件差の自動吸収

案件ごとに違う値は、設定に `auto` と書けば実データから判定する。
判定根拠は必ず `output/<id>/inspect/report.md` に残るので、鵜呑みにせず確認してから流すこと。

| 設定 | `auto` の判定内容 |
|------|-----------------|
| `SRC_SRS="auto"` | 入力に埋め込まれた CRS を使う。無ければエラーで止める（推測しない） |
| `VALUE_FIELD="auto"` | 既知の属性名（`A31a_205` 等、`tools/inspect_inputs.py` の `FIELD_HINTS`）に一致するものを優先。無ければ値が変化する数値型属性を推定 |
| `VALUE_KIND="auto"` | 整数値で 32 種類以下・値域 0〜32 ならランク、それ以外は実数値 |
| `TILE_TYPE="auto"` | rank → palette、depth → numeric |
| `MESH_SIZE="auto"` | ポリゴン頂点の座標間隔の最頻値を実測し、細分メッシュの規定値に突き合わせる |
| `MAX_ZOOM="auto"` | ネイティブZL ＋ `MAX_ZOOM_MARGIN`（既定3）、`MAX_ZOOM_CAP`（既定18）でクリップ |

ファイル間で値属性や値の種別が食い違う場合はエラーで止める。国土数値情報の
都道府県 ZIP には想定最大規模（`A31a_205`）・浸水継続時間（`A31a_305`）・
家屋倒壊等氾濫想定区域（`A31a_405`）が同居しており、
これらは意味も凡例も別物なので 1 データセットにまとめてはいけない。

## 設計上の判断

### 縮小方法は `near` から変えない

これは「好みの問題」ではなく、**どちらの仕様も画素値に意味を持たせている**ことの帰結。

- パレットPNG: ピクセル値（RGB）から凡例項目を引く。凡例に無い色が出たら値を引けない。
- 数値PNG: RGB を 24 ビット整数として解釈する。バイト境界をまたぐ非線形な符号化なので、
  チャンネルごとの平均には意味がない。

`near` はどのバンドも同じ元ピクセルを採るため、色の組み合わせが崩れない。
`average` / `bilinear` はチャンネルを独立に混ぜるので中間色が生まれる。

同梱サンプルで `TILE_RESAMPLING="average"` にして実測した結果:

| | 出現した色 | 凡例外の画素 |
|---|---|---|
| `near`（既定） | 4 色（すべて凡例内） | 0 px |
| `average` | 351 色 | **163,963 px / 347 色** |

凡例外の画素は ZL9 から ZL18 まで全レベルに現れた（ZL18 で 81,781 px）。
`gdal2tiles` は最大ZLのタイルを作るときにも `-r` を使うため、
下位ZLだけの問題ではない。`tools/validate_tiles.py` はこれを検出する。

`mode` は「最頻値」なので一見よさそうだが、GDAL はバンドごとに独立して計算するため、
R は色Aから・G は色Bから、という組み合わせが生まれうる。使わない。

### ラスタライズ後に nearest で 2 倍にする

メッシュ解像度のままタイル化すると、最大ZLで 1 メッシュが数ピクセルにしかならず、
それ以上ズームしたときにブラウザ側の拡大補間でメッシュ境界がぼやける。
先に nearest で細かくしておくと境界が保たれる。`UPSCALE` で変えられる。

### 最大ズームレベルの決め方

タイル解像度がメッシュ 1 辺に最も近い ZL を**ネイティブZL**とする。
ZL *z* のタイル解像度（256px タイル）は緯度 φ において

```
res(z) = 156543.033928 × cos(φ) / 2^z   [m/px]
```

なので `round(log2(res(0) / mesh))` で求まる。既定はこれに 3 段足して
（＝メッシュ 1 辺が約 8px になる）、18 でクリップする。

5m メッシュなら北緯 33.5° でネイティブ ZL15 → 最大 ZL18 になり、
「メッシュサイズにかかわらず原則 ZL18」という運用と一致する。
10m メッシュでは ZL17 になるので、18 に揃えたい場合は `MAX_ZOOM=18` を明示する。

### メッシュサイズは頂点座標の間隔から実測する

浸水想定区域のポリゴンはメッシュ境界に沿って作られるため、頂点の x 座標・y 座標は
メッシュ間隔の格子に載る。隣り合う相異なる座標値の差の最頻値がメッシュ 1 辺になる。

実測例（宇治川）: 経度差の最頻値 0.225″、緯度差の最頻値 0.150″
→ 浸水想定区域図データ電子化ガイドライン（共通編 表10）の細分メッシュ 1/200 ＝ 5m メッシュ。

これは設定で書かせるより実測したほうがよい。**同じ河川でもデータ種別によって
メッシュが違う**ためで、宇治川では想定最大規模が 5m メッシュ、浸水継続時間が
10m メッシュ（0.45″×0.30″）だった。ガイドラインが「浸水深は原則5mメッシュ、
時間・流速に関するデータは計算メッシュサイズ」と定めていることと一致する。
結果として最大ZLも 18 と 17 で変わる。

平面直角座標系の入力ではメートルで検出し、細分メッシュの規定値に突き合わせる。
**ラスタライズの格子は常に細分メッシュの規定値（秒）に載せる**ので、
元データが平面直角座標系でも出力は標準の格子に揃う。

### 凡例の色は一意でなければならない

産総研の JSON凡例フォーマットは「r, g, b の組み合わせがファイル内で一意」を要求する。
色が重複するとピクセル値から凡例項目を一意に引けない。
`tools/rankdef.py` は定義ファイルの読み込み時にこれを検証する。

### `gdaldem` のカラーマップに `nv` 行を書かない

`nv` 行はバンドの NoData 値に展開されるため、ランク値より後ろに置くと
「LUT が単調非減少でない」というエラーになる。このパイプラインでは
パレット経路のラスターの NoData を常に `nodata_rank`（既定 0）にしているので、
`nv` を使わず `0 0 0 0 0` という数値行で表す。

### ランク定義は 1 か所にまとめる

`colors/*.json` にランク値・しきい値・配色・出典をまとめ、そこから

- `gdaldem color-relief` 用カラーマップ
- 産総研 JSON凡例フォーマットの `legend.json`
- 実数値 → ランクの分類 SQL（`CASE WHEN`）

を生成する。しきい値と配色が別ファイルに散ると、片方だけ直して不整合を起こす。

同梱の定義:

| ファイル | 内容 | 出典 |
|---|---|---|
| `colors/water-depth-6rank.json` | 浸水深 6 ランク | 国土数値情報 浸水ランクコード ＋ 洪水浸水想定区域図作成マニュアル（第4版）図-7.2-1 |
| `colors/water-depth-8rank.json` | 浸水深 8 ランク（詳細版） | 同マニュアル 図-7.2-2 / 表-7.2 |
| `colors/flood-duration-7rank.json` | 浸水継続時間 7 ランク | 国土数値情報 浸水継続時間ランクコード ＋ 同マニュアル 表-7.4 |

## ビューワ

`viewer/` は MapLibre GL JS の Vite アプリ。姉妹リポジトリ
[aerial-photo-tile-pipeline](https://github.com/shiwaku/aerial-photo-tile-pipeline) ではなく、
[mlit-urban-planning-converter](https://github.com/shiwaku/mlit-urban-planning-converter) の
ビューワを土台にして、レイヤー部分をラスタータイル用に差し替えている。

- `output/` 以下の全タイルセットを 1 レイヤーずつ並べる（`datasets.json` から自動列挙）
- **クリックした地点のタイル画素を読んで値に戻す**。パレットPNGは色から
  `legend.json` の凡例項目を引き、数値PNGは RGB から実数を復号する
- レイヤーごとの ON/OFF・不透明度・凡例・「この範囲へ」
- 背景は 国土地理院 最適化ベクトルタイル（淡色）／全国最新写真 を切替
- ライト／ダークテーマ（淡色スタイルは明度を反転してダーク化）
- PWA（オフラインキャッシュはしない。常に最新を取る Service Worker）
- `?debug` で診断 HUD

ラスタータイルには属性を持つ地物が無いので、ベクトル版の
`queryRenderedFeatures` によるハイライトは使えない。代わりに読み取った画素の位置に
点を打ち、値はタイル画像から直接取り出す。この「画素から値を引く」処理が
グリッドPNGタイル仕様の使い方そのものなので、ビューワが仕様の動作確認も兼ねる。

### 実装で踏んだ落とし穴

- **`new URL('./{z}/{x}/{y}.png', base)` は使えない。** 中括弧が `%7Bz%7D` に
  パーセントエンコードされ、以降の `{z}` 置換が一致せず全タイルが 404 になる。
  `resolveTemplate()` で文字列連結して解決している。
- **Service Worker の `controllerchange` で無条件に reload してはいけない。**
  初回訪問では「未制御 → activate」で必ず一度発火するため、初回に必ずページが
  読み直される。そのとき URL には `hash: true` が書いたハッシュが付いているので、
  「URL で位置指定が無い初回だけデータ範囲に合わせる」判定が壊れる。
  `navigator.serviceWorker.controller` の有無を先に見て、本当の更新時だけ reload する。
- **`fitBounds` は `duration: 0` で呼ぶ。** アニメーション中に `hash: true` の
  hashchange が割り込むと元の位置へ戻されることがある。
- **タイルの 404 は「取得失敗」ではなく「値が無い」。** このパイプラインは
  `gdal2tiles -x` で完全透明タイルを出力しないため、404 は無効値として扱う。

## 仕様への適合

産総研「グリッドPNGタイル 仕様」(0.1, 2020-12-15) に沿う。

**パレットPNGタイル**

- ピクセル値 `pv = 2^16 r + 2^8 g + b`。凡例情報は `tiles/legend.json`（JSON凡例フォーマット）
- 無効値は不透明度 0。ランク 0（浸水なし）を透明にするので、背景地図に重ねられる
- 同仕様の解説ページは、国土交通省「重ねるハザードマップ」のデータ配信を
  パレットPNGタイルの適合例として挙げている

**数値PNGタイル**

- `r' = r`（`r < 2^7`）または `r - 2^8`（`r ≧ 2^7`）、`v = f (2^16 r' + 2^8 g + b) + o`
- 係数 `f` とオフセット `o` は `tiles/tiles.json` の `datapng.numeric` に書く。
  これが無いと受け取り側は画素値から値を復元できない
- 既定は `f = 0.01`（cm 単位。地理院標高タイルと同じ）。
  24 ビット符号付き整数なので表現範囲は ±83,886.07

`tools/encode_numeric.py` の符号化は、負値・無効値・24 ビット境界（±83886.07 @ f=0.01）
を含む往復テストで一致を確認している。

## ディレクトリ構成

```
.
├── .github/workflows/
│   └── pages.yml             … 同梱サンプルを通して GitHub Pages に公開する CI
├── colors/                   … ランク定義（値・しきい値・配色・出典）
├── config/
│   ├── sample.conf.example                 … 設定テンプレート
│   ├── ksj-flood-ujigawa.conf.example      … ランク → パレットPNG
│   ├── ksj-duration-ujigawa.conf.example   … 同じ河川の浸水継続時間
│   ├── fukushima-depth-numeric.conf.example… 実数値 → 数値PNG
│   └── fukushima-depth-palette.conf.example… 同じ入力を → パレットPNG
├── data/                     … 入力データ（gitignore／公開データのみ）
├── output/                   … 中間・出力（gitignore）
├── scripts/
│   ├── 00_fetch_data.sh … Step 0: サンプルデータ取得（任意）
│   ├── 01_inspect.sh … 05_make_metadata.sh
│   ├── run_pipeline.sh  … Step 1〜5 の一括実行（--from / --to）
│   ├── serve.sh         … ローカルプレビュー
│   ├── build_site.sh    … 公開用サイトの組み立て（_site/）
│   └── lib/common.sh    … 設定ロード・既定値・ログ
├── tools/
│   ├── inspect_inputs.py  … 入力検査・auto 値の解決
│   ├── rankdef.py         … ランク定義 → カラーマップ / 凡例 / 分類SQL
│   ├── encode_numeric.py  … 実数値ラスター → 数値PNG の RGBA
│   ├── make_metadata.py   … tiles.json / legend.json
│   ├── validate_tiles.py  … 生成タイルの仕様適合検証
│   ├── make_dataset_index.py … output/ を走査して datasets.json を作る
│   └── fetch_data.py      … ZIP の取得と CP932 ファイル名の展開
└── viewer/                … MapLibre ビューワ（Vite + TypeScript）
    ├── src/
    │   ├── main.ts        … 地図・UI・クリックでの画素読み取り
    │   ├── layers.ts      … タイルセットの読込・凡例・画素→値の復号
    │   ├── basemap.ts     … 背景地図（淡色／写真、ダーク化）
    │   ├── theme.ts       … ライト／ダークの保存と適用
    │   ├── pale-style.json… 地理院 最適化ベクトルタイルのスタイル
    │   └── style.css
    ├── public/            … PWA マニフェスト・Service Worker・アイコン
    └── vite.config.ts     … dev で output/ を /data として配信する
```

## サンプルデータの出典

| データ | 提供元 | ライセンス |
|---|---|---|
| 洪水浸水想定区域データ（河川単位）2025年度 A31a | 国土交通省 国土数値情報 | CC BY 4.0 |
| 津波浸水想定（最大浸水深） | 福島県 | CC BY 2.1 JP |

`data/` の中身はリポジトリに含めない。`00_fetch_data.sh` で各自取得する。

## ライセンス

このリポジトリのコードは [Apache License 2.0](LICENSE)。

`data/` に取得するデータはそれぞれの提供元のライセンスに従う（上表参照）。
生成したタイルを配信する場合は、元データの出典表記を必ず添えること。

## 関連

- [aerial-photo-tile-pipeline](https://github.com/shiwaku/aerial-photo-tile-pipeline)
  … 航空写真（正射画像）から XYZ ラスタータイルを生成するパイプライン。
  スクリプト構成・設定ファイル方式・`auto` 解決の考え方を揃えている。
- [mlit-urban-planning-converter](https://github.com/shiwaku/mlit-urban-planning-converter)
  … 都市計画決定GISデータのビューワ。`viewer/` はこちらを土台にしている。

## 参考

- [産総研 データPNG](https://gsj-seamless.jp/labs/datapng/) / [グリッドPNGタイル](https://gsj-seamless.jp/labs/datapng/gridpngtile.html) / [仕様](https://gsj-seamless.jp/labs/datapng/gridpngtileSpec.html)
- [浸水想定区域図データ電子化ガイドライン（第5.1版）](https://www.mlit.go.jp/river/shishin_guideline/bousai/saigai/tisiki/syozaiti/pdf/e-guideline.pdf)
- [洪水浸水想定区域図作成マニュアル（第4版）](https://www.mlit.go.jp/river/shishin_guideline/pdf/manual_kouzuishinsui_1710.pdf)
- [国土数値情報 洪水浸水想定区域データ（河川単位）](https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-A31a-2025.html)
- [ハザードマップポータルサイト オープンデータ配信](https://disaportal.gsi.go.jp/hazardmapportal/hazardmap/copyright/opendata.html)
- [GDAL: gdal_rasterize](https://gdal.org/en/stable/programs/gdal_rasterize.html) / [gdaldem](https://gdal.org/en/stable/programs/gdaldem.html) / [gdal2tiles](https://gdal.org/en/stable/programs/gdal2tiles.html)
- [TileJSON 2.2.0 仕様](https://github.com/mapbox/tilejson-spec/tree/master/2.2.0)
