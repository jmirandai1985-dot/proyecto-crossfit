import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // host: true => escucha en TODAS las interfaces (IPv4 + IPv6). Sin esto Vite se
    // ata solo a "localhost" resuelto a ::1 (IPv6), así que abrir el dev server con
    // http://127.0.0.1:5173 daba "conexión rechazada" y, en una pestaña ya abierta,
    // TODAS las llamadas fallaban con "Network Error" en todas las pantallas.
    // ⚠️ Queda accesible desde la LAN: si preferís sólo local, borralo y arrancá con
    //    `npm run dev -- --host 127.0.0.1` cuando lo necesites.
    host: true,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        // ⚠️ changeOrigin: true reescribe el Host al del target (localhost:8000), así que
        // los redirects 307 de FastAPI (p. ej. /api/v1/clases -> /api/v1/clases/) salían
        // ABSOLUTOS a http://localhost:8000/... y el navegador los veía como CROSS-ORIGIN:
        // si el dev server se abre con 127.0.0.1 (o cualquier host/IP fuera de
        // CORS_ORIGINS) el preflight daba 400 y axios mostraba "Network Error" en TODAS
        // las pantallas que llaman endpoints sin slash final.
        // Con changeOrigin: false el Host se preserva (127.0.0.1:5173 / localhost:5173) y
        // el 307 apunta de vuelta al MISMO origen del dev server => no hay CORS.
        changeOrigin: false,
      },
    },
  },
})
