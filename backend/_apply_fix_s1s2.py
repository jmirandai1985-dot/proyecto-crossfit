"""Aplica los fixes S1 y S2 en solicitudes_planes.py preservando CRLF.

S1: GET /{id}/voucher  -> control de propiedad (dueño) + staff del mismo tenant (403).
S2: PUT /{id}/aprobar y /{id}/rechazar -> filtro tenant_id del token (404 si no pertenece).
"""
import io

PATH = r"c:\Users\Asus\Desktop\Proyectos\proyecto-crossfit\backend\app\api\v1\solicitudes_planes.py"

with io.open(PATH, "r", encoding="utf-8", newline="") as f:
    src = f.read()

BLOCK_SOLICITUD_404 = (
    '    solicitud = db.query(SolicitudPlan).filter(\n'
    '        SolicitudPlan.id == solicitud_id).first()\n'
    '    if not solicitud:\n'
    '        raise HTTPException(status_code=404, detail="Solicitud no encontrada")\n'
)

# --- FIX S1: voucher ---
S1_OLD = (
    BLOCK_SOLICITUD_404 +
    '\n'
    '    if not solicitud.voucher_url:\n'
    '        raise HTTPException(status_code=404, detail="Sin voucher disponible")\n'
)
S1_NEW = (
    BLOCK_SOLICITUD_404 +
    '\n'
    '    # ── FIX S1 (seguridad): control de propiedad/tenant ──\n'
    '    # El voucher es un comprobante de pago sensible. Solo pueden descargarlo:\n'
    '    # (a) el alumno dueño de la solicitud, o (b) un admin/coach del MISMO box\n'
    '    # al que pertenece la solicitud. Sin esto, cualquier usuario autenticado\n'
    '    # podía leer vouchers ajenos de cualquier tenant con solo cambiar el id (IDOR).\n'
    '    rol = current_user.get("rol", "")\n'
    '    es_dueno = current_user["usuario_id"] == solicitud.alumno_id\n'
    '    es_staff_mismo_box = (\n'
    '        rol in ("coach", "admin", "administrador")\n'
    '        and current_user["tenant_id"] == solicitud.tenant_id\n'
    '    )\n'
    '    if not (es_dueno or es_staff_mismo_box):\n'
    '        # 403 explícito (convención del proyecto: no silenciar la autorización)\n'
    '        raise HTTPException(\n'
    '            status_code=status.HTTP_403_FORBIDDEN,\n'
    '            detail="No puedes descargar el voucher de esta solicitud",\n'
    '        )\n'
    '\n'
    '    if not solicitud.voucher_url:\n'
    '        raise HTTPException(status_code=404, detail="Sin voucher disponible")\n'
)

# --- FIX S2: aprobar ---
S2A_OLD = (
    BLOCK_SOLICITUD_404 +
    '\n'
    '    solicitud.estado = "approved"\n'
)
S2A_NEW = (
    '    # ── FIX S2 (seguridad): la solicitud debe ser del tenant del admin ──\n'
    '    # Un admin del box A ya no puede aprobar solicitudes del box B (cross-tenant).\n'
    '    # Se devuelve 404 (no 403) para no revelar que el id existe en otro tenant.\n'
    '    solicitud = db.query(SolicitudPlan).filter(\n'
    '        SolicitudPlan.id == solicitud_id,\n'
    '        SolicitudPlan.tenant_id == current_user["tenant_id"],\n'
    '    ).first()\n'
    '    if not solicitud:\n'
    '        raise HTTPException(status_code=404, detail="Solicitud no encontrada")\n'
    '\n'
    '    solicitud.estado = "approved"\n'
)

# --- FIX S2: rechazar ---
S2R_OLD = (
    BLOCK_SOLICITUD_404 +
    '\n'
    '    solicitud.estado = "rejected"\n'
)
S2R_NEW = (
    '    # ── FIX S2 (seguridad): la solicitud debe ser del tenant del admin ──\n'
    '    # Un admin del box A ya no puede rechazar solicitudes del box B (cross-tenant).\n'
    '    # Se devuelve 404 (no 403) para no revelar que el id existe en otro tenant.\n'
    '    solicitud = db.query(SolicitudPlan).filter(\n'
    '        SolicitudPlan.id == solicitud_id,\n'
    '        SolicitudPlan.tenant_id == current_user["tenant_id"],\n'
    '    ).first()\n'
    '    if not solicitud:\n'
    '        raise HTTPException(status_code=404, detail="Solicitud no encontrada")\n'
    '\n'
    '    solicitud.estado = "rejected"\n'
)


def aplicar(texto, tag, old, new):
    old_crlf = old.replace("\n", "\r\n")
    new_crlf = new.replace("\n", "\r\n")
    n = texto.count(old_crlf)
    if n != 1:
        raise SystemExit(f"[{tag}] bloque no encontrado o ambiguo (matches={n})")
    texto = texto.replace(old_crlf, new_crlf)
    print(f"[{tag}] OK - reemplazo aplicado")
    return texto


src = aplicar(src, "S1 voucher", S1_OLD, S1_NEW)
src = aplicar(src, "S2 aprobar", S2A_OLD, S2A_NEW)
src = aplicar(src, "S2 rechazar", S2R_OLD, S2R_NEW)

with io.open(PATH, "w", encoding="utf-8", newline="") as f:
    f.write(src)

print("Listo: 3 fixes aplicados preservando CRLF.")
