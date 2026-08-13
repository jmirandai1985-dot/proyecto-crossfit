"""
Middleware de seguridad HTTP: agrega headers de protección a todas las respuestas.

Previene:
- MIME sniffing (X-Content-Type-Options)
- Clickjacking (X-Frame-Options)
- XSS reflejado antiguo (X-XSS-Protection)
- Downgrade HTTPS (Strict-Transport-Security)
- Inyección de contenido (Content-Security-Policy)
- Fuga de referrer (Referrer-Policy)
- Acceso no deseado a APIs del navegador (Permissions-Policy)
"""
from starlette.middleware.base import BaseHTTPMiddleware


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)

        # Prevenir MIME sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"

        # Prevenir clickjacking
        response.headers["X-Frame-Options"] = "DENY"

        # XSS Protection
        response.headers["X-XSS-Protection"] = "1; mode=block"

        # HSTS (Force HTTPS en producción)
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        # CSP (Content Security Policy)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'"
        )

        # Referrer Policy
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Permissions Policy
        response.headers["Permissions-Policy"] = (
            "geolocation=(), microphone=(), camera=()"
        )

        return response
