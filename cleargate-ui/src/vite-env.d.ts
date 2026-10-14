/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_MODE?: string;
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_ENABLE_DELETE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
