import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'
import { visualizer } from 'rollup-plugin-visualizer'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    // PWA instalable (ícono en el home, standalone). Alcance: SOLO instalable.
    // ⚠️ Sin runtime caching de /api/*: generateSW solo precachea el app shell
    // (HTML/JS/CSS/ícono). Si no hay internet, el navegador muestra su pantalla de
    // "sin conexión" normal — nada de datos desactualizados de pagos/clases.
    VitePWA({
      registerType: 'autoUpdate',
      manifest: {
        name: 'Urban Training Box',
        short_name: 'Urban Box',
        description: 'Plataforma de gestión para Urban Training Box',
        lang: 'es',
        theme_color: '#0b0e14',
        background_color: '#0b0e14',
        display: 'standalone',
        start_url: '/',
        icons: [
          // El logo del box tal como está en /imgs/logo.png (447x447). Los íconos
          // pwa-* de abajo son ESE logo en 192/512 (los exige el instalador); se
          // mantienen los tres para que Chrome/Android pueda instalar la app.
          { src: '/imgs/logo.png', sizes: '447x447', type: 'image/png', purpose: 'any' },
          { src: '/pwa-192x192.png', sizes: '192x192', type: 'image/png' },
          { src: '/pwa-512x512.png', sizes: '512x512', type: 'image/png' },
          {
            src: '/pwa-maskable-512x512.png',
            sizes: '512x512',
            type: 'image/png',
            purpose: 'maskable',
          },
        ],
      },
    }),
    // Observabilidad del bundle: en cada `vite build` genera dist/stats.html con el
    // tamaño de cada chunk (y su desglose por módulo, con gzip/brotli). Sirve para
    // frenar regresiones de tamaño. Sólo actúa durante el build (no en dev).
    visualizer({
      open: false,
      filename: 'dist/stats.html',
      // gzip sí (es el peso real que transfiere el servidor); brotli se deja
      // apagado porque su cálculo dispara el tiempo del build sin aportar para
      // el objetivo de frenar regresiones de tamaño.
      gzipSize: true,
      brotliSize: false,
      template: 'treemap',
    }),
  ],
  build: {
    rollupOptions: {
      output: {
        // manualChunks: separa el "vendor" (dependencias de node_modules) del
        // código propio de la app, y de paso parte las librerías más pesadas en
        // chunks cacheables e independientes de la ruta:
        //   · vendor-recharts → recharts + sus deps gráficas (d3-*, victory-vendor,
        //     recharts-scale, react-smooth). Es la dependencia más grande.
        //   · vendor-react    → react / react-dom / react-router + scheduler.
        //   · vendor          → el resto de node_modules.
        // El código de cada rol (admin/coach/alumno) NO cae aquí: vive en los
        // chunks por pantalla que genera React.lazy en App.jsx.
        // (En Vite 8/Rolldown, manualChunks se admite por compatibilidad con Rollup
        //  y se transforma internamente en output.codeSplitting.groups.)
        manualChunks(id) {
          const seg = /[\\/]node_modules[\\/]/;
          if (!seg.test(id)) return undefined; // código propio de la app
          // recharts y todo su árbol de dependencias de gráficos
          if (/[\\/]node_modules[\\/](recharts|recharts-scale|react-smooth|victory-vendor|d3-[^\\/]+|internmap|decimal\.js-light)[\\/]/.test(id)) {
            return 'vendor-recharts';
          }
          // núcleo de React + router
          if (/[\\/]node_modules[\\/](react|react-dom|react-router|react-router-dom|scheduler|use-sync-external-store)[\\/]/.test(id)) {
            return 'vendor-react';
          }
          return 'vendor'; // resto de dependencias
        },
      },
    },
  },
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
      // /static: las imágenes de los productos (que en dev/TEST guarda el backend
      // en app/static/uploads) las sirve uvicorn en :8000. Vite NO las proxea por
      // defecto, así que el <img src="/static/uploads/..."> del Bazar daba 404.
      // En PROD nginx ya proxea /static/ al backend (mismo origen).
      '/static': {
        target: 'http://localhost:8000',
        changeOrigin: false,
      },
    },
  },
})
