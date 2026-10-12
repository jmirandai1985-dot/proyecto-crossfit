import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClientProvider } from '@tanstack/react-query'
import './index.css'
import App from './App.jsx'
import ErrorBoundary from './components/ErrorBoundary.jsx'
import { queryClient } from './services/queryClient.js'
import { instalarRecargaPorChunk } from './utils/recargaAutomatica.js'

// ANTES del primer render (y del primer import() de una ruta `lazy`): si el navegador
// pide un chunk que ya no existe —pestaña abierta desde el deploy anterior—, se recarga
// solo una vez en vez de dejar la pantalla en blanco (ver utils/recargaAutomatica.js).
instalarRecargaPorChunk();

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
