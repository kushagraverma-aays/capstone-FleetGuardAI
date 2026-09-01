/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Only set when the API is on a different origin from the app. Empty in
   *  development (the Vite proxy) and in Docker (nginx proxies /api). */
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
