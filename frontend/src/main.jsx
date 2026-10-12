import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClientProvider } from '@tanstack/react-query'
import './index.css'
import App from './App.jsx'
import { queryClient } from './services/queryClient.js'

// El QueryClientProvider envuelve TODA la app (App adentro): la caché de React Query
// sobrevive a la navegación entre rutas, que es justo lo que hacía que cada pantalla
// `lazy` volviera a pedir sus datos al montarse.
createRoot(document.getElementById('root')).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
)
