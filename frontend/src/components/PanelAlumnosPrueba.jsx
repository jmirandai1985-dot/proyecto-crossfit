/**
 * Pantalla "Alumnos nuevos y en prueba" — COMPARTIDA por el Inicio móvil del
 * admin (<768px) y la ruta de escritorio `/admin/alumnos-prueba`.
 *
 * Recibe el estado de `useAlumnosPrueba` (mismos endpoints y mismos errores por
 * sección) y pinta los DOS listados + la vista previa del correo manual. No hace
 * fetch por su cuenta: así el Inicio móvil puede usar el contador de la tarjeta
 * y la pantalla sin pedir dos veces lo mismo.
 *
 * `embebido` es para la ruta de escritorio: el CSS deja de ser una capa `fixed`
 * y pasa a ser una tarjeta dentro del Layout (ver inicioMobileAdmin.css).
 */
import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../services/api';
import { textoHace } from '../utils/hace';
import { iniciales } from '../utils/iniciales';
import {
    textoEstadoPrueba, tonoEstadoPrueba, textoAlta, textoEnPrueba,
} from '../utils/pruebaAlumnos';

const PanelAlumnosPrueba = ({
    estado, onVolver, onToast = null, embebido = false,
}) => {
    const navigate = useNavigate();
    const [correo, setCorreo] = useState(null);
    // Sin `onToast` (ruta de escritorio) el aviso se pinta acá; con `onToast`
    // (Inicio móvil) se usa el toast único de esa pantalla.
    const [toastLocal, setToastLocal] = useState(null);

    const {
        enPrueba = [], nuevosMes = [], cargando = false,
        errorPrueba = '', errorNuevos = '', marcarEnviado,
    } = estado || {};

    useEffect(() => {
        if (!toastLocal) return undefined;
        const t = setTimeout(() => setToastLocal(null), 2600);
        return () => clearTimeout(t);
    }, [toastLocal]);

    const avisar = useCallback((texto, error = false) => {
        if (onToast) {
            onToast(texto, error);
            return;
        }
        setToastLocal({ texto, error });
    }, [onToast]);

    // Vista previa NO editable: el correo lo arma el backend con los datos reales
    // (la misma función que usa el envío, así lo que se ve es lo que sale).
    const abrirCorreo = async (alumno) => {
        setCorreo({ alumno, cargando: true, preview: null, error: '', enviando: false });
        try {
            const res = await api.get(
                `/api/v1/admin/alumnos-prueba/${alumno.id}/invitacion/preview`);
            setCorreo({ alumno, cargando: false, preview: res.data, error: '', enviando: false });
        } catch (err) {
            setCorreo({
                alumno, cargando: false, preview: null, enviando: false,
                error: err.response?.data?.detail || 'No se pudo armar el correo',
            });
        }
    };

    const enviarCorreo = async () => {
        if (!correo?.alumno || correo.enviando) return;
        setCorreo((c) => ({ ...c, enviando: true }));
        try {
            const { data } = await api.post(
                `/api/v1/admin/alumnos-prueba/${correo.alumno.id}/invitacion`);
            if (data?.exito) {
                // La fila pasa a "Correo enviado hace X" con la hora REAL del envío.
                marcarEnviado?.(correo.alumno.id, data.enviado_en);
                avisar(data.ya_enviado
                    ? 'Ese correo ya se había enviado hoy'
                    : `Correo enviado a ${correo.alumno.nombre}`);
            } else {
                avisar(data?.detalle_error || 'No se pudo enviar el correo', true);
            }
            setCorreo(null);
        } catch (err) {
            avisar(err.response?.data?.detail || 'No se pudo enviar el correo', true);
            setCorreo((c) => (c ? { ...c, enviando: false } : c));
        }
    };

    /** Tocar un nombre lleva a la FICHA del alumno (Historial), igual que el buscador. */
    const irAFicha = (alumnoId) => navigate(`/admin/alumnos/${alumnoId}/historial`);

    // Cuántos de los altas del mes YA compraron un plan: el mismo `convertido` que
    // publica `/admin/alumnos-nuevos` y que respalda la tarjeta "Convertidos".
    const convertidosMes = nuevosMes.filter((a) => a.convertido).length;

    // Último envío manual del alumno. El preview lo trae fresco; mientras carga
    // (o si el GET falla) se usa el que ya tenía la fila, para no perder el dato.
    // `enviado_hoy` lo decide el backend en días de CHILE: la hoja no ofrece un
    // envío que la dedupe diaria va a descartar.
    const ultimoEnvio = correo?.preview?.ultimo_envio
        || correo?.alumno?.ultimo_envio || null;
    const enviadoHoy = Boolean(correo?.preview?.enviado_hoy);
    const haceUltimoEnvio = textoHace(ultimoEnvio);

    return (
        <>
            <section className={`screen${embebido ? ' embebida' : ''}`}
                aria-label="Alumnos nuevos y en prueba"
                data-testid="pantalla-alumnos-prueba">
                <div className="s-head">
                    <button type="button" className="icon-btn" onClick={onVolver}
                        aria-label="Volver">←</button>
                    <div className="s-title">
                        <h3>Alumnos nuevos, convertidos y en prueba</h3>
                        <small>
                            {textoEnPrueba(enPrueba.length)}
                            {nuevosMes.length ? ` · ${nuevosMes.length} nuevos del mes` : ''}
                            {convertidosMes ? ` · ${convertidosMes} ya con plan` : ''}
                        </small>
                    </div>
                </div>

                <div className="results">
                    <h4 className="sec">En prueba</h4>
                    {errorPrueba ? (
                        <p className="empty-line" role="alert">⚠️ {errorPrueba}</p>
                    ) : cargando ? (
                        <p className="hint">Cargando…</p>
                    ) : enPrueba.length === 0 ? (
                        <p className="hint">Nadie está en prueba ahora mismo.</p>
                    ) : enPrueba.map((a) => {
                        const tono = tonoEstadoPrueba(a.estado);
                        return (
                            <article className="prow" key={a.id}>
                                <button type="button" className="pr-head"
                                    onClick={() => irAFicha(a.id)}>
                                    <span className="avatar">{iniciales(a.nombre)}</span>
                                    <span className="pr-name">{a.nombre}</span>
                                    <span className="pr-go" aria-hidden="true">›</span>
                                </button>
                                <p className={`pr-estado ${tono.clase}`}>
                                    <span aria-hidden="true">{tono.icono}</span>{' '}
                                    {textoEstadoPrueba(a.estado, a.dias_inscrito)}
                                </p>
                                <div className="pr-foot">
                                    <button type="button" className="btn soft small"
                                        onClick={() => abrirCorreo(a)}>
                                        Enviar correo
                                    </button>
                                    {/* Envío MANUAL registrado: la fila lo muestra. */}
                                    {a.ultimo_envio && (
                                        <span className="pr-note">
                                            Correo enviado {textoHace(a.ultimo_envio)}
                                        </span>
                                    )}
                                </div>
                            </article>
                        );
                    })}

                    <h4 className="sec">Alumnos nuevos de este mes</h4>
                    {errorNuevos ? (
                        <p className="empty-line" role="alert">⚠️ {errorNuevos}</p>
                    ) : cargando ? (
                        <p className="hint">Cargando…</p>
                    ) : nuevosMes.length === 0 ? (
                        <p className="hint">Todavía no hay altas este mes.</p>
                    ) : nuevosMes.map((a) => (
                        <button type="button" className="nrow" key={a.id}
                            onClick={() => irAFicha(a.id)}>
                            <span className="avatar">{iniciales(a.nombre)}</span>
                            <span className="n-name">{a.nombre}</span>
                            {a.convertido ? (
                                <span
                                    className="n-badge"
                                    title={`Ya compró un plan vigente${a.plan_nombre ? `: ${a.plan_nombre}` : ''}`}
                                >
                                    Convertido
                                </span>
                            ) : (
                                <span
                                    className="n-badge pendiente"
                                    title="Todavía no compró un plan pagado"
                                >
                                    Sin plan
                                </span>
                            )}
                            <span className="n-fecha">{textoAlta(a.fecha_alta)}</span>
                        </button>
                    ))}
                </div>
            </section>

            {/* Hoja inferior: vista previa del correo manual. */}
            {correo && (
                <>
                    {/* La hoja se abre DESDE esta pantalla completa (`.screen`,
                        z-index 50): sin `.sobre` quedaba DEBAJO y parecía que el
                        botón no hacía nada aunque el preview respondiera 200. */}
                    <div className="scrim sobre" onClick={() => setCorreo(null)} />
                    <section className="sheet sobre" aria-label="Vista previa del correo">
                        <div className="sheet-grab" />
                        <div className="sheet-head">
                            <div>
                                <h3>Vista previa del correo</h3>
                                <small>
                                    {correo.alumno?.nombre}
                                    {correo.preview?.destinatario ? ` · ${correo.preview.destinatario}` : ''}
                                </small>
                            </div>
                            <button type="button" className="close-x"
                                onClick={() => setCorreo(null)} aria-label="Cerrar">✕</button>
                        </div>
                        <div className="sheet-body">
                            {correo.cargando ? (
                                <p className="empty-line">Armando el correo…</p>
                            ) : (correo.error || !correo.preview) ? (
                                <p className="empty-line" role="alert">
                                    ⚠️ {correo.error || 'No se pudo armar el correo'}
                                </p>
                            ) : (
                                <>
                                    {/* Lo que ya pasó: se ve ANTES de confirmar (no
                                        después de que el backend lo descarte). */}
                                    {ultimoEnvio && haceUltimoEnvio && (
                                        <p className={`envio-previo${enviadoHoy ? ' hoy' : ''}`}>
                                            <b>{enviadoHoy ? 'Ya enviado hoy' : 'Último envío'}</b>
                                            <span>· {haceUltimoEnvio}</span>
                                            <em>{enviadoHoy
                                                ? 'No se manda dos veces el mismo correo el mismo día.'
                                                : 'Puedes reenviarlo: quedará como el envío de hoy.'}</em>
                                        </p>
                                    )}
                                    <div className="mail-meta">
                                        <small>Asunto</small>
                                        <b>{correo.preview.asunto}</b>
                                    </div>
                                    {/* El HTML lo renderiza el backend: se muestra tal cual,
                                        sin poder editarlo y sin ejecutar nada (sandbox=""). */}
                                    <iframe className="mail-doc" title="Vista previa del correo"
                                        sandbox="" srcDoc={correo.preview.html} />
                                    <p className="note">
                                        El mensaje lo arma Urban Box con los datos del alumno:
                                        se envía tal cual.
                                    </p>
                                </>
                            )}
                        </div>
                        <div className="sheet-foot una">
                            <button type="button" className="btn primary" onClick={enviarCorreo}
                                disabled={correo.cargando || Boolean(correo.error)
                                    || !correo.preview || correo.enviando || enviadoHoy}>
                                {correo.enviando ? 'Enviando…'
                                    : enviadoHoy ? 'Enviado hoy'
                                        : ultimoEnvio ? 'Enviar de nuevo' : 'Enviar'}
                            </button>
                        </div>
                    </section>
                </>
            )}

            {toastLocal && (
                <div className={`toast${toastLocal.error ? ' error' : ''}`} role="status">
                    {toastLocal.texto}
                </div>
            )}
        </>
    );
};

export default PanelAlumnosPrueba;
