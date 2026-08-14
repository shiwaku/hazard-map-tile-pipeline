import maplibregl from 'maplibre-gl'
import { Protocol } from 'pmtiles'
import 'maplibre-gl/dist/maplibre-gl.css'

import { getBasemapStyle, type Basemap } from './basemap'
import {
  type DatasetDef,
  datapngOf,
  describe,
  legendFor,
  loadDatasets,
  opacityOf,
  popupHtml,
  rasterLayer,
  readPixel,
} from './layers'
import { applyThemeAttr, initialTheme, type Theme } from './theme'
import './style.css'

// タイル成果物の置き場。dev では vite の middleware が ../output を /data に見せる。
// 本番（serve.sh / 静的ホスティング）では index.html と同じ階層に各データセットが並ぶ。
const DATA_BASE = import.meta.env.VITE_DATA_BASE ?? (import.meta.env.DEV ? '/data' : '.')

let theme: Theme = initialTheme()
let base: Basemap = 'pale'
applyThemeAttr(theme)

const isMobile = window.matchMedia('(max-width: 640px)').matches
const DEBUG = new URLSearchParams(location.search).has('debug')
// hash:true の Map は初期化直後に自分で location.hash を書く。そのため
// 「URL で位置が指定されていたか」は Map を作る前に控えておく必要がある
// （後から読むと常に hash 有りになり、データ範囲への自動フィットが働かない）。
const HAD_HASH = location.hash.length > 1

// 背景の「地図」は国土地理院 最適化ベクトルタイルで、PMTiles で配信されている。
// ハザードタイル自体は XYZ ラスターだが、背景のためにこのプロトコル登録が必要。
const protocol = new Protocol()
maplibregl.addProtocol('pmtiles', protocol.tile)

const map = new maplibregl.Map({
  container: 'map',
  style: getBasemapStyle(base, theme),
  center: [139.74, 35.68],
  zoom: 9,
  // 地図位置を URL の #ズーム/緯度/経度 に反映（共有・リロード時の位置維持）
  hash: true,
  attributionControl: false,
  maxTileCacheSize: isMobile ? 48 : undefined,
  pixelRatio: isMobile ? Math.min(window.devicePixelRatio || 1, 2) : undefined,
})
map.addControl(new maplibregl.NavigationControl({ showCompass: true, visualizePitch: true }), 'top-right')
map.addControl(
  new maplibregl.GeolocateControl({
    positionOptions: { enableHighAccuracy: true },
    trackUserLocation: true,
    showUserLocation: true,
  }),
  'top-right',
)
map.addControl(new maplibregl.ScaleControl(), 'bottom-left')
const attribCtrl = new maplibregl.AttributionControl({ compact: true })
map.addControl(attribCtrl)

// ---- 診断（?debug で画面表示） ----
const diagLog: string[] = []
let ctxLostCount = 0
let hudEl: HTMLElement | null = null
function diag(msg: string): void {
  const line = `${new Date().toISOString().slice(11, 19)} ${msg}`
  diagLog.push(line)
  if (diagLog.length > 8) diagLog.shift()
  // eslint-disable-next-line no-console
  console.log('[diag]', line)
  renderHud()
}
function renderHud(): void {
  if (!DEBUG || !hudEl) return
  const rows = DATASETS.map((d) => `${d.id}: ${d.on ? 'on' : 'off'}`).join('<br>')
  hudEl.innerHTML =
    `<b>build ${__BUILD_TIME__}</b><br>` +
    `zoom ${map.getZoom().toFixed(1)} · mobile ${isMobile} · ctxLost ${ctxLostCount}<br>` +
    `<u>datasets</u><br>${rows || '(none)'}<br>` +
    `<u>log</u><br>${diagLog.join('<br>')}`
}
function initHud(): void {
  if (!DEBUG) return
  hudEl = document.createElement('div')
  hudEl.id = 'diag-hud'
  document.body.append(hudEl)
  renderHud()
  map.on('render', () => {
    if (map.areTilesLoaded()) renderHud()
  })
}

// ---- データセット ----
let DATASETS: DatasetDef[] = []

const sourceId = (id: string): string => `ds-${id}`
const layerId = (id: string): string => `ds-${id}-lyr`
const visibleDatasets = (): DatasetDef[] => DATASETS.filter((d) => d.on)

// canonical z順: DATASETS 配列の後ろほど地図で最前面。
// クリックマーカーは常に全データ層より前面に保つ。
function beforeIdFor(def: DatasetDef): string | undefined {
  const i = DATASETS.indexOf(def)
  for (let j = i + 1; j < DATASETS.length; j++) {
    const id = layerId(DATASETS[j].id)
    if (map.getLayer(id)) return id
  }
  return map.getLayer(MARKER_LYR) ? MARKER_LYR : undefined
}

// ---- クリック位置マーカー ----
// ラスタータイルにはクリックできる地物が無いため、ベクトル版のハイライトの代わりに
// 「どの画素を読んだか」を示す点を打つ。
const MARKER_SRC = 'click-marker'
const MARKER_LYR = 'click-marker-lyr'
const EMPTY_FC: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: [] }

function ensureMarkerLayer(): void {
  if (!map.getSource(MARKER_SRC)) {
    map.addSource(MARKER_SRC, { type: 'geojson', data: EMPTY_FC })
  }
  if (!map.getLayer(MARKER_LYR)) {
    map.addLayer({
      id: MARKER_LYR,
      type: 'circle',
      source: MARKER_SRC,
      paint: {
        'circle-radius': 5,
        'circle-color': 'rgba(0,0,0,0)',
        'circle-stroke-color': 'rgba(255,200,0,1)',
        'circle-stroke-width': 2.5,
      },
    })
  }
}

function setMarker(lngLat: maplibregl.LngLat | null): void {
  const src = map.getSource(MARKER_SRC) as maplibregl.GeoJSONSource | undefined
  if (!src) return
  src.setData(
    lngLat
      ? {
          type: 'FeatureCollection',
          features: [
            { type: 'Feature', geometry: { type: 'Point', coordinates: [lngLat.lng, lngLat.lat] }, properties: {} },
          ],
        }
      : EMPTY_FC,
  )
}

function ensureLayer(def: DatasetDef): void {
  if (map.getLayer(layerId(def.id))) return
  if (!map.getSource(sourceId(def.id))) {
    map.addSource(sourceId(def.id), {
      type: 'raster',
      tiles: [def.tileUrl],
      tileSize: 256,
      minzoom: def.tilejson.minzoom,
      maxzoom: def.tilejson.maxzoom,
      bounds: def.tilejson.bounds,
      attribution: def.tilejson.attribution ?? '',
    })
  }
  map.addLayer(rasterLayer(layerId(def.id), sourceId(def.id), def), beforeIdFor(def))
}

function removeLayer(def: DatasetDef): void {
  if (map.getLayer(layerId(def.id))) map.removeLayer(layerId(def.id))
  if (map.getSource(sourceId(def.id))) map.removeSource(sourceId(def.id))
}

/** 有効なデータセットのみを（正規 z順で）地図に載せる。無効なものはソースごと持たない。 */
function addDataLayers(): void {
  ensureMarkerLayer()
  for (const def of DATASETS) {
    if (def.on) ensureLayer(def)
    else removeLayer(def)
  }
}

// ---- テーマ切替 ----
const themeBtn = document.getElementById('theme-btn') as HTMLButtonElement
const renderThemeBtn = (): void => {
  themeBtn.textContent = theme === 'dark' ? '☀️' : '🌙'
}
// 背景スタイルを差し替える。ラスタ（写真）↔ベクタ（淡色）の切替では diff 適用が
// 効かないため diff:false で完全に再構築し、idle を待ってデータ層を貼り直す。
function reloadStyle(): void {
  map.setStyle(getBasemapStyle(base, theme), { diff: false })
  map.once('idle', () => addDataLayers())
}
themeBtn.addEventListener('click', () => {
  theme = theme === 'dark' ? 'light' : 'dark'
  applyThemeAttr(theme)
  renderThemeBtn()
  reloadStyle()
})

// ---- パネル開閉 ----
const panel = document.getElementById('panel') as HTMLElement
const collapseBtn = document.getElementById('collapse-btn') as HTMLButtonElement
const renderCollapseBtn = (): void => {
  collapseBtn.textContent = panel.classList.contains('collapsed') ? '▾' : '▴'
}
collapseBtn.addEventListener('click', () => {
  panel.classList.toggle('collapsed')
  renderCollapseBtn()
})

// ---- レイヤートグル ----
const layersDiv = document.getElementById('layers') as HTMLElement

function legendMarkup(def: DatasetDef): string {
  const dp = datapngOf(def)
  if (dp.tile_type === 'numeric' && dp.numeric) {
    const n = dp.numeric
    const range =
      n.value_min !== undefined && n.value_max !== undefined
        ? `値域 ${n.value_min.toFixed(2)} 〜 ${n.value_max.toFixed(2)} ${n.unit}`
        : `単位 ${n.unit}`
    return (
      `<div class="lg-note">数値PNG（画素値に実数を符号化）<br>` +
      `<code>v = ${n.factor} × (2¹⁶r' + 2⁸g + b) + ${n.offset}</code><br>${range}</div>`
    )
  }
  const items = legendFor(def)
  if (!items.length) return '<div class="lg-note">凡例情報なし</div>'
  return items
    .map(
      (it) =>
        `<span class="lg-row"><span class="lg-sw" style="background:${it.color}"></span>${it.label}</span>`,
    )
    .join('')
}

function buildToggles(): void {
  layersDiv.textContent = ''
  for (const def of DATASETS) {
    const item = document.createElement('div')
    item.className = 'layer-item'
    item.dataset.key = def.id

    const label = document.createElement('label')
    label.className = 'toggle'

    const input = document.createElement('input')
    input.type = 'checkbox'
    input.checked = def.on
    input.addEventListener('change', () => setLayerVisible(def, input.checked))

    const sw = document.createElement('span')
    sw.className = 'switch'
    const text = document.createElement('span')
    text.className = 't-label'
    text.textContent = def.name

    const desc = document.createElement('div')
    desc.className = 'layer-desc'
    desc.hidden = true
    desc.textContent = describe(def)

    const info = document.createElement('button')
    info.type = 'button'
    info.className = 'info-btn'
    info.textContent = 'i'
    info.setAttribute('aria-label', `${def.name}の説明`)
    info.setAttribute('aria-expanded', 'false')
    info.addEventListener('click', (e) => {
      // label 内のボタン。クリックが checkbox のトグルへ波及しないようにする
      e.preventDefault()
      e.stopPropagation()
      const open = desc.hidden
      desc.hidden = !open
      info.setAttribute('aria-expanded', String(open))
    })

    label.append(input, sw, text, info)

    // 不透明度スライダー
    const opac = document.createElement('div')
    opac.className = 'layer-opacity'
    opac.hidden = !def.on
    const range = document.createElement('input')
    range.type = 'range'
    range.min = '0'
    range.max = '1'
    range.step = '0.05'
    range.value = String(opacityOf(def))
    range.setAttribute('aria-label', `${def.name}の不透明度`)
    const val = document.createElement('span')
    val.className = 'op-val'
    val.textContent = `${Math.round(opacityOf(def) * 100)}%`
    range.addEventListener('input', () => {
      const v = Number(range.value)
      val.textContent = `${Math.round(v * 100)}%`
      setLayerOpacity(def, v)
    })
    opac.append(range, val)

    const legend = document.createElement('div')
    legend.className = 'layer-legend'
    legend.innerHTML = legendMarkup(def)
    legend.hidden = !def.on

    // 範囲へ移動（データセットごとに対象地域が違うので必須）
    const zoomBtn = document.createElement('button')
    zoomBtn.type = 'button'
    zoomBtn.className = 'mini-btn zoom-btn'
    zoomBtn.textContent = 'この範囲へ'
    zoomBtn.hidden = !def.on
    zoomBtn.addEventListener('click', () => fitTo([def]))

    item.append(label, desc, opac, zoomBtn, legend)
    layersDiv.append(item)
  }
}

function setLayerVisible(def: DatasetDef, on: boolean): void {
  def.on = on
  if (on) ensureLayer(def)
  else removeLayer(def)
  const item = layersDiv.querySelector<HTMLElement>(`.layer-item[data-key="${def.id}"]`)
  item?.querySelector<HTMLElement>('.layer-legend')?.toggleAttribute('hidden', !on)
  item?.querySelector<HTMLElement>('.layer-opacity')?.toggleAttribute('hidden', !on)
  item?.querySelector<HTMLElement>('.zoom-btn')?.toggleAttribute('hidden', !on)
  renderHud()
}

function setLayerOpacity(def: DatasetDef, v: number): void {
  def.opacity = v
  const id = layerId(def.id)
  if (map.getLayer(id)) map.setPaintProperty(id, 'raster-opacity', v)
}

function setAll(on: boolean): void {
  for (const def of DATASETS) {
    if (def.on === on) continue
    const input = layersDiv.querySelector<HTMLInputElement>(`.layer-item[data-key="${def.id}"] input`)
    if (input) input.checked = on
    setLayerVisible(def, on)
  }
}
;(document.getElementById('all-on') as HTMLButtonElement).addEventListener('click', () => setAll(true))
;(document.getElementById('all-off') as HTMLButtonElement).addEventListener('click', () => setAll(false))

/** 指定データセット群の範囲に地図を合わせる。 */
function fitTo(defs: DatasetDef[]): void {
  if (!defs.length) return
  const b = new maplibregl.LngLatBounds(
    [defs[0].tilejson.bounds[0], defs[0].tilejson.bounds[1]],
    [defs[0].tilejson.bounds[2], defs[0].tilejson.bounds[3]],
  )
  for (const d of defs.slice(1)) {
    b.extend([d.tilejson.bounds[0], d.tilejson.bounds[1]])
    b.extend([d.tilejson.bounds[2], d.tilejson.bounds[3]])
  }
  // duration:0 で即時に移動する。アニメーションさせると、hash:true が初期化時に書いた
  // ハッシュの hashchange が移動中に割り込み、元の位置へ戻されることがある。
  map.fitBounds(b, { padding: isMobile ? 24 : 64, maxZoom: 15, duration: 0 })
}

// ---- 背景地図スイッチャー（右下） ----
class BasemapControl implements maplibregl.IControl {
  private el!: HTMLElement
  onAdd(): HTMLElement {
    this.el = document.createElement('div')
    this.el.className = 'maplibregl-ctrl basemap-switch'
    const defs: [Basemap, string][] = [
      ['pale', '地図'],
      ['photo', '写真'],
    ]
    for (const [b, label] of defs) {
      const btn = document.createElement('button')
      btn.type = 'button'
      btn.textContent = label
      btn.dataset.base = b
      btn.setAttribute('aria-selected', String(b === base))
      btn.addEventListener('click', () => setBase(b))
      this.el.append(btn)
    }
    return this.el
  }
  onRemove(): void {
    this.el.remove()
  }
  sync(): void {
    for (const btn of this.el.querySelectorAll<HTMLButtonElement>('button')) {
      btn.setAttribute('aria-selected', String(btn.dataset.base === base))
    }
  }
}
const basemapCtrl = new BasemapControl()
map.addControl(basemapCtrl, 'bottom-right')

function setBase(next: Basemap): void {
  if (next === base) return
  base = next
  basemapCtrl.sync()
  reloadStyle()
}

// ---- クリックで画素値を読む ----
// 表示中のデータセットを最前面から順に見て、最初に「不透明な画素」が当たったものを採る。
// どれも透明なら最前面のものの結果（無効値）を出す。
let popup: maplibregl.Popup | null = null

map.on('click', async (e) => {
  const defs = visibleDatasets()
  if (!defs.length) {
    setMarker(null)
    return
  }
  setMarker(e.lngLat)

  const zoom = map.getZoom()
  let chosen: { def: DatasetDef; px: Awaited<ReturnType<typeof readPixel>> } | null = null
  for (const def of [...defs].reverse()) {
    const px = await readPixel(def, e.lngLat.lng, e.lngLat.lat, zoom)
    if (!chosen) chosen = { def, px }
    if (px && px.a !== 0) {
      chosen = { def, px }
      break
    }
  }
  if (!chosen) return

  if (popup) {
    const old = popup
    popup = null
    old.remove()
  }
  const p = new maplibregl.Popup({ closeButton: true, maxWidth: '320px' })
    .setLngLat(e.lngLat)
    .setHTML(popupHtml(chosen.def, chosen.px))
    .addTo(map)
  p.on('close', () => {
    if (popup === p) {
      popup = null
      setMarker(null)
    }
  })
  popup = p
})

if (window.matchMedia('(hover: hover)').matches) {
  map.on('mousemove', () => {
    map.getCanvas().style.cursor = visibleDatasets().length ? 'crosshair' : ''
  })
}

// ---- 初期化 ----
const buildEl = document.getElementById('build-ver')
if (buildEl) buildEl.textContent = `build: ${__BUILD_TIME__}`
renderThemeBtn()
if (isMobile) panel.classList.add('collapsed')
renderCollapseBtn()
initHud()

async function init(): Promise<void> {
  const statusEl = document.getElementById('status') as HTMLElement
  try {
    DATASETS = await loadDatasets(DATA_BASE)
  } catch (err) {
    statusEl.hidden = false
    statusEl.innerHTML =
      `<b>タイルセットを読み込めませんでした。</b><br>` +
      `${(err as Error).message}<br><br>` +
      `パイプラインを実行してから <code>./scripts/serve.sh</code> で起動してください。`
    return
  }
  if (!DATASETS.length) {
    statusEl.hidden = false
    statusEl.innerHTML =
      '<b>タイルセットが見つかりません。</b><br>' +
      '<code>./scripts/run_pipeline.sh config/&lt;name&gt;.conf</code> を先に実行してください。'
    return
  }
  statusEl.hidden = true
  buildToggles()

  const run = (): void => {
    addDataLayers()
    // URL で位置が指定されていない初回だけデータの範囲に合わせる
    if (!HAD_HASH) fitTo(visibleDatasets())
  }
  if (map.isStyleLoaded()) run()
  else map.once('load', run)
  diag(`datasets: ${DATASETS.map((d) => d.id).join(', ')}`)
}
void init()

// WebGL コンテキスト消失からの復帰。モバイルではメモリ逼迫時に GL コンテキストが
// 失われ、データ層がまるごと消えて戻らないことがある。復帰時に貼り直して自動回復する。
const canvas = map.getCanvas()
canvas.addEventListener(
  'webglcontextlost',
  (ev) => {
    // preventDefault しないと自動復帰イベントが発火しない
    ev.preventDefault()
    ctxLostCount++
    diag('WebGL context lost')
  },
  false,
)
canvas.addEventListener(
  'webglcontextrestored',
  () => {
    diag('WebGL context restored → relayering')
    if (map.isStyleLoaded()) addDataLayers()
    else map.once('idle', addDataLayers)
  },
  false,
)

map.on('error', (e) => {
  const msg = (e && (e as unknown as { error?: Error }).error?.message) || 'map error'
  diag(`error: ${msg}`)
})

// デバッグ/外部連携用にマップを公開
;(window as unknown as { __map: maplibregl.Map }).__map = map

// PWA: Service Worker 登録（本番のみ。dev では HMR を妨げないよう無効）
if (import.meta.env.PROD && 'serviceWorker' in navigator) {
  // 初回訪問時は「まだ SW に制御されていない」状態から activate されるため
  // controllerchange が必ず一度発火する。ここで無条件に reload すると初回に必ず
  // ページが読み直される。そのとき URL には hash:true が書いたハッシュが付いているので、
  // 「URL で位置が指定されていない初回」の判定が壊れ、データ範囲への自動フィットが効かない。
  // 既に制御されていた場合（＝本当の SW 更新）だけ読み直す。
  const hadController = !!navigator.serviceWorker.controller
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('sw.js').catch(() => {})
  })
  let refreshing = false
  navigator.serviceWorker.addEventListener('controllerchange', () => {
    if (!hadController || refreshing) return
    refreshing = true
    window.location.reload()
  })
}
