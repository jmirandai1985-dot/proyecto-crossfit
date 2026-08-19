"""
Middleware ligero para detectar el patrón inseguro de multi-tenancy:
requests donde `tenant_id` llega como None o 1 (default hardcodeado) desde el
query o el body del cliente.

SOLO LOGUEA en nivel warning — no bloquea ni modifica la request.
Sirve para priorizar qué endpoints migrar al patrón "tenant_id derivado del
JWT" (ver SECURITY.md, PR-04 / Fase 1).
"""
import json
import logging

from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("uvicorn.tenant_audit")

# Valores que delatan el patrón inseguro: ausente (None) o el default hardcodeado 1
_VALORES_SOSPECHOSOS = (None, 1)


class TenantAuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        client_ip = request.client.host if request.client else "desconocida"
        method = request.method
        path = request.url.path

        # ── 1) tenant_id en query params ──
        try:
            tenant_query = request.query_params.get("tenant_id")
            if tenant_query is not None:
                try:
                    tenant_value = int(tenant_query) if tenant_query else None
                except ValueError:
                    tenant_value = None
                if tenant_value in _VALORES_SOSPECHOSOS:
                    logger.warning(
                        "TENANT_AUDIT query tenant_id=%s %s %s ip=%s",
                        tenant_value, method, path, client_ip,
                    )
        except Exception:
            pass  # Nunca debe romper la request por un problema del log

        # ── 2) tenant_id en body JSON ──
        # Starlette cachea el body (request._body), por lo que el handler
        # downstream puede volver a leerlo sin problema.
        if method in ("POST", "PUT", "PATCH", "DELETE"):
            try:
                body_bytes = await request.body()
                if body_bytes:
                    try:
                        data = json.loads(body_bytes)
                    except (ValueError, TypeError):
                        data = None
                    if isinstance(data, dict) and "tenant_id" in data:
                        if data.get("tenant_id") in _VALORES_SOSPECHOSOS:
                            logger.warning(
                                "TENANT_AUDIT body tenant_id=%s %s %s ip=%s",
                                data.get("tenant_id"), method, path, client_ip,
                            )
            except Exception:
                pass  # Ídem

        response = await call_next(request)
        return response
