/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** タイル成果物のベースURL。既定は dev で /data、本番で . */
  readonly VITE_DATA_BASE?: string
}
interface ImportMeta {
  readonly env: ImportMetaEnv
}

declare const __BUILD_TIME__: string
