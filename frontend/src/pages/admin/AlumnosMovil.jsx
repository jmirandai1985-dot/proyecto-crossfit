import React, { useState } from 'react';
import { ChevronRight, FileText, History, Pencil, Trash2, UserRound } from 'lucide-react';
import {
    alternarTarjeta, detalleTarjeta, estaAbierta, resumenTarjeta,
} from '../../utils/alumnosMovil';
// Estilos de las tarjetas. Van scopeados bajo `.ub-alu`, así que NO tocan la tabla de
// escritorio (>=768px): esa pantalla no cambia.
import './alumnosMovil.css';

/**
 * El padrón de alumnos como TARJETAS con acordeón (móvil <768px).
 *
 * POR QUÉ EXISTE: la tabla de 8 columnas no entra en un teléfono (scroll horizontal y las
 * acciones quedaban fuera de la pantalla). Acá la tarjeta cerrada muestra sólo lo que
 * decide —nombre, estado, plan y créditos— y al tocarla se abre EN EL LUGAR el contacto
 * (correo, teléfono, fecha de registro) y las 5 acciones de siempre.
 *
 * Sólo UNA tarjeta abierta a la vez: el id vive acá (no en cada tarjeta), así que abrir
 * otra cierra la anterior por construcción (`utils/alumnosMovil.alternarTarjeta`).
 *
 * Los modales y los manejadores NO viven acá: se avisa por callback y los sigue abriendo
 * `pages/admin/Alumnos.jsx`, donde ya viven el comprobante, la ficha, el historial, el
 * formulario y la baja. Así el rediseño móvil no agrega una segunda copia de ninguna
 * llamada al backend: recibe el mismo padrón, las mismas suscripciones y los mismos planes
 * que la tabla.
 *
 * Nada de tooltips al pasar el mouse (`title`): en un teléfono el hover no existe, así que
 * TODO lo que explica la pantalla es texto visible (regla del rediseño móvil).
 *
 * La pantalla de ESCRITORIO (>=768px) no monta este componente: sigue con su tabla.
 */
const AlumnosMovil = ({
    alumnos, suscripciones, planes,
    onVoucher, onFicha, onHistorial, onEditar, onEliminar,
}) => {
    const [abierta, setAbierta] = useState(null);

    if (!alumnos?.length) {
        return (
            <div className="ub-alu">
                <p className="ub-alu-vacio" data-testid="alumnos-movil-vacio">
                    No se encontraron alumnos
                </p>
            </div>
        );
    }

    return (
        <div className="ub-alu">
        <ul className="ub-alu-lista" data-testid="lista-alumnos-movil">
            {alumnos.map((alumno) => {
                const resumen = resumenTarjeta({ alumno, suscripciones, planes });
                const abierto = estaAbierta(abierta, alumno.id);
                const detalle = detalleTarjeta(alumno);
                return (
                    <li key={alumno.id}
                        className="ub-alu-card"
                        data-estado={resumen.estado.key}
                        data-abierta={abierto}
                        data-testid={`alumno-movil-${alumno.id}`}>
                        {/* Fila CERRADA. Es un <button> (no un div con onClick) para que
                            el teclado y los lectores de pantalla vean el acordeón; el
                            panel de abajo queda FUERA del botón (no se anidan botones). */}
                        <button
                            type="button"
                            className="ub-alu-cabecera"
                            onClick={() => setAbierta((prev) => alternarTarjeta(prev, alumno.id))}
                            aria-expanded={abierto}
                            aria-controls={`detalle-alumno-${alumno.id}`}
                            data-testid={`tarjeta-alumno-movil-${alumno.id}`}
                        >
                            <div className="ub-alu-titulo">
                                <div className="ub-alu-fila">
                                    <span className="ub-alu-nombre">{resumen.nombre}</span>
                                    <span className={`ub-alu-badge ${resumen.estado.clase}`}
                                        data-testid={`estado-alumno-movil-${alumno.id}`}>
                                        {resumen.estado.texto}
                                    </span>
                                </div>
                                <div className="ub-alu-fila ub-alu-plan">
                                    <span className="ub-alu-dato">
                                        <span className="ub-alu-etiqueta">Plan</span>
                                        <span className="ub-alu-valor"
                                            data-testid={`plan-alumno-movil-${alumno.id}`}>
                                            {resumen.plan.texto}
                                        </span>
                                    </span>
                                    <span className="ub-alu-dato">
                                        <span className="ub-alu-etiqueta">Créditos</span>
                                        <span className="ub-alu-valor"
                                            data-testid={`creditos-alumno-movil-${alumno.id}`}>
                                            {resumen.creditos.texto}
                                        </span>
                                    </span>
                                </div>
                            </div>
                            <ChevronRight
                                aria-hidden="true"
                                className={`ub-alu-chevron${abierto ? ' abierto' : ''}`}
                            />
                        </button>
                        {/* PANEL (abierto). Va FUERA del <button>: adentro no se pueden
                            anidar los botones de acción. Se calcula de los MISMOS datos
                            del alumno, así que colapsar no pierde nada. */}
                        {abierto && (
                            <div
                                id={`detalle-alumno-${alumno.id}`}
                                className="ub-alu-panel"
                                data-testid={`detalle-alumno-movil-${alumno.id}`}
                            >
                                <dl className="ub-alu-datos">
                                    <dt>Correo</dt><dd>{detalle.correo}</dd>
                                    <dt>Teléfono</dt><dd>{detalle.telefono}</dd>
                                    <dt>Fecha Registro</dt><dd>{detalle.registro}</dd>
                                </dl>
                                <div className="ub-alu-acciones">
                                    <button type="button" className="ub-alu-btn voucher"
                                        onClick={() => onVoucher(alumno)}
                                        aria-label={`Voucher de ${resumen.nombre}`}
                                        data-testid={`btn-voucher-movil-${alumno.id}`}>
                                        <FileText aria-hidden="true" /> Voucher
                                    </button>
                                    <button type="button" className="ub-alu-btn ficha"
                                        onClick={() => onFicha(alumno)}
                                        aria-label={`Ficha de ${resumen.nombre}`}
                                        data-testid={`btn-ficha-movil-${alumno.id}`}>
                                        <UserRound aria-hidden="true" /> Ficha
                                    </button>
                                    <button type="button" className="ub-alu-btn historial"
                                        onClick={() => onHistorial(alumno)}
                                        aria-label={`Historial de ${resumen.nombre}`}
                                        data-testid={`btn-historial-movil-${alumno.id}`}>
                                        <History aria-hidden="true" /> Historial
                                    </button>
                                    <button type="button" className="ub-alu-btn editar"
                                        onClick={() => onEditar(alumno)}
                                        aria-label={`Editar a ${resumen.nombre}`}
                                        data-testid={`btn-editar-movil-${alumno.id}`}>
                                        <Pencil aria-hidden="true" /> Editar
                                    </button>
                                    <button type="button" className="ub-alu-btn eliminar"
                                        onClick={() => onEliminar(alumno)}
                                        aria-label={`Eliminar a ${resumen.nombre}`}
                                        data-testid={`btn-eliminar-movil-${alumno.id}`}>
                                        <Trash2 aria-hidden="true" /> Eliminar
                                    </button>
                                </div>
                            </div>
                        )}
                    </li>
                );
            })}
        </ul>
        </div>
    );
};

export default AlumnosMovil;

