# data/

入力データを置くディレクトリ。**リポジトリには含めない**（`.gitignore` 済み）。

ここに置いてよいのは、**公開されているデータ（オープンデータ）のみ**。
業務で受領したデータは置かないこと。

```
data/
├── _zip/                 … 00_fetch_data.sh がダウンロードした ZIP のキャッシュ
└── <データセットID>/
    ├── *.shp / *.shx / *.dbf / *.prj
    └── または *.geojson
```

同梱の設定例は `./scripts/00_fetch_data.sh config/<name>.conf` で自動取得できる。

## 同梱サンプルの出典

| データセット | 提供元 | ライセンス | 出典URL |
|---|---|---|---|
| 洪水浸水想定区域データ（河川単位）2025年度 A31a | 国土交通省 国土数値情報 | CC BY 4.0 | https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-A31a-2025.html |
| 津波浸水想定（最大浸水深） | 福島県 | CC BY 2.1 JP | https://www.pref.fukushima.lg.jp/sec/41045a/tsunami-shinsuisoutei.html |

出典表記はどちらも必須。生成したタイルの `tiles.json` の `attribution` に入る
（設定の `ATTRIBUTION`）。

## 自分のデータを使う場合

`data/<DATASET_ID>/` に置いて `SRC_DIR` を指すだけでよい。対応形式は
シェープファイル / GeoJSON / GeoPackage / FlatGeobuf。

1 データセットには**同じ意味の値属性を持つファイルだけ**を入れること。
浸水深と浸水継続時間のように意味が違うものは、別のデータセットとして分ける
（属性名や値の種別が食い違うと Step 1 がエラーで止まる）。

## その他の取得元

| 提供元 | 内容 | URL |
|--------|------|-----|
| 国土数値情報 | 洪水・津波・高潮・内水の浸水想定区域（Shapefile / GeoJSON / GML） | https://nlftp.mlit.go.jp/ksj/ |
| ハザードマップポータルサイト | 重ねるハザードマップのタイル配信 | https://disaportal.gsi.go.jp/ |
| G空間情報センター | 自治体公開の浸水想定区域データ | https://www.geospatial.jp/ |
| 各都道府県の河川担当課 | 洪水浸水想定区域図のシェープデータ | 都道府県サイト |

> 浸水深の**実数値**を持つ公開データは限られる。洪水はほぼすべてランクコードで、
> 実数値が必要な場合は津波（一部県が最大浸水深を実数で公開）か、
> 河川管理者から電子化ガイドラインの CSV データを受領する必要がある。
