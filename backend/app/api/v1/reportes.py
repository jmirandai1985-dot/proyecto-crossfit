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

import logging

from app.db.database import get_db
from app.core.dependencies import get_current_admin
from app.services import metricas_service as metricas

logger = logging.getLogger(__name__)

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
        # El detalle tecnico va SOLO al log del servidor: nunca en la respuesta
        # HTTP (el traceback exponia rutas, SQL y estructura interna).
        logger.error("reportes/monthly-sales tenant=%s %s-%s: %s",
                     tenant_id, mes, anio, e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Error al generar el reporte. El detalle quedo en los logs del servidor.")



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
        # OJO con el nombre: esto cuenta VENCIMIENTOS (estado='vencido' con
        # fecha_expiracion dentro del mes), no cancelaciones explicitas (ese
        # estado no existe en la base). La UI lo rotula "Planes Vencidos (Mes)".
        cancelaciones_mes = db.execute(sql_text("""
            SELECT COUNT(*) FROM suscripciones
            WHERE tenant_id = :tid
              AND estado = 'vencido'
              AND fecha_expiracion >= :inicio
              AND fecha_expiracion <= :fin
        """), {"tid": tenant_id, "inicio": inicio_mes, "fin": fin_mes}).scalar() or 0

        # --- 4. RETENCION (cohorte) ---
        # Definicion COMPARTIDA con el BI (metricas_service.retencion_cohorte):
        # de los alumnos VIGENTES hace 30 dias, cuantos siguen vigentes hoy.
        # Antes se dividia "activos de hoy / activos hace 30 dias", que no es
        # retencion (el numerador incluia a los alumnos nuevos) y por eso un box
        # que crece daba mas de 100%: el caso reportado del 7600%.
        retencion, base_retencion = metricas.retencion_ultimos_30_dias(
            db, tenant_id, ahora.date())

        # --- 5. MRR (INGRESOS MENSUALES RECURRENTES) ---
        # Definicion COMPARTIDA con el BI: metricas_service.mrr (precio de lista
        # de los planes con suscripcion activa vigente en la fecha).
        mrr = metricas.mrr(db, tenant_id, ahora.date())

        # --- 6. INGRESOS DEL MES (neto) ---
        # Definicion COMPARTIDA con el BI: metricas_service.ingresos_netos.
        ingresos_mes = metricas.ingresos_netos(
            db, tenant_id, inicio_mes.date(), fin_mes.date())

        # Mes anterior (misma funcion, otro periodo)
        ingresos_mes_ant = metricas.ingresos_netos(
            db, tenant_id, inicio_mes_ant.date(), fin_mes_ant.date())

        # --- 7. ARPU (Ingresos del mes / alumnos activos) ---
        arpu = round(ingresos_mes / alumnos_activos,
                     0) if alumnos_activos > 0 else 0

        # --- 8. COMPARACION MoM ---
        # Si el mes anterior no es comparable (neto <= 0: sin movimientos o mas
        # egresos que ingresos) NO se devuelve 0% (que se lee como "no crecio"):
        # se devuelve None y la UI muestra "s/d".
        if ingresos_mes_ant > 0:
            crecimiento_mom = int(
                ((ingresos_mes - ingresos_mes_ant) / ingresos_mes_ant) * 100)
        else:
            crecimiento_mom = None

        # --- 9. CLASES IMPARTIDAS ESTE MES ---
        clases_impartidas = db.execute(sql_text("""
            SELECT COUNT(*) FROM clases
            WHERE tenant_id = :tid
              AND fecha >= :inicio_d
              AND fecha <= :fin_d
        """), {"tid": tenant_id, "inicio_d": inicio_mes.date(), "fin_d": fin_mes.date()}).scalar() or 0

        # --- 10. OCUPACION PROMEDIO ---
        # Definicion COMPARTIDA con el BI (monthly_kpis.ocupacion_promedio).
        ocupacion_promedio = metricas.ocupacion_promedio(
            db, tenant_id, inicio_mes.date(), fin_mes.date())

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
            historico_ingresos.append({
                "mes": label_h,
                "ingresos": metricas.ingresos_netos(
                    db, tenant_id, ini_h.date(), fin_h.date()),
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
            "retencion": retencion,  # None si la base no alcanza el minimo
            "tieneDatosRetencion": retencion is not None,
            # Transparencia: base usada y umbral, para explicar el "sin dato".
            "alumnosActivosHace30": base_retencion,
            "retencionBaseMinima": metricas.MIN_BASE_RETENCION,

            # Ingresos
            "mrr": mrr,
            "ingresoMensual": ingresos_mes,
            "ingresoMesAnterior": ingresos_mes_ant,
            "arpu": arpu,
            "crecimientoMensual": crecimiento_mom,  # None si no hay base comparable

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
        # Igual que en /monthly-sales: traceback al log, mensaje generico al cliente.
        logger.error("reportes/ tenant=%s: %s", tenant_id, e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Error al calcular los KPIs. El detalle quedo en los logs del servidor."
        )


MESES = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun',
         'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']
