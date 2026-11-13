import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClientProvider } from '@tanstack/react-query'
import { registerSW } from 'virtual:pwa-register'
import './index.css'
import App from './App.jsx'
import ErrorBoundary from './components/ErrorBoundary.jsx'
import { queryClient } from './services/queryClient.js'
import { iniciarInstalacionApp } from './services/instalacionApp.js'
import { instalarRecargaPorChunk } from './utils/recargaAutomatica.js'

// ANTES del primer render (y del primer import() de una ruta `lazy`): si el navegador
// pide un chunk que ya no existe —pestaña abierta desde el deploy anterior—, se recarga
// solo una vez en vez de dejar la pantalla en blanco (ver utils/recargaAutomatica.js).
instalarRecargaPorChunk();

// PWA (vite-plugin-pwa con registerType: 'autoUpdate'): el service worker nuevo ya hace
// skipWaiting + clientsClaim en segundo plano, pero la pestaña abierta sigue corriendo el
// JS viejo que tiene en memoria. registerSW() engancha el evento 'activated' y fuerza un
// reload silencioso apenas el SW nuevo toma control (sin banner ni decisión del usuario).
registerSW({ immediate: true });

// PWA instalable: engancha `beforeinstallprompt` ANTES del primer render. El evento
// puede dispararse una sola vez y muy temprano; si el listener viviera recién en el
// Layout del alumno, el prompt se perdería y el botón "Instalar app" no aparecería.
iniciarInstalacionApp();

// El QueryClientProvider envuelve TODA la app (App adentro): la caché de React Query
// sobrevive a la navegación entre rutas, que es justo lo que hacía que cada pantalla
// `lazy` volviera a pedir sus datos al montarse.
createRoot(document.getElementById('root')).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      {/* ErrorBoundary por FUERA de App: atrapa también lo que reviente dentro de
          AuthProvider/Router. Nada de pantallas en blanco: aviso + Recargar. */}
      <ErrorBoundary>
        <App />
      </ErrorBoundary>
    </QueryClientProvider>
  </StrictMode>,
)
