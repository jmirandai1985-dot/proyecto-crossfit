"""Vista previa de comprobantes: `loading` NUNCA puede quedar sin desenlace.

Bug de PROD ("Revisar comprobante" colgado): el hook compartido pedía el blob con
`api.get(...)` a secas y el cliente axios NO tiene timeout, así que una petición que
no respondía dejaba la hoja en "Cargando el comprobante…" PARA SIEMPRE, sin error y
sin forma de reintentar (el admin no podía revisar el pago del alumno). Es el MISMO
caso ya corregido en el aviso de retiro (utils/avisoRetiro.js) y la corrección
reutiliza SUS constantes: una sola definición de "sin desenlace" en todo el panel.

Guard de fuente del FRONTEND (sin red y sin base):

  A. El hook pide el blob CON plazo: reloj (`Promise.race`) + `AbortController`, y
     el caso "sin desenlace" cae en `MSG_TIMEOUT` (no en un detalle técnico).
  B. Existe `reintentar()` y el reloj vuelve a correr al reintentar.
  C. La hoja móvil y el modal de escritorio muestran el motivo + Reintentar.
  D. El tile "Vouchers por aprobar" ya no le pasa el EVENTO a `abrirRevision`.

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_voucher_preview_sin_desenlace_front.py -q --noconftest
"""
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]          # .../proyecto-crossfit
HOOK = "frontend/src/hooks/useDocumentoAutenticado.js"
AVISO = "frontend/src/utils/avisoRetiro.js"
MOVIL = "frontend/src/pages/admin/InicioMobileAdmin.jsx"
ESCRITORIO = "frontend/src/pages/admin/Dashboard.jsx"


def _fuente(rel: str) -> str:
    return (RAIZ / rel).read_text(encoding="utf-8")


def test_a_el_hook_pide_el_blob_con_plazo():
    h = _fuente(HOOK)
    # La petición ya no puede salir "pelada": sin plazo, una red muda la deja colgada.
    assert "api.get(previewUrl, { responseType: 'blob' })" not in h, \
        "la vista previa volvió a pedirse SIN plazo: sin desenlace no hay salida"
    for linea in ("api.get(previewUrl, { responseType: 'blob', signal: control.signal })",
                  "const control = new AbortController();",
                  "const expiro = new Promise((_, rechazar) => {",
                  "const res = await Promise.race([",
                  "control.abort();",
                  "}, timeoutMs);"):
        assert linea in h, f"falta el plazo en la vista previa: {linea}"
    # El motivo del vencimiento es el MISMO mensaje del aviso de retiro (una sola
    # definición de "la red no respondió" en el panel).
    assert "import { AVISO_TIMEOUT_MS, MSG_TIMEOUT, esTimeout } from '../utils/avisoRetiro';" in h
    assert "export const PREVIEW_TIMEOUT_MS = AVISO_TIMEOUT_MS;" in h
    assert "error: esTimeout(err) ? MSG_TIMEOUT : await detalleDeErrorBlob(err)," in h
    assert "export const AVISO_TIMEOUT_MS = 12000;" in _fuente(AVISO)
    # `loading` sólo puede terminar en error o en blob: nunca se queda encendido.
    assert "loading: false, blobUrl: '', mime: ''," in h


def test_b_reintentar_vuelve_a_correr_el_plazo():
    h = _fuente(HOOK)
    assert "const reintentar = useCallback(() => setReintento((n) => n + 1), []);" in h
    assert "}, [previewUrl, reintento, timeoutMs]);" in h, \
        "Reintentar tiene que volver a disparar la petición (dependencia `reintento`)"
    assert "return { preview, descargando, descargar, reintentar };" in h
    # Al cambiar de documento o desmontar se corta el reloj y la conexión vieja.
    assert "clearTimeout(reloj);" in h
    assert "control.abort();" in h.split("return () => {", 1)[1], \
        "el cleanup tiene que abortar la petición en vuelo"


def test_c_las_dos_pantallas_muestran_el_motivo_y_ofrecen_reintentar():
    movil = _fuente(MOVIL)
    assert "onClick={voucherDoc.reintentar}" in movil, \
        "la hoja móvil del comprobante tiene que ofrecer Reintentar"
    assert "{voucherDoc.preview.error}" in movil
    assert "Cargando el comprobante…" in movil
    escritorio = _fuente(ESCRITORIO)
    assert "reintentar: reintentarVoucher," in escritorio
    assert "onClick={reintentarVoucher}" in escritorio, \
        "el modal de escritorio del voucher tiene que ofrecer Reintentar"
    assert "{voucherPreview.error}" in escritorio


def test_d_el_tile_no_le_pasa_el_evento_a_abrir_revision():
    movil = _fuente(MOVIL)
    assert "onClick={() => abrirRevision()}" in movil, \
        "el tile del KPI tiene que abrir la PRIMERA solicitud, no recibir el evento"
    assert "onClick={abrirRevision}" not in movil
    # El handler sigue aceptando una fila concreta (la lista y el tile comparten puerta).
    assert "const abrirRevision = (solicitud) => {" in movil
    assert "setRevision(solicitud || vouchers[0] || null);" in movil
