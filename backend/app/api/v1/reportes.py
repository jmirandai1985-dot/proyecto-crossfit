"""
Router de endpoints para generación de Reportes Excel y KPIs del Dashboard
"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, text as sql_text
from datetime import datetime, timezone, timedelta
import io
from typing import Optional

from app.db.database import get_db
from app.core.dependencies import get_current_admin

router = APIRouter()


def _inicio_fin_mes(offset_meses=0):
    """Retorna (inicio_mes, fin_mes) para el mes actual + offset_meses.

    FIX S12b: la versión anterior usaba (day=28 + 4*offset).replace(day=1), que
    para offsets -1..-5 colapsaba al MES ACTUAL (28-4=24, 28-8=20, ... siempre
    dentro del mismo mes). Consecuencia: ingresos_mes_ant, historico_membresias
    e historico_ingresos mostraban siempre el mes actual. Se reemplaza por
    aritmética de meses (calendar-safe, no depende de la duración del mes).
    """
    ahora = datetime.now(timezone.utc)
    # Primer día del MES ACTUAL
    inicio_actual = ahora.replace(
        day=1, hour=0, minute=0, second=0, microsecond=0)
    # Desplazamiento en meses sin depender de la duración del mes
    total_meses = inicio_actual.year * 12 + (inicio_actual.month - 1) + offset_meses
    anio_obj = total_meses // 12
    mes_obj = total_meses % 12 + 1
    inicio = inicio_actual.replace(
        year=anio_obj, month=mes_obj, day=1,
        hour=0, minute=0, second=0, microsecond=0)
    fin = (inicio + timedelta(days=32)).replace(day=1) - timedelta(seconds=1)
    return inicio, fin


@router.get("/monthly-sales")
def descargar_reporte_ventas_mensual(
    tenant_id: int,
    mes: int,
    anio: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Genera y descarga un reporte Excel con ventas mensuales. Solo admin (su tenant)."""
    # 🔒 El admin solo puede descargar reportes de su propio tenant
    if current_user.get("tenant_id") != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes acceso a este tenant",
        )
    from app.services.reportes_service import crear_reporte_ventas_mensual_bytes
    if mes < 1 or mes > 12:
        raise HTTPException(
            status_code=400, detail="Mes debe estar entre 1 y 12")
    if anio < 2000 or anio > 2100:
        raise HTTPException(
            status_code=400, detail="Año debe estar entre 2000 y 2100")
    try:
        excel_bytes = crear_reporte_ventas_mensual_bytes(
            db=db, tenant_id=tenant_id, mes=mes, anio=anio)
        filename = f"reporte_ventas_{mes:02d}_{anio}.xlsx"
        return StreamingResponse(
            io.BytesIO(excel_bytes),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Access-Control-Expose-Headers": "Content-Disposition",
            }
        )
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print(f"ERROR REPORT: {tb}")
        raise HTTPException(
            status_code=500, detail=f"Error al generar reporte: {str(e)} | {tb[:500]}")


@router.get("/dashboard")
def descargar_reporte_dashboard(
    tenant_id: int,
    mes: int = None,
    anio: int = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Genera un reporte de Dashboard Negocio. Solo admin (su tenant)."""
    # 🔒 El admin solo puede descargar reportes de su propio tenant
    if current_user.get("tenant_id") != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes acceso a este tenant",
        )
    from app.services.reportes_service import crear_reporte_ventas_mensual_bytes
    if mes is None or anio is None:
        ahora = datetime.now()
        mes = mes or ahora.month
        anio = anio or ahora.year
    try:
        excel_bytes = crear_reporte_ventas_mensual_bytes(
            db=db, tenant_id=tenant_id, mes=mes, anio=anio)
        filename = f"dashboard_{mes:02d}_{anio}.xlsx"
        return StreamingResponse(
            io.BytesIO(excel_bytes),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error al generar dashboard: {str(e)}")


@router.get("/")
def obtener_reportes_analytics(
    tenant_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """
    ENDPOINT PRINCIPAL DE KPIs REALES.
    Calcula todos los indicadores desde las tablas reales de la BD.
    Solo admin (su tenant).
    """
    # 🔒 El admin solo puede ver KPIs de su propio tenant
    if current_user.get("tenant_id") != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes acceso a este tenant",
        )
    try:
        ahora = datetime.now(timezone.utc)
        mes_actual_num = ahora.month
        anio_actual = ahora.year

        # --- PERIODOS ---
        inicio_mes, fin_mes = _inicio_fin_mes(0)
        inicio_mes_ant, fin_mes_ant = _inicio_fin_mes(-1)
        hace_30_dias = ahora - timedelta(days=30)

        # --- 1. ALUMNOS ACTIVOS ---
        # Alumnos con rol='alumno' Y suscripcion activa vigente (fecha_expiracion >= hoy)
        alumnos_activos = db.execute(sql_text("""
            SELECT COUNT(DISTINCT u.id)
            FROM usuarios u
            JOIN suscripciones s ON u.id = s.usuario_id
            WHERE u.tenant_id = :tid
              AND u.rol = 'alumno'
              AND u.activo = true
              AND s.estado = 'activo'
              AND s.fecha_expiracion >= CURRENT_DATE
        """), {"tid": tenant_id}).scalar() or 0

        # --- 2. NUEVOS ALUMNOS ESTE MES ---
        nuevos_alumnos_mes = db.execute(sql_text("""
            SELECT COUNT(*) FROM usuarios
            WHERE tenant_id = :tid
              AND rol = 'alumno'
              AND created_at >= :inicio
              AND created_at <= :fin
        """), {"tid": tenant_id, "inicio": inicio_mes, "fin": fin_mes}).scalar() or 0

        # --- 3. CANCELACIONES ESTE MES ---
        # Suscripciones que expiraron o se cancelaron este mes
        cancelaciones_mes = db.execute(sql_text("""
            SELECT COUNT(*) FROM suscripciones
            WHERE tenant_id = :tid
              AND estado = 'vencido'
              AND fecha_expiracion >= :inicio
              AND fecha_expiracion <= :fin
        """), {"tid": tenant_id, "inicio": inicio_mes, "fin": fin_mes}).scalar() or 0

        # --- 4. RETENCION ---
        # Alumnos activos hace 30 días que siguen activos hoy
        # DEFINICIÓN: alumnos con suscripción activa hace 30 días / alumnos con suscripción activa hoy
        alumnos_activos_hace_30 = db.execute(sql_text("""
            SELECT COUNT(DISTINCT u.id)
            FROM usuarios u
            JOIN suscripciones s ON u.id = s.usuario_id
            WHERE u.tenant_id = :tid
              AND u.rol = 'alumno'
              AND u.activo = true
              AND s.estado = 'activo'
              AND s.fecha_inicio <= :hace30
              AND s.fecha_expiracion >= :hace30
        """), {"tid": tenant_id, "hace30": hace_30_dias}).scalar() or 0

        if alumnos_activos_hace_30 > 0:
            retencion = int((alumnos_activos / alumnos_activos_hace_30) * 100)
        else:
            retencion = None  # "Sin datos suficientes"

        # --- 5. MRR (INGRESOS MENSUALES RECURRENTES) ---
        # Suma de precio de planes con suscripción activa vigente
        mrr = db.execute(sql_text("""
            SELECT COALESCE(SUM(p.precio_clp), 0)
            FROM suscripciones s
            JOIN planes p ON s.plan_id = p.id
            WHERE s.tenant_id = :tid
              AND s.estado = 'activo'
              AND s.fecha_expiracion >= CURRENT_DATE
        """), {"tid": tenant_id}).scalar() or 0
        mrr = float(mrr)

        # --- 6. INGRESOS TOTALES DEL MES (desde transacciones_financieras reales) ---
        # Suma de ingresos - egresos del mes actual
        ing_mes = db.execute(sql_text("""
            SELECT COALESCE(SUM(CASE WHEN tipo='ingreso' THEN monto ELSE 0 END), 0)
            FROM transacciones_financieras
            WHERE tenant_id = :tid AND fecha >= :inicio_d AND fecha <= :fin_d
        """), {"tid": tenant_id, "inicio_d": inicio_mes.date(), "fin_d": fin_mes.date()}).scalar() or 0
        eg_mes = db.execute(sql_text("""
            SELECT COALESCE(SUM(CASE WHEN tipo='egreso' THEN monto ELSE 0 END), 0)
            FROM transacciones_financieras
            WHERE tenant_id = :tid AND fecha >= :inicio_d AND fecha <= :fin_d
        """), {"tid": tenant_id, "inicio_d": inicio_mes.date(), "fin_d": fin_mes.date()}).scalar() or 0
        ingresos_mes = float(ing_mes) - float(eg_mes)

        # Mes anterior
        ing_mes_ant = db.execute(sql_text("""
            SELECT COALESCE(SUM(CASE WHEN tipo='ingreso' THEN monto ELSE 0 END), 0)
            FROM transacciones_financieras
            WHERE tenant_id = :tid AND fecha >= :ini_ant AND fecha <= :fin_a
        """), {"tid": tenant_id, "ini_ant": inicio_mes_ant.date(), "fin_a": fin_mes_ant.date()}).scalar() or 0
        eg_mes_ant = db.execute(sql_text("""
            SELECT COALESCE(SUM(CASE WHEN tipo='egreso' THEN monto ELSE 0 END), 0)
            FROM transacciones_financieras
            WHERE tenant_id = :tid AND fecha >= :ini_ant AND fecha <= :fin_a
        """), {"tid": tenant_id, "ini_ant": inicio_mes_ant.date(), "fin_a": fin_mes_ant.date()}).scalar() or 0
        ingresos_mes_ant = float(ing_mes_ant) - float(eg_mes_ant)

        # --- 7. ARPU (Ingresos del mes / alumnos activos) ---
        arpu = round(ingresos_mes / alumnos_activos,
                     0) if alumnos_activos > 0 else 0

        # --- 8. COMPARACION MoM ---
        if ingresos_mes_ant > 0:
            crecimiento_mom = int(
                ((ingresos_mes - ingresos_mes_ant) / ingresos_mes_ant) * 100)
        else:
            crecimiento_mom = 0

        # --- 9. CLASES IMPARTIDAS ESTE MES ---
        clases_impartidas = db.execute(sql_text("""
            SELECT COUNT(*) FROM clases
            WHERE tenant_id = :tid
              AND fecha >= :inicio_d
              AND fecha <= :fin_d
        """), {"tid": tenant_id, "inicio_d": inicio_mes.date(), "fin_d": fin_mes.date()}).scalar() or 0

        # --- 10. OCUPACION PROMEDIO REAL ---
        ocupacion = db.execute(sql_text("""
            SELECT
                COALESCE(SUM(COALESCE(c.asistentes_confirmados, 0)), 0),
                COALESCE(SUM(COALESCE(c.cupo_maximo, 1)), 0)
            FROM clases c
            WHERE c.tenant_id = :tid
              AND c.fecha >= :inicio_d
              AND c.fecha <= :fin_d
        """), {"tid": tenant_id, "inicio_d": inicio_mes.date(), "fin_d": fin_mes.date()}).first()
        total_asistentes = ocupacion[0] or 0
        total_cupo = ocupacion[1] or 0
        ocupacion_promedio = round(
            total_asistentes / total_cupo * 100) if total_cupo > 0 else 0

        # --- 11. OCUPACION POR DISCIPLINA ---
        ocupacion_por_disciplina = []
        disc_rows = db.execute(sql_text("""
            SELECT d.id, d.nombre,
                   COUNT(c.id) as total_clases,
                   COALESCE(SUM(COALESCE(c.asistentes_confirmados, 0)), 0) as asistentes,
                   COALESCE(SUM(COALESCE(c.cupo_maximo, 1)), 0) as cupo
            FROM clases c
            JOIN disciplinas d ON c.disciplina_id = d.id
            WHERE c.tenant_id = :tid
              AND c.fecha >= :inicio_d
              AND c.fecha <= :fin_d
            GROUP BY d.id, d.nombre
            ORDER BY d.id
        """), {"tid": tenant_id, "inicio_d": inicio_mes.date(), "fin_d": fin_mes.date()}).fetchall()
        for r in disc_rows:
            cupo = r.cupo or 0
            pct = round(r.asistentes / cupo * 100) if cupo > 0 else 0
            # Alumnos unicos con reserva confirmada (asistio=true) en esta disciplina este mes
            alumnos_unicos = db.execute(sql_text("""
                SELECT COUNT(DISTINCT r.alumno_id)
                FROM reservas r
                JOIN clases c ON r.clase_id = c.id
                WHERE c.tenant_id = :tid AND c.disciplina_id = :did
                  AND r.asistio = true
                  AND c.fecha >= :ini_d AND c.fecha <= :fin_d
            """), {"tid": tenant_id, "did": r.id, "ini_d": inicio_mes.date(), "fin_d": fin_mes.date()}).scalar() or 0
            ocupacion_por_disciplina.append({
                "id": r.id,
                "nombre": r.nombre.strip() if r.nombre else "—",
                "clases": r.total_clases,
                "asistentes": r.asistentes,
                "cupo_total": cupo,
                "alumnos_unicos": alumnos_unicos,
                "ocupacion_pct": pct
            })

        # --- 12. CLASES POR COACH ESTE MES ---
        clases_por_coach = []
        coach_rows = db.execute(sql_text("""
            SELECT u.id, u.nombre, COUNT(c.id) as total_clases
            FROM clases c
            JOIN usuarios u ON c.coach_id = u.id
            WHERE c.tenant_id = :tid
              AND c.fecha >= :inicio_d
              AND c.fecha <= :fin_d
              AND c.coach_id IS NOT NULL
            GROUP BY u.id, u.nombre
            ORDER BY total_clases DESC
        """), {"tid": tenant_id, "inicio_d": inicio_mes.date(), "fin_d": fin_mes.date()}).fetchall()
        for r in coach_rows:
            clases_por_coach.append({
                "id": r.id,
                "nombre": r.nombre,
                "clases": r.total_clases
            })

        # --- 13. COBERTURAS DE EMERGENCIA ESTE MES ---
        coberturas_mes = db.execute(sql_text("""
            SELECT COUNT(*) FROM cobertura_emergencia
            WHERE tenant_id = :tid
              AND created_at >= :inicio
              AND created_at <= :fin
        """), {"tid": tenant_id, "inicio": inicio_mes, "fin": fin_mes}).scalar() or 0

        # --- 14. PLANES VENDIDOS ESTE MES ---
        planes_vendidos = []
        # --- 14b. SUSCRIPCIONES DEL MES (detalle por alumno/plan/fecha) ---
        suscripciones_mes = []
        sub_rows = db.execute(sql_text("""
            SELECT u.nombre AS alumno_nombre, p.nombre AS plan_nombre, s.fecha_inicio
            FROM suscripciones s
            JOIN usuarios u ON s.usuario_id = u.id
            JOIN planes p ON s.plan_id = p.id
            WHERE s.tenant_id = :tid
              AND s.fecha_inicio >= :inicio
              AND s.fecha_inicio <= :fin
            ORDER BY s.fecha_inicio DESC
        """), {"tid": tenant_id, "inicio": inicio_mes, "fin": fin_mes}).fetchall()
        for r in sub_rows:
            suscripciones_mes.append({
                "alumno_nombre": r.alumno_nombre,
                "plan_nombre": r.plan_nombre,
                "fecha_inicio": str(r.fecha_inicio)[:10] if r.fecha_inicio else None,
            })
        plan_rows = db.execute(sql_text("""
            SELECT p.id, p.nombre, COUNT(s.id) as total
            FROM suscripciones s
            JOIN planes p ON s.plan_id = p.id
            WHERE s.tenant_id = :tid
              AND s.fecha_inicio >= :inicio
              AND s.fecha_inicio <= :fin
            GROUP BY p.id, p.nombre
            ORDER BY total DESC
        """), {"tid": tenant_id, "inicio": inicio_mes, "fin": fin_mes}).fetchall()
        for r in plan_rows:
            planes_vendidos.append({
                "id": r.id,
                "nombre": r.nombre,
                "vendidos": r.total
            })

        # --- 15. HISTORICO 6 MESES (suscripciones nuevas por mes) ---
        historico_membresias = []
        for i in range(5, -1, -1):
            ini, _ = _inicio_fin_mes(-i)
            label = f"{MESES[ini.month - 1]} {ini.year}"
            cnt = db.execute(sql_text("""
                SELECT COUNT(*) FROM suscripciones
                WHERE tenant_id = :tid
                  AND fecha_inicio >= :ini
                  AND fecha_inicio <= :fin
            """), {"tid": tenant_id, "ini": ini, "fin": (ini + timedelta(days=32)).replace(day=1) - timedelta(seconds=1)}).scalar() or 0
            historico_membresias.append({"mes": label, "membresias": cnt})

        # --- 15b. HISTORICO INGRESOS 6 MESES (desde transacciones_financieras) ---
        # FIX S12: antes hardcodeado [] con comentario desactualizado ("no existe
        # tabla de transacciones"). La tabla SI existe y es la misma fuente que
        # ingresos_mes: se agrupa por mes (ingreso - egreso) los ultimos 6 meses.
        historico_ingresos = []
        for i in range(5, -1, -1):
            ini_h, fin_h = _inicio_fin_mes(-i)
            label_h = f"{MESES[ini_h.month - 1]} {ini_h.year}"
            ing_h = db.execute(sql_text("""
                SELECT COALESCE(SUM(CASE WHEN tipo='ingreso' THEN monto ELSE 0 END), 0)
                FROM transacciones_financieras
                WHERE tenant_id = :tid AND fecha >= :ini_d AND fecha <= :fin_d
            """), {"tid": tenant_id, "ini_d": ini_h.date(), "fin_d": fin_h.date()}).scalar() or 0
            eg_h = db.execute(sql_text("""
                SELECT COALESCE(SUM(CASE WHEN tipo='egreso' THEN monto ELSE 0 END), 0)
                FROM transacciones_financieras
                WHERE tenant_id = :tid AND fecha >= :ini_d AND fecha <= :fin_d
            """), {"tid": tenant_id, "ini_d": ini_h.date(), "fin_d": fin_h.date()}).scalar() or 0
            historico_ingresos.append({
                "mes": label_h,
                "ingresos": float(ing_h) - float(eg_h),
            })

        # --- RESPUESTA COMPLETA ---
        result = {
            # Suscripciones del mes (detalle para modal)
            "suscripcionesMes": suscripciones_mes,
            "totalSuscripcionesMes": len(suscripciones_mes),
            # Membresía / Clientes
            "alumnosActivos": alumnos_activos,
            "nuevosAlumnosMes": nuevos_alumnos_mes,
            "cancelacionesMes": cancelaciones_mes,
            "retencion": retencion,  # None si no hay datos
            "tieneDatosRetencion": retencion is not None,

            # Ingresos
            "mrr": mrr,
            "ingresoMensual": ingresos_mes,
            "ingresoMesAnterior": ingresos_mes_ant,
            "arpu": arpu,
            "crecimientoMensual": crecimiento_mom,

            # Ocupación
            "clasesImpartidas": clases_impartidas,
            "asistenciaPromedio": ocupacion_promedio,
            "ocupacionPorDisciplina": ocupacion_por_disciplina,

            # Coaches
            "clasesPorCoach": clases_por_coach,
            "coberturasEmergencia": coberturas_mes,

            # Planes
            "planesVendidos": planes_vendidos,

            # Histórico para gráficos
            "historicoMembresias": historico_membresias,
            "historicoIngresos": historico_ingresos,
        }
        return result

    except Exception as e:
        import traceback
        raise HTTPException(
            status_code=500,
            detail=f"Error al obtener KPIs: {str(e)} | {traceback.format_exc()}"
        )


MESES = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun',
         'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']
