import { defineConfig, type Plugin } from 'vite'
import { createReadStream, existsSync, readdirSync, statSync } from 'node:fs'
import { extname, join, normalize, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const rootDir = fileURLToPath(new URL('.', import.meta.url))
// パイプラインの成果物はリポジトリ直下 output/<データセットID>/tiles/ にある。
const OUTPUT_DIR = resolve(rootDir, '..', 'output')

const MIME: Record<string, string> = {
  '.png': 'image/png',
  '.webp': 'image/webp',
  '.jpg': 'image/jpeg',
  '.json': 'application/json; charset=utf-8',
}

/** output/<id>/tiles/tiles.json を走査してデータセット一覧を組み立てる。 */
function datasetIndex(): string {
  const datasets: { id: string; name: string; tilejson: string }[] = []
  if (existsSync(OUTPUT_DIR)) {
    for (const id of readdirSync(OUTPUT_DIR).sort()) {
      if (id.startsWith('_') || id.startsWith('.')) continue
      const tj = join(OUTPUT_DIR, id, 'tiles', 'tiles.json')
      if (!existsSync(tj)) continue
      datasets.push({ id, name: id, tilejson: `${id}/tiles/tiles.json` })
    }
  }
  return JSON.stringify({ datasets }, null, 2)
}

/**
 * 開発サーバーで output/ を /data として配信するミドルウェア。
 * /data/datasets.json は毎回その場で組み立てるので、パイプラインを回すと
 * リロードだけで新しいタイルセットが一覧に出る。
 */
function tilesDevServer(): Plugin {
  return {
    name: 'tiles-dev-server',
    configureServer(server) {
      server.middlewares.use('/data', (req, res, next) => {
        try {
          const urlPath = decodeURIComponent((req.url ?? '').split('?')[0])

          if (urlPath === '/datasets.json' || urlPath === '/datasets.json/') {
            const body = datasetIndex()
            res.statusCode = 200
            res.setHeader('Content-Type', MIME['.json'])
            res.setHeader('Cache-Control', 'no-store')
            res.end(body)
            return
          }

          const rel = normalize(urlPath).replace(/^([/\\]|\.\.[/\\])+/, '')
          const file = join(OUTPUT_DIR, rel)
          if (!file.startsWith(OUTPUT_DIR) || !existsSync(file) || statSync(file).isDirectory()) {
            res.statusCode = 404
            res.end('Not found')
            return
          }
          res.statusCode = 200
          res.setHeader('Content-Type', MIME[extname(file).toLowerCase()] ?? 'application/octet-stream')
          res.setHeader('Content-Length', String(statSync(file).size))
          res.setHeader('Access-Control-Allow-Origin', '*')
          // タイルは作り直されるので dev ではキャッシュさせない
          res.setHeader('Cache-Control', 'no-store')
          createReadStream(file).pipe(res)
        } catch (err) {
          next(err)
        }
      })
    },
  }
}

export default defineConfig({
  base: './',
  plugins: [tilesDevServer()],
  server: { port: 8000, fs: { allow: ['..'] } },
  define: {
    __BUILD_TIME__: JSON.stringify(new Date().toISOString().replace('T', ' ').slice(0, 16) + ' UTC'),
  },
})
