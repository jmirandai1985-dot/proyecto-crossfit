"""Cookies de sesión (httpOnly) y token CSRF (double-submit).

Hallazgo #15 de la auditoría de seguridad: el JWT vivía en `localStorage` del
frontend (expuesto a robo vía XSS). Migración a cookie httpOnly:

- `access_token` → cookie httpOnly: el JS del navegador NO puede leerla, así que
  un XSS ya no roba el JWT. `get_current_user` la lee de acá (fallback Bearer).
- `csrf_token` → cookie NO-httpOnly: el frontend la lee con `document.cookie` y
  la devuelve en el header `X-CSRF-Token` en cada request que muta estado. La
  cookie y el header deben coincidir (double-submit) para que un sitio ajeno no
  pueda forjar una mutación amparada en la cookie httpOnly.
"""
import secrets

from fastapi import HTTPException, Request, Response, status

from app.core.config import en_produccion

COOKIE_ACCESS = "access_token"
COOKIE_CSRF = "csrf_token"

# Únicos métodos que validan CSRF: GET (y OPTIONS/HEAD) nunca mutan estado.
METODOS_MUTACION = ("POST", "PUT", "PATCH", "DELETE")


def _cookie_secure() -> bool:
    """`Secure` sólo en producción: en TEST/dev local no hay HTTPS.

    Sigue el mismo patrón de entorno del proyecto (`ENVIRONMENT=production`):
    si el proceso no declara producción, la cookie NO lleva `Secure` para no
    romper el desarrollo local (el navegador no envía cookies `Secure` por HTTP).
    """
    return en_produccion()


def generar_csrf_token() -> str:
    """Token CSRF aleatorio (double-submit)."""
    return secrets.token_urlsafe(32)


def set_auth_cookies(
    response: Response,
    access_token: str,
    csrf_token: str,
    max_age: int,
) -> None:
    """Setea las dos cookies de sesión tras un login válido.

    `access_token` (httpOnly) guarda el JWT; `csrf_token` (legible por JS)
    habilita el double-submit en las mutaciones.
    """
    secure = _cookie_secure()
    response.set_cookie(
        key=COOKIE_ACCESS,
        value=access_token,
        httponly=True,
        secure=secure,
        samesite="strict",
        path="/",
        max_age=max_age,
    )
    response.set_cookie(
        key=COOKIE_CSRF,
        value=csrf_token,
        httponly=False,
        secure=secure,
        samesite="strict",
        path="/",
        max_age=max_age,
    )


def clear_auth_cookies(response: Response) -> None:
    """Limpia ambas cookies (Max-Age=0) en el logout."""
    secure = _cookie_secure()
    response.set_cookie(
        key=COOKIE_ACCESS,
        value="",
        httponly=True,
        secure=secure,
        samesite="strict",
        path="/",
        max_age=0,
    )
    response.set_cookie(
        key=COOKIE_CSRF,
        value="",
        httponly=False,
        secure=secure,
        samesite="strict",
        path="/",
        max_age=0,
    )


def validar_csrf(request: Request) -> None:
    """Double-submit: `X-CSRF-Token` debe coincidir con la cookie `csrf_token`.

    Si falta cualquiera de los dos o no coinciden → 403. Sólo se invoca para
    requests de mutación autenticados por cookie (ver `get_current_user`).
    """
    cookie = request.cookies.get(COOKIE_CSRF, "")
    header = request.headers.get("X-CSRF-Token", "")
    if not cookie or not header or not secrets.compare_digest(cookie, header):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF: falta el header X-CSRF-Token o no coincide con la cookie",
        )
