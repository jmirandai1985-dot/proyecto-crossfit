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

router = APIRouter()


def _inicio_fin_mes(offset_meses=0):
    """Retorna (inicio_mes, fin_mes) para el mes actual + offset_meses."""
    ahora = datetime.now(timezone.utc)
    # Calcular primer día del MES ACTUAL
    inicio_actual = ahora.replace(
        day=1, hour=0, minute=0, second=0, microsecond=0)
    # Si offset=0: mes actual. Si offset=-1: mes anterior
    inicio = (inicio_actual.replace(day=28) + timedelta(days=4*offset_meses)
              ).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    fin = (inicio + timedelta(days=32)).replace(day=1) - timedelta(seconds=1)
    return inicio, fin


@router.get("/monthly-sales")
def descargar_reporte_ventas_mensual(
    tenant_id: int,
    mes: int,
    anio: int,
    db: Session = Depends(get_db)
):
    """Genera y descarga un reporte Excel con ventas mensuales."""
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
        raise HTTPException(
            status_code=500, detail=f"Error al generar reporte: {str(e)}")


@router.get("/dashboard")
def descargar_reporte_dashboard(
    tenant_id: int,
    mes: int = None,
    anio: int = None,
    db: Session = Depends(get_db)
):
    """Genera un reporte de Dashboard Negocio."""
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
    db: Session = Depends(get_db)
):
    """
    ENDPOINT PRINCIPAL DE KPIs REALES.
    Calcula todos los indicadores desde las tablas reales de la BD.
    """
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

        # Historico ingresos 6 meses - PENDIENTE: no existe tabla de transacciones
        historico_ingresos = []

        # --- RESPUESTA COMPLETA ---
        result = {
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
