import React, { useCallback, useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import apiPublica from '../../services/apiPublica';

// ═══════════════════════════════════════════════════════════════════════════
// RANKING DE ASISTENCIA POR PLAN — Pantalla TV pública (sin login, fullscreen)
// Port 1:1 del mockup aprobado `mockup_tv_ranking_v3.html` (referencia visual,
// ya eliminado del repo). Paleta por columna, cintas con puntas triangulares,
// sellos dorado/verde rotados -4°, estrellas grises, marco madera + pizarra
// con glow radial dorado sutil. Sin medallas en el top 3 (el orden de filas ya
// expresa el ranking; todos los 100% muestran el mismo sello).
// ═══════════════════════════════════════════════════════════════════════════

const REFRESH_MS = 5 * 60 * 1000; // auto-refresh cada 5 minutos (decisión confirmada)
const SELLO_PERFECTO = '100% PERFECTO';
const SELLO_MONSTRUO = '🦍 MONSTRUO';

const FONT_TITLE = "'Bebas Neue', 'Oswald', sans-serif";
const FONT_BODY = "'Oswald', 'Segoe UI', sans-serif";

const MESES = [
    'ENERO', 'FEBRERO', 'MARZO', 'ABRIL', 'MAYO', 'JUNIO',
    'JULIO', 'AGOSTO', 'SEPTIEMBRE', 'OCTUBRE', 'NOVIEMBRE', 'DICIEMBRE',
];

// Paleta exacta del mockup por columna (índice = orden de columnas 8,10,12,16,Full).
const TINTS = [
    { // 8 · verde-teal
        ribbon: 'linear-gradient(180deg, #8fd9bd, #5fb896)', texto: '#12241d', tri: '#3f8a6c',
        ribbonFont: '14.5px',
    },
    { // 10 · celeste
        ribbon: 'linear-gradient(180deg, #8fc4e8, #5f9bc0)', texto: '#0f1e28', tri: '#3f7595',
        ribbonFont: '14.5px',
    },
    { // 12 · lila
        ribbon: 'linear-gradient(180deg, #c2b0f2, #9a80e0)', texto: '#1c1530', tri: '#6f52b8',
        ribbonFont: '12.5px',
    },
    { // 16 · naranja
        ribbon: 'linear-gradient(180deg, #ff9a63, #e8712f)', texto: '#2c1408', tri: '#c25520',
        ribbonFont: '12.5px',
    },
    { // Full · dorado
        ribbon: 'linear-gradient(180deg, #f5cf6a, #e0a828)', texto: '#2a1f04', tri: '#b3841a',
        ribbonFont: '12.5px',
    },
];

// ── Estrellas grises (solo las ganadas, sin contorno vacío) ─────────────────
function Estrellas({ n }) {
    return (
        <span
            style={{
                fontSize: 11,
                color: '#5c5646',
                flexShrink: 0,
                fontFamily: FONT_BODY,
                letterSpacing: '0.06em',
            }}
        >
            {'★'.repeat(Math.max(0, n))}
        </span>
    );
}

// ── Sello (chips del mockup, rotados -4°) ───────────────────────────────────
// Dorado para "100% PERFECTO"; verde para "🦍 MONSTRUO" (columna Full).
function Sello({ texto, esMonstruo }) {
    return (
        <span
            style={{
                display: 'inline-block',
                fontSize: 8,
                fontWeight: 800,
                letterSpacing: '0.3px',
                color: '#241f19',
                background: esMonstruo
                    ? 'linear-gradient(180deg, #b8f5c8, #6bc98a)'
                    : 'linear-gradient(180deg, #f5cf6a, #d9a626)',
                padding: '2px 6px',
                borderRadius: 3,
                flexShrink: 0,
                transform: 'rotate(-4deg)',
                boxShadow: '0 2px 4px rgba(0,0,0,0.3)',
                whiteSpace: 'nowrap',
                fontFamily: FONT_BODY,
            }}
        >
            {texto}
        </span>
    );
}

// ── Cinta (banner) con puntas triangulares hacia los costados ───────────────
// Reproduce el CSS del mockup: ::before/::after con border-top + bordes
// laterales transparentes, usando dos <span> absolutos.
function BannerRibbon({ titulo, meta, tint }) {
    return (
        <div style={{ textAlign: 'center', marginBottom: 16 }}>
            <div
                style={{
                    display: 'inline-block',
                    position: 'relative',
                    background: tint.ribbon,
                    color: tint.texto,
                    fontFamily: FONT_TITLE,
                    fontSize: tint.ribbonFont,
                    letterSpacing: '0.5px',
                    padding: '6px 16px 5px',
                    whiteSpace: 'nowrap',
                    boxShadow: '0 3px 6px rgba(0,0,0,0.35)',
                }}
            >
                <span
                    style={{
                        position: 'absolute', top: 0, left: -9, width: 0, height: 0,
                        borderTop: '16px solid ' + tint.tri,
                        borderRight: '9px solid transparent',
                    }}
                />
                <span
                    style={{
                        position: 'absolute', top: 0, right: -9, width: 0, height: 0,
                        borderTop: '16px solid ' + tint.tri,
                        borderLeft: '9px solid transparent',
                    }}
                />
                {titulo}
            </div>
            <div
                style={{
                    fontFamily: FONT_BODY,
                    fontSize: 10,
                    letterSpacing: 1,
                    textTransform: 'uppercase',
                    color: '#8a8272',
                    marginTop: 8,
                }}
            >
                {meta}
            </div>
        </div>
    );
}

// ── Fila del ranking ────────────────────────────────────────────────────────
function FilaRanking({ posicion, fila }) {
    const esIlimitado = fila.contratadas === null;
    const metrica = esIlimitado
        ? String(fila.asistencias)
        : `${fila.asistencias}/${fila.contratadas}`;
    return (
        <div
            style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                padding: '8px 2px',
                borderBottom: '1px solid rgba(243,234,210,0.08)',
            }}
        >
            <span
                style={{
                    fontFamily: FONT_TITLE,
                    fontSize: 14,
                    color: '#8a8272',
                    width: 16,
                    flexShrink: 0,
                }}
            >
                {posicion}
            </span>
            <span
                style={{
                    flex: 1,
                    minWidth: 0,
                    fontFamily: FONT_BODY,
                    fontWeight: 500,
                    fontSize: 12.5,
                    color: '#f3ead2',
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                }}
                title={fila.plan_nombre}
            >
                {fila.nombre}
            </span>
            <span
                style={{
                    fontFamily: FONT_TITLE,
                    fontSize: 14,
                    color: '#e8b23e',
                    flexShrink: 0,
                    whiteSpace: 'nowrap',
                }}
            >
                {metrica}
            </span>
            {fila.sello ? (
                <Sello texto={fila.sello} esMonstruo={fila.sello === SELLO_MONSTRUO} />
            ) : (
                <Estrellas n={fila.estrellas || 0} />
            )}
        </div>
    );
}


// ── Columna del ranking (cinta + filas + footer) ────────────────────────────
function ColumnaRanking({ col, index, maxNoIlimitado }) {
    const tint = TINTS[index] || TINTS[TINTS.length - 1];
    const esIlimitado = col.es_ilimitado;
    const filas = col.top || [];
    const vacias = Array.from({ length: Math.max(0, 10 - filas.length) });

    // Título: nombres de marketing separados por "/" (nm-sep del mockup).
    const titulo = (col.nombres_marketing || []).map((nm, i) => (
        <span key={nm}>
            {i > 0 && <span style={{ fontSize: 10, opacity: 0.5, margin: '0 2px' }}>/</span>}
            {nm}
        </span>
    ));

    const meta = esIlimitado
        ? `ilimitado · vs. ${maxNoIlimitado} (plan más alto)`
        : `${col.tramo_clases} sesiones${col.incluye_estudiante ? ' · incl. estudiante' : ''}`;

    return (
        <div
            style={{
                borderRight: index < TINTS.length - 1
                    ? '1px dashed rgba(243,234,210,0.15)'
                    : 'none',
                padding: '0 16px',
            }}
        >
            <BannerRibbon titulo={titulo} meta={meta} tint={tint} />

            {filas.map((fila, i) => (
                <FilaRanking key={fila.alumno_id ?? i} posicion={i + 1} fila={fila} />
            ))}
            {vacias.map((_, i) => (
                <div
                    key={`v-${i}`}
                    style={{
                        padding: '8px 2px',
                        borderBottom: '1px solid rgba(243,234,210,0.08)',
                    }}
                />
            ))}

            <div
                style={{
                    textAlign: 'center',
                    fontFamily: FONT_BODY,
                    fontSize: 9.5,
                    letterSpacing: 0.5,
                    color: '#5c5646',
                    textTransform: 'uppercase',
                    marginTop: 10,
                    paddingTop: 8,
                    borderTop: '1px dashed rgba(243,234,210,0.1)',
                }}
            >
                {col.alumnos_activos ?? 0} alumnos activos
            </div>
        </div>
    );
}


// ── Componente principal (pantalla TV) ──────────────────────────────────────
function RankingAsistencia() {
    const { boxPublicId } = useParams();
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    const cargar = useCallback(async (silencioso = false) => {
        if (!silencioso) setLoading(true);
        try {
            const res = await apiPublica.get(`/api/v1/ranking/asistencia/${boxPublicId}`);
            setData(res.data);
            setError(null);
        } catch (e) {
            if (!silencioso) {
                setError(
                    e.response && e.response.status === 404
                        ? 'Este box no existe o el enlace es incorrecto.'
                        : 'No se pudo cargar el ranking. Verifica la conexión.'
                );
            }
        } finally {
            if (!silencioso) setLoading(false);
        }
    }, [boxPublicId]);

    useEffect(() => {
        cargar(false);
        // Auto-refresh silencioso cada 5 min (el TV queda sin interacción).
        const id = setInterval(() => cargar(true), REFRESH_MS);
        return () => clearInterval(id);
    }, [cargar]);

    useEffect(() => {
        document.title = data
            ? `Ranking de Asistencia · ${data.box_nombre}`
            : 'Ranking de Asistencia';
    }, [data]);

    // ── Fondo, marco de madera y pizarra (estilos exactos del mockup) ──
    const fondo = {
        minHeight: '100vh',
        minWidth: '100vw',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '40px 20px',
        boxSizing: 'border-box',
        background:
            'radial-gradient(1200px 700px at 50% -10%, rgba(255,255,255,0.03), transparent 60%), linear-gradient(180deg, #3a332a, #241f19)',
        fontFamily: "'Inter', 'Oswald', sans-serif",
    };

    const frame = {
        background: 'linear-gradient(135deg, #8a6b47, #5e4530 40%, #7a5c3c 60%, #4a3524)',
        padding: 22,
        borderRadius: 6,
        boxShadow: '0 40px 80px rgba(0,0,0,0.55), inset 0 0 0 1px rgba(255,255,255,0.06)',
        maxWidth: 1180,
        width: '100%',
    };

    const board = {
        background:
            'radial-gradient(900px 500px at 20% 0%, rgba(240,180,41,0.05), transparent 60%), #171512',
        borderRadius: 3,
        padding: '30px 34px 26px',
        boxShadow: 'inset 0 0 60px rgba(0,0,0,0.5)',
    };

    // ── Estados: carga inicial / error ──
    if (loading) {
        return (
            <div style={{ ...fondo, color: '#f3ead2' }}>
                <div
                    style={{
                        textAlign: 'center',
                        fontFamily: FONT_TITLE,
                        fontSize: 34,
                        letterSpacing: 3,
                    }}
                >
                    CARGANDO RANKING…
                </div>
            </div>
        );
    }

    if (error) {
        return (
            <div style={{ ...fondo, color: '#f3ead2' }}>
                <div
                    style={{
                        background: '#171512',
                        border: '1px solid rgba(243,234,210,0.15)',
                        borderRadius: 6,
                        padding: '30px 40px',
                        textAlign: 'center',
                        boxShadow: '0 40px 80px rgba(0,0,0,0.55)',
                        maxWidth: 480,
                    }}
                >
                    <div style={{ fontFamily: FONT_TITLE, fontSize: 28, letterSpacing: 2 }}>
                        {error}
                    </div>
                    <button
                        onClick={() => cargar(false)}
                        style={{
                            marginTop: 18,
                            fontFamily: FONT_BODY,
                            fontSize: 12,
                            fontWeight: 600,
                            letterSpacing: 1,
                            textTransform: 'uppercase',
                            padding: '8px 18px',
                            border: 'none',
                            borderRadius: 3,
                            cursor: 'pointer',
                            background: 'linear-gradient(180deg, #f5cf6a, #d9a626)',
                            color: '#241f19',
                            boxShadow: '0 2px 4px rgba(0,0,0,0.3)',
                        }}
                    >
                        REINTENTAR
                    </button>
                </div>
            </div>
        );
    }

    const columnas = data?.columnas || [];
    const maxNoIlimitado = data?.max_no_ilimitado ?? 0;
    const [anio, mes] = (data?.mes || '').split('-');
    const mesLabel = MESES[Number(mes) - 1] || data?.mes || '';

    return (
        <div style={fondo}>
            <div style={frame}>
                <div style={board}>
                    {/* Título */}
                    <div
                        style={{
                            textAlign: 'center',
                            fontFamily: FONT_TITLE,
                            fontSize: 34,
                            letterSpacing: 3,
                            color: '#f3ead2',
                            marginBottom: 6,
                            textShadow: '0 2px 0 rgba(0,0,0,0.4)',
                        }}
                    >
                        RANKING DE ASISTENCIA <span style={{ color: '#e8b23e' }}>·</span>{' '}
                        MES DE {mesLabel}
                    </div>
                    <div
                        style={{
                            textAlign: 'center',
                            fontFamily: FONT_BODY,
                            fontWeight: 500,
                            fontSize: 12,
                            letterSpacing: 2,
                            textTransform: 'uppercase',
                            color: '#8a8272',
                            marginBottom: 24,
                        }}
                    >
                        Cerrado · {data?.box_nombre || ''}
                    </div>

                    {/* 5 columnas */}
                    <div
                        style={{
                            display: 'grid',
                            gridTemplateColumns: 'repeat(5, 1fr)',
                            gap: 0,
                        }}
                    >
                        {columnas.map((col, i) => (
                            <ColumnaRanking
                                key={`${col.tramo_clases}-${i}`}
                                col={col}
                                index={i}
                                maxNoIlimitado={maxNoIlimitado}
                            />
                        ))}
                    </div>

                    {/* Leyenda */}
                    <div
                        style={{
                            display: 'flex',
                            justifyContent: 'center',
                            gap: 26,
                            flexWrap: 'wrap',
                            marginTop: 26,
                            paddingTop: 18,
                            borderTop: '1px dashed rgba(243,234,210,0.12)',
                            fontFamily: FONT_BODY,
                            fontSize: 10.5,
                            color: '#8a8272',
                        }}
                    >
                        <div>
                            <b style={{ color: '#e8b23e' }}>100% PERFECTO</b> — cumplió todas
                            las clases contratadas
                        </div>
                        <div>
                            <b style={{ color: '#e8b23e' }}>🦍 Monstruo</b> — Full que superó
                            las {maxNoIlimitado} clases del plan más alto
                        </div>
                        <div>Se actualiza al cierre de cada mes</div>
                    </div>
                </div>
            </div>
        </div>
    );
}

export default RankingAsistencia;

