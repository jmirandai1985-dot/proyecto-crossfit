"""
Rate limiting global (slowapi).

Uso en endpoints:
    @router.post("/login")
    @limiter.limit("5/minute")
    def login(request: Request, ...):
        ...

La clave por defecto es la IP del cliente (get_remote_address).
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

# Límite por IP
limiter = Limiter(key_func=get_remote_address)

# Límites predefinidos reutilizables
LIMIT_LOGIN = "5/minute"          # fuerza bruta de login
LIMIT_REGISTRO = "5/hour"          # abuso de registro masivo
LIMIT_CRITICO = "30/minute"        # cambios sensibles (pagos/aprobaciones)
