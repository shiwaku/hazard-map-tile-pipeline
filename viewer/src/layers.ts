// ハザードマップタイル（グリッドPNGタイル）のレイヤー定義。
//
// 元リポジトリ（都市計画GISビューワ）はベクトルタイルの属性から配色していたが、
// こちらが扱うのはラスタータイルで、色そのものがデータ（パレットPNG）か、
// RGB に数値が符号化されている（数値PNG）。したがって:
//
//   * 配色はここでは決めない。パレットPNGは焼かれた色をそのまま表示する
//   * 凡例はタイルセット付属の legend.json（産総研 JSON凡例フォーマット）から読む
//   * 値の取得はベクトルの属性参照ではなく、タイル画素の読み取りで行う
//
// データセット一覧は datasets.json（tools/make_dataset_index.py が生成）から取る。

import type { RasterLayerSpecification } from 'maplibre-gl'

/** 産総研 JSON凡例フォーマットの凡例項目。 */
export interface LegendItem {
  r: number
  g: number
  b: number
  title: string
  /** 6桁16進のピクセル値（省略可） */
  value?: string
  description?: string
  /** 生成側で付けている追加メンバー（仕様上、未知メンバーは無視してよい） */
  rank?: number
  min?: number
  max?: number
}

export interface Legend {
  title: string
  items: LegendItem[]
  unit?: string
  source?: string[]
}

/** 数値PNGタイルの復号パラメータ。 */
export interface NumericSpec {
  factor: number
  offset: number
  unit: string
  formula?: string
  nodata?: string
  value_min?: number
  value_max?: number
}

/** tiles.json（TileJSON 2.2.0 + datapng 拡張）。 */
export interface TileJson {
  name: string
  description?: string
  attribution?: string
  tiles: string[]
  minzoom: number
  maxzoom: number
  bounds: [number, number, number, number]
  center: [number, number, number]
  format: string
  datapng?: {
    tile_type: 'palette' | 'numeric'
    value_kind: 'rank' | 'depth'
    value_field: string
    mesh?: string
    mesh_side_m?: number
    spec?: string
    legend?: string
    numeric?: NumericSpec
  }
}

/** 1 データセット = 1 レイヤー。 */
export interface DatasetDef {
  /** データセットID（output/<id>/ のディレクトリ名） */
  id: string
  /** 表示名 */
  name: string
  /** タイルURLテンプレート（解決済み） */
  tileUrl: string
  tilejson: TileJson
  legend: Legend | null
  /** 初期表示 ON/OFF */
  on: boolean
  /** 不透明度（UI のスライダーで変更される） */
  opacity?: number
}

/** 既定の不透明度。背景地図が透けるくらいがハザードの重ね合わせでは見やすい。 */
export const DEFAULT_OPACITY = 0.75

export function opacityOf(def: DatasetDef): number {
  return def.opacity ?? DEFAULT_OPACITY
}

/** datapng 拡張。このパイプライン以外が作った tiles.json でも落ちないよう Partial で返す。 */
export type DataPng = Partial<NonNullable<TileJson['datapng']>>

export function datapngOf(def: DatasetDef): DataPng {
  return def.tilejson.datapng ?? {}
}

export function tileType(def: DatasetDef): 'palette' | 'numeric' {
  return datapngOf(def).tile_type ?? 'palette'
}

/** データセットの説明文（パネルの i ボタンで表示）。 */
export function describe(def: DatasetDef): string {
  const dp = datapngOf(def)
  const lines: string[] = []
  if (def.tilejson.description) lines.push(def.tilejson.description)
  if (dp.tile_type) {
    const kind = dp.value_kind === 'rank' ? '離散ランク' : '浸水深の実数値'
    const type = dp.tile_type === 'palette' ? 'パレットPNG' : '数値PNG'
    lines.push(`元データ: ${kind}（属性 ${dp.value_field}） → ${type}`)
    if (dp.tile_type === 'numeric') {
      lines.push('画素値から実数を復元できる。クリックで値を読み取れる。')
    } else {
      lines.push('凡例に定義された色だけが使われる。クリックで該当ランクを引ける。')
    }
  }
  if (dp.mesh) lines.push(`メッシュ: ${dp.mesh}`)
  lines.push(`ZL ${def.tilejson.minzoom}–${def.tilejson.maxzoom}`)
  return lines.join('\n')
}

/** ラスターレイヤー定義。パレット／数値どちらも nearest で描く（画素値を混ぜない）。 */
export function rasterLayer(id: string, source: string, def: DatasetDef): RasterLayerSpecification {
  return {
    id,
    type: 'raster',
    source,
    paint: {
      'raster-opacity': opacityOf(def),
      // 画素値そのものが意味を持つので、拡大時も補間しない。
      // linear にするとメッシュ境界がぼやけ、凡例に無い色・値が画面上に現れる。
      'raster-resampling': 'nearest',
      'raster-fade-duration': 0,
    },
  }
}

// ---- 凡例 ----

export interface LegendSwatch {
  color: string
  label: string
}

const rgbCss = (it: LegendItem): string => `rgb(${it.r},${it.g},${it.b})`

/**
 * パネルに出す凡例。
 * パレットPNGは legend.json をそのまま並べる。
 * 数値PNGは色を持たないので、値域を段階に割った擬似カラーバーの代わりに
 * 「復号式と値域」をテキストで示す（main.ts 側で扱う）。
 */
export function legendFor(def: DatasetDef): LegendSwatch[] {
  if (!def.legend) return []
  return def.legend.items.map((it) => ({ color: rgbCss(it), label: it.title }))
}

/** レイヤートグルの代表色。 */
export function dotColor(def: DatasetDef): string {
  const items = legendFor(def)
  if (items.length) return items[Math.floor(items.length / 2)].color
  return 'rgba(120,160,220,0.9)'
}

// ---- 画素からの値取得 ----

/** 緯度経度 → タイル座標（グリッドPNGタイル解説ページの式と同じ）。 */
export function lngLatToTile(lng: number, lat: number, z: number): { x: number; y: number } {
  const w = Math.pow(2, z) / 2
  const yrad = Math.log(Math.tan((Math.PI * (90 + lat)) / 360))
  return { x: (lng / 180 + 1) * w, y: (1 - yrad / Math.PI) * w }
}

export interface PixelHit {
  z: number
  x: number
  y: number
  i: number
  j: number
  r: number
  g: number
  b: number
  a: number
  /**
   * タイル自体が存在しなかった（404）。
   * このパイプラインは gdal2tiles -x で完全透明なタイルを出力しないため、
   * 「タイルが無い」＝「その範囲に値が無い」を意味する。取得失敗ではない。
   */
  missing?: boolean
}

const imgCache = new Map<string, Promise<HTMLImageElement | null>>()

function loadImage(url: string): Promise<HTMLImageElement | null> {
  const cached = imgCache.get(url)
  if (cached) return cached
  const p = new Promise<HTMLImageElement | null>((resolve) => {
    const img = new Image()
    img.crossOrigin = 'anonymous'
    img.onload = () => resolve(img)
    img.onerror = () => resolve(null)
    img.src = url
  })
  imgCache.set(url, p)
  // キャッシュが無限に増えないよう、ある程度で古いものを捨てる
  if (imgCache.size > 200) {
    const first = imgCache.keys().next().value
    if (first !== undefined) imgCache.delete(first)
  }
  return p
}

/** 指定地点のタイル画素を読む。タイルが無ければ null。 */
export async function readPixel(
  def: DatasetDef,
  lng: number,
  lat: number,
  zoom: number,
): Promise<PixelHit | null> {
  const z = Math.min(def.tilejson.maxzoom, Math.max(def.tilejson.minzoom, Math.floor(zoom)))
  const p = lngLatToTile(lng, lat, z)
  const x = Math.floor(p.x)
  const y = Math.floor(p.y)
  const i = Math.min(255, Math.floor((p.x - x) * 256))
  const j = Math.min(255, Math.floor((p.y - y) * 256))
  const url = def.tileUrl
    .replace('{z}', String(z))
    .replace('{x}', String(x))
    .replace('{y}', String(y))
  const img = await loadImage(url)
  if (!img) {
    // 完全透明なタイルは出力されないので、404 は「値が無い」と解釈する。
    return { z, x, y, i, j, r: 0, g: 0, b: 0, a: 0, missing: true }
  }

  const canvas = document.createElement('canvas')
  canvas.width = 1
  canvas.height = 1
  const ctx = canvas.getContext('2d', { willReadFrequently: true })
  if (!ctx) return null
  ctx.clearRect(0, 0, 1, 1)
  ctx.drawImage(img, i, j, 1, 1, 0, 0, 1, 1)
  const d = ctx.getImageData(0, 0, 1, 1).data
  return { z, x, y, i, j, r: d[0], g: d[1], b: d[2], a: d[3] }
}

/** ピクセル値（産総研パレットPNGタイル仕様）。pv = 2^16 r + 2^8 g + b */
export function pixelValue(px: PixelHit): number {
  return (px.r << 16) + (px.g << 8) + px.b
}

/** 数値PNGタイルの復号。v = f (2^16 r' + 2^8 g + b) + o、r' は符号付き。 */
export function decodeNumeric(px: PixelHit, num: NumericSpec): number {
  const rp = px.r < 2 ** 7 ? px.r : px.r - 2 ** 8
  return num.factor * (2 ** 16 * rp + 2 ** 8 * px.g + px.b) + num.offset
}

/** パレットPNGタイルの色 → 凡例項目。仕様どおり RGB の完全一致で引く。 */
export function findLegendItem(legend: Legend | null, px: PixelHit): LegendItem | null {
  if (!legend) return null
  return legend.items.find((it) => it.r === px.r && it.g === px.g && it.b === px.b) ?? null
}

function esc(s: string): string {
  return s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c] as string)
}

/** クリック時のポップアップ HTML。 */
export function popupHtml(def: DatasetDef, px: PixelHit | null): string {
  const head =
    `<div class="pp-title">${esc(def.name)}</div>` +
    (def.name === def.id ? '' : `<div class="pp-sub">${esc(def.id)}</div>`)
  if (!px) {
    return head + '<div class="pp-sub">タイルを取得できませんでした</div>'
  }

  const dp = datapngOf(def)
  const rows: string[] = []
  const rgba = `(${px.r}, ${px.g}, ${px.b}, ${px.a})`

  if (px.a === 0) {
    // 仕様: 完全に透明なピクセルは無効値
    const meaning = dp.value_kind === 'rank' ? '浸水なし・範囲外' : '範囲外'
    const how = px.missing
      ? 'タイル無し（完全透明なタイルは出力されない）'
      : `不透明度 0 / RGBA ${rgba}`
    return (
      head +
      '<dl class="pp-dl"><dt>値</dt><dd><b>無効値</b></dd>' +
      `<dt>意味</dt><dd>${meaning}</dd>` +
      `<dt>根拠</dt><dd>${how}</dd>` +
      `<dt>タイル</dt><dd>ZL${px.z} / ${px.x},${px.y} / 画素 ${px.i},${px.j}</dd></dl>`
    )
  }

  let title = ''
  if (dp.tile_type === 'numeric' && dp.numeric) {
    const v = decodeNumeric(px, dp.numeric)
    title = `${v.toFixed(2)} ${dp.numeric.unit}`
    rows.push(`<dt>値</dt><dd><b>${esc(title)}</b></dd>`)
    rows.push(`<dt>復号</dt><dd>f=${dp.numeric.factor} / o=${dp.numeric.offset}</dd>`)
  } else {
    const hit = findLegendItem(def.legend, px)
    const pv = pixelValue(px).toString(16).toUpperCase().padStart(6, '0')
    title = hit?.title ?? '凡例に無い色'
    rows.push(
      `<dt>区分</dt><dd><b>${esc(title)}</b>${
        hit ? '' : ' <span class="pp-warn">（仕様違反）</span>'
      }</dd>`,
    )
    if (hit?.rank !== undefined) rows.push(`<dt>ランク</dt><dd>${hit.rank}</dd>`)
    if (hit?.description) rows.push(`<dt>目安</dt><dd>${esc(hit.description)}</dd>`)
    rows.push(`<dt>ピクセル値</dt><dd><code>${pv}</code></dd>`)
  }

  rows.push(`<dt>RGBA</dt><dd>${rgba}</dd>`)
  rows.push(`<dt>タイル</dt><dd>ZL${px.z} / ${px.x},${px.y} / 画素 ${px.i},${px.j}</dd>`)
  return head + `<dl class="pp-dl">${rows.join('')}</dl>`
}

// ---- データセット一覧の読み込み ----

interface DatasetIndexEntry {
  id: string
  name?: string
  tilejson: string
}

interface DatasetIndex {
  datasets: DatasetIndexEntry[]
}

/**
 * タイルURLテンプレートを tiles.json の位置基準で解決する。
 *
 * `new URL()` は使えない。`{z}` を `%7Bz%7D` にパーセントエンコードしてしまい、
 * 以降の置換が一致しなくなって全タイルが 404 になる（実際に踏んだ）。
 * そのため中括弧を残したまま文字列として連結する。
 */
export function resolveTemplate(template: string, tilejsonUrl: string): string {
  if (/^[a-z][a-z0-9+.-]*:/i.test(template)) return template // 絶対URL
  const base = new URL(tilejsonUrl)
  if (template.startsWith('/')) return `${base.origin}${template}`
  const dir = base.pathname.slice(0, base.pathname.lastIndexOf('/') + 1)
  return `${base.origin}${dir}${template.replace(/^\.\//, '')}`
}

/**
 * datasets.json を読み、各データセットの tiles.json / legend.json まで取得して
 * DatasetDef の配列にする。tiles.json の tiles[0] は `./{z}/{x}/{y}.png` のような
 * 相対URLなので、tiles.json の位置を基準に解決する。
 */
export async function loadDatasets(dataBase: string): Promise<DatasetDef[]> {
  const indexUrl = `${dataBase}/datasets.json`
  const res = await fetch(indexUrl, { cache: 'no-store' })
  if (!res.ok) throw new Error(`${indexUrl} を読めない（${res.status}）。serve.sh で生成される`)
  const index = (await res.json()) as DatasetIndex

  const defs: DatasetDef[] = []
  for (const [i, entry] of index.datasets.entries()) {
    const tjUrl = new URL(entry.tilejson, new URL(indexUrl, location.href)).toString()
    const tj = (await (await fetch(tjUrl, { cache: 'no-store' })).json()) as TileJson
    const tileUrl = resolveTemplate(tj.tiles[0], tjUrl)

    let legend: Legend | null = null
    const legendRel = tj.datapng?.legend
    if (legendRel) {
      try {
        const lg = await fetch(new URL(legendRel, tjUrl).toString(), { cache: 'no-store' })
        if (lg.ok) {
          const raw = (await lg.json()) as Legend | LegendItem[]
          legend = Array.isArray(raw) ? { title: tj.name, items: raw } : raw
        }
      } catch {
        legend = null
      }
    }

    defs.push({
      id: entry.id,
      name: entry.name ?? tj.name ?? entry.id,
      tileUrl,
      tilejson: tj,
      legend,
      // 先頭のデータセットだけ初期表示 ON。全部載せると重ねすぎて見えない。
      on: i === 0,
    })
  }
  return defs
}
